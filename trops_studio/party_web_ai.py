"""Iskanje podatkov o stranki na spletu + AI ekstrakcija v strukturo obrazca."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any

from trops_studio.config import DATA_DIR
from trops_studio.money import normalize_text, normalize_vat_id, sanitize_display_text, tax_digits

AI_SETTINGS_PATH = DATA_DIR / "ai_settings.json"

# Znane skupine podjetij: EU VAT ≠ matična družba (npr. Fiverr IL vs CY)
_KNOWN_GROUP_ENTITIES: dict[str, list[dict[str, str]]] = {
    "fiverr": [
        {
            "name": "Fiverr International Ltd.",
            "country": "IL",
            "country_name": "Izrael",
            "vat_id": "",
            "vies": "Ni v VIES — Izrael ni član EU",
            "registration_no": "514440874",
            "tax_file": "917369274",
            "headquarters": "8 Eliezer Kaplan St., Tel Aviv 6473409, Izrael",
            "address": "8 Eliezer Kaplan St.",
            "postal_code": "6473409",
            "city": "Tel Aviv",
            "notes": "Matična družba (IL), ne EU zavezanec",
        },
        {
            "name": "Fiverr Limited",
            "country": "CY",
            "country_name": "Ciper",
            # Ciper VIES: 8 mest + kontrolna črka (Impressum pogosto brez črke T)
            "vat_id": "CY10342296T",
            "vies": "VIES: v sistemu (CY10342296T); C.N. HE 342296",
            "registration_no": "HE342296",
            "tax_file": "",
            "headquarters": "Vasiliou Vryonidi 6, Gala Court Chambers 503, 3095 Limassol, Cyprus",
            "address": "Vasiliou Vryonidi 6, Gala Court Chambers 503",
            "postal_code": "3095",
            "city": "Limassol",
            "notes": "EU subjekt (Ciper). Impressum CY10342296 = VIES CY10342296T",
        },
    ],
    "openai": [
        {
            "name": "OpenAI, L.L.C.",
            "country": "US",
            "country_name": "ZDA",
            "vat_id": "",
            "vies": "Ni v VIES — ZDA niso EU",
            "address": "",
            "notes": "Vzorec: Open AI / OpenAI — najprej poišči v Minimaxu",
        },
    ],
}


def _known_related_entities(name: str, vat: str) -> list[dict[str, str]]:
    blob = f"{name} {vat}".casefold()
    compact = re.sub(r"[^a-z0-9]+", "", blob)
    for key, entities in _KNOWN_GROUP_ENTITIES.items():
        if key in blob or key.replace(" ", "") in compact:
            return [dict(e) for e in entities]
    return []


def _enrich_related_vies(entities: list[dict[str, str]]) -> list[dict[str, str]]:
    """Osveži VIES status za EU VAT v povezanih subjektih (živa preverba)."""
    from trops_studio.vies_client import check_eu_vat, is_eu_vat_id

    out: list[dict[str, str]] = []
    for ent in entities:
        row = dict(ent)
        vat = normalize_vat_id(row.get("vat_id"))
        if vat and is_eu_vat_id(vat):
            try:
                vies = check_eu_vat(vat)
                full = f"{vies.country}{vies.vat_number}" if vies.country else vat
                if vies.ok and vies.valid:
                    row["vat_id"] = full
                    row["vies"] = f"JE V SISTEMU VIES ({full})"
                    if vies.name:
                        row["vies_name"] = vies.name
                        row["name"] = row.get("name") or vies.name
                    if vies.address:
                        row["vies_address"] = vies.address
                elif vies.ok and vies.valid is False:
                    row["vies"] = f"NI V SISTEMU VIES ({full})"
                elif not vies.ok:
                    row["vies"] = vies.message or f"VIES preverjanje ni uspelo ({vat})"
            except Exception as exc:
                row["vies"] = f"VIES napaka: {exc}"
        out.append(row)
    return out


_COUNTRY_NAMES = {
    "izrael": "IL",
    "israel": "IL",
    "ireland": "IE",
    "irlanda": "IE",
    "italy": "IT",
    "italija": "IT",
    "italia": "IT",
    "germany": "DE",
    "nemčija": "DE",
    "nemcija": "DE",
    "slovenia": "SI",
    "slovenija": "SI",
    "netherlands": "NL",
    "nizozemska": "NL",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "cyprus": "CY",
    "ciper": "CY",
    "kipr": "CY",
    "france": "FR",
    "francija": "FR",
    "austria": "AT",
    "avstrija": "AT",
    "croatia": "HR",
    "hrvaška": "HR",
    "hrvaska": "HR",
}


def _country_code_from_name(name: str) -> str:
    key = sanitize_display_text(name).casefold()
    if len(key) == 2 and key.isalpha():
        return key.upper()
    return _COUNTRY_NAMES.get(key, "")


def _split_vies_address(text: str) -> dict[str, str]:
    """
    Razčleni VIES naslov (pogosto brez vejic).
    npr. »VIA M CERVANTES 55/27 80133 NAPOLI NA« → ulica / 80133 / NAPOLI NA
    """
    raw = sanitize_display_text(text)
    if not raw:
        return {}
    out: dict[str, str] = {}
    # Ulica + pošta (4–7 mest) + kraj
    m = re.match(r"^(?P<addr>.+?)\s+(?P<postal>\d{4,7})\s+(?P<city>.+)$", raw)
    if m:
        out["address"] = m.group("addr").strip(" ,")
        out["postal_code"] = m.group("postal")
        out["city"] = m.group("city").strip(" ,")
        return out
    # Pošta na začetku: 80133 NAPOLI, VIA …
    m2 = re.match(r"^(?P<postal>\d{4,7})\s+(?P<rest>.+)$", raw)
    if m2:
        out["postal_code"] = m2.group("postal")
        rest = m2.group("rest").strip()
        if "," in rest:
            city, _, addr = rest.partition(",")
            out["city"] = city.strip()
            out["address"] = addr.strip() or rest
        else:
            out["address"] = rest
        return out
    out["address"] = raw
    return out


def _split_headquarters(text: str) -> dict[str, str]:
    """Razčleni sedež; če ni jasne ulice, celotno pusti za polje address."""
    raw = sanitize_display_text(text)
    if not raw:
        return {}
    parts = [p.strip() for p in re.split(r",\s*", raw) if p.strip()]
    out: dict[str, str] = {"headquarters": raw}
    if not parts:
        return out
    # Ena komponenta — najprej VIES-oblika (ulica + pošta + kraj)
    if len(parts) == 1:
        only = parts[0]
        vies_like = _split_vies_address(only)
        if vies_like.get("postal_code") and (vies_like.get("city") or vies_like.get("address")):
            out.update({k: v for k, v in vies_like.items() if v})
            return out
        m = re.search(r"^(.*?)[\s,]+(\d{4,7})$", only)
        if m and m.group(1).strip() and len(m.group(2)) >= 5:
            # npr. Tel Aviv 6473409
            out["city"] = m.group(1).strip()
            out["postal_code"] = m.group(2)
        else:
            out["address"] = only
        return out
    # Zadnji del: država
    if len(parts) >= 2:
        country_name = parts[-1]
        code = _country_code_from_name(country_name)
        if code or len(country_name) > 2:
            out["country_name"] = country_name
            if code:
                out["country"] = code
            parts = parts[:-1]
    # Predzadnji: mestno + pošta
    if parts:
        city_bit = parts[-1]
        m = re.search(r"^(.*?)[\s,]+(\d{4,7})$", city_bit)
        if m:
            out["city"] = m.group(1).strip()
            out["postal_code"] = m.group(2)
        else:
            m2 = re.search(r"\b(\d{4,7})\b", city_bit)
            if m2:
                out["postal_code"] = m2.group(1)
                out["city"] = city_bit.replace(m2.group(1), "").strip(" ,")
            else:
                out["city"] = city_bit
        parts = parts[:-1]
    if parts:
        out["address"] = ", ".join(parts)
    elif not out.get("address") and raw:
        # Ni ulice po razčlenitvi — celoten sedež v naslov
        out["address"] = raw
    return out


@dataclass
class PartyWebResult:
    ok: bool
    name: str = ""
    address: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""
    country_name: str = ""
    email: str = ""
    phone: str = ""
    registration_no: str = ""
    tax_file: str = ""  # npr. withheld tax file (IL)
    vat_id: str = ""
    website: str = ""
    headquarters: str = ""  # celoten sedež v eni vrstici
    legal_form: str = ""
    notes: str = ""
    vies_status: str = ""  # npr. neveljavna / veljavna / ni EU
    vies_name: str = ""
    vies_address: str = ""
    related_entities: list[dict[str, str]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)
    message: str = ""
    used_ai: bool = False

    def as_form_updates(self) -> dict[str, str]:
        """Polja za obrazec Stranke (samo neprazna). Prednost: VIES naziv/naslov."""

        def _clean(val: Any) -> str:
            text = sanitize_display_text(str(val or "")).strip()
            if not text or text in {"-", "—", ".", "n/a", "N/A"}:
                return ""
            return text

        # Naziv: VIES (uradni) pred AI/spletnim
        name = _clean(self.vies_name) or _clean(self.name)

        address = _clean(self.address)
        postal = _clean(self.postal_code)
        city = _clean(self.city)
        # VIES naslov → razčleni v ulico / pošto / kraj (vedno prednost pred »-«)
        if self.vies_address:
            vies_parts = _split_vies_address(self.vies_address)
            address = address or vies_parts.get("address") or _clean(self.vies_address)
            postal = postal or vies_parts.get("postal_code") or ""
            city = city or vies_parts.get("city") or ""
        if self.headquarters:
            parsed = _split_headquarters(self.headquarters)
            address = address or _clean(parsed.get("address"))
            postal = postal or _clean(parsed.get("postal_code"))
            city = city or _clean(parsed.get("city"))
            if not address:
                address = _clean(self.headquarters)

        vat = normalize_vat_id(self.vat_id)
        country = normalize_text(self.country)[:2].upper()
        if country in {"", "XX"}:
            country = ""
        if not country and self.country_name:
            country = _country_code_from_name(self.country_name)
        if not country and len(vat) >= 2 and vat[:2].isalpha():
            country = vat[:2]
        tax = ""
        if vat and len(vat) > 2 and vat[:2].isalpha():
            tax = vat[2:]

        mapping = {
            "name": name,
            "address": address,
            "postal_code": postal,
            "city": city,
            "country": country,
            "email": _clean(self.email),
            "phone": _clean(self.phone),
            "registration_no": _clean(self.registration_no),
            "vat_id": vat,
            "tax_number": tax,
        }
        return {k: v for k, v in mapping.items() if sanitize_display_text(str(v or ""))}

    def as_listview_rows(self) -> list[tuple[str, str, str]]:
        """Vrstice (oznaka, vrednost, tag) za ListView — čim več podatkov."""
        rows: list[tuple[str, str, str]] = []

        def add(label: str, value: Any, tag: str = "") -> None:
            text = sanitize_display_text(str(value or ""))
            if not text:
                return
            rows.append((label, text, tag))

        add("— Osnovni podatki —", "········", "section")
        add("Naziv podjetja", self.name, "ok" if self.name else "")
        add("Sedež podjetja (celota)", self.headquarters)
        add("Naslov (ulica)", self.address)
        add("Pošta", self.postal_code)
        add("Kraj", self.city)
        add("Država (ISO)", self.country)
        add("Država (naziv)", self.country_name)
        add("Pravna oblika", self.legal_form)

        add("— Identifikatorji —", "········", "section")
        add("ID za DDV (vpisan/iskalni)", self.vat_id)
        add("Matična / registrska št.", self.registration_no)
        add("Davčna datoteka (Withheld Tax File)", self.tax_file)
        add("E-pošta", self.email)
        add("Telefon", self.phone)
        add("Splet", self.website)

        add("— VIES (EU) —", "········", "section")
        vies_tag = "warn"
        if self.vies_status:
            low = self.vies_status.casefold()
            if ("je v sistemu" in low or ("veljav" in low and "neveljav" not in low)) and "ni v sistemu" not in low:
                vies_tag = "ok"
            elif "neveljav" in low or "ni v sistemu" in low or "ni v vies" in low or "ni eu" in low:
                vies_tag = "warn"
        add("VIES status", self.vies_status or "— ni preverjeno —", vies_tag if self.vies_status else "")
        add("VIES naziv", self.vies_name)
        add("VIES naslov", self.vies_address)

        if self.related_entities:
            add("— Povezani subjekti (skupina) —", "········", "section")
            for i, ent in enumerate(self.related_entities, start=1):
                title = sanitize_display_text(ent.get("name")) or f"Subjekt {i}"
                vies_txt = str(ent.get("vies") or "").casefold()
                ok_tag = (
                    "ok"
                    if ("je v sistemu" in vies_txt or ("veljav" in vies_txt and "neveljav" not in vies_txt))
                    and "ni v sistemu" not in vies_txt
                    else ("warn" if vies_txt else "")
                )
                add(f"Subjekt {i}", title, ok_tag)
                for key, label in (
                    ("country_name", "Država"),
                    ("country", "Država ISO"),
                    ("vat_id", "VAT ID"),
                    ("vies", "VIES"),
                    ("registration_no", "Matična / C.N."),
                    ("tax_file", "Davčna datoteka"),
                    ("headquarters", "Sedež"),
                    ("address", "Naslov"),
                    ("postal_code", "Pošta"),
                    ("city", "Kraj"),
                    ("notes", "Opomba"),
                ):
                    add(f"  · {label}", ent.get(key))

        if self.extras:
            add("— Dodatno (AI) —", "········", "section")
            for key, val in self.extras.items():
                add(str(key), val)

        if self.sources:
            add("— Viri —", "········", "section")
            for i, src in enumerate(self.sources[:12], start=1):
                add(f"Vir {i}", src)

        add("— Opombe —", "········", "section")
        add("Opomba", self.notes)
        add("Sporočilo", self.message)
        return rows


def load_ai_settings() -> dict[str, Any]:
    """Nastavitve AI: data/ai_settings.json ali okoljske spremenljivke."""
    cfg: dict[str, Any] = {
        "enabled": True,
        "provider": "openai",
        "api_key": "",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    }
    if AI_SETTINGS_PATH.is_file():
        try:
            payload = json.loads(AI_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                cfg.update({k: payload[k] for k in cfg if k in payload})
                if payload.get("api_key"):
                    cfg["api_key"] = str(payload["api_key"]).strip()
        except (OSError, json.JSONDecodeError):
            pass
    env_key = (
        str(cfg.get("api_key") or "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("PROJEST_AI_API_KEY", "").strip()
    )
    cfg["api_key"] = env_key
    if os.environ.get("OPENAI_BASE_URL"):
        cfg["base_url"] = os.environ["OPENAI_BASE_URL"].rstrip("/")
    if os.environ.get("OPENAI_MODEL"):
        cfg["model"] = os.environ["OPENAI_MODEL"]
    return cfg


def ensure_ai_settings_template() -> Path:
    """Ustvari vzorec ai_settings.json, če manjka."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if AI_SETTINGS_PATH.is_file():
        return AI_SETTINGS_PATH
    sample = {
        "enabled": True,
        "provider": "openai",
        "api_key": "",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "_comment": "Vnesi api_key (OpenAI ali združljiv endpoint). Ali nastavi OPENAI_API_KEY.",
    }
    AI_SETTINGS_PATH.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    return AI_SETTINGS_PATH


