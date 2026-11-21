"""Mapa DDV\\MRN, uradni CSV eDavki in nalaganje v DDV_Deklaracija_*.xls."""

from __future__ import annotations

import csv
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from trops_studio.config import DEFAULT_TROPS, TROPS_ROOT
from trops_studio.edavki_links import PROJEST_TAX_ID
from trops_studio.edavki_mrn import MrnLookup
from trops_studio.money import decimal_value, money_text

EDAVKI_CSV_HEADER = (
    "Številka MRN;Tip deklaracije;Verzija MRN;Kontrolni rezultat;"
    "Datum priprave sporočila;Datum sprejema carinske deklaracije;"
    "Datum sprostitve blaga;Znesek DDV po deklaraciji;Opombe;"
)


def mrn_folder(zst: str | int | None) -> Path:
    digits = re.sub(r"\D", "", str(zst or ""))
    root = TROPS_ROOT / digits / "DDV" / "MRN" if digits else DEFAULT_TROPS / "DDV" / "MRN"
    root.mkdir(parents=True, exist_ok=True)
    return root


def mrn_period_stamp(day: date | None, fallback: str = "") -> str:
    if day is not None:
        return f"{day.year:04d}{day.month:02d}"
    digits = re.sub(r"\D", "", fallback)
    if len(digits) >= 6:
        if digits[:2] in {"20", "19"}:
            return digits[:6]
        # dd.mm.yyyy
        if len(digits) >= 8:
            return digits[4:8] + digits[2:4]
    return "obdobje"


def mrn_csv_filename(period: str) -> str:
    return f"{period} - DDV-Deklaracija - Seznam carinskih deklaracij.csv"


def deklaracija_xls_path(folder: Path, tax_number: str = PROJEST_TAX_ID) -> Path:
    digits = re.sub(r"\D", "", tax_number or "") or PROJEST_TAX_ID
    return Path(folder) / f"DDV_Deklaracija_{digits}.xls"


def save_edavki_mrn_csv(lookup: MrnLookup, folder: Path, *, period: str) -> Path | None:
    """Uradno ime in stolpci eDavki (vse vrstice, tudi O+P). Če ni vrstic, ne piše datoteke."""
    source = list(lookup.all_rows or lookup.rows)
    if not lookup.ok or lookup.empty or not source:
        return None
    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / mrn_csv_filename(period)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write(EDAVKI_CSV_HEADER + "\n")
        writer = csv.writer(handle, delimiter=";", lineterminator=";\n")
        for row in source:
            writer.writerow(
                [
                    row.mrn,
                    row.tip,
                    row.verzija,
                    row.kontrola,
                    row.datum_priprave,
                    row.datum_sprejema,
                    row.datum_sprostitve,
                    row.vat_text or money_text(row.vat),
                    row.opombe,
                ]
            )
    return path


def _csv_data_rows(csv_path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        for i, raw in enumerate(reader):
            cells = [str(c).strip() for c in raw]
            while cells and cells[-1] == "":
                cells.pop()
            if i == 0 or not cells:
                continue
            if not re.match(r"^\d{2}SI\d+", cells[0], re.I):
                continue
            rows.append(cells)
    return rows


def _excel_cell(value: str, *, date_col: bool = False, money_col: bool = False):
    text = str(value or "").strip()
    if date_col:
        match = re.match(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
        if match:
            return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        return text
    if money_col:
        return float(decimal_value(text))
    return text


def load_csv_into_deklaracija_xls(xls_path: Path, csv_path: Path) -> str:
    """Odpre DDV_Deklaracija_*.xls in doda manjkajoče vrstice iz CSV."""
    xls_path = Path(xls_path)
    csv_path = Path(csv_path)
    if not xls_path.is_file():
        return f"Ni Excel datoteke: {xls_path.name}"
    incoming = _csv_data_rows(csv_path)
    if not incoming:
        os.startfile(str(xls_path))  # type: ignore[attr-defined]
        return "Excel odprt (CSV brez vrstic)."
    try:
        import win32com.client  # type: ignore
    except ImportError:
        os.startfile(str(xls_path))  # type: ignore[attr-defined]
        os.startfile(str(csv_path))  # type: ignore[attr-defined]
        return "Excel + CSV odprta (ni win32com za uvoz)."

    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = True
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(str(xls_path))
    sheet = None
    for sh in wb.Worksheets:
        name = str(sh.Name or "")
        if name.upper() in {"LIST1", "ODDANO"}:
            continue
        if int(sh.UsedRange.Rows.Count) > 1:
            sheet = sh
            break
    sheet = sheet or wb.Worksheets(1)

    used = sheet.UsedRange
    first = int(used.Row)
    last = first + int(used.Rows.Count) - 1
    existing: set[tuple[str, str]] = set()
    last_mrn_row = 2
    for row_i in range(first, last + 1):
        mrn = str(sheet.Cells(row_i, 1).Value or "").strip().upper()
        verz = str(sheet.Cells(row_i, 3).Value or "").strip()
        if re.match(r"^\d{2}SI\d+", mrn, re.I):
            existing.add((mrn, verz))
            last_mrn_row = row_i

    appended = 0
    cursor = last_mrn_row
    date_cols = {5, 6, 7}
    for cells in incoming:
        key = (cells[0].strip().upper(), cells[2].strip() if len(cells) > 2 else "")
        if key in existing:
            continue
        cursor += 1
        vat = decimal_value(cells[7] if len(cells) > 7 else 0)
        for col in range(1, 9):
            raw = cells[col - 1] if col <= len(cells) else ""
            sheet.Cells(cursor, col).Value = _excel_cell(
                raw,
                date_col=col in date_cols,
                money_col=col == 8,
            )
        if vat:
            sheet.Cells(cursor, 9).Value = float(vat / Decimal("0.22"))
        existing.add(key)
        appended += 1
    try:
        excel.Calculate()
    except Exception:
        pass
    try:
        wb.Save()
    except Exception:
        pass
    excel.DisplayAlerts = True
    already = len(existing) - appended
    return f"Excel: dodanih {appended} vrstic iz CSV (že bilo {already})."


def open_mrn_files(xls_path: Path | None, csv_path: Path | None) -> None:
    for path in (xls_path, csv_path):
        if path is not None and Path(path).is_file():
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]
            except OSError:
                pass
