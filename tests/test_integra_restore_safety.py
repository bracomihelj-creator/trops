"""Točka 2: seje, zaklep, prekinitev povezav samo z oznako. Brez pravega SQL/RESTORE."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trops_studio.integra_sql import (
    BakBackupSet,
    IntegraSqlError,
    TropsSession,
    TropsSqlTarget,
    begin_restore_preview,
    format_trops_sessions,
    list_trops_sessions,
    restore_bak_to_trops,
    restore_lock,
    restore_lock_path,
)
import trops_studio.integra_sql as integra_sql


def _target() -> TropsSqlTarget:
    return TropsSqlTarget(
        server=r"BRACO-NUC\SQLEXPRESS",
        database="TROPS",
        data_file=r"C:\data\TROPS_Data.MDF",
        log_file=r"C:\data\TROPS_Log.LDF",
    )


def _chosen() -> BakBackupSet:
    return BakBackupSet(
        position=1,
        backup_type=1,
        database="TROPS",
        machine="BRACO-NUC",
        finish="2026-10-28 00:00:00",
    )


def _session() -> TropsSession:
    return TropsSession(
        session_id=52,
        login="braco",
        host="BRACO-NUC",
        program="Microsoft SQL Server Management Studio",
        login_time="2026-11-22 13:00:00",
    )


def _patch_common(monkeypatch, tmp_path, *, sessions=None, attached=True):
    bak = tmp_path / "INTEGRA.bak"
    bak.write_bytes(b"bak")
    safety = tmp_path / "TROPS_pred_restore.bak"
    safety.write_bytes(b"safety")
    queries: list[str] = []
    monkeypatch.setattr(integra_sql, "stage_bak_for_sql", lambda *a, **k: bak)
    monkeypatch.setattr(integra_sql, "read_bak_header", lambda *a, **k: [_chosen()])
    monkeypatch.setattr(integra_sql, "latest_full_backup_set", lambda sets: sets[0])
    monkeypatch.setattr(
        integra_sql, "filelist_from_bak", lambda *a, **k: ("TROPS_Data", "TROPS_Log")
    )
    monkeypatch.setattr(integra_sql, "trops_is_attached", lambda *a, **k: attached)
    monkeypatch.setattr(integra_sql, "backup_current_trops", lambda *a, **k: safety)
    monkeypatch.setattr(integra_sql, "list_trops_sessions", lambda *a, **k: list(sessions or []))
    monkeypatch.setattr(integra_sql, "restore_lock_path", lambda: tmp_path / "integra_restore.lock")

    def fake_sqlcmd(server, query, **kw):
        queries.append(query)
        return "Processed 1 pages"

    monkeypatch.setattr(integra_sql, "_sqlcmd_query", fake_sqlcmd)
    return bak, safety, queries


def test_list_sessions_parses_sqlcmd(monkeypatch):
    monkeypatch.setattr(integra_sql, "trops_is_attached", lambda t: True)

    def fake_sqlcmd(server, query, **kw):
        assert "sys.dm_exec_sessions" in query
        assert "@@SPID" in query
        return "52|braco|BRACO-NUC|SSMS|2026-11-22 13:00:00\n"

    monkeypatch.setattr(integra_sql, "_sqlcmd_query", fake_sqlcmd)
    sess = list_trops_sessions(_target())
    assert len(sess) == 1
    assert sess[0].session_id == 52
    assert sess[0].login == "braco"
    assert sess[0].host == "BRACO-NUC"
    assert "SPID 52" in format_trops_sessions(sess)


def test_list_sessions_empty_when_detached(monkeypatch):
    called = []
    monkeypatch.setattr(integra_sql, "trops_is_attached", lambda t: False)
    monkeypatch.setattr(
        integra_sql, "_sqlcmd_query", lambda *a, **k: called.append(a) or ""
    )
    assert list_trops_sessions(_target()) == []
    assert called == []


def test_restore_refuses_sessions_without_flag(monkeypatch, tmp_path):
    bak, _safety, queries = _patch_common(monkeypatch, tmp_path, sessions=[_session()])
    with pytest.raises(IntegraSqlError, match="aktivne seje"):
        restore_bak_to_trops(bak, _target(), disconnect_sessions=False)
    assert not any("RESTORE DATABASE" in q for q in queries)
    assert not any("ROLLBACK IMMEDIATE" in q for q in queries)


def test_restore_kills_sessions_only_with_flag(monkeypatch, tmp_path):
    bak, safety, queries = _patch_common(monkeypatch, tmp_path, sessions=[_session()])
    result = restore_bak_to_trops(bak, _target(), disconnect_sessions=True)
    restore_q = next(q for q in queries if "RESTORE DATABASE" in q)
    assert "ROLLBACK IMMEDIATE" in restore_q
    assert result.safety_backup == safety


def test_restore_no_rollback_when_no_sessions(monkeypatch, tmp_path):
    bak, _safety, queries = _patch_common(monkeypatch, tmp_path, sessions=[])
    restore_bak_to_trops(bak, _target(), disconnect_sessions=False)
    restore_q = next(q for q in queries if "RESTORE DATABASE" in q)
    assert "SET SINGLE_USER" in restore_q
    assert "ROLLBACK IMMEDIATE" not in restore_q


def test_lock_blocks_second_restore(monkeypatch, tmp_path):
    bak, _safety, queries = _patch_common(monkeypatch, tmp_path, sessions=[])
    with restore_lock(holder="test"):
        with pytest.raises(IntegraSqlError, match="že teče"):
            restore_bak_to_trops(bak, _target())
    assert not any("RESTORE DATABASE" in q for q in queries)
    restore_bak_to_trops(bak, _target())
    assert any("RESTORE DATABASE" in q for q in queries)


def test_stale_lock_is_replaced(monkeypatch, tmp_path):
    bak, _safety, queries = _patch_common(monkeypatch, tmp_path, sessions=[])
    lock = tmp_path / "integra_restore.lock"
    stale = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    lock.write_text(
        json.dumps({"holder": "old", "started": stale, "pid": 1}),
        encoding="utf-8",
    )
    restore_bak_to_trops(bak, _target())
    assert any("RESTORE DATABASE" in q for q in queries)
    assert not lock.exists()


def test_preview_does_not_restore(monkeypatch, tmp_path):
    bak, safety, queries = _patch_common(monkeypatch, tmp_path, sessions=[_session()])
    preview = begin_restore_preview(bak, _target())
    assert preview.sessions[0].session_id == 52
    assert preview.safety_backup == safety
    assert preview.backup_set.position == 1
    assert not any("RESTORE DATABASE" in q for q in queries)
    assert not any("ROLLBACK IMMEDIATE" in q for q in queries)


def test_preview_blocked_by_active_lock(monkeypatch, tmp_path):
    bak, _safety, _queries = _patch_common(monkeypatch, tmp_path, sessions=[])
    with restore_lock(holder="test"):
        with pytest.raises(IntegraSqlError, match="že teče"):
            begin_restore_preview(bak, _target())


def test_existing_safety_skips_second_backup(monkeypatch, tmp_path):
    bak, safety, _queries = _patch_common(monkeypatch, tmp_path, sessions=[])
    called = []
    monkeypatch.setattr(
        integra_sql,
        "backup_current_trops",
        lambda *a, **k: called.append(True) or safety,
    )
    result = restore_bak_to_trops(
        bak,
        _target(),
        existing_safety=safety,
        safety_backup=False,
    )
    assert called == []
    assert result.safety_backup == safety
