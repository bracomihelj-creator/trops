"""Avtomatska oddaja IR/PR temeljnic v Minimax API kot osnutki (Status=O).

Mimo ročnega: shrani XML → WebUI uvoz.
Uporabi isto XML zgradbo kot »XML→Minimax«, nato POST /journals.

Ponovni sync: samo še nepreneseno — obstoječe osnutke/listine v Minimaxu
ne podvaja (preskoči in označi synced).
"""

from __future__ import annotations

import logging

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from trops_studio.db import Database
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path
from trops_studio.minimax_runtime import open_minimax_client
from trops_studio.money import decimal_value, is_nonzero, normalize_text
from trops_studio.sync_state import SYNC_ERROR, SYNC_READY, SYNC_SYNCED
from trops_studio.xml_export import (
    _build_ir_journals,
    _build_pr_journals,
    _import_xml_helpers,
    _make_root_with_addresses,
    ir_to_kir,
    pr_to_kpr,
)

ProgressCb = Callable[[str, int, int], None]


def _progress(cb: ProgressCb | None, message: str, current: int = 0, total: int = 0) -> None:
    if cb:
        try:
            cb(message, current, total)
        except Exception:
            logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:38)", exc_info=True)


@dataclass
class JournalPushResult:
    ir_ok: int = 0
    pr_ok: int = 0
    ir_skipped: int = 0
    pr_skipped: int = 0
    ir_failed: list[str] = field(default_factory=list)
    pr_failed: list[str] = field(default_factory=list)
    message: str = ""


