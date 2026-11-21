"""Nastavitve videza (Trops 4 / Trops 5, tema) — shranjene v settings.local.json.

Samo videz: nobena poslovna logika ali izračun ni odvisen od teh vrednosti.
settings.local.json ni v gitu in ga nadgradnja ne prepiše; ostali ključi v datoteki ostanejo nespremenjeni.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from trops_studio.config import APP_ROOT
from trops_studio_web.accounts_parties import InputError

log = logging.getLogger("trops_studio")

LOCAL_SETTINGS = APP_ROOT / "settings.local.json"
# Dovoljeni ključi in vrednosti; prva vrednost je privzeta.
UI_PREFS: dict[str, tuple[str, ...]] = {
    "ui_videz": ("t5", "t4"),
    "ui_tema": ("light", "dark"),
}
_lock = threading.Lock()


class PrefError(InputError):
    pass


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise PrefError(f"{path.name} ni JSON objekt.")
    return data


def load_ui_prefs(path: Path | None = None) -> dict[str, str]:
    """Trenutne vrednosti (neveljavne ali manjkajoče → privzeto). Napaka pri branju ne ustavi zagona."""
    path = path or LOCAL_SETTINGS
    try:
        data = _read(path)
    except (OSError, ValueError) as exc:
        log.warning("Nastavitve videza ni mogoče prebrati iz %s: %s", path, exc)
        data = {}
    out: dict[str, str] = {}
    for key, allowed in UI_PREFS.items():
        val = str(data.get(key) or "")
        out[key] = val if val in allowed else allowed[0]
    return out


def save_ui_pref(key: Any, value: Any, path: Path | None = None) -> dict[str, Any]:
    """Zapiše en ključ v settings.local.json (atomarno, ostali ključi ostanejo)."""
    key, value = str(key or ""), str(value or "")
    if key not in UI_PREFS:
        raise PrefError(f"Neznana nastavitev videza: {key}")
    if value not in UI_PREFS[key]:
        raise PrefError(f"Neveljavna vrednost za {key}: {value}")
    path = path or LOCAL_SETTINGS
    with _lock:
        try:
            data = _read(path)
        except ValueError as exc:
            # Pokvarjene datoteke ne prepišemo — uporabnik jo mora najprej popraviti.
            raise PrefError(f"{path.name} ni berljiv ({exc}); nastavitev videza ni shranjena.") from exc
        if data.get(key) == value:
            return {"ok": True, "key": key, "value": value, "changed": False}
        data[key] = value
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    log.info("Nastavitev videza: %s = %s", key, value)
    return {"ok": True, "key": key, "value": value, "changed": True}
