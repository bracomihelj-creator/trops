"""Izvoz kontrolnega DDV-O v XML ovojnico eDavki (shema DDV_O_11)."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

import kirkpr_minimax_core as core

NS = "http://edavki.durs.si/Documents/Schemas/DDV_O_11.xsd"
EDP = "http://edavki.durs.si/Documents/Schemas/EDP-Common-1.xsd"
# Isti prikaz kot v eDavkih (hslsig:DisplayTransformDigest @transform):
DISPLAY_TRANSFORM_URL = (
    "https://edavki.durs.si/Documents/Transforms/DDV_O_11.7-display-sl.xslt"
)
DISPLAY_TRANSFORM_FILE = "DDV_O_11.7-display-sl.xslt"
FORM_VERSION = "e-DDV_O_11.7"

# Vsa denarna polja f* v telesu DDV-O (cela EUR, kot eDavki).
_DDVO_AMOUNT_CODES = (
    "11", "11a", "12", "13", "14", "15",
    "21", "22", "22a", "23", "23a", "24", "24a", "24b", "24c",
    "25", "25a", "25b", "26",
    "31", "31a", "32", "32a", "33", "34", "35",
    "41", "42", "42a", "43",
    "51", "52",
)

ET.register_namespace("", NS)
ET.register_namespace("edp", EDP)


def _bool_xml(value: Any) -> str:
    if isinstance(value, str):
        return "true" if value.strip().casefold() in {"1", "true", "da", "yes"} else "false"
    return "true" if bool(value) else "false"


def _int_eur(value: Decimal | int | float | str) -> str:
    return str(int(Decimal(str(value or 0))))


def parse_slovenian_address(raw: str) -> dict[str, str]:
    """Razčleni naslov iz EvidenceFirm / prostega besedila v polja eDavki."""
    text = " ".join(str(raw or "").replace("\n", " ").split()).strip()
    if not text:
        return {"address1": "", "city": "", "postNumber": "", "postName": ""}

    post_m = re.search(r"\b(\d{4})\s+(.+)$", text)
    post_number = post_m.group(1) if post_m else ""
    post_name = (post_m.group(2) if post_m else "").strip(" ,")
    before = text[: post_m.start()].strip(" ,") if post_m else text

    parts = [p.strip() for p in before.split(",") if p.strip()]
    city = ""
    street = before
    if len(parts) >= 2:
        # npr. "Ljubljana, Trtnikova ulica 8"
        if re.search(r"\d", parts[-1]):
            street = parts[-1]
            city = parts[0]
        else:
            street = ", ".join(parts[:-1]) if len(parts) > 1 else parts[0]
            city = parts[-1]
    elif parts:
        street = parts[0]

    if not city and post_name:
        city = post_name.split("-")[0].strip()

    return {
        "address1": street.upper(),
        "city": city.upper(),
        "postNumber": post_number,
        "postName": post_name.upper(),
    }


def period_label(period_from: str, period_to: str) -> str:
    """Oznaka obdobja za ime datoteke: 2026-Q1, 2026-H1, 2026-06, 2026 …"""
    start = str(period_from or "")[:10]
    end = str(period_to or "")[:10]
    if len(start) < 10 or start[4] != "-" or start[7] != "-":
        return f"{start}_{end}".strip("_") or "obdobje"
    year = start[:4]
    try:
        m1 = int(start[5:7])
        d1 = int(start[8:10])
    except ValueError:
        return f"{start}_{end}".strip("_") or "obdobje"
    m2 = d2 = None
    if len(end) >= 10 and end[4] == "-" and end[7] == "-":
        try:
            m2 = int(end[5:7])
            d2 = int(end[8:10])
        except ValueError:
            m2 = d2 = None
    if m2 is None:
        return f"{year}-Q{(m1 - 1) // 3 + 1}"

    # En mesec
    if m1 == m2 and d1 == 1:
        return f"{year}-{m1:02d}"
    # Tromesečja
    quarters = {(1, 3): "Q1", (4, 6): "Q2", (7, 9): "Q3", (10, 12): "Q4"}
    if (m1, m2) in quarters and d1 == 1:
        return f"{year}-{quarters[(m1, m2)]}"
    # Polletja / leto
    if m1 == 1 and m2 == 6 and d1 == 1:
        return f"{year}-H1"
    if m1 == 7 and m2 == 12 and d1 == 1:
        return f"{year}-H2"
    if m1 == 1 and m2 == 12 and d1 == 1:
        return year
    return f"{year}-{m1:02d}_{m2:02d}"


def default_ddvo_xml_name(dataset: core.KirkprDataset) -> str:
    return f"DDV_O_{period_label(dataset.period_from, dataset.period_to)}.xml"


def default_ddvo_pdf_name(dataset: core.KirkprDataset) -> str:
    label = period_label(dataset.period_from, dataset.period_to).replace("-", " ")
    return f"DDV O {label}.pdf"


def _field_map(summary: Mapping[str, Any]) -> dict[str, Decimal]:
    return {
        str(item["code"]): Decimal(str(item["value"]))
        for item in summary.get("fields") or []
    }


def build_ddvo_envelope(
    dataset: core.KirkprDataset,
    *,
    company_name: str = "",
    address: str = "",
    address1: str = "",
    city: str = "",
    post_number: str = "",
    post_name: str = "",
    contact_name: str = "",
    contact_phone: str = "",
    taxpayer_type: str = "PO",
) -> ET.Element:
    """Sestavi Envelope/DDV-O (brez eDavki podpisov — kontrolni/osnutek)."""
    summary = core.ddvo_summary(dataset)
    values = _field_map(summary)
    header = dataset.header

    tax = re.sub(r"\D", "", str(header.get("TaxPayerID") or ""))
    parsed = parse_slovenian_address(address)
    addr1 = (address1 or parsed["address1"]).strip()
    city_v = (city or parsed["city"]).strip()
    post_n = (post_number or parsed["postNumber"]).strip()
    post_nm = (post_name or parsed["postName"]).strip()
    name = (company_name or "").strip().upper() or "—"

    root = ET.Element(f"{{{NS}}}Envelope")
    edp_header = ET.SubElement(root, f"{{{EDP}}}Header")
    taxpayer = ET.SubElement(edp_header, f"{{{EDP}}}taxpayer")
    ET.SubElement(taxpayer, f"{{{EDP}}}taxNumber").text = tax
    ET.SubElement(taxpayer, f"{{{EDP}}}taxpayerType").text = (taxpayer_type or "PO").strip() or "PO"
    ET.SubElement(taxpayer, f"{{{EDP}}}name").text = name
    ET.SubElement(taxpayer, f"{{{EDP}}}address1").text = addr1
    ET.SubElement(taxpayer, f"{{{EDP}}}city").text = city_v
    ET.SubElement(taxpayer, f"{{{EDP}}}postNumber").text = post_n
    ET.SubElement(taxpayer, f"{{{EDP}}}postName").text = post_nm
    ET.SubElement(edp_header, f"{{{EDP}}}domain").text = "edavki.durs.si"
    ET.SubElement(root, f"{{{EDP}}}AttachmentList")
    ET.SubElement(root, f"{{{EDP}}}Signatures")

    body = ET.SubElement(root, f"{{{NS}}}body")
    ET.SubElement(body, f"{{{EDP}}}bodyContent")
    ddvo = ET.SubElement(body, f"{{{NS}}}DDV-O")

    ET.SubElement(ddvo, f"{{{NS}}}n_ddv").text = "9.5"
    ET.SubElement(ddvo, f"{{{NS}}}v_ddv").text = "22"
    ET.SubElement(ddvo, f"{{{NS}}}z_ddv").text = "5"
    ET.SubElement(ddvo, f"{{{NS}}}taxPeriodStart").text = str(dataset.period_from or "")[:10]
    ET.SubElement(ddvo, f"{{{NS}}}taxPeriodEnd").text = str(dataset.period_to or "")[:10]
    ET.SubElement(ddvo, f"{{{NS}}}selfReport").text = "false"
    ET.SubElement(ddvo, f"{{{NS}}}depositAfterDeadline").text = "false"
    ET.SubElement(ddvo, f"{{{NS}}}selfReportDoNotUseInstitute").text = "false"
    ET.SubElement(ddvo, f"{{{NS}}}contactPersonFullName").text = (contact_name or "").strip()
    ET.SubElement(ddvo, f"{{{NS}}}contactPersonPhoneNumber").text = re.sub(
        r"[^\d+]", "", str(contact_phone or "")
    ) or str(contact_phone or "").strip()
    ET.SubElement(ddvo, f"{{{NS}}}f03").text = _bool_xml(header.get("ODBDELEZ"))
    ET.SubElement(ddvo, f"{{{NS}}}f04").text = _bool_xml(header.get("VRACILO"))

    for code in _DDVO_AMOUNT_CODES:
        if code == "51":
            amount = summary["obligation"]
        elif code == "52":
            amount = summary["excess"]
        else:
            amount = values.get(code, Decimal("0"))
        ET.SubElement(ddvo, f"{{{NS}}}f{code}").text = _int_eur(amount)

    return root


def build_ddvo_xml_bytes(
    dataset: core.KirkprDataset,
    **kwargs: Any,
) -> bytes:
    """Envelope bytes + sklic na uradni eDavki XSLT prikaz (kot DisplayTransformDigest)."""
    root = build_ddvo_envelope(dataset, **kwargs)
    body = ET.tostring(root, encoding="utf-8")
    # xml-stylesheet + komentar — enako kot hslsig:Presentation / DisplayTransformDigest
    head = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<?xml-stylesheet type='text/xsl' href='{DISPLAY_TRANSFORM_URL}'?>\n"
        f"<!-- eDavki prikaz: {FORM_VERSION} · {DISPLAY_TRANSFORM_URL} · "
        f"lokalno: ddvo_transforms/{DISPLAY_TRANSFORM_FILE} -->\n"
    ).encode()
    if body.startswith(b"<?xml"):
        # odstranimo podvojeno deklaracijo iz tostring
        nl = body.find(b"?>")
        body = body[nl + 2 :].lstrip() if nl >= 0 else body
    return head + body


def write_ddvo_xml(
    dataset: core.KirkprDataset,
    target: Path | str,
    **kwargs: Any,
) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_ddvo_xml_bytes(dataset, **kwargs))
    return path