def _norm_ref(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _decorate_vat_listina(payload: dict[str, Any], sql_row: Mapping[str, Any]) -> dict[str, Any]:
    """Knjiga PR stolpec 4 = Notes;Document. Notes=interna, Document=listina (brez Obracun)."""
    try:
        from minimax_api_client import _clean_vat_document  # type: ignore
    except Exception:
        _clean_vat_document = lambda v: str(v or "").strip()

    doc = _clean_vat_document(sql_row.get("document_no") or sql_row.get("Document") or "")
    interna = normalize_text(sql_row.get("internal_no"))
    os_amt, realty_amt = _pr_os_vat_amounts(sql_row)
    for vat in payload.get("VatEntries") or []:
        if not isinstance(vat, dict):
            continue
        if doc:
            vat["Document"] = doc
        else:
            vat["Document"] = _clean_vat_document(vat.get("Document"))
        vat.pop("ReportingType", None)
        if interna:
            vat["Notes"] = interna[:250]
        else:
            vat.pop("Notes", None)
        book = str(vat.get("VatBook") or "PR").strip().upper()
        if book == "PR":
            if is_nonzero(os_amt) and not vat.get("OsnovnoSredstvo"):
                vat["OsnovnoSredstvo"] = float(os_amt)
            if is_nonzero(realty_amt) and not vat.get("Nepremicnina"):
                vat["Nepremicnina"] = float(realty_amt)
    return payload


def _pr_os_vat_amounts(sql_row: Mapping[str, Any]) -> tuple[Any, Any]:
    """0470 / KPR 13 → Osnovno sredstvo; 12 → Nepremičnina (WebUI temeljnica)."""
    from decimal import Decimal

    from trops_studio.os_accounts import add_os_amount_to_kpr

    zero = Decimal("0.00")
    kpr = {"P8": decimal_value(sql_row.get("net_taxable")), "P12": zero, "P13": zero, "P14": zero, "P15": zero}
    add_os_amount_to_kpr(kpr, sql_row)
    return decimal_value(kpr.get("P13")), decimal_value(kpr.get("P12"))


def _sql_rows_to_kir_kpr(
    db: Database,
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from trops_studio.config import KONCNI_KUPCI_CODE, KONCNI_KUPCI_NAME
    from trops_studio.money import has_country_prefixed_vat_id

    koncni = db.find_party_by_minimax_code(KONCNI_KUPCI_CODE)
    koncni_party = dict(koncni) if koncni else {
        "minimax_code": KONCNI_KUPCI_CODE,
        "name": KONCNI_KUPCI_NAME,
        "vat_id": "",
        "tax_number": "",
        "country": "SI",
    }

    def _force_koncni(mapped: dict[str, Any]) -> dict[str, Any]:
        p = dict(mapped.get("__party__") or {})
        p["code"] = KONCNI_KUPCI_CODE
        p["name"] = KONCNI_KUPCI_NAME
        p["tax_id"] = ""
        mapped["__party__"] = p
        mapped["__party_code__"] = KONCNI_KUPCI_CODE
        return mapped

    def _resolve_pr(row: Mapping[str, Any]) -> dict[str, Any] | None:
        from trops_studio.money import sanitize_display_text
        from trops_studio.parties_ensure import resolve_party_for_journal_row

        return resolve_party_for_journal_row(
            db,
            party_id=row.get("party_id"),
            vat_id=str(row.get("vat_id") or ""),
            tax_number=str(row.get("tax_number") or ""),
            name=sanitize_display_text(row.get("supplier_name")),
        )

    def _unique_opis(book: str, row: Mapping[str, Any], mapped: dict[str, Any]) -> None:
        """Opis glave: IR = listina (DR… / 100…); PR = interna ali listina.

        #IR868 / #PR12 ostane samo sync_tag (dedup), ne gre v OpisGlave.
        """
        interna = normalize_text(row.get("internal_no"))
        doc = normalize_text(row.get("document_no"))
        rid = int(row.get("id") or 0)
        tag = f"#{book.upper()}{rid}" if rid else ""
        if book.upper() == "IR":
            head = doc or interna or tag
        else:
            head = interna or doc or tag
        mapped["__opis__"] = head[:250]
        if interna and book.upper() == "PR":
            # Stolpec Knjižba = OpisVrstice + listina → »260197; 26-360-…«
            mapped["__opis_knjizba__"] = f"{interna};"[:250]
        else:
            mapped["__opis_knjizba__"] = head[:250]
        if tag:
            mapped["__sync_tag__"] = tag

    from trops_studio.journal_preview import _ir_payment_account

    kir: list[dict[str, Any]] = []
    kpr: list[dict[str, Any]] = []
    for index, row in enumerate(ir_rows, start=1):
        payment = _ir_payment_account(row)
        # Integra Paragoni (1000/1650): DI, brez Končnih kupcev / 1200
        if payment in {"1000", "1650"}:
            mapped = ir_to_kir(row, party=None, zapst=index)
            mapped["__payment_account__"] = payment
            mapped["__journal_type__"] = "DI"
            mapped["__party_code__"] = ""
            p = dict(mapped.get("__party__") or {})
            p["code"] = ""
            mapped["__party__"] = p
        elif not has_country_prefixed_vat_id(row.get("vat_id")):
            # Brez SI/DE/US… (prazno ali 8 mest) → Končni kupci 01345, ne OSOVNIKAR
            mapped = ir_to_kir(row, party=koncni_party, zapst=index)
            mapped = _force_koncni(mapped)
            mapped["__payment_account__"] = payment or "1200"
        else:
            from trops_studio.money import sanitize_display_text
            from trops_studio.parties_ensure import resolve_party_for_journal_row

            party = resolve_party_for_journal_row(
                db,
                party_id=row.get("party_id"),
                vat_id=str(row.get("vat_id") or ""),
                name=sanitize_display_text(row.get("party_name")),
            )
            mapped = ir_to_kir(row, party=party, zapst=index)
            if party and normalize_text(party.get("minimax_code")) == KONCNI_KUPCI_CODE:
                mapped = _force_koncni(mapped)
            mapped["__payment_account__"] = payment or "1200"
        _unique_opis("IR", row, mapped)
        kir.append(mapped)
    for index, row in enumerate(pr_rows, start=1):
        party = _resolve_pr(row)
        mapped = pr_to_kpr(row, party=party, zapst=index)
        # PR: Končni kupci samo, če je stranka že eksplicitno 01345
        if party and normalize_text(party.get("minimax_code")) == KONCNI_KUPCI_CODE:
            mapped = _force_koncni(mapped)
        _unique_opis("PR", row, mapped)
        kpr.append(mapped)
    return kir, kpr


def _root_for_single_journal(
    *,
    book: str,
    kir_row: Mapping[str, Any] | None = None,
    kpr_row: Mapping[str, Any] | None = None,
) -> Any:
    """Enaka XML temeljnica kot pri uvozu datoteke — ena Temeljnica."""
    mx = _import_xml_helpers()
    party_dicts: list[dict[str, str]] = []
    if kir_row and kir_row.get("__party__"):
        party_dicts.append(dict(kir_row["__party__"]))
    if kpr_row and kpr_row.get("__party__"):
        party_dicts.append(dict(kpr_row["__party__"]))
    root, tem = _make_root_with_addresses(mx, party_dicts)
    if book.upper() == "IR" and kir_row:
        _build_ir_journals(mx, tem, [kir_row])
    elif book.upper() == "PR" and kpr_row:
        _build_pr_journals(mx, tem, [kpr_row])
    else:
        raise ValueError(f"Manjka vrstica za knjigo {book}")
    return root


def _row_doc_ref(sql_row: Mapping[str, Any]) -> str:
    return _norm_ref(sql_row.get("document_no") or sql_row.get("internal_no") or "")


def _row_unique_key(book: str, sql_row: Mapping[str, Any]) -> str:
    """Primarni ključ proti podvajanju: #PR106 / #IR12 (ne samo listina)."""
    rid = int(sql_row.get("id") or 0)
    if rid:
        return _norm_ref(f"#{book.upper()}{rid}")
    return _row_doc_ref(sql_row)


def _is_journal_only_pr(sql_row: Mapping[str, Any]) -> bool:
    """»Ne gre v knjigo« = ni v DDV: samo temeljnica, brez DDV bloka."""
    excluded = decimal_value(sql_row.get("excluded"))
    if not is_nonzero(excluded):
        return False
    taxable = (
        decimal_value(sql_row.get("net_taxable"))
        + decimal_value(sql_row.get("f76a"))
        + decimal_value(sql_row.get("eu_goods"))
        + decimal_value(sql_row.get("eu_services"))
        + decimal_value(sql_row.get("vat_22"))
        + decimal_value(sql_row.get("vat_95"))
        + decimal_value(sql_row.get("vat_5"))
    )
    return not is_nonzero(taxable)


def _row_minimax_journal_id(sql_row: Mapping[str, Any]) -> int:
    try:
        raw = json.loads(sql_row.get("raw_json") or "{}")
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        return 0
    try:
        return int(raw.get("minimax_journal_id") or 0)
    except (TypeError, ValueError):
        return 0


def _save_minimax_journal_id(db: Database, kind: str, sql_row: Mapping[str, Any], journal_id: int) -> None:
    if not sql_row.get("id") or journal_id <= 0:
        return
    try:
        raw = json.loads(sql_row.get("raw_json") or "{}")
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["minimax_journal_id"] = int(journal_id)
    payload = dict(sql_row)
    payload["raw_json"] = raw
    if kind.upper() == "IR":
        db.upsert_ir(payload, row_id=int(sql_row["id"]))
    else:
        db.upsert_pr(payload, row_id=int(sql_row["id"]))


def _clear_minimax_journal_id(db: Database, kind: str, sql_row: Mapping[str, Any]) -> None:
    """Odstrani mrtvi JournalId (404) — vrstica gre spet v oddajo."""
    if not sql_row.get("id"):
        return
    try:
        raw = json.loads(sql_row.get("raw_json") or "{}")
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if "minimax_journal_id" not in raw:
        return
    raw.pop("minimax_journal_id", None)
    payload = dict(sql_row)
    payload["raw_json"] = raw
    payload["sync_status"] = SYNC_READY
    if kind.upper() == "IR":
        db.upsert_ir(payload, row_id=int(sql_row["id"]))
    else:
        db.upsert_pr(payload, row_id=int(sql_row["id"]))


def _journal_alive(client: Any, journal_id: int) -> bool:
    """True, če temeljnica še obstaja v Minimaxu (ne 404)."""
    if journal_id <= 0:
        return False
    try:
        detail = client.journal(int(journal_id))
    except Exception as exc:
        text = str(exc).casefold()
        if "404" in text or "not found" in text or "ni najden" in text:
            return False
        # omrežna napaka — raje ne briši ID
        return True
    if not isinstance(detail, Mapping):
        return False
    try:
        jid = int(detail.get("JournalId") or detail.get("ID") or detail.get("Id") or 0)
    except (TypeError, ValueError):
        jid = 0
    return jid > 0


def reset_missing_minimax_journals(
    db: Database,
    org_id: str | int,
    *,
    ir_rows: Sequence[Mapping[str, Any]] | None = None,
    pr_rows: Sequence[Mapping[str, Any]] | None = None,
    progress: ProgressCb | None = None,
) -> dict[str, int]:
    """
    Če SQL pravi synced / ima JournalId, a v Minimaxu osnutka ni (404),
    počisti ID in nastavi ready — naslednji sync jih znova doda.
    """
    ir_src = list(ir_rows) if ir_rows is not None else list(db.list_ir())
    pr_src = list(pr_rows) if pr_rows is not None else list(db.list_pr())
    candidates = [( "IR", r) for r in ir_src] + [("PR", r) for r in pr_src]
    stats = {"checked": 0, "reset": 0, "alive": 0}
    if not candidates:
        return stats
    _progress(progress, "Preverjam osnutke v Minimaxu …", 0, len(candidates))
    client = open_minimax_client(org_id)
    for index, (kind, row) in enumerate(candidates, start=1):
        jid = _row_minimax_journal_id(row)
        st = str(row.get("sync_status") or "")
        if jid <= 0 and st != SYNC_SYNCED:
            continue
        stats["checked"] += 1
        _progress(
            progress,
            f"Preverjam {kind} {normalize_text(row.get('document_no')) or row.get('id')} …",
            index - 1,
            len(candidates),
        )
        if jid > 0 and _journal_alive(client, jid):
            stats["alive"] += 1
            continue
        # synced brez ID ali mrtvi ID → spet oddaj
        _clear_minimax_journal_id(db, kind, row)
        try:
            db.set_row_sync(kind, int(row["id"]), SYNC_READY)
        except Exception:
            logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:372)", exc_info=True)
        stats["reset"] += 1
    _progress(progress, f"Ponovno za oddajo: {stats['reset']}", len(candidates), len(candidates))
    return stats


def _period_bounds(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    """Razpon po datumu temeljnice.

    IR: datum listine (sicer knjiženja). PR: datum knjiženja (sicer listine)
    in datum prejema — starejši osnutki so datirani na prejem.
    """

    def _day(row: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            day = str(row.get(key) or "")[:10]
            if len(day) == 10 and day[4] == "-":
                return day
        return ""

    dates: list[str] = []
    for row in ir_rows:
        dates.append(_day(row, "document_date", "booking_date"))
    for row in pr_rows:
        dates.append(_day(row, "booking_date", "document_date"))
        dates.append(_day(row, "received_date"))
    dates = [d for d in dates if d]
    if not dates:
        return "", ""
    return min(dates), max(dates)


def _index_existing_journals(
    client: Any,
    *,
    date_from: str,
    date_to: str,
    books: set[str],
    progress: ProgressCb | None = None,
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str, str], int]]:
    """
    Indeks:
      - (knjiga, #pr106) → JournalId  (Projest unikaten ključ)
      - (knjiga, listina, znesek) → JournalId  (stari osnutki brez #PR)
    """
    by_tag: dict[tuple[str, str], int] = {}
    by_doc_amt: dict[tuple[str, str, str], int] = {}
    if not date_from or not date_to:
        return by_tag, by_doc_amt
    try:
        summaries = client.journals(date_from=date_from, date_to=date_to)
    except Exception:
        logging.getLogger(__name__).warning("Minimax: seznam temeljnic %s–%s ni dosegljiv (preverba dvojnikov preskočena)", date_from, date_to, exc_info=True)
        return by_tag, by_doc_amt

    count = len(summaries)
    for index, summary in enumerate(summaries, start=1):
        if index == 1 or index % 20 == 0 or index == count:
            _progress(
                progress,
                f"Preverjam obstoječe temeljnice v Minimaxu {index}/{count} …",
                index,
                count,
            )
        try:
            jid = int(summary.get("JournalId") or summary.get("ID") or summary.get("Id") or 0)
        except (TypeError, ValueError):
            jid = 0
        if jid <= 0:
            continue
        book = ""
        try:
            book = str(client.journal_book_code(summary) or "").upper()
        except Exception:
            book = ""
        if book in {"IR", "PR", "DI"} and book not in books:
            continue
        desc = str(summary.get("Description") or summary.get("Notes") or "")
        tags: set[str] = set()
        for m in re.findall(r"#((?:PR|IR)\d+)\b", desc, flags=re.I):
            tags.add(_norm_ref(f"#{m}"))
        try:
            detail = client.journal(jid)
        except Exception:
            detail = None
        if detail is not None:
            book = str(client.journal_book_code(detail) or book).upper()
        if book not in books:
            continue
        doc_refs: set[str] = set()
        amount = "0.00"
        if isinstance(detail, Mapping):
            det_desc = str(detail.get("Description") or "")
            for m in re.findall(r"#((?:PR|IR)\d+)\b", det_desc, flags=re.I):
                tags.add(_norm_ref(f"#{m}"))
            for entry in detail.get("JournalEntries") or []:
                if not isinstance(entry, Mapping):
                    continue
                ed = str(entry.get("Description") or "")
                for m in re.findall(r"#((?:PR|IR)\d+)\b", ed, flags=re.I):
                    tags.add(_norm_ref(f"#{m}"))
                pref = entry.get("PaymentReference") or entry.get("DocumentReference")
                if pref:
                    doc_refs.add(_norm_ref(pref))
                try:
                    credit = float(entry.get("CreditInDomesticCurrency") or entry.get("Credit") or 0)
                    debit = float(entry.get("DebitInDomesticCurrency") or entry.get("Debit") or 0)
                    side = max(credit, debit)
                    if side > 0:
                        amount = f"{side:.2f}"
                except (TypeError, ValueError):
                    logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:485)", exc_info=True)
            for vat in detail.get("VatEntries") or []:
                if isinstance(vat, Mapping) and vat.get("Document"):
                    doc_refs.add(_norm_ref(vat.get("Document")))
        for tag in tags:
            by_tag.setdefault((book, tag), jid)
        for doc in doc_refs:
            if doc and amount != "0.00":
                by_doc_amt.setdefault((book, doc, amount), jid)
    return by_tag, by_doc_amt


