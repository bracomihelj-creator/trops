from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _setup_companies(motor, data_dir):
    motor.companies = [
        {"Zšt": "21", "Kratko ime": "PROJEST test", "Org_ID": "179531"},
        {"Zšt": "20", "Kratko ime": "Integra test", "Org_ID": "555001"},
    ]
    motor.select_company("zst-21", "21", "", "")
    motor.set_period("2026-10-01", "2026-10-31")
    return company_db_expected(data_dir)


def company_db_expected(data_dir: Path) -> Path:
    return (Path(data_dir) / "zst-20.sqlite3").resolve()


def _close_motor(motor) -> None:
    db = getattr(motor, "db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass


def test_kisanal_writes_to_zst20_when_projest_selected(empty_motor, data_dir, monkeypatch):
    """Uvoz Integre gre v zst-20, tudi če je izbran Prejest (21). Brez pravega SQL."""
    import trops_studio.integra_irpr as irpr_mod
    import trops_studio.integra_kisanal as kis_mod

    m = empty_motor
    expected = _setup_companies(m, data_dir)
    captured: dict = {}

    def fake_kisanal(**kwargs):
        captured["kisanal_db"] = Path(kwargs["db_path"]).resolve()
        return SimpleNamespace(
            message="UrejanjeKisanal OK",
            year=kwargs.get("year") or 2026,
            db_path=kwargs["db_path"],
        )

    def fake_irpr(db, **kwargs):
        captured["irpr_db"] = Path(db.path).resolve()
        captured["org_id"] = kwargs.get("org_id")
        return SimpleNamespace(message="Prenos OK", ir=3, pr=2)

    monkeypatch.setattr(kis_mod, "urejanje_kisanal_to_sqlite", fake_kisanal)
    monkeypatch.setattr(irpr_mod, "import_kisanal_to_ir_pr", fake_irpr)

    res = m.integra_kisanal(2026)
    assert res["ok"] is True
    assert captured["kisanal_db"] == expected
    assert captured["irpr_db"] == expected
    assert captured["org_id"] == "555001"
    assert Path(res["db_path"]).resolve() == expected
    assert res["target_zst"] == "20"
    assert res["target_company"] == "Integra test"
    assert res["active_is_target"] is False
    assert res["refreshed"] is False
    assert res["irpr"]["ir"] == 3
    assert res["irpr"]["pr"] == 2
    assert "Cilj:" in (res.get("msg") or "")
    assert "Preklopi na podjetje 20" in (res.get("msg") or "")
    # Izbrano ostane podjetje 21 — njegova baza ni cilj uvoza.
    from trops_studio.companies import company_zst

    assert company_zst(m.active_company) == "21"
    assert Path(m.db.path).resolve() != expected
    _close_motor(m)


def test_kisanal_report_uses_ir_pr_fields_not_ir_count(empty_motor, data_dir, monkeypatch):
    import trops_studio.integra_irpr as irpr_mod
    import trops_studio.integra_kisanal as kis_mod

    m = empty_motor
    _setup_companies(m, data_dir)

    monkeypatch.setattr(
        kis_mod,
        "urejanje_kisanal_to_sqlite",
        lambda **kwargs: SimpleNamespace(message="ok", year=2026, db_path=kwargs["db_path"]),
    )
    monkeypatch.setattr(
        irpr_mod,
        "import_kisanal_to_ir_pr",
        lambda db, **kwargs: SimpleNamespace(message="prenos", ir=7, pr=4),
    )
    res = m.integra_kisanal("2026")
    assert res["irpr"]["ir"] == 7
    assert res["irpr"]["pr"] == 4
    assert "ir_count" not in res["irpr"]
    assert "pr_count" not in res["irpr"]
    _close_motor(m)


def test_integra_info_lists_company_20_target(empty_motor, data_dir):
    m = empty_motor
    _setup_companies(m, data_dir)
    info = m.integra_info()
    assert info["ok"] is True
    assert info["target_zst"] == "20"
    assert info["target_company"] == "Integra test"
    assert Path(info["target_db_path"]).resolve() == company_db_expected(data_dir)
    _close_motor(m)


def test_kisanal_refreshes_only_when_company_20_is_active(empty_motor, data_dir, monkeypatch):
    import trops_studio.integra_irpr as irpr_mod
    import trops_studio.integra_kisanal as kis_mod

    m = empty_motor
    m.companies = [
        {"Zšt": "20", "Kratko ime": "Integra test", "Org_ID": "555001"},
    ]
    m.select_company("zst-20", "20", "", "")
    m.set_period("2026-10-01", "2026-10-31")

    monkeypatch.setattr(
        kis_mod,
        "urejanje_kisanal_to_sqlite",
        lambda **kwargs: SimpleNamespace(message="ok", year=2026, db_path=kwargs["db_path"]),
    )
    monkeypatch.setattr(
        irpr_mod,
        "import_kisanal_to_ir_pr",
        lambda db, **kwargs: SimpleNamespace(message="prenos", ir=1, pr=1),
    )
    called = {"n": 0}
    orig = m.refresh_all

    def wrapped():
        called["n"] += 1
        return orig()

    monkeypatch.setattr(m, "refresh_all", wrapped)
    res = m.integra_kisanal(2026)
    assert res["active_is_target"] is True
    assert res["refreshed"] is True
    assert called["n"] == 1
    _close_motor(m)
