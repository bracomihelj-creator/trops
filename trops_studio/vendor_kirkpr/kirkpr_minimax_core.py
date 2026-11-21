"""Poslovna logika za pretvorbo FURS KIR/KPR v Minimax XML.

Modul je brez grafičnega vmesnika. Podpira neposredne datoteke in ZIP-e, v
katerih je KIR/KPR zapisan kot JSON, XML ali CSV. Grafični program
``convert_KIrKpr_to_minimax.py`` uporablja vse funkcije iz tega modula.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from xml.etree import ElementTree as StdET

from lxml import etree

import convert_ddv_json_to_minimax as minimax_xml


SUPPORTED_SUFFIXES = {".zip", ".json", ".xml", ".csv"}
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
EURO = Decimal("1")
DEFAULT_CONFIG_NAME = "convert_KIrKpr_to_minimax_config.json"

# Oznake usklajene z eDavki obrazcem e-DDV_O_11.7 (glej ddvo_obrazec_eDDV_O_11.7.json).
DDVO_FIELD_DEFINITIONS = (
    ("I. Dobave blaga in storitev", "11", "Dobava blaga in storitev", "KIR", ("P7",)),
    ("I. Dobave blaga in storitev", "11a", "Dobava blaga in storitev v Sloveniji od katerih obračuna DDV prejemnik", "KIR", ("P8",)),
    ("I. Dobave blaga in storitev", "12", "Dobave blaga in storitev v druge države članice EU", "KIR", ("P10", "P11")),
    ("I. Dobave blaga in storitev", "13", "Prodaja blaga na daljavo", "KIR", ("P12",)),
    ("I. Dobave blaga in storitev", "14", "Montaža in instaliranje blaga v drugi državi članici", "KIR", ("P13",)),
    ("I. Dobave blaga in storitev", "15", "Oproščene dobave brez pravice do odbitka DDV", "KIR", ("P9",)),
    ("II. Obračunani DDV", "21", "po stopnji 22,00%", "KIR", ("P14",)),
    ("II. Obračunani DDV", "22", "po stopnji 9,50%", "KIR", ("P15",)),
    ("II. Obračunani DDV", "22a", "po stopnji 5,00%", "KIR", ("P16",)),
    ("II. Obračunani DDV", "23", "od pridobitev blaga iz EU po 22,00%", "KIR", ("P17",)),
    ("II. Obračunani DDV", "23a", "od prejetih storitev iz EU po 22,00%", "KIR", ("P18",)),
    ("II. Obračunani DDV", "24", "od pridobitev blaga iz EU po 9,50%", "KIR", ("P19",)),
    ("II. Obračunani DDV", "24a", "od prejetih storitev iz EU po 9,50%", "KIR", ("P20",)),
    ("II. Obračunani DDV", "24b", "od pridobitev blaga iz EU po 5,00%", "KIR", ("P21",)),
    ("II. Obračunani DDV", "24c", "od prejetih storitev iz EU po 5,00%", "KIR", ("P22",)),
    ("II. Obračunani DDV", "25", "samoobdavčitev prejemnika po 22,00%", "KIR", ("P23",)),
    ("II. Obračunani DDV", "25a", "samoobdavčitev prejemnika po 9,50%", "KIR", ("P24",)),
    ("II. Obračunani DDV", "25b", "samoobdavčitev prejemnika po 5,00%", "KIR", ("P25",)),
    ("II. Obračunani DDV", "26", "samoobdavčitev od uvoza", "KIR", ("P26",)),
    ("III. Nabave blaga in storitev", "31", "Nabave blaga in storitev", "KPR", ("P8",)),
    ("III. Nabave blaga in storitev", "31a", "Nabave blaga in storitev v Sloveniji od katerih obračuna DDV prejemnik", "KPR", ("P9",)),
    ("III. Nabave blaga in storitev", "32", "Pridobitve blaga iz drugih držav članic EU", "KPR", ("P10",)),
    ("III. Nabave blaga in storitev", "32a", "Prejete storitve iz drugih držav članic EU", "KPR", ("P11",)),
    ("III. Nabave blaga in storitev", "33", "Oproščene nabave blaga in storitve in oproščene pridobitve blaga", "KPR", ("P14",)),
    ("III. Nabave blaga in storitev", "34", "Nabavna vrednost nepremičnin", "KPR", ("P12", "P15")),
    ("III. Nabave blaga in storitev", "35", "Nabavna vrednost drugih osnovnih sredstev", "KPR", ("P13", "P16")),
    ("IV. Odbitek DDV", "41", "od nabav / pridobitev / uvoza po 22,00%", "KPR", ("P18",)),
    ("IV. Odbitek DDV", "42", "od nabav / pridobitev / uvoza po 9,50%", "KPR", ("P19",)),
    ("IV. Odbitek DDV", "42a", "od nabav / pridobitev / uvoza po 5,00%", "KPR", ("P20",)),
    ("IV. Odbitek DDV", "43", "od pavšalnega nadomestila po stopnji 8%", "KPR", ("P21",)),
)


def ddvo_codes_for_field(book: str, field_name: str) -> tuple[str, ...]:
    """Vrne polja DDV-O, v katera se neposredno sešteva izbrano polje KIR/KPR."""
    evidence = "KIR" if str(book).upper() in {"IR", "KIR"} else "KPR"
    field = str(field_name or "").strip().upper()
    return tuple(
        code
        for _section, code, _label, source_book, source_fields in DDVO_FIELD_DEFINITIONS
        if source_book == evidence and field in source_fields
    )


def load_ddvo_form_layout() -> dict[str, Any]:
    """Struktura obrazca eDavki e-DDV_O_11.7 (za UI / izvoz)."""
    path = Path(__file__).with_name("ddvo_obrazec_eDDV_O_11.7.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"form": "DDV-O", "version": "e-DDV_O_11.7", "sections": []}


class KirkprError(RuntimeError):
    """Napaka, primerna za prikaz uporabniku."""


@dataclass
class KirkprDataset:
    header: dict[str, Any]
    kir: list[dict[str, Any]]
    kpr: list[dict[str, Any]]
    source_path: Path
    source_format: str
    source_members: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def period_from(self) -> str:
        return str(self.header.get("OBDOBJE_OD") or "")[:10]

    @property
    def period_to(self) -> str:
        return str(self.header.get("OBDOBJE_DO") or "")[:10]


@dataclass(frozen=True)
class ParsedCandidate:
    header: dict[str, Any]
    kir: list[dict[str, Any]]
    kpr: list[dict[str, Any]]
    format_name: str
    member_name: str
    warnings: tuple[str, ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.kir) + len(self.kpr)


@dataclass(frozen=True)
class ExportResult:
    issued_xml: Path
    received_xml: Path
    report: Path
    archive: Path
    issued_count: int
    received_count: int
    tax_only_kir_count: int
    xsd_validated: bool


def decimal_value(value: Any) -> Decimal:
    """Pretvori tudi slovenski zapis 1.234,56 v Decimal."""
    if value in (None, ""):
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return ZERO
    text = re.sub(r"[^0-9,\.\-+]", "", text)
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
        raise KirkprError(f"Neveljaven znesek: {value!r}") from exc


def decimal_text(value: Any) -> str:
    return f"{decimal_value(value):.2f}"


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text[:10]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def _canonical_field(name: Any) -> str:
    text = str(name or "").replace("\ufeff", "").strip().upper()
    text = re.sub(r"\s+", "_", text)
    aliases = {
        "ZAP._ST.": "ZAPST",
        "ZAP_ST": "ZAPST",
        "ZAPOREDNA_STEVILKA": "ZAPST",
        "DAVCNO_OBDOBJE": "OBDOBJE",
        "BOOK": "KNJIGA",
        "TIP": "KNJIGA",
        "VRSTA": "KNJIGA",
    }
    return aliases.get(text, text)


def _normalize_row(row: Mapping[str, Any], book: str) -> dict[str, Any]:
    clean = {_canonical_field(key): value for key, value in row.items() if key is not None}
    numeric_fields = (
        {f"P{index}" for index in range(7, 28)}
        if book == "KIR"
        else {f"P{index}" for index in range(8, 22)}
    )
    out: dict[str, Any] = {}
    for key, value in clean.items():
        if key in {"P2", "P4"} or (book == "KPR" and key == "P5"):
            out[key] = normalize_date(value)
        elif key == "ZAPST":
            try:
                out[key] = int(decimal_value(value))
            except KirkprError:
                out[key] = int(str(value or "0").strip() or 0)
        elif key in numeric_fields:
            out[key] = decimal_text(value)
        else:
            out[key] = str(value or "").strip() if value is not None else ""

    out.setdefault("ZAPST", 0)
    out.setdefault("OBRAVNAVA", "1")
    if book == "KIR":
        out.setdefault("P6DS", "")
        for index in range(7, 28):
            out.setdefault(f"P{index}", "0.00")
    else:
        out.setdefault("P7DS", "")
        for index in range(8, 22):
            out.setdefault(f"P{index}", "0.00")
    return out


def _normalize_header(header: Mapping[str, Any], kir: Sequence[dict], kpr: Sequence[dict]) -> dict[str, Any]:
    clean = {_canonical_field(key): value for key, value in header.items()}
    start = normalize_date(clean.get("OBDOBJE_OD"))
    end = normalize_date(clean.get("OBDOBJE_DO"))
    dates: list[str] = []
    for row in list(kir) + list(kpr):
        for field_name in ("P2", "P4", "P5"):
            candidate = normalize_date(row.get(field_name))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
                dates.append(candidate)
    if not start and dates:
        start = min(dates)
    if not end and dates:
        end = max(dates)
    def as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "da", "yes"}
        return bool(value)

    return {
        "TaxPayerID": str(clean.get("TAXPAYERID") or clean.get("DAVCNA") or "").strip(),
        "OBDOBJE_OD": start or "2000-01-01",
        "OBDOBJE_DO": end or "2000-01-01",
        "KIR": bool(kir),
        "KPR": bool(kpr),
        "ODBDELEZ": as_bool(clean.get("ODBDELEZ", False)),
        "VRACILO": as_bool(clean.get("VRACILO", False)),
        "INSPOS": as_bool(clean.get("INSPOS", False)),
        "PREDLODO": as_bool(clean.get("PREDLODO", False)),
        "OPOMBA": str(clean.get("OPOMBA") or "").strip(),
    }


def _decode_text(data: bytes) -> str:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "windows-1250", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(str(exc))
    raise KirkprError("Datoteke ni mogoče prebrati v podprtem znakovnem naboru: " + "; ".join(errors[:2]))


def _unwrap_json(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KirkprError("JSON koren mora biti objekt.")
    if "DDV_KIR_KPR" in value and isinstance(value["DDV_KIR_KPR"], Mapping):
        return value["DDV_KIR_KPR"]
    return value


def parse_json_bytes(data: bytes, member_name: str = "podatki.json") -> ParsedCandidate:
    try:
        payload = _unwrap_json(json.loads(_decode_text(data)))
    except (json.JSONDecodeError, TypeError) as exc:
        raise KirkprError(f"Neveljaven JSON ({member_name}): {exc}") from exc
    header = payload.get("Glava") or payload.get("GLAVA") or {}
    kir_value = payload.get("Lista_KIR") or payload.get("LISTA_KIR") or payload.get("KIR") or {}
    kpr_value = payload.get("Lista_KPR") or payload.get("LISTA_KPR") or payload.get("KPR") or {}
    kir_rows = kir_value.get("KIR", []) if isinstance(kir_value, Mapping) else kir_value
    kpr_rows = kpr_value.get("KPR", []) if isinstance(kpr_value, Mapping) else kpr_value
    kir = [_normalize_row(row, "KIR") for row in (kir_rows or []) if isinstance(row, Mapping)]
    kpr = [_normalize_row(row, "KPR") for row in (kpr_rows or []) if isinstance(row, Mapping)]
    if not kir and not kpr:
        raise KirkprError(f"JSON {member_name} ne vsebuje Lista_KIR/KIR ali Lista_KPR/KPR.")
    return ParsedCandidate(_normalize_header(header, kir, kpr), kir, kpr, "JSON", member_name)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children_as_dict(element: StdET.Element) -> dict[str, Any]:
    return {_local_name(child.tag): (child.text or "").strip() for child in list(element)}


def parse_xml_bytes(data: bytes, member_name: str = "podatki.xml") -> ParsedCandidate:
    try:
        root = StdET.fromstring(data)
    except StdET.ParseError as exc:
        raise KirkprError(f"Neveljaven XML ({member_name}): {exc}") from exc
    if _local_name(root.tag).upper() != "DDV_KIR_KPR":
        raise KirkprError(f"XML {member_name} ni FURS DDV_KIR_KPR.")
    header: dict[str, Any] = {}
    kir: list[dict[str, Any]] = []
    kpr: list[dict[str, Any]] = []
    for element in root.iter():
        local = _local_name(element.tag)
        if local == "Glava":
            header = _children_as_dict(element)
        elif local == "KIR" and _local_name(root.tag) != "KIR":
            values = _children_as_dict(element)
            if values:
                kir.append(_normalize_row(values, "KIR"))
        elif local == "KPR" and _local_name(root.tag) != "KPR":
            values = _children_as_dict(element)
            if values:
                kpr.append(_normalize_row(values, "KPR"))
    if not kir and not kpr:
        raise KirkprError(f"XML {member_name} nima vrstic KIR ali KPR.")
    return ParsedCandidate(_normalize_header(header, kir, kpr), kir, kpr, "XML", member_name)


def _detect_delimiter(text: str) -> str:
    sample = text[:12000]
    lines = [line for line in sample.splitlines() if line.strip()][:8]
    # FURS eDavki CSV vedno uporablja ; — sniffer ga sicer zamenja z vejico.
    if lines:
        first = lines[0]
        if first.count(";") >= 4 and first.count(";") > first.count(","):
            return ";"
        if any(line.upper().startswith(("KIR;", "KPR;", "IR;", "PR;")) for line in lines):
            return ";"
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,|\t").delimiter
    except csv.Error:
        first = next((line for line in text.splitlines() if "ZAP" in line.upper()), "")
        counts = {delimiter: first.count(delimiter) for delimiter in (";", ",", "\t", "|")}
        return max(counts, key=counts.get) if any(counts.values()) else ";"


def _book_from_value(value: Any) -> str:
    text = str(value or "").strip().upper().replace(" ", "")
    if text in {"IR", "KIR", "IZDANI", "IZDANIRACUNI"}:
        return "KIR"
    if text in {"PR", "KPR", "PREJETI", "PREJETIRACUNI"}:
        return "KPR"
    return ""


# FURS eDavki CSV brez imen stolpcev (prva vrstica = glava, nato KIR/KPR).
_FURS_CSV_KIR_FIELDS = (
    "ZAPST",
    "OBDOBJE",
    "P2",
    "P3",
    "P4",
    "P5",
    "P6",
    "P6DS",
    *(f"P{index}" for index in range(7, 28)),
)
_FURS_CSV_KPR_FIELDS = (
    "ZAPST",
    "OBDOBJE",
    "P2",
    "P3",
    "P4",
    "P5",
    "P6",
    "P7",
    "P7DS",
    *(f"P{index}" for index in range(8, 22)),
)


def _parse_furs_csv_header_line(parts: Sequence[str]) -> dict[str, Any] | None:
    """Glava FURS CSV: davčna;;;OBDOBJE_OD;OBDOBJE_DO;KIR;KPR;…"""
    if len(parts) < 5:
        return None
    tax = str(parts[0] or "").strip()
    start = normalize_date(parts[3])
    end = normalize_date(parts[4])
    if not (tax.isdigit() and len(tax) >= 8):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        return None
    return {
        "TaxPayerID": tax,
        "OBDOBJE_OD": start,
        "OBDOBJE_DO": end,
        "KIR": parts[5] if len(parts) > 5 else "",
        "KPR": parts[6] if len(parts) > 6 else "",
        "VRACILO": parts[7] if len(parts) > 7 else "",
        "ODBDELEZ": parts[8] if len(parts) > 8 else "",
        "INSPOS": parts[10] if len(parts) > 10 else "",
        "PREDLODO": parts[11] if len(parts) > 11 else "",
        "OPOMBA": parts[12] if len(parts) > 12 else "",
    }


def _row_from_furs_csv_parts(parts: Sequence[str]) -> tuple[str, dict[str, Any]] | None:
    book = _book_from_value(parts[0] if parts else "")
    if not book or len(parts) < 9:
        return None
    fields = _FURS_CSV_KIR_FIELDS if book == "KIR" else _FURS_CSV_KPR_FIELDS
    values = list(parts[1 : 1 + len(fields)])
    while len(values) < len(fields):
        values.append("")
    row = {name: values[index] for index, name in enumerate(fields)}
    # Trailing OBRAVNAVA (za zneski / praznimi polji).
    trail_index = 1 + len(fields)
    if len(parts) > trail_index + 1:
        maybe_obravnava = str(parts[trail_index + 1] or "").strip()
        if maybe_obravnava in {"0", "1", "2"}:
            row["OBRAVNAVA"] = maybe_obravnava
    elif len(parts) > trail_index:
        maybe_obravnava = str(parts[trail_index] or "").strip()
        if maybe_obravnava in {"0", "1", "2"}:
            row["OBRAVNAVA"] = maybe_obravnava
    return book, row


def parse_csv_bytes(data: bytes, member_name: str = "podatki.csv") -> ParsedCandidate:
    text = _decode_text(data)
    delimiter = _detect_delimiter(text)
    lines = [line for line in text.splitlines() if str(line or "").strip()]
    if not lines:
        raise KirkprError(f"CSV {member_name} je prazen.")

    # 1) FURS eDavki CSV: glava z davčno + obdobjem, vrstice KIR;/KPR; brez imen stolpcev.
    header_guess = _parse_furs_csv_header_line(lines[0].split(delimiter))
    data_start = 0
    furs_header: dict[str, Any] = {}
    if header_guess is not None:
        furs_header = header_guess
        data_start = 1
    elif _book_from_value(lines[0].split(delimiter)[0]):
        data_start = 0
    else:
        header_guess = None

    if header_guess is not None or (data_start == 0 and _book_from_value(lines[0].split(delimiter)[0])):
        kir: list[dict[str, Any]] = []
        kpr: list[dict[str, Any]] = []
        for line in lines[data_start:]:
            parts = line.split(delimiter)
            parsed = _row_from_furs_csv_parts(parts)
            if not parsed:
                continue
            book, raw = parsed
            normalized = _normalize_row(raw, book)
            (kir if book == "KIR" else kpr).append(normalized)
        if kir or kpr:
            header = _normalize_header(furs_header, kir, kpr)
            return ParsedCandidate(header, kir, kpr, "CSV", member_name)
        if header_guess is not None:
            raise KirkprError(f"CSV {member_name} ima FURS glavo, a nima vrstic KIR/KPR.")

    # 2) Klasični CSV z glavo stolpcev (ZAPST / P2 / P3 …).
    header_index = 0
    for index, line in enumerate(lines[:30]):
        upper = line.upper()
        if "ZAPST" in upper or ("P2" in upper and "P3" in upper):
            header_index = index
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
    if not reader.fieldnames:
        raise KirkprError(f"CSV {member_name} nima glave stolpcev.")
    fields = {_canonical_field(field) for field in reader.fieldnames}
    filename_book = "KPR" if "KPR" in member_name.upper() else "KIR" if "KIR" in member_name.upper() else ""
    inferred_book = filename_book
    if "P7DS" in fields:
        inferred_book = "KPR"
    elif "P6DS" in fields:
        inferred_book = "KIR"

    kir = []
    kpr = []
    for raw in reader:
        canonical = {_canonical_field(key): value for key, value in raw.items() if key is not None}
        if not any(str(value or "").strip() for value in canonical.values()):
            continue
        book = ""
        for field_name in ("KNJIGA", "BOOK", "TIP", "VRSTA"):
            book = _book_from_value(canonical.get(field_name))
            if book:
                break
        book = book or inferred_book
        if not book:
            raise KirkprError(
                f"CSV {member_name}: ni mogoče ugotoviti KIR/KPR. Dodajte stolpec KNJIGA ali P6DS/P7DS."
            )
        normalized = _normalize_row(canonical, book)
        (kir if book == "KIR" else kpr).append(normalized)
    if not kir and not kpr:
        raise KirkprError(f"CSV {member_name} nima podatkovnih vrstic.")
    header = _normalize_header({}, kir, kpr)
    return ParsedCandidate(header, kir, kpr, "CSV", member_name)


def parse_member(data: bytes, member_name: str) -> ParsedCandidate:
    suffix = Path(member_name).suffix.lower()
    if suffix == ".json":
        return parse_json_bytes(data, member_name)
    if suffix == ".xml":
        return parse_xml_bytes(data, member_name)
    if suffix == ".csv":
        return parse_csv_bytes(data, member_name)
    raise KirkprError(f"Nepodprt format: {member_name}")


def _row_identity(book: str, row: Mapping[str, Any]) -> tuple[str, ...]:
    tax_field = "P6DS" if book == "KIR" else "P7DS"
    return (
        str(row.get("P3") or ""),
        str(row.get("P2") or ""),
        str(row.get("P4") or ""),
        str(row.get("P5") or ""),
        str(row.get(tax_field) or ""),
        str(row.get("ZAPST") or ""),
    )


def _dedupe(book: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(book, row)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(row)
    return result


def _normalize_preferred_format(preferred_format: str | None) -> str:
    """Vrne all|json|xml|csv (zip = all, ker ZIP vsebuje te formate)."""
    choice = str(preferred_format or "all").strip().casefold()
    if choice in {"json", "xml", "csv"}:
        return choice
    return "all"


def _merge_candidates(
    candidates: Sequence[ParsedCandidate],
    *,
    preferred_format: str | None = None,
) -> tuple[ParsedCandidate, list[str], list[str]]:
    """Združi člane ZIP po pravilih NAVODIL.

    Pravila:
    1. V ZIP-u so dovoljeni JSON, XML in CSV (skupaj ali ločeno KIR/KPR).
    2. Prednostni format (če je nastavljen in na voljo) omeji izbor nanj.
    3. Sicer: najpopolnejši vir (več vrstic, obe knjigi), nato JSON > XML > CSV.
    4. Manjkajoči KIR ali KPR se dopolni iz drugega člana ZIP-a.
    """
    if not candidates:
        raise KirkprError("V ZIP-u ni uporabnega JSON, XML ali CSV KIR/KPR.")
    warnings: list[str] = []
    preferred = _normalize_preferred_format(preferred_format)
    pool: list[ParsedCandidate] = list(candidates)
    preferred_applied = False
    if preferred != "all":
        wanted = preferred.upper()
        filtered = [item for item in candidates if item.format_name.upper() == wanted]
        if filtered:
            pool = filtered
            preferred_applied = True
        else:
            warnings.append(
                f"Prednostni format {wanted} v ZIP-u ni na voljo — uporabljen je najpopolnejši drug vir."
            )
    priority = {"JSON": 3, "XML": 2, "CSV": 1}
    primary = max(
        pool,
        key=lambda item: (
            item.row_count,
            int(bool(item.kir) and bool(item.kpr)),
            priority.get(item.format_name.upper(), 0),
        ),
    )
    used = [primary]
    kir = list(primary.kir)
    kpr = list(primary.kpr)
    # Najprej dopolni iz istega formata (npr. KIR.csv + KPR.csv), nato iz ostalih.
    fill_order: list[list[ParsedCandidate]] = [pool]
    if preferred_applied:
        fill_order.append(list(candidates))

    def _fill_book(book: str) -> None:
        nonlocal kir, kpr
        current = kir if book == "KIR" else kpr
        if current:
            return
        for group in fill_order:
            supplier = max(
                (item for item in group if (item.kir if book == "KIR" else item.kpr)),
                key=lambda item: len(item.kir if book == "KIR" else item.kpr),
                default=None,
            )
            if supplier:
                if book == "KIR":
                    kir.extend(supplier.kir)
                else:
                    kpr.extend(supplier.kpr)
                used.append(supplier)
                return

    _fill_book("KIR")
    _fill_book("KPR")
    kir = _dedupe("KIR", kir)
    kpr = _dedupe("KPR", kpr)
    header = _normalize_header(primary.header, kir, kpr)
    formats = ", ".join(dict.fromkeys(f"{item.format_name}: {item.member_name}" for item in used))
    merged = ParsedCandidate(header, kir, kpr, formats, primary.member_name)
    members = list(dict.fromkeys(item.member_name for item in used))
    return merged, members, warnings


def _parse_zip_member_bytes(
    data: bytes,
    member_name: str,
    *,
    candidates: list[ParsedCandidate],
    rejected: list[str],
) -> None:
    suffix = Path(member_name).suffix.lower()
    if suffix not in {".json", ".xml", ".csv"}:
        return
    try:
        candidates.append(parse_member(data, member_name))
    except KirkprError as exc:
        rejected.append(f"{member_name}: {exc}")


def _collect_zip_candidates(
    archive: zipfile.ZipFile,
    *,
    prefix: str = "",
    recurse_nested: bool = True,
) -> tuple[list[ParsedCandidate], list[str], list[str]]:
    """Prebere JSON/XML/CSV iz ZIP; po potrebi tudi en nivo ugnezdenih ZIP-ov."""
    candidates: list[ParsedCandidate] = []
    rejected: list[str] = []
    member_names: list[str] = []
    nested_zips: list[tuple[str, bytes]] = []

    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        label = f"{prefix}{name}" if prefix else name
        member_names.append(label)
        suffix = Path(name).suffix.lower()
        if suffix in {".json", ".xml", ".csv"}:
            _parse_zip_member_bytes(
                archive.read(info),
                label,
                candidates=candidates,
                rejected=rejected,
            )
        elif suffix == ".zip" and recurse_nested:
            try:
                nested_zips.append((label, archive.read(info)))
            except OSError as exc:
                rejected.append(f"{label}: branje ugnezdenega ZIP ni uspelo ({exc})")

    if candidates or not nested_zips:
        return candidates, rejected, member_names

    # Zunanji ZIP nima uporabnega KIR/KPR — poskusi ugnezdene ZIP arhive (1 nivo).
    for nested_name, nested_data in nested_zips:
        try:
            with zipfile.ZipFile(io.BytesIO(nested_data)) as nested:
                nested_candidates, nested_rejected, nested_members = _collect_zip_candidates(
                    nested,
                    prefix=f"{nested_name}/",
                    recurse_nested=False,
                )
        except zipfile.BadZipFile:
            rejected.append(f"{nested_name}: neveljaven ugnezden ZIP")
            continue
        candidates.extend(nested_candidates)
        rejected.extend(nested_rejected)
        member_names.extend(nested_members)
        if candidates:
            break
    return candidates, rejected, member_names


def inspect_source(path: Path | str, *, preferred_format: str | None = None) -> dict[str, Any]:
    """Hiter pregled ZIP/JSON/XML/CSV pred uvozom (brez shranjevanja v GUI)."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise KirkprError(f"Datoteka ne obstaja: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise KirkprError("Podprti formati so ZIP, JSON, XML in CSV.")

    info: dict[str, Any] = {
        "path": str(source),
        "name": source.name,
        "suffix": suffix,
        "size": source.stat().st_size,
        "members": [],
        "usable_members": [],
        "rejected": [],
        "kir": 0,
        "kpr": 0,
        "period_from": "",
        "period_to": "",
        "tax_id": "",
        "format": "",
        "preferred_format": _normalize_preferred_format(preferred_format),
        "error": "",
    }
    try:
        dataset = load_dataset(source, preferred_format=preferred_format)
    except KirkprError as exc:
        info["error"] = str(exc)
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(source) as archive:
                    info["members"] = [
                        name for name in archive.namelist() if name and not name.endswith("/")
                    ]
            except zipfile.BadZipFile:
                pass
        return info

    info["kir"] = len(dataset.kir)
    info["kpr"] = len(dataset.kpr)
    info["period_from"] = str(dataset.header.get("OBDOBJE_OD") or dataset.period_from or "")
    info["period_to"] = str(dataset.header.get("OBDOBJE_DO") or dataset.period_to or "")
    info["tax_id"] = str(dataset.header.get("TaxPayerID") or "")
    info["format"] = dataset.source_format
    info["usable_members"] = list(dataset.source_members)
    info["rejected"] = list(dataset.warnings)
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(source) as archive:
                info["members"] = [
                    name for name in archive.namelist() if name and not name.endswith("/")
                ]
        except zipfile.BadZipFile:
            info["members"] = list(dataset.source_members)
    else:
        info["members"] = [source.name]
    return info


