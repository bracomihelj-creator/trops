"""Vpis novega OS s Tabom v že odprt Minimax (kazalec je v inventarni številki)."""

from __future__ import annotations

import time
from typing import Any, Mapping

from trops_studio.win_keys import (
    find_os_edit_window,
    focus_window,
    press_alt_down,
    press_down,
    press_enter,
    press_tab,
    replace_text,
)


def fill_os_via_keyboard(payload: Mapping[str, str]) -> dict[str, Any]:
    hit = find_os_edit_window()
    if hit is None:
        return {"ok": False, "filled": False, "window": False, "message": "Ni okna Minimax OS."}
    hwnd, title = hit
    if not focus_window(hwnd):
        return {
            "ok": False,
            "filled": False,
            "window": True,
            "message": f"Okna ni bilo mogoče osredotočiti: {title}",
        }
    naziv = str(payload.get("naziv") or payload.get("dobavitelj") or "")
    datum = str(payload.get("datum") or "")
    dobavitelj = str(payload.get("dobavitelj") or "")
    listina = str(payload.get("listina") or "")
    nabava = str(payload.get("nabava") or "")

    # Inventarna številka → Naziv
    press_tab()
    replace_text(naziv)
    # Datum pridobitve
    press_tab()
    replace_text(datum)
    # Dobavitelj (rdeče)
    press_tab()
    replace_text(dobavitelj)
    # Listina (rdeče)
    press_tab()
    replace_text(listina)
    # Kombo: ne F5 (Chrome osveži stran). Alt+↓ → vpis → ↓ → Enter na 20 %.
    press_tab()
    press_alt_down()
    replace_text("Oprema, vozila, mehanizacija")
    time.sleep(0.75)
    press_down()
    press_enter()
    time.sleep(0.4)
    # % amort, analitika, nahajališče, količina, opis
    for _ in range(5):
        press_tab()
    # Datum začetne
    replace_text(datum)
    press_tab()
    # Nabavna vrednost (rdeče)
    replace_text(nabava)
    return {
        "ok": True,
        "filled": True,
        "cdp": False,
        "window": True,
        "keyboard": True,
        "message": f"Vpisano s Tab v {title}. Preveri rdeča polja in Shrani.",
    }
