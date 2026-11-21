from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from trops_studio.config import EVIDENCA_FIRM_ROOT, KIRKPR_CURSOR_ROOT

REGISTRY_CANDIDATES = (
    EVIDENCA_FIRM_ROOT / "data" / "firme_evidenca.json",
    EVIDENCA_FIRM_ROOT / "firme_evidenca.json",
)


def _text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def company_key(record: Mapping[str, Any]) -> str:
    zst = re.sub(r"\D", "", _text(record, "Zšt", "ZST", "ZŠT"))
    if zst:
        return f"zst-{int(zst)}"
    org_id = re.sub(r"\D", "", _text(record, "Org_ID", "OrganisationId"))
    if org_id:
        return f"org-{org_id}"
    tax = re.sub(r"\D", "", _text(record, "DAVČNA", "DAVCNA", "ID za DDV"))
    return f"tax-{tax}" if tax else "company-unknown"


def company_name(record: Mapping[str, Any]) -> str:
    return _text(record, "Kratko ime", "Dolgo", "NAZIV", "Name") or "Neimenovano"


def company_tax(record: Mapping[str, Any]) -> str:
    return re.sub(r"\D", "", _text(record, "DAVČNA", "DAVCNA", "ID za DDV", "TaxNumber"))


def company_zst(record: Mapping[str, Any]) -> str:
    value = re.sub(r"\D", "", _text(record, "Zšt", "ZST", "ZŠT"))
    return str(int(value)) if value else ""


def company_org_id(record: Mapping[str, Any]) -> str:
    return re.sub(r"\D", "", _text(record, "Org_ID", "OrganisationId", "OrganizationId"))


def company_source_kind(record: Mapping[str, Any] | None) -> str:
    """Vir podatkov v Trops Studio: projest | integra | kirkpr."""
    zst = company_zst(record or {})
    if zst == "21":
        return "projest"
    if zst == "20":
        return "integra"
    # Ostale firme (KLUG, …): skoraj vedno FURS KIR/KPR.
    return "kirkpr"


def company_ddv_cadence(record: Mapping[str, Any] | None) -> str:
    """Frekvenca oddaje DDV: monthly | quarterly | yearly.

    Iz evidence firm (`oddaja DDV`). Če polja ni:
    Projest → mesečni, Integra → tromesečni.
    """
    text = _text(record or {}, "oddaja DDV", "Oddaja DDV", "ODDAJA DDV").casefold()
    text = (
        text.replace("č", "c")
        .replace("š", "s")
        .replace("ž", "z")
        .replace("ć", "c")
    )
    if "tromese" in text or "kvart" in text:
        return "quarterly"
    if "letn" in text:
        return "yearly"
    if "mese" in text:
        return "monthly"
    kind = company_source_kind(record)
    if kind == "integra":
        return "quarterly"
    return "monthly"


def is_active(record: Mapping[str, Any]) -> bool:
    active = _text(record, "Aktiven", "AKTIVEN").upper()
    cooperation = _text(record, "Sodelovanje", "SODELOVANJE").casefold()
    return active not in {"NE", "N", "0", "FALSE"} and "prekin" not in cooperation


def load_companies() -> tuple[Path | None, list[dict[str, Any]]]:
    # Register podjetij iz KirKpr_convert_cursor, sicer Evidenca firm (JSON).
    for kirkpr in (KIRKPR_CURSOR_ROOT,):
        if kirkpr.is_dir() and str(kirkpr) not in sys.path:
            sys.path.insert(0, str(kirkpr))
        try:
            from kirkpr_company_registry import load_companies as kirkpr_load  # type: ignore

            return kirkpr_load()
        except Exception:
            logging.getLogger(__name__).warning("Register podjetij iz KirKpr ni uspel (%s)", kirkpr, exc_info=True)
            continue

    source = next((path for path in REGISTRY_CANDIDATES if isinstance(path, Path) and path.is_file()), None)
    if source is None:
        return None, []
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        logging.getLogger(__name__).warning("Evidenca firm ni berljiva: %s", source, exc_info=True)
        return source, []
    rows: Any = payload.get("companies") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return source, []
    companies = [dict(row) for row in rows if isinstance(row, Mapping) and is_active(row)]

    def sort_key(record: Mapping[str, Any]) -> tuple[int, str]:
        zst = company_zst(record)
        return (int(zst) if zst else 999999, company_name(record).casefold())

    return source, sorted(companies, key=sort_key)


def find_company(companies: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((dict(c) for c in companies if company_key(c) == key), None)
