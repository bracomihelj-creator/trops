"""Vasco Excel brez Accessa (5.1): openpyxl/xlrd mora dati enak izhod kot prej ACE most.

Pričakovani izhod so pravi ACE zapisi iz baze (ir_rows/pr_rows.raw_json, Zšt 21): iz njih
sestavimo Excel (glava + besedilne celice, kot jih izvozi Vasco), ga preberemo in primerjamo.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from conftest import REAL_DB, needs_real
from trops_studio import excel_bridge as xb

EXTRA_KEYS = {"minimax_journal_id", "supplier_kind", "vat_fix_note", "os_kpr", "os_amount", "os_contra",
              "os_allocations", "extra_journal_lines"}
LONG_TAIL = " sklepanja v drugi državi članici"


def _ace_rows(table: str, limit: int = 60) -> list[dict]:
    con = sqlite3.connect(REAL_DB)
    try:
        raws = [json.loads(r) for (r,) in con.execute(
            f"SELECT raw_json FROM {table} WHERE raw_json LIKE '{{%' ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        con.close()
    return [{k: v for k, v in d.items() if k not in EXTRA_KEYS} for d in raws]


def _header_from_keys(keys: list[str]) -> list[str | None]:
    """Obratno od ACE: F{n} → prazna glava, # → pika, 64-znakovni naslov podaljšamo."""
    out: list[str | None] = []
    for i, k in enumerate(keys, start=1):
        if k == f"F{i}":
            out.append(None)
        elif len(k) == xb.ACE_MAX_COLUMN_NAME:
            out.append(k.replace("#", ".") + LONG_TAIL)
        else:
            out.append(k.replace("#", "."))
    return out


def _matrix(rows: list[dict]) -> list[list]:
    keys = list(rows[0].keys())
    body = [[r.get(k) for k in keys] for r in rows]
    # vmesna vrstica brez zaporedne številke (npr. vsota) se mora preskočiti
    body.insert(1, ["Skupaj"] + [None] * (len(keys) - 1))
    return [_header_from_keys(keys)] + body


def _write_xlsx(path: Path, matrix: list[list]) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Knjiga"
    for row in matrix:
        ws.append(row)
    wb.create_sheet("Zzz")  # ACE vzame prvi list po abecedi
    wb.save(path)


def _write_xls(path: Path, matrix: list[list]) -> None:
    xlwt = pytest.importorskip("xlwt")
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Knjiga")
    for r, row in enumerate(matrix):
        for c, v in enumerate(row):
            if v is not None:
                ws.write(r, c, v)
    wb.add_sheet("Zzz")
    wb.save(str(path))


def _norm(rows: list[dict]) -> list[dict]:
    # openpyxl ne shrani praznega niza ('') — Excel ga hrani kot prazno celico (None).
    return [{k: (None if v == "" else v) for k, v in r.items()} for r in rows]


@needs_real
@pytest.mark.parametrize("table", ["ir_rows", "pr_rows"])
@pytest.mark.parametrize("ext", ["xlsx", "xls"])
def test_same_output_as_ace(tmp_path, table, ext):
    expected = _ace_rows(table)
    assert expected
    path = tmp_path / f"vasco.{ext}"
    (_write_xlsx if ext == "xlsx" else _write_xls)(path, _matrix(expected))
    book = xb.read_excel_books([("PR" if table == "pr_rows" else "IR:Darila", path)])[0]
    assert book["sheet"] == "Knjiga$"
    assert _norm(book["rows"]) == _norm(expected)
    assert [list(r) for r in book["rows"]] == [list(r) for r in expected]  # enak vrstni red stolpcev


@needs_real
def test_map_ir_identical_after_reparse(tmp_path):
    from trops_studio.excel_map import map_ir, map_pr

    for table, mapper in (("ir_rows", lambda r: map_ir(r, "Darila")), ("pr_rows", None)):
        expected = _ace_rows(table, 25)
        path = tmp_path / f"{table}.xlsx"
        _write_xlsx(path, _matrix(expected))
        got = xb.read_excel_books([("X", path)])[0]["rows"]
        if mapper is None:
            from trops_studio.db import Database

            db = Database(tmp_path / "t.sqlite3")
            mapper = lambda r, db=db: map_pr(r, db)
        for a, b in zip(expected, got):
            ma, mb = mapper(a), mapper(b)
            ma.pop("raw_json"), mb.pop("raw_json")
            assert ma == mb


def test_ace_semantics_synthetic(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from datetime import date

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "B list"
    ws.append(["ZŠ", "Interna št.", None, "Kupec", "Kupec", "Znesek", "Datum"])
    ws.append([1, "A-1", None, "X", "Y", 12.5, date(2026, 10, 31)])
    ws.append(["0", "nič", None, None, None, None, None])        # 0 → preskoči
    ws.append([" 2 ", " ", "z", "", None, 7.0, "31.10.2026"])
    ws.append(["Skupaj", None, None, None, None, 19.5, None])  # ne-številka → preskoči
    wb.create_sheet("A list")  # prvi po abecedi → prazen list, nič vrstic
    p = tmp_path / "s.xlsx"
    wb.save(p)
    book = xb.read_excel_book(p, "IR:Darila")
    assert book["sheet"] == "'A list$'" and book["rows"] == []
    del wb["A list"]
    wb.save(p)
    rows = xb.read_excel_book(p, "IR:Darila")["rows"]
    assert list(rows[0]) == ["ZŠ", "Interna št#", "F3", "Kupec", "F5", "Znesek", "Datum"]
    assert rows[0] == {"ZŠ": 1, "Interna št#": "A-1", "F3": None, "Kupec": "X", "F5": "Y", "Znesek": 12.5, "Datum": "2026-10-31"}
    assert rows[1]["ZŠ"] == " 2 " and rows[1]["Interna št#"] == " " and rows[1]["Znesek"] == 7
    assert len(rows) == 2


def test_unsupported_and_missing(tmp_path):
    from trops_studio.money import ProjestError

    with pytest.raises(ProjestError):
        xb.read_excel_book(tmp_path / "ni.xls", "PR")
    bad = tmp_path / "x.csv"
    bad.write_text("a;b")
    with pytest.raises(ProjestError):
        xb.read_excel_book(bad, "PR")
