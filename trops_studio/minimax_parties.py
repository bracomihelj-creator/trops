"""Minimax API → SQLite parties (šifrant strank) + uvoz novih strank."""

from __future__ import annotations

import logging

import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from trops_studio.ajpes_client import lookup_si_company
from trops_studio.config import KONCNI_KUPCI_CODE, KONCNI_KUPCI_NAME
from trops_studio.db import Database
from trops_studio.money import (
    ensure_eu_vat_id,
    has_country_prefixed_vat_id,
    has_taxpayer_vat,
    infer_country_code,
    national_tax_id,
    normalize_text,
    normalize_vat_id,
    sanitize_display_text,
    si_tax8,
    tax_digits,
    vats_compatible,
)
from trops_studio.vies_client import EU_VAT_COUNTRIES, is_eu_vat_id
from trops_studio.parties_ensure import (
    ACTION_KONCNI,
    ACTION_TUJEC,
    _annotate_firm_item,
    classify_firm_action,
    collect_firms_needing_minimax,
    link_rows_to_parties,
    relink_journal_parties_by_vat,
    resolve_party_for_journal_row,
)


@dataclass
class SyncResult:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    message: str = ""


@dataclass
class CreateCustomerResult:
    ok: bool
    customer_id: str = ""
    code: str = ""
    message: str = ""
    already_existed: bool = False


@dataclass
class ImportResult:
    created: int = 0
    linked_existing: int = 0
    koncni: int = 0
    skipped_manual: int = 0
    failed: list[str] = field(default_factory=list)
    message: str = ""


def _record_text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is None or isinstance(value, Mapping):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _address_parts(record: Mapping[str, Any]) -> tuple[str, str, str]:
    address = _record_text(
        record,
        "Address",
        "StreetAddress",
        "Street",
        "Naslov",
    )
    postal = _record_text(record, "PostalCode", "PostCode", "Zip", "PostnaStevilka")
    city = _record_text(record, "City", "Town", "Place", "NazivPoste")
    nested = record.get("Address")
    if isinstance(nested, Mapping):
        address = address or _record_text(nested, "Street", "Address", "StreetAddress")
        postal = postal or _record_text(nested, "PostalCode", "PostCode", "Zip")
        city = city or _record_text(nested, "City", "Town", "Place")
    return address, postal, city


def customer_to_party(record: Mapping[str, Any]) -> dict[str, Any] | None:
    from trops_studio.money import national_tax_id, split_vat_and_mm_code

    code = _record_text(record, "Code", "CustomerCode", "Sifra")
    name = sanitize_display_text(_record_text(record, "Name", "CustomerName", "Naziv"))
    # ID za DDV samo iz VAT polja — ne inventiraj SI+davčna; loči zlepeljeno MM šifro
    raw_vat, mm_from_vat = split_vat_and_mm_code(
        _record_text(record, "VATIdentificationNumber", "VatNumber", "VATNumber")
    )
    vat = normalize_vat_id(raw_vat)
    if not code and mm_from_vat:
        code = mm_from_vat
    if vat and vat.isdigit() and len(vat) == 8:
        # SubjectToVAT=N: v polju je le davčna (FO / nezavezanec), ne ID za DDV
        if normalize_text(record.get("SubjectToVAT")).upper() == "N":
            vat = ""
        else:
            vat = f"SI{vat}"
    country = ""
    country_obj = record.get("Country")
    if isinstance(country_obj, Mapping):
        country = normalize_text(
            country_obj.get("Code")
            or country_obj.get("CountryCode")
            or country_obj.get("IsoCode")
            or ""
        )[:2].upper()
        if not (len(country) == 2 and country.isalpha()):
            name_cc = normalize_text(country_obj.get("Name") or "")[:2].upper()
            country = name_cc if len(name_cc) == 2 and name_cc.isalpha() else ""
    if not country:
        raw_cc = record.get("Country")
        if isinstance(raw_cc, str):
            country = normalize_text(raw_cc)[:2].upper()
        if not (len(country) == 2 and country.isalpha()):
            country = normalize_text(
                _record_text(record, "CountryCode", "KraticaDrzave") or ""
            )[:2].upper()
        if not (len(country) == 2 and country.isalpha()):
            country = ""
    if not country and vat and len(vat) >= 3 and vat[:2].isalpha():
        country = vat[:2]
    if not country:
        country = "SI" if (vat.startswith("SI") or not vat) else "XX"
    # IE/CY…: ohrani črke v davčni (6364992H), ne samo cifre
    tax_raw = _record_text(record, "TaxNumber", "RegistrationNumber", "DavcnaStevilka")
    if country and country != "SI":
        tax = national_tax_id(tax_raw or vat, country=country)
        # Napačen SI+DŠ na tujcu (npr. SI160072623 + BG) → sestavi pravi ID
        if vat.startswith("SI") and tax:
            vat = ""
        if not vat and tax:
            vat = ensure_eu_vat_id(tax, country=country) or f"{country}{tax}"
        elif vat and not vat[:2].isalpha() and tax:
            vat = ensure_eu_vat_id(vat, country=country) or f"{country}{tax}"
    else:
        tax = tax_digits(tax_raw or vat)
    if not name and not tax and not code:
        return None
    address, postal, city = _address_parts(record)
    is_foreign = 0 if country == "SI" else 1
    return {
        "vat_id": vat,
        "tax_number": tax,
        "country": country,
        "name": name or f"Stranka {code or tax}",
        "address": sanitize_display_text(address),
        "postal_code": postal,
        "city": sanitize_display_text(city),
        "is_foreign": is_foreign,
        "minimax_code": code,
        "registration_no": tax_digits(_record_text(record, "RegistrationNumber", "MaticnaStevilka")),
        "email": _record_text(record, "Email", "EMail"),
        "phone": _record_text(record, "Phone", "Telephone", "MobilePhone"),
        "notes": f"Minimax Code={code}" if code else "",
        "source": "minimax",
    }


