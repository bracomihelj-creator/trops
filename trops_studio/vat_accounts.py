"""Minimax DDV konti 160xx / 260xx — domači, EU, tujci (po stopnji).

Vhodni (160) ← knjiga PR (odbitni → DDV-O 41/42/42a):
  domači PR ………… 16000 / 16001 / 16002
  EU blago …………… 16040 / 16041 / 16046     (P10 → polje 32 / DDV 23)
  EU storitve ……… 16044 / 16045 / 16048     (P11 → polje 32a / DDV 23a)
  tujci storitve … 16042 / 16043 / 16047     (osnova 08 → polje 31 / DDV 25)
  uvoz / tujci blago 16030 / 16031 / 16032   (osnova 08 → 31; DDV 25 ali 26)

Izhodni (260) — samoobdavčitev (sintetični KIR → DDV-O 23–26):
  domači IR ……… 26000 / 26001 / 26004
  EU blago ……… 26040 / 26041 / 26050   → polje 23
  EU storitve … 26044 / 26045 / 26052   → polje 23a
  tujci storitve 26042 / 26043 / 26051  → polje 25  (NI EU!)
  tujci blago … 26046 / 26047 / 26053   → polje 25  (pridobitev izven EU)
  MRN uvoz ……… 26046 (+ 16030)         → polje 26  (samoobdavčitev od uvoza)

DDV-O polje 41 (= KPR P18): odbitek od nabav + pridobitev EU + uvoz + tujci SA
  (input = output pri prevalitvi; NI samo »EU«).

Obveznosti do dobaviteljev (plačilo):
  SI / nezavezanec … 2200
  EU ………………… 2211
  tretja država …… 2210
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from trops_studio.money import decimal_value, is_nonzero, normalize_text, normalize_vat_id
from trops_studio.pr_vat_flags import resolve_pr_vat_flags
from trops_studio.vies_client import EU_VAT_COUNTRIES, is_eu_vat_id

Rate = Literal["22", "95", "5"]
VatKind = Literal[
    "domestic",
    "eu_goods",
    "eu_services",
    "foreign_services",
    "foreign_goods",
    "import_goods",
]
SupplierKind = Literal["SI", "EU", "THIRD", "NONE", "UVOZ", "MRN"]

# stopnja → (vhodni, izhodni)
_VAT_MAP: dict[VatKind, dict[Rate, tuple[str, str]]] = {
    "domestic": {
        "22": ("16000", "26000"),
        "95": ("16001", "26001"),
        "5": ("16002", "26004"),
    },
    "eu_goods": {
        "22": ("16040", "26040"),
        "95": ("16041", "26041"),
        "5": ("16046", "26050"),
    },
    "eu_services": {
        "22": ("16044", "26044"),
        "95": ("16045", "26045"),
        "5": ("16048", "26052"),
    },
    "foreign_services": {
        "22": ("16042", "26042"),
        "95": ("16043", "26043"),
        "5": ("16047", "26051"),
    },
    "foreign_goods": {
        "22": ("16030", "26046"),
        "95": ("16031", "26047"),
        "5": ("16032", "26053"),
    },
    "import_goods": {
        "22": ("16030", "26046"),
        "95": ("16031", "26047"),
        "5": ("16032", "26053"),
    },
}

# Združljivost s starimi klici (samo domači)
VAT_IN = {"22": "16000", "95": "16001", "5": "16002"}
VAT_OUT = {"22": "26000", "95": "26001", "5": "26004"}

# Minimax obveznosti do dobaviteljev
PAYABLE_BY_SUPPLIER: dict[SupplierKind, str] = {
    "SI": "2200",
    "NONE": "2200",
    "EU": "2211",
    "THIRD": "2210",
    "UVOZ": "2210",
    "MRN": "2210",
}

_SUPPLIER_ALIASES: dict[str, SupplierKind] = {
    "SI": "SI",
    "DOMACI": "SI",
    "DOMAČI": "SI",
    "DOMESTIC": "SI",
    "EU": "EU",
    "THIRD": "THIRD",
    "FOREIGN": "THIRD",
    "TUJEC": "THIRD",
    "TRETJA": "THIRD",
    "TRETJE": "THIRD",
    "TRETJA DRZAVA": "THIRD",
    "TRETJA DRŽAVA": "THIRD",
    "TRETJE DRZAVE": "THIRD",
    "TRETJE DRŽAVE": "THIRD",
    "IZVEN EU": "THIRD",
    "IZVENEU": "THIRD",
    "OUTSIDE EU": "THIRD",
    "NONE": "NONE",
    "NEZAVEZANEC": "NONE",
    "NI ZAVEZANEC": "NONE",
    "UVOZ": "UVOZ",
    "IMPORT": "UVOZ",
    "MRN": "MRN",
}


def vat_accounts(kind: VatKind, rate: Rate) -> tuple[str, str]:
    """(vhodni 160…, izhodni 260…) za tip prometa in stopnjo."""
    pair = _VAT_MAP.get(kind, _VAT_MAP["domestic"]).get(rate)
    if not pair:
        return _VAT_MAP["domestic"]["22"]
    return pair


def vat_in_account(kind: VatKind, rate: Rate) -> str:
    return vat_accounts(kind, rate)[0]


def vat_out_account(kind: VatKind, rate: Rate) -> str:
    return vat_accounts(kind, rate)[1]


def payable_account(kind: SupplierKind | str) -> str:
    """Konto plačila (2200 / 2211 / 2210) po opredelitvi dobavitelja."""
    sk = normalize_supplier_kind(kind) or "SI"
    return PAYABLE_BY_SUPPLIER.get(sk, "2200")  # type: ignore[arg-type]


def normalize_supplier_kind(value: Any) -> SupplierKind | str:
    """SI | EU | THIRD | NONE | UVOZ | MRN — ali prazen niz, če neznano."""
    raw = normalize_text(value).upper().replace("_", " ")
    if not raw:
        return ""
    if raw in _SUPPLIER_ALIASES:
        return _SUPPLIER_ALIASES[raw]
    # regija iz pr_list_view
    if raw == "FOREIGN":
        return "THIRD"
    return ""


def row_supplier_kind(row: Mapping[str, Any] | None = None) -> SupplierKind | str:
    """supplier_kind iz vrstice ali raw_json (brez sklepanja)."""
    row = row or {}
    explicit = normalize_supplier_kind(row.get("supplier_kind"))
    if explicit:
        return explicit
    try:
        import json

        raw = json.loads(row.get("raw_json") or "{}")
        if isinstance(raw, dict):
            return normalize_supplier_kind(raw.get("supplier_kind"))
    except Exception:
        pass
    return ""


def extract_mrn_codes(*texts: Any) -> list[str]:
    """MRN kode: 'MRN: …' ali eDavki oblika 26SI00112340108193."""
    import re

    found: list[str] = []
    seen: set[str] = set()
    patterns = (
        re.compile(r"\bMRN[:\s#-]*([A-Z0-9]{6,})\b", re.IGNORECASE),
        re.compile(r"\b(\d{2}SI\d{10,})\b", re.IGNORECASE),
    )
    for text in texts:
        blob = str(text or "")
        if not blob.strip():
            continue
        for pat in patterns:
            for match in pat.finditer(blob):
                code = match.group(1).upper()
                if code not in seen:
                    seen.add(code)
                    found.append(code)
    return found


def is_mrn_row(row: Mapping[str, Any] | None = None) -> bool:
    """True samo ob eksplicitni opredelitvi MRN (blago / carina → DDV-O 26).

    Ne sklepaj iz zneska DDV (npr. Foshan ≠ MRN) niti iz gole SA zastavice.
    """
    row = row or {}
    sk = normalize_supplier_kind(row_supplier_kind(row) or row.get("supplier_kind"))
    if sk == "MRN":
        return True
    if sk in ("UVOZ", "THIRD", "EU", "SI", "NONE"):
        # eksplicitna druga opredelitev → ni MRN (tudi če je v notes star MRN tag)
        return False
    # brez opredelitve: samo če je v dokumentu/opombi prava MRN koda
    codes = extract_mrn_codes(
        row.get("notes"),
        row.get("document_no"),
        row.get("internal_no"),
    )
    return bool(codes)


def pr_looks_like_goods(row: Mapping[str, Any] | None = None) -> bool:
    """Blago (ne storitev): EU blago, konto 65/66/40…, tipični uvozniki."""
    row = row or {}
    if is_nonzero(row.get("eu_goods")):
        return True
    if is_nonzero(row.get("eu_services")):
        return False
    for key in ("odhodek01", "odhodek10", "odhodek07"):
        code = normalize_text(row.get(key))
        if code.startswith(("65", "66", "40", "41")) and not code.startswith("419"):
            return True
    name = normalize_text(row.get("supplier_name")).casefold()
    if any(
        tip in name
        for tip in (
            "openai",
            "fiverr",
            "stripe",
            "google",
            "meta ",
            "facebook",
            "mailerlite",
            "mailer lite",
            "adobe",
            "deepl",
            "worldline",
        )
    ):
        return False
    if any(tip in name for tip in ("impex", "foshan", "alpicool", "fitness", "sport", "electronics")):
        return True
    return False


def is_uvoz_row(row: Mapping[str, Any] | None = None) -> bool:
    """Uvoz: odbitni uvozni DDV, brez samoobdavčitve (ni polje 26)."""
    return normalize_supplier_kind(row_supplier_kind(row or {})) == "UVOZ"


def is_third_country_digital_supplier(
    row: Mapping[str, Any] | None = None,
    party: Mapping[str, Any] | None = None,
) -> bool:
    """
    OpenAI/Fiverr/Upwork tip dobavitelja: tretja država + digitalna storitev.

    UI opomba:
      samoobdavčitev DA, vendar NI EU logika 23/23a;
      obračunani DDV gre v AOP 25 (odbitni del v 41).
    """
    row = row or {}
    if infer_supplier_kind(row, party) != "THIRD":
        return False
    name = normalize_text(row.get("supplier_name") or ((party or {}).get("name") if party else ""))
    if not name:
        return False
    blob = name.casefold()
    return any(
        hint in blob
        for hint in (
            "openai",
            "open ai",
            "fiverr",
            "upwork",
            "market street",
            "san francisco",
            "california",
        )
    )


def infer_supplier_kind(
    row: Mapping[str, Any] | None = None,
    party: Mapping[str, Any] | None = None,
) -> SupplierKind:
    """
    Opredelitev dobavitelja za DDV/obveznosti.

    Prednost: eksplicitni supplier_kind na vrstici → MRN v besedilu → stranka → DDV ID.
    """
    row = row or {}
    explicit = normalize_supplier_kind(row_supplier_kind(row) or row.get("supplier_kind"))
    if explicit in ("SI", "EU", "THIRD", "NONE", "UVOZ", "MRN"):
        # Shranjen EU, a je US/CN (OpenAI, Foshan) → tretja, ne EU
        if explicit in {"EU", "THIRD"}:
            try:
                from trops_studio.pr_list_view import pr_supplier_region

                region = pr_supplier_region(row, party)
                if region == "FOREIGN":
                    return "THIRD"
                if region == "EU":
                    return "EU"
                if region == "SI":
                    return "SI"
            except Exception:
                pass
        return explicit  # type: ignore[return-value]
    if is_mrn_row(row):
        return "MRN"

    vat = normalize_vat_id(
        row.get("vat_id")
        or row.get("tax_number")
        or (party or {}).get("vat_id")
        or (party or {}).get("tax_number")
    )
    cc = normalize_text((party or {}).get("country") or row.get("country"))[:2].upper()
    is_foreign = bool((party or {}).get("is_foreign") or row.get("is_foreign"))

    if vat.startswith("SI"):
        return "SI"
    if cc == "SI" and not is_foreign:
        tax = normalize_text((party or {}).get("tax_number") or row.get("tax_number"))
        if not vat and not tax:
            return "NONE"
        return "SI"
    if len(vat) >= 2 and vat[:2].isalpha():
        cc = cc or vat[:2]
    if cc in EU_VAT_COUNTRIES or (vat and is_eu_vat_id(vat) and vat[:2] in EU_VAT_COUNTRIES):
        return "EU"
    if is_foreign or (cc and cc != "SI"):
        return "THIRD"

    # Naziv / regija (brez krožnega importa ob uvozu modula)
    try:
        from trops_studio.pr_list_view import pr_supplier_region

        region = pr_supplier_region(row, party)
        if region == "EU":
            return "EU"
        if region == "FOREIGN":
            return "THIRD"
        if region == "SI" and not vat:
            return "NONE"
        if region == "SI":
            return "SI"
    except Exception:
        pass

    if not vat:
        return "NONE"
    return "SI"


def is_third_country_supplier(
    row: Mapping[str, Any] | None = None,
    party: Mapping[str, Any] | None = None,
) -> bool:
    """US, CN, IL … — izven EU (AOP 25, ne 23/23a)."""
    kind = infer_supplier_kind(row, party)
    return kind == "THIRD"


def third_country_kpr_bases(row: Mapping[str, Any]) -> dict[str, Any]:
    """Tretje države: nabava → KPR P8 (AOP 31); ne P9/31a, P10/32, P11/32a."""
    net = decimal_value(row.get("net_taxable"))
    f76a = decimal_value(row.get("f76a"))
    eu_g = decimal_value(row.get("eu_goods"))
    eu_s = decimal_value(row.get("eu_services"))
    if is_third_country_supplier(row):
        return {
            "P8": net + f76a + eu_g + eu_s,
            "P9": decimal_value("0"),
            "P10": decimal_value("0"),
            "P11": decimal_value("0"),
        }
    return {"P8": net, "P9": f76a, "P10": eu_g, "P11": eu_s}


def pr_vat_kind(row: Mapping[str, Any]) -> VatKind:
    """
    Tip DDV prometa za PR (en račun → en nabor 160/260).

    Prednost: EU blago → EU storitve → 76.a → opredelitev stranke + SA → domači.
    """
    eu_g = is_nonzero(row.get("eu_goods"))
    eu_s = is_nonzero(row.get("eu_services"))
    f76a = is_nonzero(row.get("f76a"))
    self_assessment, _vd, _ = resolve_pr_vat_flags(row)
    supplier = normalize_supplier_kind(row.get("supplier_kind")) or infer_supplier_kind(row)

    # MRN = carinska deklaracija za BLAGO → 16030/26046 (+ DDV-O 26)
    if supplier == "MRN" or (not supplier and is_mrn_row(row)):
        return "import_goods"
    if supplier == "UVOZ":
        return "import_goods"
    if supplier == "THIRD":
        # US/CN/IL niso EU — P10/P11 na tujcu ne smejo dati 16044/23a
        if eu_g:
            return "foreign_goods"
        return "foreign_services"
    if eu_g:
        return "eu_goods"
    if eu_s:
        return "eu_services"
    if f76a:
        return "foreign_services"

    if supplier == "EU":
        # SA na osnovi 08 (storitve B2B) → EU storitve 16044/26044
        return "eu_services" if self_assessment else "domestic"
    if supplier == "NONE":
        # prazen DDV + SA → tujci storitve (OpenAI); sicer domači nezavezanec
        return "foreign_services" if self_assessment else "domestic"
    # SI
    if self_assessment:
        return "foreign_services"
    return "domestic"


def ir_vat_kind(row: Mapping[str, Any]) -> VatKind:
    """IR: privzeto domači izhodni; EU stolpci redki."""
    if is_nonzero(row.get("eu_goods")):
        return "eu_goods"
    if is_nonzero(row.get("eu_services")):
        return "eu_services"
    return "domestic"


def kind_label(kind: VatKind) -> str:
    return {
        "domestic": "domači",
        "eu_goods": "EU blago",
        "eu_services": "EU storitve",
        "foreign_services": "tujci (storitve)",
        "foreign_goods": "tujci (blago)",
        "import_goods": "uvoz blaga",
    }.get(kind, kind)


def supplier_kind_label(kind: SupplierKind | str) -> str:
    return {
        "SI": "Domači (SI)",
        "EU": "EU",
        "THIRD": "Tretje države (izven EU)",
        "NONE": "Nezavezanec",
        "UVOZ": "Uvoz (odbitni DDV)",
        "MRN": "MRN blago SA (16030/26046 → 26)",
    }.get(normalize_supplier_kind(kind) or kind, str(kind))
