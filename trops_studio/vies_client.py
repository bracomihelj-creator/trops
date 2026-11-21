"""Preverjanje EU ID za DDV prek VIES (SOAP)."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from trops_studio.money import normalize_vat_id, tax_digits

VIES_CHECK_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
VIES_WEB_URL = "https://ec.europa.eu/taxation_customs/vies/#/vat-validation"

# Države z EU VIES (brez SI lahko tudi, SI je vključen)
EU_VAT_COUNTRIES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK", "XI",
})

# Ciper: 8 mest + kontrolna črka (jsvat / uradni format CY########L)
_CY_EVEN_REMAP = {0: 1, 1: 0, 2: 5, 3: 7, 4: 9, 5: 13, 6: 15, 7: 17, 8: 19, 9: 21}


@dataclass
class ViesResult:
    ok: bool
    valid: bool | None = None
    country: str = ""
    vat_number: str = ""
    name: str = ""
    address: str = ""
    message: str = ""
    is_eu: bool = False
    corrected: bool = False  # npr. dopolnjena CY kontrolna črka


def cyprus_check_letter(eight_digits: str) -> str:
    """Vrni kontrolno črko za 8-mestno ciprsko DDV številko."""
    digits = re.sub(r"\D", "", eight_digits)
    if len(digits) != 8:
        raise ValueError("Ciprska DDV številka mora imeti 8 mest pred črko.")
    total = 0
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == 0:
            n = _CY_EVEN_REMAP[n]
        total += n
    return chr(65 + (total % 26))


def normalize_eu_vat_for_vies(country: str, number: str) -> tuple[str, bool]:
    """
    Pripravi številko za VIES.
    Ciper: Impressum pogosto navede CY10342296 brez črke — dopolni npr. T.
    """
    country = (country or "").upper()
    number = re.sub(r"\s+", "", (number or "")).upper()
    if country == "CY":
        if len(number) == 8 and number.isdigit():
            return number + cyprus_check_letter(number), True
        if len(number) == 9 and number[:8].isdigit() and number[8].isalpha():
            expected = cyprus_check_letter(number[:8])
            if number[8] != expected:
                return number[:8] + expected, True
    return number, False


def split_eu_vat(value: str) -> tuple[str, str]:
    """Vrni (država, številka) iz SI12345678 / DE123…"""
    vat = normalize_vat_id(value)
    if len(vat) >= 4 and vat[:2].isalpha() and any(ch.isdigit() for ch in vat[2:]):
        return vat[:2].upper(), vat[2:]
    digits = tax_digits(vat)
    if len(digits) == 8:
        return "SI", digits
    return "", vat


def is_eu_vat_id(value: str) -> bool:
    country, number = split_eu_vat(value)
    return bool(country in EU_VAT_COUNTRIES and number)


def vies_web_url(*, country: str = "", number: str = "") -> str:
    """Spletni VIES obrazec (ročni vnos / pregled)."""
    return VIES_WEB_URL


def check_eu_vat(value: str, *, timeout: int = 25) -> ViesResult:
    """
    Preveri ID za DDV v EU VIES.
    Če ni EU format → is_eu=False.
    Za Ciper dopolni manjkajočo kontrolno črko, če je vnesenih samo 8 mest.
    """
    country, number = split_eu_vat(value)
    if not country or not number:
        return ViesResult(
            ok=False,
            is_eu=False,
            message="Vnesi ID za DDV tipa DE… / IT… / SI… (država + številka).",
        )
    if country not in EU_VAT_COUNTRIES:
        return ViesResult(
            ok=False,
            is_eu=False,
            country=country,
            vat_number=number,
            message=f"Država {country} ni v EU VIES.",
        )

    number, corrected = normalize_eu_vat_for_vies(country, number)

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">'
        "<soapenv:Body>"
        "<urn:checkVat>"
        f"<urn:countryCode>{country}</urn:countryCode>"
        f"<urn:vatNumber>{number}</urn:vatNumber>"
        "</urn:checkVat>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    ).encode()

    req = urllib.request.Request(
        VIES_CHECK_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return ViesResult(
            ok=False,
            is_eu=True,
            country=country,
            vat_number=number,
            corrected=corrected,
            message=f"VIES HTTP {exc.code}: {detail or exc.reason}",
        )
    except urllib.error.URLError as exc:
        return ViesResult(
            ok=False,
            is_eu=True,
            country=country,
            vat_number=number,
            corrected=corrected,
            message=f"VIES povezava ni uspela: {exc.reason}",
        )
    except Exception as exc:
        return ViesResult(
            ok=False,
            is_eu=True,
            country=country,
            vat_number=number,
            corrected=corrected,
            message=f"VIES napaka: {exc}",
        )

    # Namespace-agnostično branje
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return ViesResult(
            ok=False,
            is_eu=True,
            country=country,
            vat_number=number,
            corrected=corrected,
            message="VIES je vrnil neveljaven XML.",
        )

    def _find_text(*names: str) -> str:
        for el in root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local in names and el.text:
                return str(el.text).strip()
        return ""

    valid_raw = _find_text("valid").casefold()
    valid = valid_raw in {"true", "1", "yes"}
    name = re.sub(r"\s+", " ", _find_text("name")).strip()
    address = re.sub(r"\s+", " ", _find_text("address")).strip()
    if valid_raw == "":
        fault = _find_text("faultstring", "FaultString", "message")
        return ViesResult(
            ok=False,
            is_eu=True,
            country=country,
            vat_number=number,
            corrected=corrected,
            message=fault or "VIES ni vrnil rezultata (morda preobremenjen).",
        )

    full = f"{country}{number}"
    if valid:
        msg = f"VIES: {full} JE V SISTEMU (veljavna)."
        if corrected:
            msg += " Dopolnjena kontrolna črka (Ciper: 8 mest + črka)."
    else:
        msg = f"VIES: {full} NI V SISTEMU (neveljavna)."
        if corrected:
            msg += " (Številka je bila dopolnjena s kontrolno črko.)"

    return ViesResult(
        ok=True,
        valid=valid,
        is_eu=True,
        country=country,
        vat_number=number,
        corrected=corrected,
        name="" if name.upper() in {"---", "-"} else name,
        address="" if address.upper() in {"---", "-"} else address,
        message=msg,
    )
