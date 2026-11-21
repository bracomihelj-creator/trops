"""
Integra: UrejanjeKisanal → SQLite (namesto kisanal.dbf / popa.dbf).

Postopek (enak kot nekdanji makro UrejanjeKisanal; Access ni več potreben):
  1) zbriši popa_dbf
  2) Append dbo_POPA → popa_dbf
  3) zbriši kisanal_dbf za obdobje
  4) INSERT kisanal z zamenjavo kontov:
       KONT.OLDSIFRA = dbo_KISANAL.AnalAKon → KONT.KONTCTRL

Tu isto v zst-20 / integra SQLite tabelah ``popa`` in ``kisanal``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from trops_studio.config import TROPS_ROOT, company_db_path
from trops_studio.integra_sql import IntegraSqlError, TropsSqlTarget
from trops_studio.integra_trops_client import fetch_all, open_trops_connection

from trops_studio.config import DEFAULT_KONT_DBF, KONT_DBF_FALLBACKS


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kont_map (
    old_sifra TEXT NOT NULL PRIMARY KEY,
    new_konto TEXT NOT NULL,
    old_naziv TEXT NOT NULL DEFAULT '',
    new_naziv TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    year INTEGER
);

CREATE TABLE IF NOT EXISTS popa (
    popa_ctrl TEXT NOT NULL PRIMARY KEY,
    popa_koda TEXT NOT NULL DEFAULT '',
    popa_ime TEXT NOT NULL DEFAULT '',
    popa_nazv TEXT NOT NULL DEFAULT '',
    popa_nasl TEXT NOT NULL DEFAULT '',
    popa_ulic TEXT NOT NULL DEFAULT '',
    popa_ptt TEXT NOT NULL DEFAULT '',
    popa_kraj TEXT NOT NULL DEFAULT '',
    popa_drza TEXT NOT NULL DEFAULT '',
    popa_dast TEXT NOT NULL DEFAULT '',
    popa_mast TEXT NOT NULL DEFAULT '',
    popa_ziro TEXT NOT NULL DEFAULT '',
    popa_email TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kisanal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anal_ctrl TEXT NOT NULL DEFAULT '',
    anal_pozi TEXT NOT NULL DEFAULT '',
    anal_akon_old TEXT NOT NULL DEFAULT '',
    anal_akon TEXT NOT NULL DEFAULT '',
    anal_ddok TEXT,
    anal_ddur TEXT,
    anal_dknj TEXT,
    anal_debt REAL NOT NULL DEFAULT 0,
    anal_krdt REAL NOT NULL DEFAULT 0,
    anal_part TEXT NOT NULL DEFAULT '',
    anal_pime TEXT NOT NULL DEFAULT '',
    anal_doku TEXT NOT NULL DEFAULT '',
    anal_anal TEXT NOT NULL DEFAULT '',
    anal_veza TEXT NOT NULL DEFAULT '',
    anal_vrkn TEXT NOT NULL DEFAULT '',
    anal_vedo TEXT NOT NULL DEFAULT '',
    anal_dekr TEXT NOT NULL DEFAULT '',
    anal_osnova REAL,
    aop_obracun TEXT NOT NULL DEFAULT '',
    aop_knjiga TEXT NOT NULL DEFAULT '',
    year INTEGER,
    kont_mapped INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL DEFAULT '',
    UNIQUE (anal_ctrl, anal_pozi, anal_ddok, anal_akon_old, anal_debt, anal_krdt)
);

CREATE INDEX IF NOT EXISTS idx_kisanal_year ON kisanal(year);
CREATE INDEX IF NOT EXISTS idx_kisanal_ddok ON kisanal(anal_ddok);
CREATE INDEX IF NOT EXISTS idx_kisanal_vrkn ON kisanal(anal_vrkn);
CREATE INDEX IF NOT EXISTS idx_kisanal_akon ON kisanal(anal_akon);
"""


@dataclass
class UrejanjeKisanalResult:
    year: int
    date_from: date
    date_to: date
    kont_map_path: Path
    kont_map_count: int = 0
    popa_count: int = 0
    kisanal_count: int = 0
    kisanal_mapped: int = 0
    kisanal_unmapped: int = 0
    db_path: Path = field(default_factory=lambda: Path())
    message: str = ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _iso_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    # sql already date/datetime
    return text[:10]


