from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from trops_studio.config import EVIDENCA_FIRM_ROOT
from trops_studio.money import sanitize_display_text, tax_digits


AJPES_PRS_RESULTS_URL = "https://www.ajpes.si/prs/rezultati.asp"


@dataclass
class AjpesResult:
    ok: bool
    needs_login: bool = False
    message: str = ""
    name: str = ""
    vat_id: str = ""
    tax_number: str = ""
    address: str = ""
    postal_code: str = ""
    city: str = ""
    registration_no: str = ""
    ajpes_code: str = ""
    email: str = ""
    phone: str = ""
    iban: str = ""  # TRR / IBAN (kot EvidencaFirm Transakcijski račun)
    ibans: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""


def eprs_url_by_tax(davcna: str) -> str:
    """URL kot v EvidencaFirm: podrobno=0&tip=0&davcna=8 števk."""
    tax = tax_digits(davcna)
    if len(tax) > 8:
        tax = tax[-8:]
    params = {
        "podrobno": "0",
        "tip": "0",
        "naziv": "",
        "maticna": "",
        "davcna": tax,
        "status": "1",
        "MAXREC": "20",
    }
    return f"{AJPES_PRS_RESULTS_URL}?{urlencode(params)}"


def _ensure_evidenca_path() -> None:
    root = str(EVIDENCA_FIRM_ROOT)
    if root not in sys.path and EVIDENCA_FIRM_ROOT.is_dir():
        sys.path.insert(0, root)


