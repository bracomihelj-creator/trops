"""DDV-O: znani rezultat za Zšt 21, oktober 2026 (obveznost 6.828,00 → f51 = 6828)."""
from __future__ import annotations

from conftest import needs_real


@needs_real
def test_ddvo_summary_october_2026(motor21):
    d = motor21.compute_ddvo()
    assert d["ok"] is True
    s = d["summary"]
    assert s["output_vat"] == "19.983,00"
    assert s["input_vat"] == "13.155,00"
    assert s["obligation"] == "6.828,00"
    assert s["control_ok"] is True


@needs_real
def test_ddvo_xml_f51(motor21):
    from lxml import etree

    from trops_studio import ddvo_actions

    ir, pr = motor21._period_rows()
    ds = ddvo_actions.make_dataset(ir, pr, period_from=motor21.filter_from_date, period_to=motor21.filter_to_date, company=motor21.active_company)
    import kirkpr_ddvo_xml as dx

    raw = dx.build_ddvo_xml_bytes(ds)
    body = raw.split(b"-->", 1)[1].strip() if b"-->" in raw else raw
    root = etree.fromstring(body)
    fields = {el.tag.split("}")[-1]: (el.text or "") for el in root.iter() if isinstance(el.tag, str)}
    assert fields.get("f51") == "6828"


@needs_real
def test_analysis_uses_obligation(motor21):
    text = motor21.analysis_text()["text"]
    assert "6.828,00" in text


@needs_real
def test_counts(motor21):
    assert motor21.list_ir()["count"] == 186
    assert motor21.list_pr()["count"] == 56


def test_ddvo_out_dir_per_company(tmp_path, monkeypatch):
    """5.1: DDV-O gre v TROPS_ROOT\\<Zšt>\\DDV (ne v TROPS_ROOT\\21\\<Zšt>\\DDV); brez mape podjetja → rezervna mapa."""
    from trops_studio import ddvo_actions

    (tmp_path / "21").mkdir()
    (tmp_path / "41").mkdir()
    (tmp_path / "01").mkdir()
    monkeypatch.setattr(ddvo_actions, "TROPS_ROOT", tmp_path)
    monkeypatch.setattr(ddvo_actions, "DEFAULT_MINIMAX_OUT", tmp_path / "21" / "MiniMax")
    assert ddvo_actions._out_dir({"Zšt": "21"}) == tmp_path / "21" / "DDV"
    assert ddvo_actions._out_dir({"Zšt": "41"}) == tmp_path / "41" / "DDV"
    assert ddvo_actions._out_dir({"Zšt": "1"}) == tmp_path / "01" / "DDV"
    assert not (tmp_path / "21" / "21").exists()
    fallback = ddvo_actions._out_dir({"Zšt": "77", "Kratko ime": "Test 77"})
    assert fallback.parent == tmp_path / "21" / "MiniMax" / "DDV-O"
