"""Uvoz FURS KIR/KPR (ZIP/JSON/XML/CSV) → Trops SQLite IR/PR.

Uporabi vendor `load_dataset` (isti parser kot KirKpr Studio).
DDV-O ohrani izvirna P-polja v raw_json (`__source__=furs-kirkpr`).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio.accounts import allocate_pr_accounts, resolve_ir_account, resolve_pr_accounts
from trops_studio.config import DEFAULT_IR_REVENUE_ACCOUNT
from trops_studio.db import Database
from trops_studio.excel_map import _ir_dedupe_key, _pr_dedupe_key
from trops_studio.ir_list_view import apply_ir_eu_sale
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path
from trops_studio.money import (
    ProjestError,
    ZERO,
    decimal_value,
    normalize_text,
    normalize_vat_id,
    parse_date,
    tax_digits,
)
from trops_studio.pr_list_view import apply_pr_si_vat_flag

SOURCE_TAG = "furs-kirkpr"


def _safe_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return parse_date(value)
    except Exception:
        text = str(value or "").strip()[:10]
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
        return None


def _safe_iso(value: Any) -> str | None:
    day = _safe_date(value)
    return day.isoformat() if day else None


def _base_from_vat(vat: Decimal, rate: str) -> Decimal:
    if vat == ZERO:
        return ZERO
    div = Decimal(rate)
    if div <= 0:
        return ZERO
    return (vat / div).quantize(Decimal("0.01"))


def _boolish(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "da", "yes", "d", "y"}:
        return True
    if text in {"0", "false", "ne", "no", "n"}:
        return False
    return None


def _pack_raw(book: str, row: Mapping[str, Any]) -> str:
    payload = dict(row)
    payload["__source__"] = SOURCE_TAG
    payload["__book__"] = book
    return json.dumps(payload, ensure_ascii=False, default=str)


def kir_to_ir(row: Mapping[str, Any], db: Database | None = None) -> dict[str, Any]:
    """FURS KIR vrstica → Trops IR payload."""
    vat_22 = decimal_value(row.get("P14"))
    vat_95 = decimal_value(row.get("P15"))
    vat_5 = decimal_value(row.get("P16"))
    net = decimal_value(row.get("P7"))
    eu_goods = decimal_value(row.get("P10"))
    eu_services = decimal_value(row.get("P11"))
    reverse = decimal_value(row.get("P8"))
    exempt = decimal_value(row.get("P9"))
    excluded = decimal_value(row.get("P27"))
    base_22 = _base_from_vat(vat_22, "0.22")
    base_95 = _base_from_vat(vat_95, "0.095")
    if base_22 == ZERO and vat_22 == ZERO and net and not (eu_goods or eu_services or reverse or exempt):
        base_22 = net
    party_name = normalize_text(row.get("P5"))
    vat_id = normalize_vat_id(row.get("P6DS") or row.get("P6"))
    if db is not None:
        account = resolve_ir_account(db, vat_id=vat_id, name=party_name)
    else:
        account = DEFAULT_IR_REVENUE_ACCOUNT
    try:
        seq = int(decimal_value(row.get("ZAPST") or row.get("P1") or 0))
    except Exception:
        seq = 0
    sa = (
        decimal_value(row.get("P17"))
        + decimal_value(row.get("P18"))
        + decimal_value(row.get("P19"))
        + decimal_value(row.get("P20"))
        + decimal_value(row.get("P21"))
        + decimal_value(row.get("P22"))
        + decimal_value(row.get("P23"))
        + decimal_value(row.get("P24"))
        + decimal_value(row.get("P25"))
        + decimal_value(row.get("P26"))
    )
    notes = "FURS KIR SA" if sa and not (net or vat_22 or vat_95 or vat_5 or eu_goods or eu_services) else ""
    total = base_22 + vat_22 + base_95 + vat_95 + eu_goods + eu_services + exempt + reverse
    payload = {
        "book": "KIR",
        "seq": seq,
        "booking_date": _safe_iso(row.get("P2")),
        "document_date": _safe_iso(row.get("P4")) or _safe_iso(row.get("P2")),
        "document_no": normalize_text(row.get("P3")),
        "party_name": party_name,
        "vat_id": vat_id,
        "net": net,
        "base_22": base_22,
        "vat_22": vat_22,
        "base_95": base_95,
        "vat_95": vat_95,
        "eu_goods": eu_goods,
        "eu_services": eu_services,
        "reverse_charge": reverse,
        "excluded": excluded,
        "exempt": exempt,
        "total": total,
        "account": account,
        "status": "OSNUTEK",
        "notes": notes,
        "raw_json": _pack_raw("KIR", row),
    }
    return apply_ir_eu_sale(payload)


def kpr_to_pr(row: Mapping[str, Any], db: Database) -> dict[str, Any]:
    """FURS KPR vrstica → Trops PR payload."""
    vat_id = normalize_vat_id(row.get("P7DS") or row.get("P7"))
    supplier = normalize_text(row.get("P6"))
    accounts = resolve_pr_accounts(db, vat_id=vat_id, name=supplier)
    vat_22 = decimal_value(row.get("P18"))
    vat_95 = decimal_value(row.get("P19"))
    vat_5 = decimal_value(row.get("P20"))
    try:
        seq = int(decimal_value(row.get("ZAPST") or row.get("P1") or 0))
    except Exception:
        seq = 0
    self_a = _boolish(row.get("__samoobdavcitev__") or row.get("SAMOOBDAVCITEV"))
    vat_ded = _boolish(row.get("__ddv_se_odbija__") or row.get("DDV_SE_ODBIJA"))
    # P9/P10/P11 → samoobdavčitev (kot kirkpr_minimax_core.source_self_assessment)
    if self_a is None and (
        decimal_value(row.get("P9"))
        or decimal_value(row.get("P10"))
        or decimal_value(row.get("P11"))
    ):
        self_a = True
        if vat_ded is None:
            vat_ded = True
    payload: dict[str, Any] = {
        "seq": seq,
        "booking_date": _safe_iso(row.get("P2")),
        "received_date": _safe_iso(row.get("P4")) or _safe_iso(row.get("P5")),
        "document_date": _safe_iso(row.get("P5")) or _safe_iso(row.get("P4")),
        "document_no": normalize_text(row.get("P3")),
        "internal_no": normalize_text(row.get("OPOMBE") or row.get("Opombe") or ""),
        "supplier_name": supplier,
        "vat_id": vat_id,
        "tax_number": tax_digits(vat_id),
        "net_taxable": decimal_value(row.get("P8")),
        "f76a": decimal_value(row.get("P9")),
        "eu_goods": decimal_value(row.get("P10")),
        "eu_services": decimal_value(row.get("P11")),
        "exempt_non": decimal_value(row.get("P12")),
        "exempt_os": decimal_value(row.get("P13")),
        "exempt_on": decimal_value(row.get("P14")),
        "nondeduct_22": decimal_value(row.get("P17")),
        "nondeduct_95": ZERO,
        "base_22": _base_from_vat(vat_22, "0.22"),
        "vat_22": vat_22,
        "base_95": _base_from_vat(vat_95, "0.095"),
        "vat_95": vat_95,
        "base_5": _base_from_vat(vat_5, "0.05"),
        "vat_5": vat_5,
        "excluded": ZERO,
        "odhodek01": accounts.get("odhodek01") or "",
        "odhodek07": accounts.get("odhodek07") or "",
        "odhodek10": accounts.get("odhodek10") or "",
        "odhodek11": accounts.get("odhodek11") or "",
        "odhodek_excluded": accounts.get("odhodek_excluded") or "",
        "placilo": accounts.get("placilo") or "2200",
        "status": "OSNUTEK",
        "notes": "",
        "raw_json": _pack_raw("KPR", row),
    }
    if self_a is not None:
        payload["self_assessment"] = self_a
    if vat_ded is not None:
        payload["vat_deductible"] = vat_ded
    payload.update(allocate_pr_accounts(payload))
    return payload


def raw_furs_kirkpr_row(sql_row: Mapping[str, Any], *, book: str) -> dict[str, Any] | None:
    """Če je vrstica iz FURS uvoza, vrni izvirna P-polja (za DDV-O)."""
    raw_text = sql_row.get("raw_json")
    if not raw_text:
        return None
    try:
        raw = json.loads(raw_text) if isinstance(raw_text, str) else dict(raw_text)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    if str(raw.get("__source__") or "") != SOURCE_TAG:
        return None
    if book and str(raw.get("__book__") or "").upper() != book.upper():
        return None
    return {k: v for k, v in raw.items() if not str(k).startswith("__")}


def import_kirkpr_file_to_db(
    db: Database,
    source: Path | str,
    *,
    replace_existing: bool = False,
    note: str = "furs kirkpr import",
    period_rev: int = 1,
    period_key: str = "",
    period_from: date | None = None,
    period_to: date | None = None,
) -> dict[str, Any]:
    """Naloži FURS datoteko in zapiše IR/PR v SQLite (brez podvajanja)."""
    path = Path(source)
    if not path.is_file():
        raise ProjestError(f"Datoteka ne obstaja:\n{path}")

    ensure_kirkpr_on_path()
    try:
        from kirkpr_minimax_core import load_dataset  # type: ignore
    except Exception as exc:
        raise ProjestError(f"Manjka KIR/KPR parser (vendor_kirkpr):\n{exc}") from exc

    try:
        dataset = load_dataset(path)
    except Exception as exc:
        raise ProjestError(str(exc)) from exc

    kir_rows: Sequence[Mapping[str, Any]] = list(getattr(dataset, "kir", None) or [])
    kpr_rows: Sequence[Mapping[str, Any]] = list(getattr(dataset, "kpr", None) or [])
    if not kir_rows and not kpr_rows:
        raise ProjestError("V datoteki ni vrstic KIR/KPR.")

    learned = db.learn_account_rules_from_rows()
    rev = max(1, int(period_rev or 1))
    batch_id = db.create_batch(
        str(path),
        "",
        str(path),
        note=f"{note} · {getattr(dataset, 'source_format', '')}",
        period_key=period_key,
        period_rev=rev,
    )

    existing_ir: set[tuple[str, str, str]] = set()
    existing_pr: set[tuple[str, str]] = set()
    if replace_existing and period_from and period_to:
        db.delete_ir_pr_for_period(period_from, period_to)
    elif replace_existing:
        replace_existing = False
    if not replace_existing:
        for row in db.list_ir():
            key = _ir_dedupe_key(row)
            if key is not None:
                existing_ir.add(key)
        for row in db.list_pr():
            key = _pr_dedupe_key(row)
            if key is not None:
                existing_pr.add(key)

    ir_count = 0
    pr_count = 0
    ir_skipped = 0
    pr_skipped = 0
    pr_si_vat = 0
    ir_ids: list[int] = []
    pr_ids: list[int] = []
    ir_docs: list[str] = []
    pr_docs: list[str] = []

    for raw in kir_rows:
        data = kir_to_ir(raw, db)
        data["batch_id"] = batch_id
        data["period_rev"] = rev
        key = _ir_dedupe_key(data)
        if key is not None and key in existing_ir:
            ir_skipped += 1
            continue
        from trops_studio.parties_ensure import resolve_party_for_journal_row

        party = resolve_party_for_journal_row(
            db,
            vat_id=data.get("vat_id") or "",
            name=data.get("party_name") or "",
        )
        if party:
            data["party_id"] = party["id"]
        rid = int(db.upsert_ir(data))
        if key is not None:
            existing_ir.add(key)
        ir_count += 1
        ir_ids.append(rid)
        doc = normalize_text(data.get("document_no"))
        if doc:
            ir_docs.append(doc)

    for raw in kpr_rows:
        data = kpr_to_pr(raw, db)
        data["batch_id"] = batch_id
        data["period_rev"] = rev
        key = _pr_dedupe_key(data)
        if key is not None and key in existing_pr:
            pr_skipped += 1
            continue
        from trops_studio.parties_ensure import resolve_party_for_journal_row

        party = resolve_party_for_journal_row(
            db,
            vat_id=data.get("vat_id") or "",
            tax_number=str(data.get("tax_number") or ""),
            name=data.get("supplier_name") or "",
        )
        if party:
            data["party_id"] = party["id"]
        if apply_pr_si_vat_flag(data, party):
            pr_si_vat += 1
        rid = int(db.upsert_pr(data))
        if key is not None:
            existing_pr.add(key)
        pr_count += 1
        pr_ids.append(rid)
        doc = normalize_text(data.get("document_no"))
        if doc:
            pr_docs.append(doc)

    warnings = list(getattr(dataset, "warnings", None) or [])
    return {
        "ir": ir_count,
        "pr": pr_count,
        "ir_skipped": ir_skipped,
        "pr_skipped": pr_skipped,
        "pr_si_vat": pr_si_vat,
        "batch_id": batch_id,
        "period_rev": rev,
        "learned_pr": learned.get("pr", 0),
        "learned_ir": learned.get("ir", 0),
        "ir_ids": ir_ids,
        "pr_ids": pr_ids,
        "ir_docs": ir_docs,
        "pr_docs": pr_docs,
        "source": str(path),
        "source_format": str(getattr(dataset, "source_format", "") or ""),
        "warnings": warnings,
    }
