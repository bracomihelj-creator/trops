"""Integra — SQL TROPS pomožne funkcije (ZIP/BAK → SQL mapa + odkritje TROPS)."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from trops_studio.config import DEFAULT_INTEGRA_SQL


class IntegraSqlError(RuntimeError):
    """Napaka pri Integra SQL obdelavi."""


@dataclass
class TropsSqlTarget:
    """Lokacija baze TROPS na SQL Serverju."""

    server: str
    database: str
    data_file: str = ""
    log_file: str = ""

    @property
    def label(self) -> str:
        bits = [self.server, self.database]
        if self.data_file:
            bits.append(self.data_file)
        return " · ".join(bits)

    @property
    def key(self) -> str:
        return f"{self.server.casefold()}|{self.database.casefold()}"

    @property
    def data_dir(self) -> Path | None:
        if not self.data_file:
            return None
        return Path(self.data_file).parent

    @property
    def backup_dir(self) -> Path | None:
        """MSSQL\\Backup ob DATA mapi instance."""
        data_dir = self.data_dir
        if data_dir is None:
            return None
        # ...\MSSQL\DATA → ...\MSSQL\Backup
        if data_dir.name.casefold() == "data":
            return data_dir.parent / "Backup"
        return data_dir / "Backup"


@dataclass
class BakBackupSet:
    """Ena kopija (backup set) v .bak datoteki — RESTORE HEADERONLY."""

    position: int
    backup_type: int
    database: str = ""
    machine: str = ""
    finish: str = ""

    @property
    def label(self) -> str:
        bits = [self.finish[:16] or "?", self.machine or "?", self.database or "?"]
        return " · ".join(bits)


@dataclass
class RestoreTropsResult:
    bak_path: Path
    staging_bak: Path
    trops: TropsSqlTarget
    logical_data: str
    logical_log: str
    data_file: str
    log_file: str
    message: str = ""
    backup_set: BakBackupSet | None = None
    backup_set_count: int = 0
    safety_backup: Path | None = None


@dataclass
class UnpackSqlBckResult:
    source_path: Path
    sql_dir: Path
    bak_path: Path | None = None
    extracted: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    trops: TropsSqlTarget | None = None
    source_kind: str = ""  # zip | bak

    @property
    def zip_path(self) -> Path:
        """Vzdržuj združljivost s starejšimi klici."""
        return self.source_path

    @property
    def bak_files(self) -> list[Path]:
        if self.bak_path is not None:
            return [self.bak_path]
        return [p for p in self.extracted if p.suffix.lower() == ".bak"]


def resolve_integra_sql_dir(sql_dir: str | Path | None = None) -> Path:
    path = Path(sql_dir or DEFAULT_INTEGRA_SQL).expanduser()
    return path.resolve() if path.exists() else path


def list_sql_bck_zips(sql_dir: str | Path | None = None) -> list[Path]:
    """ZIP arhivi z SQL backupom v mapi SQL (novejši najprej)."""
    root = resolve_integra_sql_dir(sql_dir)
    if not root.is_dir():
        return []
    zips = [p for p in root.glob("*.zip") if p.is_file()]
    return sorted(zips, key=lambda p: p.stat().st_mtime, reverse=True)


def list_sql_bak_files(sql_dir: str | Path | None = None) -> list[Path]:
    """Že razpakirani .bak v mapi SQL (novejši najprej)."""
    root = resolve_integra_sql_dir(sql_dir)
    if not root.is_dir():
        return []
    baks = [p for p in root.glob("*.bak") if p.is_file()]
    return sorted(baks, key=lambda p: p.stat().st_mtime, reverse=True)


def list_sql_bck_candidates(sql_dir: str | Path | None = None) -> list[Path]:
    """ZIP in BAK kandidati v SQL mapi (novejši najprej)."""
    items = list_sql_bck_zips(sql_dir) + list_sql_bak_files(sql_dir)
    return sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)


def newest_sql_bck_zip(sql_dir: str | Path | None = None) -> Path | None:
    zips = list_sql_bck_zips(sql_dir)
    return zips[0] if zips else None


def list_bak_names_in_zip(zip_path: Path) -> list[str]:
    """Imena .bak datotek znotraj ZIP (brez razpakiranja)."""
    try:
        if not zipfile.is_zipfile(zip_path):
            return []
        with zipfile.ZipFile(zip_path, "r") as zf:
            names: list[str] = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                if name.lower().endswith(".bak"):
                    names.append(name)
            return names
    except (OSError, zipfile.BadZipFile):
        return []


def format_file_stamp(path: Path) -> str:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime)
        size_mb = path.stat().st_size / (1024 * 1024)
        return f"{path.name}  ({size_mb:.1f} MB, {ts:%d.%m.%Y %H:%M})"
    except OSError:
        return path.name


def candidate_display(path: Path) -> tuple[str, str, str]:
    """(tip, bak_opis, info) za seznam izbire."""
    suffix = path.suffix.lower()
    if suffix == ".zip":
        baks = list_bak_names_in_zip(path)
        bak_txt = ", ".join(baks) if baks else "(ni .bak v ZIP)"
        kind = "ZIP"
    elif suffix == ".bak":
        bak_txt = path.name
        kind = "BAK"
    else:
        bak_txt = path.name
        kind = path.suffix.upper().lstrip(".") or "?"
    stamp = format_file_stamp(path)
    info = stamp[len(path.name) :].strip(" ()") if stamp.startswith(path.name) else stamp
    return kind, bak_txt, info


def _odbc_trops_servers() -> list[str]:
    """Strežniki iz ODBC DSN Trops/TROPS (če so na voljo)."""
    found: list[str] = []
    try:
        import pyodbc  # type: ignore

        sources = pyodbc.dataSources()
        for name, driver in sources.items():
            if name.casefold() not in {"trops"}:
                continue
            # Poskusi prebrati Server iz registrov prek powershell — fallback spodaj.
            _ = driver
    except Exception:
        pass
    # Znani lokalni kandidati (ODBC Trops → BRACO-NUC\SQLEXPRESS)
    for server in (
        r"BRACO-NUC\SQLEXPRESS",
        r".\SQLEXPRESS",
        "BRACO-NUC",
        ".",
        "localhost",
        r"localhost\SQLEXPRESS",
    ):
        if server not in found:
            found.append(server)
    return found


def _sqlcmd_query(
    server: str,
    query: str,
    *,
    timeout: int = 20,
    fail_on_error: bool = False,
) -> str:
    cmd = [
        "sqlcmd",
        "-S",
        server,
        "-E",
        "-C",
        "-W",
        "-h",
        "-1",
        "-s",
        "|",
    ]
    if fail_on_error:
        # brez -b sqlcmd ob SQL napaki (npr. RESTORE) vrne 0
        cmd.append("-b")
    cmd += ["-Q", query]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise IntegraSqlError("sqlcmd ni na voljo (SQL Server tools).") from exc
    except subprocess.TimeoutExpired as exc:
        raise IntegraSqlError(f"sqlcmd timeout na {server}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise IntegraSqlError(f"sqlcmd napaka ({server}): {err or proc.returncode}")
    return proc.stdout or ""


def discover_trops_targets() -> list[TropsSqlTarget]:
    """
    Poišči baze TROPS na lokalnih SQL instancah.
    Če jih je več, UI ponudi izbiro.
    """
    by_key: dict[str, TropsSqlTarget] = {}
    errors: list[str] = []

    db_q = (
        "SET NOCOUNT ON; "
        "SELECT @@SERVERNAME, name FROM sys.databases "
        "WHERE UPPER(name) LIKE '%TROPS%';"
    )
    file_q = (
        "SET NOCOUNT ON; "
        "SELECT @@SERVERNAME, db_name(database_id), type_desc, physical_name "
        "FROM sys.master_files "
        "WHERE UPPER(db_name(database_id)) LIKE '%TROPS%';"
    )

    for server in _odbc_trops_servers():
        try:
            out = _sqlcmd_query(server, db_q)
        except IntegraSqlError as exc:
            errors.append(str(exc))
            continue
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            srv, db = parts[0], parts[1]
            if not srv or not db or db.upper() == "NAME":
                continue
            target = TropsSqlTarget(server=srv, database=db)
            by_key[target.key] = target

        try:
            fout = _sqlcmd_query(server, file_q)
        except IntegraSqlError:
            continue
        for line in fout.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            srv, db, typ, phys = parts[0], parts[1], parts[2], parts[3]
            key = f"{srv.casefold()}|{db.casefold()}"
            target = by_key.get(key) or TropsSqlTarget(server=srv, database=db)
            if typ.upper() == "ROWS":
                target.data_file = phys
            elif typ.upper() == "LOG":
                target.log_file = phys
            by_key[key] = target

    targets = sorted(by_key.values(), key=lambda t: (t.server.casefold(), t.database.casefold()))
    if not targets and errors:
        raise IntegraSqlError(
            "TROPS baze nisem našel.\n\n" + "\n".join(errors[:4])
        )
    return targets


DETACHED_DATA_NAME = "TROPS_Data.MDF"
DETACHED_LOG_NAME = "TROPS_Log.LDF"


def find_detached_trops_targets(database: str = "TROPS") -> list[TropsSqlTarget]:
    """
    TROPS ni priklopljen v SQL: cilj = privzeta DATA/LOG mapa instance.
    Če TROPS_Data.MDF že obstaja na kateri instanci, vrni samo te.
    """
    q = (
        "SET NOCOUNT ON; "
        "SELECT @@SERVERNAME, "
        "CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(400)), "
        "CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(400));"
    )
    by_server: dict[str, TropsSqlTarget] = {}
    for server in _odbc_trops_servers():
        try:
            out = _sqlcmd_query(server, q)
        except IntegraSqlError:
            continue
        for line in out.splitlines():
            parts = [p.strip() for p in line.strip().split("|")]
            if len(parts) < 3 or not parts[0] or not parts[1]:
                continue
            srv, data_dir, log_dir = parts[0], parts[1], parts[2] or parts[1]
            if srv.casefold() in by_server:
                continue
            by_server[srv.casefold()] = TropsSqlTarget(
                server=srv,
                database=database,
                data_file=str(Path(data_dir) / DETACHED_DATA_NAME),
                log_file=str(Path(log_dir) / DETACHED_LOG_NAME),
            )
    targets = sorted(by_server.values(), key=lambda t: t.server.casefold())
    with_files = [t for t in targets if Path(t.data_file).is_file()]
    return with_files or targets


def trops_is_attached(trops: TropsSqlTarget) -> bool:
    out = _sqlcmd_query(
        trops.server,
        f"SET NOCOUNT ON; SELECT CASE WHEN DB_ID(N'{_sql_literal(trops.database)}') "
        "IS NULL THEN 0 ELSE 1 END;",
    )
    return any(line.strip() == "1" for line in out.splitlines())


def unpack_zip_to_sql_dir(
    archive: Path,
    sql_dir: Path,
    *,
    overwrite: bool = True,
) -> UnpackSqlBckResult:
    """Razpakiraj ZIP z .bak v SQL mapo."""
    if not zipfile.is_zipfile(archive):
        raise IntegraSqlError(f"Datoteka ni veljaven ZIP:\n{archive}")
    result = UnpackSqlBckResult(source_path=archive, sql_dir=sql_dir, source_kind="zip")
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            if not zf.namelist():
                raise IntegraSqlError(f"ZIP je prazen:\n{archive}")
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest_name = Path(info.filename).name
                if not dest_name or dest_name in {".", ".."}:
                    result.skipped.append(info.filename)
                    continue
                dest = sql_dir / dest_name
                if dest.exists() and not overwrite:
                    result.skipped.append(dest_name)
                    continue
                with zf.open(info, "r") as src, open(dest, "wb") as out:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                result.extracted.append(dest)
    except IntegraSqlError:
        raise
    except zipfile.BadZipFile as exc:
        raise IntegraSqlError(f"Poškodovan ZIP:\n{archive}\n{exc}") from exc
    except OSError as exc:
        raise IntegraSqlError(f"Razpakiranje ni uspelo: {exc}") from exc

    if not result.extracted:
        raise IntegraSqlError(
            f"Iz ZIP ni bilo razpakirano ničesar:\n{archive}\n"
            f"Preskočeno: {', '.join(result.skipped) or '—'}"
        )
    baks = [p for p in result.extracted if p.suffix.lower() == ".bak"]
    result.bak_path = baks[0] if baks else None
    return result


def prepare_sql_bck(
    sql_dir: str | Path | None = None,
    source_path: str | Path | None = None,
    *,
    trops: TropsSqlTarget | None = None,
    overwrite: bool = True,
) -> UnpackSqlBckResult:
    """
    Pripravi SQL_bck:
    - ZIP → razpakiraj .bak v SQL mapo pod TROPS
    - BAK → uporabi izbrano .bak datoteko
    Obvezno poveži / preveri ciljno TROPS bazo (če jih je več, izberi zunaj).
    """
    root = resolve_integra_sql_dir(sql_dir)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise IntegraSqlError(f"SQL mapa ni mapa: {root}")

    if source_path is None:
        raise IntegraSqlError("Manjka izbira ZIP ali BAK datoteke.")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise IntegraSqlError(f"Datoteka ne obstaja:\n{source}")

    suffix = source.suffix.lower()
    if suffix == ".zip":
        result = unpack_zip_to_sql_dir(source, root, overwrite=overwrite)
    elif suffix == ".bak":
        result = UnpackSqlBckResult(
            source_path=source,
            sql_dir=root,
            bak_path=source,
            extracted=[],
            source_kind="bak",
        )
    else:
        raise IntegraSqlError(f"Podprt je ZIP ali BAK, dobil: {source.name}")

    result.trops = trops
    return result


def unpack_sql_bck(
    sql_dir: str | Path | None = None,
    zip_path: str | Path | None = None,
    *,
    overwrite: bool = True,
    trops: TropsSqlTarget | None = None,
) -> UnpackSqlBckResult:
    """Združljiv vstop: ZIP (ali BAK) + opcijski TROPS cilj."""
    source = Path(zip_path) if zip_path else newest_sql_bck_zip(sql_dir)
    return prepare_sql_bck(sql_dir, source, trops=trops, overwrite=overwrite)


def _sql_literal(path: str | Path) -> str:
    return str(path).replace("'", "''")


def stage_bak_for_sql(bak_path: Path, trops: TropsSqlTarget) -> Path:
    """
    SQL Service pogosto nima pravic do D:\\Trops\\… —
    zato BAK skopiraj v MSSQL\\Backup ob DATA mapi.
    """
    bak_path = Path(bak_path).resolve()
    if not bak_path.is_file():
        raise IntegraSqlError(f"BAK ne obstaja:\n{bak_path}")
    backup_dir = trops.backup_dir
    if backup_dir is None:
        raise IntegraSqlError(
            "Ne morem določiti SQL Backup mape (manjka TROPS DATA pot)."
        )
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise IntegraSqlError(f"SQL Backup mapa ni dostopna:\n{backup_dir}\n{exc}") from exc
    staged = backup_dir / bak_path.name
    try:
        if staged.resolve() != bak_path.resolve():
            shutil.copy2(bak_path, staged)
    except OSError as exc:
        raise IntegraSqlError(
            f"Kopiranje BAK v SQL Backup ni uspelo:\n{bak_path}\n→ {staged}\n{exc}"
        ) from exc
    return staged


def read_bak_header(server: str, bak_path: Path) -> list[BakBackupSet]:
    """Kopije (backup sets) v .bak — RESTORE HEADERONLY."""
    q = (
        "SET NOCOUNT ON; "
        f"RESTORE HEADERONLY FROM DISK = N'{_sql_literal(bak_path)}';"
    )
    out = _sqlcmd_query(server, q, timeout=120, fail_on_error=True)
    sets: list[BakBackupSet] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.strip().split("|")]
        # 2=BackupType, 5=Position, 9=DatabaseName, 18=BackupFinishDate, 28=MachineName
        if len(parts) < 29 or not parts[5].isdigit() or not parts[2].isdigit():
            continue
        sets.append(
            BakBackupSet(
                position=int(parts[5]),
                backup_type=int(parts[2]),
                database=parts[9],
                finish=parts[18],
                machine=parts[28],
            )
        )
    if not sets:
        raise IntegraSqlError(f"V BAK ni kopij (HEADERONLY):\n{bak_path}\n\n{out[:500]}")
    return sets


def latest_full_backup_set(sets: list[BakBackupSet]) -> BakBackupSet:
    """Zadnja polna kopija baze (BackupType 1) — RESTORE brez FILE vzame prvo."""
    full = [s for s in sets if s.backup_type == 1]
    if not full:
        raise IntegraSqlError("V BAK ni polne kopije baze (BackupType 1).")
    return max(full, key=lambda s: s.position)


def backup_current_trops(trops: TropsSqlTarget, *, attached: bool) -> Path | None:
    """
    Varnostna kopija obstoječe TROPS pred RESTORE v MSSQL\\Backup:
    priklopljena → BACKUP COPY_ONLY (.bak), nepriklopljena → kopija MDF/LDF.
    """
    backup_dir = trops.backup_dir
    if backup_dir is None:
        raise IntegraSqlError("Ne morem določiti SQL Backup mape za varnostno kopijo.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if attached:
        dest = backup_dir / f"{trops.database}_pred_restore_{stamp}.bak"
        _sqlcmd_query(
            trops.server,
            f"BACKUP DATABASE [{trops.database}] TO DISK = N'{_sql_literal(dest)}' "
            "WITH COPY_ONLY, INIT, CHECKSUM;",
            timeout=600,
            fail_on_error=True,
        )
        if not dest.is_file():
            raise IntegraSqlError(f"Varnostna kopija ni nastala:\n{dest}")
        return dest

    files = [Path(p) for p in (trops.data_file, trops.log_file) if p and Path(p).is_file()]
    if not files:
        return None
    dest_dir = backup_dir / f"{trops.database}_pred_restore_{stamp}"
    try:
        dest_dir.mkdir(parents=True, exist_ok=False)
        for src in files:
            dst = dest_dir / src.name
            shutil.copy2(src, dst)
            if dst.stat().st_size != src.stat().st_size:
                raise IntegraSqlError(f"Kopija ni enake velikosti:\n{src}\n→ {dst}")
    except OSError as exc:
        raise IntegraSqlError(
            f"Varnostna kopija MDF/LDF ni uspela:\n{dest_dir}\n{exc}"
        ) from exc
    return dest_dir


def filelist_from_bak(
    server: str,
    bak_path: Path,
    position: int | None = None,
) -> tuple[str, str]:
    """LogicalName za DATA (D) in LOG (L) iz RESTORE FILELISTONLY."""
    file_opt = f" WITH FILE = {int(position)}" if position else ""
    q = (
        "SET NOCOUNT ON; "
        f"RESTORE FILELISTONLY FROM DISK = N'{_sql_literal(bak_path)}'{file_opt};"
    )
    out = _sqlcmd_query(server, q, timeout=120)
    data_name = ""
    log_name = ""
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        logical, _phys, typ = parts[0], parts[1], parts[2]
        if logical.casefold() == "logicalname":
            continue
        if typ.upper() in {"D", "ROWS"} and not data_name:
            data_name = logical
        elif typ.upper() in {"L", "LOG"} and not log_name:
            log_name = logical
    if not data_name or not log_name:
        raise IntegraSqlError(
            f"V BAK nisem našel logical imen DATA/LOG:\n{bak_path}\n\n{out[:500]}"
        )
    return data_name, log_name


def restore_bak_to_trops(
    bak_path: Path,
    trops: TropsSqlTarget,
    *,
    keep_staging: bool = True,
    backup_set: BakBackupSet | None = None,
    safety_backup: bool = True,
) -> RestoreTropsResult:
    """
    Obnovi zadnjo polno kopijo iz BAK v SQL bazo TROPS (REPLACE) na poti
    instance DATA (npr. …\\MSSQL17.SQLEXPRESS\\MSSQL\\DATA\\TROPS_Data.MDF).
    Deluje tudi, ko TROPS ni priklopljen. Pred tem varnostna kopija obstoječe.
    """
    if not trops.data_file or not trops.log_file:
        raise IntegraSqlError(
            "TROPS cilj nima DATA/LOG poti — preveri bazo v SQL Serverju."
        )
    bak_path = Path(bak_path).resolve()
    staged = stage_bak_for_sql(bak_path, trops)
    sets = read_bak_header(trops.server, staged)
    chosen = backup_set or latest_full_backup_set(sets)
    logical_data, logical_log = filelist_from_bak(trops.server, staged, chosen.position)

    attached = trops_is_attached(trops)
    safety = backup_current_trops(trops, attached=attached) if safety_backup else None

    db = trops.database
    # RESTORE zahteva ekskluzivni dostop (le če je baza priklopljena)
    single_user = (
        f"ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;" if attached else ""
    )
    q = f"""
