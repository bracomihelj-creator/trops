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


def test_new_party_with_existing_tax_asks_before_overwrite(empty_motor):
    """5.1: »Nova stranka« z obstoječo davčno ne prepiše tiho; s potrditvijo posodobi; nova davčna doda."""
    m = empty_motor
    first = m.party_save({"name": "Prva d.o.o.", "tax_number": "12345678", "country": "SI", "city": "Ljubljana"})
    assert first["ok"] is True
    n0 = len(m.db.list_parties())
    dup = m.party_save({"name": "Druga d.o.o.", "tax_number": "12345678", "country": "SI"})
    assert dup["ok"] is False and dup["duplicate"] is True
    assert dup["existing"]["id"] == first["id"]
    assert m.db.get_party(first["id"])["name"] == "Prva d.o.o."
    assert len(m.db.list_parties()) == n0
    upd = m.party_save({"name": "Druga d.o.o.", "tax_number": "12345678", "country": "SI", "confirm_existing": True})
    assert upd["ok"] is True and upd["id"] == first["id"]
    assert m.db.get_party(first["id"])["name"] == "Druga d.o.o."
    new = m.party_save({"name": "Tretja d.o.o.", "tax_number": "87654321", "country": "SI"})
    assert new["ok"] is True and new["id"] != first["id"]
    assert len(m.db.list_parties()) == n0 + 1
    assert m.boot()["summary"]["parties"] == n0 + 1


def test_edit_existing_party_needs_no_confirm(empty_motor):
    m = empty_motor
    first = m.party_save({"name": "Ena d.o.o.", "tax_number": "11223344", "country": "SI"})
    res = m.party_save({"id": first["id"], "name": "Ena d.o.o.", "tax_number": "11223344", "country": "SI", "notes": "x"})
    assert res["ok"] is True and m.db.get_party(first["id"])["notes"] == "x"


def test_account_map_info_shows_shared_maps(empty_motor):
    """5.1 (2A): okno Konti Trops → Minimax prikaže tudi skupne preslikave (prazen Org_ID), tuje org pa ne."""
    m = empty_motor
    m.db.upsert_account_code_maps({"7622": "7620"}, org_id="", source="default")
    m.db.upsert_account_code_maps({"4061": "4060"}, org_id="999999", source="default")
    m.active_company = {"Zšt": "99", "Kratko ime": "Test 99", "Org_ID": "123456"}
    m.db.upsert_account_code_maps({"4191": "4190"}, org_id="123456", source="user")
    info = m.account_map_info()
    got = {(x["trops_code"], bool(x["shared"])) for x in info["saved"]}
    assert ("7622", True) in got and ("4191", False) in got
    assert all(x["trops_code"] != "4061" for x in info["saved"])


def test_default_maps_not_seeded_without_org(empty_motor):
    """5.1 (2B): brez znanega Org_ID se privzete preslikave ne zapišejo v bazo (veljajo pa enako)."""
    from trops_studio import account_choices as ac

    db = empty_motor.db
    ac._MAP_CACHE.clear()
    maps = ac.load_account_code_maps(db, None)
    assert maps["7622"] == "7620" and maps == {**ac.TROPS_TO_MINIMAX_DEFAULTS, **maps}
    assert db.list_account_code_maps(None) == []
    ac._MAP_CACHE.clear()
    maps2 = ac.load_account_code_maps(db, "123456")
    assert maps2 == maps
    assert {m["org_id"] for m in db.list_account_code_maps(None)} == {"123456"}
    ac._MAP_CACHE.clear()