def load_dataset(path: Path | str, *, preferred_format: str | None = None) -> KirkprDataset:
    """Naloži KIR/KPR iz ZIP/JSON/XML/CSV.

    ZIP pravila:
    - znotraj ZIP so dovoljeni člani .json / .xml / .csv (tudi ločeno KIR in KPR);
    - ugnezdeni ZIP se odpre 1 nivo, če zunanji nima uporabnih članov;
    - preferred_format (json|xml|csv) omeji izbor, če je tak član na voljo;
    - sicer se izbere najpopolnejši vir (JSON > XML > CSV).
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise KirkprError(f"Datoteka ne obstaja: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise KirkprError("Podprti formati so ZIP, JSON, XML in CSV.")

    preferred = _normalize_preferred_format(preferred_format)
    warnings: list[str] = []
    if suffix != ".zip":
        candidate = parse_member(source.read_bytes(), source.name)
        members = [source.name]
        format_name = candidate.format_name
        if preferred != "all" and candidate.format_name.upper() != preferred.upper():
            warnings.append(
                f"Datoteka je {candidate.format_name}, prednostni format je bil {preferred.upper()}."
            )
    else:
        try:
            with zipfile.ZipFile(source) as archive:
                candidates, rejected, all_members = _collect_zip_candidates(archive)
        except zipfile.BadZipFile as exc:
            raise KirkprError(f"Neveljaven ZIP: {source.name}") from exc
        if not candidates:
            sample = ", ".join(all_members[:8]) if all_members else "(prazno)"
            more = f" (+{len(all_members) - 8})" if len(all_members) > 8 else ""
            detail = " | ".join(rejected[:4]) if rejected else "ni JSON/XML/CSV z vrsticami KIR/KPR"
            raise KirkprError(
                f"V ZIP-u ni uporabnega JSON, XML ali CSV KIR/KPR.\n"
                f"Vsebina: {sample}{more}\n"
                f"Razlog: {detail}"
            )
        candidate, members, merge_warnings = _merge_candidates(
            candidates,
            preferred_format=preferred,
        )
        warnings.extend(merge_warnings)
        format_name = "ZIP → " + candidate.format_name
        if preferred != "all":
            format_name += f" (prednost {preferred.upper()})"
        if rejected:
            warnings.append("Prezrte neustrezne datoteke: " + " | ".join(rejected[:4]))

    warnings.extend(candidate.warnings)
    return KirkprDataset(
        header=candidate.header,
        kir=copy.deepcopy(candidate.kir),
        kpr=copy.deepcopy(candidate.kpr),
        source_path=source,
        source_format=format_name,
        source_members=members,
        warnings=warnings,
    )


def default_config() -> dict[str, Any]:
    return {
        "pr_default_account": "4190",
        "ir_revenue_account": "7601",
        "supplier_accounts": {},
        "supplier_self_assessment": {},
        "supplier_vat_deductible": {},
        "customer_accounts": {},
        "document_accounts": {},
        "document_descriptions": {},
        "document_vat_deductible": {},
        "document_self_assessment": {},
        # Ohranimo samo za enkratno pretvorbo stare oznake R.
        "document_representation": {},
        "company_profiles": {},
        "company_registry_path": "",
        "trops_root": "",
        "selected_company_key": "",
        "last_input_dir": "",
        "last_output_dir": "",
        "last_source_file": "",
        "last_export_dir": "",
        "last_export_archive": "",
        "last_working_copy": "",
        "last_action": "",
        "last_action_detail": "",
        "last_action_at": "",
        "last_account": "4190",
        "last_ir_account": "7601",
        "window_geometry": "1480x900",
        "window_state": "normal",
        "active_tab": 0,
        "auto_reopen_last_source": True,
        # Pridobivanje KIR/KPR: privzeta mapa + prednostni format (all|zip|json|xml|csv).
        "source_input_dir": "",
        "source_preferred_format": "all",
        # Prenos v Minimax po pridobitvi: api | xml.
        "source_transfer_mode": "xml",
        "source_transfer_after_acquire": False,
        "ddvo_email_editor_geometry": "",
        "recent_sessions": [],
        "minimax_settings_path": "",
        "minimax_selected_org_id": "",
        "minimax_journal_status": "O",
        "minimax_api_transfer_mode": "journal",
        "minimax_api_sent": {},
        "log_level": "INFO",
        "app_version": "",
        "version_history": [],
    }


def config_path(base_dir: Path | None = None) -> Path:
    return (base_dir or Path(__file__).resolve().parent) / DEFAULT_CONFIG_NAME


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    config = default_config()
    if not target.exists():
        return config
    try:
        loaded = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return config
    if isinstance(loaded, Mapping):
        for key in config:
            if key in loaded:
                config[key] = loaded[key]
    if not isinstance(config.get("supplier_accounts"), dict):
        config["supplier_accounts"] = {}
    if not isinstance(config.get("supplier_self_assessment"), dict):
        config["supplier_self_assessment"] = {}
    if not isinstance(config.get("supplier_vat_deductible"), dict):
        config["supplier_vat_deductible"] = {}
    if not isinstance(config.get("customer_accounts"), dict):
        config["customer_accounts"] = {}
    if not isinstance(config.get("document_accounts"), dict):
        config["document_accounts"] = {}
    if not isinstance(config.get("document_descriptions"), dict):
        config["document_descriptions"] = {}
    if not isinstance(config.get("document_vat_deductible"), dict):
        config["document_vat_deductible"] = {}
    if not isinstance(config.get("document_self_assessment"), dict):
        config["document_self_assessment"] = {}
    if not isinstance(config.get("document_representation"), dict):
        config["document_representation"] = {}
    if not isinstance(config.get("minimax_api_sent"), dict):
        config["minimax_api_sent"] = {}
    if not isinstance(config.get("version_history"), list):
        config["version_history"] = []
    if not isinstance(config.get("recent_sessions"), list):
        config["recent_sessions"] = []
    if not isinstance(config.get("company_profiles"), dict):
        config["company_profiles"] = {}
    return config


def save_config(config: Mapping[str, Any], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def _clean_identity(country: Any, tax_id: Any, name: Any) -> str:
    country_text = re.sub(r"[^A-Za-z]", "", str(country or "")).upper()[:2]
    tax_text = re.sub(r"[^0-9A-Za-z]", "", str(tax_id or "")).upper()
    if tax_text:
        return tax_text if tax_text.startswith(country_text) else country_text + tax_text
    return re.sub(r"[^0-9A-Za-z]", "", str(name or "").upper())[:40]


def supplier_key(row: Mapping[str, Any]) -> str:
    return _clean_identity(row.get("P7"), row.get("P7DS"), row.get("P6"))


def customer_key(row: Mapping[str, Any]) -> str:
    return _clean_identity(row.get("P6"), row.get("P6DS"), row.get("P5"))


def row_key(book: str, row: Mapping[str, Any]) -> str:
    is_issued = book.upper() in {"IR", "KIR"}
    tax_field = "P6DS" if is_issued else "P7DS"
    country_field = "P6" if is_issued else "P7"
    name_field = "P5" if is_issued else "P6"
    party = _clean_identity(row.get(country_field), row.get(tax_field), row.get(name_field))
    return "|".join((book, str(row.get("P3") or ""), str(row.get("P2") or ""), party, str(row.get("ZAPST") or "")))


def _boolean_value(value: Any) -> bool | None:
    """Prebere Minimaxov D/N in običajne zapise DA/NE; None pomeni brez nastavitve."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"1", "D", "DA", "R", "TRUE", "YES", "Y"}:
            return True
        if normalized in {"0", "N", "NE", "FALSE", "NO"}:
            return False
    return bool(value)


