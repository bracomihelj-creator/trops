"""Branje Vasco Excel datotek v čistem Pythonu (openpyxl za .xlsx/.xlsm, xlrd za .xls).

Do 5.0 je Trops bral Excel prek 32-bitnega PowerShella in gonilnika Microsoft.ACE.OLEDB (Access).
Ta modul daje ENAK izhod, kot ga je dajal ACE (HDR=YES; IMEX=1), da se uvoz (excel_map) ne spremeni:

* prva vrstica je glava; prazen naslov stolpca → ``F{n}`` (1-based), pika v naslovu → ``#``
  (»Interna št.« → »Interna št#«), naslov skrajšan na 64 znakov, podvojen naslov → ``F{n}``;
* list: prvi po abecedi imen, kot jih vrne ACE (``List1$``, ``'IF DARILA$'``);
* vrstica se vzame samo, če je prvi stolpec pozitivno število (``163``, ``1,5``);
* prazna celica → ``None``; besedilo ostane točno tako (tudi ``" "``); datum → ``YYYY-MM-DD``;
  število → ``int``, če je celo, sicer ``float``; logična vrednost → ``bool``.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Sequence

from trops_studio.money import ProjestError

ACE_MAX_COLUMN_NAME = 64
_FIRST_COL_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_PLAIN_SHEET_RE = re.compile(r"^[A-Za-z0-9_\u00C0-\u024F]+$")


def _number(value: float | int) -> int | float:
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _cell_value(value: Any) -> Any:
    """Vrednost celice v obliki, kot jo je vrnil ACE most (JSON)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        value = _number(value)
    return str(value).strip()


def _first_column_ok(value: Any) -> bool:
    text = _as_text(value)
    if not _FIRST_COL_RE.match(text):
        return False
    return float(text.replace(",", ".")) > 0


def column_names(header: Sequence[Any]) -> list[str]:
    """Imena stolpcev kot pri ACE (HDR=YES)."""
    names: list[str] = []
    used: set[str] = set()
    for idx, raw in enumerate(header, start=1):
        text = "" if raw is None else str(_cell_value(raw))
        text = text.replace(".", "#")[:ACE_MAX_COLUMN_NAME]
        if not text.strip() or text.casefold() in used:
            text = f"F{idx}"
        used.add(text.casefold())
        names.append(text)
    return names


def ace_sheet_name(name: str) -> str:
    """Ime lista, kot ga našteje ACE (s ``$``, z narekovaji, če vsebuje presledke ali posebne znake)."""
    return f"{name}$" if _PLAIN_SHEET_RE.match(name) else f"'{name}$'"


def _pick_sheet(names: Iterable[str]) -> str:
    ordered = sorted(names, key=lambda n: ace_sheet_name(n).casefold())
    if not ordered:
        raise ProjestError("Excel datoteka nima lista.")
    return ordered[0]


def rows_from_matrix(matrix: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    """Glava + podatkovne vrstice → seznam slovarjev (samo vrstice s pozitivno številko v 1. stolpcu)."""
    if not matrix:
        return []
    names = column_names(list(matrix[0]))
    width = len(names)
    out: list[dict[str, Any]] = []
    for raw in matrix[1:]:
        cells = list(raw)[:width] + [None] * max(0, width - len(raw))
        if not cells or not _first_column_ok(cells[0]):
            continue
        out.append({names[i]: _cell_value(cells[i]) for i in range(width)})
    return out


def _read_xlsx(path: Path) -> tuple[str, list[list[Any]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - odvisno od namestitve
        raise ProjestError("Manjka paket openpyxl (py -3.10 -m pip install -r requirements.txt).") from exc
    wb = load_workbook(path, read_only=False, data_only=True)
    try:
        sheet = _pick_sheet(ws.title for ws in wb.worksheets)
        ws = wb[sheet]
        matrix = [list(r) for r in ws.iter_rows(values_only=True)]
        return sheet, matrix
    finally:
        wb.close()


def _read_xls(path: Path) -> tuple[str, list[list[Any]]]:
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - odvisno od namestitve
        raise ProjestError("Manjka paket xlrd za .xls (py -3.10 -m pip install -r requirements.txt).") from exc
    book = xlrd.open_workbook(str(path), on_demand=True)
    try:
        sheet = _pick_sheet(book.sheet_names())
        sh = book.sheet_by_name(sheet)
        matrix: list[list[Any]] = []
        for r in range(sh.nrows):
            row: list[Any] = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                    row.append(None)
                elif cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    row.append(bool(cell.value))
                else:
                    row.append(cell.value)
            matrix.append(row)
        return sheet, matrix
    finally:
        book.release_resources()


def read_excel_book(path: Path, kind: str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ProjestError(f"Datoteka ne obstaja: {path}")
    ext = path.suffix.lower()
    try:
        if ext == ".xls":
            sheet, matrix = _read_xls(path)
        elif ext in {".xlsx", ".xlsm"}:
            sheet, matrix = _read_xlsx(path)
        else:
            raise ProjestError(f"Nepodprta vrsta datoteke: {path.name} (pričakujem .xls, .xlsx ali .xlsm).")
    except ProjestError:
        raise
    except Exception as exc:
        raise ProjestError(f"Excel datoteke ni mogoče prebrati: {path.name} ({exc})") from exc
    return {"kind": kind, "path": str(path), "sheet": ace_sheet_name(sheet), "rows": rows_from_matrix(matrix)}


def read_excel_books(files: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    """[(vrsta, pot)] → [{kind, path, sheet, rows}] (enako kot prej ACE most)."""
    return [read_excel_book(Path(path), kind) for kind, path in files]
