"""Pivot kontov iz IR/PR knjižb (debet/kredit) za zavihek KONTI."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Sequence

from trops_studio.ddvo_calc import ir_row_to_kir, pr_row_to_kpr
from trops_studio.journal_preview import preview_ir_journals, preview_pr_journals
from trops_studio.money import decimal_value, is_nonzero, money_text, normalize_text

ZERO = Decimal("0.00")


def _ddvo_codes_for_evidence(book: str, row_map: Mapping[str, Any]) -> frozenset[str]:
    """DDV-O polja, v katera vrstica (KIR/KPR) prispeva znesek <> 0."""
    try:
        from kirkpr_minimax_core import ddvo_codes_for_field  # type: ignore
    except Exception:
        from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path

        ensure_kirkpr_on_path()
        from kirkpr_minimax_core import ddvo_codes_for_field  # type: ignore

    codes: set[str] = set()
    for key, value in row_map.items():
        field = str(key or "").strip().upper()
        # samo zneskovna P-polja (P7…), ne P2/P3/P5 (datumi / nazivi)
        if not field.startswith("P") or len(field) < 2:
            continue
        if not field[1].isdigit():
            continue
        try:
            if not is_nonzero(value):
                continue
        except Exception:
            continue
        for code in ddvo_codes_for_field(book, field):
            codes.add(str(code))
    return frozenset(codes)


@dataclass
class PivotLine:
    group: str
    konto: str
    party: str
    document: str
    tip: str
    kind: str  # IR | PR
    doc_id: int
    debet: Decimal
    kredit: Decimal
    opis: str = ""
    ddvo_codes: frozenset[str] = field(default_factory=frozenset)

    def search_chunks(self) -> list[str]:
        return [
            self.group,
            self.konto,
            self.party,
            self.document,
            self.tip,
            self.kind,
            self.opis,
            str(self.doc_id),
            *sorted(self.ddvo_codes),
            money_text(self.debet),
            money_text(self.kredit),
        ]


@dataclass
class PivotNode:
    key: str
    label: str
    level: str  # group | konto | party | document | tip
    debet: Decimal = ZERO
    kredit: Decimal = ZERO
    children: list[PivotNode] = field(default_factory=list)
    open: bool = True
    kind: str = ""
    doc_id: int | None = None
    ddvo_codes: frozenset[str] = field(default_factory=frozenset)


def _konto_group(code: str) -> str:
    text = normalize_text(code)
    if not text:
        return "—"
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 2:
        return digits[:2]
    return text[:2].upper() if len(text) >= 2 else text


def collect_pivot_lines(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
) -> list[PivotLine]:
    """Vse knjižne vrstice obdobja → listi za pivot (+ DDV-O kode / doc_id)."""
    out: list[PivotLine] = []
    for row in ir_rows:
        doc_id = int(row.get("id") or 0)
        if not doc_id:
            continue
        party = normalize_text(row.get("party_name")) or "—"
        document = normalize_text(row.get("document_no")) or "—"
        tip = normalize_text(row.get("book")) or "IR"
        codes = _ddvo_codes_for_evidence("IR", ir_row_to_kir(row))
        for line in preview_ir_journals(row):
            konto = normalize_text(line.get("konto")) or "—"
            debet = decimal_value(line.get("debet"))
            kredit = decimal_value(line.get("kredit"))
            if not is_nonzero(debet) and not is_nonzero(kredit):
                continue
            out.append(
                PivotLine(
                    group=_konto_group(konto),
                    konto=konto,
                    party=party,
                    document=document,
                    tip=tip,
                    kind="IR",
                    doc_id=doc_id,
                    debet=debet,
                    kredit=kredit,
                    opis=normalize_text(line.get("opis")),
                    ddvo_codes=codes,
                )
            )
    for row in pr_rows:
        doc_id = int(row.get("id") or 0)
        if not doc_id:
            continue
        party = normalize_text(row.get("supplier_name")) or "—"
        document = normalize_text(row.get("document_no")) or "—"
        tip = "PR"
        codes = _ddvo_codes_for_evidence("PR", pr_row_to_kpr(row))
        for line in preview_pr_journals(row):
            konto = normalize_text(line.get("konto")) or "—"
            debet = decimal_value(line.get("debet"))
            kredit = decimal_value(line.get("kredit"))
            if not is_nonzero(debet) and not is_nonzero(kredit):
                continue
            out.append(
                PivotLine(
                    group=_konto_group(konto),
                    konto=konto,
                    party=party,
                    document=document,
                    tip=tip,
                    kind="PR",
                    doc_id=doc_id,
                    debet=debet,
                    kredit=kredit,
                    opis=normalize_text(line.get("opis")),
                    ddvo_codes=codes,
                )
            )
    return out


def _add_amount(node: PivotNode, debet: Decimal, kredit: Decimal) -> None:
    node.debet += debet
    node.kredit += kredit


def _merge_codes(node: PivotNode, codes: frozenset[str]) -> None:
    if codes:
        node.ddvo_codes = frozenset(set(node.ddvo_codes) | set(codes))


def _child_map(node: PivotNode) -> dict[str, PivotNode]:
    return {c.key: c for c in node.children}


def build_pivot_tree(lines: Sequence[PivotLine]) -> tuple[list[PivotNode], Decimal, Decimal]:
    """
    Hierarhija: skupina (2) → konto → stranka → listina → tip (IR knjiga / PR).
    """
    roots: dict[str, PivotNode] = {}
    total_d = ZERO
    total_k = ZERO

    for line in lines:
        total_d += line.debet
        total_k += line.kredit

        g = roots.get(line.group)
        if g is None:
            g = PivotNode(key=line.group, label=line.group, level="group", open=True)
            roots[line.group] = g
        _add_amount(g, line.debet, line.kredit)
        _merge_codes(g, line.ddvo_codes)

        g_kids = _child_map(g)
        k = g_kids.get(line.konto)
        if k is None:
            k = PivotNode(key=line.konto, label=line.konto, level="konto", open=False)
            g.children.append(k)
        _add_amount(k, line.debet, line.kredit)
        _merge_codes(k, line.ddvo_codes)

        k_kids = _child_map(k)
        p_key = line.party.casefold()
        p = k_kids.get(p_key)
        if p is None:
            p = PivotNode(key=p_key, label=line.party, level="party", open=False)
            k.children.append(p)
        _add_amount(p, line.debet, line.kredit)
        _merge_codes(p, line.ddvo_codes)

        p_kids = _child_map(p)
        d_key = f"{line.kind}:{line.doc_id}"
        d = p_kids.get(d_key)
        if d is None:
            d = PivotNode(
                key=d_key,
                label=line.document,
                level="document",
                open=False,
                kind=line.kind,
                doc_id=line.doc_id,
            )
            p.children.append(d)
        _add_amount(d, line.debet, line.kredit)
        _merge_codes(d, line.ddvo_codes)
        d.kind = line.kind
        d.doc_id = line.doc_id

        d_kids = _child_map(d)
        t_key = f"{line.kind}:{line.tip}".casefold()
        t = d_kids.get(t_key)
        if t is None:
            label = line.tip if line.kind == "IR" else "PR"
            t = PivotNode(
                key=t_key,
                label=label,
                level="tip",
                open=False,
                kind=line.kind,
                doc_id=line.doc_id,
            )
            d.children.append(t)
        _add_amount(t, line.debet, line.kredit)
        _merge_codes(t, line.ddvo_codes)
        t.kind = line.kind
        t.doc_id = line.doc_id

    def _sort(nodes: list[PivotNode]) -> None:
        nodes.sort(key=lambda n: (n.label.casefold(), n.key))
        for child in nodes:
            _sort(child.children)

    root_list = list(roots.values())
    _sort(root_list)
    return root_list, total_d, total_k


def filter_pivot_lines(
    lines: Sequence[PivotLine],
    *,
    tokens: Sequence[str],
    nonzero_only: bool,
    ddvo_codes: set[str] | None = None,
) -> list[PivotLine]:
    """
    ddvo_codes:
      None / prazno / vsa polja → brez filtra po DDV-O
      sicer samo listine, ki prispevajo v označenih poljih.
    """
    from trops_studio.ui.search import haystack_matches

    out: list[PivotLine] = []
    for line in lines:
        if nonzero_only and not (is_nonzero(line.debet) or is_nonzero(line.kredit)):
            continue
        if ddvo_codes is not None and ddvo_codes:
            # 51/52 nimata vira — če so med označenimi, ne zožita filtra
            active = {c for c in ddvo_codes if c not in {"51", "52"}}
            if active and not (line.ddvo_codes & active):
                continue
        if tokens and not haystack_matches(tokens, line.search_chunks()):
            continue
        out.append(line)
    return out
