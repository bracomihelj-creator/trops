"""Potrditev v SQL → sinhronizacija z Minimax (stranke API + journals API)."""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from trops_studio.db import Database
from trops_studio.minimax_parties import ensure_parties_for_journals, import_parties_to_minimax
from trops_studio.minimax_journals import push_journals_as_drafts, reset_missing_minimax_journals
from trops_studio.money import normalize_text
from trops_studio.parties_ensure import collect_firms_needing_minimax
from trops_studio.row_status import STATUS_SHRANJENO
from trops_studio.sync_state import SYNC_ERROR, SYNC_LOCAL, SYNC_READY, SYNC_SYNCED
from trops_studio.xml_export import export_minimax_xml_for_kirkpr

ProgressCb = Callable[[str, int, int], None]


def _progress(cb: ProgressCb | None, message: str, current: int = 0, total: int = 0) -> None:
    if cb:
        try:
            cb(message, current, total)
        except Exception:
            logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_sync.py:25)", exc_info=True)


@dataclass
class SyncResult:
    parties_ok: int = 0
    parties_failed: list[str] = field(default_factory=list)
    ir_marked: int = 0
    pr_marked: int = 0
    ir_api_ok: int = 0
    pr_api_ok: int = 0
    journal_failed: list[str] = field(default_factory=list)
    ir_path: Path | None = None
    pr_path: Path | None = None
    message: str = ""


def confirm_document(db: Database, kind: str, row_id: int) -> None:
    """Potrdi IR/PR v SQL: status Shranjeno + sync_status=ready + knjižbe."""
    kind_u = kind.upper()
    if kind_u == "IR":
        row = db.get_ir(row_id)
        if not row:
            raise ValueError(f"IR #{row_id} ne obstaja.")
        db.replace_journal_lines("IR", row_id, row)
        db.set_row_sync("IR", row_id, SYNC_READY, status=STATUS_SHRANJENO)
    else:
        row = db.get_pr(row_id)
        if not row:
            raise ValueError(f"PR #{row_id} ne obstaja.")
        db.replace_journal_lines("PR", row_id, row)
        db.set_row_sync("PR", row_id, SYNC_READY, status=STATUS_SHRANJENO)


def confirm_documents(db: Database, kind: str, row_ids: list[int]) -> int:
    n = 0
    for rid in row_ids:
        confirm_document(db, kind, int(rid))
        n += 1
    return n


def stage_missing_parties_in_sql(db: Database) -> int:
    """
    Dodaj manjkajoče firme samo v SQLite (sync_status=ready).
    Brez Minimax API — to stori sync_ready_to_minimax.
    """
    items = collect_firms_needing_minimax(db)
    staged = 0
    for raw in items:
        item = dict(raw)
        name = normalize_text(item.get("name"))
        if not name and not item.get("tax_number") and not item.get("vat_id"):
            continue
        party_id = item.get("party_id")
        payload = {
            "vat_id": item.get("vat_id") or "",
            "tax_number": item.get("tax_number") or "",
            "country": item.get("country") or "SI",
            "name": name or "Neznana stranka",
            "address": item.get("address") or "",
            "postal_code": item.get("postal_code") or "",
            "city": item.get("city") or "",
            "is_foreign": 1 if item.get("is_foreign") else 0,
            "source": "sql_stage",
            "sync_status": SYNC_READY,
            "minimax_code": "",
        }
        if party_id:
            existing = db.get_party(int(party_id))
            if existing and normalize_text(existing.get("minimax_code")):
                db.set_party_sync(int(party_id), SYNC_SYNCED)
                continue
            db.upsert_party(payload, party_id=int(party_id))
            db.set_party_sync(int(party_id), SYNC_READY)
        else:
            new_id = db.upsert_party(payload)
            db.set_party_sync(new_id, SYNC_READY)
        staged += 1
    return staged