def vat_is_deductible(row: Mapping[str, Any]) -> bool:
    """Vrne nastavitev Minimax »DDV se odbija«; privzeto je odbitek dovoljen."""
    for field in ("__ddv_se_odbija__", "MINIMAX_DDV_SE_ODBIJA", "DDV_SE_ODBIJA"):
        parsed = _boolean_value(row.get(field))
        if parsed is not None:
            return parsed

    # Združljivost s prejšnjo različico: oznaka R je pomenila brez odbitka.
    for field in ("__reprezentanca__", "REPREZENTANCA", "R"):
        parsed = _boolean_value(row.get(field))
        if parsed is not None:
            return not parsed
    return True


def source_self_assessment(row: Mapping[str, Any]) -> bool:
    """Samodejna zaznava samoobdavčitve iz polj KPR 9, 10 in 11."""
    return any(decimal_value(row.get(f"P{i}")) != ZERO for i in (9, 10, 11))


def is_self_assessment(row: Mapping[str, Any]) -> bool:
    """Vrne ročno nastavitev »Samoobdavčitev« ali zaznano vrednost KPR."""
    for field in ("__samoobdavcitev__", "MINIMAX_SAMOOBDAVCITEV", "SAMOOBDAVCITEV"):
        parsed = _boolean_value(row.get(field))
        if parsed is not None:
            return parsed
    return source_self_assessment(row)