def _http_get(url: str, *, timeout: int = 25, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(
        url,
        headers=headers
        or {
            "User-Agent": "Mozilla/5.0 (compatible; ProjestStudio/1.0; +local)",
            "Accept": "text/html,application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _http_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: int = 60,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "ProjestStudio/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("AI API ni vrnil JSON objekta.")
    return data


def duckduckgo_snippets(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Hitri rezultati prek DuckDuckGo HTML (brez ključa)."""
    q = urllib.parse.quote_plus(query.strip())
    if not q:
        return []
    url = f"https://html.duckduckgo.com/html/?q={q}"
    try:
        html = _http_get(url, timeout=20)
    except Exception:
        return []
    results: list[dict[str, str]] = []
    # DuckDuckGo html: result__a + result__snippet
    blocks = re.split(r'class="result__body"', html)
    for block in blocks[1 : limit + 1]:
        title_m = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.I | re.S)
        snip_m = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)', block, re.I | re.S)
        href_m = re.search(r'class="result__a"[^>]*href="([^"]+)"', block, re.I)
        title = _strip_html(title_m.group(1) if title_m else "")
        snippet = _strip_html(snip_m.group(1) if snip_m else "")
        href = unescape(href_m.group(1) if href_m else "")
        if title or snippet:
            results.append({"title": title, "snippet": snippet, "url": href})
    if results:
        return results
    # Fallback: uddg redirect links
    for m in re.finditer(
        r'uddg=([^&"]+).*?class="result__a"[^>]*>(.*?)</a>',
        html,
        re.I | re.S,
    ):
        href = urllib.parse.unquote(m.group(1))
        title = _strip_html(m.group(2))
        if title:
            results.append({"title": title, "snippet": "", "url": href})
        if len(results) >= limit:
            break
    return results


def _strip_html(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_search_query(name: str, vat: str, country: str) -> str:
    parts = [p for p in (name, vat, country, "registered office address") if p]
    return " ".join(parts)


def _ai_extract(
    *,
    name: str,
    vat: str,
    country: str,
    snippets: list[dict[str, str]],
    cfg: dict[str, Any],
) -> PartyWebResult:
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        return PartyWebResult(ok=False, message="Manjka AI api_key.")
    base = str(cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = str(cfg.get("model") or "gpt-4o-mini")
    sources_txt = "\n\n".join(
        f"- {s.get('title')}\n  {s.get('snippet')}\n  {s.get('url')}" for s in snippets[:10]
    )
    system = (
        "Si pomočnik za knjigovodstvo. Iz spletnih zadetkov izlušči uradne podatke podjetja "
        "(registered office / legal address / company registry). "
        "Vrni SAMO veljaven JSON objekt s ključi: "
        "name, headquarters, address, postal_code, city, country, country_name, "
        "email, phone, registration_no, tax_file, website, legal_form, notes, confidence, extras. "
        "country = ISO 2 črki (IL za Izrael, IE za Irsko, …). "
        "country_name = polni naziv države. "
        "headquarters = celoten sedež v eni vrstici, če je znan. "
        "registration_no = matična/company number (NE VAT ID). "
        "tax_file = withheld tax file / davčna datoteka, če obstaja (npr. Izrael). "
        "extras = objekt dodatnih ključ/vrednost (poljubno). "
        "Če ne veš, pusti prazen niz. Ne izmišljuj. "
        "Če je sedež v Izraelu, country=IL tudi če je vpisan EU VAT."
    )
    user = (
        f"Iskanje stranke:\n"
        f"Naziv: {name or '—'}\n"
        f"ID za DDV (samo referenca, ne piši v registration_no): {vat or '—'}\n"
        f"Država (vnos): {country or '—'}\n\n"
        f"Zadetki:\n{sources_txt or '(ni zadetkov)'}\n\n"
        f"JSON:"
    )
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        data = _http_json(f"{base}/chat/completions", payload, api_key=api_key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        # Starejši modeli brez response_format
        if exc.code in {400, 404} and "response_format" in detail.casefold():
            payload.pop("response_format", None)
            try:
                data = _http_json(f"{base}/chat/completions", payload, api_key=api_key)
            except Exception as exc2:
                return PartyWebResult(ok=False, message=f"AI API: {exc2}", used_ai=True)
        else:
            return PartyWebResult(ok=False, message=f"AI HTTP {exc.code}: {detail}", used_ai=True)
    except Exception as exc:
        return PartyWebResult(ok=False, message=f"AI API: {exc}", used_ai=True)

    content = ""
    try:
        content = str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return PartyWebResult(ok=False, message="AI ni vrnil vsebine.", used_ai=True)
    parsed = _parse_json_object(content)
    if not parsed:
        return PartyWebResult(ok=False, message="AI odgovor ni veljaven JSON.", used_ai=True, notes=content[:500])

    country_out = normalize_text(parsed.get("country") or country)[:2].upper()
    country_name = sanitize_display_text(parsed.get("country_name"))
    if not country_out and country_name:
        country_out = _country_code_from_name(country_name)
    reg = normalize_text(parsed.get("registration_no"))
    vat_digits = tax_digits(vat)
    if reg and vat_digits and tax_digits(reg) == vat_digits:
        reg = ""
    tax_file = normalize_text(parsed.get("tax_file") or parsed.get("withheld_tax_file"))
    hq = sanitize_display_text(parsed.get("headquarters"))
    address = sanitize_display_text(parsed.get("address"))
    postal = normalize_text(parsed.get("postal_code"))
    city = sanitize_display_text(parsed.get("city"))
    if hq and (not address or not city or not postal):
        split = _split_headquarters(hq)
        address = address or split.get("address") or ""
        postal = postal or split.get("postal_code") or ""
        city = city or split.get("city") or ""
        country_name = country_name or split.get("country_name") or ""
        if not country_out and split.get("country"):
            country_out = split["country"]
    extras_raw = parsed.get("extras")
    extras: dict[str, str] = {}
    if isinstance(extras_raw, dict):
        for k, v in extras_raw.items():
            text = sanitize_display_text(v)
            if text:
                extras[str(k)] = text
    # Preostali neznani ključi → extras
    known = {
        "name", "headquarters", "address", "postal_code", "city", "country", "country_name",
        "email", "phone", "registration_no", "tax_file", "withheld_tax_file", "website",
        "legal_form", "notes", "confidence", "extras",
    }
    for k, v in parsed.items():
        if k in known or isinstance(v, (dict, list)):
            continue
        text = sanitize_display_text(v)
        if text and str(k) not in extras:
            extras[str(k)] = text

    return PartyWebResult(
        ok=True,
        used_ai=True,
        name=sanitize_display_text(parsed.get("name") or name),
        headquarters=hq,
        address=address,
        postal_code=postal,
        city=city,
        country=country_out,
        country_name=country_name,
        email=normalize_text(parsed.get("email")),
        phone=normalize_text(parsed.get("phone")),
        registration_no=reg,
        tax_file=tax_file,
        vat_id=normalize_vat_id(vat),
        website=normalize_text(parsed.get("website")),
        legal_form=sanitize_display_text(parsed.get("legal_form")),
        notes=sanitize_display_text(parsed.get("notes")),
        extras=extras,
        sources=[s.get("url") or s.get("title") or "" for s in snippets if s.get("url") or s.get("title")],
        message="AI je predlagal podatke iz spleta — preveri pred shranjevanjem.",
    )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _heuristic_extract(
    name: str,
    vat: str,
    country: str,
    snippets: list[dict[str, str]],
) -> PartyWebResult:
    """Brez AI: poskusi izluščiti naslov iz zadetkov."""
    blob = " ".join(f"{s.get('title')} {s.get('snippet')}" for s in snippets)
    address = ""
    postal = ""
    city = ""
    # EU-ish: 4–6 digit postal + city
    m = re.search(
        r"\b(\d{4,6})\s+([A-ZÁÉÍÓÚÄÖÜŠČŽ][A-Za-zÁÉÍÓÚÄÖÜŠČŽáéíóúäöüščž\- ]{2,40})\b",
        blob,
    )
    if m:
        postal = m.group(1)
        city = m.group(2).strip(" ,.")
    # street-ish
    m2 = re.search(
        r"\b(\d{1,4}\s+[A-Za-z][A-Za-z0-9 .,'\-]{6,60}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ltd|Limited)?)",
        blob,
        re.I,
    )
    if m2:
        address = m2.group(1).strip(" ,.")
    email_m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob)
    ok = bool(address or postal or city or email_m)
    return PartyWebResult(
        ok=ok,
        used_ai=False,
        name=sanitize_display_text(name),
        address=sanitize_display_text(address),
        postal_code=postal,
        city=sanitize_display_text(city),
        country=normalize_text(country)[:2].upper(),
        vat_id=normalize_vat_id(vat),
        email=email_m.group(0) if email_m else "",
        sources=[s.get("url") or "" for s in snippets if s.get("url")],
        message=(
            "Najdeno brez AI (hevrístika) — preveri. Za boljše rezultate nastavi AI ključ."
            if ok
            else "Ni dovolj podatkov v zadetkih. Odpri iskanje v brskalniku ali nastavi AI."
        ),
    )


def lookup_party_on_web(
    *,
    name: str = "",
    vat_id: str = "",
    country: str = "",
    check_vies: bool = True,
) -> PartyWebResult:
    """
    1) opcijsko VIES (EU),
    2) spletno iskanje (DuckDuckGo),
    3) AI ekstrakcija (če je api_key),
    4) sicer hevrístika.
    """
    from trops_studio.vies_client import check_eu_vat, is_eu_vat_id

    ensure_ai_settings_template()
    name = sanitize_display_text(name)
    vat = normalize_vat_id(vat_id)
    country = normalize_text(country)[:2].upper()
    if not name and not vat:
        return PartyWebResult(ok=False, message="Vnesi vsaj naziv ali ID za DDV.")

    vies_status = ""
    vies_name = ""
    vies_address = ""
    if check_vies and vat and is_eu_vat_id(vat):
        vies = check_eu_vat(vat)
        if vies.ok and vies.valid:
            full = f"{vies.country}{vies.vat_number}"
            vies_status = f"JE V SISTEMU ({full})"
            vies_name = vies.name
            vies_address = vies.address
            vat = full  # kanonični ID (npr. CY…T)
        elif vies.ok and vies.valid is False:
            vies_status = (
                f"NI V SISTEMU ({vies.country}{vies.vat_number})"
            )
        else:
            vies_status = vies.message or "VIES preverjanje ni uspelo"
    elif vat and not is_eu_vat_id(vat):
        vies_status = "Ni EU ID za DDV — VIES ne velja"
    elif not vat:
        vies_status = "Ni ID za DDV — VIES ni preverjen"

    query = _build_search_query(name, vat, country)
    # Dodatni iskalni nizi za boljši sedež (npr. Izrael)
    snippets = duckduckgo_snippets(query)
    snippets.extend(duckduckgo_snippets(f"{name} registered office Israel OR Ireland company number"))
    if vat:
        snippets.extend(duckduckgo_snippets(f"{vat} company"))
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for s in snippets:
        key = (s.get("url") or s.get("title") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(s)

    def _attach_vies(result: PartyWebResult) -> PartyWebResult:
        result.vies_status = vies_status
        result.vies_name = vies_name
        result.vies_address = vies_address
        result.vat_id = result.vat_id or vat
        related = _known_related_entities(name, vat)
        if related:
            result.related_entities = _enrich_related_vies(related)
            # Če je primarni rezultat IL/Fiverr International, dopolni sedež iz znanega zapisa
            for ent in result.related_entities:
                if ent.get("country") == "IL" and "international" in str(ent.get("name") or "").casefold():
                    if not result.headquarters:
                        result.headquarters = ent.get("headquarters") or ""
                    if not result.registration_no:
                        result.registration_no = ent.get("registration_no") or ""
                    if not result.tax_file:
                        result.tax_file = ent.get("tax_file") or ""
                    if not result.country or result.country == "IE":
                        result.country = "IL"
                        result.country_name = "Izrael"
                    if not result.address:
                        result.address = ent.get("address") or ""
                    if not result.city:
                        result.city = ent.get("city") or ""
                    if not result.postal_code:
                        result.postal_code = ent.get("postal_code") or ""
                    if not result.name or "fiverr" in result.name.casefold():
                        result.name = ent.get("name") or result.name
        if vies_status and "neveljav" in vies_status.casefold():
            tip = ""
            for ent in result.related_entities:
                if normalize_vat_id(ent.get("vat_id")):
                    tip = f" EU subjekt: {ent.get('name')} · {ent.get('vat_id')}."
                    break
            result.message = (
                (result.message + " · " if result.message else "")
                + "VIES: ta EU DDV ni veljaven / subjekt ni EU."
                + tip
            )
        elif result.country == "IL" or (result.country_name or "").casefold() in {"izrael", "israel"}:
            result.vies_status = result.vies_status or "Ni v VIES — Izrael ni član EU"
            result.message = (
                (result.message + " · " if result.message else "")
                + "Izraelsko podjetje ni v VIES; glej povezane EU subjekte v ListView."
            )
        return result

    cfg = load_ai_settings()
    if cfg.get("enabled") and cfg.get("api_key"):
        ai = _ai_extract(name=name, vat=vat, country=country, snippets=unique, cfg=cfg)
        if ai.ok:
            if not ai.country and country:
                ai.country = country
            ai.sources = ai.sources or [s.get("url") or "" for s in unique if s.get("url")]
            return _attach_vies(ai)
        heur = _heuristic_extract(name, vat, country, unique)
        heur.message = f"{ai.message} | {heur.message}"
        heur.sources = [s.get("url") or "" for s in unique if s.get("url")]
        return _attach_vies(heur)

    heur = _heuristic_extract(name, vat, country, unique)
    heur.sources = [s.get("url") or "" for s in unique if s.get("url")]
    if not cfg.get("api_key"):
        heur.message += f" Nastavi ključ v {AI_SETTINGS_PATH.name} ali OPENAI_API_KEY."
    return _attach_vies(heur)


def google_search_url(name: str, vat: str, country: str) -> str:
    q = _build_search_query(name, vat, country)
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)


__all__ = [
    "AI_SETTINGS_PATH",
    "PartyWebResult",
    "ensure_ai_settings_template",
    "google_search_url",
    "load_ai_settings",
    "lookup_party_on_web",
]
