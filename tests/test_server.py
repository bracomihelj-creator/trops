"""HTTP strežnik: avtentikacija, enoten format napak, 400/404 JSON, ozadne naloge."""
from __future__ import annotations

import http.client
import json
import threading
import time

import pytest


@pytest.fixture()
def server(empty_motor):
    import host

    srv = host.AppServer()
    srv.motor = empty_motor
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _req(srv, method, path, body=None, auth=True, host_header=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=20)
    headers = {"Host": host_header or srv.allowed_host}
    if auth:
        headers["Cookie"] = f"trops5={srv.token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        return r.status, json.loads(raw.decode("utf-8")), r
    except ValueError:
        return r.status, raw, r


def test_requires_session(server):
    code, data, _ = _req(server, "GET", "/api/boot", auth=False)
    assert code == 403 and data["ok"] is False


def test_rejects_foreign_host(server):
    code, _, _ = _req(server, "GET", "/api/boot", host_header="evil.example:80")
    assert code == 403


def test_ticket_sets_cookie(server):
    code, body, r = _req(server, "GET", f"/?ticket={server.token}", auth=False)
    assert code == 200 and b"<html" in body.lower()
    assert f"trops5={server.token}" in (r.getheader("Set-Cookie") or "")


def test_boot_ok(server):
    code, data, _ = _req(server, "GET", "/api/boot")
    assert code == 200 and data["ok"] is True and data["version"] == "5.0.00"


@pytest.mark.parametrize("path", ["/api/row?kind=IR&id=abc", "/api/row?kind=IR&id="])
def test_invalid_id_is_400_json(server, path):
    code, data, _ = _req(server, "GET", path)
    assert code == 400
    assert data["ok"] is False and data["error"] and data["msg"] == data["error"]


def test_missing_row_is_4xx_json(server):
    code, data, _ = _req(server, "GET", "/api/row?kind=IR&id=999999")
    assert 400 <= code < 500 and data["ok"] is False and data["error"]


def test_unknown_get_and_action_404(server):
    code, data, _ = _req(server, "GET", "/api/ne_obstaja")
    assert code == 404 and data["error"]
    code, data, _ = _req(server, "POST", "/api/action", {"name": "ne_obstaja"})
    assert code == 404 and data["ok"] is False and data["msg"]


def test_action_without_name_400(server):
    code, data, _ = _req(server, "POST", "/api/action", {})
    assert code == 400 and data["error"] == data["msg"]


def test_confirm_required_actions(server):
    for name in ("delete_import_period", "integra_restore", "ddvo_email_send"):
        code, data, _ = _req(server, "POST", "/api/action", {"name": name})
        assert code == 400 and "potrdit" in data["error"].lower()


def test_save_row_roundtrip(server):
    code, data, _ = _req(server, "POST", "/api/row/save", {"kind": "IR", "row": {"book": "Fakture", "document_no": "S-1", "document_date": "2026-10-01", "party_name": "X", "total": "10.00"}})
    assert code == 200 and data.get("ok", True) is not False
    rid = data["id"]
    code, data, _ = _req(server, "POST", "/api/row/save", {"kind": "IR", "row": {"id": rid, "party_name": "Y"}})
    assert code == 200
    _req(server, "POST", "/api/filters", {"filters": {"ir_books": {"Fakture": True}}})
    code, data, _ = _req(server, "GET", "/api/ir")
    assert [r["party_name"] for r in data["rows"] if r["document_no"] == "S-1"] == ["Y"]


def test_long_action_runs_as_job(server, monkeypatch):
    def fake_check():
        time.sleep(0.3)
        return {"ok": False, "error": "Manjka Org_ID."}

    monkeypatch.setattr(server.motor, "check_minimax_api", fake_check)
    code, start, _ = _req(server, "POST", "/api/action", {"name": "check_api"})
    assert code == 200 and start["job_id"]
    # Med tekom: druga naloga je zavrnjena
    code2, busy, _ = _req(server, "POST", "/api/action", {"name": "check_api"})
    assert code2 in (400, 409) and busy["ok"] is False
    for _ in range(50):
        code, job, _ = _req(server, "GET", f"/api/job?id={start['job_id']}")
        if job["state"] != "running":
            break
        time.sleep(0.1)
    assert job["state"] == "error" and job["ok"] is False
    assert job["result"]["error"] == "Manjka Org_ID." and job["result"]["msg"] == "Manjka Org_ID."


def test_unknown_job_404(server):
    code, data, _ = _req(server, "GET", "/api/job?id=nope")
    assert code == 404 and data["error"]


def test_companies_warning_when_empty(server):
    server.motor.companies = []
    code, data, _ = _req(server, "GET", "/api/companies")
    assert code == 200 and data["warning"]