def is_representation(row: Mapping[str, Any]) -> bool:
    """Zastareli vzdevek: True pomeni, da DDV ni odbiten."""
    return not vat_is_deductible(row)


def apply_saved_accounts(dataset: KirkprDataset, config: Mapping[str, Any]) -> None:
    document_accounts = dict(config.get("document_accounts") or {})
    document_descriptions = dict(config.get("document_descriptions") or {})
    document_vat_deductible = dict(config.get("document_vat_deductible") or {})
    document_self_assessment = dict(config.get("document_self_assessment") or {})
    document_representation = dict(config.get("document_representation") or {})
    supplier_accounts = dict(config.get("supplier_accounts") or {})
    supplier_self_assessment = dict(config.get("supplier_self_assessment") or {})
    supplier_vat_deductible = dict(config.get("supplier_vat_deductible") or {})
    customer_accounts = dict(config.get("customer_accounts") or {})
    pr_default = str(config.get("pr_default_account") or "4190")
    ir_default = str(config.get("ir_revenue_account") or "7601")
    for row in dataset.kir:
        existing = str(row.get("__konto__") or "").strip()
        row["__konto__"] = str(
            document_accounts.get(row_key("IR", row))
            or row.get("MINIMAX_KONTO")
            or customer_accounts.get(customer_key(row))
            or existing
            or ir_default
        )
        row["__opis__"] = str(
            document_descriptions.get(row_key("IR", row))
            or row.get("MINIMAX_OPIS")
            or row.get("P3")
            or ""
        )
    for row in dataset.kpr:
        document_key = row_key("PR", row)
        sk = supplier_key(row)
        existing = str(row.get("__konto__") or "").strip()
        row["__konto__"] = str(
            document_accounts.get(document_key)
            or row.get("MINIMAX_KONTO")
            or supplier_accounts.get(sk)
            or existing
            or pr_default
        )
        row["__opis__"] = str(
            document_descriptions.get(document_key)
            or row.get("MINIMAX_OPIS")
            or row.get("P3")
            or ""
        )
        offer_from: list[str] = []
        vat_explicit = (
            document_key in document_vat_deductible
            or document_key in document_representation
            or sk in supplier_vat_deductible
        )
        if document_key in document_vat_deductible:
            deductible = _boolean_value(document_vat_deductible[document_key])
        elif document_key in document_representation:
            legacy = _boolean_value(document_representation[document_key])
            deductible = not bool(legacy)
        elif sk in supplier_vat_deductible:
            deductible = _boolean_value(supplier_vat_deductible[sk])
            offer_from.append("dobavitelj")
        else:
            deductible = vat_is_deductible(row)

        if document_key in document_self_assessment:
            self_assessment = _boolean_value(document_self_assessment[document_key])
        elif sk in supplier_self_assessment:
            self_assessment = _boolean_value(supplier_self_assessment[sk])
            if "dobavitelj" not in offer_from:
                offer_from.append("dobavitelj")
        elif source_self_assessment(row):
            # KPR P9/P10/P11 → ponudi samoobdavčitev (+ odbitni DDV, če ni drugega zapisa)
            self_assessment = True
            offer_from.append("KPR P9–P11")
        else:
            self_assessment = is_self_assessment(row)

        self_on = source_self_assessment(row) if self_assessment is None else bool(self_assessment)
        # Ob samoobdavčitvi privzeto ponudi tudi »DDV se odbija«, razen če je že zabeleženo drugače.
        if self_on and not vat_explicit:
            deductible = True
            if "KPR P9–P11" in offer_from or "dobavitelj" in offer_from:
                pass
            elif "privzeto ob samoobdavčitvi" not in offer_from:
                offer_from.append("privzeto ob samoobdavčitvi")

        row["__ddv_se_odbija__"] = True if deductible is None else bool(deductible)
        row["__samoobdavcitev__"] = self_on
        row["__vat_offer_from__"] = ", ".join(offer_from)
        row.pop("__reprezentanca__", None)