def _money(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def resolve_kont_dbf(year: int) -> Path:
    """Izberi KONT mapo za leto (Access privzeto KONT2005.DBF)."""
    candidates = [
        TROPS_ROOT / "dat" / f"KONTO - {year}.DBF",
        TROPS_ROOT / "dat" / f"KONTO-{year}.DBF",
        TROPS_ROOT / "dat" / f"KONT{year}.DBF",
        TROPS_ROOT / "dat" / f"KONT{str(year)[-2:]}.DBF",
        DEFAULT_KONT_DBF,
        *KONT_DBF_FALLBACKS,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise IntegraSqlError(
        f"Ni KONT*.DBF za leto {year}.\nPričakovano npr. {DEFAULT_KONT_DBF}"
    )


def load_kont_map_from_dbf(path: Path) -> dict[str, dict[str, str]]:
    """OLDSIFRA → KONTCTRL (kot Access JOIN v UrejanjeKisanal)."""
    try:
        from dbfread import DBF  # type: ignore
    except ImportError as exc:
        raise IntegraSqlError("Manjka dbfread — namesti za branje KONT.DBF.") from exc
    if not path.is_file():
        raise IntegraSqlError(f"KONT DBF ne obstaja:\n{path}")
    table = DBF(str(path), encoding="cp852", ignore_missing_memofile=True)
    mapping: dict[str, dict[str, str]] = {}
    for row in table:
        old = _text(row.get("OLDSIFRA"))
        new = _text(row.get("KONTCTRL"))
        if not old or not new:
            continue
        mapping[old] = {
            "new_konto": new,
            "old_naziv": _text(row.get("OLDNAZIV")),
            "new_naziv": _text(row.get("KONTNAZV") or row.get("KONTOPIS")),
        }
    if not mapping:
        raise IntegraSqlError(f"V {path.name} ni OLDSIFRA→KONTCTRL mapiranj.")
    return mapping


def ensure_integra_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def urejanje_kisanal_to_sqlite(
    *,
    db_path: Path | None = None,
    year: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    kont_dbf: Path | None = None,
    trops: TropsSqlTarget | None = None,
) -> UrejanjeKisanalResult:
    """
    Ekvivalent Access ``Call UrejanjeKisanal`` → SQLite tabele popa + kisanal.
    """
    if year is None:
        year = (date_from or date.today()).year
    y0, y1 = year_bounds(year)
    d0 = date_from or y0
    d1 = date_to or y1
    path = Path(db_path or company_db_path(20))
    path.parent.mkdir(parents=True, exist_ok=True)
    kont_path = Path(kont_dbf) if kont_dbf else resolve_kont_dbf(year)
    kont_map = load_kont_map_from_dbf(kont_path)

    result = UrejanjeKisanalResult(
        year=year,
        date_from=d0,
        date_to=d1,
        kont_map_path=kont_path,
        kont_map_count=len(kont_map),
        db_path=path,
    )

    with open_trops_connection(trops) as sql:
        popa_rows = fetch_all(
            sql,
            """
            SELECT PopaCtrl, PopaKoda, PopaIme, PopaNazv, PopaNasl, PopaUlic, PopaPtt, PopaKraj,
                   PopaDrza, PopaDaSt, PopaMaSt, PopaZiro, popaimail
            FROM dbo.POPA
            """,
        )
        kis_rows = fetch_all(
            sql,
            """
            SELECT AnalCtrl, AnalPozi, AnalAKon, AnalDDok, AnalDDur, AnalDKnj,
                   AnalDebt, AnalKrdt, AnalPart, AnalPIme, AnalDoku, AnalAnal,
                   AnalVeza, AnalVrKn, AnalVeDo, AnalDeKr, AnalOsnova,
                   AOPObracun, AOPKnjiga
            FROM dbo.KISANAL
            WHERE (AnalDDok >= ? AND AnalDDok <= ?)
               OR (AnalDDur >= ? AND AnalDDur <= ?)
            ORDER BY AnalCtrl, AnalDDok, AnalPozi
            """,
            (d0, d1, d0, d1),
        )

    import json
    from datetime import datetime as dt

    now = dt.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(str(path))
    try:
        ensure_integra_tables(conn)
        conn.execute("DELETE FROM kont_map")
        conn.executemany(
            """
            INSERT INTO kont_map(old_sifra, new_konto, old_naziv, new_naziv, source, year)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    old,
                    info["new_konto"],
                    info.get("old_naziv", ""),
                    info.get("new_naziv", ""),
                    kont_path.name,
                    year,
                )
                for old, info in kont_map.items()
            ],
        )

        conn.execute("DELETE FROM popa")
        for row in popa_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO popa(
                    popa_ctrl, popa_koda, popa_ime, popa_nazv, popa_nasl, popa_ulic,
                    popa_ptt, popa_kraj, popa_drza, popa_dast, popa_mast, popa_ziro,
                    popa_email, raw_json, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _text(row.get("PopaCtrl")),
                    _text(row.get("PopaKoda")),
                    _text(row.get("PopaIme")),
                    _text(row.get("PopaNazv")),
                    _text(row.get("PopaNasl")),
                    _text(row.get("PopaUlic")),
                    _text(row.get("PopaPtt")),
                    _text(row.get("PopaKraj")),
                    _text(row.get("PopaDrza")),
                    _text(row.get("PopaDaSt")),
                    _text(row.get("PopaMaSt")),
                    _text(row.get("PopaZiro")),
                    _text(row.get("popaimail")),
                    json.dumps({k: _text(v) if not isinstance(v, (int, float)) else v for k, v in row.items()}, ensure_ascii=False, default=str),
                    now,
                ),
            )
        result.popa_count = len(popa_rows)

        conn.execute("DELETE FROM kisanal WHERE year = ?", (year,))
        mapped = 0
        unmapped = 0
        for row in kis_rows:
            old_konto = _text(row.get("AnalAKon"))
            info = kont_map.get(old_konto)
            if info:
                new_konto = info["new_konto"]
                is_mapped = 1
                mapped += 1
            else:
                # Access LEFT JOIN: brez OLDSIFRA → KONTCTRL je NULL (prazen konto)
                new_konto = ""
                is_mapped = 0
                unmapped += 1
            conn.execute(
                """
                INSERT OR IGNORE INTO kisanal(
                    anal_ctrl, anal_pozi, anal_akon_old, anal_akon,
                    anal_ddok, anal_ddur, anal_dknj, anal_debt, anal_krdt,
                    anal_part, anal_pime, anal_doku, anal_anal, anal_veza,
                    anal_vrkn, anal_vedo, anal_dekr, anal_osnova,
                    aop_obracun, aop_knjiga, year, kont_mapped, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _text(row.get("AnalCtrl")),
                    _text(row.get("AnalPozi")),
                    old_konto,
                    new_konto,
                    _iso_date(row.get("AnalDDok")),
                    _iso_date(row.get("AnalDDur")),
                    _iso_date(row.get("AnalDKnj")),
                    _money(row.get("AnalDebt")),
                    _money(row.get("AnalKrdt")),
                    _text(row.get("AnalPart")),
                    _text(row.get("AnalPIme")),
                    _text(row.get("AnalDoku")),
                    _text(row.get("AnalAnal")),
                    _text(row.get("AnalVeza")),
                    _text(row.get("AnalVrKn")),
                    _text(row.get("AnalVeDo")),
                    _text(row.get("AnalDeKr")),
                    None if row.get("AnalOsnova") is None else _money(row.get("AnalOsnova")),
                    _text(row.get("AOPObracun")),
                    _text(row.get("AOPKnjiga")),
                    year,
                    is_mapped,
                    json.dumps({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}, ensure_ascii=False, default=str),
                ),
            )
        result.kisanal_count = len(kis_rows)
        result.kisanal_mapped = mapped
        result.kisanal_unmapped = unmapped
        conn.commit()
    finally:
        conn.close()

    result.message = (
        f"UrejanjeKisanal → SQLite uspešno.\n"
        f"Baza: {path}\n"
        f"Leto: {year} ({d0.isoformat()} – {d1.isoformat()})\n"
        f"KONT mapa: {kont_path.name} ({len(kont_map)} OLDSIFRA->KONTCTRL)\n"
        f"POPA: {result.popa_count}\n"
        f"KISANAL: {result.kisanal_count} "
        f"(mapirano {mapped}, brez mape {unmapped})"
    )
    return result


def kisanal_vrkn_summary(db_path: Path, year: int) -> list[tuple[str, int]]:
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_integra_tables(conn)
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(anal_vrkn), ''), '(prazno)') AS vk, COUNT(*) AS c
            FROM kisanal WHERE year = ?
            GROUP BY 1 ORDER BY c DESC
            """,
            (year,),
        ).fetchall()
        return [(str(a), int(b)) for a, b in rows]
    finally:
        conn.close()
