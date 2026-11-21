"""Integra: prenesi kisanal dokumente v Studio IR/PR (kot Vasco pri Projetu).

Trops → Minimax skupine po AnalCtrl:
  IR  = 100* (Paragoni) + 120* (Fakture)
  PR  = 220* (prejeti)
  BD  = 110* (bančni izpiski) — Minimax BD
  OP  = BOD* (plače) — že knjiženo v Minimax kot OP; NE uvažamo iz SQL
  DOP = podobni dohodki (če so v SQL) — Minimax DOP; NE uvažamo
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio.account_choices import (
    coerce_minimax_bookable_account,
    default_minimax_org_id,
)
from trops_studio.accounts import allocate_pr_accounts, resolve_ir_account, resolve_pr_accounts
from trops_studio.ir_list_view import apply_ir_eu_sale
from trops_studio.config import DEFAULT_IR_REVENUE_ACCOUNT, DEFAULT_PR_EXPENSE_ACCOUNT
from trops_studio.db import Database
from trops_studio.pr_list_view import apply_pr_si_vat_flag
from trops_studio.money import (
    CENT,
    ZERO,
    decimal_value,
    ensure_eu_vat_id,
    normalize_text,
    normalize_vat_id,
    parse_date,
    tax_digits,
)

KISANAL_NOTE_PREFIX = "kisanal:"


# Posamezne serije knjižb (AnalCtrl predpona) → Minimax skupina.
# BD ≠ BOD: banka je 110→BD; plače BOD→OP (že v MM, ne uvoz).
KNJIGA_SERIES: tuple[tuple[str, str, str], ...] = (
    ("110", "BD", "110* bančni izpiski → Minimax BD"),
    ("BOD", "OP", "BOD* plače → Minimax OP (že knjiženo, ne uvažamo)"),
    ("DOP", "DOP", "DOP* dohodki → Minimax DOP (ne uvažamo)"),
    ("100", "IR", "100* Paragoni"),
    ("120", "IR", "120* Fakture"),
    ("220", "PR", "220* prejeti računi"),
    ("OST", "OST", "Druge knjižbe"),
)

# Skupine, ki jih ne prenašamo v IR/PR / ne uvažamo v Minimax iz SQL.
SKIP_IMPORT_GROUPS: frozenset[str] = frozenset({"OP", "DOP"})


def knjiga_series(anal_ctrl: str, anal_vrkn: str = "") -> str:
    """Posamezna serija: 110 / BOD / DOP / 100 / 120 / 220 / OST."""
    ctrl = (anal_ctrl or "").strip().upper()
    # BOD pred morebitnim "BD…" — BD ≠ BOD
    if ctrl.startswith("BOD"):
        return "BOD"
    if ctrl.startswith("DOP"):
        return "DOP"
    if ctrl.startswith("110"):
        return "110"
    if ctrl.startswith("100"):
        return "100"
    if ctrl.startswith("120"):
        return "120"
    if ctrl.startswith("220"):
        return "220"
    vrkn = (anal_vrkn or "").strip().upper()
    if vrkn in {"BOD", "DOP", "110", "100", "120", "220"}:
        return vrkn
    if vrkn == "BD":
        return "110"
    if vrkn == "OP":
        return "BOD"
    if vrkn == "IR":
        return "100"
    if vrkn == "PR":
        return "220"
    return "OST"


def knjiga_group(anal_ctrl: str, anal_vrkn: str = "") -> str:
    """Minimax skupina: BD / OP / DOP / IR / PR / OST."""
    series = knjiga_series(anal_ctrl, anal_vrkn)
    for code, group, _tip in KNJIGA_SERIES:
        if code == series:
            return group
    return "OST"


def is_importable_kisanal(anal_ctrl: str, anal_vrkn: str = "") -> bool:
    """False za plače (OP/BOD) in DOP — že v Minimaxu, ne uvažamo iz SQL."""
    return knjiga_group(anal_ctrl, anal_vrkn) not in SKIP_IMPORT_GROUPS


def kisanal_marker(anal_ctrl: str) -> str:
    return f"{KISANAL_NOTE_PREFIX}{(anal_ctrl or '').strip()}"


def transferred_ctrls_from_rows(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """AnalCtrl, ki so že v ir_rows/pr_rows (raw_json ali legacy notes kisanal:)."""
    out: set[str] = set()
    for row in rows:
        raw = row.get("raw_json")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, Mapping):
            ctrl = normalize_text(
                data.get("anal_ctrl") or data.get("kisanal_ctrl") or data.get("kisanal_marker")
            )
            if ctrl.startswith(KISANAL_NOTE_PREFIX):
                ctrl = ctrl[len(KISANAL_NOTE_PREFIX) :].strip()
            if ctrl:
                out.add(ctrl)
                continue
        notes = str(row.get("notes") or "")
        if notes.startswith(KISANAL_NOTE_PREFIX):
            out.add(notes[len(KISANAL_NOTE_PREFIX) :].strip())
    return {c for c in out if c}


def _konto_base(akon: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", (akon or "").strip().upper())


def _is_vat_out(akon: str) -> bool:
    b = _konto_base(akon)
    return b.startswith("260") or b.startswith("262")


def _is_vat_in(akon: str) -> bool:
    b = _konto_base(akon)
    return b.startswith("160")


def _is_revenue(akon: str) -> bool:
    b = _konto_base(akon)
    return b.startswith("7")


def _is_cash_or_card(akon: str) -> bool:
    """Paragoni: gotovina 1000 / kartice 1006 (→ MM 1650)."""
    b = _konto_base(akon)
    return b.startswith("100")


def paragon_payment_account(
    lines: Sequence[Mapping[str, Any]],
    *,
    db: Database | None = None,
    org_id: str = "",
) -> str:
    """Iz kisanal vrstic 100*: 1000 gotovina ali 1650 kartice (ne 1200)."""
    cash = ZERO
    card = ZERO
    for line in lines:
        akon = normalize_text(line.get("anal_akon") or line.get("anal_akon_old"))
        if not _is_cash_or_card(akon):
            continue
        amt = decimal_value(line.get("anal_debt")) - decimal_value(line.get("anal_krdt"))
        if amt <= 0:
            continue
        base = _konto_base(akon)
        tekst = normalize_text(line.get("anal_anal")).upper()
        # 1006 kartice; 1000 čista blagajna / gotovina
        if (
            base.startswith("1006")
            or base.startswith("1001")
            or "KART" in tekst
            or "EUROCARD" in tekst
            or "MASTERCARD" in tekst
            or "VISA" in tekst
        ):
            card += amt
        elif base.startswith("1000") or "GOTOVIN" in tekst or "BLAGAJN" in tekst:
            cash += amt
        else:
            card += amt
    if card > cash:
        code = "1650"
    else:
        code = "1000"
    if db is not None:
        return coerce_minimax_bookable_account(db, org_id, code, fallback=code)
    return code


def integra_vat_id(raw_vat: str, *, country: str = "SI") -> str:
    """Integra: davčna brez predpone → SI… / AT… (ne pusti golih 8 mest)."""
    vat = normalize_vat_id(raw_vat)
    if not vat:
        return ""
    cc = normalize_text(country)[:2].upper() or "SI"
    if cc in {"SLO", "SVN"}:
        cc = "SI"
    return ensure_eu_vat_id(vat, country=cc) or vat


def _is_expense(akon: str) -> bool:
    """Domači odhodek (4xxx / 66xx) — ne 65xx EU pridobitve."""
    b = _konto_base(akon)
    return b.startswith("4") or b.startswith("66")


def _base_from_vat(vat: Decimal, rate: str) -> Decimal:
    """Osnova iz zneska DDV (22 / 9,5 / 5)."""
    amount = decimal_value(vat)
    if not amount:
        return ZERO
    divisor = {"22": Decimal("0.22"), "95": Decimal("0.095"), "5": Decimal("0.05")}.get(rate)
    if not divisor:
        return ZERO
    return (amount / divisor).quantize(CENT)


def split_taxable_and_exempt(
    expense: Decimal,
    *,
    vat_22: Decimal = ZERO,
    vat_95: Decimal = ZERO,
    vat_5: Decimal = ZERO,
    eu_goods: Decimal = ZERO,
    eu_services: Decimal = ZERO,
    f76a: Decimal = ZERO,
) -> dict[str, Decimal]:
    """Loči obdavčeno (P8→31) in oproščeno (P14→33).

    EU / 76.a osnova ostane v P10/P11/P9 — ne gre v 31 ali 33.
    Brez vstopnega DDV gre domači odhodek v oproščeno (33).
    Z DDV: obdavčena osnova iz DDV; presežek odhodka → 33.
    """
    expense = decimal_value(expense)
    v22 = decimal_value(vat_22)
    v95 = decimal_value(vat_95)
    v5 = decimal_value(vat_5)
    eu_g = decimal_value(eu_goods)
    eu_s = decimal_value(eu_services)
    f76 = decimal_value(f76a)
    has_eu = bool(eu_g or eu_s or f76)

    # EU/76.a: osnova + DDV sta v P9–P11 / P18 — ne v P8/31.
    # Domači odhodek na isti listini (redko) → oproščeno, ne obdavčeno iz EU DDV.
    if has_eu:
        eu_base = eu_g + eu_s + f76
        # pool pogosto = napačno prestavljena EU osnova; te ne damo v 33.
        domestic = expense - eu_base
        if domestic < CENT:
            domestic = ZERO
        return {
            "net_taxable": ZERO,
            "base_22": ZERO,
            "base_95": ZERO,
            "base_5": ZERO,
            "exempt_on": domestic if domestic > 0 else ZERO,
        }

    base_22 = _base_from_vat(v22, "22")
    base_95 = _base_from_vat(v95, "95")
    base_5 = _base_from_vat(v5, "5")
    taxable = base_22 + base_95 + base_5

    if not v22 and not v95 and not v5:
        return {
            "net_taxable": ZERO,
            "base_22": ZERO,
            "base_95": ZERO,
            "base_5": ZERO,
            "exempt_on": expense if expense > 0 else ZERO,
        }

    if expense <= 0:
        return {
            "net_taxable": taxable,
            "base_22": base_22,
            "base_95": base_95,
            "base_5": base_5,
            "exempt_on": ZERO,
        }

    if taxable >= expense:
        return {
            "net_taxable": expense,
            "base_22": base_22 if v22 else expense,
            "base_95": base_95 if v95 else ZERO,
            "base_5": base_5 if v5 else ZERO,
            "exempt_on": ZERO,
        }

    exempt = (expense - taxable).quantize(CENT)
    return {
        "net_taxable": taxable,
        "base_22": base_22,
        "base_95": base_95,
        "base_5": base_5,
        "exempt_on": exempt if exempt > 0 else ZERO,
    }


def reclassify_pr_exempt_to_field33(db: Database) -> dict[str, Any]:
    """Popravi obstoječe PR: presežek / nabave brez DDV → exempt_on (DDV-O 33)."""
    updated = 0
    moved = ZERO
    for row in db.list_pr():
        existing_net = decimal_value(row.get("net_taxable"))
        existing_exempt = decimal_value(row.get("exempt_on"))
        pool = existing_net + existing_exempt
        split = split_taxable_and_exempt(
            pool,
            vat_22=decimal_value(row.get("vat_22")),
            vat_95=decimal_value(row.get("vat_95")),
            vat_5=decimal_value(row.get("vat_5")),
            eu_goods=decimal_value(row.get("eu_goods")),
            eu_services=decimal_value(row.get("eu_services")),
            f76a=decimal_value(row.get("f76a")),
        )
        new_net = split["net_taxable"]
        new_ex = split["exempt_on"]
        if new_net == existing_net and new_ex == existing_exempt:
            continue
        payload = dict(row)
        payload["net_taxable"] = new_net
        payload["exempt_on"] = new_ex
        payload["base_22"] = split["base_22"]
        payload["base_95"] = split["base_95"]
        payload["base_5"] = split["base_5"]
        payload.update(allocate_pr_accounts(payload))
        db.upsert_pr(payload, row_id=int(row["id"]))
        updated += 1
        moved += (existing_net - new_net).copy_abs()
    return {"updated": updated, "moved": moved}


def _is_payable(akon: str) -> bool:
    b = _konto_base(akon)
    return b.startswith("220") or b.startswith("221") or b.startswith("222")


def _is_eu_acquisition(akon: str, anal_text: str = "") -> bool:
    """Pridobitve blaga/storitev v EU (npr. 6526) — ne DDV 160/260."""
    if _is_vat_in(akon) or _is_vat_out(akon) or _is_payable(akon):
        return False
    b = _konto_base(akon)
    text = (anal_text or "").casefold()
    if b.startswith("6526") or b.startswith("6527"):
        return True
    if b.startswith("65") and ("eu" in text or "pridobitv" in text):
        return True
    return False


def _is_eu_vat_account(akon: str) -> bool:
    """1600-8 / 2600-8 = DDV pridobitve EU (samoobdavčitev)."""
    raw = (akon or "").strip().upper()
    return raw.endswith("-8") or raw.endswith(".8")


def _vat_bucket(akon: str) -> str:
    """'22' | '95' | '5' po sufiksu konta."""
    raw = (akon or "").strip().upper()
    if raw.endswith("-1") or raw.endswith(".1"):
        return "95"
    if raw.endswith("-4") or raw.endswith("-5") or raw.endswith(".5"):
        return "5"
    return "22"


def _parse_iso(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_date(text[:10])
    except Exception:
        return None


def _load_popa(
    conn: sqlite3.Connection,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Vrni (vat_by_ctrl, name_by_ctrl, country_by_ctrl) iz tabele popa."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='popa'"
    ).fetchone()
    if not exists:
        return {}, {}, {}
    vat_map: dict[str, str] = {}
    name_map: dict[str, str] = {}
    country_map: dict[str, str] = {}
    for row in conn.execute(
        "SELECT popa_ctrl, popa_dast, popa_mast, popa_ime, popa_nazv, popa_drza FROM popa"
    ):
        ctrl = normalize_text(row[0])
        if not ctrl:
            continue
        name = normalize_text(row[3] or row[4])
        if name:
            name_map[ctrl] = name
        drza = normalize_text(row[5]).upper()
        if drza in {"SLO", "SVN", "SI", "SLOVENIJA", "SLOVENIA"}:
            cc = "SI"
        else:
            cc = drza[:2]
        # POPA ima včasih SLO tudi za tuje — ime prepiše
        name_u = name.upper()
        if "ITALY" in name_u or "ITALI" in name_u or "ITALIA" in name_u:
            cc = "IT"
        elif any(x in name_u for x in ("GERMANY", "DEUTSCH", "AUSTRIA", "ÖSTER", "OSTER")):
            if "GERMANY" in name_u or "DEUTSCH" in name_u:
                cc = "DE"
            elif "AUSTRIA" in name_u or "OSTER" in name_u or "ÖSTER" in name_u:
                cc = "AT"
        if cc:
            country_map[ctrl] = cc
        raw_vat = normalize_text(row[1] or row[2] or "")
        vat = integra_vat_id(raw_vat, country=cc or "SI")
        if vat:
            vat_map[ctrl] = vat
    return vat_map, name_map, country_map


@dataclass
class IntegraIrPrResult:
    ir: int = 0
    pr: int = 0
    skipped: int = 0
    updated: int = 0
    batch_id: int = 0
    message: str = ""
    ir_ctrls: list[str] = field(default_factory=list)
    pr_ctrls: list[str] = field(default_factory=list)


def _find_existing_id(rows: Sequence[Mapping[str, Any]], anal_ctrl: str) -> int | None:
    marker = kisanal_marker(anal_ctrl)
    ctrl = normalize_text(anal_ctrl)
    for row in rows:
        if str(row.get("notes") or "").startswith(marker):
            return int(row["id"])
        raw = row.get("raw_json")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, Mapping):
            raw_ctrl = normalize_text(data.get("anal_ctrl") or data.get("kisanal_ctrl"))
            if raw_ctrl.startswith(KISANAL_NOTE_PREFIX):
                raw_ctrl = raw_ctrl[len(KISANAL_NOTE_PREFIX) :].strip()
            if raw_ctrl == ctrl:
                return int(row["id"])
        # Po lepem Opisu (brez kisanal:) — ujemanje po listini / AnalCtrl
        doc = normalize_text(row.get("document_no"))
        if ctrl.startswith("100") and doc == ctrl:
            return int(row["id"])
        if doc and ctrl.startswith("120") and doc.upper().startswith("DR"):
            # DR00024 ↔ 1200024 (zadnji del)
            try:
                if int(doc[2:]) == int(ctrl[3:]):
                    return int(row["id"])
            except (TypeError, ValueError):
                pass
    return None


def _group_lines(lines: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lines:
        ctrl = normalize_text(row.get("anal_ctrl"))
        if ctrl:
            groups[ctrl].append(dict(row))
    return groups


def _build_ir_from_group(
    ctrl: str,
    lines: Sequence[Mapping[str, Any]],
    *,
    db: Database,
    popa_vat: Mapping[str, str],
    popa_name: Mapping[str, str],
    seq: int,
    org_id: str = "",
    popa_country: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    first = lines[0]
    doc_date = _parse_iso(first.get("anal_ddok")) or _parse_iso(first.get("anal_ddur"))
    book_date = _parse_iso(first.get("anal_dknj")) or doc_date
    ddv_date = _parse_iso(first.get("anal_ddur")) or doc_date

    base_22 = Decimal("0")
    vat_22 = Decimal("0")
    base_95 = Decimal("0")
    vat_95 = Decimal("0")
    revenue_account = ""
    party_name = ""
    part_code = ""
    document_no = ""

    for line in lines:
        akon = normalize_text(line.get("anal_akon") or line.get("anal_akon_old"))
        debt = decimal_value(line.get("anal_debt"))
        krdt = decimal_value(line.get("anal_krdt"))
        if not party_name:
            party_name = normalize_text(line.get("anal_pime"))
        if not part_code:
            part_code = normalize_text(line.get("anal_part"))
        if not document_no:
            document_no = normalize_text(line.get("anal_doku"))

        if _is_revenue(akon):
            base_22 += krdt - debt
            if not revenue_account and (krdt or debt):
                revenue_account = akon
        elif _is_vat_out(akon):
            bucket = _vat_bucket(akon)
            amt = krdt - debt
            if bucket == "95":
                vat_95 += amt
                # osnova ni na DDV vrstici — ostane na prihodku
            else:
                vat_22 += amt

    # Če so prihodki pomešani 22/9.5 brez ločitve, vse v 22
    net = base_22 + base_95
    total = net + vat_22 + vat_95
    if total == 0 and net == 0:
        # fallback: saldo razen plačilnih kontov 100/110/120
        for line in lines:
            akon = normalize_text(line.get("anal_akon") or line.get("anal_akon_old"))
            b = _konto_base(akon)
            if b.startswith("100") or b.startswith("110") or b.startswith("120"):
                continue
            if _is_vat_out(akon):
                continue
            net += decimal_value(line.get("anal_krdt")) - decimal_value(line.get("anal_debt"))
        base_22 = net
        total = net + vat_22 + vat_95

    if net == 0 and vat_22 == 0 and vat_95 == 0:
        return None

    countries = popa_country or {}
    cc = countries.get(part_code, "SI")
    vat_id = integra_vat_id(popa_vat.get(part_code, ""), country=cc)
    if not party_name or re.fullmatch(r"\d+", party_name or ""):
        party_name = popa_name.get(part_code, "") or party_name

    is_paragon = ctrl.startswith("100")
    # Paragoni: listina = AnalCtrl (100****). anal_doku je pogosto pokvarjen (0001100, 100003).
    if is_paragon:
        document_no = ctrl
    else:
        document_no = document_no or ctrl
    payment_account = ""
    if is_paragon:
        payment_account = paragon_payment_account(lines, db=db, org_id=org_id)
        if not party_name:
            party_name = (
                "Paragoni / kartice" if payment_account == "1650" else "Paragoni / gotovina"
            )
    elif not party_name:
        party_name = "Kupec"

    book = "Paragoni" if is_paragon else "Fakture"
    # Opis v UI: čista listina, ne kisanal:#IR…
    nice_notes = document_no if is_paragon else f"Izdani račun {document_no}"
    # Trops 7622 ni v Minimax — samo knjižljivi konti iz API plana.
    resolved = resolve_ir_account(db, vat_id=vat_id, name=party_name, org_id=org_id)
    account = coerce_minimax_bookable_account(
        db,
        org_id,
        revenue_account or resolved,
        fallback=resolved or DEFAULT_IR_REVENUE_ACCOUNT,
    )

    payload = {
        "book": book,
        "seq": seq,
        "booking_date": book_date or ddv_date,
        "document_date": doc_date or book_date,
        "document_no": document_no or ctrl,
        "party_name": party_name,
        "vat_id": vat_id,
        "net": net,
        "base_22": base_22,
        "vat_22": vat_22,
        "base_95": base_95,
        "vat_95": vat_95,
        "eu_goods": Decimal("0"),
        "eu_services": Decimal("0"),
        "reverse_charge": Decimal("0"),
        "excluded": Decimal("0"),
        "exempt": Decimal("0"),
        "total": total,
        "account": account,
        "status": "OSNUTEK",
        "notes": nice_notes,
        "raw_json": {
            "source": "kisanal",
            "anal_ctrl": ctrl,
            "kisanal_marker": kisanal_marker(ctrl),
            "lines": len(lines),
            "anal_part": part_code,
            "payment_account": payment_account,
            "integra_paragon": is_paragon,
        },
    }
    return apply_ir_eu_sale(payload)


def _build_pr_from_group(
    ctrl: str,
    lines: Sequence[Mapping[str, Any]],
    *,
    db: Database,
    popa_vat: Mapping[str, str],
    popa_name: Mapping[str, str],
    seq: int,
    org_id: str = "",
    popa_country: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    first = lines[0]
    doc_date = _parse_iso(first.get("anal_ddok")) or _parse_iso(first.get("anal_ddur"))
    book_date = _parse_iso(first.get("anal_dknj")) or doc_date
    recv_date = _parse_iso(first.get("anal_ddur")) or doc_date

    base_22 = Decimal("0")
    vat_22 = Decimal("0")
    base_95 = Decimal("0")
    vat_95 = Decimal("0")
    eu_goods = Decimal("0")
    eu_services = Decimal("0")
    expense_account = ""
    eu_account = ""
    placilo = ""
    supplier = ""
    part_code = ""
    document_no = ""
    is_eu = False

    for line in lines:
        akon = normalize_text(line.get("anal_akon") or line.get("anal_akon_old"))
        anal_txt = normalize_text(line.get("anal_anal"))
        debt = decimal_value(line.get("anal_debt"))
        krdt = decimal_value(line.get("anal_krdt"))
        if not supplier:
            supplier = normalize_text(line.get("anal_pime"))
        if not part_code:
            part_code = normalize_text(line.get("anal_part"))
        if not document_no:
            document_no = normalize_text(line.get("anal_doku")) or ctrl

        if _is_payable(akon):
            if not placilo:
                placilo = akon.split("-")[0] if akon else "2200"
            if _konto_base(akon).startswith("222") or _konto_base(akon).startswith("221"):
                is_eu = True
            continue
        if _is_eu_acquisition(akon, anal_txt):
            eu_goods += debt - krdt
            is_eu = True
            if not eu_account and (debt or krdt):
                eu_account = akon
            continue
        if _is_vat_out(akon):
            # 2600-8 pri EU = samoobdavčitev (zrcali 1600) — ne prištej dvakrat
            if _is_eu_vat_account(akon):
                is_eu = True
            continue
        if _is_vat_in(akon):
            if _is_eu_vat_account(akon):
                is_eu = True
            bucket = _vat_bucket(akon)
            amt = debt - krdt
            if bucket == "95":
                vat_95 += amt
            else:
                vat_22 += amt
            continue
        if _is_expense(akon):
            base_22 += debt - krdt
            if not expense_account and (debt or krdt):
                expense_account = akon

    expense_total = base_22 + base_95
    if (
        expense_total == 0
        and eu_goods == 0
        and eu_services == 0
        and vat_22 == 0
        and vat_95 == 0
    ):
        # Plačilo obveznosti (2200↔100/110) — ni nabava; ostane za Vse knjižbe.
        return None

    if not supplier or re.fullmatch(r"\d+", supplier or ""):
        supplier = popa_name.get(part_code, "") or supplier
    countries = popa_country or {}
    cc = countries.get(part_code, "")
    if is_eu and not cc:
        if "ITALY" in (supplier or "").upper() or "ITALI" in (supplier or "").upper():
            cc = "IT"
        else:
            cc = "EU"
    if not cc:
        cc = "SI"
    vat_id = integra_vat_id(popa_vat.get(part_code, ""), country=cc)

    accounts = resolve_pr_accounts(db, vat_id=vat_id, name=supplier)
    # Pri EU ohrani kisanal plačilo (2220/2211), ne prepisuj slepo.
    if is_eu:
        default_placilo = placilo or "2211"
        supplier_kind = "EU"
        odhodek01 = expense_account or ""
        odhodek10 = eu_account or accounts.get("odhodek10") or "6500"
        self_assessment = True
        vat_deductible = True
    else:
        default_placilo = placilo or accounts.get("placilo") or "2200"
        supplier_kind = "SI"
        odhodek01 = expense_account or accounts.get("odhodek01") or ""
        odhodek10 = ""
        self_assessment = accounts.get("self_assessment")
        vat_deductible = accounts.get("vat_deductible")

    if odhodek01:
        odhodek01 = coerce_minimax_bookable_account(
            db, org_id, odhodek01, fallback=DEFAULT_PR_EXPENSE_ACCOUNT
        )
    if odhodek10:
        odhodek10 = coerce_minimax_bookable_account(
            db, org_id, odhodek10, fallback="6500"
        )
    default_placilo = coerce_minimax_bookable_account(
        db, org_id, default_placilo, fallback="2211" if is_eu else "2200"
    )

    # Obdavčeno → P8/31; oproščeno (brez DDV / presežek) → P14/33.
    split = split_taxable_and_exempt(
        expense_total,
        vat_22=vat_22,
        vat_95=vat_95,
        vat_5=ZERO,
        eu_goods=eu_goods,
        eu_services=eu_services,
        f76a=ZERO,
    )

    payload: dict[str, Any] = {
        "seq": seq,
        "booking_date": book_date or recv_date,
        "received_date": recv_date or book_date,
        "document_date": doc_date or recv_date,
        "document_no": document_no or ctrl,
        "internal_no": ctrl,
        "supplier_name": supplier or "Dobavitelj",
        "vat_id": vat_id,
        "tax_number": tax_digits(vat_id),
        "net_taxable": split["net_taxable"],
        "f76a": Decimal("0"),
        "eu_goods": eu_goods,
        "eu_services": eu_services,
        "exempt_non": Decimal("0"),
        "exempt_os": Decimal("0"),
        "exempt_on": split["exempt_on"],
        "nondeduct_22": Decimal("0"),
        "nondeduct_95": Decimal("0"),
        "base_22": split["base_22"],
        "vat_22": vat_22,
        "base_95": split["base_95"],
        "vat_95": vat_95,
        "base_5": split["base_5"],
        "vat_5": Decimal("0"),
        "excluded": Decimal("0"),
        "odhodek01": odhodek01,
        "odhodek07": accounts.get("odhodek07") or "",
        "odhodek10": odhodek10,
        "odhodek11": accounts.get("odhodek11") or "",
        "odhodek_excluded": accounts.get("odhodek_excluded") or "",
        "placilo": default_placilo,
        "supplier_kind": supplier_kind,
        "status": "OSNUTEK",
        "notes": kisanal_marker(ctrl),
        "raw_json": {
            "source": "kisanal",
            "anal_ctrl": ctrl,
            "lines": len(lines),
            "anal_part": part_code,
            "supplier_kind": supplier_kind,
            "expense_total": str(expense_total),
            "exempt_to_33": str(split["exempt_on"]),
        },
    }
    if self_assessment is not None:
        payload["self_assessment"] = self_assessment
    if vat_deductible is not None:
        payload["vat_deductible"] = vat_deductible
    payload.update(allocate_pr_accounts(payload))
    # Po allocate ohrani kisanal plačilo (ne 2200→2211 iz imena).
    if placilo:
        payload["placilo"] = placilo.split("-")[0] if "-" in placilo else placilo
    return payload


def import_kisanal_to_ir_pr(
    db: Database,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    replace_existing: bool = False,
    groups: Sequence[str] = ("IR", "PR"),
    org_id: str | int | None = None,
) -> IntegraIrPrResult:
    """Prenesi IR/PR dokumente iz tabele kisanal v ir_rows/pr_rows."""
    result = IntegraIrPrResult()
    path = Path(db.path)
    if not path.is_file():
        result.message = "Ni SQLite baze."
        return result
    org = normalize_text(org_id) or default_minimax_org_id(db)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kisanal'"
        ).fetchone()
        if not exists:
            result.message = "Tabela kisanal še ne obstaja — najprej UrejanjeKisanal → SQLite."
            return result
        popa_vat, popa_name, popa_country = _load_popa(conn)
        params: list[Any] = []
        where = "1=1"
        if date_from and date_to:
            where = "(anal_ddok BETWEEN ? AND ?) OR (anal_ddur BETWEEN ? AND ?)"
            iso0, iso1 = date_from.isoformat(), date_to.isoformat()
            params = [iso0, iso1, iso0, iso1]
        cur = conn.execute(
            f"""
            SELECT anal_ctrl, anal_pozi, anal_akon, anal_akon_old, anal_ddok, anal_ddur,
                   anal_dknj, anal_debt, anal_krdt, anal_part, anal_pime, anal_doku,
                   anal_anal, anal_vrkn, anal_veza
            FROM kisanal
            WHERE {where}
            ORDER BY anal_ctrl, anal_pozi
            """,
            params,
        )
        raw_lines = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    wanted = {g.upper() for g in groups} - set(SKIP_IMPORT_GROUPS)
    ir_lines = [
        r
        for r in raw_lines
        if knjiga_group(str(r.get("anal_ctrl") or ""), str(r.get("anal_vrkn") or "")) == "IR"
        and "IR" in wanted
    ]
    pr_lines = [
        r
        for r in raw_lines
        if knjiga_group(str(r.get("anal_ctrl") or ""), str(r.get("anal_vrkn") or "")) == "PR"
        and "PR" in wanted
    ]

    if replace_existing:
        for row in list(db.list_ir()):
            if str(row.get("notes") or "").startswith(KISANAL_NOTE_PREFIX):
                db.delete_ir([row["id"]])
        for row in list(db.list_pr()):
            if str(row.get("notes") or "").startswith(KISANAL_NOTE_PREFIX):
                db.delete_pr([row["id"]])

    batch_id = db.create_batch("", "", str(path), note="integra kisanal -> IR/PR")
    result.batch_id = batch_id

    existing_ir = db.list_ir()
    existing_pr = db.list_pr()
    ir_seq = max((int(r.get("seq") or 0) for r in existing_ir), default=0)
    pr_seq = max((int(r.get("seq") or 0) for r in existing_pr), default=0)

    repaired_ir = 0
    for ctrl, lines in sorted(_group_lines(ir_lines).items()):
        existing_id = None if replace_existing else _find_existing_id(existing_ir, ctrl)
        data = _build_ir_from_group(
            ctrl,
            lines,
            db=db,
            popa_vat=popa_vat,
            popa_name=popa_name,
            popa_country=popa_country,
            seq=ir_seq + 1,
            org_id=org,
        )
        if data is None:
            result.skipped += 1
            continue
        if existing_id and not replace_existing:
            # Integra: osveži Paragoni konto (1000/1650) + SI/AT davčno na obstoječih
            if _patch_existing_ir(db, int(existing_id), data):
                repaired_ir += 1
            result.skipped += 1
            continue
        ir_seq += 1
        data["seq"] = ir_seq
        data["batch_id"] = batch_id
        party = db.find_party_by_tax(data["vat_id"]) if data.get("vat_id") else None
        if party:
            data["party_id"] = party["id"]
        rid = db.upsert_ir(data)
        try:
            db.replace_journal_lines("IR", int(rid), data)
        except Exception:
            pass
        result.ir += 1
        result.ir_ctrls.append(ctrl)

    repaired_pr = 0
    for ctrl, lines in sorted(_group_lines(pr_lines).items()):
        existing_id = None if replace_existing else _find_existing_id(existing_pr, ctrl)
        data = _build_pr_from_group(
            ctrl,
            lines,
            db=db,
            popa_vat=popa_vat,
            popa_name=popa_name,
            popa_country=popa_country,
            seq=pr_seq + 1,
            org_id=org,
        )
        if data is None:
            result.skipped += 1
            continue
        if existing_id and not replace_existing:
            if _patch_existing_pr(db, int(existing_id), data):
                repaired_pr += 1
            result.skipped += 1
            continue
        pr_seq += 1
        data["seq"] = pr_seq
        data["batch_id"] = batch_id
        party = db.find_party_by_tax(data["vat_id"]) if data.get("vat_id") else None
        if party:
            data["party_id"] = party["id"]
        apply_pr_si_vat_flag(data, party)
        db.upsert_pr(data)
        result.pr += 1
        result.pr_ctrls.append(ctrl)

    # Obstoječe: SI/AT predpone + Paragoni konti tudi izven obdobja prenosa
    vat_fix = repair_integra_vat_prefixes(db)
    # Obstoječe PR: oproščeno iz 31 → 33 (tudi če ni bilo novega prenosa).
    fix = reclassify_pr_exempt_to_field33(db)

    dlabel = (
        f"{date_from.isoformat()} - {date_to.isoformat()}"
        if date_from and date_to
        else "vsa obdobja"
    )
    result.message = (
        f"Prenos kisanal → IR/PR ({dlabel})\n"
        f"IR: {result.ir} novih · PR: {result.pr} novih · "
        f"preskočeno (že v knjigi / plačila): {result.skipped}"
    )
    if repaired_ir or repaired_pr:
        result.message += (
            f"\nOsveženo (Paragoni 1000/1650 + davčna): IR {repaired_ir}, PR {repaired_pr}."
        )
    if vat_fix.get("ir") or vat_fix.get("pr") or vat_fix.get("parties"):
        result.message += (
            f"\nDavčna +SI/AT: IR {vat_fix.get('ir', 0)}, "
            f"PR {vat_fix.get('pr', 0)}, stranke {vat_fix.get('parties', 0)}."
        )
    if fix.get("updated"):
        from trops_studio.money import money_text

        result.message += (
            f"\nOproščeno → polje 33: {fix['updated']} PR "
            f"(premaknjeno {money_text(fix['moved'])})."
        )
    return result


def _merge_raw_json(existing: Mapping[str, Any] | None, patch: Mapping[str, Any]) -> dict[str, Any]:
    raw = (existing or {}).get("raw_json")
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.update({k: v for k, v in patch.items() if v is not None and v != ""})
    return data


def _patch_existing_ir(db: Database, row_id: int, data: Mapping[str, Any]) -> bool:
    """Osveži Paragoni payment_account, listino 100****, Opis + SI davčno."""
    row = db.get_ir(row_id)
    if not row:
        return False
    changed = False
    new_vat = normalize_vat_id(data.get("vat_id"))
    old_vat = normalize_vat_id(row.get("vat_id"))
    patch_raw = data.get("raw_json") if isinstance(data.get("raw_json"), dict) else {}
    merged = _merge_raw_json(row, patch_raw if isinstance(patch_raw, dict) else {})
    pay = normalize_text(merged.get("payment_account"))
    old_raw = row.get("raw_json")
    try:
        old_data = json.loads(old_raw) if isinstance(old_raw, str) else dict(old_raw or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        old_data = {}
    old_pay = normalize_text(old_data.get("payment_account") if isinstance(old_data, dict) else "")

    payload: dict[str, Any] = dict(row)
    if new_vat and new_vat != old_vat:
        payload["vat_id"] = new_vat
        changed = True
    new_doc = normalize_text(data.get("document_no"))
    old_doc = normalize_text(row.get("document_no"))
    if new_doc and new_doc != old_doc:
        payload["document_no"] = new_doc
        changed = True
    new_notes = normalize_text(data.get("notes"))
    old_notes = normalize_text(row.get("notes"))
    # Zamenjaj grd kisanal:/#IR… opis
    if new_notes and (
        new_notes != old_notes
        or old_notes.startswith(KISANAL_NOTE_PREFIX)
        or old_notes.startswith("#IR")
        or old_notes.startswith("IR:")
    ):
        payload["notes"] = new_notes
        changed = True
    if pay and pay != old_pay:
        payload["raw_json"] = merged
        changed = True
    elif merged != old_data:
        payload["raw_json"] = merged
        changed = True
    name = normalize_text(data.get("party_name"))
    if name and name != normalize_text(row.get("party_name")):
        # Samo Paragoni / generična imena — ne prepiši ročno urejenega kupca
        old_name = normalize_text(row.get("party_name")).casefold()
        if old_name.startswith("paragoni") or not old_name:
            payload["party_name"] = name
            changed = True
    if not changed:
        return False
    if data.get("vat_id"):
        party = db.find_party_by_tax(str(data["vat_id"]))
        if party:
            payload["party_id"] = party["id"]
    # Ohrani sync_status
    payload["sync_status"] = row.get("sync_status")
    db.upsert_ir(payload, row_id=row_id)
    try:
        db.replace_journal_lines("IR", row_id, db.get_ir(row_id) or payload)
    except Exception:
        pass
    return True


def _patch_existing_pr(db: Database, row_id: int, data: Mapping[str, Any]) -> bool:
    """Osveži SI/AT davčno na že prenesenem PR."""
    row = db.get_pr(row_id)
    if not row:
        return False
    new_vat = normalize_vat_id(data.get("vat_id"))
    old_vat = normalize_vat_id(row.get("vat_id"))
    if not new_vat or new_vat == old_vat:
        return False
    payload = dict(row)
    payload["vat_id"] = new_vat
    if data.get("tax_number"):
        payload["tax_number"] = tax_digits(data.get("tax_number"))
    else:
        payload["tax_number"] = tax_digits(new_vat)
    party = db.find_party_by_tax(new_vat)
    if party:
        payload["party_id"] = party["id"]
    payload["sync_status"] = row.get("sync_status")
    db.upsert_pr(payload, row_id=row_id)
    return True


def repair_integra_vat_prefixes(db: Database) -> dict[str, int]:
    """Dopolni gole davčne (8 mest) z SI/AT na IR, PR in parties."""
    stats = {"ir": 0, "pr": 0, "parties": 0}
    for row in db.list_ir():
        raw = normalize_vat_id(row.get("vat_id"))
        if not raw:
            continue
        fixed = integra_vat_id(raw, country="SI")
        if fixed and fixed != raw:
            payload = dict(row)
            payload["vat_id"] = fixed
            payload["sync_status"] = row.get("sync_status")
            party = db.find_party_by_tax(fixed) or db.find_party_by_tax(tax_digits(fixed))
            if party:
                payload["party_id"] = party["id"]
            db.upsert_ir(payload, row_id=int(row["id"]))
            stats["ir"] += 1
    for row in db.list_pr():
        raw = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        if not raw:
            continue
        cc = "SI"
        if len(raw) >= 2 and raw[:2].isalpha() and raw[:2] != "SI":
            cc = raw[:2]
        fixed = integra_vat_id(raw, country=cc)
        if fixed and fixed != normalize_vat_id(row.get("vat_id")):
            payload = dict(row)
            payload["vat_id"] = fixed
            payload["tax_number"] = tax_digits(fixed)
            payload["sync_status"] = row.get("sync_status")
            party = db.find_party_by_tax(fixed) or db.find_party_by_tax(tax_digits(fixed))
            if party:
                payload["party_id"] = party["id"]
            db.upsert_pr(payload, row_id=int(row["id"]))
            stats["pr"] += 1
    for party in db.list_parties():
        country = (normalize_text(party.get("country"))[:2] or "SI").upper()
        raw = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
        tax = tax_digits(party.get("tax_number") or raw)
        if country not in {"", "SI"} and not raw:
            continue
        if not tax and not raw:
            continue
        fixed = integra_vat_id(raw or tax, country=country or "SI")
        old = normalize_vat_id(party.get("vat_id"))
        if fixed and fixed != old:
            db.upsert_party(
                {
                    **party,
                    "vat_id": fixed,
                    "tax_number": tax or tax_digits(fixed),
                    "country": country or "SI",
                },
                party_id=int(party["id"]),
            )
            stats["parties"] += 1
    return stats