def normalize_account_code(account: Any) -> str:
    """Iz »4170 — Naziv« ali golo šifro vrne samo šifro konta."""
    text = str(account or "").strip()
    if not text:
        return ""
    return re.split(r"\s+[—–-]\s+", text, maxsplit=1)[0].strip()


def validate_minimax_account_code(
    account: Any,
    *,
    catalog: Mapping[str, Any] | Sequence[Any] | None = None,
) -> str:
    """Polna Minimax šifra konta (npr. 4170). Skrajšano 417 ni dovoljeno.

    Če je na voljo šifrant organizacije, mora šifra obstajati natanko v njem.
    """
    code = normalize_account_code(account)
    if not code:
        raise KirkprError("Konto ne sme biti prazen.")

    catalog_codes: list[str] = []
    if isinstance(catalog, Mapping):
        catalog_codes = [str(key).strip() for key in catalog if str(key).strip()]
    elif catalog is not None:
        for item in catalog:
            if isinstance(item, Mapping):
                value = str(item.get("code") or item.get("Code") or "").strip()
            else:
                value = str(item or "").strip()
            if value:
                catalog_codes.append(value)

    if catalog_codes:
        if code in catalog_codes:
            return code
        prefix_hits = sorted(item for item in catalog_codes if item.startswith(code) and item != code)
        if prefix_hits and len(code) < 4:
            sample = ", ".join(prefix_hits[:6])
            raise KirkprError(
                f"Konto '{code}' je prekratek za Minimax API. "
                f"Uporabite polno šifro (npr. {prefix_hits[0]}, ne {code}). "
                f"V šifrantu: {sample}."
            )
        if prefix_hits:
            sample = ", ".join(prefix_hits[:6])
            raise KirkprError(
                f"Konto '{code}' ni natančna Minimax šifra. Izberite polno šifro, npr. {sample}."
            )
        raise KirkprError(
            f"Konto '{code}' ni v Minimax šifrantu izbrane organizacije. "
            "Uporabite polno šifro iz šifranta (običajno 4 mesta, npr. 4170)."
        )

    if re.fullmatch(r"\d{1,3}", code):
        raise KirkprError(
            f"Konto '{code}' je prekratek. Minimax API zahteva polno šifro "
            f"(npr. 4170, ne 417) — vsaj 4 mesta."
        )
    if not re.fullmatch(r"[0-9A-Za-z.\-]{4,30}", code):
        raise KirkprError(
            "Konto mora biti polna Minimax šifra: 4–30 znakov (številke/črke), npr. 4170 ali 4190."
        )
    return code


def remember_account(config: dict[str, Any], book: str, row: Mapping[str, Any], account: str, supplier_rule: bool = True) -> None:
    account = validate_minimax_account_code(account)
    config.setdefault("document_accounts", {})[row_key(book, row)] = account
    if book == "PR" and supplier_rule:
        config.setdefault("supplier_accounts", {})[supplier_key(row)] = account
    elif book == "IR" and supplier_rule:
        config.setdefault("customer_accounts", {})[customer_key(row)] = account


def remember_description(config: dict[str, Any], book: str, row: Mapping[str, Any], description: str) -> None:
    description = str(description or "").strip()
    if not description:
        raise KirkprError("Opis knjižbe ne sme biti prazen.")
    if len(description) > 250:
        raise KirkprError("Opis knjižbe je lahko dolg največ 250 znakov.")
    config.setdefault("document_descriptions", {})[row_key(book, row)] = description


def remember_vat_deductible(
    config: dict[str, Any],
    row: Mapping[str, Any],
    enabled: bool,
    *,
    supplier_rule: bool = False,
) -> None:
    """Trajno shrani Minimaxovo nastavitev »DDV se odbija« za PR (in po želji za dobavitelja)."""
    config.setdefault("document_vat_deductible", {})[row_key("PR", row)] = bool(enabled)
    if supplier_rule:
        config.setdefault("supplier_vat_deductible", {})[supplier_key(row)] = bool(enabled)


def remember_self_assessment(
    config: dict[str, Any],
    row: Mapping[str, Any],
    enabled: bool,
    *,
    supplier_rule: bool = False,
) -> None:
    """Trajno shrani Minimaxovo nastavitev »Samoobdavčitev« za PR (in po želji za dobavitelja)."""
    config.setdefault("document_self_assessment", {})[row_key("PR", row)] = bool(enabled)
    if supplier_rule:
        config.setdefault("supplier_self_assessment", {})[supplier_key(row)] = bool(enabled)


def remember_representation(config: dict[str, Any], row: Mapping[str, Any], enabled: bool) -> None:
    """Združljivost s starimi klici: reprezentanca je pomenila brez odbitka DDV."""
    remember_vat_deductible(config, row, not enabled)


