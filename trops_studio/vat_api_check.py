"""Preverba IR/PR po davčnih: Minimax (SI), Minimax+VIES (EU), Minimax+splet (tretje).

SI s predpono → samo šifrant Minimax (brez AJPES, brez nove stranke).
EU predpona → Minimax + VIES. Tretje države → Minimax + splet.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from trops_studio.ajpes_client import lookup_si_company
from trops_studio.config import DATA_DIR
from trops_studio.money import (
    has_country_prefixed_vat_id,
    ir_imported_name_locked,
    normalize_text,
    normalize_vat_id,
    sanitize_display_text,
    tax_digits,
)
from trops_studio.pr_list_view import EU_COUNTRY_CODES, region_label
from trops_studio.vies_client import (
    EU_VAT_COUNTRIES,
    check_eu_vat,
    is_eu_vat_id,
    split_eu_vat,
)

ProgressFn = Callable[[int, int, str], None]
CancelFn = Callable[[], bool]

VAT_CACHE_PATH = DATA_DIR / "vat_api_cache.json"
VAT_SESSION_PATH = DATA_DIR / "vat_api_sessions.json"
VAT_CACHE_DAYS = 180

_LEGAL_RE = re.compile(
    r"\b("
    r"d\.?\s*o\.?\s*o\.?|s\.?\s*p\.?|ltd\.?|llc|inc\.?|gmbh|"
    r"s\.?a\.?r\.?l\.?|a\.?\s*s\.?|k\.?\s*d\.?|z\.?\s*o\.?\s*o\.?"
    r")\b",
    re.I,
)
_SP_RE = re.compile(r"\bs\.?\s*p\.?\b", re.I)
_COMPANY_FORM_RE = re.compile(
    r"\b(d\.?\s*o\.?\s*o\.?|d\.?\s*d\.?|k\.?\s*d\.?|z\.?\s*o\.?\s*o\.?|"
    r"ltd\.?|llc|inc\.?|gmbh|s\.?a\.?r\.?l\.?|a\.?\s*s\.?)\b",
    re.I,
)


@dataclass
class VatApiHit:
    source: str = ""
    vat_id: str = ""
    name: str = ""
    country: str = ""
    region: str = ""
    address: str = ""
    valid: bool | None = None
    message: str = ""
    mm_code: str = ""


def _vat_cache_keys(vat: str) -> list[str]:
    value = normalize_vat_id(vat)
    keys = [value]
    digits = tax_digits(value)
    if digits:
        keys.append(digits)
        keys.append(f"SI{digits}")
    return list(dict.fromkeys(k for k in keys if k))


def load_vat_lookup_cache() -> dict[str, dict[str, Any]]:
    if not VAT_CACHE_PATH.is_file():
        return {}
    try:
        payload = json.loads(VAT_CACHE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_vat_lookup_cache(store: Mapping[str, Any]) -> None:
    VAT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VAT_CACHE_PATH.write_text(
        json.dumps(dict(store), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _hit_from_cache_record(rec: Mapping[str, Any]) -> VatApiHit | None:
    checked = str(rec.get("checked_at") or "")
    if checked:
        try:
            stamp = datetime.fromisoformat(checked.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)
            if age.days > VAT_CACHE_DAYS:
                return None
        except ValueError:
            pass
    valid_raw = rec.get("valid")
    valid: bool | None
    if valid_raw is True or valid_raw is False:
        valid = bool(valid_raw)
    else:
        valid = None
    return VatApiHit(
        source=str(rec.get("source") or ""),
        vat_id=str(rec.get("vat_id") or ""),
        name=str(rec.get("name") or ""),
        country=str(rec.get("country") or ""),
        region=str(rec.get("region") or ""),
        address=str(rec.get("address") or ""),
        valid=valid,
        message=str(rec.get("message") or "Predpomnilnik"),
    )


def cache_get_hit(store: Mapping[str, Any], vat: str) -> VatApiHit | None:
    for key in _vat_cache_keys(vat):
        rec = store.get(key)
        if isinstance(rec, Mapping):
            hit = _hit_from_cache_record(rec)
            if hit is not None:
                if hit.message and "Predpomnilnik" not in hit.message:
                    hit.message = f"{hit.message} · predpomnilnik"
                elif not hit.message:
                    hit.message = "Predpomnilnik"
                return hit
    return None


def cache_put_hit(store: dict[str, Any], vat: str, hit: VatApiHit) -> None:
    rec = {
        "source": hit.source,
        "vat_id": hit.vat_id,
        "name": hit.name,
        "country": hit.country,
        "region": hit.region,
        "address": hit.address,
        "valid": hit.valid,
        "message": hit.message,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    for key in _vat_cache_keys(vat) + _vat_cache_keys(hit.vat_id):
        store[key] = rec


@dataclass
class VatApiRow:
    book: str
    row_id: int
    party_id: int | None
    document_no: str
    date: str
    trops_vat: str
    trops_name: str
    trops_region: str
    trops_country: str
    api: VatApiHit = field(default_factory=VatApiHit)
    diffs: list[str] = field(default_factory=list)
    check_kind: str = ""
    check_status: str = ""

    @property
    def has_diff(self) -> bool:
        return bool(self.diffs)


@dataclass
class VatApiReport:
    book: str
    rows: list[VatApiRow] = field(default_factory=list)
    unique_vats: int = 0
    diff_count: int = 0
    ajpes_login: bool = False
    mm_ok: bool = False
    message: str = ""
    mode: str = "vat"  # vat = SI/DE/US… | fo = fizične osebe (brez predpone)


def _hit_to_dict(hit: VatApiHit) -> dict[str, Any]:
    return {
        "source": hit.source,
        "vat_id": hit.vat_id,
        "name": hit.name,
        "country": hit.country,
        "region": hit.region,
        "address": hit.address,
        "valid": hit.valid,
        "message": hit.message,
        "mm_code": hit.mm_code,
    }


def _hit_from_dict(data: Mapping[str, Any] | None) -> VatApiHit:
    rec = data or {}
    valid_raw = rec.get("valid")
    valid: bool | None
    if valid_raw is True or valid_raw is False:
        valid = bool(valid_raw)
    else:
        valid = None
    return VatApiHit(
        source=str(rec.get("source") or ""),
        vat_id=str(rec.get("vat_id") or ""),
        name=str(rec.get("name") or ""),
        country=str(rec.get("country") or ""),
        region=str(rec.get("region") or ""),
        address=str(rec.get("address") or ""),
        valid=valid,
        message=str(rec.get("message") or ""),
        mm_code=str(rec.get("mm_code") or ""),
    )


def report_to_dict(report: VatApiReport) -> dict[str, Any]:
    return {
        "book": report.book,
        "mode": report.mode,
        "unique_vats": report.unique_vats,
        "diff_count": report.diff_count,
        "ajpes_login": report.ajpes_login,
        "mm_ok": report.mm_ok,
        "message": report.message,
        "rows": [
            {
                "book": row.book,
                "row_id": row.row_id,
                "party_id": row.party_id,
                "document_no": row.document_no,
                "date": row.date,
                "trops_vat": row.trops_vat,
                "trops_name": row.trops_name,
                "trops_region": row.trops_region,
                "trops_country": row.trops_country,
                "diffs": list(row.diffs),
                "check_kind": row.check_kind,
                "check_status": row.check_status,
                "api": _hit_to_dict(row.api),
            }
            for row in report.rows
        ],
    }


def report_from_dict(data: Mapping[str, Any] | None) -> VatApiReport | None:
    if not isinstance(data, Mapping):
        return None
    book = str(data.get("book") or "IR").upper() or "IR"
    mode = "fo" if data.get("mode") == "fo" else "vat"
    report = VatApiReport(
        book=book,
        unique_vats=int(data.get("unique_vats") or 0),
        diff_count=int(data.get("diff_count") or 0),
        ajpes_login=bool(data.get("ajpes_login")),
        mm_ok=bool(data.get("mm_ok")),
        message=str(data.get("message") or ""),
        mode=mode,
    )
    for rec in data.get("rows") or []:
        if not isinstance(rec, Mapping):
            continue
        try:
            row_id = int(rec.get("row_id") or 0)
        except (TypeError, ValueError):
            row_id = 0
        party_raw = rec.get("party_id")
        try:
            party_id = int(party_raw) if party_raw not in (None, "") else None
        except (TypeError, ValueError):
            party_id = None
        report.rows.append(
            VatApiRow(
                book=str(rec.get("book") or book),
                row_id=row_id,
                party_id=party_id,
                document_no=str(rec.get("document_no") or ""),
                date=str(rec.get("date") or ""),
                trops_vat=str(rec.get("trops_vat") or ""),
                trops_name=str(rec.get("trops_name") or ""),
                trops_region=str(rec.get("trops_region") or ""),
                trops_country=str(rec.get("trops_country") or ""),
                api=_hit_from_dict(rec.get("api") if isinstance(rec.get("api"), Mapping) else {}),
                diffs=[str(x) for x in (rec.get("diffs") or [])],
                check_kind=str(rec.get("check_kind") or ""),
                check_status=str(rec.get("check_status") or ""),
            )
        )
    if not report.unique_vats:
        report.unique_vats = len({row.trops_vat for row in report.rows if row.trops_vat})
    if not report.diff_count:
        report.diff_count = sum(1 for row in report.rows if row.has_diff)
    return report


def vat_session_key(zst: str | int | None, book: str, mode: str) -> str:
    digits = re.sub(r"\D", "", str(zst or "")) or "0"
    book = (book or "IR").upper() or "IR"
    mode = "fo" if mode == "fo" else "vat"
    return f"{digits}:{book}:{mode}"


def load_vat_session_store() -> dict[str, Any]:
    if not VAT_SESSION_PATH.is_file():
        return {}
    try:
        payload = json.loads(VAT_SESSION_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_vat_session_store(store: Mapping[str, Any]) -> None:
    VAT_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    VAT_SESSION_PATH.write_text(
        json.dumps(dict(store), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def session_stamp_label(iso: str) -> str:
    text = str(iso or "").strip()
    if not text:
        return ""
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone()
        return stamp.strftime("%d. %m. %Y %H:%M")
    except ValueError:
        return text


def save_vat_api_session(
    *,
    zst: str | int | None,
    book: str,
    mode: str,
    period_from: str = "",
    period_to: str = "",
    report: VatApiReport,
) -> None:
    store = load_vat_session_store()
    store[vat_session_key(zst, book, mode)] = {
        "zst": re.sub(r"\D", "", str(zst or "")) or "0",
        "book": report.book,
        "mode": report.mode,
        "period_from": str(period_from or ""),
        "period_to": str(period_to or ""),
        "saved_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "report": report_to_dict(report),
    }
    save_vat_session_store(store)


def load_vat_api_session(
    zst: str | int | None,
    book: str,
    mode: str,
) -> dict[str, Any] | None:
    rec = load_vat_session_store().get(vat_session_key(zst, book, mode))
    if not isinstance(rec, Mapping):
        return None
    report = report_from_dict(rec.get("report") if isinstance(rec.get("report"), Mapping) else None)
    if report is None:
        return None
    return {
        "zst": str(rec.get("zst") or ""),
        "book": report.book,
        "mode": report.mode,
        "period_from": str(rec.get("period_from") or ""),
        "period_to": str(rec.get("period_to") or ""),
        "saved_at": str(rec.get("saved_at") or ""),
        "label": session_stamp_label(str(rec.get("saved_at") or "")),
        "report": report,
    }


def load_company_vat_reports(zst: str | int | None) -> dict[str, VatApiReport]:
    digits = re.sub(r"\D", "", str(zst or ""))
    out: dict[str, VatApiReport] = {}
    if not digits:
        return out
    prefix = f"{digits}:"
    for key, rec in load_vat_session_store().items():
        if not str(key).startswith(prefix) or not isinstance(rec, Mapping):
            continue
        report = report_from_dict(rec.get("report") if isinstance(rec.get("report"), Mapping) else None)
        if report is None:
            continue
        out[f"{report.book}:{report.mode}"] = report
    return out


def compact_party_name(name: str) -> str:
    text = sanitize_display_text(name).casefold()
    text = _LEGAL_RE.sub(" ", text)
    return re.sub(r"[^a-z0-9čćžšđöüäéíáóú]+", "", text)


def names_match(left: str, right: str) -> bool:
    a = compact_party_name(left)
    b = compact_party_name(right)
    if not a or not b:
        return not a and not b
    if a == b:
        return True
    if len(a) >= 6 and len(b) >= 6 and (a in b or b in a):
        return True
    return a[:10] == b[:10] and len(a) >= 8 and len(b) >= 8


def _norm_cc(code: str) -> str:
    cc = normalize_text(code)[:2].upper()
    if cc == "GR":
        return "EL"
    if len(cc) == 2 and cc.isalpha():
        return cc
    return ""


def region_from_country(cc: str) -> str:
    code = _norm_cc(cc)
    if code == "SI":
        return "SI"
    if code in EU_COUNTRY_CODES or code in EU_VAT_COUNTRIES:
        return "EU"
    if code:
        return "FOREIGN"
    return ""


STATUS_MM = "NAJDEN V MINIMAXU"
STATUS_VIES_OK = "VIES POTRJEN"
STATUS_VIES_BAD = "VIES NEVELJAVEN"
STATUS_WEB = "NAJDEN NA SPLETU"
STATUS_MISSING = "STRANKA NI NAJDENA"
STATUS_REVIEW = "POTREBEN PREGLED"


def party_check_kind(value: Any) -> str:
    """SI / EU / THIRD — samo predpona države. Gola 8-mestna ni SI zavezanec."""
    vat = normalize_vat_id(value)
    if not has_country_prefixed_vat_id(vat):
        return ""
    cc = vat[:2].upper()
    if cc == "GR":
        cc = "EL"
    if cc == "SI":
        return "SI"
    if cc in EU_VAT_COUNTRIES:
        return "EU"
    return "THIRD"


def official_register(value: Any) -> str:
    """FO/AJPES: SI (tudi 8 mest) → AJPES; DE/CZ/EU → VIES.

    Preverba zavezancev (mode=vat) uporablja party_check_kind: SI→Minimax.
    """
    vat = normalize_vat_id(value)
    if not vat:
        return ""
    if _is_si_like(vat):
        return "AJPES"
    if len(vat) >= 4 and vat[:2].isalpha() and vat[:2] != "SI" and is_eu_vat_id(vat):
        return "VIES"
    return ""


def has_checkable_vat_id(value: Any) -> bool:
    """IR/PR zavezanec: predpona SI / EU / tretja država."""
    return bool(party_check_kind(value))


def assign_check_status(
    kind: str,
    mm: VatApiHit | None,
    official: VatApiHit | None,
    excel_name: str,
) -> tuple[str, list[str]]:
    """Status preverjanja + neskladja. Ne ustvarja nove Minimax stranke."""
    diffs: list[str] = []
    parts: list[str] = []
    if mm:
        parts.append(STATUS_MM)
        if excel_name and mm.name and not names_match(excel_name, mm.name):
            diffs.append("naziv listina ≠ Minimax")
    if kind == "EU":
        if official and official.source == "VIES":
            if official.valid is True:
                parts.append(STATUS_VIES_OK)
                if official.name and excel_name and not names_match(excel_name, official.name):
                    diffs.append("naziv listina ≠ VIES")
            elif official.valid is False:
                parts.append(STATUS_VIES_BAD)
                diffs.append("VIES: neveljavna davčna")
            else:
                diffs.append(official.message or "VIES ni vrnil podatka")
        else:
            diffs.append("VIES ni preverjen")
    if kind == "THIRD":
        web_ok = bool(
            official
            and official.source == "Splet"
            and (official.name or official.valid is True)
        )
        if web_ok:
            parts.append(STATUS_WEB)
        elif official and official.message:
            diffs.append(official.message)
        elif not mm:
            diffs.append("splet: ni zadetka")
    if not mm:
        if STATUS_VIES_BAD not in parts:
            parts.append(STATUS_MISSING)
        diffs.append("ni v Minimax šifrantu — ne ustvarjaj dvojnika, preglej")
    if diffs and STATUS_MISSING not in parts and STATUS_VIES_BAD not in parts:
        if STATUS_REVIEW not in parts:
            parts.append(STATUS_REVIEW)
    status = " · ".join(dict.fromkeys(parts)) or STATUS_REVIEW
    return status, list(dict.fromkeys(diffs))


def is_natural_person_vat(value: Any) -> bool:
    """IR fizična oseba / končni kupec: ni predpone SI/DE/US…"""
    return not has_country_prefixed_vat_id(value)


def name_has_legal_form(name: str) -> bool:
    """s.p., d.o.o., LLC… — naziv kaže na firmo, ne nujno na FO."""
    text = sanitize_display_text(name)
    return bool(text and _LEGAL_RE.search(text))


def name_is_sole_prop(name: str) -> bool:
    text = sanitize_display_text(name)
    return bool(text and _SP_RE.search(text))


def name_is_capital_company(name: str) -> bool:
    """d.o.o. / d.d. / LLC — podjetje, ne fizična oseba."""
    text = sanitize_display_text(name)
    return bool(text and _COMPANY_FORM_RE.search(text))


def is_bare_eight_digit_tax(value: Any) -> bool:
    """8 mest brez SI/DE/US… — npr. MARKO ŠTOK s.p. / 78920809."""
    vat = normalize_vat_id(value)
    digits = tax_digits(vat)
    return bool(digits and len(digits) == 8 and not has_country_prefixed_vat_id(vat))


def _api_is_si_firm(api: VatApiHit) -> bool:
    return bool(
        api.source
        and api.region == "SI"
        and api.valid is not False
        and (api.name or api.vat_id)
    )


def document_vat_status(row: VatApiRow) -> str:
    """8 mest brez SI = ni davčni zavezanec (npr. JR GYM d.o.o. / 91884764)."""
    if is_bare_eight_digit_tax(row.trops_vat):
        return "Ni davčni zavezanec"
    if has_country_prefixed_vat_id(row.trops_vat):
        return "Zavezanec za DDV"
    return "Ni davčni zavezanec"


def is_sp_vs_fo_row(row: VatApiRow) -> bool:
    """Listina ni zavezanec (8 mest brez SI), AJPES pa je — v potrditev Projestu."""
    return is_bare_eight_digit_tax(row.trops_vat) and _api_is_si_firm(row.api)


def ajpes_party_status(row: VatApiRow) -> str:
    """Status po AJPES/VIES — isto besedilo kot v Minimaxu (podjetje / FO)."""
    api = row.api
    if _api_is_si_firm(api):
        return "Podjetje, zavezanec za DDV"
    if api.source == "VIES" and api.valid is True:
        return "Podjetje, zavezanec za DDV"
    if api.source == "VIES" and api.valid is False:
        return "Podjetje, ni zavezanec za DDV"
    if name_has_legal_form(row.trops_name) or name_has_legal_form(api.name):
        return "Ni v AJPES (naziv s.p./d.o.o.)"
    if is_bare_eight_digit_tax(row.trops_vat):
        return "Ni v AJPES — na listini ni davčni zavezanec"
    return "Končni potrošnik"


def ajpes_status_warning(row: VatApiRow) -> str:
    """Opozorilo: na listini ni zavezanec, po AJPES je — v potrditev."""
    vat = row.trops_vat or "—"
    return (
        f"Na listini {vat} (brez SI) = {document_vat_status(row)}. "
        f"Po preverbi AJPES je status: {ajpes_party_status(row)}. "
        "Prosimo za potrditev."
    )


def sp_fo_decision_rows(report: VatApiReport) -> list[VatApiRow]:
    """V potrditev Projestu: listina ni zavezanec, AJPES je zavezanec."""
    selected: list[VatApiRow] = []
    seen: set[int] = set()
    for row in report.rows:
        if not is_sp_vs_fo_row(row):
            continue
        if row.row_id in seen:
            continue
        seen.add(row.row_id)
        selected.append(row)
    return selected


def _is_si_like(vat: str) -> bool:
    value = normalize_vat_id(vat)
    if value.startswith("SI") and tax_digits(value):
        return True
    country, number = split_eu_vat(value)
    if country == "SI" and number:
        return True
    digits = tax_digits(value)
    return bool(digits and len(digits) == 8 and (not value[:2].isalpha() or value.startswith("SI")))


def _full_si_vat(vat: str) -> str:
    digits = tax_digits(vat)
    return f"SI{digits}" if digits else normalize_vat_id(vat)


def _vats_match(left: str, right: str) -> bool:
    a = normalize_vat_id(left)
    b = normalize_vat_id(right)
    if not a or not b:
        return not a and not b
    if a == b:
        return True
    da, db = tax_digits(a), tax_digits(b)
    if da and db and da == db:
        return True
    return False


def _hit_from_minimax_party(party: Mapping[str, Any]) -> VatApiHit:
    vat = normalize_vat_id(party.get("vat_id") or party.get("tax_number") or "")
    country = _norm_cc(str(party.get("country") or ""))
    if not country and vat[:2].isalpha():
        country = _norm_cc(vat[:2])
    if not country:
        country = "SI" if not party.get("is_foreign") else ""
    region = region_from_country(country)
    if not region and party.get("is_foreign"):
        region = "FOREIGN"
    if not region:
        region = "SI"
    code = normalize_text(party.get("minimax_code") or "")
    return VatApiHit(
        source="Minimax",
        vat_id=vat,
        name=sanitize_display_text(party.get("name") or ""),
        country=country,
        region=region,
        address=sanitize_display_text(party.get("address") or ""),
        message=f"Minimax {code}".strip() if code else "Minimax stranka",
        mm_code=code,
    )


def _index_minimax_customers(client: Any) -> dict[str, dict[str, Any]]:
    from trops_studio.minimax_parties import customer_to_party

    idx: dict[str, dict[str, Any]] = {}
    try:
        rows = list(client._all("customers"))
    except Exception:
        return idx
    for record in rows:
        party = customer_to_party(record)
        if not party:
            continue
        vat = normalize_vat_id(party.get("vat_id") or "")
        tax = tax_digits(party.get("tax_number") or vat)
        if vat:
            idx[vat] = party
        if tax:
            idx[tax] = party
            idx[f"SI{tax}"] = party
        name = sanitize_display_text(party.get("name") or "")
        if name:
            from trops_studio.party_aliases import compact_alias

            compact = compact_alias(name)
            if compact:
                idx[f"name:{compact}"] = party
    return idx


def _lookup_minimax(
    vat: str,
    index: Mapping[str, Mapping[str, Any]] | None,
    name: str = "",
) -> VatApiHit | None:
    if not index:
        return None
    key = normalize_vat_id(vat)
    party = index.get(key)
    if party is None:
        digits = tax_digits(key)
        party = index.get(digits) if digits else None
        if party is None and digits:
            party = index.get(f"SI{digits}")
    if party is None and name:
        from trops_studio.party_aliases import compact_alias, names_match_alias, remember_party_alias

        compact = compact_alias(name)
        if compact:
            party = index.get(f"name:{compact}")
        if party is None:
            for rec in index.values():
                if names_match_alias(name, str(rec.get("name") or "")):
                    party = rec
                    break
        if party:
            try:
                remember_party_alias(
                    name,
                    canonical=str(party.get("name") or ""),
                    minimax_code=str(party.get("minimax_code") or ""),
                )
            except Exception:
                pass
    if not party:
        return None
    return _hit_from_minimax_party(party)


def _lookup_web(vat: str, name: str, country: str = "") -> VatApiHit | None:
    """Tretje države: splet (DuckDuckGo / AI). Ne kliče VIES."""
    try:
        from trops_studio.party_web_ai import lookup_party_on_web
    except Exception as exc:
        return VatApiHit(source="Splet", message=f"Splet ni na voljo: {exc}")
    try:
        res = lookup_party_on_web(
            name=name, vat_id=vat, country=country, check_vies=False
        )
    except Exception as exc:
        return VatApiHit(source="Splet", message=str(exc))
    found = bool(res.ok or res.name or res.sources)
    return VatApiHit(
        source="Splet",
        vat_id=normalize_vat_id(res.vat_id or vat),
        name=sanitize_display_text(res.name),
        country=_norm_cc(res.country) or _norm_cc(country),
        region="FOREIGN",
        address=sanitize_display_text(res.address or res.headquarters),
        valid=True if found else None,
        message=res.message or ("Najden na spletu" if found else "Ni zadetka na spletu"),
    )


def _lookup_official(
    vat: str,
    name: str,
    *,
    use_ajpes: bool,
    use_vies: bool,
    ajpes_blocked: list[bool],
) -> VatApiHit | None:
    value = normalize_vat_id(vat)
    if not value:
        return None
    if not use_ajpes and party_check_kind(value) == "SI":
        return None

    register = official_register(value)
    if register == "AJPES":
        if not use_ajpes or ajpes_blocked[0]:
            return None
        result = lookup_si_company(value, name)
        if result.needs_login:
            ajpes_blocked[0] = True
            return None
        if result.ok and (result.name or result.tax_number):
            tax = result.tax_number or tax_digits(value)
            return VatApiHit(
                source="AJPES",
                vat_id=_full_si_vat(tax or value),
                name=sanitize_display_text(result.name),
                country="SI",
                region="SI",
                address=sanitize_display_text(result.address),
                valid=True,
                message=result.message or "AJPES: slovenska firma",
            )
        return None

    if register != "VIES" or not use_vies:
        return None

    vies_value = value
    vies = check_eu_vat(vies_value)
    if not vies.ok:
        return None
    country = _norm_cc(vies.country)
    return VatApiHit(
        source="VIES",
        vat_id=f"{vies.country}{vies.vat_number}".strip() or vies_value,
        name=sanitize_display_text(vies.name),
        country=country,
        region=region_from_country(country),
        address=sanitize_display_text(vies.address),
        valid=vies.valid,
        message=vies.message,
    )


def _merge_hits(official: VatApiHit | None, mm: VatApiHit | None) -> VatApiHit:
    if official and mm:
        extra = ""
        if official.region and mm.region and official.region != mm.region:
            extra = f" · Minimax {region_label(mm.region)}"
        if not official.name and mm.name:
            official.name = mm.name
        if not official.vat_id and mm.vat_id:
            official.vat_id = mm.vat_id
        official.message = (official.message + extra).strip(" ·")
        return official
    return official or mm or VatApiHit(message="Ni zadetka v AJPES/VIES/Minimax.")


def _collect_diffs(row: VatApiRow, *, mode: str = "vat") -> list[str]:
    diffs: list[str] = []
    api = row.api
    if mode == "fo":
        if not is_bare_eight_digit_tax(row.trops_vat):
            return diffs
        if not _api_is_si_firm(api):
            return diffs
        diffs.append(ajpes_status_warning(row))
        company = name_is_capital_company(row.trops_name) or name_is_capital_company(api.name)
        sole = name_is_sole_prop(row.trops_name) or name_is_sole_prop(api.name)
        if company:
            diffs.append("d.o.o. — v potrditev: na listini ni zavezanec, AJPES je zavezanec")
        elif sole:
            diffs.append("s.p. — v potrditev: zavezanec (s.p.) ali fizična oseba?")
        else:
            diffs.append("v potrditev: na listini ni zavezanec, AJPES je zavezanec")
        if api.vat_id:
            diffs.append(f"če potrdite zavezanca: dodaj predpono {api.vat_id}")
        return diffs
    if not row.trops_vat:
        if row.trops_region in {"EU", "FOREIGN"}:
            diffs.append("brez davčne (EU/tretja)")
        return diffs
    if not api.source:
        diffs.append(api.message or "API ni vrnil podatka")
        return diffs
    if api.valid is False:
        diffs.append("VIES: neveljavna davčna")
    if api.region and row.trops_region and api.region != row.trops_region:
        diffs.append(
            f"regija: {region_label(row.trops_region)} ≠ {region_label(api.region)} ({api.source})"
        )
    if api.vat_id and row.trops_vat and not _vats_match(row.trops_vat, api.vat_id):
        diffs.append(f"davčna: {row.trops_vat} ≠ {api.vat_id}")
    elif api.vat_id and row.trops_vat and normalize_vat_id(row.trops_vat) != normalize_vat_id(api.vat_id):
        diffs.append(f"oblika davčne: {row.trops_vat} → {api.vat_id}")
    if api.name and row.trops_name and not names_match(row.trops_name, api.name):
        diffs.append("naziv se ne ujema")
    return diffs


def check_journal_vats(
    items: Sequence[Mapping[str, Any]],
    *,
    book: str,
    org_id: str = "",
    mode: str = "vat",
    force_refresh: bool = False,
    progress: ProgressFn | None = None,
    cancelled: CancelFn | None = None,
) -> VatApiReport:
    """Preveri listine: SI→Minimax, EU→Minimax+VIES, tretje→Minimax+splet."""
    report = VatApiReport(book=(book or "").upper() or "IR", mode="fo" if mode == "fo" else "vat")
    cache: dict[str, VatApiHit] = {}
    official_cache: dict[str, VatApiHit] = {}
    ajpes_blocked = [False]
    mm_index: dict[str, dict[str, Any]] = {}
    if report.mode == "fo":
        items = [
            item
            for item in items
            if is_natural_person_vat(item.get("vat_id") or item.get("tax_number") or "")
        ]
    else:
        items = [
            item
            for item in items
            if has_checkable_vat_id(item.get("vat_id") or item.get("tax_number") or "")
        ]

    unique_keys: list[str] = []
    seen: set[str] = set()
    prepared: list[tuple[Mapping[str, Any], str]] = []
    for item in items:
        vat = normalize_vat_id(item.get("vat_id") or item.get("tax_number") or "")
        cache_key = vat or f"#{item.get('row_id')}"
        prepared.append((item, cache_key))
        if vat and vat not in seen:
            seen.add(vat)
            unique_keys.append(vat)
    report.unique_vats = len(unique_keys)

    disk = load_vat_lookup_cache()
    cached_n = 0
    if org_id:
        if progress:
            progress(0, max(len(unique_keys), 1), "Minimax: šifrant strank …")
        try:
            from trops_studio.minimax_runtime import open_minimax_client

            client = open_minimax_client(org_id)
            mm_index = _index_minimax_customers(client)
            report.mm_ok = True
        except Exception as exc:
            report.message = f"Minimax API: {exc}"
            report.mm_ok = False

    total = max(len(unique_keys), 1)
    dirty = False
    for index, vat in enumerate(unique_keys, start=1):
        if cancelled and cancelled():
            report.message = (report.message + " · prekinjeno").strip(" ·")
            break
        sample_name = ""
        for item, key in prepared:
            if key == vat:
                sample_name = str(item.get("name") or "")
                break
        kind = party_check_kind(vat)
        official: VatApiHit | None = None
        cached = None if force_refresh else cache_get_hit(disk, vat)
        if report.mode == "fo":
            if progress:
                progress(index, total, f"AJPES {index}/{len(unique_keys)}: {vat}")
            official = _lookup_official(
                vat, sample_name, use_ajpes=True, use_vies=True, ajpes_blocked=ajpes_blocked
            )
        elif kind == "EU":
            if cached and cached.source == "VIES":
                official = cached
                cached_n += 1
            else:
                if progress:
                    progress(index, total, f"VIES {index}/{len(unique_keys)}: {vat}")
                official = _lookup_official(
                    vat, sample_name, use_ajpes=False, use_vies=True, ajpes_blocked=ajpes_blocked
                )
        elif kind == "THIRD":
            if cached and cached.source == "Splet":
                official = cached
                cached_n += 1
            else:
                if progress:
                    progress(index, total, f"Splet {index}/{len(unique_keys)}: {vat}")
                official = _lookup_web(vat, sample_name)
        else:
            if progress:
                progress(index, total, f"Minimax {index}/{len(unique_keys)}: {vat}")
        if official:
            official_cache[vat] = official
        mm = _lookup_minimax(vat, mm_index, sample_name)
        hit = _merge_hits(official, mm)
        if mm and mm.mm_code:
            hit.mm_code = mm.mm_code
        cache[vat] = hit
        to_store = official if official and official.source in {"VIES", "Splet", "AJPES"} else None
        if to_store is not None and not (ajpes_blocked[0] and not to_store.source):
            cache_put_hit(disk, vat, to_store)
            dirty = True
    if dirty:
        try:
            save_vat_lookup_cache(disk)
        except OSError:
            pass

    report.ajpes_login = bool(ajpes_blocked[0])
    if cached_n:
        extra_cache = f"predpomnilnik {cached_n}/{len(unique_keys)}"
        report.message = f"{report.message} · {extra_cache}".strip(" ·") if report.message else extra_cache

    for item, _cache_key in prepared:
        vat = normalize_vat_id(item.get("vat_id") or item.get("tax_number") or "")
        try:
            row_id = int(item.get("row_id") or 0)
        except (TypeError, ValueError):
            row_id = 0
        try:
            party_id = int(item["party_id"]) if item.get("party_id") else None
        except (TypeError, ValueError):
            party_id = None
        region = str(item.get("region") or "")
        api = cache.get(vat) if vat else VatApiHit(
            message="Fizična oseba / končni kupec" if report.mode == "fo" else "Brez ID za DDV."
        )
        if api is None:
            api = VatApiHit(message="Ni zadetka v Minimax/VIES/spletu.")
        excel_name = sanitize_display_text(item.get("name") or "")
        kind = party_check_kind(vat)
        row = VatApiRow(
            book=report.book,
            row_id=row_id,
            party_id=party_id,
            document_no=str(item.get("document_no") or ""),
            date=str(item.get("date") or ""),
            trops_vat=vat,
            trops_name=excel_name,
            trops_region=region,
            trops_country=_norm_cc(str(item.get("country") or "")),
            api=api,
            check_kind=kind,
        )
        if report.mode == "fo":
            row.diffs = _collect_diffs(row, mode=report.mode)
        else:
            mm_hit = _lookup_minimax(vat, mm_index, excel_name)
            official_hit = official_cache.get(vat)
            if official_hit is None and api.source in {"VIES", "Splet"}:
                official_hit = api
            status, diffs = assign_check_status(kind, mm_hit, official_hit, excel_name)
            row.check_status = status
            row.diffs = diffs
        report.rows.append(row)
        if row.has_diff:
            report.diff_count += 1

    parts = [
        "fizične osebe" if report.mode == "fo" else "Minimax / VIES / splet",
        f"{len(report.rows)} listin",
        f"{report.unique_vats} davčnih",
        f"{report.diff_count} razlik",
    ]
    if report.ajpes_login:
        parts.append("AJPES zahteva prijavo")
    if report.message:
        parts.append(report.message)
    report.message = " · ".join(parts)
    return report


def irregularity_rows(report: VatApiReport) -> list[VatApiRow]:
    """Vrstice za e-pošto: zavezanci = razlike; FO = s.p. ali fizična oseba."""
    if report.mode == "fo":
        return sp_fo_decision_rows(report)
    return [row for row in report.rows if row.has_diff]


FO_DECISION_TITLE = "V potrditev: listina ni zavezanec, AJPES je zavezanec"
FO_DECISION_NOTE = (
    "Prosimo za potrditev: na listini ni davčni zavezanec, po AJPES je. "
    "Če je s.p.: zavezanec ali fizična oseba?"
)
FO_COMPANY_NOTE = (
    "Prosimo za potrditev: na listini ni davčni zavezanec, po AJPES je "
    "podjetje-zavezanec — na računu mora biti SI…"
)


def fo_decision_note(row: VatApiRow) -> str:
    names = f"{row.trops_name} {row.api.name}"
    prefix = row.api.vat_id or _full_si_vat(row.trops_vat)
    if name_is_capital_company(names):
        return f"{FO_COMPANY_NOTE} {prefix}".strip()
    return FO_DECISION_NOTE


def _is_confirm_section(title: str) -> bool:
    text = title.casefold()
    return any(token in text for token in ("potrdit", "fizič", "s.p.", "brez si"))


def _html_vat_table(rows: Sequence[VatApiRow], *, fo_question: bool = False) -> list[str]:
    lines = [
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>",
        "<tr>"
        "<th>Dokument</th><th>Datum</th><th>Listina davčna</th><th>Listina ime</th>"
        "<th>Register davčna</th><th>Register ime</th>"
        + (
            "<th>Status na listini</th><th>Status AJPES</th><th>Potrditev</th>"
            if fo_question
            else "<th>Razlika</th>"
        )
        + "</tr>",
    ]
    for row in rows:
        api = row.api
        if fo_question:
            doc_status = document_vat_status(row)
            status = ajpes_party_status(row)
            warning = ajpes_status_warning(row)
            note = fo_decision_note(row)
            status_html = (
                f"<td>{html.escape(doc_status)}</td>"
                f"<td style='background:#fff3cd'><b>{html.escape(status)}</b>"
                f"<br><span>{html.escape(warning)}</span></td>"
            )
            lines.append(
                "<tr>"
                f"<td>{html.escape(row.document_no or '—')}</td>"
                f"<td>{html.escape(row.date or '—')}</td>"
                f"<td>{html.escape(row.trops_vat or '—')}</td>"
                f"<td>{html.escape(row.trops_name or '—')}</td>"
                f"<td>{html.escape(api.vat_id or '—')}</td>"
                f"<td>{html.escape(api.name or '—')}</td>"
                f"{status_html}"
                f"<td>{html.escape(note)}</td>"
                "</tr>"
            )
            continue
        note = "; ".join(row.diffs) if row.diffs else (
            "davčna brez SI" if not has_country_prefixed_vat_id(row.trops_vat) else "—"
        )
        lines.append(
            "<tr>"
            f"<td>{html.escape(row.document_no or '—')}</td>"
            f"<td>{html.escape(row.date or '—')}</td>"
            f"<td>{html.escape(row.trops_vat or '—')}</td>"
            f"<td>{html.escape(row.trops_name or '—')}</td>"
            f"<td>{html.escape(api.vat_id or '—')}</td>"
            f"<td>{html.escape(api.name or '—')}</td>"
            f"<td>{html.escape(note)}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return lines


def format_vat_irregularities_email(
    rows: Sequence[VatApiRow],
    *,
    book: str,
    mode: str = "vat",
    company_name: str = "",
    period_label: str = "",
    extra_sections: Sequence[tuple[str, Sequence[VatApiRow]]] | None = None,
) -> tuple[str, str]:
    """Zadeva + HTML telo za seznam drugačnih davčnih (tudi s.p. vs FO)."""
    sections: list[tuple[str, Sequence[VatApiRow]]] = []
    if rows:
        title = FO_DECISION_TITLE if mode == "fo" else f"{book} zavezanci SI/DE/US"
        sections.append((title, rows))
    for title, extra_rows in extra_sections or ():
        if extra_rows:
            sections.append((title, extra_rows))
    period = period_label or "—"
    firm = company_name or "stranka"
    has_fo = mode == "fo" or any(_is_confirm_section(title) for title, _ in sections)
    if has_fo and len(sections) > 1:
        subject = f"{book} — nepravilnosti ID za DDV in potrditev zavezanca ({period})"
    elif has_fo:
        subject = f"{book} — v potrditev: AJPES zavezanec, na listini ni ({period})"
    else:
        subject = f"{book} — nepravilnosti ID za DDV ({period})"
    total = sum(len(block) for _, block in sections)
    lines = [
        "<p>Spoštovani,</p>",
        f"<p>pri kontroli knjige za obdobje <b>{html.escape(period)}</b> "
        f"({html.escape(firm)}) so nepravilnosti pri ID za DDV"
        + (
            ". 8-mestna davčna brez predpone SI (npr. JR GYM d.o.o. / 91884764) "
            "pomeni, da na listini <b>ni davčni zavezanec</b>"
            if has_fo
            else ""
        )
        + ".</p>",
    ]
    if has_fo:
        lines.append(
            "<p><b>V POTRDITEV:</b> po preverbi AJPES je pri spodnjih kupcih status "
            "<b>Podjetje, zavezanec za DDV</b>, na listini pa je samo 8 mest "
            "(<b>ni davčni zavezanec</b>).</p>"
            "<p>Prosimo za <b>potrditev</b> vsake vrstice:</p>"
            "<ul>"
            "<li><b>potrjujemo zavezanca</b> → na računu mora biti ID za DDV s predpono SI…</li>"
            "<li><b>d.o.o.</b> → podjetje; če potrdite, dodati SI…</li>"
            "<li><b>s.p.</b> → zavezanec (s.p.) ali fizična oseba (končni kupec)?</li>"
            "</ul>"
        )
    else:
        lines.append(
            "<p>Prosimo za pregled in morebiten popravek davčne številke / naziva.</p>"
        )
    for title, block in sections:
        fo_block = _is_confirm_section(title)
        lines.append(f"<h3>{html.escape(title)} ({len(block)})</h3>")
        lines.extend(_html_vat_table(block, fo_question=fo_block))
    lines.append(f"<p>Število nepravilnosti: <b>{total}</b>.</p>")
    lines.append("<p>Lep pozdrav<br>Braco Mihelj</p>")
    return subject, "\n".join(lines)


def apply_api_to_party(
    db: Any,
    row: VatApiRow,
    *,
    update_name: bool = False,
    update_document_vat: bool = True,
) -> str:
    """Uporabi API državo/davčno na stranki (in po potrebi na listini)."""
    api = row.api
    if not api.source or not api.region:
        return "Ni API podatka za popravek."
    party = None
    if row.party_id:
        party = db.get_party(int(row.party_id))
    if party is None and row.trops_vat:
        party = db.find_party_by_tax(row.trops_vat)
    if party is None:
        return "Ni stranke v SQLite — odpri Stranke in shrani partnerja."

    payload = dict(party)
    payload["country"] = api.country or payload.get("country") or ""
    payload["is_foreign"] = 0 if api.region == "SI" else 1
    if api.vat_id:
        payload["vat_id"] = api.vat_id
    if update_name and api.name:
        payload["name"] = api.name
    if api.address and not payload.get("address"):
        payload["address"] = api.address
    if api.source:
        payload["source"] = str(api.source).lower()
    party_id = db.upsert_party(payload, int(party["id"]))

    if update_document_vat and row.row_id and api.vat_id:
        if row.book == "IR":
            doc = db.get_ir(int(row.row_id)) if hasattr(db, "get_ir") else None
            # IR brez vpisane / brez predpone: naziv in davčna ostaneta z uvoza.
            if doc and not ir_imported_name_locked(doc.get("vat_id")) and has_country_prefixed_vat_id(
                doc.get("vat_id")
            ):
                data = dict(doc)
                data["vat_id"] = api.vat_id
                data["party_id"] = party_id
                if update_name and api.name:
                    data["party_name"] = api.name
                db.upsert_ir(data, int(row.row_id))
        elif row.book == "PR":
            doc = db.get_pr(int(row.row_id)) if hasattr(db, "get_pr") else None
            if doc:
                data = dict(doc)
                # Dobavitelj ostane z Excela — API/šifrant ne prepiše naziva.
                if api.vat_id and has_country_prefixed_vat_id(api.vat_id):
                    data["vat_id"] = api.vat_id
                data["party_id"] = party_id
                db.upsert_pr(data, int(row.row_id))
    return ""
