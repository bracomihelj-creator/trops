"""Majhen Minimax OAuth/API odjemalec za neposredno oddajo KIR/KPR temeljnic.

Gesla se ne shranjujejo v konfiguracijo pretvornika. Privzeto se preberejo iz
obstoječe datoteke ``DavčnaBlagajna/blagajna_minimax_settings.json``.
"""

from __future__ import annotations

import copy
import base64
import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from lxml import etree

import convert_ddv_json_to_minimax as minimax_xml
import kirkpr_minimax_core as core


DEFAULT_API_BASE = "https://moj.minimax.si/SI/API"
DEFAULT_AUTH_URL = "https://moj.minimax.si/SI/AUT/OAuth20/Token"
DEFAULT_SCOPE = "minimax.si"
PAGE_SIZE = 200
RATE_PERCENTAGES = {"S": 22.0, "Z": 9.5, "0": 5.0, "O": 0.0, "N": 0.0}
VAT_ROW_FIELDS = {
    "Osnova": "VatBase",
    "DDV": "Vat",
    "NeodbitiDDVOsnova": "NonDeductibleVatBase",
    "NeodbitiDDV": "NonDeductibleVat",
    "StoritevOsnova": "ServicesVatBase",
    "StoritevDDV": "ServicesVat",
    "StoritevNeodbitiDDVOsnova": "ServicesNonDeductibleVatBase",
    "StoritevNeodbitiDDV": "ServicesNonDeductibleVat",
}
# DDV glava: Osnovno sredstvo / Nepremičnina (XML = WebUI polji na temeljnici).
VAT_HEADER_AMOUNTS = {
    "OsnovnoSredstvo": "OsnovnoSredstvo",
    "Nepremicnina": "Nepremicnina",
}


