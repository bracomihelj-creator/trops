"""Privzeta mapa za uvoz Excela: TROPS_ROOT\\<Zšt>\\DDV (sicer mapa podjetja, sicer last_used)."""
from __future__ import annotations

from trops_studio import config


def test_excel_import_dir_uses_company_ddv(tmp_path, monkeypatch):
    (tmp_path / "21" / "DDV").mkdir(parents=True)
    (tmp_path / "01").mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(config, "TROPS_ROOT", tmp_path)

    assert config.company_trops_dir("21") == tmp_path / "21"
    assert config.company_trops_dir(1) == tmp_path / "01"
    assert config.company_trops_dir("77") is None
    assert config.company_trops_dir("") is None

    assert config.excel_import_initial_dir("21", str(other)) == str(tmp_path / "21" / "DDV")
    assert config.excel_import_initial_dir("1") == str(tmp_path / "01")
    assert config.excel_import_initial_dir("77", str(other)) == str(other)
    assert config.excel_import_initial_dir(None) == "."
    file_in_other = other / "x.xls"
    file_in_other.write_text("x", encoding="utf-8")
    assert config.excel_import_initial_dir("99", str(file_in_other)) == str(other)
