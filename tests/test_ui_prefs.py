"""Videz Trops 4 / Trops 5: shranjevanje v settings.local.json."""
from __future__ import annotations

import json

import pytest

from trops_studio_web.ui_prefs import PrefError, load_ui_prefs, save_ui_pref


def test_defaults_when_missing(tmp_path):
    assert load_ui_prefs(tmp_path / "settings.local.json") == {"ui_videz": "t5", "ui_tema": "light"}


def test_save_keeps_other_keys(tmp_path):
    p = tmp_path / "settings.local.json"
    p.write_text(json.dumps({"trops_root": "D:\\Trops", "ui_tema": "dark"}), encoding="utf-8")
    res = save_ui_pref("ui_videz", "t4", p)
    assert res["ok"] and res["changed"]
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"trops_root": "D:\\Trops", "ui_tema": "dark", "ui_videz": "t4"}
    assert load_ui_prefs(p) == {"ui_videz": "t4", "ui_tema": "dark"}
    assert save_ui_pref("ui_videz", "t4", p)["changed"] is False


@pytest.mark.parametrize("key,value", [("data_dir", "C:\\x"), ("ui_videz", "t3"), ("ui_tema", "<b>")])
def test_rejects_unknown(tmp_path, key, value):
    p = tmp_path / "settings.local.json"
    with pytest.raises(PrefError):
        save_ui_pref(key, value, p)
    assert not p.exists()


def test_broken_file_not_overwritten(tmp_path):
    p = tmp_path / "settings.local.json"
    p.write_text("{pokvarjeno", encoding="utf-8")
    assert load_ui_prefs(p)["ui_videz"] == "t5"
    with pytest.raises(PrefError):
        save_ui_pref("ui_videz", "t4", p)
    assert p.read_text(encoding="utf-8") == "{pokvarjeno"


def test_invalid_value_in_file_falls_back(tmp_path):
    p = tmp_path / "settings.local.json"
    p.write_text(json.dumps({"ui_videz": "xx"}), encoding="utf-8")
    assert load_ui_prefs(p)["ui_videz"] == "t5"