def _strip_vat_if_journal_only(payload: dict[str, Any], sql_row: Mapping[str, Any]) -> dict[str, Any]:
    """Ne gre v knjigo (ni v DDV) → samo temeljnica, brez VatEntries."""
    if _is_journal_only_pr(sql_row):
        payload = dict(payload)
        payload["VatEntries"] = []
    return payload


def _repair_vat_listina(client: Any, journal_id: int, payload: Mapping[str, Any]) -> int:
    """Znova vstavi VatEntries z Notes=interna (brez ReportingType), da knjiga ne kaže Obracun;."""
    wanted = [dict(v) for v in (payload.get("VatEntries") or []) if isinstance(v, Mapping)]
    if not wanted:
        return 0
    try:
        detail = client.get(f"orgs/{client.organisation_id}/journals/{int(journal_id)}")
    except Exception:
        logging.getLogger(__name__).warning("Minimax: temeljnica %s ni berljiva", journal_id, exc_info=True)
        return 0
    existing = list(detail.get("VatEntries") or []) if isinstance(detail, Mapping) else []
    ok = True
    if len(existing) != len(wanted):
        ok = False
    else:
        for vat, want in zip(existing, wanted):
            if not isinstance(vat, Mapping):
                ok = False
                break
            if str(vat.get("Notes") or "").strip() != str(want.get("Notes") or "").strip():
                ok = False
                break
            if str(vat.get("Document") or "").strip() != str(want.get("Document") or "").strip():
                ok = False
                break
            if vat.get("ReportingType"):
                ok = False
                break
    if ok:
        return 0
    for vat in existing:
        if not isinstance(vat, Mapping):
            continue
        vid = vat.get("VatEntryId") or vat.get("ID") or vat.get("Id")
        if not vid:
            continue
        try:
            client.delete(f"orgs/{client.organisation_id}/journals/{int(journal_id)}/vat/{int(vid)}")
        except Exception:
            logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:543)", exc_info=True)
    added = 0
    for vat_entry in wanted:
        vat_payload = dict(vat_entry)
        vat_payload["Journal"] = {"ID": int(journal_id)}
        vat_payload.pop("ReportingType", None)
        vat_payload.pop("VatEntryId", None)
        vat_payload.pop("RowVersion", None)
        notes = str(vat_payload.get("Notes") or "").strip()
        if notes:
            vat_payload["Notes"] = notes[:250]
        else:
            vat_payload.pop("Notes", None)
        client.post(
            f"orgs/{client.organisation_id}/journals/{int(journal_id)}/vat",
            vat_payload,
        )
        added += 1
    return added