def _detail_get(detail: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = detail.get(key)
        if value is None:
            continue
        text = sanitize_display_text(value)
        if text:
            return text
    lowered = {str(k).casefold(): v for k, v in detail.items()}
    for key in keys:
        value = lowered.get(key.casefold())
        if value is None:
            continue
        text = sanitize_display_text(value)
        if text:
            return text
    return ""


def _merge_phones(*parts: str) -> str:
    """Kot EvidencaFirm._merge_ajpes_phones — telefon / telefaks / GSM."""
    seen: list[str] = []
    for part in parts:
        text = sanitize_display_text(part)
        if not text:
            continue
        key = re.sub(r"\D", "", text)
        if not key or any(re.sub(r"\D", "", s) == key for s in seen):
            continue
        seen.append(text)
    if not seen:
        return ""
    return seen[0] if len(seen) == 1 else " / ".join(seen)


def _split_address(address: str) -> tuple[str, str, str]:
    postal = ""
    city = ""
    street = sanitize_display_text(address)
    if not street:
        return "", "", ""
    parts = [p.strip() for p in street.split(",") if p.strip()]
    if len(parts) >= 2:
        tail = parts[-1].split(None, 1)
        if tail and tail[0].isdigit():
            postal = tail[0]
            city = tail[1] if len(tail) > 1 else ""
            street = ", ".join(parts[:-1]) if len(parts) > 1 else street
    return street, postal, city


def _normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", sanitize_display_text(value)).upper()


def _enrich_pick(pick: Any) -> Any:
    """Lahki enrich (podjetje.asp) — fallback, če company_record_from_candidate ni na voljo."""
    try:
        from minimax_ajpes import enrich_ajpes_candidate_detail  # type: ignore

        return enrich_ajpes_candidate_detail(pick)
    except Exception:
        return pick


def _from_evidenca_record(pick: Any, entity_id: str = "") -> AjpesResult | None:
    """Polni fetch kot EvidencaFirm: ePRS → podjetje.asp p=1 → eRTR (TRR/email/tel)."""
    try:
        from ajpes_company_service import company_record_from_candidate  # type: ignore
    except Exception:
        return None
    try:
        record, ibans, note, _iban_status = company_record_from_candidate(pick, zst=0)
    except Exception:
        return None
    if not isinstance(record, dict):
        return None

    name = sanitize_display_text(
        record.get("Kratko ime") or record.get("Dolgo") or getattr(pick, "company_name", "") or ""
    )
    found_tax = tax_digits(record.get("DAVČNA") or getattr(pick, "davcna", "") or "")
    address_raw = sanitize_display_text(record.get("NASLOV") or "")
    street, postal, city = _split_address(address_raw)
    if not city:
        city = sanitize_display_text(getattr(pick, "city", "") or "")

    iban_list = [_normalize_iban(x) for x in (ibans or []) if _normalize_iban(x)]
    selected = _normalize_iban(str(record.get("Transakcijski račun") or ""))
    if selected and selected not in iban_list:
        iban_list.insert(0, selected)
    elif not selected and iban_list:
        selected = iban_list[0]

    email = sanitize_display_text(record.get("Email") or "")
    phone = sanitize_display_text(record.get("Telefon") or "")
    msg = "OK (EvidencaFirm: ePRS + podjetje.asp + eRTR)"
    if note:
        msg = f"{msg} · {sanitize_display_text(note)[:180]}"

    return AjpesResult(
        ok=True,
        message=msg,
        name=name,
        vat_id="",  # ID za DDV ne inventiramo (ni vsak zavezanec)
        tax_number=found_tax,
        address=street or address_raw,
        postal_code=postal,
        city=city,
        registration_no=tax_digits(record.get("MATIČNA") or "")
        or str(getattr(pick, "maticna", "") or ""),
        ajpes_code=sanitize_display_text(record.get("AJPES sifra") or entity_id or ""),
        email=email,
        phone=phone,
        iban=selected,
        ibans=iban_list,
        source="evidenca-firm-full",
    )


def _from_detail_fallback(pick: Any, tax: str, entity_id: str = "") -> AjpesResult:
    """Fallback: enrich_ajpes_candidate_detail + lokalno branje email/tel/iban."""
    pick = _enrich_pick(pick)
    detail = getattr(pick, "ajpes_detail", None) or {}
    if not isinstance(detail, dict):
        detail = {}

    name = sanitize_display_text(
        getattr(pick, "company_name", "")
        or _detail_get(detail, "Kratko ime", "Dolgo", "company_name")
    )
    found_tax = tax_digits(
        getattr(pick, "davcna", "")
        or _detail_get(detail, "DAVČNA", "davcna")
        or tax
    )
    address = _detail_get(detail, "NASLOV", "address") or sanitize_display_text(
        getattr(pick, "address", "") or ""
    )
    street, postal, city = _split_address(address)
    if not city:
        city = sanitize_display_text(getattr(pick, "city", "") or "")

    email = _detail_get(detail, "email", "eposta", "Email", "E-pošta", "E-posta")
    phone = _merge_phones(
        _detail_get(detail, "telefon", "Telefon", "Phone", "Tel."),
        _detail_get(detail, "telefaks", "Telefaks", "Faks", "Fax"),
        _detail_get(detail, "gsm", "GSM", "Mobilni telefon"),
    )
    iban_raw = _detail_get(detail, "iban", "trr", "Transakcijski račun", "Transakcijski računi")
    # več IBAN ločenih z ; , |
    iban_list = [
        _normalize_iban(p)
        for p in re.split(r"[;,\n|]+", iban_raw)
        if _normalize_iban(p)
    ]
    selected = iban_list[0] if iban_list else ""

    return AjpesResult(
        ok=True,
        message="OK (EvidencaFirm ePRS + podjetje.asp)",
        name=name,
        vat_id="",
        tax_number=found_tax,
        address=street or address,
        postal_code=postal,
        city=city,
        registration_no=_detail_get(detail, "MATIČNA", "maticna")
        or str(getattr(pick, "maticna", "") or ""),
        ajpes_code=_detail_get(detail, "AJPES sifra", "entity_id")
        or str(entity_id or ""),
        email=email,
        phone=phone,
        iban=selected,
        ibans=iban_list,
        source="evidenca-firm",
    )


def lookup_si_company(
    davcna: str,
    naziv: str = "",
    *,
    entity_id: str = "",
) -> AjpesResult:
    """AJPES prek EvidencaFirm (ePRS + podjetje.asp + eRTR) — email, telefon, TRR."""
    tax = tax_digits(davcna)
    if not tax and not naziv.strip() and not str(entity_id or "").strip():
        return AjpesResult(ok=False, message="Vnesi davčno številko (SI), AJPES šifro ali naziv.")

    _ensure_evidenca_path()
    try:
        from ajpes_prs_lookup import lookup_ajpes  # type: ignore
    except Exception as exc:
        return AjpesResult(
            ok=False,
            message=(
                "AJPES modul iz EvidencaFirm ni na voljo "
                f"({exc}). Odpri ePRS ročno:\n{eprs_url_by_tax(tax or davcna)}"
            ),
            tax_number=tax,
            source="fallback-url",
        )

    try:
        lookup = lookup_ajpes(tax or "", naziv or "", entity_id=str(entity_id or ""))
    except Exception as exc:
        return AjpesResult(ok=False, message=f"AJPES iskanje ni uspelo: {exc}", tax_number=tax)

    needs_login = bool(getattr(lookup, "needs_login", False))
    message = str(getattr(lookup, "message", "") or "")
    source = str(getattr(lookup, "source", "") or "")
    pick = getattr(lookup, "pick", None)
    candidates_raw = list(getattr(lookup, "candidates", []) or [])

    candidates: list[dict[str, Any]] = []
    for cand in candidates_raw:
        detail = getattr(cand, "ajpes_detail", None) or {}
        if not isinstance(detail, dict):
            detail = {}
        candidates.append(
            {
                "name": sanitize_display_text(
                    getattr(cand, "company_name", "")
                    or detail.get("Kratko ime")
                    or detail.get("Dolgo")
                    or detail.get("company_name")
                    or ""
                ),
                "tax_number": tax_digits(
                    getattr(cand, "davcna", "")
                    or detail.get("DAVČNA")
                    or detail.get("davcna")
                    or ""
                ),
                "ajpes_code": str(
                    detail.get("AJPES sifra")
                    or detail.get("entity_id")
                    or ""
                ),
                "address": sanitize_display_text(detail.get("NASLOV") or detail.get("address") or ""),
                "registration_no": str(detail.get("MATIČNA") or detail.get("maticna") or ""),
                "email": sanitize_display_text(detail.get("email") or detail.get("Email") or ""),
                "phone": sanitize_display_text(detail.get("telefon") or detail.get("Telefon") or ""),
                "iban": _normalize_iban(str(detail.get("iban") or detail.get("trr") or "")),
                "detail": detail,
            }
        )

    if needs_login:
        return AjpesResult(
            ok=False,
            needs_login=True,
            message=message or "Za AJPES je potrebna prijava (ajpes_config.json).",
            tax_number=tax,
            candidates=candidates,
            source=source,
        )

    if pick is None and candidates:
        return AjpesResult(
            ok=False,
            message=message or "Najdenih je več zadetkov — izberi enega / vnesi AJPES šifro.",
            tax_number=tax,
            candidates=candidates,
            source=source,
        )

    if pick is None:
        return AjpesResult(
            ok=False,
            message=message or "Ni zadetkov na AJPES.",
            tax_number=tax,
            source=source,
        )

    full = _from_evidenca_record(pick, entity_id=str(entity_id or ""))
    if full is not None:
        full.candidates = candidates
        if message and "OK" not in full.message:
            full.message = f"{full.message} · {message}"
        return full

    result = _from_detail_fallback(pick, tax, entity_id=str(entity_id or ""))
    result.candidates = candidates
    return result
