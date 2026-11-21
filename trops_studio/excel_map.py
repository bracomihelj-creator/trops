from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio.accounts import (
    _known_vat_from_name,
    allocate_pr_accounts,
    resolve_ir_account,
    resolve_pr_accounts,
)
from trops_studio.ir_list_view import apply_ir_eu_sale
from trops_studio.db import Database
from trops_studio.excel_bridge import read_excel_books
from trops_studio.money import (
    ProjestError,
    decimal_value,
    iso_date,
    normalize_text,
    normalize_vat_id,
    parse_date,
    tax_digits,
)
from trops_studio.pr_list_view import apply_pr_si_vat_flag
from trops_studio.vasco_discover import ir_book_from_filename, ir_group_from_document


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _ir_dedupe_key(data: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """IR: knjiga + št. listine + datum listine (enako kot idx_ir_document)."""
    document_no = normalize_text(data.get("document_no"))
    if not document_no:
        return None
    return (
        normalize_text(data.get("book")).casefold(),
        document_no.casefold(),
        iso_date(data.get("document_date")) or "",
    )


def _pr_dedupe_key(data: Mapping[str, Any]) -> tuple[str, str] | None:
    """PR: št. listine + datum (brez DDV — prazen/dopolnjen ID ne sme podvojiti)."""
    document_no = normalize_text(data.get("document_no")).casefold()
    if not document_no:
        return None
    day = iso_date(data.get("document_date")) or iso_date(data.get("received_date")) or ""
    return (document_no, day)


def map_ir(raw: Mapping[str, Any], book_name: str, db: Database | None = None) -> dict[str, Any]:
    document_date = parse_date(raw.get("Datum listine"), field_name="datum listine")
    booking_date = parse_date(raw.get("Datum knjižbe"), field_name="datum knjižbe")
    base_22 = decimal_value(raw.get("Obdavčen promet - DDV"))
    vat_22 = decimal_value(raw.get("F19"))
    base_95 = decimal_value(raw.get("F20"))
    vat_95 = decimal_value(raw.get("F21"))
    eu_goods = decimal_value(raw.get("F11"))
    eu_services = decimal_value(raw.get("F12"))
    exempt = decimal_value(raw.get("Oproščen promet"))
    reverse = decimal_value(raw.get("Obrnjeno davčno breme (brez DDV)"))
    excluded = decimal_value(raw.get("Ne gre v knjigo"))
    net = decimal_value(raw.get("Vrednost brez DDV"))
    total = base_22 + vat_22 + base_95 + vat_95 + eu_goods + eu_services + exempt
    document_no = normalize_text(raw.get("Številka listine"))
    group = ir_group_from_document(document_no, fallback=book_name)
    party_name = normalize_text(raw.get("Kupec"))
    vat_id = normalize_vat_id(raw.get("ID za DDV"))
    if db is not None:
        account = resolve_ir_account(db, vat_id=vat_id, name=party_name)
    else:
        from trops_studio.config import DEFAULT_IR_REVENUE_ACCOUNT

        account = DEFAULT_IR_REVENUE_ACCOUNT
    payload = {
        "book": group,
        "seq": int(decimal_value(raw.get("ZŠ"))),
        "booking_date": booking_date,
        "document_date": document_date,
        "document_no": document_no,
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
        "notes": "",
        "raw_json": json.dumps(dict(raw), ensure_ascii=False, default=str),
    }
    return apply_ir_eu_sale(payload)


def map_pr(raw: Mapping[str, Any], db: Database) -> dict[str, Any]:
    vat_id = normalize_vat_id(raw.get("ID za DDV"))
    supplier = normalize_text(raw.get("Dobavitelj"))
    if not vat_id:
        vat_id = _known_vat_from_name(supplier)
    accounts = resolve_pr_accounts(db, vat_id=vat_id, name=supplier)
    f8 = decimal_value(raw.get("Vrednost obdavčenih nabav brez DDV"))
    f14 = decimal_value(raw.get("Vrednost oproščenih nabav"))
    payload: dict[str, Any] = {
        "seq": int(decimal_value(raw.get("ZŠ"))),
        "booking_date": parse_date(raw.get("Datum knjižbe"), field_name="datum knjižbe"),
        "received_date": parse_date(raw.get("Datum prejema listine"), field_name="datum prejema"),
        "document_date": parse_date(raw.get("Datum listine"), field_name="datum listine"),
        "document_no": normalize_text(raw.get("Številka listine")),
        "internal_no": normalize_text(raw.get("Opombe") or raw.get("Interna št#")),
        "supplier_name": supplier,
        "vat_id": vat_id,
        "tax_number": tax_digits(vat_id),
        "net_taxable": f8,
        "f76a": decimal_value(raw.get("F11")),
        "eu_goods": decimal_value(raw.get("F12")),
        "eu_services": decimal_value(raw.get("F13")),
        "exempt_non": decimal_value(raw.get("F14")),
        "exempt_os": decimal_value(raw.get("F15")),
        "exempt_on": f14,
        "nondeduct_22": decimal_value(raw.get("DDV, ki se ne odbija")),
        "nondeduct_95": decimal_value(raw.get("F20")),
        "base_22": decimal_value(raw.get("DDV, ki se odbija")),
        "vat_22": decimal_value(raw.get("F24")),
        "base_95": decimal_value(raw.get("F25")),
        "vat_95": decimal_value(raw.get("F26")),
        "base_5": decimal_value(raw.get("F27")),
        "vat_5": decimal_value(raw.get("F28")),
        "excluded": decimal_value(raw.get("Ne gre v knjigo")),
        # Predloga iz account_rules / zgodovine — allocate razporedi 08/10/11/ne gre
        "odhodek01": accounts.get("odhodek01") or "",
        "odhodek07": accounts.get("odhodek07") or "",
        "odhodek10": accounts.get("odhodek10") or "",
        "odhodek11": accounts.get("odhodek11") or "",
        "odhodek_excluded": accounts.get("odhodek_excluded") or "",
        "placilo": accounts.get("placilo") or "2200",
        "status": "OSNUTEK",
        "notes": "",
        "raw_json": json.dumps(dict(raw), ensure_ascii=False, default=str),
    }
    if accounts.get("self_assessment") is not None:
        payload["self_assessment"] = accounts["self_assessment"]
    if accounts.get("vat_deductible") is not None:
        payload["vat_deductible"] = accounts["vat_deductible"]
    allocated = allocate_pr_accounts(payload)
    payload.update(allocated)
    return payload


def import_vasco_files_to_db(
    db: Database,
    *,
    ir_files: Sequence[Path],
    pr_files: Sequence[Path],
    replace_existing: bool = False,
    note: str = "vasco import",
    period_rev: int = 1,
    period_key: str = "",
    period_from: date | None = None,
    period_to: date | None = None,
) -> dict[str, int]:
    """Uvoz vseh IR/PR iz Vasco datotek. Že v bazi se ne podvajajo."""
    ir_files = [Path(p) for p in ir_files]
    pr_files = [Path(p) for p in pr_files]
    missing = [str(p) for p in [*ir_files, *pr_files] if not p.is_file()]
    if missing:
        raise ProjestError("Manjkajo datoteke:\n" + "\n".join(missing))
    if not ir_files and not pr_files:
        raise ProjestError("Ni Vasco datotek za uvoz (IF* = IR, kp* = PR).")

    # Pred uvozom se nauči kontov iz že shranjenih mesecev (maj → junij).
    learned = db.learn_account_rules_from_rows()

    bridge: list[tuple[str, Path]] = []
    for path in ir_files:
        bridge.append((f"IR:{ir_book_from_filename(path)}", path))
    for path in pr_files:
        bridge.append(("PR", path))

    books = read_excel_books(bridge)
    rev = max(1, int(period_rev or 1))
    batch_id = db.create_batch(
        str(ir_files[0]) if ir_files else "",
        str(ir_files[1]) if len(ir_files) > 1 else "",
        str(pr_files[0]) if pr_files else "",
        note=note,
        period_key=period_key,
        period_rev=rev,
    )
    existing_ir: set[tuple[str, str, str]] = set()
    existing_pr: set[tuple[str, str]] = set()
    if replace_existing and period_from and period_to:
        # Samo trenutno obdobje — nikoli cele baze (zaključen mesec ostane).
        db.delete_ir_pr_for_period(period_from, period_to)
    elif replace_existing:
        replace_existing = False
    if not replace_existing:
        # Vedno: obstoječih ne podvajaj (tudi po brisanju posameznih listin).
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
    for book in books:
        kind = str(book.get("kind") or "")
        source_path = Path(str(book.get("path") or ""))
        for raw in _as_list(book.get("rows")):
            if kind.startswith("IR"):
                fallback = kind.split(":", 1)[1] if ":" in kind else ir_book_from_filename(source_path)
                data = map_ir(raw, fallback, db)
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
                # Kupec + ID za DDV ostaneta iz Excela — šifrant jih ne prepiše.
                rid = int(db.upsert_ir(data))
                if key is not None:
                    existing_ir.add(key)
                ir_count += 1
                ir_ids.append(rid)
                doc = normalize_text(data.get("document_no"))
                if doc:
                    ir_docs.append(doc)
            elif kind == "PR":
                data = map_pr(raw, db)
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
    }


def import_excels_to_db(
    db: Database,
    *,
    ir_darila: Path,
    ir_fitnes: Path,
    pr_file: Path,
    replace_existing: bool = False,
) -> dict[str, int]:
    """Združljivost: stari klic 3 datotek → Vasco uvoz."""
    return import_vasco_files_to_db(
        db,
        ir_files=[ir_darila, ir_fitnes],
        pr_files=[pr_file],
        replace_existing=replace_existing,
        note="vasco import (3 datoteke)",
    )