def search_customers_by_name(
    client: Any,
    query: str,
    *,
    page_size: int = 40,
    max_pages: int = 2,
) -> list[dict[str, Any]]:
    """
    Išči stranke v Minimax API po delu naziva (SearchString).
    Poskusi cel niz, stisnjen niz in posamezne besede; razvrsti po ujemanju imena.
    """
    from minimax_api_client import _rows  # type: ignore

    raw = sanitize_display_text(query)
    if not raw or client.organisation_id is None:
        return []
    from trops_studio.party_aliases import alias_search_terms

    tokens = [t for t in re.split(r"\s+", raw) if len(t) >= 2]
    terms: list[str] = []
    for candidate in (*alias_search_terms(raw), raw, re.sub(r"\s+", "", raw), *tokens):
        c = sanitize_display_text(candidate)
        if c and c not in terms:
            terms.append(c)

    by_key: dict[str, dict[str, Any]] = {}
    for term in terms:
        for page in range(1, max_pages + 1):
            qs = urlencode({"SearchString": term, "CurrentPage": page, "PageSize": page_size})
            try:
                body = client.get(f"orgs/{client.organisation_id}/customers?{qs}")
            except Exception:
                break
            rows = list(_rows(body))
            if not rows:
                break
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                code = _customer_code(row)
                name = sanitize_display_text(row.get("Name") or "")
                if not code and not name:
                    continue
                cid = str(row.get("CustomerId") or row.get("ID") or code or name)
                key = code or cid
                if not key or key in by_key:
                    continue
                by_key[key] = dict(row)
            if len(rows) < page_size:
                break

    needle = raw.casefold()
    token_cf = [t.casefold() for t in tokens]
    significant = [t for t in token_cf if len(t) >= 3]

    def _token_hit(token: str, text: str) -> bool:
        if len(token) <= 2:
            return re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", text) is not None
        return token in text

    def _score(rec: Mapping[str, Any]) -> tuple[int, str]:
        name = sanitize_display_text(rec.get("Name") or "").casefold()
        code = _customer_code(rec).casefold()
        blob = f"{name} {code}"
        score = 0
        if needle and needle in name:
            score += 100
        compact_needle = needle.replace(" ", "")
        if compact_needle and compact_needle in name.replace(" ", ""):
            score += 80
        if token_cf and all(_token_hit(t, blob) for t in token_cf):
            score += 60
        if significant:
            score += 15 * sum(1 for t in significant if _token_hit(t, blob))
        elif token_cf:
            score += 10 * sum(1 for t in token_cf if _token_hit(t, blob))
        return (-score, name)

    ranked = sorted(by_key.values(), key=_score)
    # Filtriraj: vsaj ena »pomembna« beseda (≥3) mora zadeti, če obstaja
    if significant:
        filtered = [
            r
            for r in ranked
            if any(
                _token_hit(t, sanitize_display_text(r.get("Name") or "").casefold())
                or _token_hit(t, _customer_code(r).casefold())
                for t in significant
            )
        ]
        if filtered:
            ranked = filtered
    matched = [r for r in ranked if _score(r)[0] < 0]
    return matched or ranked


