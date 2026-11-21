from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from trops_studio.config import DATA_DIR, DEFAULT_DB
from trops_studio.money import (
    decimal_value,
    ensure_eu_vat_id,
    iso_date,
    national_tax_id,
    normalize_text,
    normalize_vat_id,
    parse_date,
    split_vat_and_mm_code,
    tax_digits,
)
from trops_studio.sync_state import SYNC_LOCAL, normalize_sync_status

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vat_id TEXT NOT NULL DEFAULT '',
    tax_number TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT 'SI',
    name TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    postal_code TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    is_foreign INTEGER NOT NULL DEFAULT 0,
    ajpes_code TEXT NOT NULL DEFAULT '',
    minimax_code TEXT NOT NULL DEFAULT '',
    registration_no TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    iban TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (vat_id, name)
);

CREATE TABLE IF NOT EXISTS account_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_kind TEXT NOT NULL DEFAULT 'supplier',
    match_vat TEXT NOT NULL DEFAULT '',
    match_tax TEXT NOT NULL DEFAULT '',
    match_name TEXT NOT NULL DEFAULT '',
    odhodek01 TEXT NOT NULL DEFAULT '',
    odhodek07 TEXT NOT NULL DEFAULT '',
    odhodek10 TEXT NOT NULL DEFAULT '',
    odhodek11 TEXT NOT NULL DEFAULT '',
    odhodek_excluded TEXT NOT NULL DEFAULT '',
    placilo TEXT NOT NULL DEFAULT '',
    prihodek TEXT NOT NULL DEFAULT '',
    self_assessment INTEGER,
    vat_deductible INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'manual',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ir_darila_path TEXT NOT NULL DEFAULT '',
    ir_fitnes_path TEXT NOT NULL DEFAULT '',
    pr_path TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    period_key TEXT NOT NULL DEFAULT '',
    period_rev INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ir_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    book TEXT NOT NULL DEFAULT '',
    seq INTEGER NOT NULL DEFAULT 0,
    booking_date TEXT,
    document_date TEXT,
    document_no TEXT NOT NULL DEFAULT '',
    party_name TEXT NOT NULL DEFAULT '',
    vat_id TEXT NOT NULL DEFAULT '',
    net TEXT NOT NULL DEFAULT '0.00',
    base_22 TEXT NOT NULL DEFAULT '0.00',
    vat_22 TEXT NOT NULL DEFAULT '0.00',
    base_95 TEXT NOT NULL DEFAULT '0.00',
    vat_95 TEXT NOT NULL DEFAULT '0.00',
    eu_goods TEXT NOT NULL DEFAULT '0.00',
    eu_services TEXT NOT NULL DEFAULT '0.00',
    reverse_charge TEXT NOT NULL DEFAULT '0.00',
    excluded TEXT NOT NULL DEFAULT '0.00',
    exempt TEXT NOT NULL DEFAULT '0.00',
    total TEXT NOT NULL DEFAULT '0.00',
    account TEXT NOT NULL DEFAULT '',
    party_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'OSNUTEK',
    notes TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    period_rev INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pr_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    booking_date TEXT,
    received_date TEXT,
    document_date TEXT,
    document_no TEXT NOT NULL DEFAULT '',
    internal_no TEXT NOT NULL DEFAULT '',
    supplier_name TEXT NOT NULL DEFAULT '',
    vat_id TEXT NOT NULL DEFAULT '',
    tax_number TEXT NOT NULL DEFAULT '',
    net_taxable TEXT NOT NULL DEFAULT '0.00',
    f76a TEXT NOT NULL DEFAULT '0.00',
    eu_goods TEXT NOT NULL DEFAULT '0.00',
    eu_services TEXT NOT NULL DEFAULT '0.00',
    exempt_non TEXT NOT NULL DEFAULT '0.00',
    exempt_os TEXT NOT NULL DEFAULT '0.00',
    exempt_on TEXT NOT NULL DEFAULT '0.00',
    nondeduct_22 TEXT NOT NULL DEFAULT '0.00',
    nondeduct_95 TEXT NOT NULL DEFAULT '0.00',
    base_22 TEXT NOT NULL DEFAULT '0.00',
    vat_22 TEXT NOT NULL DEFAULT '0.00',
    base_95 TEXT NOT NULL DEFAULT '0.00',
    vat_95 TEXT NOT NULL DEFAULT '0.00',
    base_5 TEXT NOT NULL DEFAULT '0.00',
    vat_5 TEXT NOT NULL DEFAULT '0.00',
    excluded TEXT NOT NULL DEFAULT '0.00',
    odhodek01 TEXT NOT NULL DEFAULT '',
    odhodek07 TEXT NOT NULL DEFAULT '',
    odhodek10 TEXT NOT NULL DEFAULT '',
    odhodek11 TEXT NOT NULL DEFAULT '',
    odhodek_excluded TEXT NOT NULL DEFAULT '',
    os_kpr TEXT NOT NULL DEFAULT '',
    os_amount TEXT NOT NULL DEFAULT '0.00',
    os_contra TEXT NOT NULL DEFAULT '1300',
    placilo TEXT NOT NULL DEFAULT '',
    self_assessment INTEGER,
    vat_deductible INTEGER,
    party_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'OSNUTEK',
    notes TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    period_rev INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_ir_document ON ir_rows(book, document_no, document_date);
CREATE INDEX IF NOT EXISTS idx_pr_internal ON pr_rows(internal_no);
CREATE INDEX IF NOT EXISTS idx_pr_document ON pr_rows(document_no, document_date, vat_id);
CREATE INDEX IF NOT EXISTS idx_parties_tax ON parties(tax_number);
CREATE INDEX IF NOT EXISTS idx_account_tax ON account_rules(match_tax);
CREATE INDEX IF NOT EXISTS idx_ir_status ON ir_rows(status);
CREATE INDEX IF NOT EXISTS idx_pr_status ON pr_rows(status);
CREATE INDEX IF NOT EXISTS idx_pr_odhodek ON pr_rows(odhodek01);
CREATE INDEX IF NOT EXISTS idx_pr_party ON pr_rows(party_id);
CREATE INDEX IF NOT EXISTS idx_ir_party ON ir_rows(party_id);
CREATE INDEX IF NOT EXISTS idx_parties_mm ON parties(minimax_code);
CREATE INDEX IF NOT EXISTS idx_account_kind_tax ON account_rules(party_kind, match_tax);

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_kind TEXT NOT NULL,
    doc_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL DEFAULT 0,
    account TEXT NOT NULL DEFAULT '',
    debit TEXT NOT NULL DEFAULT '0.00',
    credit TEXT NOT NULL DEFAULT '0.00',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(doc_kind, doc_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_journal_doc ON journal_lines(doc_kind, doc_id);

CREATE TABLE IF NOT EXISTS minimax_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT '',
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    minimax_id TEXT NOT NULL DEFAULT '',
    allowed_posting TEXT NOT NULL DEFAULT '',
    application TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'minimax',
    updated_at TEXT NOT NULL,
    UNIQUE(org_id, code)
);
CREATE INDEX IF NOT EXISTS idx_mm_accounts_org ON minimax_accounts(org_id);
CREATE INDEX IF NOT EXISTS idx_mm_accounts_code ON minimax_accounts(code);

