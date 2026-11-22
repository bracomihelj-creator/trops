from __future__ import annotations

from pathlib import Path

import pytest

from trops_studio.integra_sql import (
    IntegraSqlError,
    TropsSqlTarget,
    discover_trops_targets,
    preferred_trops_target,
    read_trops_dsn_server,
    resolve_integra_sql_server,
)


DSN = r"BRACO-NUC\SQLEXPRESS"
DEFAULT = "BRACO-NUC"


def test_read_dsn_from_wow6432node():
    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def open_key(hive, sub):
        if sub.endswith(r"WOW6432Node\ODBC\ODBC.INI\Trops"):
            return _Key()
        raise OSError(2, "not found")

    def query_value(key, name):
        assert name == "Server"
        return (DSN, 1)

    assert read_trops_dsn_server(_open_key=open_key, _query_value=query_value) == DSN


def test_settings_override_dsn(monkeypatch):
    from trops_studio import config as cfg

    monkeypatch.setenv("TROPS_INTEGRA_SQL_SERVER", "")
    # empty env is still "set"; resolve treats blank as missing
    monkeypatch.delenv("TROPS_INTEGRA_SQL_SERVER", raising=False)
    monkeypatch.setitem(cfg.SETTINGS, "integra_sql_server", r"SETTINGS\INSTANCE")
    monkeypatch.setattr(
        "trops_studio.integra_sql.read_trops_dsn_server", lambda: DSN
    )
    server, source = resolve_integra_sql_server()
    assert server == r"SETTINGS\INSTANCE"
    assert source == "settings"


def test_env_overrides_settings_and_dsn(monkeypatch):
    from trops_studio import config as cfg

    monkeypatch.setitem(cfg.SETTINGS, "integra_sql_server", r"SETTINGS\INSTANCE")
    monkeypatch.setenv("TROPS_INTEGRA_SQL_SERVER", r"ENV\INSTANCE")
    monkeypatch.setattr(
        "trops_studio.integra_sql.read_trops_dsn_server", lambda: DSN
    )
    server, source = resolve_integra_sql_server()
    assert server == r"ENV\INSTANCE"
    assert source == "settings"


def test_dsn_used_when_settings_empty(monkeypatch):
    from trops_studio import config as cfg

    monkeypatch.delenv("TROPS_INTEGRA_SQL_SERVER", raising=False)
    monkeypatch.setitem(cfg.SETTINGS, "integra_sql_server", "")
    monkeypatch.setattr(
        "trops_studio.integra_sql.read_trops_dsn_server", lambda: DSN
    )
    server, source = resolve_integra_sql_server()
    assert server == DSN
    assert source == "DSN Trops"


def test_missing_dsn_and_settings_raises_without_fallback(monkeypatch):
    from trops_studio import config as cfg

    monkeypatch.delenv("TROPS_INTEGRA_SQL_SERVER", raising=False)
    monkeypatch.setitem(cfg.SETTINGS, "integra_sql_server", "")
    monkeypatch.setattr(
        "trops_studio.integra_sql.read_trops_dsn_server", lambda: None
    )
    with pytest.raises(IntegraSqlError, match="ne preklopi na drugo instanco"):
        resolve_integra_sql_server()


def test_discover_queries_only_chosen_server(monkeypatch):
    calls: list[str] = []

    def fake_sqlcmd(server, query, **kwargs):
        calls.append(server)
        if "sys.databases" in query:
            return f"{DSN}|TROPS\n{DSN}|TROPS_OLD\n"
        if "sys.master_files" in query:
            return (
                f"{DSN}|TROPS|ROWS|C:\\data\\TROPS_Data.MDF\n"
                f"{DSN}|TROPS|LOG|C:\\data\\TROPS_Log.LDF\n"
            )
        raise AssertionError(query)

    monkeypatch.setattr(
        "trops_studio.integra_sql.resolve_integra_sql_server",
        lambda: (DSN, "DSN Trops"),
    )
    monkeypatch.setattr("trops_studio.integra_sql._sqlcmd_query", fake_sqlcmd)
    targets = discover_trops_targets()
    assert calls and all(s == DSN for s in calls)
    assert DEFAULT not in calls
    assert "localhost" not in calls
    names = {t.database.upper() for t in targets}
    assert "TROPS" in names
    assert preferred_trops_target(targets).database.upper() == "TROPS"
    assert preferred_trops_target(targets).server == DSN


def test_discover_sqlcmd_error_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(
        "trops_studio.integra_sql.resolve_integra_sql_server",
        lambda: (DSN, "DSN Trops"),
    )

    def boom(server, query, **kwargs):
        raise IntegraSqlError(f"sqlcmd napaka ({server}): ni povezave")

    monkeypatch.setattr("trops_studio.integra_sql._sqlcmd_query", boom)
    with pytest.raises(IntegraSqlError, match="ni povezave"):
        discover_trops_targets()