def import_minimax_customer_to_sql(
    db: Database,
    record: Mapping[str, Any],
    *,
    party_id: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Pretvori Minimax customer → SQL parties (upsert) in vrni (id, payload)."""
    from trops_studio.sync_state import SYNC_SYNCED

    payload = customer_to_party(record)
    if not payload:
        raise ValueError("Minimax zapis nima uporabnih podatkov (naziv/šifra).")
    payload["sync_status"] = SYNC_SYNCED
    code = normalize_text(payload.get("minimax_code"))
    target = party_id
    if target is None and code:
        existing = db.find_party_by_minimax_code(code)
        if existing:
            target = int(existing["id"])
    if target is None:
        existing = db.find_party_by_tax(payload.get("vat_id") or payload.get("tax_number") or "")
        if existing:
            target = int(existing["id"])
    new_id = db.upsert_party(payload, party_id=target)
    fresh = db.get_party(new_id) or payload
    return new_id, dict(fresh)


def open_minimax_client(org_id: str | int) -> Any:
    """Samostojen Minimax odjemalec (Projest vendor + nastavitve)."""
    org = str(org_id or "").strip()
    if not org or org == "0":
        raise ValueError("Izberi podjetje z veljavnim Org_ID.")
    from trops_studio.minimax_runtime import open_minimax_client as _open

    return _open(org)


def sync_customers_from_minimax(db: Database, org_id: str | int) -> SyncResult:
    """Napolni parties iz Minimax šifranta customers."""
    client = open_minimax_client(org_id)
    records = client._all("customers")
    result = SyncResult(fetched=len(records))
    errors = 0
    for record in records:
        if not isinstance(record, Mapping):
            result.skipped += 1
            continue
        payload = customer_to_party(record)
        if not payload:
            result.skipped += 1
            continue
        existing = None
        code = str(payload.get("minimax_code") or "")
        if code:
            existing = db.find_party_by_minimax_code(code)
        if existing is None:
            existing = db.find_party_by_tax(payload.get("vat_id") or payload.get("tax_number") or "")
        before_id = int(existing["id"]) if existing else None
        try:
            party_id = db.upsert_party(payload, party_id=before_id)
        except Exception:
            errors += 1
            result.skipped += 1
            continue
        if before_id:
            result.updated += 1
        else:
            result.inserted += 1
            _ = party_id
    result.message = (
        f"Minimax stranke: {result.fetched} prebranih, "
        f"{result.inserted} novih, {result.updated} posodobljenih"
        + (f", {errors} napak" if errors else "")
        + "."
    )
    return result


def _si_tax8(value: str, *, country: str = "") -> str:
    return si_tax8(value, country=country)


def _customer_vat_blob(record: Mapping[str, Any]) -> str:
    return normalize_vat_id(
        _record_text(
            record,
            "VATIdentificationNumber",
            "VatNumber",
            "VATNumber",
            "TaxNumber",
            "RegistrationNumber",
        )
    )


def _is_third_country(party: Mapping[str, Any]) -> bool:
    from trops_studio.pr_list_view import infer_party_kind

    return infer_party_kind(
        vat_id=party.get("vat_id"),
        tax_number=party.get("tax_number"),
        country=party.get("country"),
        is_foreign=bool(party.get("is_foreign")),
        name=party.get("name"),
    ) == "THIRD"


def _extract_customer_id(body: Any, location: str = "") -> str:
    if isinstance(body, Mapping):
        for key in ("CustomerId", "customerId", "ID", "Id", "id"):
            raw = body.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text.isdigit():
                return text
    if location:
        match = re.search(r"/customers/(\d+)", location, re.I)
        if match:
            return match.group(1)
    return ""


def _customer_code(record: Mapping[str, Any]) -> str:
    return _record_text(record, "Code", "CustomerCode", "Sifra")


def _lookup_fk_record(client: Any, resource: str, code: str) -> dict[str, Any]:
    """Vrni zapis iz Minimax FK šifranta (država/valuta) po Code."""
    from minimax_api_client import MinimaxApiError  # type: ignore

    org = client.organisation_id
    if not org:
        raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
    wanted = normalize_text(code)
    if not wanted:
        raise MinimaxApiError(f"Manjka šifra za {resource}.")
    try:
        body = client.get(f"orgs/{org}/{resource}/code({wanted})")
    except Exception:
        body = None
    if isinstance(body, Mapping):
        return dict(body)
    for record in client._all(resource):
        codes = [
            normalize_text(record.get(key))
            for key in ("Code", "CountryCode", "CurrencyCode", "Abbreviation", "Name")
        ]
        if wanted.upper() in {c.upper() for c in codes if c}:
            return dict(record)
    raise MinimaxApiError(f"V Minimax šifrantu '{resource}' ni šifre '{wanted}'.")


def _fk_id_from_record(record: Mapping[str, Any], *, prefer: Sequence[str] = ()) -> int:
    from minimax_api_client import _record_id  # type: ignore

    for key in (*prefer, "CountryId", "CurrencyId", "ID", "Id", "id"):
        raw = record.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    rid = _record_id(record)
    if rid:
        return int(rid)
    raise RuntimeError("Minimax FK zapis nima ID.")


def _lookup_fk_id(client: Any, resource: str, code: str) -> int:
    prefer = ("CountryId",) if resource == "countries" else (("CurrencyId",) if resource == "currencies" else ())
    return _fk_id_from_record(_lookup_fk_record(client, resource, code), prefer=prefer)


def _lookup_country(client: Any, code: str) -> tuple[int, str, str]:
    """(CountryId, Code, Name) — Name je obvezen za tuje stranke (CountryName)."""
    cc = (normalize_text(code)[:2] or "SI").upper()
    if cc == "GR":
        cc = "EL"
    record = _lookup_fk_record(client, "countries", cc)
    cid = _fk_id_from_record(record, prefer=("CountryId",))
    name = normalize_text(record.get("Name") or "")
    code_out = normalize_text(record.get("Code") or cc)[:2].upper() or cc
    return cid, code_out, name


def find_customer_by_tax(
    client: Any, tax_or_vat: str, *, country: str = ""
) -> dict[str, Any] | None:
    """Poišči stranko v Minimaxu po SI/DE/CH… ID — brez 'endswith' in brez DE→SI."""
    from minimax_api_client import _rows  # type: ignore

    vat = normalize_vat_id(tax_or_vat)
    tax8 = _si_tax8(vat, country=country)
    if (not vat and not tax8) or client.organisation_id is None:
        return None
    terms: list[str] = []
    if vat:
        terms.append(vat)
    if tax8:
        terms.append(tax8)
        terms.append(f"SI{tax8}")
    for term in dict.fromkeys(t for t in terms if t):
        query = urlencode({"SearchString": term, "CurrentPage": 1, "PageSize": 50})
        try:
            body = client.get(f"orgs/{client.organisation_id}/customers?{query}")
        except Exception:
            continue
        for row in _rows(body):
            if vats_compatible(vat or tax8, _customer_vat_blob(row), left_country=country):
                return dict(row)
    return None


def find_customer_by_exact_name(
    client: Any,
    name: str,
    *,
    country: str = "",
    allow_taxpayer: bool = False,
) -> dict[str, Any] | None:
    """Natanko isti naziv — za EU-nezavezanca / tretjo državo, ne za SI/DE zamenjavo."""
    from minimax_api_client import _rows  # type: ignore

    wanted = sanitize_display_text(name).casefold()
    if len(wanted) < 3 or client.organisation_id is None:
        return None
    query = urlencode({"SearchString": name[:40], "CurrentPage": 1, "PageSize": 20})
    try:
        body = client.get(f"orgs/{client.organisation_id}/customers?{query}")
    except Exception:
        return None
    cc = (normalize_text(country)[:2] or "").upper()
    for row in _rows(body):
        if sanitize_display_text(row.get("Name")).casefold() != wanted:
            continue
        remote = _customer_vat_blob(row)
        if has_country_prefixed_vat_id(remote) and not allow_taxpayer:
            continue
        row_cc = normalize_text(
            (row.get("Country") or {}).get("Code") if isinstance(row.get("Country"), Mapping) else ""
        )[:2].upper()
        if cc and row_cc and cc != row_cc:
            continue
        return dict(row)
    return None


def find_customer_by_name_or_alias(
    client: Any,
    name: str,
    *,
    country: str = "",
    allow_taxpayer: bool = False,
) -> dict[str, Any] | None:
    """Najprej natančen naziv, nato zapomnjeni vzorci (Open AI → OpenAI)."""
    from trops_studio.party_aliases import names_match_alias

    exact = find_customer_by_exact_name(
        client, name, country=country, allow_taxpayer=allow_taxpayer
    )
    if exact:
        return exact
    cc = (normalize_text(country)[:2] or "").upper()
    for row in search_customers_by_name(client, name):
        if not names_match_alias(name, str(row.get("Name") or "")):
            continue
        remote = _customer_vat_blob(row)
        if has_country_prefixed_vat_id(remote) and not allow_taxpayer:
            continue
        row_cc = normalize_text(
            (row.get("Country") or {}).get("Code") if isinstance(row.get("Country"), Mapping) else ""
        )[:2].upper()
        if cc and row_cc and cc != row_cc:
            continue
        return dict(row)
    return None


def find_customer_by_code(client: Any, code: str) -> dict[str, Any] | None:
    """Poišči stranko v Minimaxu po šifri (npr. 01345 Končni kupci)."""
    from minimax_api_client import _record_id  # type: ignore

    wanted = normalize_text(code)
    if not wanted or client.organisation_id is None:
        return None
    try:
        body = client.get(f"orgs/{client.organisation_id}/customers/code({wanted})")
        if isinstance(body, Mapping) and (_record_id(body) or _customer_code(body)):
            return dict(body)
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:567)", exc_info=True)
    for record in client._all("customers"):
        if _customer_code(record) == wanted:
            return dict(record)
    return None


def _customer_tax_digits(record: Mapping[str, Any]) -> str:
    return tax_digits(
        _record_text(
            record,
            "TaxNumber",
            "VatNumber",
            "VATIdentificationNumber",
            "RegistrationNumber",
            "VATNumber",
        )
    )


def customer_tax_digits(record: Mapping[str, Any]) -> str:
    """Javni alias — davčna številka iz Minimax customer zapisa."""
    return _customer_tax_digits(record)


def _party_tax_digits(party: Mapping[str, Any]) -> str:
    return tax_digits(party.get("tax_number") or party.get("vat_id")) or _si_tax8(
        str(party.get("vat_id") or party.get("tax_number") or "")
    )


def taxes_match_party_and_customer(party: Mapping[str, Any], customer: Mapping[str, Any]) -> bool:
    """Ali se davčna / ID za DDV ujema med SQL stranko in Minimax customerjem."""
    local = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
    remote = _customer_vat_blob(customer)
    if not local and not remote:
        return True
    if has_taxpayer_vat(local, country=str(party.get("country") or "")) or has_country_prefixed_vat_id(remote):
        if not local or not remote:
            return False
        return vats_compatible(local, remote, left_country=str(party.get("country") or ""))
    if local and remote:
        return vats_compatible(local, remote, left_country=str(party.get("country") or ""))
    return not local and not remote


def _fk_id_only(value: Any) -> dict[str, int] | Any:
    """Country/Currency za PUT: samo {ID}, brez ResourceUrl."""
    if isinstance(value, Mapping) and value.get("ID") is not None:
        try:
            return {"ID": int(value["ID"])}
        except (TypeError, ValueError):
            return {"ID": value["ID"]}
    return value


def _apply_consider_country(payload: dict[str, Any]) -> None:
    """
    Minimax:
    - tuji potrošnik (SubjectToVAT=N): ConsiderCountryForBookkeeping=D
    - tuje podjetje (D): ConsiderCountryForBookkeeping=N (obvezno pri PUT; D → 409)
    - SI / brez CountryName: polje odstrani
    """
    subject = normalize_text(payload.get("SubjectToVAT")).upper()
    foreign = bool(payload.get("CountryName"))
    if foreign and subject == "N":
        payload["ConsiderCountryForBookkeeping"] = "D"
    elif foreign and subject in {"D", "M"}:
        payload["ConsiderCountryForBookkeeping"] = "N"
    else:
        payload.pop("ConsiderCountryForBookkeeping", None)


def _customer_put_body(
    client: Any,
    party: Mapping[str, Any],
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    """
    PUT = GET telo + naši zapisljivi podatki.
    Čist POST-payload brez ConsiderCountry=N pri podjetju uničuje zapis (409).
    """
    fresh = _build_customer_payload(client, party)
    body = dict(existing)
    for key, value in fresh.items():
        body[key] = value
    # ohrani MM šifro / verzijo
    code = _customer_code(existing)
    if code:
        body["Code"] = code
    for key in ("CustomerId", "RowVersion"):
        if existing.get(key) is not None:
            body[key] = existing[key]
    for fk in ("Country", "Currency"):
        if fk in body:
            body[fk] = _fk_id_only(body[fk])
    _apply_consider_country(body)
    return body


def update_customer_in_minimax(
    client: Any,
    customer: Mapping[str, Any],
    party: Mapping[str, Any],
    *,
    overwrite: bool = True,
) -> CreateCustomerResult:
    """
    Posodobi obstoječo Minimax stranko s podatki iz SQL obrazca.
    Ne ustvari nove. overwrite=True: lokalni naziv/naslov prepiše MM.
    """
    from minimax_api_client import MinimaxApiError, _record_id  # type: ignore

    if client.organisation_id is None:
        return CreateCustomerResult(ok=False, message="Ni izbrane Minimax organizacije.")
    customer_id = _extract_customer_id(customer) or str(_record_id(customer) or "")
    code = _customer_code(customer)
    if not customer_id:
        return CreateCustomerResult(ok=False, code=code, message="Minimax stranka nima ID.")

    org = client.organisation_id
    try:
        detail = client.get(f"orgs/{org}/customers/{customer_id}")
    except MinimaxApiError as exc:
        return CreateCustomerResult(ok=False, code=code, customer_id=customer_id, message=str(exc))
    if not isinstance(detail, Mapping):
        return CreateCustomerResult(ok=False, code=code, customer_id=customer_id, message="API ni vrnil stranke.")

    if not overwrite:
        return CreateCustomerResult(
            ok=True,
            customer_id=customer_id,
            code=code or _customer_code(detail),
            message=f"Minimax šifra {code or '?'}: brez prepisovanja.",
            already_existed=True,
        )

    try:
        body = _customer_put_body(client, party, detail)
    except Exception as exc:
        return CreateCustomerResult(
            ok=False,
            customer_id=customer_id,
            code=code,
            message=f"Priprava podatkov ni uspela: {exc}",
        )

    try:
        client.put(f"orgs/{org}/customers/{customer_id}", body)
        detail = client.get(f"orgs/{org}/customers/{customer_id}")
        if isinstance(detail, Mapping):
            code = _customer_code(detail) or code
    except MinimaxApiError as exc:
        text = str(exc)
        low = text.casefold()
        if "potrošnik" in low or "potrosnik" in low or "considercountry" in low or "knjiženj" in low:
            text = (
                f"{text}\n\n"
                "Namig (tretja država / Podjetje Izven EU):\n"
                "• SubjectToVAT = D (pravna oseba), ne potrošnik\n"
                "• CountryName = naziv države (IZRAEL)\n"
                "• ConsiderCountryForBookkeeping = N pri podjetju (D samo za potrošnike)\n"
                "Ponovno »Poveži / posodobi Minimax«."
            )
        return CreateCustomerResult(
            ok=False,
            customer_id=customer_id,
            code=code,
            message=f"Posodobitev ni uspela: {text}",
        )

    try:
        client._references.pop("customers", None)
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:741)", exc_info=True)

    return CreateCustomerResult(
        ok=True,
        customer_id=customer_id,
        code=code,
        message=f"Minimax šifra {code or '?'}: podatki posodobljeni.",
        already_existed=True,
    )


def push_party_to_minimax(
    db: Database,
    org_id: str | int,
    party_id: int,
    *,
    update_if_exists: bool = True,
) -> CreateCustomerResult:
    """
    Ena stranka → Minimax:
    - SI+davčna: addbytaxnumber (Minimax iz javne baze, tudi TRR); brez Trops PUT;
    - tujec z MM šifro + davčna OK → opcijsko posodobi;
    - šifra + davčna ≠ → napaka;
    - EU/tretja po AI+SQL: ustvari novo (allow_create).
    """
    from trops_studio.minimax_runtime import open_minimax_client
    from trops_studio.sync_state import SYNC_SYNCED

    party = db.get_party(int(party_id))
    if not party:
        return CreateCustomerResult(ok=False, message=f"Stranka #{party_id} ne obstaja.")
    try:
        client = open_minimax_client(org_id)
    except Exception as exc:
        return CreateCustomerResult(ok=False, message=str(exc))

    item = dict(party)
    item["party_id"] = int(party_id)
    code = normalize_text(party.get("minimax_code"))

    if code:
        existing = find_customer_by_code(client, code)
        if existing:
            mm_tax = _customer_tax_digits(existing)
            local_tax = _party_tax_digits(party)
            if not taxes_match_party_and_customer(party, existing):
                return CreateCustomerResult(
                    ok=False,
                    code=code,
                    customer_id=_extract_customer_id(existing),
                    message=(
                        f"Šifra {code} obstaja v Minimaxu, a davčna se ne ujema "
                        f"(SQL: {local_tax or '—'} ≠ MM: {mm_tax or '—'}). "
                        "Ne dodajam nove stranke. Popravi davčno ali šifro."
                    ),
                    already_existed=True,
                )
            mm_party = customer_to_party(existing) or {}
            if not normalize_vat_id(item.get("vat_id")) and mm_party.get("vat_id"):
                item["vat_id"] = mm_party["vat_id"]
            if not tax_digits(item.get("tax_number")) and mm_party.get("tax_number"):
                item["tax_number"] = mm_party["tax_number"]
            if update_if_exists:
                tax8 = _si_tax8(str(item.get("tax_number") or item.get("vat_id") or ""))
                if tax8:
                    item["minimax_code"] = code
                    linked = CreateCustomerResult(
                        ok=True,
                        customer_id=_extract_customer_id(existing),
                        code=code,
                        already_existed=True,
                        message=(
                            f"Minimax šifra {code}: povezano. "
                            "Osvežitev iz javne baze (TRR, dejavnost…) naredi Minimax "
                            "z gumbom Posodobi podatke stranke."
                        ),
                    )
                    _upsert_imported_party(db, item, linked)
                    try:
                        db.set_party_sync(int(party_id), SYNC_SYNCED)
                    except Exception:
                        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:822)", exc_info=True)
                    return linked
                updated = update_customer_in_minimax(client, existing, item, overwrite=True)
                if not updated.ok:
                    return updated
                # Poveži v SQL (ohrani ročno šifro)
                item["minimax_code"] = updated.code or code
                _upsert_imported_party(db, item, updated)
                try:
                    db.set_party_sync(int(party_id), SYNC_SYNCED)
                except Exception:
                    logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:833)", exc_info=True)
                return updated
            return CreateCustomerResult(
                ok=True,
                code=code,
                customer_id=_extract_customer_id(existing),
                message=f"Šifra {code} obstaja, davčna OK — ni dodajanja.",
                already_existed=True,
            )
        # Ročna šifra, a je še ni v Minimaxu → nadaljuj z ustvarjanjem

    created = create_customer_in_minimax(client, item)
    if not created.ok:
        return created
    _upsert_imported_party(db, item, created)
    try:
        db.set_party_sync(int(party_id), SYNC_SYNCED)
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:851)", exc_info=True)
    fresh = db.get_party(int(party_id)) or {}
    out_code = normalize_text(fresh.get("minimax_code")) or created.code
    return CreateCustomerResult(
        ok=True,
        customer_id=created.customer_id,
        code=out_code,
        message=created.message or f"V Minimaxu: šifra {out_code or '?'}",
        already_existed=created.already_existed,
    )


def ensure_koncni_kupci_in_sqlite(db: Database, client: Any) -> dict[str, Any]:
    """Zagotoví SQLite zapis za Minimax šifro Končni kupci (01345)."""
    existing = db.find_party_by_minimax_code(KONCNI_KUPCI_CODE)
    mm = find_customer_by_code(client, KONCNI_KUPCI_CODE)
    if mm:
        payload = customer_to_party(mm) or {}
        payload["minimax_code"] = KONCNI_KUPCI_CODE
        payload["name"] = sanitize_display_text(payload.get("name")) or KONCNI_KUPCI_NAME
        payload["source"] = "minimax"
        party_id = db.upsert_party(
            payload,
            party_id=int(existing["id"]) if existing else None,
        )
        party = db.get_party(party_id)
        return party or payload
    if existing:
        return existing
    party_id = db.upsert_party(
        {
            "name": KONCNI_KUPCI_NAME,
            "minimax_code": KONCNI_KUPCI_CODE,
            "country": "SI",
            "is_foreign": 0,
            "source": "minimax",
            "notes": f"Skupna šifra {KONCNI_KUPCI_CODE}",
        }
    )
    return db.get_party(party_id) or {"id": party_id, "minimax_code": KONCNI_KUPCI_CODE}


def _link_rows_by_name(db: Database, party: Mapping[str, Any]) -> int:
    """Poveži IR/PR po nazivu, če manjka party_id (za Končne kupce)."""
    party_id = int(party["id"]) if party.get("id") else 0
    name = sanitize_display_text(party.get("name")).casefold()
    if not party_id or not name:
        return 0
    linked = 0
    for row in db.list_ir():
        if row.get("party_id"):
            continue
        if sanitize_display_text(row.get("party_name")).casefold() != name:
            continue
        payload = dict(row)
        payload["party_id"] = party_id
        db.upsert_ir(payload, row_id=int(row["id"]))
        linked += 1
    for row in db.list_pr():
        if row.get("party_id"):
            continue
        if sanitize_display_text(row.get("supplier_name")).casefold() != name:
            continue
        payload = dict(row)
        payload["party_id"] = party_id
        db.upsert_pr(payload, row_id=int(row["id"]))
        linked += 1
    return linked


def _upsert_imported_party(db: Database, item: Mapping[str, Any], created: CreateCustomerResult) -> int:
    party_payload = {
        # Ne inventiraj SI+davčna kot ID za DDV — samo eksplicitni vat_id
        "vat_id": normalize_vat_id(item.get("vat_id")),
        "tax_number": tax_digits(item.get("tax_number") or item.get("vat_id")),
        "country": normalize_text(item.get("country") or "SI")[:2].upper() or "SI",
        "name": sanitize_display_text(item.get("name")) or f"Stranka {created.code}",
        "address": sanitize_display_text(item.get("address")),
        "postal_code": normalize_text(item.get("postal_code")),
        "city": sanitize_display_text(item.get("city")),
        "is_foreign": 1 if item.get("is_foreign") else 0,
        "ajpes_code": normalize_text(item.get("ajpes_code")),
        "minimax_code": created.code
        or normalize_text(item.get("minimax_code"))
        or created.customer_id,
        "registration_no": normalize_text(item.get("registration_no")),
        "email": normalize_text(item.get("email")),
        "phone": normalize_text(item.get("phone")),
        "iban": re.sub(r"\s+", "", normalize_text(item.get("iban"))).upper(),
        "notes": created.message,
        "source": "minimax" if created.code else "ajpes",
    }
    party_id = item.get("party_id")
    if party_id:
        return db.upsert_party(party_payload, party_id=int(party_id))
    existing = None
    if party_payload["minimax_code"]:
        existing = db.find_party_by_minimax_code(party_payload["minimax_code"])
    if existing is None:
        existing = db.find_party_by_tax(party_payload["vat_id"] or party_payload["tax_number"])
    return db.upsert_party(party_payload, party_id=int(existing["id"]) if existing else None)


# ISO država → privzeta valuta (Minimax Currency.Code), sicer EUR
_COUNTRY_CURRENCY: dict[str, str] = {
    "IL": "ILS",
    "US": "USD",
    "GB": "GBP",
    "CH": "CHF",
    "NO": "NOK",
    "MK": "MKD",
    "RS": "RSD",
    "BA": "BAM",
    "CN": "CNY",
    "JP": "JPY",
    "AU": "AUD",
    "CA": "CAD",
}


def _lookup_currency_id(client: Any, country_code: str) -> int:
    """Valuta po državi (npr. IL→ILS), sicer EUR."""
    wanted = _COUNTRY_CURRENCY.get(country_code.upper(), "EUR")
    try:
        return _lookup_fk_id(client, "currencies", wanted)
    except Exception:
        return _lookup_fk_id(client, "currencies", "EUR")


def _build_customer_payload(client: Any, party: Mapping[str, Any]) -> dict[str, Any]:
    """
    Minimax Customer (POST /customers) — usklajeno s shemo:

    Outside EU:
      SubjectToVAT D = Podjetje (Izven EU), N = potrošnik
      CountryName obvezen
      ConsiderCountryForBookkeeping samo za potrošnike (N) — sicer HTTP 409
      Identifikacija (IL001) → VATIdentificationNumber; TaxNumber prazna
    """
    name = sanitize_display_text(party.get("name")) or "Nova stranka"
    address = sanitize_display_text(party.get("address"))
    postal = normalize_text(party.get("postal_code"))
    city = sanitize_display_text(party.get("city"))
    from trops_studio.pr_list_view import country_from_supplier_name, infer_party_kind

    country = (normalize_text(party.get("country") or "")[:2] or "").upper()
    if country == "GR":
        country = "EL"
    kind = infer_party_kind(
        vat_id=party.get("vat_id"),
        tax_number=party.get("tax_number"),
        country=country or party.get("country"),
        is_foreign=bool(party.get("is_foreign")),
        name=name,
    )
    if not country or country == "SI":
        hint = country_from_supplier_name(name)
        if kind == "THIRD" and hint:
            country = hint
        elif not country:
            country = "SI"
    tax8 = _si_tax8(str(party.get("tax_number") or party.get("vat_id") or ""), country=country)
    vat = normalize_vat_id(party.get("vat_id"))
    reg = tax_digits(party.get("registration_no"))
    code = tax8 or reg or secrets.token_hex(4)
    country_id, country_code, country_name = _lookup_country(
        client, country if len(country) == 2 else "SI"
    )
    currency_id = _lookup_currency_id(client, country_code)

    # EU VIES ID vs. tretja država — odločitev po kodi države, ne po formatu IL001
    eu_vat = vat if (vat and is_eu_vat_id(vat) and vat[:2] in EU_VAT_COUNTRIES) else ""
    third_country = country_code not in {"", "SI"} and country_code not in EU_VAT_COUNTRIES
    eu_foreign = country_code not in {"", "SI"} and country_code in EU_VAT_COUNTRIES
    third_vat = vat if (vat and third_country) else ""  # npr. IL001 — Identifikacijska št.

    prefixed = has_country_prefixed_vat_id(vat)
    if country_code == "SI":
        if prefixed and vat.startswith("SI"):
            subject = "D"
        else:
            subject = "M"  # podjetje, ni zavezanec za DDV
    elif third_country or kind == "THIRD":
        notes = normalize_text(party.get("notes")).casefold()
        subject = "N" if "potrošnik" in notes else "D"
    else:
        subject = "D" if prefixed else "N"

    payload: dict[str, Any] = {
        "Name": name,
        "Address": address or ".",
        "PostalCode": postal,
        "City": city,
        "Code": code[:32],
        "Country": {"ID": country_id},
        "SubjectToVAT": subject,
        "Currency": {"ID": currency_id},
        "EInvoiceIssuing": "SeNePripravlja",
    }
    # Minimax: CountryName obvezen za nedomače (Naziv države = IZRAEL)
    if country_code != "SI":
        if not country_name:
            raise RuntimeError(
                f"Minimax nima naziva države za kodo {country_code}. "
                "Preveri šifrant držav (IL → IZRAEL) ali vpiši drugo državo."
            )
        payload["CountryName"] = country_name
        _apply_consider_country(payload)

    if tax8 and country_code == "SI":
        payload["TaxNumber"] = tax8
    elif eu_foreign:
        # EU: davčna lokalno opcijsko; ID za DDV gre spodaj
        local_tax = national_tax_id(party.get("tax_number"), country=country_code)
        if local_tax:
            payload["TaxNumber"] = local_tax[:32]
    # tretja država: TaxNumber prazna (kot v Minimaxu pri Fiverr); IL001 → VATIdentificationNumber

    if eu_vat:
        payload["VATIdentificationNumber"] = eu_vat
    elif third_vat:
        payload["VATIdentificationNumber"] = third_vat
    if reg:
        payload["RegistrationNumber"] = reg[:32]
    return payload


def create_customer_in_minimax(
    client: Any,
    party: Mapping[str, Any],
    *,
    allow_create: bool = True,
) -> CreateCustomerResult:
    """
    Poveži ali ustvari stranko v Minimaxu:
    1) če že obstaja po davčni / nazivu / vzorcu → vrni obstoječo,
    2) SI+davčna: addbytaxnumber (Minimax iz javne baze, tudi TRR; brez Trops PUT),
    3) EU/tretja: POST samo če je allow_create (po AI + SQL).
    """
    from minimax_api_client import MinimaxApiError  # type: ignore

    if client.organisation_id is None:
        return CreateCustomerResult(ok=False, message="Ni izbrane Minimax organizacije.")
    name = sanitize_display_text(party.get("name"))
    if len(name) < 2:
        return CreateCustomerResult(ok=False, message="Ime stranke je prazno.")

    country = infer_country_code(
        country=party.get("country"),
        vat_id=party.get("vat_id") or party.get("tax_number"),
        postal_code=party.get("postal_code"),
        address=party.get("address"),
        city=party.get("city"),
    )
    vat = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
    tax8 = _si_tax8(vat, country=country)
    third = _is_third_country(party)
    existing = None
    if has_taxpayer_vat(vat, country=country) or tax8:
        existing = find_customer_by_tax(client, vat or tax8, country=country)
        if existing and not taxes_match_party_and_customer(party, existing):
            existing = None
    if existing is None:
        existing = find_customer_by_name_or_alias(
            client,
            name,
            country=country,
            allow_taxpayer=third or bool(country and country != "SI"),
        )
        if existing and has_country_prefixed_vat_id(_customer_vat_blob(existing)) and not third:
            existing = None
    if existing:
        cid = _extract_customer_id(existing)
        code = _customer_code(existing)
        _remember_foreign_alias(party, code)
        return CreateCustomerResult(
            ok=True,
            customer_id=cid,
            code=code,
            message=f"Že v Minimaxu (Code={code or '?'}, ID={cid or '?'})",
            already_existed=True,
        )

    org = client.organisation_id
    customer_id = ""
    msg = ""

    if tax8:
        try:
            response = client.post(f"orgs/{org}/customers/addbytaxnumber({tax8})", {})
            customer_id = _extract_customer_id(response.body, response.location)
            msg = f"Ustvarjena iz javne baze (ID {customer_id or '?'})"
        except MinimaxApiError as exc:
            text = str(exc)
            if "409" in text or "že obstaja" in text.casefold():
                found = find_customer_by_tax(client, tax8)
                if found:
                    return CreateCustomerResult(
                        ok=True,
                        customer_id=_extract_customer_id(found),
                        code=_customer_code(found),
                        message="Že v Minimaxu (409)",
                        already_existed=True,
                    )
            # drugih napak addbytaxnumber ne prekinemo — poskusimo POST
            msg = text
    elif not allow_create:
        return CreateCustomerResult(
            ok=False,
            message="Ni v Minimaxu — preveri z AI, shrani v SQL, nato Prenesi v Minimax API.",
        )

    if not customer_id:
        try:
            payload = _build_customer_payload(client, party)
            response = client.post(f"orgs/{org}/customers", payload)
            customer_id = _extract_customer_id(response.body, response.location)
            if not msg or "HTTP" in msg:
                msg = f"Ustvarjena (ID {customer_id or '?'})"
        except MinimaxApiError as exc:
            text = str(exc)
            if tax8 and ("409" in text) and "držav" not in text.casefold():
                found = find_customer_by_tax(client, tax8)
                if found:
                    return CreateCustomerResult(
                        ok=True,
                        customer_id=_extract_customer_id(found),
                        code=_customer_code(found),
                        message="Že v Minimaxu (409)",
                        already_existed=True,
                    )
            low = text.casefold()
            # »Državo se pri knjiženju… potrošnik« = ConsiderCountry, ne manjkajoč CountryName
            if "potrošnik" in low or "potrosnik" in low or "considercountry" in low or "knjiženj" in low:
                text = (
                    f"{text}\n\n"
                    "Namig (tretja država / Podjetje Izven EU):\n"
                    "• SubjectToVAT = D (pravna oseba), ne potrošnik\n"
                    "• CountryName = naziv države (IZRAEL), Država = IL\n"
                    "• ConsiderCountryForBookkeeping samo za potrošnike — pri podjetju ne\n"
                    "• IL001 → Identifikacijska št. (VATIdentificationNumber), davčna prazna\n"
                    "Ponovno »Poveži / posodobi Minimax« (po restartu Studia)."
                )
            elif "držav" in low or "countryname" in low:
                text = (
                    f"{text}\n\n"
                    "Namig: za tujo stranko Minimax zahteva CountryName (npr. IZRAEL). "
                    "Preveri polje Država (IL) in ponovno »Poveži / posodobi Minimax«."
                )
            return CreateCustomerResult(ok=False, message=text)

    if not customer_id and tax8:
        found = find_customer_by_tax(client, tax8)
        if found:
            return CreateCustomerResult(
                ok=True,
                customer_id=_extract_customer_id(found),
                code=_customer_code(found),
                message=msg or "Najdena po ustvarjanju",
                already_existed=True,
            )

    if not customer_id:
        return CreateCustomerResult(ok=False, message=msg or "Stranka ni bila ustvarjena.")

    code = ""
    try:
        detail = client.get(f"orgs/{org}/customers/{customer_id}")
        if isinstance(detail, Mapping):
            code = _customer_code(detail)
            if not code:
                customer_id = _extract_customer_id(detail) or customer_id
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:1224)", exc_info=True)

    # Tujec / ročni POST: dopolni prazna polja s PUT.
    if code or customer_id:
        try:
            detail = client.get(f"orgs/{org}/customers/{customer_id}")
            if isinstance(detail, Mapping):
                code = code or _customer_code(detail)
                if not tax8:
                    needs = False
                    if name and sanitize_display_text(detail.get("Name")) != name:
                        needs = True
                    addr = sanitize_display_text(party.get("address"))
                    if addr and not sanitize_display_text(detail.get("Address")):
                        needs = True
                    postal = normalize_text(party.get("postal_code"))
                    if postal and not normalize_text(detail.get("PostalCode")):
                        needs = True
                    city = sanitize_display_text(party.get("city"))
                    if city and not sanitize_display_text(detail.get("City")):
                        needs = True
                    if needs:
                        body = _customer_put_body(client, party, detail)
                        client.put(f"orgs/{org}/customers/{customer_id}", body)
                        detail = client.get(f"orgs/{org}/customers/{customer_id}")
                        if isinstance(detail, Mapping):
                            code = _customer_code(detail) or code
        except Exception:
            logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:1252)", exc_info=True)

    # Osveži lokalni cache šifranta
    try:
        client._references.pop("customers", None)
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:1258)", exc_info=True)

    _remember_foreign_alias(party, code)
    return CreateCustomerResult(
        ok=True,
        customer_id=customer_id,
        code=code or tax8,
        message=msg or f"Ustvarjena (Code={code or tax8})",
    )


def _remember_foreign_alias(party: Mapping[str, Any], minimax_code: str = "") -> None:
    if not _is_third_country(party) and infer_country_code(
        country=party.get("country"),
        vat_id=party.get("vat_id") or party.get("tax_number"),
    ) == "SI":
        return
    try:
        from trops_studio.party_aliases import remember_party_alias

        remember_party_alias(
            str(party.get("name") or ""),
            canonical=str(party.get("name") or ""),
            minimax_code=minimax_code,
        )
    except Exception:
        logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_parties.py:1284)", exc_info=True)


def _enrich_party_from_ajpes(item: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Za SI z davčno dopolni iz AJPES pred uvozom v Minimax."""
    payload = dict(item)
    country = (normalize_text(payload.get("country") or "SI")[:2] or "SI").upper()
    tax = _si_tax8(str(payload.get("tax_number") or payload.get("vat_id") or ""), country=country)
    if country != "SI" or not tax or payload.get("is_foreign"):
        return payload
    needs = (
        force
        or not sanitize_display_text(payload.get("address"))
        or not sanitize_display_text(payload.get("city"))
        or not sanitize_display_text(payload.get("name"))
    )
    if not needs:
        return payload
    lookup = lookup_si_company(tax, str(payload.get("name") or ""), entity_id=str(payload.get("ajpes_code") or ""))
    if not lookup.ok:
        payload["_ajpes_error"] = lookup.message or "AJPES ni vrnil podatkov"
        if lookup.needs_login:
            payload["_ajpes_login"] = True
        return payload
    payload["name"] = lookup.name or payload.get("name")
    # Ne inventiraj SI+DŠ kot ID za DDV — ohrani eksplicitni vat_id ali pusti prazno
    payload["vat_id"] = normalize_vat_id(payload.get("vat_id")) or ""
    payload["tax_number"] = lookup.tax_number or tax
    payload["address"] = lookup.address or payload.get("address")
    payload["postal_code"] = lookup.postal_code or payload.get("postal_code")
    payload["city"] = lookup.city or payload.get("city")
    payload["registration_no"] = lookup.registration_no or payload.get("registration_no")
    payload["ajpes_code"] = lookup.ajpes_code or payload.get("ajpes_code")
    payload["email"] = lookup.email or payload.get("email")
    payload["phone"] = lookup.phone or payload.get("phone")
    payload["iban"] = lookup.iban or payload.get("iban")
    if lookup.ibans:
        payload["_ibans"] = list(lookup.ibans)
    payload["country"] = "SI"
    payload["is_foreign"] = 0
    return payload


