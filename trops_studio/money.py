from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
_ENTITY_RE = re.compile(r"&#x?[0-9A-Fa-f]+;|&[a-zA-Z]+;")
_BAD_CHARS_RE = re.compile(
    r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\ue000-\uf8ff\ufffe\uffff\ufffd]"
)


class ProjestError(RuntimeError):
    """Napaka, primerna za prikaz uporabniku."""


def decimal_value(value: Any) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    if isinstance(value, bool):
        return Decimal(int(value)).quantize(CENT)
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return ZERO
    text = re.sub(r"[^0-9,.+\-]", "", text)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ProjestError(f"Neveljaven znesek: {value!r}") from exc


def is_nonzero(value: Any) -> bool:
    """True, če znesek <> 0 (tudi negativen — storno). Ne uporabljaj > 0."""
    return decimal_value(value) != ZERO


def money_text(value: Any) -> str:
    amount = decimal_value(value)
    raw = f"{amount:,.2f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def sanitize_display_text(value: Any) -> str:
    """Odstrani HTML entitete / hieroglife (&#x…;, private-use) iz nazivov strank."""
    text = str(value or "")
    for _ in range(4):
        nxt = html.unescape(text)
        if nxt == text:
            break
        text = nxt
    text = _ENTITY_RE.sub("", text)
    text = _BAD_CHARS_RE.sub("", text)
    text = (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u00a0", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(value: Any) -> str:
    return sanitize_display_text(value)


def name_needs_repair(value: Any) -> bool:
    text = str(value or "")
    if not text.strip():
        return False
    if "&#" in text or "\ufffd" in text or "???" in text:
        return True
    if _ENTITY_RE.search(text) or _BAD_CHARS_RE.search(text):
        return True
    return sanitize_display_text(text) != re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def normalize_vat_id(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def split_vat_and_mm_code(value: Any) -> tuple[str, str]:
    """
    Loči DDV in MM šifro, če sta zlepjeni (npr. »6364992H 02879«).
    Vrne (vat_del, mm_šifra) — mm je prazen, če ni ločenega vzorca.
    """
    text = str(value or "").strip()
    if not text:
        return "", ""
    m = re.match(r"^(.+?)\s+(\d{4,6})\s*$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return text, ""


def tax_digits(value: Any) -> str:
    text = normalize_vat_id(value)
    if text.startswith("SI") and len(text) > 2:
        text = text[2:]
    return re.sub(r"\D", "", text)


def national_tax_id(value: Any, *, country: str = "") -> str:
    """
    Nacionalni del ID za DDV — ohrani črke (IE: 6388047V, CY: 10342296T).
    Odstrani predpono države, če je vpisana.
    """
    text = normalize_vat_id(value)
    if not text:
        return ""
    cc = normalize_text(country)[:2].upper()
    if len(text) >= 3 and text[:2].isalpha() and any(ch.isdigit() for ch in text[2:]):
        # IE6388047V / SI12345678 → brez predpone
        text = text[2:]
    elif cc and text.startswith(cc) and len(text) > 2:
        text = text[len(cc) :]
    # samo A–Z / 0–9
    return re.sub(r"[^A-Z0-9]", "", text)


def has_country_prefixed_vat_id(value: Any) -> bool:
    """True, če ID za DDV se začne z državo: SI…, DE…, CH…, US…, AT…"""
    vat = normalize_vat_id(value)
    if len(vat) < 4 or not vat[:2].isalpha():
        return False
    return any(ch.isdigit() for ch in vat[2:])


def has_eu_vat_id(value: Any) -> bool:
    """True, če obstaja ID za DDV tipa SI… / AT… / DE… (država + številka).

    Brez take davčne = IR kupec gre na Končne kupce (01345).
    """
    vat = normalize_vat_id(value)
    if len(vat) >= 4 and vat[:2].isalpha() and vat[2:].isalnum() and any(ch.isdigit() for ch in vat[2:]):
        return True
    # SI firma včasih samo 8 mest (brez SI predpono)
    return len(tax_digits(vat)) == 8


def vat_country_and_id(value: Any, *, country: str = "") -> tuple[str, str]:
    """Razčleni zavezanca: ('SI', '12345678'), ('DE', '123456789'), sicer ('', '')."""
    vat = normalize_vat_id(value)
    if not vat:
        return "", ""
    cc = normalize_text(country)[:2].upper()
    if cc == "GR":
        cc = "EL"
    if len(vat) >= 4 and vat[:2].isalpha() and any(ch.isdigit() for ch in vat[2:]):
        prefix = vat[:2].upper()
        if prefix == "GR":
            prefix = "EL"
        national = national_tax_id(vat, country=prefix)
        return prefix, national
    digits = tax_digits(vat)
    if cc and cc != "SI" and cc not in {"", "XX"}:
        return cc, national_tax_id(vat, country=cc) if has_country_prefixed_vat_id(vat) else ""
    return "", digits


def has_taxpayer_vat(value: Any, *, country: str = "") -> bool:
    """Zavezanec samo s predpono: SI…, DE…, CH…, US…, AT…

    PR: brez predpone = podjetje, ni zavezanec za DDV (ne 8-mestna SI).
    IR: predpona → nujno preveri partnerja.
    """
    return has_country_prefixed_vat_id(value)


def ir_imported_name_locked(value: Any) -> bool:
    """IR brez vpisane davčne: naziv ostane z uvoza (Kupec). Ne prepisuj s šifranta."""
    return not bool(normalize_vat_id(value))


def vats_compatible(left: Any, right: Any, *, left_country: str = "", right_country: str = "") -> bool:
    """Isti zavezanec? SI12345678 ≡ 12345678; DE… ≠ SI… tudi če so števke podobne."""
    lp, ln = vat_country_and_id(left, country=left_country)
    rp, rn = vat_country_and_id(right, country=right_country)
    if not ln or not rn:
        return False
    if lp and rp and lp != rp:
        return False
    return ln == rn


def si_tax8(value: Any, *, country: str = "") -> str:
    """Samo SI… predpona + 8 mest. Gola 8-mestna ni zavezanec (PR)."""
    vat = normalize_vat_id(value)
    if not vat.startswith("SI"):
        return ""
    digits = tax_digits(vat)
    return digits if len(digits) == 8 else ""


def ensure_eu_vat_id(
    value: Any,
    *,
    country: Any = "",
    name: Any = "",
) -> str:
    """
    Dopolni EU ID za DDV s predpono države.
    npr. 73496102 + AT → ATU73496102; 3206488LH + IE → IE3206488LH.
    """
    vat = normalize_vat_id(value)
    cc = normalize_text(country)[:2].upper()
    if cc == "GR":
        cc = "EL"
    # že veljavna predpona (razen napačnega SI pri tujcu)
    if len(vat) >= 4 and vat[:2].isalpha() and any(ch.isdigit() for ch in vat[2:]):
        if vat.startswith("SI") and cc and cc != "SI":
            vat = vat[2:]
        elif not vat.startswith("SI") or cc in {"", "SI"}:
            # AT brez U: AT73496102 → ATU73496102
            if vat.startswith("AT") and len(vat) > 2 and vat[2] != "U" and vat[2:].isdigit():
                return f"ATU{vat[2:]}"
            return vat
    if not cc:
        # poskusi iz naziva (Ireland → IE, …)
        try:
            from trops_studio.pr_list_view import country_from_supplier_name

            cc = country_from_supplier_name(str(name or ""))
        except Exception:
            cc = ""
    if not cc or cc == "XX":
        return vat
    national = national_tax_id(vat, country=cc) if vat else ""
    if not national:
        return vat
    if cc == "AT":
        digits = re.sub(r"\D", "", national)
        if national.upper().startswith("U"):
            digits = re.sub(r"\D", "", national[1:])
        return f"ATU{digits}" if digits else vat
    if cc == "EL":
        return f"EL{national}" if not national.startswith("EL") else national
    return f"{cc}{national}"


def infer_country_code(
    *,
    country: Any = "",
    postal_code: Any = "",
    address: Any = "",
    city: Any = "",
    vat_id: Any = "",
) -> str:
    """Država iz polj / naslova (npr. SI pošta 4 mesta, Vrbnje/Radovljica)."""
    vat = normalize_vat_id(vat_id)
    if len(vat) >= 2 and vat[:2].isalpha():
        return vat[:2].upper()
    existing = normalize_text(country)[:2].upper()
    if len(existing) == 2 and existing.isalpha() and existing != "XX":
        return existing
    postal = re.sub(r"\D", "", str(postal_code or ""))
    # Slovenske pošte so 4-mestne (1000–9999)
    if len(postal) == 4 and postal.isdigit():
        return "SI"
    blob = f"{address} {city} {postal_code}".casefold()
    si_hints = (
        "slovenija",
        "slovenia",
        "ljubljana",
        "maribor",
        "celje",
        "kranj",
        "koper",
        "novo mesto",
        "radovljica",
        "vrbnje",
        "d.o.o.",
        "d.d.",
        "s.p.",
    )
    if any(h in blob for h in si_hints):
        return "SI"
    return existing


def parse_date(value: Any, *, field_name: str = "datum") -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        serial = float(text.replace(",", "."))
        if 20_000 <= serial <= 80_000:
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    text = text.split(" ", 1)[0]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ProjestError(f"Neveljaven {field_name}: {value!r}")


def date_text(value: Any) -> str:
    parsed = value if isinstance(value, date) else parse_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else ""


def iso_date(value: Any) -> str | None:
    parsed = value if isinstance(value, date) else parse_date(value)
    return parsed.isoformat() if parsed else None
