"""Povezava na SQL Server TROPS (Integra)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from trops_studio.integra_sql import IntegraSqlError, TropsSqlTarget, discover_trops_targets


def _connect_string(server: str, database: str = "TROPS") -> str:
    return (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={database};"
        "Trusted_Connection=Yes;"
        "TrustServerCertificate=Yes;"
    )


@contextmanager
def open_trops_connection(trops: TropsSqlTarget | None = None) -> Iterator[Any]:
    try:
        import pyodbc  # type: ignore
    except ImportError as exc:
        raise IntegraSqlError("Manjka pyodbc — namesti paket za SQL TROPS.") from exc

    target = trops
    if target is None:
        targets = discover_trops_targets()
        if not targets:
            raise IntegraSqlError("TROPS baze v SQL ni.")
        target = targets[0]

    try:
        conn = pyodbc.connect(
            _connect_string(target.server, target.database),
            timeout=15,
        )
    except Exception as exc:
        raise IntegraSqlError(f"Povezava na TROPS ni uspela ({target.server}): {exc}") from exc
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(conn: Any, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    rows: list[dict[str, Any]] = []
    for row in cur.fetchall():
        rows.append({cols[i]: row[i] for i in range(len(cols))})
    return rows
