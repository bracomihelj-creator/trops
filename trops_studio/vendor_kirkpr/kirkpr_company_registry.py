"""Večpodjetniški register in dinamične mape za KIR/KPR Minimax Studio."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


from trops_studio.config import EVIDENCA_FIRM_REGISTRY_CANDIDATES, TROPS_ROOT

DEFAULT_REGISTRY_CANDIDATES = tuple(EVIDENCA_FIRM_REGISTRY_CANDIDATES)
DEFAULT_TROPS_ROOT = TROPS_ROOT


@dataclass(frozen=True)
class CompanyPaths:
    company_root: Path
    ddv_root: Path
    virmani_root: Path
    workspace: Path
    working_copies: Path
    exports: Path
    attachments: Path


def resolve_trops_root(preferred: Path | str | None = None) -> Path:
    """Vrne korensko mapo TROPS; privzeto D:\\TROPS, sicer konfigurirana pot."""
    if preferred:
        return Path(preferred).expanduser().resolve()
    return DEFAULT_TROPS_ROOT.expanduser().resolve()


def company_virmani_dir(company_root: Path) -> Path:
    """TROPS\\{Zšt}\\Virmani (ali virmani) — kot Minimax / Fakturiranje."""
    root = Path(company_root)
    for name in ("Virmani", "virmani"):
        path = root / name
        if path.is_dir():
            return path
    path = root / "Virmani"
    path.mkdir(parents=True, exist_ok=True)
    return path


def registry_path(preferred: Path | str | None = None) -> Path | None:
    candidates = ([Path(preferred)] if preferred else []) + list(DEFAULT_REGISTRY_CANDIDATES)
    return next((path.expanduser().resolve() for path in candidates if path.is_file()), None)


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
    return _text(record, "Kratko ime", "Dolgo", "NAZIV", "Name") or "Neimenovano podjetje"


def clean_responsible_person_name(raw: str) -> str:
    """Ime odg. osebe brez nazivov (direktor, samostojno, …)."""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.sub(
        r"\(?\b(?:direktor(?:ica)?|samostojn[aoi])\b\)?",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s*,\s*,+", ",", text)
    return text.strip(" ,;-/|")


def company_responsible_person(record: Mapping[str, Any] | None) -> str:
    """Odgovorna oseba iz Evidence firm (brez direktor/samostojno)."""
    if not record:
        return ""
    raw = _text(
        record,
        "Ime in priimek odg osebe",
        "Ime in priimek odg. osebe",
        "Odgovorna oseba",
        "Odg oseba",
        "Kontaktna oseba",
    )
    return clean_responsible_person_name(raw)


def company_tax_number(record: Mapping[str, Any]) -> str:
    return re.sub(r"\D", "", _text(record, "DAVČNA", "DAVCNA", "ID za DDV", "TaxNumber"))


def company_org_id(record: Mapping[str, Any]) -> str:
    return re.sub(r"\D", "", _text(record, "Org_ID", "OrganisationId", "OrganizationId"))


def company_zst(record: Mapping[str, Any]) -> str:
    value = re.sub(r"\D", "", _text(record, "Zšt", "ZST", "ZŠT"))
    return str(int(value)) if value else ""


def is_active(record: Mapping[str, Any]) -> bool:
    active = _text(record, "Aktiven", "AKTIVEN").upper()
    cooperation = _text(record, "Sodelovanje", "SODELOVANJE").casefold()
    return active not in {"NE", "N", "0", "FALSE"} and "prekin" not in cooperation


def load_companies(preferred: Path | str | None = None) -> tuple[Path | None, list[dict[str, Any]]]:
    source = registry_path(preferred)
    if source is None:
        return None, []
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return source, []
    rows: Any = payload.get("companies") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return source, []
    companies = [dict(row) for row in rows if isinstance(row, Mapping) and is_active(row)]

    def sort_key(record: Mapping[str, Any]) -> tuple[int, str]:
        zst = company_zst(record)
        return (int(zst) if zst else 999999, company_name(record).casefold())

    return source, sorted(companies, key=sort_key)


def find_company(companies: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any] | None:
    return next((dict(company) for company in companies if company_key(company) == key), None)


def match_company(
    companies: Sequence[Mapping[str, Any]],
    *,
    tax_number: Any = "",
    source_path: Path | str | None = None,
) -> dict[str, Any] | None:
    wanted_tax = re.sub(r"\D", "", str(tax_number or ""))
    if wanted_tax:
        match = next((company for company in companies if company_tax_number(company) == wanted_tax), None)
        if match is not None:
            return dict(match)
    source = str(source_path or "").replace("/", "\\")
    for company in companies:
        zst = company_zst(company)
        if zst and re.search(rf"\\0*{re.escape(zst)}\\", source, flags=re.I):
            return dict(company)
    return None


def safe_name(value: Any, fallback: str = "podatki") -> str:
    text = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip(" ._")
    return text or fallback


def company_paths(
    record: Mapping[str, Any],
    period_from: str = "",
    period_to: str = "",
    *,
    trops_root: Path | str | None = None,
) -> CompanyPaths:
    zst = company_zst(record)
    if not zst:
        raise ValueError("Izbrano podjetje nima veljavne Zšt.")
    folder_name = str(int(zst)).zfill(2)
    company_root = resolve_trops_root(trops_root) / folder_name
    ddv_root = company_root / "DDV"
    start = str(period_from or "")[:10]
    end = str(period_to or "")[:10]
    if start and end:
        period = safe_name(f"{start}_{end}", "brez_obdobja")
    elif start or end:
        period = safe_name(start or end, "brez_obdobja")
    else:
        period = "brez_obdobja"
    workspace = ddv_root / "KIRKPR_Minimax" / period
    return CompanyPaths(
        company_root=company_root,
        ddv_root=ddv_root,
        virmani_root=company_virmani_dir(company_root),
        workspace=workspace,
        working_copies=workspace / "Delovne_kopije",
        exports=workspace / "Minimax_izvoz",
        attachments=workspace / "Priponke_API",
    )


__all__ = [
    "CompanyPaths",
    "clean_responsible_person_name",
    "company_key",
    "company_name",
    "company_org_id",
    "company_paths",
    "company_responsible_person",
    "company_tax_number",
    "company_virmani_dir",
    "company_zst",
    "find_company",
    "is_active",
    "load_companies",
    "match_company",
    "registry_path",
    "resolve_trops_root",
    "safe_name",
]
