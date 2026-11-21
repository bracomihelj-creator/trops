"""PR seznam: regija dobavitelja + vrstice odhodkov (za treeview +/-)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping, Sequence

from trops_studio.accounts import allocate_pr_accounts
from trops_studio.money import (
    decimal_value,
    infer_country_code,
    is_nonzero,
    normalize_text,
    normalize_vat_id,
)

ZERO = Decimal("0.00")

# EU (brez SI) — za filter »EU« vs »Domači«
EU_COUNTRY_CODES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
        "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
        "RO", "SE", "SK",
    }
)

# Namigi iz naziva (vrstni red: bolj specifično najprej — Ireland pred Limited)
_NAME_COUNTRY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.I), cc)
    for pat, cc in (
        (r"\bireland\b|\bdublin\b", "IE"),
        (r"\bnederland|\bholland\b|\bamsterdam\b", "NL"),
        (r"\bauustria\b|\bwien\b|\bvienna\b", "AT"),
        (r"\bgermany\b|\bdeutschland\b|\bgmbh\b", "DE"),
        (r"\bfrance\b|\bsarl\b", "FR"),
        (r"\bitaly\b|\bitalia\b", "IT"),
        (r"\bspain\b|\bespana\b", "ES"),
        (r"\bcroatia\b|\bhrvatska\b|\bzagreb\b", "HR"),
        (r"\blithuania\b|\blithuanian\b|\bvilnius\b|\bpaupio\b", "LT"),
        (
            r"\bfoshan\b|\bshenzhen\b|\bshanghai\b|\bbeijing\b|\bguangzhou\b|"
            r"\bhangzhou\b|\bchina\b|\bchinese\b|\bhong\s*kong\b",
            "CN",
        ),
        (r"\bindia\b|\bmumbai\b|\bbangalore\b", "IN"),
        (r"\bsingapore\b", "SG"),
        (r"\bswitzerland\b|\bschweiz\b|\bzurich\b", "CH"),
        (
            r"\bopenai\b|\bfiverr\b|\bupwork\b|\bmarket\s*street\b|"
            r"\bsan\s*francisco\b|\bcalifornia\b|\bunited\s+states\b|\busa\b|"
            r"\bllc\b|\binc\.?\b|\bcorp\.?\b",
            "US",
        ),
        # Limited/Ltd šele po Ireland (Google Ireland Limited → IE, ne GB)
        (r"\bunited\s+kingdom\b|\bengland\b|\blondon\b|\bltd\.?\b|\blimited\b", "GB"),
    )
)


def country_from_supplier_name(name: str) -> str:
    """ISO država iz naziva dobavitelja (Ireland → IE, Foshan → CN, …)."""
    text = normalize_text(name)
    if not text:
        return ""
    for pattern, cc in _NAME_COUNTRY_HINTS:
        if pattern.search(text):
            return cc
    if re.search(r"\bslovenija\b|\bslovenia\b", text, re.I):
        return "SI"
    if re.search(r"\bd\.?\s*o\.?\s*o\.?\b|\bs\.?\s*p\.?\b", text, re.I):
        return "SI"
    return ""


def infer_party_kind(
    *,
    vat_id: Any = "",
    tax_number: Any = "",
    country: Any = "",
    is_foreign: bool = False,
    name: Any = "",
    book: str = "",
) -> str:
    """SI / EU / THIRD / NONE — isto kot obrazec Stranke.

    Zavezanec = predpona SI, DE, CH, US… (IR: nujno preveri).
    PR brez predpone = podjetje, ni zavezanec za DDV (ne 8-mestna SI).
    """
    from trops_studio.money import has_country_prefixed_vat_id
    from trops_studio.vies_client import EU_VAT_COUNTRIES, is_eu_vat_id

    vat = normalize_vat_id(vat_id or tax_number)
    cc = normalize_text(country)[:2].upper()
    if cc == "GR":
        cc = "EL"
    hint = country_from_supplier_name(str(name or ""))
    if has_country_prefixed_vat_id(vat):
        prefix = vat[:2].upper()
        if prefix == "GR":
            prefix = "EL"
        if prefix == "SI":
            return "SI"
        if prefix in EU_VAT_COUNTRIES or (is_eu_vat_id(vat) and prefix in EU_VAT_COUNTRIES):
            return "EU"
        return "THIRD"
    # brez predpone
    if (book or "").upper() == "IR":
        return "NONE"
    if is_foreign or (hint and hint != "SI") or (cc and cc != "SI"):
        return "THIRD"
    if (book or "").upper() == "PR":
        return "NONE"
    if hint and hint != "SI":
        return "THIRD"
    return "NONE"


def _norm_cc(code: str) -> str:
    cc = normalize_text(code)[:2].upper()
    if cc == "GR":
        return "EL"
    if cc in {"", "XX"}:
        return ""
    return cc if len(cc) == 2 and cc.isalpha() else ""


def pr_supplier_country(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> str:
    """ISO država (2 črki) iz DDV / stranke / naziva — ne privzemi SI za tujce."""
    vat = normalize_vat_id(
        row.get("vat_id")
        or row.get("tax_number")
        or ((party or {}).get("vat_id") if party else "")
        or ((party or {}).get("tax_number") if party else "")
    )
    if len(vat) >= 2 and vat[:2].isalpha():
        return _norm_cc(vat[:2])

    name = normalize_text(row.get("supplier_name") or ((party or {}).get("name") if party else ""))
    name_cc = country_from_supplier_name(name)

    party_cc = ""
    foreign = False
    if party:
        party_cc = _norm_cc(str(party.get("country") or ""))
        foreign = bool(party.get("is_foreign"))

    # Tujec v šifrantu z napačno SI (Minimax privzeto) → zaupaj imenu
    if foreign and party_cc in {"", "SI"}:
        return name_cc or party_cc or ""

    if party_cc and party_cc != "SI":
        return party_cc

    if name_cc and name_cc != "SI":
        return name_cc

    if party_cc == "SI" and not foreign:
        # SI samo če ime ni očitno tuje
        if name_cc and name_cc != "SI":
            return name_cc
        return "SI"

    inferred = infer_country_code(
        country=party_cc,
        postal_code=(party or {}).get("postal_code") if party else "",
        address=(party or {}).get("address") if party else "",
        city=(party or {}).get("city") if party else "",
        vat_id=vat,
    )
    inferred = _norm_cc(inferred or "")
    if inferred and inferred != "SI":
        return inferred
    if name_cc:
        return name_cc
    if inferred == "SI":
        return "SI"
    return ""


def _vat_country_prefix(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> str:
    vat = normalize_vat_id(
        row.get("vat_id")
        or row.get("tax_number")
        or ((party or {}).get("vat_id") if party else "")
        or ((party or {}).get("tax_number") if party else "")
    )
    prefix = vat[:2] if len(vat) >= 2 and vat[:2].isalpha() else ""
    return _norm_cc(prefix)


def pr_supplier_region(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> str:
    """SI | EU | FOREIGN (tretja država = samo izven EU, ne SI/AT/DE/…)."""
    prefix = _vat_country_prefix(row, party)
    cc = pr_supplier_country(row, party)
    # DDV predpona ima prednost: AT/DE/IE… nikoli tretja država.
    if prefix == "SI" or cc == "SI":
        return "SI"
    if prefix in EU_COUNTRY_CODES or cc in EU_COUNTRY_CODES:
        return "EU"
    if cc and cc not in EU_COUNTRY_CODES:
        return "FOREIGN"
    if prefix and prefix not in EU_COUNTRY_CODES:
        return "FOREIGN"
    if party and party.get("is_foreign"):
        # is_foreign brez EU/SI kode = tretja; EU tujec (AT) je že zgoraj EU
        return "FOREIGN"
    name = normalize_text(row.get("supplier_name") or ((party or {}).get("name") if party else ""))
    name_cc = country_from_supplier_name(name)
    if name_cc == "SI":
        return "SI"
    if name_cc in EU_COUNTRY_CODES:
        return "EU"
    if name_cc:
        return "FOREIGN"
    return "SI"


def pr_is_third_country(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> bool:
    """True samo za izven EU (US/CN/GB/CH…) — ne SI in ne EU 10/11."""
    return pr_corrected_region(row, party) == "FOREIGN"


def region_label(region: str) -> str:
    return {
        "SI": "Domači",
        "EU": "EU",
        "FOREIGN": "Tretja država",
    }.get(region, region)


SI_VAT_NOTE = "SI+DŠ na EU/tujcu"


def is_si_ds_vat(value: Any) -> bool:
    """True, če je ID za DDV slovenska predpona SI… ali sama 8-mestna DŠ."""
    vat = normalize_vat_id(value)
    if not vat:
        return False
    if vat.startswith("SI"):
        body = vat[2:]
        return bool(body) and any(ch.isdigit() for ch in body)
    return vat.isdigit() and len(vat) == 8


def apply_pr_si_vat_flag(row: dict[str, Any], party: Mapping[str, Any] | None = None) -> bool:
    """Ob uvozu / kontroli: status Popravi + opomba. True, če je napaka."""
    if not pr_si_vat_on_non_domestic(row, party):
        return False
    notes = normalize_text(row.get("notes"))
    if SI_VAT_NOTE not in notes:
        row["notes"] = f"{SI_VAT_NOTE} | {notes}".strip(" |") if notes else SI_VAT_NOTE
    status = str(row.get("status") or "").casefold()
    if status in {"", "osnutek", "poglej"}:
        row["status"] = "Popravi"
    return True


def pr_looks_non_domestic(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> bool:
    """EU / tretja — tudi če je na listini napačno SI+DŠ."""
    if is_nonzero(row.get("eu_goods")) or is_nonzero(row.get("eu_services")):
        return True
    try:
        from trops_studio.vat_accounts import row_supplier_kind

        kind = str(row_supplier_kind(row) or "")
    except Exception:
        kind = str(row.get("supplier_kind") or "")
    if kind in {"EU", "THIRD", "UVOZ", "MRN"}:
        return True
    name = normalize_text(row.get("supplier_name") or ((party or {}).get("name") if party else ""))
    name_cc = country_from_supplier_name(name)
    if name_cc and name_cc != "SI":
        return True
    if party:
        party_cc = _norm_cc(str(party.get("country") or ""))
        if party.get("is_foreign") or (party_cc and party_cc != "SI"):
            return True
    return False


def pr_si_vat_on_non_domestic(
    row: Mapping[str, Any],
    party: Mapping[str, Any] | None = None,
) -> bool:
    """Kontrola: kdor ni Domači, ne sme imeti ID za DDV SI+DŠ."""
    vat = (
        row.get("vat_id")
        or row.get("tax_number")
        or ((party or {}).get("vat_id") if party else "")
        or ((party or {}).get("tax_number") if party else "")
    )
    return is_si_ds_vat(vat) and pr_looks_non_domestic(row, party)


def pr_corrected_region(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> str:
    """Regija za prikaz: pri SI+DŠ na tujcu → EU ali tretja, ne Domači."""
    geo = pr_supplier_region(row, party)
    if not pr_si_vat_on_non_domestic(row, party):
        return geo
    name = normalize_text(row.get("supplier_name") or ((party or {}).get("name") if party else ""))
    name_cc = country_from_supplier_name(name)
    party_cc = _norm_cc(str((party or {}).get("country") or "")) if party else ""
    cc = name_cc or party_cc
    if cc and cc not in EU_COUNTRY_CODES and cc != "SI":
        return "FOREIGN"
    return "EU"


def pr_p8_amount(row: Mapping[str, Any], region: str) -> Decimal:
    """KPR 08 = Excel »8-Vred brez DDV« za SI in tretje države (ne EU 10/11).

    Osnova 5 % (F27) je »od tega« v polju 8, ne dodatno — sicer se 178,20 podvoji.
    """
    if region not in {"SI", "FOREIGN"}:
        return ZERO
    amount = decimal_value(row.get("net_taxable"))
    if not is_nonzero(amount):
        amount = decimal_value(row.get("base_5"))
    if region == "FOREIGN":
        # Na tujcu P10/P11 ne obstajata — znesek spada v 08.
        amount += decimal_value(row.get("eu_goods")) + decimal_value(row.get("eu_services"))
    return amount


def pr_odhodek_lines(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Vrstice odhodkov za drevo (samo tiste z zneskom <> 0, tudi storno).
    tip: 08 | 14 | 9a | 10 | 11 | excl — vsaka s svojim kontom.
    """
    lines: list[dict[str, Any]] = []
    acc = allocate_pr_accounts(row)
    od01 = acc["odhodek01"]
    od07 = acc["odhodek07"] or od01
    od10 = acc["odhodek10"] or od07 or od01
    od11 = acc["odhodek11"] or od07 or od01
    od_ex = acc["odhodek_excluded"]

    net = decimal_value(row.get("net_taxable"))
    if is_nonzero(net):
        lines.append(
            {"tip": "08", "label": "08 — osnova", "amount": net, "konto": od01 or ""}
        )
    exempt = (
        decimal_value(row.get("exempt_on"))
        + decimal_value(row.get("exempt_non"))
        + decimal_value(row.get("exempt_os"))
    )
    if is_nonzero(exempt):
        lines.append(
            {"tip": "14", "label": "14 — oproščeno", "amount": exempt, "konto": od07 or ""}
        )
    f76a = decimal_value(row.get("f76a"))
    if is_nonzero(f76a):
        lines.append(
            {"tip": "9a", "label": "9a — 76.a člen", "amount": f76a, "konto": od07 or ""}
        )
    eu_g = decimal_value(row.get("eu_goods"))
    if is_nonzero(eu_g):
        lines.append(
            {"tip": "10", "label": "10 — BL EU", "amount": eu_g, "konto": od10 or ""}
        )
    eu_s = decimal_value(row.get("eu_services"))
    if is_nonzero(eu_s):
        lines.append(
            {"tip": "11", "label": "11 — ST EU", "amount": eu_s, "konto": od11 or ""}
        )
    excluded = decimal_value(row.get("excluded"))
    if is_nonzero(excluded):
        lines.append(
            {
                "tip": "excl",
                "label": "Ne gre v knjigo",
                "amount": excluded,
                "konto": od_ex or "",
            }
        )
    return lines


def odhodek_summary(lines: Sequence[Mapping[str, Any]]) -> str:
    konta: list[str] = []
    seen: set[str] = set()
    for line in lines:
        code = normalize_text(line.get("konto"))
        if code and code not in seen:
            seen.add(code)
            konta.append(code)
    if not konta:
        return ""
    if len(konta) == 1:
        return konta[0]
    if len(konta) <= 3:
        return "+".join(konta)
    return f"{len(konta)}×"