def test_preferred_target_rejects_ambiguous_names():
    targets = [
        TropsSqlTarget(server=DSN, database="TROPS_A"),
        TropsSqlTarget(server=DSN, database="TROPS_B"),
    ]
    with pytest.raises(IntegraSqlError, match="natančnega imena TROPS"):
        preferred_trops_target(targets)


def test_open_connection_uses_preferred_not_targets0(monkeypatch):
    import trops_studio.integra_trops_client as client

    wrong = TropsSqlTarget(server=DEFAULT, database="TROPS")
    right = TropsSqlTarget(server=DSN, database="TROPS")
    # If someone still returned both, preferred/open must not take default first.
    monkeypatch.setattr(
        client, "resolve_integra_sql_server", lambda: (DSN, "DSN Trops")
    )
    monkeypatch.setattr(client, "discover_trops_targets", lambda: [right])
    monkeypatch.setattr(client, "preferred_trops_target", lambda ts: right)

    class _Conn:
        def close(self):
            pass

    seen: dict = {}

    def fake_connect(conn_str, timeout=15):
        seen["s"] = conn_str
        return _Conn()

    class _Pyodbc:
        connect = staticmethod(fake_connect)

    monkeypatch.setitem(__import__("sys").modules, "pyodbc", _Pyodbc)
    with client.open_trops_connection(None) as conn:
        assert conn is not None
    assert DSN in seen["s"]
    assert DEFAULT + ";" not in seen["s"]


def test_restore_uses_dsn_server_not_default_instance(empty_motor, data_dir, monkeypatch, tmp_path):
    """integra_restore izbere DSN SQLEXPRESS, ne prve instance po abecedi. Brez pravega RESTORE."""
    import trops_studio.integra_sql as sql_mod
    from trops_studio.integra_sql import UnpackSqlBckResult, RestoreTropsResult

    bak = tmp_path / "kopija.bak"
    bak.write_bytes(b"not-a-real-bak")
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    (sql_dir / "kopija.bak").write_bytes(b"not-a-real-bak")

    right = TropsSqlTarget(
        server=DSN,
        database="TROPS",
        data_file=r"C:\sqlexpress\TROPS_Data.MDF",
        log_file=r"C:\sqlexpress\TROPS_Log.LDF",
    )
    wrong = TropsSqlTarget(
        server=DEFAULT,
        database="TROPS",
        data_file=r"C:\default\TROPS_Data.MDF",
        log_file=r"C:\default\TROPS_Log.LDF",
    )
    chosen: dict = {}

    def fake_discover():
        # Namerno oba, da bi stari targets[0] vzel DEFAULT (abeceda).
        return [wrong, right]

    def fake_restore(sql_dir_arg, src, trops, **kwargs):
        chosen["server"] = trops.server
        chosen["db"] = trops.database
        prepared = UnpackSqlBckResult(source_path=Path(src), sql_dir=Path(sql_dir_arg), bak_path=Path(src))
        restored = RestoreTropsResult(
            bak_path=Path(src),
            staging_bak=Path(src),
            trops=trops,
            logical_data="TROPS_Data",
            logical_log="TROPS_Log",
            data_file=trops.data_file,
            log_file=trops.log_file,
        )
        return prepared, restored

    monkeypatch.setattr(sql_mod, "resolve_integra_sql_server", lambda: (DSN, "DSN Trops"))
    monkeypatch.setattr(sql_mod, "discover_trops_targets", fake_discover)
    monkeypatch.setattr(sql_mod, "find_detached_trops_targets", lambda database="TROPS": [])
    monkeypatch.setattr(sql_mod, "preferred_trops_target", lambda targets: right)
    monkeypatch.setattr(sql_mod, "razpakiraj_in_restore", fake_restore)
    monkeypatch.setattr(sql_mod, "list_sql_bck_candidates", lambda d: [sql_dir / "kopija.bak"])
    monkeypatch.setattr(sql_mod, "list_sql_bak_files", lambda d: [sql_dir / "kopija.bak"])
    monkeypatch.setattr(sql_mod, "resolve_integra_sql_dir", lambda d=None: sql_dir)

    m = empty_motor
    m.integra_sql_dir = str(sql_dir)
    cand = str(sql_dir / "kopija.bak")
    res = m.integra_restore(cand)
    assert res["ok"] is True
    assert chosen["server"] == DSN
    assert res["server"] == DSN
    assert res["database"] == "TROPS"
    assert DSN in (res.get("msg") or "")
    _close = getattr(m, "db", None)
    if _close is not None:
        _close.close()