SET NOCOUNT ON;
{single_user}
RESTORE DATABASE [{db}]
FROM DISK = N'{_sql_literal(staged)}'
WITH FILE = {int(chosen.position)},
REPLACE,
MOVE N'{_sql_literal(logical_data)}' TO N'{_sql_literal(trops.data_file)}',
MOVE N'{_sql_literal(logical_log)}' TO N'{_sql_literal(trops.log_file)}',
STATS = 10;
ALTER DATABASE [{db}] SET MULTI_USER;
"""
    try:
        out = _sqlcmd_query(trops.server, q, timeout=600, fail_on_error=True)
    except IntegraSqlError:
        # poskusi vrniti MULTI_USER tudi ob napaki
        try:
            _sqlcmd_query(
                trops.server,
                f"IF DB_ID(N'{_sql_literal(db)}') IS NOT NULL "
                f"ALTER DATABASE [{db}] SET MULTI_USER;",
                timeout=60,
            )
        except IntegraSqlError:
            pass
        raise

    if not trops_is_attached(trops):
        raise IntegraSqlError(f"Po RESTORE baze {db} ni v SQL ({trops.server}).")

    if not keep_staging and staged.resolve() != bak_path.resolve():
        try:
            staged.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if staged.exists():
                staged.unlink()
        except OSError:
            pass

    msg = (
        f"RESTORE uspešen.\n"
        f"BAK: {bak_path.name}\n"
        f"Kopija {chosen.position}/{len(sets)}: {chosen.label}\n"
        f"SQL: {trops.server} / {trops.database}\n"
        f"DATA: {trops.data_file}\n"
        f"LOG: {trops.log_file}\n"
        f"Varnostna kopija prej: {safety or '— (TROPS ni obstajal)'}"
    )
    if out.strip():
        msg += f"\n\n{out.strip()[-400:]}"
    return RestoreTropsResult(
        bak_path=bak_path,
        staging_bak=staged,
        trops=trops,
        logical_data=logical_data,
        logical_log=logical_log,
        data_file=trops.data_file,
        log_file=trops.log_file,
        message=msg,
        backup_set=chosen,
        backup_set_count=len(sets),
        safety_backup=safety,
    )


def inspect_bak_for_restore(
    bak_path: Path,
    trops: TropsSqlTarget,
) -> tuple[Path, BakBackupSet, int]:
    """Pred potrditvijo: BAK v SQL Backup + katera kopija bo obnovljena."""
    staged = stage_bak_for_sql(Path(bak_path).resolve(), trops)
    sets = read_bak_header(trops.server, staged)
    return staged, latest_full_backup_set(sets), len(sets)


def razpakiraj_in_restore(
    sql_dir: str | Path | None,
    source_path: str | Path,
    trops: TropsSqlTarget,
    *,
    overwrite: bool = True,
    backup_set: BakBackupSet | None = None,
) -> tuple[UnpackSqlBckResult, RestoreTropsResult]:
    """ZIP/BAK priprava + varnostna kopija + RESTORE zadnje kopije v TROPS."""
    prepared = prepare_sql_bck(sql_dir, source_path, trops=trops, overwrite=overwrite)
    if prepared.bak_path is None:
        raise IntegraSqlError("Po pripravi ni .bak datoteke za RESTORE.")
    restored = restore_bak_to_trops(prepared.bak_path, trops, backup_set=backup_set)
    return prepared, restored

