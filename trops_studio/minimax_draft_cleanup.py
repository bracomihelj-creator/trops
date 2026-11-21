"""Brisanje Minimax osnutkov temeljnic za obdobje (Status=O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from trops_studio.minimax_runtime import open_minimax_client


@dataclass
class DraftCleanupResult:
    scanned: int = 0
    candidates: int = 0
    deleted: int = 0
    failed: list[str] = field(default_factory=list)
    message: str = ""


def delete_draft_journals_for_period(
    org_id: str | int,
    *,
    date_from: str,
    date_to: str,
    books: set[str] | None = None,
    only_without_vat: bool = False,
    progress: Callable[[str], None] | None = None,
) -> DraftCleanupResult:
    """
    Izbriši Minimax osnutke (Status=O) v datumu od–do.
    Privzeto IR+PR; only_without_vat=True = samo tiste brez DDV-vrstic
    (npr. po neuspešnem 409).
    """
    result = DraftCleanupResult()
    wanted = {str(b).strip().upper() for b in (books or {"IR", "PR"}) if str(b).strip()}
    client = open_minimax_client(org_id)
    if progress:
        progress(f"Berem temeljnice {date_from} … {date_to} …")
    rows = client.journals(date_from=date_from[:10], date_to=date_to[:10])
    result.scanned = len(rows)

    for row in rows:
        jid = None
        try:
            jid = int(row.get("ID") or row.get("JournalId") or row.get("Id") or 0)
        except (TypeError, ValueError):
            jid = 0
        if jid <= 0:
            continue
        status = client.journal_status_code(row)
        if status and status != "O":
            continue
        book = client.journal_book_code(row)
        # Seznam včasih nima tipa — preveri detajl
        detail = None
        if book not in wanted or not status:
            try:
                detail = client.journal(jid)
            except Exception as exc:
                result.failed.append(f"{jid}: branje {exc}")
                continue
            status = client.journal_status_code(detail) or status
            book = client.journal_book_code(detail) or book
            if status != "O":
                continue
            if book not in wanted:
                continue
        if only_without_vat:
            if detail is None:
                try:
                    detail = client.journal(jid)
                except Exception as exc:
                    result.failed.append(f"{jid}: branje DDV {exc}")
                    continue
            vat = detail.get("VatEntries") if isinstance(detail, dict) else None
            if isinstance(vat, list) and len(vat) > 0:
                continue
        result.candidates += 1
        try:
            if progress:
                progress(f"Brišem osnutek {book} ID {jid} …")
            client.delete_journal(jid)
            result.deleted += 1
        except Exception as exc:
            result.failed.append(f"{book} {jid}: {exc}")

    result.message = (
        f"Osnutki {date_from}–{date_to}: pregledanih {result.scanned}, "
        f"kandidatov {result.candidates}, izbrisanih {result.deleted}"
        + (f", napak {len(result.failed)}" if result.failed else "")
        + "."
    )
    return result


def reset_ir_error_to_ready(db: Any, *, books: set[str] | None = None) -> int:
    """Po neuspelem syncu: IR error → ready (za ponovno oddajo)."""
    from trops_studio.sync_state import SYNC_ERROR, SYNC_READY

    rows = db.list_ir_by_sync(SYNC_ERROR)
    n = 0
    for row in rows:
        if books and str(row.get("book") or "") not in books:
            continue
        db.set_row_sync("IR", int(row["id"]), SYNC_READY)
        n += 1
    return n