CREATE TABLE IF NOT EXISTS account_code_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT '',
    trops_code TEXT NOT NULL DEFAULT '',
    minimax_code TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'user',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(org_id, trops_code)
);
CREATE INDEX IF NOT EXISTS idx_account_code_map_org ON account_code_map(org_id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _money(value: Any) -> str:
    return f"{decimal_value(value):.2f}"


def _account_code(value: Any) -> str:
    """Šifra konta; 0000 / 0 / prazno → ''."""
    text = normalize_text(value)
    if "—" in text:
        text = text.split("—", 1)[0].strip()
    if not text or text in {"0", "0000"}:
        return ""
    return text


def _int_flag(value: Any) -> int | None:
    """0/1 za SQLite; None = ni nastavljeno (avtomatika P9–P11)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) else 0
    text = str(value).strip().casefold()
    if text in {"1", "true", "da", "d", "yes", "y", "on"}:
        return 1
    if text in {"0", "false", "ne", "n", "no", "off"}:
        return 0
    return None


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DEFAULT_DB)
        self._local = threading.local()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -8000")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Ena povezava na nit (odpiranje ~3 ms × stotine klicev ob zagonu).

        Gnezdena seja v isti niti dobi ločeno povezavo — enaka transakcijska
        semantika kot prej (vsaka seja svoj commit/rollback).
        """
        local = self._local
        if getattr(local, "busy", False) or str(self.path) == ":memory:":
            conn = self.connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = self.connect()
            local.conn = conn
        local.busy = True
        try:
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except sqlite3.Error:
                local.conn = None
            raise
        finally:
            local.busy = False

    def close(self) -> None:
        """Zapri povezavo te niti (npr. pred brisanjem/premikom datoteke baze)."""
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            conn.close()

    def _init_schema(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)
            self._migrate_sync_columns(conn)
            self._migrate_pr_vat_flags(conn)
            self._migrate_pr_extra_accounts(conn)
            self._migrate_pr_os_book(conn)
            self._migrate_account_rules_extra(conn)
            self._migrate_minimax_account_flags(conn)
            self._migrate_period_revisions(conn)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(parties)").fetchall()}
            if "minimax_code" not in cols:
                conn.execute(
                    "ALTER TABLE parties ADD COLUMN minimax_code TEXT NOT NULL DEFAULT ''"
                )
            if "iban" not in cols:
                conn.execute(
                    "ALTER TABLE parties ADD COLUMN iban TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_parties_minimax ON parties(minimax_code)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", "6"),
            )

    def _migrate_pr_vat_flags(self, conn: sqlite3.Connection) -> None:
        """Samoobdavčitev / DDV se odbija — stolpci na PR in account_rules."""
        for table in ("pr_rows", "account_rules"):
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "self_assessment" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN self_assessment INTEGER")
            if "vat_deductible" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN vat_deductible INTEGER")

    def _migrate_pr_extra_accounts(self, conn: sqlite3.Connection) -> None:
        """Konti za P10 / P11 / Ne gre v knjigo (ne vedno 9729)."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pr_rows)").fetchall()}
        for col in ("odhodek10", "odhodek11", "odhodek_excluded"):
            if col not in cols:
                conn.execute(f"ALTER TABLE pr_rows ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

    def _migrate_pr_os_book(self, conn: sqlite3.Connection) -> None:
        """KPR 12/13/14/15 (DDV-O 34/35) + konto razlike 1300 v minus."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pr_rows)").fetchall()}
        if "os_kpr" not in cols:
            conn.execute("ALTER TABLE pr_rows ADD COLUMN os_kpr TEXT NOT NULL DEFAULT ''")
        if "os_amount" not in cols:
            conn.execute("ALTER TABLE pr_rows ADD COLUMN os_amount TEXT NOT NULL DEFAULT '0.00'")
        if "os_contra" not in cols:
            conn.execute("ALTER TABLE pr_rows ADD COLUMN os_contra TEXT NOT NULL DEFAULT '1300'")

    def _migrate_account_rules_extra(self, conn: sqlite3.Connection) -> None:
        """Predloge kontov EU / ne gre — stolpci na account_rules."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(account_rules)").fetchall()}
        for col in ("odhodek10", "odhodek11", "odhodek_excluded"):
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE account_rules ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                )

    def _migrate_period_revisions(self, conn: sqlite3.Connection) -> None:
        """Dodatni uvoz istega meseca: osnovni, nato -2, -3, -4 (brez prepisa)."""
        for table in ("ir_rows", "pr_rows", "import_batches"):
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "period_rev" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN period_rev INTEGER NOT NULL DEFAULT 1")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(import_batches)").fetchall()}
        if "period_key" not in cols:
            conn.execute("ALTER TABLE import_batches ADD COLUMN period_key TEXT NOT NULL DEFAULT ''")

    def _migrate_minimax_account_flags(self, conn: sqlite3.Connection) -> None:
        """AllowedPosting / Application iz Minimax Account API."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(minimax_accounts)").fetchall()}
        if "allowed_posting" not in cols:
            conn.execute(
                "ALTER TABLE minimax_accounts ADD COLUMN allowed_posting TEXT NOT NULL DEFAULT ''"
            )
        if "application" not in cols:
            conn.execute(
                "ALTER TABLE minimax_accounts ADD COLUMN application TEXT NOT NULL DEFAULT ''"
            )

    def list_account_code_maps(self, org_id: str | int | None = None) -> list[dict[str, Any]]:
        """Shranjena Trops → Minimax zamenjava kontov."""
        key = normalize_text(org_id)
        with self.session() as conn:
            if key:
                rows = conn.execute(
                    """
                    SELECT org_id, trops_code, minimax_code, source, notes, updated_at
                    FROM account_code_map
                    WHERE org_id=?
                    ORDER BY trops_code COLLATE NOCASE
                    """,
                    (key,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT org_id, trops_code, minimax_code, source, notes, updated_at
                    FROM account_code_map
                    ORDER BY org_id, trops_code COLLATE NOCASE
                    """
                ).fetchall()
            return [dict(r) for r in rows]

    def get_account_code_map_dict(self, org_id: str | int | None = None) -> dict[str, str]:
        """trops_code → minimax_code za org (in prazni org_id kot skupni)."""
        key = normalize_text(org_id)
        out: dict[str, str] = {}
        for row in self.list_account_code_maps(None):
            org = normalize_text(row.get("org_id"))
            if key and org and org != key:
                continue
            trops = _account_code(row.get("trops_code"))
            mm = _account_code(row.get("minimax_code"))
            if trops and mm:
                out[trops] = mm
        return out

    def upsert_account_code_maps(
        self,
        mappings: Mapping[str, str],
        *,
        org_id: str | int | None = None,
        source: str = "user",
    ) -> int:
        """Shrani / posodobi Trops → Minimax mapiranja. Vrne število zapisov."""
        key = normalize_text(org_id)
        now = _now()
        rows: list[tuple[str, str, str, str, str]] = []
        for trops_raw, mm_raw in mappings.items():
            trops = _account_code(trops_raw)
            mm = _account_code(mm_raw)
            if not trops or not mm:
                continue
            rows.append((key, trops, mm, normalize_text(source) or "user", now))
        if not rows:
            return 0
        with self.session() as conn:
            conn.executemany(
                """
                INSERT INTO account_code_map(org_id, trops_code, minimax_code, source, notes, updated_at)
                VALUES (?, ?, ?, ?, '', ?)
                ON CONFLICT(org_id, trops_code) DO UPDATE SET
                    minimax_code=excluded.minimax_code,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def seed_default_account_code_maps(self, org_id: str | int | None = None) -> int:
        """Vstavi privzeta mapiranja (če še niso shranjena)."""
        from trops_studio.account_choices import TROPS_TO_MINIMAX_DEFAULTS

        key = normalize_text(org_id)
        existing = self.get_account_code_map_dict(key)
        to_add = {
            k: v for k, v in TROPS_TO_MINIMAX_DEFAULTS.items() if k not in existing
        }
        if not to_add:
            return 0
        return self.upsert_account_code_maps(to_add, org_id=key, source="default")

    def apply_account_code_maps_to_data(
        self,
        mappings: Mapping[str, str],
        *,
        org_id: str | int | None = None,
    ) -> dict[str, int]:
        """Prepiši konte v kisanal / IR / PR / journal_lines po mapiranju."""
        pairs = [
            (_account_code(k), _account_code(v))
            for k, v in mappings.items()
            if _account_code(k) and _account_code(v) and _account_code(k) != _account_code(v)
        ]
        stats = {"kisanal": 0, "ir": 0, "pr": 0, "journal": 0}
        if not pairs:
            return stats
        with self.session() as conn:
            tables = {
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for trops, mm in pairs:
                if "kisanal" in tables:
                    cur = conn.execute(
                        "UPDATE kisanal SET anal_akon=? WHERE anal_akon=? OR anal_akon LIKE ?",
                        (mm, trops, f"{trops}-%"),
                    )
                    stats["kisanal"] += int(cur.rowcount or 0)
                cur = conn.execute(
                    "UPDATE ir_rows SET account=? WHERE account=? OR account LIKE ?",
                    (mm, trops, f"{trops}-%"),
                )
                stats["ir"] += int(cur.rowcount or 0)
                for col in (
                    "odhodek01",
                    "odhodek07",
                    "odhodek10",
                    "odhodek11",
                    "odhodek_excluded",
                    "placilo",
                ):
                    cur = conn.execute(
                        f"UPDATE pr_rows SET {col}=? WHERE {col}=? OR {col} LIKE ?",
                        (mm, trops, f"{trops}-%"),
                    )
                    stats["pr"] += int(cur.rowcount or 0)
                cur = conn.execute(
                    "UPDATE journal_lines SET account=? WHERE account=? OR account LIKE ?",
                    (mm, trops, f"{trops}-%"),
                )
                stats["journal"] += int(cur.rowcount or 0)
        return stats

    def _migrate_sync_columns(self, conn: sqlite3.Connection) -> None:
        """SQL-first: sync_status na IR/PR/parties (local → ready → synced)."""
        for table in ("ir_rows", "pr_rows", "parties"):
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "sync_status" not in cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN sync_status TEXT NOT NULL DEFAULT '{SYNC_LOCAL}'"
                )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_sync ON {table}(sync_status)"
            )

    def create_batch(
        self,
        ir_darila: str,
        ir_fitnes: str,
        pr_path: str,
        note: str = "",
        *,
        period_key: str = "",
        period_rev: int = 1,
    ) -> int:
        with self.session() as conn:
            cur = conn.execute(
                """
                INSERT INTO import_batches(
                    created_at, ir_darila_path, ir_fitnes_path, pr_path, note, period_key, period_rev
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    ir_darila,
                    ir_fitnes,
                    pr_path,
                    note,
                    str(period_key or "").strip(),
                    max(1, int(period_rev or 1)),
                ),
            )
            return int(cur.lastrowid)

    def get_meta(self, key: str, default: str = "") -> str:
        with self.session() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_last_import_batch(self) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM import_batches ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def set_last_vasco_import(self, data: Mapping[str, Any]) -> None:
        payload = {
            "imported_at": str(data.get("imported_at") or _now()),
            "source": str(data.get("source") or ""),
            "dir": str(data.get("dir") or ""),
            "zip": str(data.get("zip") or ""),
            "ir_darila": str(data.get("ir_darila") or ""),
            "ir_fitnes": str(data.get("ir_fitnes") or ""),
            "pr": str(data.get("pr") or ""),
        }
        self.set_meta("last_vasco_import", json.dumps(payload, ensure_ascii=False))

    def get_last_vasco_import(self) -> dict[str, str]:
        raw = self.get_meta("last_vasco_import")
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                remembered = {
                    "imported_at": str(payload.get("imported_at") or ""),
                    "source": str(payload.get("source") or ""),
                    "dir": str(payload.get("dir") or ""),
                    "zip": str(payload.get("zip") or ""),
                    "ir_darila": str(payload.get("ir_darila") or ""),
                    "ir_fitnes": str(payload.get("ir_fitnes") or ""),
                    "pr": str(payload.get("pr") or ""),
                }
                if self._vasco_snapshot_usable(remembered):
                    return remembered
        return self._last_vasco_from_import_batches()

    @staticmethod
    def _vasco_path_exists(raw: str) -> bool:
        text = str(raw or "").strip()
        if not text:
            return False
        path = Path(text)
        return path.is_file() or path.is_dir()

    def _vasco_snapshot_usable(self, rec: Mapping[str, Any]) -> bool:
        return any(
            self._vasco_path_exists(str(rec.get(key) or ""))
            for key in ("ir_darila", "ir_fitnes", "pr", "zip", "dir")
        )

    def _last_vasco_from_import_batches(self) -> dict[str, str]:
        """Zadnji uvoz, ki ga še lahko predlagamo (xls ali ZIP; brez izbrisanega Temp)."""
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM import_batches ORDER BY id DESC").fetchall()
        for row in rows:
            batch = dict(row)
            darila = str(batch.get("ir_darila_path") or "")
            fitness = str(batch.get("ir_fitnes_path") or "")
            pr_path = str(batch.get("pr_path") or "")
            existing = [p for p in (darila, fitness, pr_path) if Path(p).is_file()]
            if existing:
                return {
                    "imported_at": str(batch.get("created_at") or ""),
                    "source": "batch",
                    "dir": str(Path(existing[0]).parent),
                    "zip": "",
                    "ir_darila": darila if Path(darila).is_file() else "",
                    "ir_fitnes": fitness if Path(fitness).is_file() else "",
                    "pr": pr_path if Path(pr_path).is_file() else "",
                }
            zip_path = self._vasco_zip_for_missing_batch(darila, fitness, pr_path)
            if zip_path is not None:
                return {
                    "imported_at": str(batch.get("created_at") or ""),
                    "source": "zip",
                    "dir": str(zip_path.parent),
                    "zip": str(zip_path),
                    "ir_darila": "",
                    "ir_fitnes": "",
                    "pr": "",
                }
        return {}

    @staticmethod
    def _vasco_zip_for_missing_batch(*raw_paths: str) -> Path | None:
        for raw in raw_paths:
            text = str(raw or "").strip()
            if not text:
                continue
            parent = Path(text).parent
            month = parent.name
            candidates = (
                parent.parent / f"{month}.zip",
                parent / f"{month}.zip",
            )
            for item in candidates:
                if item.is_file():
                    return item
        return None

    def list_ir(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM ir_rows ORDER BY document_date, seq, id").fetchall()
            return [dict(row) for row in rows]

    def list_pr(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM pr_rows ORDER BY received_date, seq, id").fetchall()
            return [dict(row) for row in rows]

    def get_ir(self, row_id: int) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM ir_rows WHERE id=?", (row_id,)).fetchone()
            return dict(row) if row else None

    def get_pr(self, row_id: int) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM pr_rows WHERE id=?", (row_id,)).fetchone()
            return dict(row) if row else None

    def list_ir_by_sync(self, sync_status: str) -> list[dict[str, Any]]:
        status = normalize_sync_status(sync_status)
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM ir_rows WHERE sync_status=? ORDER BY document_date, seq, id",
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_pr_by_sync(self, sync_status: str) -> list[dict[str, Any]]:
        status = normalize_sync_status(sync_status)
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM pr_rows WHERE sync_status=? ORDER BY received_date, seq, id",
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_parties_by_sync(self, sync_status: str) -> list[dict[str, Any]]:
        status = normalize_sync_status(sync_status)
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM parties WHERE sync_status=? ORDER BY name COLLATE NOCASE, id",
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_row_sync(
        self,
        kind: str,
        row_id: int,
        sync_status: str,
        *,
        status: str | None = None,
    ) -> None:
        table = "ir_rows" if kind.upper() == "IR" else "pr_rows"
        sync = normalize_sync_status(sync_status)
        with self.session() as conn:
            if status is not None:
                conn.execute(
                    f"UPDATE {table} SET sync_status=?, status=?, updated_at=? WHERE id=?",
                    (sync, normalize_text(status), _now(), int(row_id)),
                )
            else:
                conn.execute(
                    f"UPDATE {table} SET sync_status=?, updated_at=? WHERE id=?",
                    (sync, _now(), int(row_id)),
                )

    def set_party_sync(self, party_id: int, sync_status: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE parties SET sync_status=?, updated_at=? WHERE id=?",
                (normalize_sync_status(sync_status), _now(), int(party_id)),
            )

    def replace_journal_lines(self, kind: str, doc_id: int, row: Mapping[str, Any] | None = None) -> int:
        """Zapiši knjižbe v SQL iz predogleda (SQL-first knjiženje)."""
        from trops_studio.journal_preview import preview_ir_journals, preview_pr_journals
        from trops_studio.vat_accounts import infer_supplier_kind, row_supplier_kind

        kind_u = kind.upper()
        source = row
        if source is None:
            source = self.get_ir(doc_id) if kind_u == "IR" else self.get_pr(doc_id)
        if not source:
            return 0
        if kind_u == "PR":
            # Opredelitev dobavitelja (SI/EU/tujec/Uvoz/MRN) za 160/260 in 2200/221x
            src = dict(source)
            stored = row_supplier_kind(src)
            if stored:
                src["supplier_kind"] = stored
            elif not src.get("supplier_kind"):
                party = None
                pid = src.get("party_id")
                if pid:
                    try:
                        party = self.get_party(int(pid))
                    except Exception:
                        party = None
                if party is None:
                    vat = str(src.get("vat_id") or "")
                    if vat:
                        party = self.find_party_by_tax(vat)
                src["supplier_kind"] = infer_supplier_kind(src, party)
            source = src
            lines = preview_pr_journals(source)
        else:
            lines = preview_ir_journals(source)
        with self.session() as conn:
            conn.execute(
                "DELETE FROM journal_lines WHERE doc_kind=? AND doc_id=?",
                (kind_u, int(doc_id)),
            )
            now = _now()
            for i, line in enumerate(lines):
                conn.execute(
                    """
                    INSERT INTO journal_lines(
                        doc_kind, doc_id, line_no, account, debit, credit, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kind_u,
                        int(doc_id),
                        i,
                        normalize_text(line.get("konto")),
                        _money(line.get("debet")),
                        _money(line.get("kredit")),
                        normalize_text(line.get("opis")),
                        now,
                    ),
                )
            return len(lines)

    def rebuild_all_journal_lines(self) -> dict[str, int]:
        """Osveži vse journal_lines (npr. po popravku Minimax DDV kontov 160/260)."""
        ir_rows = self.list_ir()
        pr_rows = self.list_pr()
        ir_n = 0
        pr_n = 0
        for row in ir_rows:
            ir_n += self.replace_journal_lines("IR", int(row["id"]), row)
        for row in pr_rows:
            pr_n += self.replace_journal_lines("PR", int(row["id"]), row)
        return {
            "ir_lines": ir_n,
            "pr_lines": pr_n,
            "ir_docs": len(ir_rows),
            "pr_docs": len(pr_rows),
        }

    def list_journal_lines(self, kind: str, doc_id: int) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM journal_lines
                WHERE doc_kind=? AND doc_id=?
                ORDER BY line_no, id
                """,
                (kind.upper(), int(doc_id)),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_ir(self, row_ids: Sequence[int]) -> int:
        if not row_ids:
            return 0
        with self.session() as conn:
            ids = [(int(i),) for i in row_ids]
            conn.executemany("DELETE FROM journal_lines WHERE doc_kind='IR' AND doc_id=?", ids)
            conn.executemany("DELETE FROM ir_rows WHERE id=?", ids)
            return len(row_ids)

    def delete_pr(self, row_ids: Sequence[int]) -> int:
        if not row_ids:
            return 0
        with self.session() as conn:
            ids = [(int(i),) for i in row_ids]
            conn.executemany("DELETE FROM journal_lines WHERE doc_kind='PR' AND doc_id=?", ids)
            conn.executemany("DELETE FROM pr_rows WHERE id=?", ids)
            return len(row_ids)

    def delete_ir_pr_for_period(
        self,
        date_from: date,
        date_to: date,
    ) -> dict[str, int]:
        """Izbriši IR/PR v obdobju (enaka logika datumov kot UI filter)."""

        def _in_period(row: Mapping[str, Any], date_keys: tuple[str, ...]) -> bool:
            for key in date_keys:
                raw = row.get(key)
                if not raw:
                    continue
                try:
                    parsed = parse_date(raw)
                except Exception:
                    parsed = None
                if parsed is None:
                    continue
                return date_from <= parsed <= date_to
            # Brez datuma: nikoli ne briši ob brisanju obdobja.
            return False

        ir_ids = [
            int(row["id"])
            for row in self.list_ir()
            if row.get("id") is not None
            and _in_period(row, ("document_date", "booking_date"))
        ]
        pr_ids = [
            int(row["id"])
            for row in self.list_pr()
            if row.get("id") is not None
            and _in_period(row, ("received_date", "document_date", "booking_date"))
        ]
        return {
            "ir": self.delete_ir(ir_ids),
            "pr": self.delete_pr(pr_ids),
        }

    def list_period_revisions(self, date_from: date, date_to: date) -> list[int]:
        """Obstoječe oznake uvoza v obdobju (1 = osnovni, 2 = -2 …)."""

        def _in_period(row: Mapping[str, Any], date_keys: tuple[str, ...]) -> bool:
            for key in date_keys:
                raw = row.get(key)
                if not raw:
                    continue
                try:
                    parsed = parse_date(raw)
                except Exception:
                    parsed = None
                if parsed is None:
                    continue
                return date_from <= parsed <= date_to
            return True

        revs: set[int] = set()
        for row in self.list_ir():
            if _in_period(row, ("document_date", "booking_date")):
                revs.add(max(1, int(row.get("period_rev") or 1)))
        for row in self.list_pr():
            if _in_period(row, ("received_date", "document_date", "booking_date")):
                revs.add(max(1, int(row.get("period_rev") or 1)))
        return sorted(revs)

    def period_has_documents(self, date_from: date, date_to: date) -> bool:
        return bool(self.list_period_revisions(date_from, date_to))

    def next_period_revision(self, date_from: date, date_to: date) -> int:
        revs = self.list_period_revisions(date_from, date_to)
        if not revs:
            return 1
        return max(revs) + 1

    def upsert_ir(self, data: Mapping[str, Any], row_id: int | None = None) -> int:
        payload = {
            "batch_id": data.get("batch_id"),
            "book": normalize_text(data.get("book")),
            "seq": int(data.get("seq") or 0),
            "booking_date": iso_date(data.get("booking_date")),
            "document_date": iso_date(data.get("document_date")),
            "document_no": normalize_text(data.get("document_no")),
            "party_name": normalize_text(data.get("party_name")),
            "vat_id": normalize_vat_id(data.get("vat_id")),
            "net": _money(data.get("net")),
            "base_22": _money(data.get("base_22")),
            "vat_22": _money(data.get("vat_22")),
            "base_95": _money(data.get("base_95")),
            "vat_95": _money(data.get("vat_95")),
            "eu_goods": _money(data.get("eu_goods")),
            "eu_services": _money(data.get("eu_services")),
            "reverse_charge": _money(data.get("reverse_charge")),
            "excluded": _money(data.get("excluded")),
            "exempt": _money(data.get("exempt")),
            "total": _money(data.get("total")),
            "account": normalize_text(data.get("account")),
            "party_id": data.get("party_id"),
            "status": normalize_text(data.get("status") or "OSNUTEK"),
            "sync_status": normalize_sync_status(data.get("sync_status") or SYNC_LOCAL),
            "notes": normalize_text(data.get("notes")),
            "raw_json": data.get("raw_json") if isinstance(data.get("raw_json"), str) else json.dumps(data.get("raw_json") or {}, ensure_ascii=False),
            "updated_at": _now(),
        }
        if "period_rev" in data or not row_id:
            payload["period_rev"] = max(1, int(data.get("period_rev") or 1))
        with self.session() as conn:
            if row_id:
                # Ob urejanju vrni v local, razen če kličemo eksplicitno ready/synced
                if "sync_status" not in data:
                    payload["sync_status"] = SYNC_LOCAL
                cols = ", ".join(f"{k}=?" for k in payload)
                conn.execute(f"UPDATE ir_rows SET {cols} WHERE id=?", (*payload.values(), row_id))
                return int(row_id)
            payload["created_at"] = _now()
            cols = ", ".join(payload)
            marks = ", ".join("?" for _ in payload)
            cur = conn.execute(f"INSERT INTO ir_rows ({cols}) VALUES ({marks})", tuple(payload.values()))
            return int(cur.lastrowid)

    def upsert_pr(self, data: Mapping[str, Any], row_id: int | None = None) -> int:
        payload = {
            "batch_id": data.get("batch_id"),
            "seq": int(data.get("seq") or 0),
            "booking_date": iso_date(data.get("booking_date")),
            "received_date": iso_date(data.get("received_date")),
            "document_date": iso_date(data.get("document_date")),
            "document_no": normalize_text(data.get("document_no")),
            "internal_no": normalize_text(data.get("internal_no")),
            "supplier_name": normalize_text(data.get("supplier_name")),
            "vat_id": normalize_vat_id(data.get("vat_id")),
            "tax_number": tax_digits(data.get("tax_number") or data.get("vat_id")),
            "net_taxable": _money(data.get("net_taxable")),
            "f76a": _money(data.get("f76a")),
            "eu_goods": _money(data.get("eu_goods")),
            "eu_services": _money(data.get("eu_services")),
            "exempt_non": _money(data.get("exempt_non")),
            "exempt_os": _money(data.get("exempt_os")),
            "exempt_on": _money(data.get("exempt_on")),
            "nondeduct_22": _money(data.get("nondeduct_22")),
            "nondeduct_95": _money(data.get("nondeduct_95")),
            "base_22": _money(data.get("base_22")),
            "vat_22": _money(data.get("vat_22")),
            "base_95": _money(data.get("base_95")),
            "vat_95": _money(data.get("vat_95")),
            "base_5": _money(data.get("base_5")),
            "vat_5": _money(data.get("vat_5")),
            "excluded": _money(data.get("excluded")),
            "odhodek01": _account_code(data.get("odhodek01")),
            "odhodek07": _account_code(data.get("odhodek07")),
            "odhodek10": _account_code(data.get("odhodek10")),
            "odhodek11": _account_code(data.get("odhodek11")),
            "odhodek_excluded": _account_code(data.get("odhodek_excluded")),
            "os_kpr": normalize_text(data.get("os_kpr")),
            "os_amount": _money(data.get("os_amount")),
            "os_contra": _account_code(data.get("os_contra")) or "1300",
            "placilo": _account_code(data.get("placilo")),
            "self_assessment": _int_flag(data.get("self_assessment")),
            "vat_deductible": _int_flag(data.get("vat_deductible")),
            "party_id": data.get("party_id"),
            "status": normalize_text(data.get("status") or "OSNUTEK"),
            "sync_status": normalize_sync_status(data.get("sync_status") or SYNC_LOCAL),
            "notes": normalize_text(data.get("notes")),
            "raw_json": data.get("raw_json") if isinstance(data.get("raw_json"), str) else json.dumps(data.get("raw_json") or {}, ensure_ascii=False),
            "updated_at": _now(),
        }
        if "period_rev" in data or not row_id:
            payload["period_rev"] = max(1, int(data.get("period_rev") or 1))
        with self.session() as conn:
            if row_id:
                if "sync_status" not in data:
                    payload["sync_status"] = SYNC_LOCAL
                cols = ", ".join(f"{k}=?" for k in payload)
                conn.execute(f"UPDATE pr_rows SET {cols} WHERE id=?", (*payload.values(), row_id))
                return int(row_id)
            payload["created_at"] = _now()
            cols = ", ".join(payload)
            marks = ", ".join("?" for _ in payload)
            cur = conn.execute(f"INSERT INTO pr_rows ({cols}) VALUES ({marks})", tuple(payload.values()))
            return int(cur.lastrowid)

    def list_parties(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM parties ORDER BY name COLLATE NOCASE, id").fetchall()
            return [dict(row) for row in rows]

    def search_parties(self, query: str = "", *, limit: int = 150) -> list[dict[str, Any]]:
        """Šifrant strank: *query* po nazivu, DDV, davčni, Minimax šifri."""
        needle = normalize_text(query).strip()
        lim = max(1, min(int(limit), 500))
        with self.session() as conn:
            if not needle:
                rows = conn.execute(
                    "SELECT * FROM parties ORDER BY name COLLATE NOCASE, id LIMIT ?",
                    (lim,),
                ).fetchall()
            else:
                like = f"%{needle}%"
                rows = conn.execute(
                    """
                    SELECT * FROM parties
                    WHERE name LIKE ? COLLATE NOCASE
                       OR IFNULL(vat_id, '') LIKE ? COLLATE NOCASE
                       OR IFNULL(tax_number, '') LIKE ? COLLATE NOCASE
                       OR IFNULL(minimax_code, '') LIKE ? COLLATE NOCASE
                    ORDER BY
                        CASE WHEN name LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END,
                        name COLLATE NOCASE,
                        id
                    LIMIT ?
                    """,
                    (like, like, like, like, f"{needle}%", lim),
                ).fetchall()
            return [dict(row) for row in rows]

    def get_party(self, party_id: int) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM parties WHERE id=?", (party_id,)).fetchone()
            return dict(row) if row else None

    def find_party_by_minimax_code(self, code: str) -> dict[str, Any] | None:
        key = normalize_text(code)
        if not key:
            return None
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM parties WHERE minimax_code=? ORDER BY id LIMIT 1",
                (key,),
            ).fetchone()
            return dict(row) if row else None

    def find_party_by_tax(self, vat_or_tax: str) -> dict[str, Any] | None:
        tax = tax_digits(vat_or_tax)
        vat = normalize_vat_id(vat_or_tax)
        alnum = national_tax_id(vat_or_tax)
        si_vat = f"SI{tax}" if tax and len(tax) == 8 else ""
        if not tax and not vat and not alnum:
            return None
        with self.session() as conn:
            row = conn.execute(
                """
                SELECT * FROM parties
                WHERE (? <> '' AND tax_number = ?)
                   OR (? <> '' AND vat_id = ?)
                   OR (? <> '' AND vat_id = ?)
                   OR (? <> '' AND UPPER(REPLACE(tax_number,' ','')) = ?)
                   OR (? <> '' AND UPPER(REPLACE(vat_id,' ','')) = ?)
                ORDER BY id LIMIT 1
                """,
                (
                    tax, tax,
                    vat, vat,
                    si_vat, si_vat,
                    alnum, alnum,
                    vat, vat,
                ),
            ).fetchone()
            return dict(row) if row else None

    def upsert_party(self, data: Mapping[str, Any], party_id: int | None = None) -> int:
        raw_vat, mm_from_vat = split_vat_and_mm_code(data.get("vat_id"))
        vat = normalize_vat_id(raw_vat)
        mm_code = normalize_text(data.get("minimax_code")) or mm_from_vat
        country = normalize_text(data.get("country") or ("SI" if not data.get("is_foreign") else ""))[:2].upper()
        # Če je lokalni ID z DDV črko (6364992H) in država še SI — sklepaj iz predpone IE/…
        if (country == "SI" or not country) and vat:
            if len(vat) >= 3 and vat[:2].isalpha() and vat[:2] != "SI":
                country = vat[:2]
        # SI: samo cifre; tuja (IE…): ohrani črke (6388047V)
        if country == "SI" or not country:
            tax = tax_digits(data.get("tax_number") or vat)
            country = country or "SI"
            # Gola davčna 8 mest → SI… (Integra POPA / AJPES)
            if tax and len(tax) == 8:
                vat = ensure_eu_vat_id(vat or tax, country="SI") or f"SI{tax}"
        else:
            tax = national_tax_id(data.get("tax_number") or vat, country=country)
            if vat.startswith("SI") and tax:
                vat = ""
            if not vat and tax:
                vat = ensure_eu_vat_id(tax, country=country) or f"{country}{tax}"
            elif vat and not (len(vat) >= 2 and vat[:2].isalpha()):
                vat = ensure_eu_vat_id(vat, country=country) or vat
        payload = {
            "vat_id": vat,
            "tax_number": tax,
            "country": country or "SI",
            "name": normalize_text(data.get("name")),
            "address": normalize_text(data.get("address")),
            "postal_code": normalize_text(data.get("postal_code")),
            "city": normalize_text(data.get("city")),
            "is_foreign": 1 if data.get("is_foreign") or (country and country != "SI") else 0,
            "ajpes_code": normalize_text(data.get("ajpes_code")),
            "minimax_code": mm_code,
            "registration_no": normalize_text(data.get("registration_no")),
            "email": normalize_text(data.get("email")),
            "phone": normalize_text(data.get("phone")),
            "iban": re.sub(r"\s+", "", normalize_text(data.get("iban"))).upper(),
            "notes": normalize_text(data.get("notes")),
            "source": normalize_text(data.get("source") or "manual"),
            "sync_status": normalize_sync_status(
                data.get("sync_status") or ("synced" if mm_code else SYNC_LOCAL)
            ),
            "updated_at": _now(),
        }
        # UNIQUE(vat_id, name): prazni ID za DDV + isti naziv → razloči z MM / davčno
        if not payload["vat_id"]:
            base_name = re.sub(
                r"\s*\[(?:MM|DS):[^\]]+\]\s*$",
                "",
                payload["name"] or "Stranka",
            ).strip() or "Stranka"
            if payload["minimax_code"]:
                payload["name"] = f"{base_name} [MM:{payload['minimax_code']}]"
            elif tax:
                payload["name"] = f"{base_name} [DS:{tax}]"
            if payload["minimax_code"] and "sync_status" not in data:
                payload["sync_status"] = "synced"

        def _merge_minimax(conn: sqlite3.Connection, existing_id: int) -> None:
            if payload["minimax_code"]:
                return
            old = conn.execute(
                "SELECT minimax_code, sync_status FROM parties WHERE id=?",
                (existing_id,),
            ).fetchone()
            if old and old["minimax_code"]:
                payload["minimax_code"] = old["minimax_code"]
                if "sync_status" not in data:
                    payload["sync_status"] = old["sync_status"] or SYNC_LOCAL
                # Osveži razločevalni priponk v nazivu
                if not payload["vat_id"] and payload["minimax_code"]:
                    base_name = re.sub(
                        r"\s*\[(?:MM|DS):[^\]]+\]\s*$",
                        "",
                        payload["name"] or "Stranka",
                    ).strip() or "Stranka"
                    payload["name"] = f"{base_name} [MM:{payload['minimax_code']}]"

        def _repoint_party_refs(conn: sqlite3.Connection, from_id: int, to_id: int) -> None:
            if from_id == to_id:
                return
            for table in ("ir_rows", "pr_rows"):
                conn.execute(
                    f"UPDATE {table} SET party_id=? WHERE party_id=?",
                    (to_id, from_id),
                )

        def _apply_update(conn: sqlite3.Connection, target_id: int) -> int:
            """UPDATE z združitvijo ob UNIQUE(vat_id, name) konfliktu."""
            _merge_minimax(conn, int(target_id))
            cols = ", ".join(f"{k}=?" for k in payload)
            try:
                conn.execute(
                    f"UPDATE parties SET {cols} WHERE id=?",
                    (*payload.values(), int(target_id)),
                )
                return int(target_id)
            except sqlite3.IntegrityError:
                clash = conn.execute(
                    "SELECT id FROM parties WHERE vat_id=? AND name=? ORDER BY id LIMIT 1",
                    (payload["vat_id"], payload["name"]),
                ).fetchone()
                if not clash:
                    raise
                clash_id = int(clash["id"])
                if clash_id == int(target_id):
                    raise
                _merge_minimax(conn, clash_id)
                conn.execute(
                    f"UPDATE parties SET {cols} WHERE id=?",
                    (*payload.values(), clash_id),
                )
                _repoint_party_refs(conn, int(target_id), clash_id)
                conn.execute("DELETE FROM parties WHERE id=?", (int(target_id),))
                return clash_id

        with self.session() as conn:
            if party_id:
                return _apply_update(conn, int(party_id))

            existing = None
            code = payload["minimax_code"]
            if code:
                existing = conn.execute(
                    "SELECT id FROM parties WHERE minimax_code=? ORDER BY id LIMIT 1",
                    (code,),
                ).fetchone()
            if existing is None and (tax or vat):
                existing = conn.execute(
                    """
                    SELECT id FROM parties
                    WHERE (? <> '' AND tax_number = ?) OR (? <> '' AND vat_id = ?)
                    ORDER BY id LIMIT 1
                    """,
                    (tax, tax, vat, vat),
                ).fetchone()
            if existing is None and payload["name"]:
                existing = conn.execute(
                    "SELECT id FROM parties WHERE vat_id=? AND name=? ORDER BY id LIMIT 1",
                    (payload["vat_id"], payload["name"]),
                ).fetchone()
            if existing:
                return _apply_update(conn, int(existing["id"]))

            payload["created_at"] = _now()
            cols = ", ".join(payload)
            marks = ", ".join("?" for _ in payload)
            try:
                cur = conn.execute(
                    f"INSERT INTO parties ({cols}) VALUES ({marks})",
                    tuple(payload.values()),
                )
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                clash = conn.execute(
                    "SELECT id FROM parties WHERE vat_id=? AND name=? ORDER BY id LIMIT 1",
                    (payload["vat_id"], payload["name"]),
                ).fetchone()
                if not clash:
                    raise
                return _apply_update(conn, int(clash["id"]))

    def delete_party(self, party_id: int) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM parties WHERE id=?", (party_id,))

    def find_account_rule(self, *, vat_id: str = "", name: str = "", party_kind: str = "supplier") -> dict[str, Any] | None:
        tax = tax_digits(vat_id)
        name_key = normalize_text(name).casefold()
        with self.session() as conn:
            if tax:
                row = conn.execute(
                    """
                    SELECT * FROM account_rules
                    WHERE active=1 AND party_kind=? AND match_tax=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (party_kind, tax),
                ).fetchone()
                if row:
                    return dict(row)
            if name_key:
                row = conn.execute(
                    """
                    SELECT * FROM account_rules
                    WHERE active=1 AND party_kind=? AND lower(match_name)=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (party_kind, name_key),
                ).fetchone()
                if row:
                    return dict(row)
        return None

    def list_account_rules(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM account_rules WHERE active=1 ORDER BY match_name COLLATE NOCASE, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def list_account_codes(self) -> list[str]:
        """Hitri DISTINCT konti iz account_rules (za Combobox)."""
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT code FROM (
                    SELECT odhodek01 AS code FROM account_rules WHERE active=1 AND odhodek01 <> ''
                    UNION SELECT odhodek07 FROM account_rules WHERE active=1 AND odhodek07 <> ''
                    UNION SELECT odhodek10 FROM account_rules WHERE active=1 AND odhodek10 <> ''
                    UNION SELECT odhodek11 FROM account_rules WHERE active=1 AND odhodek11 <> ''
                    UNION SELECT odhodek_excluded FROM account_rules
                        WHERE active=1 AND odhodek_excluded <> ''
                    UNION SELECT placilo FROM account_rules WHERE active=1 AND placilo <> ''
                    UNION SELECT prihodek FROM account_rules WHERE active=1 AND prihodek <> ''
                    UNION SELECT DISTINCT odhodek01 FROM pr_rows WHERE odhodek01 <> ''
                    UNION SELECT DISTINCT odhodek07 FROM pr_rows WHERE odhodek07 <> ''
                    UNION SELECT DISTINCT odhodek10 FROM pr_rows WHERE odhodek10 <> ''
                    UNION SELECT DISTINCT odhodek11 FROM pr_rows WHERE odhodek11 <> ''
                    UNION SELECT DISTINCT odhodek_excluded FROM pr_rows WHERE odhodek_excluded <> ''
                    UNION SELECT DISTINCT placilo FROM pr_rows WHERE placilo <> ''
                    UNION SELECT DISTINCT account FROM ir_rows WHERE account <> ''
                    UNION SELECT code FROM minimax_accounts WHERE code <> ''
                ) WHERE code IS NOT NULL AND code <> ''
                ORDER BY code
                """
            ).fetchall()
            return [str(row[0]) for row in rows]

    def count_minimax_accounts(self, org_id: str | int | None = None) -> int:
        key = normalize_text(org_id)
        with self.session() as conn:
            if key:
                row = conn.execute(
                    "SELECT COUNT(*) FROM minimax_accounts WHERE org_id=?",
                    (key,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM minimax_accounts").fetchone()
            return int(row[0] if row else 0)

    def list_minimax_accounts(self, org_id: str | int | None = None) -> list[dict[str, Any]]:
        """Kontni plan iz SQL (Minimax pull)."""
        key = normalize_text(org_id)
        with self.session() as conn:
            if key:
                rows = conn.execute(
                    """
                    SELECT org_id, code, name, minimax_id, allowed_posting, application,
                           source, updated_at
                    FROM minimax_accounts
                    WHERE org_id=?
                    ORDER BY
                        CASE WHEN code GLOB '[0-9]*' THEN 0 ELSE 1 END,
                        CAST(code AS INTEGER),
                        code COLLATE NOCASE
                    """,
                    (key,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT org_id, code, name, minimax_id, allowed_posting, application,
                           source, updated_at
                    FROM minimax_accounts
                    ORDER BY org_id, code COLLATE NOCASE
                    """
                ).fetchall()
            return [dict(row) for row in rows]

    def minimax_accounts_need_refresh(self, org_id: str | int | None) -> bool:
        """True, če manjkajo AllowedPosting zastavice (stari pull) — potreben nov API sync."""
        key = normalize_text(org_id)
        if not key:
            return False
        with self.session() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM minimax_accounts WHERE org_id=?", (key,)
            ).fetchone()
            if not total or int(total[0] or 0) == 0:
                return True
            with_flag = conn.execute(
                """
                SELECT COUNT(*) FROM minimax_accounts
                WHERE org_id=? AND TRIM(allowed_posting) <> ''
                """,
                (key,),
            ).fetchone()
            return int(with_flag[0] if with_flag else 0) == 0

    def replace_minimax_accounts(
        self,
        org_id: str | int,
        accounts: Sequence[Mapping[str, Any]],
    ) -> int:
        """Zamenjaj kontni plan za org (po pullu iz Minimax API)."""
        key = normalize_text(org_id)
        if not key:
            return 0
        now = _now()
        rows: list[tuple[str, str, str, str, str, str, str, str]] = []
        seen: set[str] = set()
        for item in accounts:
            code = normalize_text(item.get("code") or item.get("Code"))
            if not code or code in seen:
                continue
            seen.add(code)
            name = normalize_text(item.get("name") or item.get("Name") or "")
            mid = normalize_text(item.get("id") or item.get("minimax_id") or "")
            posting = normalize_text(
                item.get("allowed_posting") or item.get("AllowedPosting") or ""
            ).upper()
            application = normalize_text(
                item.get("application") or item.get("Application") or ""
            ).upper()
            rows.append((key, code, name, mid, posting, application, "minimax", now))
        with self.session() as conn:
            conn.execute("DELETE FROM minimax_accounts WHERE org_id=?", (key,))
            if rows:
                conn.executemany(
                    """
                    INSERT INTO minimax_accounts(
                        org_id, code, name, minimax_id, allowed_posting, application,
                        source, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        return len(rows)

    def last_pr_account(self, *, vat_id: str = "", name: str = "") -> dict[str, Any] | None:
        """Zadnji uporabljeni konto odhodka za dobavitelja (npr. iz maja → junij)."""
        tax = tax_digits(vat_id)
        name_key = normalize_text(name).casefold()
        select_cols = (
            "odhodek01, odhodek07, odhodek10, odhodek11, odhodek_excluded, placilo, "
            "self_assessment, vat_deductible"
        )
        has_acc = (
            "(odhodek01 <> '' OR odhodek07 <> '' OR odhodek10 <> '' "
            "OR odhodek11 <> '' OR odhodek_excluded <> '')"
        )

        def _pack(row: Any) -> dict[str, str]:
            return {
                "odhodek01": str(row["odhodek01"] or ""),
                "odhodek07": str(row["odhodek07"] or ""),
                "odhodek10": str(row["odhodek10"] or ""),
                "odhodek11": str(row["odhodek11"] or ""),
                "odhodek_excluded": str(row["odhodek_excluded"] or ""),
                "placilo": str(row["placilo"] or "2200"),
                "self_assessment": row["self_assessment"],
                "vat_deductible": row["vat_deductible"],
            }

        with self.session() as conn:
            if tax:
                row = conn.execute(
                    f"""
                    SELECT {select_cols} FROM pr_rows
                    WHERE {has_acc} AND (tax_number=? OR replace(vat_id,'SI','')=?)
                    ORDER BY COALESCE(booking_date, received_date, document_date) DESC, id DESC
                    LIMIT 1
                    """,
                    (tax, tax),
                ).fetchone()
                if row:
                    return _pack(row)
            if name_key:
                row = conn.execute(
                    f"""
                    SELECT {select_cols} FROM pr_rows
                    WHERE {has_acc} AND lower(supplier_name)=?
                    ORDER BY COALESCE(booking_date, received_date, document_date) DESC, id DESC
                    LIMIT 1
                    """,
                    (name_key,),
                ).fetchone()
                if row:
                    return _pack(row)
        return None

    def last_ir_account(self, *, vat_id: str = "", name: str = "") -> str:
        """Zadnji uporabljeni prihodkovni konto za kupca."""
        tax = tax_digits(vat_id)
        name_key = normalize_text(name).casefold()
        with self.session() as conn:
            if tax:
                row = conn.execute(
                    """
                    SELECT account FROM ir_rows
                    WHERE account <> '' AND replace(vat_id,'SI','')=?
                    ORDER BY COALESCE(booking_date, document_date) DESC, id DESC
                    LIMIT 1
                    """,
                    (tax,),
                ).fetchone()
                if row and row["account"]:
                    return str(row["account"])
            if name_key:
                row = conn.execute(
                    """
                    SELECT account FROM ir_rows
                    WHERE account <> '' AND lower(party_name)=?
                    ORDER BY COALESCE(booking_date, document_date) DESC, id DESC
                    LIMIT 1
                    """,
                    (name_key,),
                ).fetchone()
                if row and row["account"]:
                    return str(row["account"])
        return ""

    def learn_account_rules_from_rows(self) -> dict[str, int]:
        """Iz obstoječih IR/PR zapiše/posodobi pravila kontov po stranki."""
        pr_n = 0
        ir_n = 0
        seen_pr: set[str] = set()
        seen_ir: set[str] = set()
        with self.session() as conn:
            pr_rows = conn.execute(
                """
                SELECT vat_id, tax_number, supplier_name,
                       odhodek01, odhodek07, odhodek10, odhodek11, odhodek_excluded,
                       placilo, self_assessment, vat_deductible
                FROM pr_rows
                WHERE odhodek01 <> '' OR odhodek07 <> '' OR odhodek10 <> ''
                   OR odhodek11 <> '' OR odhodek_excluded <> ''
                ORDER BY COALESCE(booking_date, received_date, document_date) DESC, id DESC
                """
            ).fetchall()
            ir_rows = conn.execute(
                """
                SELECT vat_id, party_name, account
                FROM ir_rows
                WHERE account <> ''
                ORDER BY COALESCE(booking_date, document_date) DESC, id DESC
                """
            ).fetchall()
        for row in pr_rows:
            tax = tax_digits(row["tax_number"] or row["vat_id"])
            name = normalize_text(row["supplier_name"])
            key = tax or name.casefold()
            if not key or key in seen_pr:
                continue
            seen_pr.add(key)
            payload: dict[str, Any] = {
                "party_kind": "supplier",
                "match_vat": row["vat_id"] or (f"SI{tax}" if tax else ""),
                "match_tax": tax,
                "match_name": name,
                "odhodek01": row["odhodek01"] or "",
                "odhodek07": row["odhodek07"] or "",
                "odhodek10": row["odhodek10"] or "",
                "odhodek11": row["odhodek11"] or "",
                "odhodek_excluded": row["odhodek_excluded"] or "",
                "placilo": row["placilo"] or "2200",
                "source": "history",
            }
            if row["self_assessment"] is not None:
                payload["self_assessment"] = row["self_assessment"]
            if row["vat_deductible"] is not None:
                payload["vat_deductible"] = row["vat_deductible"]
            self.upsert_account_rule(payload)
            pr_n += 1
        for row in ir_rows:
            tax = tax_digits(row["vat_id"])
            name = normalize_text(row["party_name"])
            key = tax or name.casefold()
            if not key or key in seen_ir:
                continue
            seen_ir.add(key)
            self.upsert_account_rule(
                {
                    "party_kind": "customer",
                    "match_vat": row["vat_id"] or (f"SI{tax}" if tax else ""),
                    "match_tax": tax,
                    "match_name": name,
                    "prihodek": row["account"],
                    "source": "history",
                }
            )
            ir_n += 1
        return {"pr": pr_n, "ir": ir_n}

    def upsert_account_rule(self, data: Mapping[str, Any], rule_id: int | None = None) -> int:
        payload = {
            "party_kind": normalize_text(data.get("party_kind") or "supplier"),
            "match_vat": normalize_vat_id(data.get("match_vat")),
            "match_tax": tax_digits(data.get("match_tax") or data.get("match_vat")),
            "match_name": normalize_text(data.get("match_name")),
            "odhodek01": normalize_text(data.get("odhodek01")),
            "odhodek07": normalize_text(data.get("odhodek07")),
            "odhodek10": normalize_text(data.get("odhodek10")),
            "odhodek11": normalize_text(data.get("odhodek11")),
            "odhodek_excluded": normalize_text(data.get("odhodek_excluded")),
            "placilo": normalize_text(data.get("placilo")),
            "prihodek": normalize_text(data.get("prihodek")),
            "active": 1 if data.get("active", True) else 0,
            "source": normalize_text(data.get("source") or "manual"),
            "notes": normalize_text(data.get("notes")),
            "updated_at": _now(),
        }
        if "self_assessment" in data:
            payload["self_assessment"] = _int_flag(data.get("self_assessment"))
        if "vat_deductible" in data:
            payload["vat_deductible"] = _int_flag(data.get("vat_deductible"))
        with self.session() as conn:
            if rule_id:
                cols = ", ".join(f"{k}=?" for k in payload)
                conn.execute(f"UPDATE account_rules SET {cols} WHERE id=?", (*payload.values(), rule_id))
                return int(rule_id)
            existing = None
            if payload["match_tax"]:
                existing = conn.execute(
                    """
                    SELECT id FROM account_rules
                    WHERE party_kind=? AND match_tax=? AND active=1
                    ORDER BY id DESC LIMIT 1
                    """,
                    (payload["party_kind"], payload["match_tax"]),
                ).fetchone()
            if existing is None and payload["match_name"]:
                existing = conn.execute(
                    """
                    SELECT id FROM account_rules
                    WHERE party_kind=? AND lower(match_name)=lower(?) AND active=1
                      AND (match_tax='' OR match_tax IS NULL)
                    ORDER BY id DESC LIMIT 1
                    """,
                    (payload["party_kind"], payload["match_name"]),
                ).fetchone()
            if existing is not None:
                rid = int(existing["id"])
                cols = ", ".join(f"{k}=?" for k in payload)
                conn.execute(f"UPDATE account_rules SET {cols} WHERE id=?", (*payload.values(), rid))
                return rid
            cols = ", ".join(payload)
            marks = ", ".join("?" for _ in payload)
            cur = conn.execute(f"INSERT INTO account_rules ({cols}) VALUES ({marks})", tuple(payload.values()))
            return int(cur.lastrowid)

    def counts(self) -> dict[str, int]:
        with self.session() as conn:
            return {
                "ir": int(conn.execute("SELECT COUNT(*) FROM ir_rows").fetchone()[0]),
                "pr": int(conn.execute("SELECT COUNT(*) FROM pr_rows").fetchone()[0]),
                "parties": int(conn.execute("SELECT COUNT(*) FROM parties").fetchone()[0]),
                "rules": int(conn.execute("SELECT COUNT(*) FROM account_rules WHERE active=1").fetchone()[0]),
            }