def push_journals_as_drafts(
    db: Database,
    org_id: str | int,
    *,
    ir_rows: Sequence[Mapping[str, Any]] | None = None,
    pr_rows: Sequence[Mapping[str, Any]] | None = None,
    mark_synced: bool = True,
    progress: ProgressCb | None = None,
) -> JournalPushResult:
    """
    Pošlji IR/PR kot osnutne temeljnice (Status=O) prek Minimax API.
    Ne podvaja: če listina že obstaja v Minimaxu (ali raw.minimax_journal_id),
    označi synced in preskoči POST.
    """
    ensure_kirkpr_on_path()
    result = JournalPushResult()
    _progress(progress, "Prijava Minimax API …", 0, 0)
    client = open_minimax_client(org_id)

    def _needs_push(kind: str, row: Mapping[str, Any]) -> bool:
        """Oddaj, če ni v MM; error/retry tudi če temeljnica obstaja (dopolni DDV)."""
        st = str(row.get("sync_status") or "")
        jid = _row_minimax_journal_id(row)
        alive = bool(jid > 0 and _journal_alive(client, jid))
        if st == SYNC_ERROR:
            return True
        if st == SYNC_SYNCED and alive:
            return False
        if jid > 0 and not alive:
            _clear_minimax_journal_id(db, kind, row)
            try:
                db.set_row_sync(kind, int(row["id"]), SYNC_READY)
            except Exception:
                logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:597)", exc_info=True)
            return True
        if st == SYNC_SYNCED and not alive:
            _clear_minimax_journal_id(db, kind, row)
            try:
                db.set_row_sync(kind, int(row["id"]), SYNC_READY)
            except Exception:
                logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:604)", exc_info=True)
            return True
        return True

    ir_src = [r for r in (ir_rows or []) if _needs_push("IR", r)]
    pr_src = [r for r in (pr_rows or []) if _needs_push("PR", r)]
    if not ir_src and not pr_src:
        result.message = "Ni IR/PR vrstic za API oddajo (vse že v Minimaxu ali prazno)."
        return result

    # osveži vrstice po clear (raw_json / sync_status)
    def _reload(kind: str, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            rid = int(row.get("id") or 0)
            fresh = db.get_ir(rid) if kind == "IR" else db.get_pr(rid)
            out.append(dict(fresh or row))
        return out

    ir_src = _reload("IR", list(ir_src))
    pr_src = _reload("PR", list(pr_src))

    total = len(ir_src) + len(pr_src)
    done = 0
    try:
        _progress(progress, "Osvežujem šifrante …", 0, total)
        client.refresh_references()
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:632)", exc_info=True)

    d_from, d_to = _period_bounds(ir_src, pr_src)
    books: set[str] = set()
    if ir_src:
        books.add("IR")
        books.add("DI")  # Integra Paragoni 100* → Minimax DI
    if pr_src:
        books.add("PR")
    _progress(progress, "Preverjam obstoječe temeljnice (brez podvajanj) …", 0, total)
    existing_tags, existing_doc_amt = _index_existing_journals(
        client, date_from=d_from, date_to=d_to, books=books, progress=progress
    )

    kir, kpr = _sql_rows_to_kir_kpr(db, ir_src, pr_src)

    def _already_there(book: str, sql_row: Mapping[str, Any]) -> int:
        saved = _row_minimax_journal_id(sql_row)
        if saved > 0:
            if _journal_alive(client, saved):
                return saved
            _clear_minimax_journal_id(
                db, "IR" if book.upper() in {"IR", "DI"} else book, sql_row
            )
        # SQL IR vrstice: ključ #IR{id}; Minimax knjiga IR ali DI
        sql_key_book = "IR" if book.upper() in {"IR", "DI"} else book
        key = _row_unique_key(sql_key_book, sql_row)
        if key:
            mm_books = (
                {book.upper(), "IR", "DI"}
                if book.upper() in {"IR", "DI"}
                else {book.upper()}
            )
            for mm_book in mm_books:
                found = int(existing_tags.get((mm_book, key)) or 0)
                if found and _journal_alive(client, found):
                    return found
        # Stari osnutki (pred #PRid): listina + znesek (BKS 1565,40 ≠ 120,78)
        doc = _row_doc_ref(sql_row)
        if book.upper() == "PR" and _is_journal_only_pr(sql_row):
            amt = f"{float(decimal_value(sql_row.get('excluded'))):.2f}"
        else:
            total_vat = (
                decimal_value(sql_row.get("vat_22"))
                + decimal_value(sql_row.get("vat_95"))
                + decimal_value(sql_row.get("vat_5"))
            )
            net = (
                decimal_value(sql_row.get("net_taxable"))
                + decimal_value(sql_row.get("f76a"))
                + decimal_value(sql_row.get("eu_goods"))
                + decimal_value(sql_row.get("eu_services"))
                + decimal_value(sql_row.get("excluded"))
            )
            from trops_studio.pr_vat_flags import resolve_pr_vat_flags

            sa, _vd, _ = resolve_pr_vat_flags(sql_row)
            payable = net if sa else (net + total_vat)
            amt = f"{float(payable):.2f}"
        if doc and amt != "0.00":
            for mm_book in (
                {book.upper(), "IR", "DI"}
                if book.upper() in {"IR", "DI"}
                else {book.upper()}
            ):
                found = int(existing_doc_amt.get((mm_book, doc, amt)) or 0)
                if found and _journal_alive(client, found):
                    return found
        return 0

    def _journal_vat_books(journal_id: int) -> set[str]:
        try:
            detail = client.journal(journal_id)
        except Exception:
            logging.getLogger(__name__).warning("Minimax: DDV knjige temeljnice %s niso berljive", journal_id, exc_info=True)
            return set()
        vat = detail.get("VatEntries") if isinstance(detail, Mapping) else None
        if not isinstance(vat, list):
            return set()
        books: set[str] = set()
        for entry in vat:
            if not isinstance(entry, Mapping):
                continue
            book = str(entry.get("VatBook") or "").strip().upper()
            if book:
                books.add(book)
        return books

    def _missing_vat_entries(journal_id: int, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Vrni VatEntries iz payload-a, ki jih na temeljnici še ni (po VatBook)."""
        existing_books = _journal_vat_books(journal_id)
        missing: list[dict[str, Any]] = []
        for vat_entry in payload.get("VatEntries") or []:
            if not isinstance(vat_entry, Mapping):
                continue
            book = str(vat_entry.get("VatBook") or "").strip().upper()
            if book and book in existing_books:
                continue
            missing.append(dict(vat_entry))
        return missing

    def _format_vat_period_error(label: str, journal_id: int, exc: BaseException) -> str:
        text = str(exc)
        if "zaključenega obdobja" in text.casefold() or "zakljucenega obdobja" in text.casefold():
            return (
                f"{label}: temeljnica #{journal_id} je OK, DDV knjiga NE — "
                f"datum DDV je v zaključenem DDV obdobju v Minimaxu. "
                f"Odpri obdobje (ali popravi datum knjižbe/DDV) in ponovi sync; "
                f"temeljnica se ne bo podvojila."
            )
        return f"{label}: {exc}"

    def _try_add_vat_only(journal_id: int, payload: Mapping[str, Any]) -> int:
        """Dodaj manjkajoče VatEntries na obstoječo temeljnico. Vrne število dodanih."""
        missing = _missing_vat_entries(journal_id, payload)
        if not missing:
            # Če ni nobenega VatEntry-ja, poskusi vse (prvi dopolnitveni sync)
            if not _journal_vat_books(journal_id):
                missing = [dict(v) for v in (payload.get("VatEntries") or []) if isinstance(v, Mapping)]
        added = 0
        for vat_entry in missing:
            vat_payload = dict(vat_entry)
            vat_payload["Journal"] = {"ID": int(journal_id)}
            try:
                from minimax_api_client import _clean_vat_document  # type: ignore

                vat_payload["Document"] = _clean_vat_document(vat_payload.get("Document"))
            except Exception:
                logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:759)", exc_info=True)
            vat_payload.pop("ReportingType", None)
            notes = str(vat_payload.get("Notes") or "").strip()
            if notes:
                vat_payload["Notes"] = notes[:250]
            else:
                vat_payload.pop("Notes", None)
            client.post(
                f"orgs/{client.organisation_id}/journals/{int(journal_id)}/vat",
                vat_payload,
            )
            added += 1
        if added:
            try:
                client.scrub_vat_document_prefixes(int(journal_id))
            except Exception:
                logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:775)", exc_info=True)
        return added

    def _remember(book: str, sql_row: Mapping[str, Any], jid: int) -> None:
        if jid <= 0:
            return
        sql_key_book = "IR" if book.upper() in {"IR", "DI"} else book
        existing_tags[(book.upper(), _row_unique_key(sql_key_book, sql_row))] = jid
        doc = _row_doc_ref(sql_row)
        if book.upper() == "PR" and _is_journal_only_pr(sql_row):
            amt = f"{float(decimal_value(sql_row.get('excluded'))):.2f}"
            if doc:
                existing_doc_amt[(book.upper(), doc, amt)] = jid

    for sql_row, kir_row in zip(ir_src, kir):
        done += 1
        mm_type = str(kir_row.get("__journal_type__") or "IR").strip().upper() or "IR"
        label = normalize_text(sql_row.get("document_no")) or f"IR#{sql_row.get('id')}"
        _progress(progress, f"{mm_type} {done}/{total}: {label}", done - 1, total)
        try:
            root = _root_for_single_journal(book="IR", kir_row=kir_row)
            payload = client.prepare_journal_payload(root, status="O", vat_type_ir="")
            payload = _decorate_vat_listina(payload, sql_row)
            needs_vat = bool(payload.get("VatEntries"))

            existing_id = _already_there(mm_type, sql_row)
            if existing_id > 0:
                # DI/IR že obstaja brez DDV (prejšnji 409) → dopolni VatEntries
                if needs_vat and (
                    _missing_vat_entries(existing_id, payload) or not _journal_vat_books(existing_id)
                ):
                    _progress(
                        progress,
                        f"{mm_type} {done}/{total}: {label} (dopolnim DDV na #{existing_id})",
                        done - 1,
                        total,
                    )
                    try:
                        added = _try_add_vat_only(existing_id, payload)
                        if added:
                            result.ir_ok += 1
                        else:
                            result.ir_skipped += 1
                    except Exception as vat_exc:
                        result.ir_failed.append(_format_vat_period_error(label, existing_id, vat_exc))
                        if mark_synced and sql_row.get("id"):
                            _save_minimax_journal_id(db, "IR", sql_row, existing_id)
                            db.set_row_sync("IR", int(sql_row["id"]), SYNC_ERROR)
                        _progress(progress, f"{mm_type} {done}/{total}: {label}", done, total)
                        continue
                else:
                    result.ir_skipped += 1
                if mark_synced and sql_row.get("id"):
                    _save_minimax_journal_id(db, "IR", sql_row, existing_id)
                    _remember(mm_type, sql_row, existing_id)
                    db.set_row_sync("IR", int(sql_row["id"]), SYNC_SYNCED)
                _progress(
                    progress,
                    f"{mm_type} {done}/{total}: {label} (že v MM #{existing_id})",
                    done,
                    total,
                )
                continue

            response = client._send_journal_with_vat(payload)
            result.ir_ok += 1
            jid = 0
            try:
                jid = int(client._response_record_id(response, "JournalId") or 0)
            except Exception:
                jid = 0
            if mark_synced and sql_row.get("id"):
                if jid:
                    _save_minimax_journal_id(db, "IR", sql_row, jid)
                    _remember(mm_type, sql_row, jid)
                db.set_row_sync("IR", int(sql_row["id"]), SYNC_SYNCED)
        except Exception as exc:
            # Delni uspeh: »Temeljnica ID N je ustvarjena« → shrani ID, ne podvajaj
            m = re.search(r"Temeljnica ID (\d+)", str(exc))
            if m and sql_row.get("id"):
                jid = int(m.group(1))
                _save_minimax_journal_id(db, "IR", sql_row, jid)
                _remember(mm_type, sql_row, jid)
                # Poskusi takoj dopolniti DDV (npr. po popravku KnjigaDDV=IR)
                try:
                    root2 = _root_for_single_journal(book="IR", kir_row=kir_row)
                    payload2 = client.prepare_journal_payload(root2, status="O", vat_type_ir="")
                    payload2 = _decorate_vat_listina(payload2, sql_row)
                    if payload2.get("VatEntries") and not _journal_vat_books(jid):
                        _try_add_vat_only(jid, payload2)
                        if mark_synced:
                            db.set_row_sync("IR", int(sql_row["id"]), SYNC_SYNCED)
                        result.ir_ok += 1
                        _progress(progress, f"{mm_type} {done}/{total}: {label}", done, total)
                        continue
                except Exception as vat_exc:
                    result.ir_failed.append(_format_vat_period_error(label, jid, vat_exc))
                    if mark_synced and sql_row.get("id"):
                        db.set_row_sync("IR", int(sql_row["id"]), SYNC_ERROR)
                    _progress(progress, f"{mm_type} {done}/{total}: {label}", done, total)
                    continue
            result.ir_failed.append(f"{label}: {exc}")
            if mark_synced and sql_row.get("id"):
                try:
                    db.set_row_sync("IR", int(sql_row["id"]), SYNC_ERROR)
                except Exception:
                    logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:881)", exc_info=True)
        _progress(progress, f"{mm_type} {done}/{total}: {label}", done, total)

    for sql_row, kpr_row in zip(pr_src, kpr):
        done += 1
        label = normalize_text(sql_row.get("document_no")) or f"PR#{sql_row.get('id')}"
        _progress(progress, f"PR {done}/{total}: {label}", done - 1, total)
        try:
            root = _root_for_single_journal(book="PR", kpr_row=kpr_row)
            payload = client.prepare_journal_payload(root, status="O", vat_type_pr="")
            payload = _strip_vat_if_journal_only(payload, sql_row)
            payload = _decorate_vat_listina(payload, sql_row)
            needs_vat = bool(payload.get("VatEntries")) and not _is_journal_only_pr(sql_row)

            existing_id = _already_there("PR", sql_row)
            if existing_id > 0:
                _save_minimax_journal_id(db, "PR", sql_row, existing_id)
                _remember("PR", sql_row, existing_id)
                missing_vat = _missing_vat_entries(existing_id, payload) if needs_vat else []
                # SA: pogosto obstaja samo PR VatEntry — dopolni manjkajoči IR (polja 23–26)
                if needs_vat and (missing_vat or not _journal_vat_books(existing_id)):
                    _progress(
                        progress,
                        f"PR {done}/{total}: {label} (dopolnim DDV na #{existing_id})",
                        done - 1,
                        total,
                    )
                    added = _try_add_vat_only(existing_id, payload)
                    if added:
                        result.pr_ok += 1
                    else:
                        result.pr_skipped += 1
                    if mark_synced and sql_row.get("id"):
                        db.set_row_sync("PR", int(sql_row["id"]), SYNC_SYNCED if added else SYNC_ERROR)
                    if not added:
                        result.pr_failed.append(f"{label}: manjkajoči DDV zapisi niso bili dodani.")
                else:
                    # Obstoječa temeljnica: popravi listino (interna; listina) na VatEntries.
                    try:
                        _repair_vat_listina(client, existing_id, payload)
                    except Exception:
                        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:922)", exc_info=True)
                    result.pr_skipped += 1
                    if mark_synced and sql_row.get("id"):
                        db.set_row_sync("PR", int(sql_row["id"]), SYNC_SYNCED)
                    _progress(
                        progress,
                        f"PR {done}/{total}: {label} (že v MM #{existing_id})",
                        done,
                        total,
                    )
                continue

            response = client._send_journal_with_vat(payload)
            result.pr_ok += 1
            jid = 0
            try:
                jid = int(client._response_record_id(response, "JournalId") or 0)
            except Exception:
                jid = 0
            if mark_synced and sql_row.get("id"):
                if jid:
                    _save_minimax_journal_id(db, "PR", sql_row, jid)
                    _remember("PR", sql_row, jid)
                db.set_row_sync("PR", int(sql_row["id"]), SYNC_SYNCED)
        except Exception as exc:
            m = re.search(r"Temeljnica ID (\d+)", str(exc))
            jid = int(m.group(1)) if m else _row_minimax_journal_id(sql_row)
            if jid and sql_row.get("id"):
                _save_minimax_journal_id(db, "PR", sql_row, jid)
                _remember("PR", sql_row, jid)
                if _is_journal_only_pr(sql_row):
                    db.set_row_sync("PR", int(sql_row["id"]), SYNC_SYNCED)
                    result.pr_skipped += 1
                    _progress(
                        progress,
                        f"PR {done}/{total}: {label} (temeljnica #{jid}, brez DDV)",
                        done,
                        total,
                    )
                    continue
                result.pr_failed.append(_format_vat_period_error(label, jid, exc))
            else:
                result.pr_failed.append(f"{label}: {exc}")
            if mark_synced and sql_row.get("id"):
                try:
                    db.set_row_sync("PR", int(sql_row["id"]), SYNC_ERROR)
                except Exception:
                    logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_journals.py:969)", exc_info=True)
        _progress(progress, f"PR {done}/{total}: {label}", done, total)

    parts = [
        f"IR novo: {result.ir_ok}/{len(ir_src)}",
        f"PR novo: {result.pr_ok}/{len(pr_src)}",
    ]
    if result.ir_skipped or result.pr_skipped:
        parts.append(f"že v MM (preskočeno): IR {result.ir_skipped} / PR {result.pr_skipped}")
    fails = len(result.ir_failed) + len(result.pr_failed)
    if fails:
        parts.append(f"napak: {fails}")
    result.message = "Minimax API temeljnice (osnutki): " + ", ".join(parts) + "."
    return result