class MinimaxApiError(RuntimeError):
    """Napaka Minimax API, primerna za prikaz uporabniku."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ApiSettings:
    api_base: str
    auth_url: str
    scope: str
    client_id: str
    client_secret: str
    username: str
    password: str
    organisation_id: str
    source_path: Path

    @classmethod
    def from_file(cls, path: Path | str) -> ApiSettings:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise MinimaxApiError(f"Datoteka z Minimax API nastavitvami ne obstaja: {source}")
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MinimaxApiError(f"Nastavitev ni mogoče prebrati: {exc}") from exc
        if not isinstance(data, Mapping):
            raise MinimaxApiError("Minimax API nastavitve morajo biti JSON objekt.")

        def value(*names: str, default: str = "") -> str:
            for name in names:
                raw = data.get(name)
                if raw is not None and str(raw).strip():
                    return str(raw).strip()
            return default

        settings = cls(
            api_base=value("minimax_api_base", "api_base_url", default=DEFAULT_API_BASE),
            auth_url=value("minimax_auth_url", "token_url", default=DEFAULT_AUTH_URL),
            scope=value("minimax_scope", "scope", default=DEFAULT_SCOPE),
            client_id=value("minimax_client_id", "client_id"),
            client_secret=value("minimax_client_secret", "client_secret"),
            username=value("minimax_api_username", "username"),
            password=value("minimax_api_password", "password"),
            organisation_id=value("minimax_org_id", "org_id"),
            source_path=source,
        )
        missing = [
            label
            for label, raw in (
                ("client_id", settings.client_id),
                ("client_secret", settings.client_secret),
                ("API uporabniško ime", settings.username),
                ("API geslo", settings.password),
            )
            if not raw
        ]
        if missing:
            raise MinimaxApiError("V Minimax API nastavitvah manjka: " + ", ".join(missing))
        return settings


@dataclass(frozen=True)
class ApiResponse:
    status: int
    location: str
    body: Any


def shared_settings_candidates(base_dir: Path | None = None) -> list[Path]:
    base = (base_dir or Path(__file__).resolve().parent).resolve()
    python_root = base.parent
    return [
        python_root / "DavčnaBlagajna" / "blagajna_minimax_settings.json",
        python_root / "Podatki" / "minimax_config.json",
        base / "minimax_api_settings.json",
    ]


def resolve_settings_path(configured: str = "", base_dir: Path | None = None) -> Path:
    if configured.strip():
        return Path(configured).expanduser().resolve()
    candidates = shared_settings_candidates(base_dir)
    return next((path for path in candidates if path.is_file()), candidates[0])


def _parse_body(data: bytes, content_type: str) -> Any:
    if not data:
        return {}
    text = data.decode("utf-8", errors="replace")
    if "json" in (content_type or "").lower():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _error_detail(raw: str, fallback: str) -> str:
    """Iz Minimaxovega JSON/HTML odgovora pripravi kratko, čitljivo napako."""
    values: list[str] = []
    try:
        parsed: Any = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = raw

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            preferred = [
                item
                for key in ("Message", "message", "Error", "error", "Errors", "errors", "ModelState", "modelState")
                if (item := value.get(key)) not in (None, "", [], {})
            ]
            for item in preferred or value.values():
                collect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)
        elif value not in (None, ""):
            values.append(str(value))

    collect(parsed)
    text = "\n".join(values) or str(fallback or "Neznana napaka")
    text = re.sub(r"<\s*(?:br|/li|/p|/ul)\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip(" -•\t") for line in text.splitlines()]
    return "; ".join(dict.fromkeys(line for line in lines if line))[:1800]


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    json_payload: Mapping[str, Any] | None = None,
    form_payload: Mapping[str, Any] | None = None,
    timeout: int = 90,
) -> ApiResponse:
    request_headers = dict(headers or {})
    body: bytes | None = None
    if json_payload is not None and form_payload is not None:
        raise ValueError("JSON in form payload ne smeta biti podana hkrati.")
    if json_payload is not None:
        body = json.dumps(json_payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif form_payload is not None:
        body = urlparse.urlencode(form_payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urlrequest.Request(url, data=body, method=method.upper(), headers=request_headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            response_body = response.read()
            response_headers = dict(response.headers.items())
            return ApiResponse(
                status=int(getattr(response, "status", 0) or response.getcode()),
                location=str(response_headers.get("Location") or response_headers.get("location") or ""),
                body=_parse_body(response_body, response_headers.get("Content-Type", "")),
            )
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        detail = _error_detail(raw, str(exc.reason))
        raise MinimaxApiError(
            f"Minimax API HTTP {exc.code}: {detail}",
            status=int(exc.code),
        ) from exc
    except urlerror.URLError as exc:
        raise MinimaxApiError(f"Povezava z Minimax API ni uspela: {exc.reason}") from exc


def _api_base(value: str) -> str:
    base = (value or DEFAULT_API_BASE).strip().rstrip("/")
    while re.search(r"/api/api$", base, re.IGNORECASE):
        base = base[: base.lower().rfind("/api")]
    return base


def _api_url(base: str, path: str) -> str:
    relative = path.strip().lstrip("/")
    if relative.lower().startswith("api/"):
        relative = relative[4:]
    return f"{_api_base(base)}/api/{relative}"


def _rows(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [row for row in response if isinstance(row, dict)]
    if not isinstance(response, Mapping):
        return []
    for key in ("Rows", "rows", "Items", "items", "Item", "item", "Data", "data", "$values"):
        value = response.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            return [value]
    return []


def _record_id(record: Mapping[str, Any]) -> int | None:
    for key in (
        "ID", "Id", "id", "OrganisationId", "OrganizationId", "AccountId",
        "CustomerId", "JournalTypeId", "VatRateId", "CurrencyId",
        "DocumentNumberingId", "JournalId", "JournalEntryId", "VatEntryId",
        "IssuedInvoiceId", "ReceivedInvoiceId", "ItemId",
    ):
        value = record.get(key)
        if value is not None:
            try:
                result = int(value)
                if result > 0:
                    return result
            except (TypeError, ValueError):
                pass
    return None


def _invoice_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Poravna seznamni API zapis, ki je lahko zavit v Issued/ReceivedInvoice."""
    merged = dict(record)
    for key in ("IssuedInvoice", "issuedInvoice", "ReceivedInvoice", "receivedInvoice"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            merged.update(nested)
    return merged


def normal_invoice_reference(value: Any) -> str:
    """Normalizira listino za ujemanje KIR/KPR z Minimax DocumentReference."""
    return re.sub(r"\s+", "", str(value or "")).casefold()


def invoice_record_reference(record: Mapping[str, Any]) -> str:
    merged = _invoice_record(record)
    for key in (
        "DocumentReference", "documentReference", "DocumentRef", "documentRef",
        "InvoiceNumber", "invoiceNumber", "DocumentNumber", "documentNumber",
        "Reference", "reference", "Number", "number",
    ):
        value = str(merged.get(key) or "").strip()
        if value:
            return value
    return ""


def supplier_invoice_number(record: Mapping[str, Any]) -> str:
    """Vrne prikazano številko dobaviteljevega IR, npr. 2026-411."""
    merged = _invoice_record(record)
    number = str(merged.get("InvoiceNumber") or merged.get("invoiceNumber") or "").strip()
    issued = str(merged.get("DateIssued") or merged.get("dateIssued") or "").strip()
    year = issued[:4] if re.match(r"^\d{4}", issued) else ""
    if number and year and not number.startswith(year):
        return f"{year}-{number}"
    return number or invoice_record_reference(merged)


def invoice_status_label(value: Any) -> str:
    """Prevede Minimax status računa v jasno slovensko oznako za GUI."""
    if isinstance(value, Mapping):
        value = value.get("Code") or value.get("code") or value.get("Name") or value.get("name")
    code = str(value or "").strip().upper()
    if code in {"O", "OSNUTEK", "DRAFT"}:
        return "Osnutek"
    if code in {"P", "POTRJEN", "CONFIRMED", "POSTED"}:
        return "Potrjen"
    return code or "Ni podatka"


def invoice_record_status(record: Mapping[str, Any]) -> str:
    merged = _invoice_record(record)
    return invoice_status_label(
        merged.get("Status")
        or merged.get("status")
        or merged.get("InvoiceStatus")
        or merged.get("invoiceStatus")
        or merged.get("IssuedInvoiceStatus")
        or merged.get("issuedInvoiceStatus")
        or merged.get("ReceivedInvoiceStatus")
        or merged.get("receivedInvoiceStatus")
    )


def invoice_record_party(record: Mapping[str, Any]) -> str:
    """Kupec (IR) ali dobavitelj (PR) iz Minimax zapisa."""
    merged = _invoice_record(record)
    for key in ("Customer", "Supplier", "Partner", "Subject", "Recipient"):
        party = merged.get(key)
        if isinstance(party, Mapping):
            name = _record_name(party)
            if name:
                return name
    for key in (
        "CustomerName", "SupplierName", "PartnerName", "SubjectName",
        "RecipientName", "Name",
    ):
        value = str(merged.get(key) or "").strip()
        if value:
            return value
    return ""


def invoice_record_tax_id(record: Mapping[str, Any]) -> str:
    merged = _invoice_record(record)
    for key in ("Customer", "Supplier", "Partner", "Subject"):
        party = merged.get(key)
        if isinstance(party, Mapping):
            for tax_key in ("TaxNumber", "VatNumber", "RegistrationNumber", "Code"):
                value = str(party.get(tax_key) or "").strip()
                if value:
                    return value
    for key in ("TaxNumber", "VatNumber", "CustomerTaxNumber", "SupplierTaxNumber"):
        value = str(merged.get(key) or "").strip()
        if value:
            return value
    return ""


def invoice_record_date(record: Mapping[str, Any]) -> str:
    merged = _invoice_record(record)
    for key in (
        "DateIssued", "dateIssued", "InvoiceDate", "DocumentDate",
        "DateTransaction", "ReceiptDate",
    ):
        value = str(merged.get(key) or "").strip()
        if value:
            return value[:10]
    return ""


def invoice_record_amount(record: Mapping[str, Any]) -> Decimal:
    merged = _invoice_record(record)
    for key in (
        "InvoiceAmount", "InvoiceValue", "Total", "GrossAmount",
        "Amount", "InvoiceAmountDomesticCurrency",
    ):
        raw = merged.get(key)
        if raw is None or raw == "":
            continue
        try:
            return Decimal(str(raw).replace(",", ".")).quantize(Decimal("0.01"))
        except Exception:
            continue
    return Decimal("0.00")


def _record_name(record: Mapping[str, Any]) -> str:
    for key in ("Name", "name", "Title", "title", "Description", "description", "Code", "code"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _record_codes(record: Mapping[str, Any]) -> Iterable[str]:
    for key in ("Code", "code", "AccountNumber", "ShortName", "Title", "Name", "Description"):
        value = str(record.get(key) or "").strip()
        if value:
            yield value
            match = re.match(r"^(\d+)\b", value)
            if match:
                yield match.group(1)


def _normal(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _account_codes_equal(left: str, right: str) -> bool:
    if _normal(left) == _normal(right):
        return True
    left_digits = _digits(left).lstrip("0")
    right_digits = _digits(right).lstrip("0")
    return bool(left_digits and right_digits and left_digits == right_digits)


def _money(value: str | None) -> float:
    return float(Decimal(str(value or "0")))


_VAT_DOC_PREFIX_RE = re.compile(
    r"^(?:obra[cč]un|samoprijava(?:obresti)?)\s*;\s*",
    re.IGNORECASE,
)


def _clean_vat_document(value: str | None) -> str:
    """Odstrani vsiljeni predponi »Obracun;« / »Samoprijava;« iz listine."""
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = _VAT_DOC_PREFIX_RE.sub("", text).strip()
    return cleaned or text


def _reporting_type_code(value: str | None) -> str:
    """Minimax API enum: Obracun | Samoprijava | SamoprijavaObresti.

    POZOR: koda »1« Minimax napačno shrani kot Samoprijava — vedno pošlji »Obracun«.
    Pri oddaji VatEntry tega polja ne pošiljaj — sicer knjiga PR v stolpcu
    listine prikaže »Obracun;številka«.
    """
    text = str(value or "").strip()
    folded = text.casefold().replace("č", "c").replace("ć", "c")
    if folded in {"samoprijavaobresti", "3"}:
        return "SamoprijavaObresti"
    if folded in {"samoprijava", "2"}:
        return "Samoprijava"
    # »1«, »Obračun«, »Obracun« → Obracun (ASCII, brez č)
    return "Obracun"


class MinimaxClient:
    def __init__(self, settings: ApiSettings) -> None:
        self.settings = settings
        self.token = ""
        self.organisation_id: int | None = None
        self._references: dict[str, list[dict[str, Any]]] = {}
        self._auth_retrying = False

    @property
    def headers(self) -> dict[str, str]:
        if not self.token:
            raise MinimaxApiError("Minimax API prijava še ni bila izvedena.")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def authenticate(self) -> None:
        response = _request(
            self.settings.auth_url,
            method="POST",
            form_payload={
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "grant_type": "password",
                "username": self.settings.username,
                "password": self.settings.password,
                "scope": self.settings.scope,
            },
            timeout=60,
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        token = str(body.get("access_token") or body.get("AccessToken") or "")
        if not token:
            raise MinimaxApiError("Minimax OAuth ni vrnil dostopnega žetona.")
        self.token = token

    def _authorized_request(
        self,
        path: str,
        *,
        method: str = "GET",
        json_payload: Mapping[str, Any] | None = None,
        timeout: int = 90,
    ) -> ApiResponse:
        """API klic z enim samodejnim OAuth retryjem ob HTTP 401."""
        url = _api_url(self.settings.api_base, path)
        try:
            return _request(
                url,
                method=method,
                headers=self.headers,
                json_payload=json_payload,
                timeout=timeout,
            )
        except MinimaxApiError as exc:
            if exc.status != 401 or self._auth_retrying:
                raise
            self._auth_retrying = True
            try:
                self.authenticate()
                return _request(
                    url,
                    method=method,
                    headers=self.headers,
                    json_payload=json_payload,
                    timeout=timeout,
                )
            finally:
                self._auth_retrying = False

    def get(self, path: str) -> Any:
        return self._authorized_request(path, method="GET").body

    def post(self, path: str, payload: Mapping[str, Any]) -> ApiResponse:
        return self._authorized_request(
            path, method="POST", json_payload=payload, timeout=120
        )

    def put(self, path: str, payload: Mapping[str, Any]) -> ApiResponse:
        return self._authorized_request(
            path, method="PUT", json_payload=payload, timeout=120
        )

    def delete(self, path: str) -> ApiResponse:
        return self._authorized_request(path, method="DELETE", timeout=90)

    def organisations(self) -> list[dict[str, Any]]:
        response = self.get("currentuser/orgs?CurrentPage=1&PageSize=200&SearchString=")
        result: list[dict[str, Any]] = []
        for row in _rows(response):
            nested = row.get("Organisation") or row.get("organisation")
            if isinstance(nested, Mapping):
                merged = dict(row)
                merged.update(nested)
                row = merged
            result.append(dict(row))
        return result

    @staticmethod
    def organisation_label(record: Mapping[str, Any]) -> str:
        organisation_id = _record_id(record)
        name = _record_name(record)
        return f"{organisation_id} — {name}" if organisation_id else name

    def select_organisation(self, organisation_id: int | str) -> None:
        try:
            org = int(str(organisation_id).strip())
        except (TypeError, ValueError) as exc:
            raise MinimaxApiError(f"Neveljaven OrganisationId: {organisation_id!r}") from exc
        if org <= 0:
            raise MinimaxApiError("OrganisationId mora biti pozitivno število.")
        self.organisation_id = org
        self._references.clear()

    def received_invoices(
        self,
        *,
        status: str = "",
        page_size: int = 100,
        sort_field: str = "ReceivedInvoiceId",
        order: str = "D",
    ) -> list[dict[str, Any]]:
        """Vrne stran PR za izbrano organizacijo, brez ugibanja identifikatorjev."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        normal_status = str(status or "").strip().upper()
        query_data: dict[str, Any] = {
            "CurrentPage": 1,
            "PageSize": max(1, min(int(page_size or 100), PAGE_SIZE)),
            "SortField": str(sort_field or "ReceivedInvoiceId"),
            "Order": "A" if str(order or "D").strip().upper() == "A" else "D",
        }
        if normal_status:
            query_data["Status"] = normal_status
        response = self.get(
            f"orgs/{self.organisation_id}/receivedinvoices?{urlparse.urlencode(query_data)}"
        )
        return [dict(row) for row in _rows(response)]

    def _invoice_records(
        self,
        resource: str,
        *,
        date_from: str = "",
        date_to: str = "",
    ) -> list[dict[str, Any]]:
        """Prebere izdane ali prejete račune izbranega obdobja s paginacijo."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        if resource not in {"issuedinvoices", "receivedinvoices"}:
            raise MinimaxApiError(f"Nepodprt vir računov: {resource}")
        collected: list[dict[str, Any]] = []
        page = 1
        for _ in range(50):
            query_data: dict[str, Any] = {
                "CurrentPage": page,
                "PageSize": PAGE_SIZE,
                "SortField": "DateIssued",
                "Order": "D",
                "SearchString": "",
            }
            if str(date_from or "").strip():
                query_data["DateIssuedFrom"] = str(date_from).strip()[:10]
            if str(date_to or "").strip():
                query_data["DateIssuedTo"] = str(date_to).strip()[:10]
            response = self.get(
                f"orgs/{self.organisation_id}/{resource}?{urlparse.urlencode(query_data)}"
            )
            current = [_invoice_record(row) for row in _rows(response)]
            collected.extend(current)
            total = int(response.get("TotalRows") or 0) if isinstance(response, Mapping) else 0
            if not current or len(current) < PAGE_SIZE or (total and len(collected) >= total):
                break
            page += 1
        return collected

    @staticmethod
    def _status_catalog_for_records(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
        by_reference: dict[str, str] = {}
        by_id: dict[str, str] = {}
        by_reference_id: dict[str, str] = {}
        reference_rank: dict[str, int] = {}
        for raw in records:
            record = _invoice_record(raw)
            label = invoice_record_status(record)
            record_id = _record_id(record)
            if record_id is not None:
                by_id[str(record_id)] = label
            reference = normal_invoice_reference(invoice_record_reference(record))
            rank = record_id or 0
            if reference and rank >= reference_rank.get(reference, -1):
                by_reference[reference] = label
                reference_rank[reference] = rank
                if record_id is not None:
                    by_reference_id[reference] = str(record_id)
        return {
            "by_reference": by_reference,
            "by_id": by_id,
            "by_reference_id": by_reference_id,
        }

    def journals(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
    ) -> list[dict[str, Any]]:
        """Paginiran seznam temeljnic (lahko filtriraj po datumu)."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        collected: list[dict[str, Any]] = []
        page = 1
        for _ in range(100):
            query_data: dict[str, Any] = {
                "CurrentPage": page,
                "PageSize": PAGE_SIZE,
                "SortField": "JournalDate",
                "Order": "A",
                "SearchString": "",
            }
            if str(date_from or "").strip():
                query_data["DateFrom"] = str(date_from).strip()[:10]
            if str(date_to or "").strip():
                query_data["DateTo"] = str(date_to).strip()[:10]
            response = self.get(
                f"orgs/{self.organisation_id}/journals?{urlparse.urlencode(query_data)}"
            )
            current = [dict(row) for row in _rows(response) if isinstance(row, Mapping)]
            collected.extend(current)
            total = int(response.get("TotalRows") or 0) if isinstance(response, Mapping) else 0
            if not current or len(current) < PAGE_SIZE or (total and len(collected) >= total):
                break
            page += 1
        return collected

    def journal(self, journal_id: int | str) -> dict[str, Any]:
        """Podrobnosti ene temeljnice (vrstice + DDV)."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        identifier = str(journal_id or "").strip()
        if not identifier.isdigit():
            raise MinimaxApiError("ID temeljnice mora biti pozitivno število.")
        record = self.get(f"orgs/{self.organisation_id}/journals/{identifier}")
        if not isinstance(record, Mapping):
            raise MinimaxApiError(f"Minimax API ni vrnil temeljnice {identifier}.")
        return dict(record)

    def delete_journal(self, journal_id: int | str) -> ApiResponse:
        """Izbriši temeljnico (običajno samo osnutek Status=O)."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        identifier = str(journal_id or "").strip()
        if not identifier.isdigit():
            raise MinimaxApiError("ID temeljnice mora biti pozitivno število.")
        return self.delete(f"orgs/{self.organisation_id}/journals/{identifier}")

    @staticmethod
    def journal_status_code(record: Mapping[str, Any]) -> str:
        """O = osnutek, P = potrjen."""
        raw = str(
            record.get("Status")
            or record.get("JournalStatus")
            or record.get("status")
            or ""
        ).strip().upper()
        if raw in {"O", "OSNUTEK", "DRAFT"}:
            return "O"
        if raw in {"P", "POTRJEN", "CONFIRMED"}:
            return "P"
        # Včasih API vrne DisplayName
        if "OSNUT" in raw or "DRAFT" in raw:
            return "O"
        if "POTRJ" in raw or "CONFIRM" in raw:
            return "P"
        return raw[:1] if raw else ""

    @staticmethod
    def journal_type_code(record: Mapping[str, Any]) -> str:
        jt = record.get("JournalType")
        if isinstance(jt, Mapping):
            for key in ("Name", "Code", "DisplayCode"):
                value = str(jt.get(key) or "").strip().upper()
                if value:
                    return value
        return str(record.get("JournalTypeCode") or "").strip().upper()

    @classmethod
    def journal_book_code(cls, record: Mapping[str, Any]) -> str:
        """IR/PR/DI knjiga: tip temeljnice ali VatBook (temeljnice so povezane s knjigo)."""
        raw = cls.journal_type_code(record)
        text = str(raw or "").strip().upper()
        if text in {"IR", "PR", "DI"}:
            return text
        if any(token in text for token in ("IZDAN", "ISSUED", "SALES")):
            return "IR"
        if any(token in text for token in ("PREJET", "RECEIV", "PURCHAS")):
            return "PR"
        if any(token in text for token in ("IZTRZ", "IZTRŽ", "PARAGON", "BLAGAJN", "DNEVN")):
            return "DI"
        # Po detajlu: knjiga DDV na VatEntries.
        for entry in record.get("VatEntries") or []:
            if not isinstance(entry, Mapping):
                continue
            book = str(entry.get("VatBook") or "").strip().upper()
            if book in {"IR", "PR", "DI"}:
                return book
        if text.startswith("IR"):
            return "IR"
        if text.startswith("PR"):
            return "PR"
        if text.startswith("DI"):
            return "DI"
        return text

    def journal_books(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
        types: tuple[str, ...] = ("IR", "PR"),
        progress: Callable[..., None] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Temeljnice, povezane s knjigo IR/PR (+ polni detajl za stolpce FURS)."""
        wanted = {str(t).strip().upper() for t in types if str(t).strip()}
        if progress:
            progress("Berem seznam temeljnic …", current=0, total=0)
        summaries = self.journals(date_from=date_from, date_to=date_to)
        # Najprej očitni IR/PR; ostale (brez tipa IR/PR na seznamu) preverimo
        # po detajlu — VatBook je pogosto šele tam (sicer prazen prenos).
        selected: list[dict[str, Any]] = []
        maybe: list[dict[str, Any]] = []
        for row in summaries:
            if _record_id(row) is None:
                continue
            code = self.journal_book_code(row)
            if code in wanted:
                selected.append(dict(row))
            elif code not in {"IR", "PR"}:
                maybe.append(dict(row))
        # Omejitev: ne prenašaj vseh temeljnic, če je kandidatov veliko.
        if maybe and len(maybe) <= max(80, len(selected) * 3):
            selected.extend(maybe)
        result: dict[str, list[dict[str, Any]]] = {code: [] for code in sorted(wanted)}
        total = len(selected)
        if progress:
            progress(
                f"Najdeno {total} kandidatov temeljnic — prenašam podrobnosti …",
                current=0,
                total=total,
            )
        customer_lookup = self._customer_lookup()
        for index, row in enumerate(selected, start=1):
            jid = _record_id(row)
            assert jid is not None
            code = self.journal_book_code(row)
            if progress:
                progress(f"Temeljnica {code or '?'} {index}/{total} (ID {jid})", current=index, total=total)
            detail = self.journal(jid)
            detail["_list"] = dict(row)
            self._enrich_journal_customers(detail, customer_lookup)
            # Po detajlu lahko VatBook popravi IR/PR (temeljnica ↔ knjiga).
            code = self.journal_book_code(detail) or code
            if code not in wanted:
                continue
            result.setdefault(code, []).append(detail)
        if progress:
            done_n = sum(len(v) for v in result.values())
            progress(
                f"Prenos končan: {done_n} temeljnic knjige IR/PR.",
                current=total,
                total=total,
            )
        return result

    def _customer_lookup(self) -> dict[int, dict[str, Any]]:
        """Šifrant strank po CustomerId (za državo / DDV ID pri temeljnicah)."""
        lookup: dict[int, dict[str, Any]] = {}
        try:
            for record in self._all("customers"):
                cid = record.get("CustomerId") or _record_id(record)
                try:
                    key = int(cid)
                except (TypeError, ValueError):
                    continue
                if key > 0:
                    lookup[key] = dict(record)
        except MinimaxApiError:
            pass
        return lookup

    def _enrich_journal_customers(
        self,
        journal: dict[str, Any],
        lookup: Mapping[int, Mapping[str, Any]] | None = None,
    ) -> None:
        """Dopolni Customer na VatEntries z državo in davčno (za DDV-O EU)."""
        by_id = dict(lookup or self._customer_lookup())
        if not by_id:
            return

        def enrich(customer: Any) -> None:
            if not isinstance(customer, dict):
                return
            try:
                cid = int(customer.get("ID") or customer.get("CustomerId") or 0)
            except (TypeError, ValueError):
                return
            full = by_id.get(cid)
            if not full:
                return
            if full.get("Country") is not None:
                customer["Country"] = full.get("Country")
            for key in ("TaxNumber", "VatNumber", "VATIdentificationNumber", "CountryName"):
                if full.get(key) not in (None, ""):
                    customer[key] = full.get(key)

        for entry in journal.get("VatEntries") or []:
            if isinstance(entry, Mapping):
                enrich(entry.get("Customer"))
        for entry in journal.get("JournalEntries") or []:
            if isinstance(entry, Mapping):
                enrich(entry.get("Customer"))

    def invoice_book(
        self,
        book: str,
        *,
        date_from: str = "",
        date_to: str = "",
    ) -> list[dict[str, Any]]:
        """Vrne Minimax knjigo IR ali PR za obdobje (paginirano)."""
        code = str(book or "").strip().upper()
        if code == "IR":
            resource = "issuedinvoices"
        elif code == "PR":
            resource = "receivedinvoices"
        else:
            raise MinimaxApiError(f"Nepodprta knjiga: {book!r} (pričakovano IR ali PR).")
        return self._invoice_records(resource, date_from=date_from, date_to=date_to)

    def invoice_status_catalog(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
    ) -> dict[str, dict[str, dict[str, str]]]:
        """Vrne statuse IR in PR po dejanskem API ID-ju ter po listini."""
        return {
            "IR": self._status_catalog_for_records(
                self._invoice_records("issuedinvoices", date_from=date_from, date_to=date_to)
            ),
            "PR": self._status_catalog_for_records(
                self._invoice_records("receivedinvoices", date_from=date_from, date_to=date_to)
            ),
        }

    def existing_document_references(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
    ) -> dict[str, dict[str, str]]:
        """Vrne normalizirane listine, ki že obstajajo v Minimaxu (IR/PR → status)."""
        catalog = self.invoice_status_catalog(date_from=date_from, date_to=date_to)
        return {
            "IR": dict(catalog.get("IR", {}).get("by_reference") or {}),
            "PR": dict(catalog.get("PR", {}).get("by_reference") or {}),
        }

    def invoice_status_by_id(self, book: str, record_id: int | str) -> tuple[str, str]:
        """Prebere status točno določenega IR/PR; vrne (status, listina)."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        identifier = str(record_id or "").strip()
        if not identifier.isdigit():
            raise MinimaxApiError("ID računa mora biti pozitivno število.")
        resource = "issuedinvoices" if str(book).strip().upper() == "IR" else "receivedinvoices"
        record = self.get(f"orgs/{self.organisation_id}/{resource}/{identifier}")
        if not isinstance(record, Mapping):
            raise MinimaxApiError(f"Minimax API ni vrnil podatkov za {book} ID {identifier}.")
        return invoice_record_status(record), invoice_record_reference(record)

    def invoice_attachments(self, book: str, record_id: int | str) -> list[dict[str, Any]]:
        """Vrne priponke točno določenega izdanega ali prejetega računa."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        identifier = str(record_id or "").strip()
        if not identifier.isdigit():
            raise MinimaxApiError("ID računa mora biti pozitivno število.")
        resource = "issuedinvoices" if str(book).strip().upper() == "IR" else "receivedinvoices"
        response = self.get(f"orgs/{self.organisation_id}/{resource}/{identifier}/attachments")
        if isinstance(response, list):
            return [dict(row) for row in response if isinstance(row, Mapping)]
        return [dict(row) for row in _rows(response)]

    def add_invoice_attachment(
        self, book: str, record_id: int | str, *, filename: str, data: bytes, mime_type: str
    ) -> ApiResponse:
        """Doda priponko na obstoječi IR ali PR, tudi če je dokument že potrjen."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        identifier = str(record_id or "").strip()
        if not identifier.isdigit():
            raise MinimaxApiError("ID računa mora biti pozitivno število.")
        resource = "issuedinvoices" if str(book).strip().upper() == "IR" else "receivedinvoices"
        safe_name = Path(str(filename or "priponka.bin")).name or "priponka.bin"
        payload = {
            "AttachmentData": base64.b64encode(bytes(data)).decode("ascii"),
            "AttachmentFileName": safe_name,
            "AttachmentMimeType": str(mime_type or "application/octet-stream"),
        }
        return self.post(
            f"orgs/{self.organisation_id}/{resource}/{identifier}/attachments", payload
        )

    def find_received_invoice(
        self, *, document_reference: str, supplier_name: str, gross_total: Decimal,
        invoice_date: str, date_from: str, date_to: str,
    ) -> dict[str, Any]:
        """Enolično poišče PR po referenci oziroma partnerju, datumu in znesku."""
        wanted_ref = normal_invoice_reference(document_reference)
        wanted_party = _normal(supplier_name)
        wanted_date = str(invoice_date or "").strip()[:10]
        candidates: list[dict[str, Any]] = []
        for record in self._invoice_records("receivedinvoices", date_from=date_from, date_to=date_to):
            party = record.get("Customer") if isinstance(record.get("Customer"), Mapping) else {}
            party_text = _normal(party.get("Name") or record.get("CustomerName"))
            raw_total = record.get("InvoiceAmount") or record.get("InvoiceValue") or record.get("Total") or 0
            try:
                total = Decimal(str(raw_total).replace(",", "."))
            except Exception:
                continue
            record_ref = normal_invoice_reference(invoice_record_reference(record))
            record_date = str(record.get("DateIssued") or record.get("DateTransaction") or "")[:10]
            reference_ok = bool(wanted_ref and record_ref == wanted_ref)
            fallback_ok = bool(
                wanted_party and wanted_party in party_text
                and (not wanted_date or record_date == wanted_date)
                and abs(total - Decimal(gross_total)) <= Decimal("0.02")
            )
            if reference_ok or fallback_ok:
                candidates.append(record)
        unique = {_record_id(row): row for row in candidates if _record_id(row)}
        if len(unique) != 1:
            raise MinimaxApiError(
                f"PR {document_reference} ni enolično najden v ciljni organizaciji (najdenih {len(unique)})."
            )
        return next(iter(unique.values()))

    def supplier_issued_invoice_attachments(
        self, *, supplier_name: str, customer_name: str, customer_tax_id: str,
        gross_total: Decimal, invoice_date: str, date_from: str, date_to: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Poišče enoličen dobaviteljev IR za kupca in vrne njegove priponke."""
        original_org = self.organisation_id
        def org_key(value: Any) -> str:
            text = re.sub(r"\(\s*test\s*\)", "", str(value or ""), flags=re.I)
            text = re.sub(r"\b(d\s*\.\s*o\s*\.\s*o\s*\.?|d\s*\.\s*d\s*\.?)\s*$", "", text, flags=re.I)
            return re.sub(r"\W+", "", text).casefold()

        wanted_supplier = org_key(supplier_name)
        organisations = self.organisations()
        exact = [
            row for row in organisations
            if wanted_supplier and org_key(_record_name(row)) == wanted_supplier
            and "(test)" not in _record_name(row).casefold()
        ]
        matches = exact or [
            row for row in organisations
            if wanted_supplier and wanted_supplier in org_key(_record_name(row))
            and "(test)" not in _record_name(row).casefold()
        ]
        if len(matches) != 1:
            raise MinimaxApiError(f"Organizacija {supplier_name} ni enolično dostopna prek API (najdenih {len(matches)}).")
        supplier_org = _record_id(matches[0])
        if not supplier_org:
            raise MinimaxApiError(f"Organizacija {supplier_name} nima veljavnega Org_ID.")
        try:
            self.select_organisation(supplier_org)
            records = self._invoice_records("issuedinvoices", date_from=date_from, date_to=date_to)
            tax = re.sub(r"\D", "", customer_tax_id)
            name = re.sub(r"\W+", "", customer_name).casefold()
            wanted_date = str(invoice_date or "").strip()[:10]
            candidates: list[dict[str, Any]] = []
            for record in records:
                customer = record.get("Customer") if isinstance(record.get("Customer"), Mapping) else {}
                customer_text = re.sub(r"\W+", "", str(customer.get("Name") or record.get("CustomerName") or "")).casefold()
                customer_tax = re.sub(r"\D", "", str(customer.get("TaxNumber") or record.get("CustomerTaxNumber") or ""))
                raw_total = record.get("InvoiceValue") or record.get("Total") or record.get("Value") or 0
                try:
                    total = Decimal(str(raw_total).replace(",", "."))
                except Exception:
                    continue
                party_ok = bool((tax and customer_tax == tax) or (name and name in customer_text))
                record_date = str(record.get("DateTransaction") or record.get("DateIssued") or "")[:10]
                date_ok = not wanted_date or record_date == wanted_date
                if party_ok and date_ok and abs(total - Decimal(gross_total)) <= Decimal("0.02"):
                    candidates.append(record)
            if len(candidates) != 1:
                raise MinimaxApiError(
                    f"Za {customer_name} in znesek {gross_total} ni enoličnega IR pri {supplier_name} (najdenih {len(candidates)})."
                )
            invoice_id = _record_id(candidates[0])
            if not invoice_id:
                raise MinimaxApiError("Najdeni izdani račun nima IssuedInvoiceId.")
            detail = self.get(f"orgs/{self.organisation_id}/issuedinvoices/{invoice_id}")
            invoice = _invoice_record(detail) if isinstance(detail, Mapping) else candidates[0]
            return invoice, self.invoice_attachments("IR", invoice_id)
        finally:
            if original_org:
                self.select_organisation(original_org)

    @staticmethod
    def attachment_file(attachment: Mapping[str, Any]) -> tuple[str, bytes]:
        """Pretvori Minimax AttachmentData v varno ime datoteke in bajte."""
        name = str(
            attachment.get("AttachmentFileName") or attachment.get("FileName")
            or attachment.get("Name") or "priponka.bin"
        ).strip()
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(name).name) or "priponka.bin"
        raw = attachment.get("AttachmentData") or attachment.get("Data") or attachment.get("Content")
        if isinstance(raw, bytes):
            return name, raw
        value = str(raw or "").strip()
        if value.startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        if not value:
            raise MinimaxApiError(f"Priponka {name} ne vsebuje podatkov za prenos.")
        try:
            return name, base64.b64decode(value, validate=False)
        except (ValueError, TypeError) as exc:
            raise MinimaxApiError(f"Priponke {name} ni bilo mogoče dekodirati.") from exc

    def latest_confirmed_received_invoice(self) -> dict[str, Any] | None:
        """Poišče zadnji potrjeni PR (status P) in vrne njegov dejanski API zapis."""
        try:
            rows = self.received_invoices(status="P", sort_field="ReceivedInvoiceId", order="D")
        except MinimaxApiError:
            # Nekatere različice API ne sprejmejo sortiranja po ID-ju.
            rows = self.received_invoices(status="P", sort_field="DateIssued", order="D")
        confirmed = [
            row for row in rows
            if str(row.get("Status") or "P").strip().upper() in {"P", "POTRJEN", "CONFIRMED"}
        ]
        if not confirmed:
            return None
        return max(confirmed, key=lambda row: _record_id(row) or 0)

    @staticmethod
    def received_invoice_id(record: Mapping[str, Any] | None) -> int | None:
        """Javni pomočnik za dejanski ReceivedInvoiceId zapisa API."""
        return _record_id(record or {})

    def _all(self, resource: str) -> list[dict[str, Any]]:
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        if resource in self._references:
            return self._references[resource]
        collected: list[dict[str, Any]] = []
        page = 1
        for _ in range(50):
            query = urlparse.urlencode({"CurrentPage": page, "PageSize": PAGE_SIZE, "SearchString": ""})
            response = self.get(f"orgs/{self.organisation_id}/{resource}?{query}")
            current = _rows(response)
            collected.extend(current)
            total = int(response.get("TotalRows") or 0) if isinstance(response, Mapping) else 0
            if not current or len(current) < PAGE_SIZE or (total and len(collected) >= total):
                break
            page += 1
        self._references[resource] = collected
        return collected

    def refresh_references(self) -> dict[str, int]:
        self._references.clear()
        counts = {
            resource: len(self._all(resource))
            for resource in ("journaltypes", "accounts", "customers", "vatrates", "currencies", "items")
        }
        counts["document_numberings"] = len(self._all("document-numbering"))
        return counts

    def document_numbering_catalog(self, book: str = "") -> list[dict[str, Any]]:
        """Vrne aktivna številčenja za IR oziroma PR; privzeto je na vrhu."""
        wanted = book.strip().upper()
        result: list[dict[str, Any]] = []
        for record in self._all("document-numbering"):
            record_id = _record_id(record)
            document = str(record.get("Document") or "").strip().upper()
            if record_id is None or (wanted and document != wanted):
                continue
            if str(record.get("Usage") or "D").strip().upper() == "N":
                continue
            code = str(record.get("Code") or "").strip()
            name = str(record.get("Name") or code or document).strip()
            parts = [str(record_id)]
            if code:
                parts.append(code)
            if name and name != code:
                parts.append(name)
            result.append(
                {
                    "id": record_id,
                    "document": document,
                    "code": code,
                    "name": name,
                    "default": str(record.get("Default") or "N").strip().upper() == "D",
                    "label": " — ".join(parts),
                }
            )
        return sorted(result, key=lambda item: (not item["default"], item["code"].casefold(), item["id"]))

    def vat_accounting_type_catalog(self, effective_date: str = "") -> list[dict[str, str]]:
        """Vrne vrste obračuna DDV, veljavne na izbrani datum."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        value = (effective_date or date.today().isoformat())[:10]
        cache_key = f"vataccountingtypes:{value}"
        if cache_key not in self._references:
            query = urlparse.urlencode(
                {"date": value, "CurrentPage": 1, "PageSize": PAGE_SIZE, "SearchString": ""}
            )
            self._references[cache_key] = _rows(
                self.get(f"orgs/{self.organisation_id}/vataccountingtypes?{query}")
            )
        result: list[dict[str, str]] = []
        for record in self._references[cache_key]:
            code = str(record.get("Code") or "").strip().upper()
            if not code:
                continue
            result.append(
                {
                    "code": code,
                    "book": str(record.get("IssuedRecived") or "").strip().upper(),
                    "name": str(record.get("Name") or code).strip(),
                    "label": f"{code} — {str(record.get('Name') or code).strip()}",
                }
            )
        return result

    def account_catalog(self, *, bookable_only: bool = False) -> list[dict[str, Any]]:
        """
        Vrne šifro in naziv konta iz šifranta trenutno izbrane organizacije.

        Minimax Account.AllowedPosting:
          V = breme in dobro, B = samo breme, D = samo dobro, N = knjiženje ni dovoljeno.
        Application: D = v uporabi, N = ne.
        """
        catalog: dict[str, dict[str, Any]] = {}
        for record in self._all("accounts"):
            code = str(
                record.get("Code")
                or record.get("AccountNumber")
                or record.get("ShortName")
                or ""
            ).strip()
            if not code:
                continue
            name = str(
                record.get("Name")
                or record.get("Description")
                or record.get("Title")
                or code
            ).strip()
            allowed = str(record.get("AllowedPosting") or "").strip().upper()
            application = str(record.get("Application") or "").strip().upper()
            # Samo AllowedPosting = N je neknjižljiv (Application pri mnogih orgih vedno N).
            if bookable_only and allowed == "N":
                continue
            catalog.setdefault(
                code,
                {
                    "id": _record_id(record),
                    "code": code,
                    "name": name,
                    "allowed_posting": allowed,
                    "application": application,
                    "label": f"{code} — {name}" if name and name != code else code,
                },
            )

        def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
            code = str(item["code"])
            return (0, int(code), code) if code.isdigit() else (1, 0, code.casefold())

        return sorted(catalog.values(), key=sort_key)

    def item_catalog(self) -> list[dict[str, Any]]:
        """Vrne artikle, potrebne na vrsticah izdanega računa."""
        account_by_id = {
            int(item["id"]): str(item["code"])
            for item in self.account_catalog()
            if item.get("id") is not None
        }
        result: list[dict[str, Any]] = []
        for record in self._all("items"):
            item_id = _record_id(record)
            if item_id is None:
                continue
            code = str(record.get("Code") or "").strip()
            title = str(record.get("Title") or record.get("Name") or code or f"Artikel {item_id}").strip()
            item_type = str(record.get("ItemType") or "").strip().upper()
            unit = str(record.get("UnitOfMeasurement") or "kos").strip() or "kos"
            revenue = record.get("RevenueAccountDomestic")
            revenue_id = _record_id(revenue) if isinstance(revenue, Mapping) else None
            revenue_code = account_by_id.get(revenue_id or 0, "")
            parts = [str(item_id)]
            if code:
                parts.append(code)
            parts.append(title)
            details = []
            if item_type:
                details.append("storitev" if item_type == "S" else f"tip {item_type}")
            if revenue_code:
                details.append(f"konto {revenue_code}")
            label = " — ".join(parts) + (f"  [{', '.join(details)}]" if details else "")
            result.append(
                {
                    "id": item_id,
                    "code": code,
                    "title": title,
                    "type": item_type,
                    "unit": unit,
                    "revenue_account_id": revenue_id,
                    "revenue_account": revenue_code,
                    "label": label,
                }
            )
        return sorted(
            result,
            key=lambda item: (
                item["type"] != "S",
                item["revenue_account"] != "7601",
                item["code"].casefold(),
                item["title"].casefold(),
            ),
        )

    def _reference_by_code(self, resource: str, code: str) -> dict[str, int]:
        for record in self._all(resource):
            if any(_account_codes_equal(code, candidate) for candidate in _record_codes(record)):
                record_id = _record_id(record)
                if record_id is not None:
                    return {"ID": record_id}
        raise MinimaxApiError(f"V Minimax šifrantu '{resource}' ni najdena šifra '{code}'.")

    def _account_record(self, code: str) -> Mapping[str, Any] | None:
        """Minimax Account po šifri (CustomerEntry / InvoiceAccounting …)."""
        wanted = str(code or "").strip()
        if not wanted:
            return None
        for record in self._all("accounts"):
            if any(_account_codes_equal(wanted, candidate) for candidate in _record_codes(record)):
                return record
        return None

    def _account_field_flags(self, code: str) -> dict[str, str]:
        """
        Minimax Account zastavice (D/V/B = dovoljeno/obvezno, N = ne sme):
          CustomerEntry → Customer
          InvoiceAccounting + tip konta → DueDate / TransactionDate / PaymentReference

        Pozor: InvoiceAccounting=D NI dovolj — npr. 9729 (posojila) ima D, a API
        zavrne DatumOpravljanja/Zapadlosti (HTTP 409). Datumi samo na 12xx/22xx.
        """
        record = self._account_record(code) or {}
        customer = str(record.get("CustomerEntry") or "N").strip().upper() or "N"
        invoice_flag = str(record.get("InvoiceAccounting") or "N").strip().upper() or "N"
        digits = "".join(ch for ch in str(code or "") if ch.isdigit())
        trade_ar_ap = bool(digits) and (
            digits.startswith("12") or digits.startswith("22")
        )
        # Datumi/veza samo pri terjatvah/obveznostih do kupcev/dobaviteljev
        invoice = invoice_flag if (invoice_flag != "N" and trade_ar_ap) else "N"
        return {
            "customer": customer,
            "invoice": invoice,
        }

    def _customer_reference(self, party: Mapping[str, str]) -> dict[str, int]:
        wanted_tax = _digits(party.get("tax_id"))
        wanted_name = _normal(party.get("name"))
        wanted_code = _normal(party.get("code"))
        # Najprej šifra (npr. Končni kupci 01345) — zanesljivejše od davčne/imena
        if wanted_code:
            for record in self._all("customers"):
                record_id = _record_id(record)
                if record_id is None:
                    continue
                if _normal(record.get("Code")) == wanted_code:
                    return {"ID": record_id}
        for record in self._all("customers"):
            record_id = _record_id(record)
            if record_id is None:
                continue
            record_taxes = [
                _digits(record.get(key))
                for key in ("TaxNumber", "VatNumber", "RegistrationNumber", "Code")
            ]
            if wanted_tax and any(
                value and (value == wanted_tax or value.endswith(wanted_tax) or wanted_tax.endswith(value))
                for value in record_taxes
            ):
                return {"ID": record_id}
            record_name = _normal(_record_name(record))
            record_code = _normal(record.get("Code"))
            if not wanted_tax and ((wanted_name and record_name == wanted_name) or (wanted_code and record_code == wanted_code)):
                return {"ID": record_id}
        label = party.get("tax_id") or party.get("name") or party.get("code") or "neznana stranka"
        raise MinimaxApiError(
            f"Partner '{label}' ni najden v šifrantu strank Minimax. "
            "Najprej ga dodajte v Minimax ali popravite davčno številko."
        )

    def _vat_rate_reference(self, code: str) -> dict[str, int]:
        percentage = RATE_PERCENTAGES.get(code)
        if percentage is None:
            raise MinimaxApiError(f"Neznana oznaka DDV stopnje '{code}'.")
        for record in self._all("vatrates"):
            if _normal(record.get("Code")) == _normal(code):
                record_id = _record_id(record)
                if record_id is not None:
                    return {"ID": record_id}
        best: int | None = None
        for record in self._all("vatrates"):
            raw = next(
                (
                    record.get(key)
                    for key in ("Percent", "Percentage", "Rate", "VatRatePercentage")
                    if record.get(key) is not None and not isinstance(record.get(key), Mapping)
                ),
                None,
            )
            if raw is None:
                continue
            try:
                candidate = float(str(raw).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if round(candidate, 3) == round(percentage, 3):
                best = _record_id(record)
                if best is not None:
                    break
        if best is None:
            label = str(percentage).replace(".0", "").replace(".", ",")
            raise MinimaxApiError(f"V Minimax šifrantu ni najdena DDV stopnja {label} %.")
        return {"ID": best}

    def prepare_journal_payload(
        self,
        root: etree._Element,
        status: str = "O",
        *,
        vat_type_ir: str = "",
        vat_type_pr: str = "",
    ) -> dict[str, Any]:
        """
        Sestavi payload za POST /journals.
        Pri IR ne vsiljuj VatAccountingType (OD/NI → HTTP 409);
        Minimax sam določi vrsto obračuna DDV.
        """
        namespace = {"m": minimax_xml.NS}
        parties: dict[str, dict[str, str]] = {}
        for node in root.xpath("./m:Stranke/m:Stranka", namespaces=namespace):
            def node_text(name: str) -> str:
                return str(node.xpath(f"string(./m:{name})", namespaces=namespace) or "").strip()
            parties[node_text("Sifra")] = {
                "code": node_text("Sifra"),
                "name": node_text("Naziv"),
                "country": node_text("KraticaDrzave"),
                "tax_id": node_text("DavcnaStevilka") or node_text("IdentifikacijskaStevilka"),
            }

        journals = root.xpath("./m:Temeljnice/m:Temeljnica", namespaces=namespace)
        if len(journals) != 1:
            raise MinimaxApiError(f"Za API oddajo je pričakovana ena temeljnica, dobljeno: {len(journals)}.")
        journal = journals[0]

        def text(node: etree._Element, path: str) -> str:
            return str(node.xpath(f"string({path})", namespaces=namespace) or "").strip()

        kind = text(journal, "./m:GlavaTemeljnice/m:SifraVrsteTemeljnice")
        journal_date = text(journal, "./m:GlavaTemeljnice/m:DatumTemeljnice")
        description = text(journal, "./m:GlavaTemeljnice/m:OpisGlaveTemeljnice")
        currency = self._reference_by_code("currencies", "EUR")
        entries: list[dict[str, Any]] = []
        external_by_party: dict[str, str] = {}
        # Privzeta stranka iz DDV glave / prve SifraStranke — za konti z CustomerEntry=D
        default_party_code = ""
        for ddv_row in journal.xpath("./m:DDV/m:DDVVrstica", namespaces=namespace):
            default_party_code = text(ddv_row, "./m:DDVGlava/m:SifraStranke")
            if default_party_code:
                break
        if not default_party_code:
            for line in journal.xpath("./m:VrsticeTemeljnice/m:VrsticaTemeljnice", namespaces=namespace):
                default_party_code = text(line, "./m:SifraStranke")
                if default_party_code:
                    break

        for index, line in enumerate(journal.xpath("./m:VrsticeTemeljnice/m:VrsticaTemeljnice", namespaces=namespace), 1):
            account_code = core.validate_minimax_account_code(text(line, "./m:SifraKonta"))
            party_code = text(line, "./m:SifraStranke")
            flags = self._account_field_flags(account_code)
            customer_ok = flags["customer"] in {"D", "V", "B"}
            invoice_ok = flags["invoice"] in {"D", "V", "B"}
            external_id = f"{kind}-{index}"
            entry: dict[str, Any] = {
                "ExternalId": external_id,
                "JournalEntryDate": text(line, "./m:DatumKnjizbe") or journal_date,
                "Account": self._reference_by_code("accounts", account_code),
                "Currency": currency,
                "Description": text(line, "./m:OpisVrsticeTemeljnice") or description,
                "Debit": _money(text(line, "./m:ZnesekVBremeVDenarniEnoti")),
                "Credit": _money(text(line, "./m:ZnesekVDobroVDenarniEnoti")),
                "DebitInDomesticCurrency": _money(text(line, "./m:ZnesekVBremeVDomaciDenarniEnoti")),
                "CreditInDomesticCurrency": _money(text(line, "./m:ZnesekVDobroVDomaciDenarniEnoti")),
            }
            # Minimax Account.InvoiceAccounting=N → DueDate/TransactionDate/PaymentReference NE smejo
            if invoice_ok:
                due = text(line, "./m:DatumZapadlosti")
                transaction = text(line, "./m:DatumOpravljanja")
                payment_reference = text(line, "./m:VezaZaPlacilo")
                if due:
                    entry["DueDate"] = due
                if transaction:
                    entry["TransactionDate"] = transaction
                if payment_reference:
                    entry["PaymentReference"] = payment_reference
            # Minimax Account.CustomerEntry=N → Customer NE sme; D → obvezno
            use_party = party_code if customer_ok else ""
            if customer_ok and not use_party:
                use_party = default_party_code
            if customer_ok and use_party:
                party = parties.get(use_party)
                if not party:
                    raise MinimaxApiError(f"Partner '{use_party}' iz temeljnice ni v seznamu strank.")
                entry["Customer"] = self._customer_reference(party)
                external_by_party[use_party] = external_id
            elif flags["customer"] == "D" and not use_party:
                raise MinimaxApiError(
                    f"Konto {account_code} zahteva stranko (CustomerEntry=D), "
                    "vendar je v temeljnici ni."
                )
            entries.append(entry)

        debit = round(sum(float(entry["DebitInDomesticCurrency"]) for entry in entries), 2)
        credit = round(sum(float(entry["CreditInDomesticCurrency"]) for entry in entries), 2)
        if debit != credit:
            raise MinimaxApiError(f"Temeljnica ni uravnotežena: breme {debit:.2f}, dobro {credit:.2f}.")

        vat_entries: list[dict[str, Any]] = []
        for ddv_row in journal.xpath("./m:DDV/m:DDVVrstica", namespaces=namespace):
            header = ddv_row.xpath("./m:DDVGlava", namespaces=namespace)[0]
            party_code = text(header, "./m:SifraStranke")
            party = parties.get(party_code)
            # DI (Paragoni) = izdani iztržek — ista DDV logika kot IR
            vat_type = (
                vat_type_ir.strip().upper()
                if kind in {"IR", "DI"}
                else vat_type_pr.strip().upper()
            )
            raw_doc = text(header, "./m:Listina")
            # Listina = SAMO številka. Ne pošiljaj ReportingType — Minimax v knjigi
            # PR sicer v stolpec 4 zloži »Obracun;2746100« / »Samoprijava;…«.
            document = _clean_vat_document(raw_doc) or raw_doc
            vat_book = text(header, "./m:KnjigaDDV") or kind
            vat_entry: dict[str, Any] = {
                "VatDate": text(header, "./m:DatumDDV"),
                "VatBook": vat_book,
                "VatEntryDate": text(header, "./m:DatumKnjizenjaDDV") or journal_date,
                "Document": document,
                "DocumentDate": text(header, "./m:DatumListine"),
                "SelfTaxing": text(header, "./m:Samoobdavcitev") or "N",
                "AdvancePayment": "N",
                "VatEntryRows": [],
            }
            if vat_type:
                available = {
                    item["code"]
                    for item in self.vat_accounting_type_catalog(text(header, "./m:DatumDDV") or journal_date)
                    if not item["book"] or item["book"] in {kind, vat_book, "IR" if kind == "DI" else kind}
                }
                if available and vat_type not in available:
                    raise MinimaxApiError(
                        f"Vrsta obračuna DDV '{vat_type}' ni veljavna za knjigo {kind} na dan "
                        f"{text(header, './m:DatumDDV') or journal_date}."
                    )
                vat_entry["VatAccountingType"] = vat_type
            received = text(header, "./m:DatumPrejema")
            transaction = text(header, "./m:DatumOpravljanja")
            if received:
                vat_entry["ReceivedDate"] = received
            if transaction:
                vat_entry["TransactionDate"] = transaction
            # WebUI »Osnovno sredstvo« / »Nepremičnina« na podatkih za DDV.
            if str(vat_book or "").upper() == "PR":
                for xml_name, api_name in VAT_HEADER_AMOUNTS.items():
                    raw_amt = text(header, f"./m:{xml_name}")
                    if raw_amt and Decimal(str(raw_amt)) != 0:
                        vat_entry[api_name] = _money(raw_amt)
            if party:
                vat_entry["Customer"] = self._customer_reference(party)
            if party_code in external_by_party:
                vat_entry["JournalEntryExternalId"] = external_by_party[party_code]
            for rate in ddv_row.xpath("./m:DDVStopnje/m:DDVStopnja", namespaces=namespace):
                code = text(rate, "./m:SifraStopnjeDDV")
                rate_row: dict[str, Any] = {"VatRate": self._vat_rate_reference(code)}
                for xml_name, api_name in VAT_ROW_FIELDS.items():
                    value = text(rate, f"./m:{xml_name}")
                    if value:
                        rate_row[api_name] = _money(value)
                vat_entry["VatEntryRows"].append(rate_row)
            vat_entries.append(vat_entry)

        return {
            "JournalType": self._reference_by_code("journaltypes", kind),
            "JournalDate": journal_date,
            "Description": description,
            "Status": status if status in {"O", "P"} else "O",
            "JournalEntries": entries,
            "VatEntries": vat_entries,
        }

    @staticmethod
    def _positive_id(value: Any, label: str) -> int:
        try:
            result = int(str(value or "").strip())
        except (TypeError, ValueError) as exc:
            raise MinimaxApiError(f"Za {label} izberite veljavno številčenje Minimax.") from exc
        if result <= 0:
            raise MinimaxApiError(f"Za {label} izberite veljavno številčenje Minimax.")
        return result

    def _document_numbering_reference(self, book: str, value: Any) -> dict[str, int] | None:
        if not str(value or "").strip():
            catalog = self.document_numbering_catalog(book)
            return {"ID": int(catalog[0]["id"])} if catalog else None
        selected = self._positive_id(value, f"{book} račun")
        valid = {int(item["id"]) for item in self.document_numbering_catalog(book)}
        if valid and selected not in valid:
            raise MinimaxApiError(f"Številčenje ID {selected} ni aktivno številčenje za knjigo {book}.")
        return {"ID": selected}

    def _item_reference(self, value: Any) -> dict[str, int]:
        catalog = self.item_catalog()
        if not str(value or "").strip():
            if not catalog:
                raise MinimaxApiError(
                    "Minimax za izdani račun zahteva obstoječi artikel, šifrant artiklov pa je prazen. "
                    "V Minimaxu ustvarite artikel (priporočeno tip Storitev) in nato ponovno povežite API."
                )
            return {"ID": int(catalog[0]["id"])}
        selected = self._positive_id(value, "artikel izdanega računa")
        valid = {int(item["id"]) for item in catalog}
        if valid and selected not in valid:
            raise MinimaxApiError(f"Artikel ID {selected} ni aktiven v šifrantu izbrane organizacije.")
        return {"ID": selected}

    @staticmethod
    def _date_plus_days(value: str, days: Any) -> str:
        try:
            count = max(0, min(3650, int(str(days or "0").strip())))
        except ValueError as exc:
            raise MinimaxApiError("Rok plačila mora biti celo število dni.") from exc
        try:
            source = datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise MinimaxApiError(f"Neveljaven datum računa: {value}") from exc
        return (source + timedelta(days=count)).isoformat()

    @staticmethod
    def _party_from_row(book: str, row: Mapping[str, Any]) -> dict[str, str]:
        if book == "IR":
            return {
                "code": str(row.get("P6DS") or row.get("P5") or ""),
                "name": str(row.get("P5") or ""),
                "country": str(row.get("P6") or ""),
                "tax_id": str(row.get("P6DS") or ""),
            }
        return {
            "code": str(row.get("P7DS") or row.get("P6") or ""),
            "name": str(row.get("P6") or ""),
            "country": str(row.get("P7") or ""),
            "tax_id": str(row.get("P7DS") or ""),
        }

    def prepare_issued_invoice_payload(
        self,
        dataset: core.KirkprDataset,
        row: Mapping[str, Any],
        *,
        numbering_id: Any,
        item_id: Any,
        due_days: Any = 8,
        vat_accounting_type: str = "OD",
    ) -> dict[str, Any]:
        metrics = core.ir_metrics(row, dataset.kpr)
        if metrics["tax_only"]:
            raise MinimaxApiError("KIR samoobdavčitev se ne sme ustvariti kot izdani račun; sodi v PR/DDV.")
        issued = str(row.get("P4") or row.get("P2") or "")[:10]
        invoice = str(row.get("P3") or "").strip()
        description = str(row.get("__opis__") or invoice or "KIR uvoz").strip()[:250]
        item_reference = self._item_reference(item_id)
        selected_item = next(
            (item for item in self.item_catalog() if int(item.get("id") or 0) == int(item_reference["ID"])),
            {},
        )
        item_unit = str(selected_item.get("unit") or "kos").strip() or "kos"
        vat_type = vat_accounting_type.strip().upper()
        rates = minimax_xml.issued_invoice_vat_rates(dict(row))
        rows: list[dict[str, Any]] = []
        row_number = 1

        def add_optional_vat_type(invoice_row: dict[str, Any]) -> None:
            # Pri običajnem slovenskem IR Minimax vrsto obračuna določi sam.
            # OD/NI na vrstici lahko povzroči HTTP 409 zaradi neveljavne
            # kombinacije z DDV-stopnjo; izrecno jo pošljemo samo za posebne
            # obravnave (OSS, prodaja na daljavo, gradbeni posel ...).
            if vat_type not in {"", "NI", "OD"}:
                invoice_row["VatAccountingType"] = vat_type

        def add_issued_row(
            code: str,
            base: Decimal,
            vat_amt: Decimal,
            *,
            label: str,
            extra: dict[str, Any] | None = None,
        ) -> None:
            nonlocal row_number
            if base == 0 and vat_amt == 0:
                return
            percent = Decimal(str(RATE_PERCENTAGES.get(code, 0.0)))
            invoice_row: dict[str, Any] = {
                "Item": item_reference,
                "ItemName": f"{description} — {label}"[:250],
                "RowNumber": row_number,
                "Description": description,
                "Quantity": 1.0,
                "UnitOfMeasurement": item_unit,
                "Price": float(base),
                "PriceWithVAT": float(base + vat_amt),
                "VATPercent": float(percent),
                "Discount": 0.0,
                "VatRate": self._vat_rate_reference(code),
                "OtherTaxesAndDuties": "N",
            }
            if extra:
                invoice_row.update(extra)
            add_optional_vat_type(invoice_row)
            rows.append(invoice_row)
            row_number += 1

        for rate in rates:
            code = str(rate.get("code") or "")
            goods_base = core.decimal_value(rate.get("Osnova"))
            goods_vat = core.decimal_value(rate.get("DDV"))
            svc_base = core.decimal_value(rate.get("StoritevOsnova"))
            svc_vat = core.decimal_value(rate.get("StoritevDDV"))
            if code == "O":
                amount = goods_base + svc_base
                add_issued_row(
                    code, amount, Decimal("0"),
                    label="Oproščena dobava",
                    extra={"TaxExemptionValue": float(amount)},
                )
                continue
            if code == "N":
                amount = goods_base + svc_base
                add_issued_row(
                    code, amount, Decimal("0"),
                    label="Neobdavčena dobava",
                    extra={"TaxFreeValue": float(amount)},
                )
                continue
            percent = Decimal(str(RATE_PERCENTAGES.get(code, 0.0)))
            pct_label = str(percent).replace(".", ",")
            if goods_base or goods_vat:
                add_issued_row(
                    code, goods_base, goods_vat,
                    label=f"Blago DDV {pct_label} %",
                )
            if svc_base or svc_vat:
                add_issued_row(
                    code, svc_base, svc_vat,
                    label=f"DDV {pct_label} %",
                )
        if not rows:
            raise MinimaxApiError(f"Izdani račun {invoice or 'brez številke'} nima zneskov za prenos.")
        row_value = sum(
            (
                Decimal(str(item.get("Price") or 0))
                * Decimal(str(item.get("Quantity") or 0))
                - Decimal(str(item.get("Discount") or 0))
                for item in rows
            ),
            Decimal("0"),
        )
        if row_value.quantize(Decimal("0.01")) != Decimal(metrics["net"]).quantize(Decimal("0.01")):
            raise MinimaxApiError(
                f"Vrstice IR niso usklajene z neto zneskom: {row_value:.2f} != {metrics['net']:.2f}."
            )
        payload: dict[str, Any] = {
            "Customer": self._customer_reference(self._party_from_row("IR", row)),
            "DateIssued": issued,
            "DateTransaction": issued,
            "DateDue": self._date_plus_days(issued, due_days),
            "DocumentReference": invoice,
            "Currency": self._reference_by_code("currencies", "EUR"),
            "ExchangeRate": 1.0,
            "Status": "O",
            "DescriptionAbove": description,
            "Notes": f"Uvoženo iz KIR {invoice}; konto {str(row.get('__konto__') or '7601')}",
            "PricesOnInvoice": "N",
            "RecurringInvoice": "N",
            "InvoiceForPeriod": "N",
            "InvoiceType": "R",
            "PaymentStatus": "Osnutek",
            "AssociationWithStock": "N",
            "IssuedInvoiceRows": rows,
        }
        numbering = self._document_numbering_reference("IR", numbering_id)
        if numbering:
            payload["DocumentNumbering"] = numbering
        return payload

    @staticmethod
    def _si_money(value: Decimal | int | float | str) -> str:
        text = f"{Decimal(str(value or 0)):,.2f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def _base_from_vat(vat: Decimal, rate: Decimal) -> Decimal:
        """Osnova = DDV / stopnja (npr. 22 / 0,22 = 100)."""
        amount = Decimal(str(vat or 0))
        pct = Decimal(str(rate or 0))
        if amount == 0 or pct == 0:
            return Decimal("0.00")
        return (amount / pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _format_received_invoice_notes(
        self,
        row: Mapping[str, Any],
        metrics: Mapping[str, Any],
        *,
        description: str,
        expense_account: str,
        supplier_account: str,
        suffix: str,
    ) -> str:
        """Čitljiva opomba: KPR neto + osnove po stopnjah (DDV ÷ stopnja)."""
        vat_22 = Decimal(str(metrics.get("vat_22") or 0))
        vat_95 = Decimal(str(metrics.get("vat_95") or 0))
        vat_5 = Decimal(str(metrics.get("vat_5") or 0))
        net = Decimal(str(metrics.get("net") or 0))
        reported = Decimal(str(metrics.get("reported_vat") or 0))
        lines = [
            f"{description} · uvoženo iz KPR",
            f"konto odhodka {expense_account} · konto dobavitelja {supplier_account} · {suffix}",
            f"KPR neto = {self._si_money(net)} · DDV skupaj = {self._si_money(reported)}",
            "Osnova po stopnji (= DDV ÷ stopnja):",
        ]
        if vat_22 != 0:
            base_22 = self._base_from_vat(vat_22, Decimal("0.22"))
            lines.append(
                f"- osnova 22% = {self._si_money(base_22)} / DDV 22% = {self._si_money(vat_22)}"
            )
        if vat_95 != 0:
            base_95 = self._base_from_vat(vat_95, Decimal("0.095"))
            lines.append(
                f"- osnova 9,5% = {self._si_money(base_95)} / DDV 9,5% = {self._si_money(vat_95)}"
            )
        if vat_5 != 0:
            base_5 = self._base_from_vat(vat_5, Decimal("0.05"))
            lines.append(
                f"- osnova 5% = {self._si_money(base_5)} / DDV 5% = {self._si_money(vat_5)}"
            )
        if vat_22 == 0 and vat_95 == 0 and vat_5 == 0:
            lines.append(
                "- po stopnjah ni razčlenjenega DDV (P18/P19/P20 = 0)"
            )
        return "\n".join(lines)[:1000]

    def prepare_received_invoice_payload(
        self,
        row: Mapping[str, Any],
        *,
        numbering_id: Any,
        due_days: Any = 8,
    ) -> dict[str, Any]:
        metrics = core.pr_metrics(row)
        invoice = str(row.get("P3") or "").strip()
        received = str(row.get("P4") or row.get("P5") or row.get("P2") or "")[:10]
        issued = str(row.get("P5") or received)[:10]
        description = str(row.get("__opis__") or invoice or "KPR uvoz").strip()[:250]
        flags: list[str] = []
        if metrics["self_assessment"]:
            flags.append("samoobdavčitev")
        if not metrics["vat_deductible"]:
            flags.append("DDV se ne odbija")
        suffix = ", ".join(flags) if flags else "običajni PR"
        total = Decimal(metrics["gross"])
        expense_account = core.validate_minimax_account_code(row.get("__konto__") or "4190")
        supplier_account = minimax_xml.supplier_account(str(row.get("P7") or "").strip().upper())
        notes = self._format_received_invoice_notes(
            row,
            metrics,
            description=description,
            expense_account=expense_account,
            supplier_account=supplier_account,
            suffix=suffix,
        )
        payload: dict[str, Any] = {
            "DocumentReference": invoice,
            "Customer": self._customer_reference(self._party_from_row("PR", row)),
            "Currency": self._reference_by_code("currencies", "EUR"),
            "DateIssued": issued,
            "DateTransaction": issued,
            "DateDue": self._date_plus_days(issued, due_days),
            "DateReceived": received,
            "InvoiceAmount": float(total),
            "InvoiceAmountDomesticCurrency": float(total),
            "InvoiceValue": float(total),
            "PaidValue": 0.0,
            "Status": "O",
            "PaymentType": "N",
            "RecurringInvoice": "N",
            "PaymentStatus": "Osnutek",
            "Notes": notes[:1000],
        }
        numbering = self._document_numbering_reference("PR", numbering_id)
        if numbering:
            payload["DocumentNumbering"] = numbering
        return payload

    @staticmethod
    def _link_companion_journal(
        journal_payload: Mapping[str, Any],
        received_invoice_id: int | None,
        document_reference: str,
    ) -> dict[str, Any]:
        """Poveže ločeno osnutno temeljnico s PR-osnutkom brez spremembe knjižbe."""
        linked = copy.deepcopy(dict(journal_payload))
        link = f"PR osnutek ID {received_invoice_id}" if received_invoice_id else f"PR osnutek {document_reference}"
        warning = f"{link}; NE POTRDI OBEH DOKUMENTOV"
        description = str(linked.get("Description") or document_reference or "KPR uvoz")
        linked["Description"] = f"{description} | {warning}"[:250]
        linked["Status"] = "O"
        for entry in linked.get("JournalEntries", []) or []:
            if isinstance(entry, dict):
                entry["Description"] = f"{str(entry.get('Description') or description)} | {link}"[:250]
        for vat_entry in linked.get("VatEntries", []) or []:
            if isinstance(vat_entry, dict):
                vat_entry["Notes"] = warning[:250]
        return linked

    def _send_received_invoice_with_optional_journal(
        self,
        payload: Mapping[str, Any],
        companion_journal: Mapping[str, Any] | None,
    ) -> ApiResponse:
        """Vedno ustvari PR-osnutek; opcijska knjižba ostane ločen osnutek."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        invoice_payload = copy.deepcopy(dict(payload))
        invoice_response = self.post(
            f"orgs/{self.organisation_id}/receivedinvoices",
            invoice_payload,
        )
        if not companion_journal:
            return invoice_response
        received_id = self._response_record_id(invoice_response, "ReceivedInvoiceId")
        document = str(invoice_payload.get("DocumentReference") or "")
        linked_journal = self._link_companion_journal(companion_journal, received_id, document)
        try:
            journal_response = self._send_journal_with_vat(linked_journal)
        except Exception as exc:
            # PR je že nastal. Vrstico obravnavamo kot oddano, da ponovni klik ne
            # ustvari dvojnika; opozorilo ostane vidno v rezultatu.
            pr_location = invoice_response.location or (
                f"receivedinvoices/{received_id}" if received_id else "PR osnutek"
            )
            return ApiResponse(
                status=207,
                location=f"{pr_location} • PR USTVARJEN; spremljevalna temeljnica ni uspela: {exc}",
                body={
                    "ReceivedInvoiceId": received_id,
                    "CompanionJournalCreated": False,
                    "Warning": str(exc),
                },
            )
        journal_id = self._response_record_id(journal_response, "JournalId")
        pr_location = invoice_response.location or (
            f"receivedinvoices/{received_id}" if received_id else "PR osnutek"
        )
        journal_location = journal_response.location or (
            f"journals/{journal_id}" if journal_id else "temeljnica"
        )
        return ApiResponse(
            status=invoice_response.status,
            location=(
                f"PR {pr_location} • osnutna temeljnica {journal_location} • "
                "POZOR: v Minimaxu potrdite samo en dokument"
            ),
            body={
                "ReceivedInvoiceId": received_id,
                "JournalId": journal_id,
                "VatEntriesAdded": (
                    journal_response.body.get("VatEntriesAdded", 0)
                    if isinstance(journal_response.body, Mapping)
                    else 0
                ),
                "CompanionJournalCreated": True,
            },
        )

    @staticmethod
    def _response_record_id(response: ApiResponse, *keys: str) -> int | None:
        body = response.body if isinstance(response.body, Mapping) else {}
        record_id = _record_id(body)
        if record_id is not None:
            return record_id
        for key in keys:
            try:
                candidate = int(body.get(key) or 0)
            except (TypeError, ValueError):
                candidate = 0
            if candidate > 0:
                return candidate
        location_match = re.search(r"/(\d+)(?:/)?(?:\?.*)?$", response.location or "")
        return int(location_match.group(1)) if location_match else None

    def scrub_vat_document_prefixes(self, journal_id: int) -> int:
        """Če Minimax v Document vstavi »Obracun;…«, ga odstrani z PUT. Vrne št. popravkov."""
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        try:
            detail = self.get(f"orgs/{self.organisation_id}/journals/{int(journal_id)}")
        except Exception:
            return 0
        if not isinstance(detail, Mapping):
            return 0
        fixed = 0
        for vat in detail.get("VatEntries") or []:
            if not isinstance(vat, Mapping):
                continue
            vid = vat.get("VatEntryId") or vat.get("ID") or vat.get("Id")
            if not vid:
                continue
            raw_doc = str(vat.get("Document") or "")
            clean_doc = _clean_vat_document(raw_doc)
            notes_text = str(vat.get("Notes") or "").strip()
            notes_folded = notes_text.casefold().replace("č", "c").replace("ć", "c")
            notes_dirty = bool(
                notes_text
                and (
                    _VAT_DOC_PREFIX_RE.match(notes_text)
                    or notes_folded in {"obracun", "samoprijava", "samoprijavaobresti"}
                    or notes_folded.startswith("obracun;")
                    or notes_folded.startswith("samoprijava;")
                )
            )
            if clean_doc == raw_doc.strip() and not notes_dirty:
                continue
            payload = copy.deepcopy(dict(vat))
            payload["Document"] = clean_doc
            if notes_dirty:
                payload["Notes"] = None
            # ReportingType ne pošiljaj znova — enkrat nastavljenega API ne zbriše.
            payload.pop("ReportingType", None)
            try:
                self.put(
                    f"orgs/{self.organisation_id}/journals/{int(journal_id)}/vat/{int(vid)}",
                    payload,
                )
                fixed += 1
            except Exception:
                continue
        return fixed

    def _send_journal_with_vat(self, payload: Mapping[str, Any]) -> ApiResponse:
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        journal_payload = copy.deepcopy(dict(payload))
        vat_entries = list(journal_payload.pop("VatEntries", []) or [])
        # Listina čista; Notes = interna št. (sicer knjiga PR v stolpcu 4 pokaže »Obracun;…«).
        # ReportingType ne pošiljaj — PUT z Notes ga sicer nastavi na Obracun.
        for vat_entry in vat_entries:
            if not isinstance(vat_entry, dict):
                continue
            if vat_entry.get("Document") is not None:
                vat_entry["Document"] = _clean_vat_document(vat_entry.get("Document"))
            vat_entry.pop("ReportingType", None)
            notes = str(vat_entry.get("Notes") or "").strip()
            if notes:
                vat_entry["Notes"] = notes[:250]
            else:
                vat_entry.pop("Notes", None)
        requested_status = str(journal_payload.get("Status") or "O").upper()
        if vat_entries and requested_status == "P":
            # DDV se na potrjeno temeljnico praviloma ne sme več dodajati.
            journal_payload["Status"] = "O"
        journal_response = self.post(f"orgs/{self.organisation_id}/journals", journal_payload)
        if not vat_entries:
            return journal_response
        journal_id = self._response_record_id(journal_response, "JournalId")
        if journal_id is None:
            raise MinimaxApiError(
                "Temeljnica je bila ustvarjena, vendar API ni vrnil njenega ID. "
                "DDV ni bil dodan; preverite zadnjo temeljnico v Minimaxu."
            )
        try:
            for vat_entry in vat_entries:
                vat_payload = copy.deepcopy(dict(vat_entry))
                vat_payload["Journal"] = {"ID": journal_id}
                vat_payload["Document"] = _clean_vat_document(vat_payload.get("Document"))
                vat_payload.pop("ReportingType", None)
                notes = str(vat_payload.get("Notes") or "").strip()
                if notes:
                    vat_payload["Notes"] = notes[:250]
                else:
                    vat_payload.pop("Notes", None)
                self.post(
                    f"orgs/{self.organisation_id}/journals/{journal_id}/vat",
                    vat_payload,
                )
            try:
                self.scrub_vat_document_prefixes(int(journal_id))
            except Exception:
                pass
            created = self.get(f"orgs/{self.organisation_id}/journals/{journal_id}")
            created_vat = created.get("VatEntries") if isinstance(created, Mapping) else None
            if isinstance(created_vat, list) and len(created_vat) < len(vat_entries):
                raise MinimaxApiError(
                    f"Minimax je vrnil samo {len(created_vat)} od {len(vat_entries)} DDV-vrstic."
                )
            if requested_status == "P":
                if not isinstance(created, Mapping):
                    raise MinimaxApiError("Potrditve ni mogoče izvesti, ker API ni vrnil ustvarjene temeljnice.")
                confirmed_payload = copy.deepcopy(dict(created))
                confirmed_payload["Status"] = "P"
                self.put(f"orgs/{self.organisation_id}/journals/{journal_id}", confirmed_payload)
        except Exception as exc:
            raise MinimaxApiError(
                f"Temeljnica ID {journal_id} je ustvarjena, DDV pa ni bil v celoti dodan: {exc} "
                "Dokument preverite v Minimaxu; program ga zaradi varnosti ne briše samodejno."
            ) from exc
        return ApiResponse(
            status=journal_response.status,
            location=journal_response.location or f"journals/{journal_id}",
            body={"JournalId": journal_id, "VatEntriesAdded": len(vat_entries)},
        )

    def root_for_row(self, dataset: core.KirkprDataset, book: str, row: Mapping[str, Any]) -> etree._Element:
        if book.upper() == "IR":
            root, _audit = minimax_xml.build_issued([copy.deepcopy(dict(row))], copy.deepcopy(dataset.kpr))
        elif book.upper() == "PR":
            root, _audit = minimax_xml.build_received([copy.deepcopy(dict(row))])
        else:
            raise MinimaxApiError(f"Nepodprta knjiga za API: {book}")
        return root

    def preflight_row(
        self,
        dataset: core.KirkprDataset,
        book: str,
        row: Mapping[str, Any],
        status: str = "O",
        *,
        mode: str = "journal",
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected = dict(options or {})
        kind = book.upper()
        if mode == "invoice":
            if kind == "IR":
                return self.prepare_issued_invoice_payload(
                    dataset,
                    row,
                    numbering_id=selected.get("numbering_ir_id"),
                    item_id=selected.get("item_ir_id"),
                    due_days=selected.get("due_days", 8),
                    vat_accounting_type=str(selected.get("vat_type_ir") or "OD"),
                )
            if kind == "PR":
                received_payload = self.prepare_received_invoice_payload(
                    row,
                    numbering_id=selected.get("numbering_pr_id"),
                    due_days=selected.get("due_days", 8),
                )
                if selected.get("pr_companion_journal"):
                    journal_payload = self.prepare_journal_payload(
                        self.root_for_row(dataset, book, row),
                        status="O",
                        vat_type_ir=str(selected.get("vat_type_ir") or "OD"),
                        vat_type_pr=str(selected.get("vat_type_pr") or ""),
                    )
                    return {
                        "ReceivedInvoice": received_payload,
                        "CompanionJournal": journal_payload,
                    }
                return received_payload
            raise MinimaxApiError(f"Nepodprta knjiga za API: {book}")
        return self.prepare_journal_payload(
            self.root_for_row(dataset, book, row),
            status=status,
            vat_type_ir=str(selected.get("vat_type_ir") or "OD"),
            vat_type_pr=str(selected.get("vat_type_pr") or ""),
        )

    def _assert_unique_document_reference(
        self,
        book: str,
        row: Mapping[str, Any],
        *,
        existing_refs: Mapping[str, Mapping[str, Any]] | None = None,
        seen_batch: set[tuple[str, str]] | None = None,
    ) -> None:
        """Zavrže oddajo, če listina (DocumentReference) že obstaja v Minimaxu ali v paketu."""
        kind = str(book or "").strip().upper()
        invoice = str(row.get("P3") or "").strip()
        reference = normal_invoice_reference(invoice)
        if not reference:
            raise MinimaxApiError("Manjka vezna številka (listina / DocumentReference).")
        batch_key = (kind, reference)
        if seen_batch is not None:
            if batch_key in seen_batch:
                raise MinimaxApiError(
                    f"Listina {invoice} je v tem paketu podvojena — v Minimaxu se ne sme podvajati."
                )
            seen_batch.add(batch_key)
        if existing_refs:
            book_refs = existing_refs.get(kind) or {}
            if reference in book_refs:
                status = book_refs.get(reference) or "obstaja"
                raise MinimaxApiError(
                    f"Listina {invoice} že obstaja v Minimaxu ({status}). "
                    "Podvajanje vezne številke ni dovoljeno."
                )

    def send_row(
        self,
        dataset: core.KirkprDataset,
        book: str,
        row: Mapping[str, Any],
        status: str = "O",
        *,
        mode: str = "journal",
        options: Mapping[str, Any] | None = None,
    ) -> ApiResponse:
        if self.organisation_id is None:
            raise MinimaxApiError("Najprej izberite Minimax organizacijo.")
        selected = dict(options or {})
        existing_refs = selected.get("existing_refs")
        if isinstance(existing_refs, Mapping):
            self._assert_unique_document_reference(book, row, existing_refs=existing_refs)
        payload = self.preflight_row(dataset, book, row, status=status, mode=mode, options=options)
        if mode == "invoice":
            if book.upper() == "PR":
                if "ReceivedInvoice" in payload:
                    return self._send_received_invoice_with_optional_journal(
                        payload["ReceivedInvoice"],
                        payload.get("CompanionJournal"),
                    )
                return self._send_received_invoice_with_optional_journal(payload, None)
            return self.post(f"orgs/{self.organisation_id}/issuedinvoices", payload)
        return self._send_journal_with_vat(payload)

    def validate_rows(
        self,
        dataset: core.KirkprDataset,
        selections: Iterable[tuple[str, Mapping[str, Any]]],
        *,
        status: str = "O",
        mode: str = "journal",
        options: Mapping[str, Any] | None = None,
        progress: Callable[[str, str, str], None] | None = None,
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        selected = dict(options or {})
        existing_refs = selected.get("existing_refs") if isinstance(selected.get("existing_refs"), Mapping) else None
        seen_batch: set[tuple[str, str]] = set()
        for book, row in selections:
            invoice = str(row.get("P3") or "brez številke")
            try:
                self._assert_unique_document_reference(
                    book,
                    row,
                    existing_refs=existing_refs if isinstance(existing_refs, Mapping) else None,
                    seen_batch=seen_batch,
                )
                self.preflight_row(dataset, book, row, status=status, mode=mode, options=options)
                if mode == "invoice" and book.upper() == "PR" and selected.get("pr_companion_journal"):
                    detail = "Pripravljen PR-osnutek + ločena osnutna temeljnica z odhodkom in DDV"
                else:
                    detail = "Pripravljen osnutek računa" if mode == "invoice" else "Pripravljena temeljnica + DDV"
                state = "OK"
            except Exception as exc:
                state, detail = "NAPAKA", str(exc)
            results.append({"book": book, "invoice": invoice, "status": state, "detail": detail})
            if progress:
                progress(book, invoice, f"{state}: {detail}")
        return results


__all__ = [
    "ApiResponse",
    "ApiSettings",
    "MinimaxApiError",
    "MinimaxClient",
    "resolve_settings_path",
    "shared_settings_candidates",
]