def company_profile(config: dict[str, Any], key: str) -> dict[str, Any]:
    """Vrne ločene nastavitve kontiranja in API sledi za izbrano podjetje."""
    if not key:
        return config
    profiles = config.setdefault("company_profiles", {})
    profile = profiles.get(key)
    if not isinstance(profile, dict):
        profile = {}
        profiles[key] = profile
    mapping_keys = (
        "supplier_accounts",
        "supplier_self_assessment",
        "supplier_vat_deductible",
        "customer_accounts",
        "document_accounts",
        "document_descriptions",
        "document_vat_deductible",
        "document_self_assessment",
        "document_representation",
        "minimax_api_sent",
        "account_catalog",
    )
    first_use = not profile
    for name in mapping_keys:
        if not isinstance(profile.get(name), dict):
            source = config.get(name) if first_use and name != "account_catalog" else {}
            profile[name] = copy.deepcopy(source) if isinstance(source, Mapping) else {}
    for name, default in (
        ("pr_default_account", config.get("pr_default_account") or "4190"),
        ("ir_revenue_account", config.get("ir_revenue_account") or "7601"),
        ("last_source_file", ""),
        ("last_input_dir", ""),
        ("last_output_dir", ""),
        ("last_export_dir", ""),
        ("last_export_archive", ""),
        ("last_working_copy", ""),
        ("last_account", config.get("last_account") or "4190"),
        ("last_ir_account", config.get("last_ir_account") or "7601"),
        ("minimax_selected_org_id", ""),
    ):
        profile.setdefault(name, default)
    return profile


RECENT_SESSIONS_LIMIT = 20


def _period_label_short(period_from: str, period_to: str) -> str:
    start = str(period_from or "")[:10]
    end = str(period_to or "")[:10]
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d").date()
        d1 = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return end or start or "—"
    if d0.year == d1.year and d0.month == d1.month:
        return f"{d1.year}/{d1.month:02d}"
    if d0.year == d1.year:
        return f"{d1.year}/{d0.month:02d}–{d1.month:02d}"
    return f"{d0.year}/{d0.month:02d}–{d1.year}/{d1.month:02d}"


def format_recent_session_label(entry: Mapping[str, Any]) -> str:
    """Npr. »41 KLUG · 2026/04–06 · KLUGKIRKPR-04-06-2026.zip«."""
    company = str(entry.get("company_label") or entry.get("company_key") or "—").strip()
    period = _period_label_short(
        str(entry.get("period_from") or ""),
        str(entry.get("period_to") or ""),
    )
    path = str(entry.get("working_copy") or entry.get("source") or "")
    name = Path(path).name if path else "—"
    return f"{company} · {period} · {name}"