def import_parties_to_minimax(
    db: Database,
    org_id: str | int,
    items: Sequence[Mapping[str, Any]] | None = None,
    *,
    use_ajpes: bool = False,
    allow_create: bool = False,
) -> ImportResult:
    """
    Uvoz novih firm:
    - SI z davčno: poveži, če obstaja, sicer addbytaxnumber (Minimax javna baza),
    - EU/tretja: poveži po davčni/nazivu/vzorcu; POST samo če allow_create (po AI+SQL),
    - brez davčne: šifra Končni kupci 01345.
    """
    client = open_minimax_client(org_id)
    rows = list(items) if items is not None else collect_firms_needing_minimax(db)
    result = ImportResult()
    koncni_master: dict[str, Any] | None = None

    for raw in rows:
        item = dict(raw)
        label = sanitize_display_text(item.get("name")) or item.get("tax_number") or "?"
        action = str(item.get("action") or classify_firm_action(item))
        try:
            if action == ACTION_TUJEC:
                created = create_customer_in_minimax(client, item, allow_create=allow_create)
                if not created.ok:
                    result.failed.append(f"{label}: {created.message}")
                    continue
                _upsert_imported_party(db, item, created)
                if created.already_existed:
                    result.linked_existing += 1
                else:
                    result.created += 1
                continue

            if action == ACTION_KONCNI:
                if koncni_master is None:
                    koncni_master = ensure_koncni_kupci_in_sqlite(db, client)
                mm_code = normalize_text(koncni_master.get("minimax_code")) or KONCNI_KUPCI_CODE
                party_payload = {
                    "vat_id": "",
                    "tax_number": "",
                    "country": "SI",
                    "name": sanitize_display_text(item.get("name")) or KONCNI_KUPCI_NAME,
                    "address": sanitize_display_text(item.get("address")),
                    "postal_code": normalize_text(item.get("postal_code")),
                    "city": sanitize_display_text(item.get("city")),
                    "is_foreign": 0,
                    "minimax_code": mm_code,
                    "notes": f"Končni kupec → MM {mm_code}",
                    "source": "koncni_kupci",
                }
                party_id = item.get("party_id")
                if party_id:
                    db.upsert_party(party_payload, party_id=int(party_id))
                    saved = db.get_party(int(party_id)) or party_payload
                else:
                    # Nova vrstica: poveži na skupni zapis Končni kupci (ne množi šifranta).
                    master_id = int(koncni_master["id"]) if koncni_master.get("id") else None
                    if master_id:
                        db.upsert_party(
                            {
                                **dict(koncni_master),
                                "minimax_code": mm_code,
                                "name": sanitize_display_text(koncni_master.get("name")) or KONCNI_KUPCI_NAME,
                                "source": "minimax",
                            },
                            party_id=master_id,
                        )
                        saved = db.get_party(master_id) or koncni_master
                    else:
                        new_id = db.upsert_party(party_payload)
                        saved = db.get_party(new_id) or party_payload
                    # Ohrani izvirni naziv za povezavo IR/PR po imenu.
                    _link_rows_by_name(db, {"id": saved.get("id"), "name": item.get("name")})
                if party_id and saved:
                    _link_rows_by_name(db, {"id": party_id, "name": item.get("name")})
                result.koncni += 1
                continue

            # SI z davčno: poveži obstoječo MM stranko, sicer addbytaxnumber
            if use_ajpes:
                item = _enrich_party_from_ajpes(item, force=True)
            tax_key = item.get("vat_id") or item.get("tax_number") or ""
            existing_sql = db.find_party_by_tax(tax_key) if tax_key else None
            if existing_sql and normalize_text(existing_sql.get("minimax_code")):
                result.linked_existing += 1
                if item.get("party_id") and int(item["party_id"]) != int(existing_sql["id"]):
                    pass
                continue

            created = create_customer_in_minimax(client, item, allow_create=False)
            if not created.ok:
                result.failed.append(f"{label}: {created.message}")
                continue
            _upsert_imported_party(db, item, created)
            if created.already_existed:
                result.linked_existing += 1
            else:
                result.created += 1
        except Exception as exc:
            result.failed.append(f"{label}: {exc}")

    linked = link_rows_to_parties(db)
    result.message = (
        f"Minimax: {result.created} novih, {result.linked_existing} že v MM/SQL, "
        f"Končni kupci ({KONCNI_KUPCI_CODE}): {result.koncni}, "
        f"ročno tujci: {result.skipped_manual}"
        + (f", napak: {len(result.failed)}" if result.failed else "")
        + f", povezanih IR/PR: {linked}."
    )
    return result


