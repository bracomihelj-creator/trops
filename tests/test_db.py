"""Brisanje obdobja in shranjevanje brez podvajanja (sintetični podatki)."""
from __future__ import annotations

from datetime import date

import pytest

import motor


def _ir(no: str, d: str | None, **kw):
    row = {"book": "Fakture", "seq": 1, "document_no": no, "party_name": "Kupec d.o.o.", "net": "100.00",
           "base_22": "100.00", "vat_22": "22.00", "total": "122.00", "account": "7620", "status": "OSNUTEK"}
    if d:
        row["document_date"] = d
    row.update(kw)
    return row


def test_delete_period_keeps_undated_and_other_periods(empty_motor):
    db = empty_motor.db
    in_id = db.upsert_ir(_ir("A-1", "2026-10-05"))
    out_id = db.upsert_ir(_ir("A-2", "2026-09-30"))
    nodate_id = db.upsert_ir(_ir("A-3", None))
    pr_in = db.upsert_pr({"document_no": "P-1", "received_date": "2026-10-10", "supplier_name": "Dobavitelj"})
    pr_nodate = db.upsert_pr({"document_no": "P-2", "supplier_name": "Dobavitelj"})

    prev = empty_motor.delete_preview()
    assert (prev["ir"], prev["pr"]) == (1, 1)

    res = db.delete_ir_pr_for_period(date(2026, 10, 1), date(2026, 10, 31))
    assert res == {"ir": 1, "pr": 1}
    ids_ir = {r["id"] for r in db.list_ir()}
    ids_pr = {r["id"] for r in db.list_pr()}
    assert in_id not in ids_ir and {out_id, nodate_id} <= ids_ir
    assert pr_in not in ids_pr and pr_nodate in ids_pr


def test_delete_period_action_requires_confirm(empty_motor):
    import host

    with pytest.raises(motor.BadRequest):
        host.dispatch_action(empty_motor, {"name": "delete_import_period"})


def test_save_row_updates_without_duplicate(empty_motor):
    rid = empty_motor.db.upsert_ir(_ir("B-1", "2026-10-02"))
    before = len(empty_motor.db.list_ir())
    res = empty_motor.save_row("IR", {"id": str(rid), "party_name": "Novi kupec d.o.o."})
    assert res.get("ok", True) is not False
    rows = empty_motor.db.list_ir()
    assert len(rows) == before
    assert empty_motor.get_row("IR", rid)["row"]["party_name"] == "Novi kupec d.o.o."


def test_save_new_row_inserts_once(empty_motor):
    before = len(empty_motor.db.list_ir())
    empty_motor.save_row("IR", _ir("C-1", "2026-10-03"))
    assert len(empty_motor.db.list_ir()) == before + 1


def test_unchanged_save_keeps_sync_status(empty_motor):
    rid = empty_motor.db.upsert_ir(_ir("D-1", "2026-10-04", sync_status="synced"))
    row = empty_motor.get_row("IR", rid)["row"]
    form = {k: row[k] for k in ("document_no", "party_name", "account", "book")}
    form.update({"id": rid, "net": "100", "total": "122,00", "document_date": "2026-10-04"})
    empty_motor.save_row("IR", form)
    assert empty_motor.get_row("IR", rid)["row"]["sync_status"] == "synced"
    empty_motor.save_row("IR", dict(form, notes="sprememba"))
    assert empty_motor.get_row("IR", rid)["row"]["sync_status"] == "local"


def test_odznaci_clears_backend_selection(empty_motor):
    a = empty_motor.db.upsert_ir(_ir("E-1", "2026-10-06"))
    b = empty_motor.db.upsert_ir(_ir("E-2", "2026-10-07"))
    empty_motor.set_filters({"ir_books": {"Fakture": True}})
    empty_motor.refresh_all()
    empty_motor.set_chk_all("IR", True, None)
    assert {r["id"] for r in empty_motor.list_ir()["rows"] if r.get("checked")} == {a, b}
    empty_motor.set_chk_all("IR", False, None)
    assert not [r for r in empty_motor.list_ir()["rows"] if r.get("checked")]


def test_confirm_without_ids_is_bad_request(empty_motor):
    with pytest.raises(motor.BadRequest):
        empty_motor.confirm_selected("IR", [])


@pytest.mark.parametrize("bad", ["abc", "", None, "1;DROP"])
def test_parse_id_rejects_invalid(bad):
    with pytest.raises(motor.BadRequest):
        motor.parse_id(bad)


def test_email_send_requires_confirm(empty_motor):
    with pytest.raises(motor.BadRequest):
        empty_motor.ddvo_email_send({"to": "a@b.si", "subject": "x"})
