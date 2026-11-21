"""Skupne nastavitve testov Trops Studio 5.

* Vsak test teče na KOPIJI baz v začasni mapi (TROPS_DATA_DIR) — prave baze ostanejo nedotaknjene.
* Omrežje je blokirano (razen 127.0.0.1): noben test ne kliče Minimax, eDavki, AJPES ali SMTP.
* Realni podatki (zst-21.sqlite3) se iščejo v TROPS_TEST_FIXTURES ali v ./data; brez njih se
  testi z realnimi zneski preskočijo.
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
FIXTURES = Path(os.environ.get("TROPS_TEST_FIXTURES") or (APP / "data"))
_TMP = Path(tempfile.mkdtemp(prefix="trops5-test-"))
os.environ["TROPS_DATA_DIR"] = str(_TMP / "data")
os.environ.setdefault("TROPS_WEBVIEW_PROFILE_DIR", str(_TMP / "wv"))
(_TMP / "data").mkdir(parents=True, exist_ok=True)
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

REAL_DB = FIXTURES / "zst-21.sqlite3"
HAS_REAL = REAL_DB.is_file()
needs_real = pytest.mark.skipif(not HAS_REAL, reason="ni realne baze zst-21.sqlite3 (TROPS_TEST_FIXTURES)")

_real_connect = socket.socket.connect


def _guarded_connect(self, address):  # pragma: no cover - varovalo
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"Test je poskusil zunanji klic: {address!r}")
    return _real_connect(self, address)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    yield


@pytest.fixture()
def data_dir():
    """Prazna data mapa (vsak test sveža)."""
    d = Path(os.environ["TROPS_DATA_DIR"])
    for p in d.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink()
    return d


@pytest.fixture()
def motor21(data_dir):
    """Motor z izbranim podjetjem Zšt 21 in obdobjem oktober 2026 (kopija realne baze)."""
    if not HAS_REAL:
        pytest.skip("ni realne baze zst-21.sqlite3")
    shutil.copy2(REAL_DB, data_dir / "zst-21.sqlite3")
    import motor

    m = motor.Motor()
    m.companies = [{"Zšt": "21", "Kratko ime": "PROJEST test"}]
    m.select_company("zst-21", "21", "", "")
    m.set_period("2026-10-01", "2026-10-31")
    return m


@pytest.fixture()
def empty_motor(data_dir):
    """Motor s prazno bazo podjetja 99 (sintetični podatki)."""
    import motor

    m = motor.Motor()
    m.companies = [{"Zšt": "99", "Kratko ime": "Test 99"}]
    m.select_company("zst-99", "99", "", "")
    m.set_period("2026-10-01", "2026-10-31")
    return m