def _party_item_from_row(
    db: Database,
    *,
    party_id: Any,
    name: str,
    vat_id: str,
    tax_number: str = "",
    book: str = "",
) -> dict[str, Any] | None:
    """Ena stranka za uvoz (če še nima MM šifre). Zavezanec samo s predpono."""
    party = resolve_party_for_journal_row(
        db,
        party_id=party_id,
        vat_id=vat_id,
        tax_number=tax_number,
        name=name,
    )
    from trops_studio.pr_list_view import country_from_supplier_name, infer_party_kind

    vat = normalize_vat_id((party or {}).get("vat_id") or vat_id)
    country = infer_country_code(
        country=(party or {}).get("country"),
        vat_id=vat or tax_number,
        postal_code=(party or {}).get("postal_code"),
        address=(party or {}).get("address"),
        city=(party or {}).get("city"),
    ) or ""
    if country == "GR":
        country = "EL"
    label = sanitize_display_text((party or {}).get("name") or name)
    kind = infer_party_kind(
        vat_id=vat,
        tax_number=tax_number or (party or {}).get("tax_number"),
        country=country,
        is_foreign=bool((party or {}).get("is_foreign")),
        name=label,
        book=book,
    )
    if kind == "THIRD":
        country = country_from_supplier_name(label) or country or "US"
    if party and normalize_text(party.get("minimax_code")):
        return None  # že v MM
    if party:
        return _annotate_firm_item(
            {
                "party_id": int(party["id"]),
                "name": sanitize_display_text(party.get("name")) or name,
                "vat_id": vat,
                "tax_number": tax_digits(party.get("tax_number") or party.get("vat_id") or tax_number or vat_id),
                "country": country,
                "address": sanitize_display_text(party.get("address")),
                "postal_code": normalize_text(party.get("postal_code")),
                "city": sanitize_display_text(party.get("city")),
                "is_foreign": 0 if country == "SI" else 1,
                "in_sqlite": True,
            },
            book=book,
        )
    if not (name or vat_id or tax_number):
        return None
    if not country:
        country = country_from_supplier_name(name) or "SI"
    return _annotate_firm_item(
        {
            "name": name or "Neznana stranka",
            "vat_id": normalize_vat_id(vat_id),
            "tax_number": tax_digits(tax_number or vat_id),
            "country": country,
            "is_foreign": 0 if country == "SI" else 1,
            "in_sqlite": False,
        },
        book=book,
    )


