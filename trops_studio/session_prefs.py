"""Zadnji izbor firme in obdobja (seja med zagoni — data/session.json)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from trops_studio.config import DATA_DIR

SESSION_PATH = DATA_DIR / "session.json"


def load_session(path: Path | None = None) -> dict[str, Any]:
    target = path or SESSION_PATH
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_session(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or SESSION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "company_key": str(data.get("company_key") or "").strip(),
        "company_search": str(data.get("company_search") or "").strip(),
        "period_from": str(data.get("period_from") or "").strip(),
        "period_to": str(data.get("period_to") or "").strip(),
        "period_label": str(data.get("period_label") or "").strip(),
        "period_year": str(data.get("period_year") or "").strip(),
        "integra_sql_dir": str(data.get("integra_sql_dir") or "").strip(),
        "integra_auto_irpr": bool(data.get("integra_auto_irpr", True)),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