def seed_recent_sessions_from_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Če je seznam prazen, napolni iz last_source/last_working_copy po podjetjih."""
    existing = [row for row in (config.get("recent_sessions") or []) if isinstance(row, dict)]
    if existing:
        return existing
    profiles = config.get("company_profiles")
    if not isinstance(profiles, dict):
        return []
    seeded: list[dict[str, Any]] = []
    for key, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        source = str(profile.get("last_source_file") or "").strip()
        working = str(profile.get("last_working_copy") or "").strip()
        if not source and not working:
            continue
        path = working if working and Path(working).is_file() else source
        if not path or not Path(path).is_file():
            continue
        zst = str(key).replace("zst-", "") if str(key).startswith("zst-") else ""
        label_company = f"{zst} {Path(path).stem}".strip() if zst else str(key)
        entry = {
            "company_key": str(key),
            "company_label": label_company,
            "source": source or path,
            "working_copy": working if working and Path(working).is_file() else "",
            "period_from": "",
            "period_to": "",
            "opened_at": "",
        }
        entry["label"] = format_recent_session_label(entry)
        seeded.append(entry)
    config["recent_sessions"] = seeded[:RECENT_SESSIONS_LIMIT]
    return list(config["recent_sessions"])


def remember_recent_session(
    config: dict[str, Any],
    *,
    company_key: str,
    company_label: str,
    source: str | Path,
    working_copy: str | Path | None = None,
    period_from: str = "",
    period_to: str = "",
    limit: int = RECENT_SESSIONS_LIMIT,
) -> list[dict[str, Any]]:
    """Dodaj / pomakni sejo na vrh seznama (globalno, več firm + obdobij)."""
    key = str(company_key or "").strip()
    source_s = str(source or "").strip()
    working_s = str(working_copy or "").strip()
    if not key or (not source_s and not working_s):
        return list(config.get("recent_sessions") or [])
    entry = {
        "company_key": key,
        "company_label": str(company_label or key).strip(),
        "source": source_s,
        "working_copy": working_s,
        "period_from": str(period_from or "")[:10],
        "period_to": str(period_to or "")[:10],
        "opened_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    entry["label"] = format_recent_session_label(entry)
    rows: list[dict[str, Any]] = []
    for row in config.get("recent_sessions") or []:
        if not isinstance(row, dict):
            continue
        same_company = str(row.get("company_key") or "") == key
        same_source = str(row.get("source") or "") == source_s and source_s
        same_working = (
            working_s
            and str(row.get("working_copy") or "") == working_s
        )
        # Ista firma + isti vir (ali ista delovna kopija) = posodobi, ne podvoji.
        if same_company and (same_source or same_working or (
            source_s and str(row.get("source") or "") == source_s
        )):
            continue
        rows.append(dict(row))
    rows.insert(0, entry)
    config["recent_sessions"] = rows[: max(1, int(limit or RECENT_SESSIONS_LIMIT))]
    return list(config["recent_sessions"])


def recent_session_open_path(entry: Mapping[str, Any]) -> Path | None:
    """Prednost: delovna kopija, če obstaja; sicer vir."""
    for key in ("working_copy", "source"):
        value = str(entry.get(key) or "").strip()
        if value and Path(value).is_file():
            return Path(value)
    return None


def update_working_row(book: str, row: dict[str, Any], field_name: str, value: Any) -> Any:
    """Validira in spremeni samo delovno vrstico, ne izvorne datoteke."""
    book_name = book.upper()
    if book_name not in {"IR", "KIR", "PR", "KPR"}:
        raise KirkprError(f"Neznana knjiga: {book}")
    canonical = _canonical_field(field_name)
    max_p = 27 if book_name in {"IR", "KIR"} else 21
    tax_field = "P6DS" if book_name in {"IR", "KIR"} else "P7DS"
    allowed = {"ZAPST", "OBRAVNAVA", tax_field, *(f"P{index}" for index in range(1, max_p + 1))}
    if canonical not in allowed:
        raise KirkprError(f"Polja {field_name!r} ni dovoljeno spreminjati.")
    numeric_start = 7 if book_name in {"IR", "KIR"} else 8
    numeric_fields = {f"P{index}" for index in range(numeric_start, max_p + 1)}
    date_fields = {"P2", "P4"} | ({"P5"} if book_name in {"PR", "KPR"} else set())
    if canonical == "ZAPST":
        try:
            normalized: Any = int(decimal_value(value))
        except (KirkprError, ValueError) as exc:
            raise KirkprError("Zaporedna številka mora biti celo število.") from exc
    elif canonical in numeric_fields:
        normalized = decimal_text(value)
    elif canonical in date_fields:
        normalized = normalize_date(value)
        if normalized and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
            raise KirkprError("Datum mora biti v obliki LLLL-MM-DD ali DD.MM.LLLL.")
    else:
        normalized = str(value or "").strip()
        country_field = "P6" if book_name in {"IR", "KIR"} else "P7"
        if canonical == country_field:
            normalized = normalized.upper()[:2]
    row[canonical] = normalized
    return normalized


def _working_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {str(key): value for key, value in row.items() if not str(key).startswith("__")}
    result["MINIMAX_KONTO"] = str(row.get("__konto__") or "")
    result["MINIMAX_OPIS"] = str(row.get("__opis__") or row.get("P3") or "")
    result["MINIMAX_DDV_SE_ODBIJA"] = "D" if vat_is_deductible(row) else "N"
    result["MINIMAX_SAMOOBDAVCITEV"] = "D" if is_self_assessment(row) else "N"
    result.pop("REPREZENTANCA", None)
    return result


def save_working_copy(
    dataset: KirkprDataset,
    target: Path | str,
    *,
    company: Mapping[str, Any] | None = None,
) -> Path:
    """Shrani urejeno kopijo FURS strukture pod novim imenom; izvora ne prepiše."""
    destination = Path(target).expanduser().resolve()
    if destination == dataset.source_path.expanduser().resolve():
        raise KirkprError("Delovna kopija ne sme prepisati izvorne datoteke.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "original_source": str(dataset.source_path),
        "source_format": dataset.source_format,
        "company": dict(company or {}),
        "note": "Delovna kopija za Minimax; izvorna datoteka ni spremenjena.",
    }
    payload = {
        "DDV_KIR_KPR": {
            "Glava": copy.deepcopy(dataset.header),
            "Lista_KIR": {"KIR": [_working_row(row) for row in dataset.kir]},
            "Lista_KPR": {"KPR": [_working_row(row) for row in dataset.kpr]},
        },
        "MINIMAX_DELOVNA_KOPIJA": metadata,
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def kir_is_tax_only(row: Mapping[str, Any], kpr_rows: Sequence[Mapping[str, Any]]) -> bool:
    # Izvorne KIR vrstice samoobdavčitve nikoli ne smejo postati lažni IR,
    # tudi če uporabnik v delovni kopiji izključi nastavitev na pripadajočem PR.
    numbers = {
        str(item.get("P3") or "")
        for item in kpr_rows
        if source_self_assessment(item) or is_self_assessment(item)
    }
    return minimax_xml.is_kir_self_assessment(dict(row), numbers)


def ir_metrics(row: Mapping[str, Any], kpr_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    taxable = decimal_value(row.get("P7"))
    exempt = sum((decimal_value(row.get(f"P{i}")) for i in (9, 10, 11)), ZERO)
    non_taxable = sum((decimal_value(row.get(f"P{i}")) for i in (8, 12, 13, 27)), ZERO)
    vat_22 = decimal_value(row.get("P14"))
    vat_95 = decimal_value(row.get("P15"))
    vat_5 = decimal_value(row.get("P16"))
    vat = vat_22 + vat_95 + vat_5
    net = taxable + exempt + non_taxable
    tax_only = kir_is_tax_only(row, kpr_rows)
    return {
        "net": net,
        "vat": vat,
        "vat_22": vat_22,
        "vat_95": vat_95,
        "vat_5": vat_5,
        "gross": net + vat,
        "tax_only": tax_only,
    }


def base_from_vat(vat: Any, rate: Decimal) -> Decimal:
    """Osnova = DDV / stopnja (npr. 22 / 0,22 = 100)."""
    amount = decimal_value(vat)
    pct = Decimal(str(rate or 0))
    if amount == 0 or pct == 0:
        return ZERO
    return (amount / pct).quantize(CENT, rounding=ROUND_HALF_UP)


def vat_base_amounts(
    vat_22: Any = 0,
    vat_95: Any = 0,
    vat_5: Any = 0,
) -> dict[str, Decimal]:
    """Osnova 22% / 9,5% / 5% iz zneskov DDV (za WebUI / Chrome paketek)."""
    return {
        "base_22": base_from_vat(vat_22, Decimal("0.22")),
        "base_95": base_from_vat(vat_95, Decimal("0.095")),
        "base_5": base_from_vat(vat_5, Decimal("0.05")),
        "vat_22": decimal_value(vat_22),
        "vat_95": decimal_value(vat_95),
        "vat_5": decimal_value(vat_5),
    }


def pr_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    taxable = sum((decimal_value(row.get(f"P{i}")) for i in range(8, 14)), ZERO)
    exempt = sum((decimal_value(row.get(f"P{i}")) for i in range(14, 17)), ZERO)
    source_non_deductible = decimal_value(row.get("P17"))
    vat_22 = decimal_value(row.get("P18"))
    vat_95 = decimal_value(row.get("P19"))
    vat_5 = decimal_value(row.get("P20"))
    vat_flat = decimal_value(row.get("P21"))
    reported_vat = vat_22 + vat_95 + vat_5 + vat_flat
    vat_deductible = vat_is_deductible(row)
    deductible = reported_vat if vat_deductible else ZERO
    non_deductible = source_non_deductible + (ZERO if vat_deductible else reported_vat)
    self_assessment = is_self_assessment(row)
    net = taxable + exempt
    payable = net + source_non_deductible + (ZERO if self_assessment else reported_vat)
    bases = vat_base_amounts(vat_22, vat_95, vat_5)
    return {
        "net": net,
        "vat": deductible,
        "vat_22": vat_22,
        "vat_95": vat_95,
        "vat_5": vat_5,
        "base_22": bases["base_22"],
        "base_95": bases["base_95"],
        "base_5": bases["base_5"],
        "reported_vat": reported_vat,
        "non_deductible_vat": non_deductible,
        "gross": payable,
        "self_assessment": self_assessment,
        "source_self_assessment": source_self_assessment(row),
        "vat_deductible": vat_deductible,
        "representation": not vat_deductible,
        "expense": net + non_deductible,
    }


def dataset_summary(dataset: KirkprDataset) -> dict[str, Any]:
    ir_values = [ir_metrics(row, dataset.kpr) for row in dataset.kir]
    exported_ir = [item for item in ir_values if not item["tax_only"]]
    pr_values = [pr_metrics(row) for row in dataset.kpr]
    return {
        "ir_count": len(exported_ir),
        "kir_count": len(dataset.kir),
        "tax_only_kir_count": len(ir_values) - len(exported_ir),
        "pr_count": len(dataset.kpr),
        "ir_net": sum((item["net"] for item in exported_ir), ZERO),
        "ir_vat": sum((item["vat"] for item in exported_ir), ZERO),
        "pr_net": sum((item["net"] for item in pr_values), ZERO),
        "pr_vat": sum((item["vat"] for item in pr_values), ZERO),
    }


def ddvo_summary(dataset: KirkprDataset) -> dict[str, Any]:
    """Izračuna kontrolni DDV-O iz evidenc KIR/KPR.

    Posamezna polja DDV-O se po FURS preslikavi seštejejo iz polj evidenc in
    za obrazec zaokrožijo na cele evre. Polji 51 in 52 sta izračunani iz že
    zaokroženih polj obračunanega in odbitnega DDV, enako kot na obrazcu.
    """
    fields: list[dict[str, Any]] = []
    for section, code, label, book, source_fields in DDVO_FIELD_DEFINITIONS:
        rows = dataset.kir if book == "KIR" else dataset.kpr
        exact = sum(
            (
                ZERO
                if book == "KPR" and source_field in {"P18", "P19", "P20", "P21"} and not vat_is_deductible(row)
                else decimal_value(row.get(source_field))
                for row in rows
                for source_field in source_fields
            ),
            ZERO,
        )
        rounded = exact.quantize(EURO, rounding=ROUND_HALF_UP)
        fields.append(
            {
                "section": section,
                "code": code,
                "label": label,
                "book": book,
                "source_fields": source_fields,
                "source": f"{book} " + " + ".join(source_fields),
                "exact": exact,
                "value": rounded,
                "difference": rounded - exact,
                "status": "OK",
            }
        )

    output_codes = {"21", "22", "22a", "23", "23a", "24", "24a", "24b", "24c", "25", "25a", "25b", "26"}
    input_codes = {"41", "42", "42a", "43"}
    output_vat = sum((field["value"] for field in fields if field["code"] in output_codes), ZERO)
    input_vat = sum((field["value"] for field in fields if field["code"] in input_codes), ZERO)
    output_vat_exact = sum((field["exact"] for field in fields if field["code"] in output_codes), ZERO)
    input_vat_exact = sum((field["exact"] for field in fields if field["code"] in input_codes), ZERO)
    balance = output_vat - input_vat
    obligation = max(balance, ZERO)
    excess = max(-balance, ZERO)

    result_fields = (
        ("51", "Obveznost DDV", "Σ II − Σ IV", obligation),
        ("52", "Presežek DDV", "Σ IV − Σ II", excess),
    )
    for code, label, source, value in result_fields:
        fields.append(
            {
                "section": "V. Obveznost / presežek",
                "code": code,
                "label": label,
                "book": "DDV-O",
                "source_fields": (),
                "source": source,
                "exact": value,
                "value": value,
                "difference": ZERO,
                "status": "OK",
            }
        )

    control_difference = output_vat - input_vat - obligation + excess
    return {
        "fields": fields,
        "output_vat": output_vat,
        "input_vat": input_vat,
        "output_vat_exact": output_vat_exact,
        "input_vat_exact": input_vat_exact,
        "obligation": obligation,
        "excess": excess,
        "control_difference": control_difference,
        "control_ok": control_difference == ZERO,
        "non_deductible_vat": sum((pr_metrics(row)["non_deductible_vat"] for row in dataset.kpr), ZERO),
        "vat_not_deducted_count": sum(not vat_is_deductible(row) for row in dataset.kpr),
        "vat_not_deducted": sum(
            (pr_metrics(row)["reported_vat"] for row in dataset.kpr if not vat_is_deductible(row)),
            ZERO,
        ),
        "self_assessment_count": sum(is_self_assessment(row) for row in dataset.kpr),
        "excluded_kir": sum((decimal_value(row.get("P27")) for row in dataset.kir), ZERO),
    }


def edavki_konto62_credit(value: Any) -> Decimal:
    """Preplačilo DDV (konto 62): negativni saldo eDavkov → pozitivni kredit."""
    amount = decimal_value(value)
    return abs(amount)


def ddvo_virman_payment(obligation: Any, konto62: Any = ZERO) -> dict[str, Decimal]:
    """Plačilni nalog = polje 51 − preplačilo konta 62 (najmanj 0)."""
    field_51 = max(decimal_value(obligation), ZERO)
    credit = edavki_konto62_credit(konto62)
    payment = max(field_51 - credit, ZERO)
    return {
        "obligation": field_51,
        "konto62_credit": credit,
        "payment": payment,
    }


def parse_edavki_konto62_from_text(text: str) -> Decimal | None:
    """Iz eKartice / diagnostic JSON poišče saldo konta 62 (preplačilo kot abs)."""
    raw = str(text or "")
    if not raw.strip():
        return None

    # Diagnostic JSON: vrstica tabele ["62", "...", breme, dobro, skupaj saldo, ...]
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        tables = ((payload.get("optional_capture") or {}).get("tables")) or []
        for table in tables:
            for row in table.get("rows") or []:
                if not row or str(row[0]).strip() != "62":
                    continue
                for cell in reversed(list(row[1:])):
                    cell_text = str(cell or "").strip()
                    if not cell_text or cell_text in {"", "Prikaži knjižbe"}:
                        continue
                    try:
                        return edavki_konto62_credit(cell_text)
                    except KirkprError:
                        continue

    # Vidno besedilo / CSV vrstica z začetkom »62 « in zneski
    for line in raw.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if not re.match(r"^62\b", compact):
            continue
        amounts = re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", compact)
        if not amounts:
            continue
        # Prednost: zadnji znesek v vrstici (Saldo na datum), sicer predzadnji (Skupaj saldo)
        for candidate in reversed(amounts):
            try:
                parsed = decimal_value(candidate)
            except KirkprError:
                continue
            if parsed != ZERO or candidate.startswith("-"):
                return edavki_konto62_credit(parsed)
    return None


def ddvo_control_report(dataset: KirkprDataset) -> str:
    """Vrne čitljiv kontrolni pregled DDV-O za shranjevanje ali kopiranje."""
    summary = ddvo_summary(dataset)
    taxpayer = str(dataset.header.get("TaxPayerID") or "—")
    lines = [
        "KONTROLNI PREGLED DDV-O",
        f"Davčna številka: {taxpayer}",
        f"Obdobje: {dataset.period_from} do {dataset.period_to}",
        f"Vir: {dataset.source_path}",
        "",
        "Polje | Opis | Vir evidence | Točen seštevek | DDV-O (celi EUR)",
        "-" * 105,
    ]
    last_section = ""
    for field in summary["fields"]:
        if field["section"] != last_section:
            lines.extend(("", field["section"]))
            last_section = field["section"]
        lines.append(
            f"{field['code']:>4} | {field['label']:<50.50} | {field['source']:<15} | "
            f"{field['exact']:>14.2f} | {field['value']:>10.0f}"
        )
    lines.extend(
        (
            "",
            "KONTROLNI PODATEK",
            f"Obračunani DDV: {summary['output_vat']:.0f} EUR",
            f"Odbitni DDV: {summary['input_vat']:.0f} EUR",
            f"Polje 51 – obveznost: {summary['obligation']:.0f} EUR",
            f"Polje 52 – presežek: {summary['excess']:.0f} EUR",
            f"Kontrolna razlika: {summary['control_difference']:.0f} EUR "
            f"({'OK' if summary['control_ok'] else 'NAPAKA'})",
            f"DDV se ne odbija: {summary['vat_not_deducted_count']} računov; "
            f"DDV v strošku {summary['vat_not_deducted']:.2f} EUR",
            f"Samoobdavčitev: {summary['self_assessment_count']} računov",
            "",
            "Opomba: vrednosti DDV-O so zaokrožene na cele evre (ROUND_HALF_UP).",
        )
    )
    return "\n".join(lines) + "\n"


def find_xsd(base_dir: Path | None = None) -> Path | None:
    base = base_dir or Path(__file__).resolve().parent
    candidates = (
        base / "miniMAXUvozKnjigovodstvo.xsd",
        Path(__file__).resolve().parent / "miniMAXUvozKnjigovodstvo.xsd",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _validate_balances(root: etree._Element) -> None:
    namespace = {"m": minimax_xml.NS}
    for journal in root.xpath("//m:Temeljnica", namespaces=namespace):
        debit = sum(
            (Decimal(node.text) for node in journal.xpath(".//m:ZnesekVBremeVDomaciDenarniEnoti", namespaces=namespace)),
            ZERO,
        )
        credit = sum(
            (Decimal(node.text) for node in journal.xpath(".//m:ZnesekVDobroVDomaciDenarniEnoti", namespaces=namespace)),
            ZERO,
        )
        if debit != credit:
            invoice = journal.xpath("string(./m:GlavaTemeljnice/m:OpisGlaveTemeljnice)", namespaces=namespace)
            raise KirkprError(f"Neuravnotežena temeljnica {invoice}: breme {debit}, dobro {credit}.")


def _write_xml(root: etree._Element, path: Path, xsd_path: Path | None) -> bool:
    _validate_balances(root)
    if xsd_path and xsd_path.is_file():
        minimax_xml.write_and_validate(root, path, xsd_path)
        return True
    tree = etree.ElementTree(root)
    etree.indent(root, space="  ")
    tree.write(str(path), encoding="utf-8", xml_declaration=True, pretty_print=True)
    etree.parse(str(path))
    return False


def _account_distribution(rows: Sequence[Mapping[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        account = str(row.get("__konto__") or "")
        counts[account] = counts.get(account, 0) + 1
    return ", ".join(f"{account}: {count}" for account, count in sorted(counts.items())) or "ni vrstic"


def export_minimax(
    dataset: KirkprDataset,
    output_dir: Path | str,
    *,
    xsd_path: Path | None = None,
    create_archive: bool = True,
) -> ExportResult:
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not dataset.kir and not dataset.kpr:
        raise KirkprError("Ni podatkov za izvoz.")

    kir = copy.deepcopy(dataset.kir)
    kpr = copy.deepcopy(dataset.kpr)
    issued_root, issued_audit = minimax_xml.build_issued(kir, kpr)
    received_root, received_audit = minimax_xml.build_received(kpr)
    period_from = dataset.period_from or "brez-datuma"
    period_to = dataset.period_to or period_from
    token = f"{period_from}_{period_to}"
    issued_path = destination / f"Minimax_izdani_racuni_{token}.xml"
    received_path = destination / f"Minimax_prejeti_racuni_{token}.xml"
    report_path = destination / f"Minimax_pregled_pretvorbe_{token}.txt"
    archive_path = destination / f"Minimax_XML_{token}.zip"

    schema = xsd_path or find_xsd()
    validated_issued = _write_xml(issued_root, issued_path, schema)
    validated_received = _write_xml(received_root, received_path, schema)
    actual_ir = [item for item in issued_audit if item["kind"] == "IR"]
    tax_only = [item for item in issued_audit if item["kind"] == "KIR-samoobdavčitev"]
    vat_not_deducted = [item for item in received_audit if not item.get("vat_deductible", True)]
    self_assessment = [item for item in received_audit if item.get("self_assessment")]
    summary = dataset_summary(dataset)
    report_lines = [
        "PRETVORBA KIR/KPR -> MINIMAX",
        f"Vir: {dataset.source_path}",
        f"Zaznan format: {dataset.source_format}",
        f"Uporabljene datoteke: {', '.join(dataset.source_members)}",
        f"Obdobje: {period_from} do {period_to}",
        "",
        f"Izdani računi: {len(actual_ir)}; neto {summary['ir_net']:.2f}; DDV {summary['ir_vat']:.2f} EUR",
        f"Prejeti računi: {len(received_audit)}; osnove {summary['pr_net']:.2f}; odbitni DDV {summary['pr_vat']:.2f} EUR",
        f"DDV se ne odbija: {len(vat_not_deducted)}; DDV v strošku "
        f"{sum((item['reported_vat'] for item in vat_not_deducted), ZERO):.2f} EUR",
        f"Samoobdavčitev: {len(self_assessment)} prejetih računov",
        f"KIR samoobdavčitve, prenesene v PR: {len(tax_only)}",
        "",
        "KONTI",
        f"IR prihodki: {_account_distribution(kir)}",
        f"PR stroški/sredstva: {_account_distribution(kpr)}",
        "",
        "PREVERJANJE",
        "- Vse temeljnice so dvostavno uravnotežene.",
        "- XML je dobro oblikovan.",
        "- Uradna Minimax XSD-validacija: " + ("DA" if validated_issued and validated_received else "NE (XSD ni bila najdena)"),
    ]
    if dataset.warnings:
        report_lines.extend(("", "OPOZORILA", *(f"- {warning}" for warning in dataset.warnings)))
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    if create_archive:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in (issued_path, received_path, report_path):
                archive.write(file_path, file_path.name)
    else:
        archive_path = Path()

    return ExportResult(
        issued_xml=issued_path,
        received_xml=received_path,
        report=report_path,
        archive=archive_path,
        issued_count=len(actual_ir),
        received_count=len(received_audit),
        tax_only_kir_count=len(tax_only),
        xsd_validated=validated_issued and validated_received,
    )


__all__ = [
    "ExportResult",
    "KirkprDataset",
    "KirkprError",
    "SUPPORTED_SUFFIXES",
    "apply_saved_accounts",
    "company_profile",
    "config_path",
    "customer_key",
    "ddvo_codes_for_field",
    "ddvo_control_report",
    "ddvo_summary",
    "ddvo_virman_payment",
    "dataset_summary",
    "decimal_value",
    "default_config",
    "edavki_konto62_credit",
    "export_minimax",
    "find_xsd",
    "ir_metrics",
    "is_self_assessment",
    "is_representation",
    "kir_is_tax_only",
    "load_config",
    "load_dataset",
    "parse_edavki_konto62_from_text",
    "pr_metrics",
    "normalize_account_code",
    "remember_account",
    "remember_description",
    "validate_minimax_account_code",
    "remember_representation",
    "remember_self_assessment",
    "remember_vat_deductible",
    "row_key",
    "save_config",
    "save_working_copy",
    "supplier_key",
    "source_self_assessment",
    "update_working_row",
    "vat_is_deductible",
]