def ensure_parties_for_journals(
    db: Database,
    org_id: str | int,
    *,
    ir_rows: Sequence[Mapping[str, Any]] | None = None,
    pr_rows: Sequence[Mapping[str, Any]] | None = None,
    use_ajpes: bool = False,
    allow_create: bool = False,
) -> ImportResult:
    """
    Pred oddajo temeljnic:
    - IR: predpona SI/DE/CH/US… → nujno preveri; brez predpone → Končni 01345
    - PR: predpona SI/DE/US… → zavezanec; brez predpone → podjetje, ni zavezanec DDV
    - SI: poveži iz Minimaxa, sicer addbytaxnumber; EU/tretja: poveži, ne ustvarjaj (AI→SQL→API)
    """
    from trops_studio.money import has_country_prefixed_vat_id

    result = ImportResult()
    client = open_minimax_client(org_id)
    ensure_koncni_kupci_in_sqlite(db, client)
    relink_journal_parties_by_vat(db)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    koncni_used = False

    def _add_item(item: dict[str, Any] | None) -> None:
        if not item or item.get("action") == ACTION_KONCNI:
            return
        key = (
            str(item.get("party_id") or "")
            or normalize_vat_id(item.get("vat_id") or item.get("tax_number"))
            or sanitize_display_text(item.get("name")).casefold()
        )
        if not key or key in seen:
            return
        seen.add(key)
        items.append(item)

    for row in ir_rows or ():
        vat = str(row.get("vat_id") or "")
        if not has_country_prefixed_vat_id(vat):
            koncni_used = True
            continue
        item = _party_item_from_row(
            db,
            party_id=row.get("party_id"),
            name=sanitize_display_text(row.get("party_name")),
            vat_id=vat,
            book="IR",
        )
        if item and item.get("action") == ACTION_KONCNI:
            koncni_used = True
        else:
            _add_item(item)

    for row in pr_rows or ():
        item = _party_item_from_row(
            db,
            party_id=row.get("party_id"),
            name=sanitize_display_text(row.get("supplier_name")),
            vat_id=str(row.get("vat_id") or ""),
            tax_number=str(row.get("tax_number") or ""),
            book="PR",
        )
        _add_item(item)

    if koncni_used:
        result.koncni += 1

    if items:
        imported = import_parties_to_minimax(
            db, org_id, items, use_ajpes=False, allow_create=allow_create
        )
        result.created += imported.created
        result.linked_existing += imported.linked_existing
        result.koncni += imported.koncni
        result.failed.extend(imported.failed)
        # SI uvoz, ki pade → ne forsiraj Končnih pri PR; pri IR pa Končni
        failed_names = {f.split(":", 1)[0].strip().casefold() for f in imported.failed}
        retry_koncni: list[dict[str, Any]] = []
        for item in items:
            # samo če gre za IR kontekst (ni v PR rows) — poenostavi: retry koncni samo za IR imena
            label = sanitize_display_text(item.get("name")).casefold()
            if label not in failed_names:
                continue
            # če je ime iz IR vrstic brez firmnega uspeha → Končni
            ir_names = {
                sanitize_display_text(r.get("party_name")).casefold() for r in (ir_rows or ())
            }
            if label in ir_names:
                retry = dict(item)
                retry["action"] = ACTION_KONCNI
                retry["vat_id"] = ""
                retry["tax_number"] = ""
                retry_koncni.append(retry)
        if retry_koncni:
            extra = import_parties_to_minimax(db, org_id, retry_koncni, use_ajpes=False)
            result.koncni += extra.koncni
            still = []
            for msg in result.failed:
                name = msg.split(":", 1)[0].strip().casefold()
                if any(sanitize_display_text(i.get("name")).casefold() == name for i in retry_koncni):
                    continue
                still.append(msg)
            result.failed = still + list(extra.failed)

    result.message = (
        f"Stranke za temeljnice: +{result.created} novih, "
        f"+{result.linked_existing} že v MM, Končni {result.koncni}"
        + (f", napak: {len(result.failed)}" if result.failed else "")
        + "."
    )
    return result
