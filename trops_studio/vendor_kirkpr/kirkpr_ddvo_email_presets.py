"""Prednastavitve urejevalnika e-pošte DDV (kot Transkript »Konfiguracija«)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import kirkpr_ddvo_virman as ddvo_virman
import kirkpr_minimax_core as core

PRESETS_NAME = "ddvo_email_editor_presets.json"
DEFAULT_PRESET_ID = "privzeto"


def presets_path(base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else Path(core.config_path()).parent
    return root / PRESETS_NAME


def _default_presets() -> dict[str, dict[str, Any]]:
    return {
        DEFAULT_PRESET_ID: {
            "id": DEFAULT_PRESET_ID,
            "name": "Privzeto",
            "from_smtp": ddvo_virman.DEFAULT_OUTLOOK_FROM,
            "line_height": "1.35",
            "para_spacing_px": 4,
            "read_receipt": True,
            "delivery_receipt": True,
            "defer_send": False,
        },
        "gmail": {
            "id": "gmail",
            "name": "Gmail",
            "from_smtp": "braco.mihelj@gmail.com",
            "line_height": "1.35",
            "para_spacing_px": 4,
            "read_receipt": True,
            "delivery_receipt": True,
            "defer_send": False,
        },
        "windowslive": {
            "id": "windowslive",
            "name": "Windows Live",
            "from_smtp": "bracom@windowslive.com",
            "line_height": "1.35",
            "para_spacing_px": 4,
            "read_receipt": True,
            "delivery_receipt": True,
            "defer_send": False,
        },
        "quickmb": {
            "id": "quickmb",
            "name": "QuickMB info",
            "from_smtp": "info@quickmb.com",
            "line_height": "1.35",
            "para_spacing_px": 6,
            "read_receipt": True,
            "delivery_receipt": True,
            "defer_send": False,
        },
        "tesno": {
            "id": "tesno",
            "name": "Tesno (1.15 / 2 px)",
            "from_smtp": ddvo_virman.DEFAULT_OUTLOOK_FROM,
            "line_height": "1.15",
            "para_spacing_px": 2,
            "read_receipt": True,
            "delivery_receipt": True,
            "defer_send": False,
        },
    }


def _read_raw(base_dir: Path | None = None) -> dict[str, Any]:
    path = presets_path(base_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_presets(base_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    merged = _default_presets()
    raw = _read_raw(base_dir)
    rows = raw.get("presets") if raw else None
    if not isinstance(rows, dict):
        return merged
    for key, row in rows.items():
        if isinstance(row, dict):
            merged[str(key)] = {**merged.get(str(key), {}), **row, "id": str(key)}
    return merged


def get_active_preset_id(base_dir: Path | None = None) -> str:
    raw = _read_raw(base_dir)
    tid = str(raw.get("active_preset_id") or DEFAULT_PRESET_ID).strip() or DEFAULT_PRESET_ID
    presets = load_presets(base_dir)
    return tid if tid in presets else DEFAULT_PRESET_ID


def set_active_preset_id(preset_id: str, base_dir: Path | None = None) -> None:
    presets = load_presets(base_dir)
    tid = str(preset_id or DEFAULT_PRESET_ID).strip() or DEFAULT_PRESET_ID
    if tid not in presets:
        tid = DEFAULT_PRESET_ID
    save_presets(presets, base_dir, active_preset_id=tid)


def save_presets(
    presets: dict[str, dict[str, Any]],
    base_dir: Path | None = None,
    *,
    active_preset_id: str | None = None,
) -> Path:
    path = presets_path(base_dir)
    raw = _read_raw(base_dir)
    active = active_preset_id
    if active is None:
        active = str(raw.get("active_preset_id") or DEFAULT_PRESET_ID)
    if active not in presets:
        active = DEFAULT_PRESET_ID
    payload = {
        "active_preset_id": active,
        "presets": {
            tid: {
                "id": tid,
                "name": str(row.get("name") or tid),
                "from_smtp": str(row.get("from_smtp") or ddvo_virman.DEFAULT_OUTLOOK_FROM),
                "line_height": str(row.get("line_height") or "1.35"),
                "para_spacing_px": int(row.get("para_spacing_px") or 4),
                "read_receipt": bool(row.get("read_receipt", True)),
                "delivery_receipt": bool(row.get("delivery_receipt", True)),
                "defer_send": bool(row.get("defer_send", False)),
            }
            for tid, row in presets.items()
            if isinstance(row, dict)
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def list_presets(base_dir: Path | None = None) -> list[dict[str, Any]]:
    rows = list(load_presets(base_dir).values())
    rows.sort(key=lambda r: (0 if r.get("id") == DEFAULT_PRESET_ID else 1, str(r.get("name") or "").casefold()))
    return rows


def get_preset(preset_id: str = "", base_dir: Path | None = None) -> dict[str, Any]:
    presets = load_presets(base_dir)
    tid = str(preset_id or DEFAULT_PRESET_ID).strip() or DEFAULT_PRESET_ID
    return dict(presets.get(tid) or presets[DEFAULT_PRESET_ID])


def save_preset(
    preset_id: str,
    *,
    name: str,
    from_smtp: str,
    line_height: str,
    para_spacing_px: int,
    read_receipt: bool = True,
    delivery_receipt: bool = True,
    defer_send: bool = False,
    base_dir: Path | None = None,
) -> str:
    tid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(preset_id or name or "custom").strip()) or "custom"
    presets = load_presets(base_dir)
    presets[tid] = {
        "id": tid,
        "name": str(name or tid).strip(),
        "from_smtp": str(from_smtp or ddvo_virman.DEFAULT_OUTLOOK_FROM).strip(),
        "line_height": str(line_height or "1.35").strip(),
        "para_spacing_px": int(para_spacing_px or 4),
        "read_receipt": bool(read_receipt),
        "delivery_receipt": bool(delivery_receipt),
        "defer_send": bool(defer_send),
    }
    save_presets(presets, base_dir)
    return tid


def delete_preset(preset_id: str, base_dir: Path | None = None) -> bool:
    tid = str(preset_id or "").strip()
    if not tid or tid == DEFAULT_PRESET_ID:
        return False
    presets = load_presets(base_dir)
    if tid not in presets:
        return False
    del presets[tid]
    save_presets(presets, base_dir)
    return True


__all__ = [
    "DEFAULT_PRESET_ID",
    "delete_preset",
    "get_active_preset_id",
    "get_preset",
    "list_presets",
    "load_presets",
    "presets_path",
    "save_preset",
    "save_presets",
    "set_active_preset_id",
]