def sync_ready_to_minimax(
    db: Database,
    org_id: str | int,
    *,
    output_dir: Path | str | None = None,
    company_label: str = "PROJEST",
    push_parties: bool = True,
    export_xml: bool = False,
    push_journals_api: bool = True,
    kinds: set[str] | None = None,
    ir_books: set[str] | None = None,
    ir_ids: set[int] | None = None,
    pr_ids: set[int] | None = None,
    progress: ProgressCb | None = None,
) -> SyncResult:
    """
    Sinhronizacija po potrditvi:
    1) stranke ready → Minimax customers API (če push_parties)
    2) IR/PR ready → Minimax journals API (osnutki Status=O)
    3) opcijsko še XML na disk (export_xml=True)

    Filtri (za spodnji sync knjige):
    - kinds: {"IR"}, {"PR"} ali None = oboje
    - ir_books: samo te knjige (Darila/Fitness/…)
    - ir_ids / pr_ids: omeji na te ID-je
    - progress(message, current, total) — total=0 = indeterminate
    """
    result = SyncResult()
    want_ir = kinds is None or "IR" in kinds
    want_pr = kinds is None or "PR" in kinds

    if push_parties:
        _progress(progress, "Stranke → Minimax …")
        ready_parties = db.list_parties_by_sync(SYNC_READY)
        if not ready_parties:
            ready_parties = [
                p
                for p in db.list_parties()
                if not normalize_text(p.get("minimax_code"))
                and normalize_text(p.get("sync_status") or SYNC_LOCAL) in {SYNC_READY, SYNC_LOCAL}
                and normalize_text(p.get("source")) in {"sql_stage", "manual", "ajpes", "local", ""}
            ]
        if ready_parties:
            items = []
            for p in ready_parties:
                items.append(
                    {
                        "party_id": p.get("id"),
                        "name": p.get("name"),
                        "vat_id": p.get("vat_id"),
                        "tax_number": p.get("tax_number"),
                        "country": p.get("country"),
                        "address": p.get("address"),
                        "postal_code": p.get("postal_code"),
                        "city": p.get("city"),
                        "is_foreign": p.get("is_foreign"),
                    }
                )
            try:
                imported = import_parties_to_minimax(
                    db, org_id, items, use_ajpes=False, allow_create=True
                )
                result.parties_ok = imported.created + imported.linked_existing + imported.koncni
                result.parties_failed = list(imported.failed)
                for p in ready_parties:
                    pid = int(p["id"])
                    fresh = db.get_party(pid)
                    if fresh and normalize_text(fresh.get("minimax_code")):
                        db.set_party_sync(pid, SYNC_SYNCED)
            except Exception as exc:
                result.parties_failed.append(str(exc))
                for p in ready_parties:
                    try:
                        db.set_party_sync(int(p["id"]), SYNC_ERROR)
                    except Exception:
                        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_sync.py:182)", exc_info=True)

    ir_ready: list = []
    pr_ready: list = []
    if want_ir:
        # ready + error + synced (synced preverimo: če osnutka v MM ni → znova dodaj)
        ir_ready = (
            db.list_ir_by_sync(SYNC_READY)
            + db.list_ir_by_sync(SYNC_ERROR)
            + db.list_ir_by_sync(SYNC_SYNCED)
        )
        if ir_books is not None:
            ir_ready = [r for r in ir_ready if str(r.get("book") or "") in ir_books]
        if ir_ids is not None:
            ir_ready = [r for r in ir_ready if int(r["id"]) in ir_ids]
    if want_pr:
        pr_ready = (
            db.list_pr_by_sync(SYNC_READY)
            + db.list_pr_by_sync(SYNC_ERROR)
            + db.list_pr_by_sync(SYNC_SYNCED)
        )
        if pr_ids is not None:
            pr_ready = [r for r in pr_ready if int(r["id"]) in pr_ids]

    if push_journals_api and (ir_ready or pr_ready):
        # najprej stranke iz teh vrstic (tudi pri sync knjige)
        _progress(progress, "Pripravljam stranke za temeljnice …")
        try:
            ensured = ensure_parties_for_journals(
                db, org_id, ir_rows=ir_ready, pr_rows=pr_ready, use_ajpes=False, allow_create=False
            )
            result.parties_ok += (
                ensured.created + ensured.linked_existing + ensured.koncni
            )
            result.parties_failed.extend(ensured.failed)
        except Exception as exc:
            result.parties_failed.append(f"Stranke pred temeljnicami: {exc}")

        # Če SQL pravi synced, a osnutka v MM ni (404) → reset + oddaja
        try:
            stale = reset_missing_minimax_journals(
                db,
                org_id,
                ir_rows=ir_ready,
                pr_rows=pr_ready,
                progress=progress,
            )
            if stale.get("reset"):
                if want_ir:
                    ir_ready = db.list_ir_by_sync(SYNC_READY) + db.list_ir_by_sync(SYNC_ERROR)
                    if ir_books is not None:
                        ir_ready = [r for r in ir_ready if str(r.get("book") or "") in ir_books]
                    if ir_ids is not None:
                        ir_ready = [r for r in ir_ready if int(r["id"]) in ir_ids]
                if want_pr:
                    pr_ready = db.list_pr_by_sync(SYNC_READY) + db.list_pr_by_sync(SYNC_ERROR)
                    if pr_ids is not None:
                        pr_ready = [r for r in pr_ready if int(r["id"]) in pr_ids]
        except Exception as exc:
            result.journal_failed.append(f"Preverjanje osnutkov: {exc}")

        _progress(
            progress,
            "Oddajam temeljnice …",
            0,
            len(ir_ready) + len(pr_ready),
        )
        pushed = push_journals_as_drafts(
            db,
            org_id,
            ir_rows=ir_ready,
            pr_rows=pr_ready,
            mark_synced=True,
            progress=progress,
        )
        result.ir_api_ok = pushed.ir_ok
        result.pr_api_ok = pushed.pr_ok
        result.journal_failed = list(pushed.ir_failed) + list(pushed.pr_failed)
        result.journals_skipped = int(getattr(pushed, "ir_skipped", 0) or 0) + int(getattr(pushed, "pr_skipped", 0) or 0)

    if export_xml and (ir_ready or pr_ready):
        _progress(progress, "Izvažam XML …")
        exported = export_minimax_xml_for_kirkpr(
            db,
            output_dir=output_dir,
            ir_rows=ir_ready or None,
            pr_rows=pr_ready or None,
            company_label=company_label,
            validate=True,
        )
        result.ir_path = exported.ir_path
        result.pr_path = exported.pr_path
        result.ir_marked = len(ir_ready)
        result.pr_marked = len(pr_ready)

    scope = "vse"
    if kinds == {"IR"}:
        books = ", ".join(sorted(ir_books)) if ir_books else "vse knjige"
        scope = f"IR ({books})"
    elif kinds == {"PR"}:
        scope = "PR"
    skipped = int(getattr(result, "journals_skipped", 0) or 0)
    parts = [
        f"Obseg: {scope}",
        f"Stranke API: {result.parties_ok}",
        f"IR novo: {result.ir_api_ok}",
        f"PR novo: {result.pr_api_ok}",
    ]
    if skipped:
        parts.append(f"že v MM (brez podvajanja): {skipped}")
    if result.ir_path:
        parts.append(f"XML IR/PR: {result.ir_marked}/{result.pr_marked}")
    if result.parties_failed:
        parts.append(f"napak strank: {len(result.parties_failed)}")
    if result.journal_failed:
        # Loči »temeljnica OK, DDV obdobje zaključeno« od pravih napak POST
        vat_period = [
            m for m in result.journal_failed if "zaključen" in m.casefold() or "zakljucen" in m.casefold()
        ]
        other = [m for m in result.journal_failed if m not in vat_period]
        if vat_period:
            parts.append(f"DDV obdobje zaključeno: {len(vat_period)}")
        if other:
            parts.append(f"napak temeljnic: {len(other)}")
    result.message = "Sinhronizacija Minimax: " + ", ".join(parts) + "."
    if result.ir_path:
        result.message += f"\n{result.ir_path}"
    if result.pr_path:
        result.message += f"\n{result.pr_path}"
    if result.journal_failed:
        # brez podvojenih vrstic
        uniq: list[str] = []
        seen: set[str] = set()
        for line in result.journal_failed:
            if line in seen:
                continue
            seen.add(line)
            uniq.append(line)
        result.message += "\n\n" + "\n".join(uniq[:15])
        if len(uniq) > 15:
            result.message += f"\n… še {len(uniq) - 15}"
    _progress(
        progress,
        "Končano.",
        max(result.ir_api_ok + result.pr_api_ok, 1),
        max(result.ir_api_ok + result.pr_api_ok, 1),
    )
    return result
