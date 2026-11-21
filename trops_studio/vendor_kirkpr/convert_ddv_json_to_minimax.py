from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from lxml import etree


NS = "https://moj.minimax.si/SI/CommonWeb/documents/schemas/miniMAXUvozKnjigovodstvo"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_URL = f"{NS}.xsd"

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

RATE_INFO = {
    "S": (Decimal("0.22"), "16000", "26000"),
    "Z": (Decimal("0.095"), "16001", "26001"),
    "0": (Decimal("0.05"), "16002", "26002"),
}

EU_COUNTRIES = {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
        "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL",
        "PT", "RO", "SE", "SK",
    }

REPORTING = {
    "1": "Obračun",
    "2": "Samoprijava",
    "3": "SamoprijavaObresti",
}


def money(value: object) -> Decimal:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def amount(row: dict, *names: str) -> Decimal:
    return sum((money(row.get(name)) for name in names), ZERO)


def fmt(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def add(parent: etree._Element, tag: str, value: object | None = None) -> etree._Element:
    element = etree.SubElement(parent, q(tag))
    if value is not None:
        element.text = str(value)
    return element


def normalized_country(value: object) -> str:
    country = re.sub(r"[^A-Za-z]", "", str(value or "")).upper()
    return country[:2] if len(country) >= 2 else "SI"


def normalized_tax_id(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()


def party_identity(country: str, tax_id: str) -> str:
    if not tax_id:
        return ""
    return tax_id if tax_id.startswith(country) else f"{country}{tax_id}"


def party_code(name: str, country: str, tax_id: str, row_number: object) -> str:
    identity = party_identity(country, tax_id)
    if identity:
        return identity[:30]
    slug = re.sub(r"[^0-9A-Za-z]", "", name.upper())[:20] or "STRANKA"
    return f"{slug}-{row_number}"[:30]


def _party_from_override(row: dict, *, fallback_name: str, fallback_country: str, fallback_tax: str) -> dict:
    """Uporabi __party__ / __party_code__ (Minimax šifra), sicer SI+davčna."""
    override = row.get("__party__") if isinstance(row.get("__party__"), dict) else None
    if override and str(override.get("code") or "").strip():
        return {
            "code": str(override.get("code") or "").strip()[:30],
            "name": str(override.get("name") or fallback_name).strip() or fallback_name,
            "country": normalized_country(override.get("country") or fallback_country),
            "tax_id": normalized_tax_id(override.get("tax_id") or fallback_tax),
        }
    code_override = str(row.get("__party_code__") or row.get("__party_code_override__") or "").strip()
    name = fallback_name
    country = normalized_country(fallback_country)
    tax_id = normalized_tax_id(fallback_tax)
    return {
        "code": (code_override or party_code(name, country, tax_id, row.get("ZAPST")))[:30],
        "name": name,
        "country": country,
        "tax_id": tax_id,
    }


def party_from_kir(row: dict) -> dict:
    country = normalized_country(row.get("P6"))
    tax_id = normalized_tax_id(row.get("P6DS"))
    name = str(row.get("P5") or "Neznana stranka").strip()
    return _party_from_override(
        row, fallback_name=name, fallback_country=country, fallback_tax=tax_id
    )


def party_from_kpr(row: dict) -> dict:
    country = normalized_country(row.get("P7"))
    tax_id = normalized_tax_id(row.get("P7DS"))
    name = str(row.get("P6") or "Neznan dobavitelj").strip()
    return _party_from_override(
        row, fallback_name=name, fallback_country=country, fallback_tax=tax_id
    )


def make_root(parties: Iterable[dict]) -> tuple[etree._Element, etree._Element]:
    root = etree.Element(q("miniMAXUvozKnjigovodstvo"), nsmap={None: NS, "xsi": XSI})
    root.set(f"{{{XSI}}}schemaLocation", f"{NS} {SCHEMA_URL}")

    stranke = add(root, "Stranke")
    unique = {party["code"]: party for party in parties}
    for party in sorted(unique.values(), key=lambda item: item["code"]):
        stranka = add(stranke, "Stranka")
        add(stranka, "Sifra", party["code"])
        add(stranka, "Naziv", party["name"][:250])
        add(stranka, "KraticaDrzave", party["country"])
        if party["tax_id"]:
            add(stranka, "DavcniZavezanec", "D")
            add(stranka, "DavcnaStevilka", party["tax_id"][:30])
            add(
                stranka,
                "IdentifikacijskaStevilka",
                party_identity(party["country"], party["tax_id"])[:30],
            )
        add(stranka, "SifraDenarneEnote", "EUR")

    return root, add(root, "Temeljnice")


def allocate_bases(total_base: Decimal, taxes: dict[str, Decimal]) -> tuple[dict[str, Decimal], Decimal]:
    active = [code for code in ("S", "Z", "0") if taxes.get(code, ZERO) != ZERO]
    if not active:
        return {}, ZERO
    if len(active) == 1:
        return {active[0]: total_base}, ZERO

    allocated = {
        code: (taxes[code] / RATE_INFO[code][0]).quantize(CENT, rounding=ROUND_HALF_UP)
        for code in active
    }
    residual = total_base - sum(allocated.values(), ZERO)
    largest = max(active, key=lambda code: abs(allocated[code]))
    allocated[largest] += residual
    return allocated, residual


def is_eu_country(code: str) -> bool:
    cc = str(code or "").strip().upper()[:2]
    if cc == "GR":
        cc = "EL"
    return cc in EU_COUNTRIES


def issued_invoice_vat_rates(row: dict) -> list[dict]:
    """IR DDV za Minimax.

    Prodaja v EU (P6 ∈ EU, ne SI): splošna osnova (S) BLAGO brez DDV.
    Ne gre pod Oproščeno in ne pod Storitev.
    Domače (Fitness/Darila) ostane storitev.
    """
    eu_sale = is_eu_country(str(row.get("P6") or ""))
    taxable = amount(row, "P7")
    eu_goods = amount(row, "P10")
    eu_services = amount(row, "P11")
    exempt = amount(row, "P9")
    non_taxable = amount(row, "P8", "P12", "P13", "P27")
    vat = {"S": amount(row, "P14"), "Z": amount(row, "P15"), "0": amount(row, "P16")}
    allocated, _residual = allocate_bases(taxable, vat)
    rates: list[dict] = []

    def add_or_merge(
        code: str,
        *,
        goods_base: Decimal = ZERO,
        goods_vat: Decimal = ZERO,
        svc_base: Decimal = ZERO,
        svc_vat: Decimal = ZERO,
    ) -> None:
        payload: dict[str, Decimal] = {}
        if goods_base:
            payload["Osnova"] = goods_base
        if goods_vat:
            payload["DDV"] = goods_vat
        if svc_base:
            payload["StoritevOsnova"] = svc_base
        if svc_vat:
            payload["StoritevDDV"] = svc_vat
        if not payload:
            return
        existing = next((item for item in rates if item.get("code") == code), None)
        if existing:
            for key, value in payload.items():
                existing[key] = money(existing.get(key, ZERO)) + value
            return
        rates.append({"code": code, **payload})

    if eu_sale:
        for code, base in allocated.items():
            add_or_merge(code, goods_base=base, goods_vat=vat[code])
        goods = eu_goods + eu_services
        if taxable and not allocated:
            goods += taxable
        if goods:
            add_or_merge("S", goods_base=goods)
        if exempt:
            add_or_merge("O", svc_base=exempt)
        if non_taxable:
            add_or_merge("N", svc_base=non_taxable)
    else:
        for code, base in allocated.items():
            add_or_merge(code, svc_base=base, svc_vat=vat[code])
        goods = eu_goods + eu_services
        if goods:
            add_or_merge("S", goods_base=goods)
        if exempt:
            add_or_merge("O", svc_base=exempt)
        if non_taxable:
            add_or_merge("N", svc_base=non_taxable)
        if taxable and not allocated:
            add_or_merge("N", svc_base=taxable)
    return rates


def add_ddv_rates(parent: etree._Element, rates: list[dict]) -> None:
    if not rates:
        return
    ddv_stopnje = add(parent, "DDVStopnje")
    ordered_fields = (
        "Osnova", "DDV", "NeodbitiDDVOsnova", "NeodbitiDDV",
        "StoritevOsnova", "StoritevDDV", "StoritevNeodbitiDDVOsnova",
        "StoritevNeodbitiDDV",
    )
    for rate in rates:
        stopnja = add(ddv_stopnje, "DDVStopnja")
        add(stopnja, "SifraStopnjeDDV", rate["code"])
        for field in ordered_fields:
            value = rate.get(field, ZERO)
            if value != ZERO:
                add(stopnja, field, fmt(value))


def _add_ddv_row(
    ddv: etree._Element,
    *,
    book: str,
    date_ddv: str,
    date_booking: str,
    partner_code_value: str,
    invoice_number: str,
    date_invoice: str,
    reporting: str,
    rates: list[dict],
    date_received: str | None = None,
    date_service: str | None = None,
    self_assessment: bool = False,
    real_estate: Decimal = ZERO,
    fixed_assets: Decimal = ZERO,
    linked_self_assessment: str | None = None,
) -> None:
    ddv_row = add(ddv, "DDVVrstica")
    header = add(ddv_row, "DDVGlava")
    add(header, "DatumDDV", date_ddv)
    add(header, "KnjigaDDV", book)
    add(header, "DatumKnjizenjaDDV", date_booking)
    add(header, "SifraStranke", partner_code_value)
    add(header, "Listina", invoice_number[:250])
    add(header, "DatumListine", date_invoice)
    if date_received:
        add(header, "DatumPrejema", date_received)
    if date_service:
        add(header, "DatumOpravljanja", date_service)
    if fixed_assets != ZERO:
        add(header, "OsnovnoSredstvo", fmt(fixed_assets))
    if real_estate != ZERO:
        add(header, "Nepremicnina", fmt(real_estate))
    if self_assessment:
        add(header, "Samoobdavcitev", "D")
    if linked_self_assessment:
        add(header, "PovezanaSamoobdavcitev", linked_self_assessment[:250])
    # VrstaPorocanja namerno IZPUŠČENA — sicer Minimax knjiga PR v »Številka
    # listine« vpiše »Obracun;…« / »Samoprijava;…« pred številko.
    _ = reporting
    add_ddv_rates(ddv_row, rates)


def add_ddv(
    journal: etree._Element,
    *,
    book: str,
    date_ddv: str,
    date_booking: str,
    partner_code_value: str,
    invoice_number: str,
    date_invoice: str,
    reporting: str,
    rates: list[dict],
    date_received: str | None = None,
    date_service: str | None = None,
    self_assessment: bool = False,
    real_estate: Decimal = ZERO,
    fixed_assets: Decimal = ZERO,
) -> None:
    """
    DDV blok za PR/IR.

    Pri samoobdavčitvi: PR vrstica (odbitni → 41) + IR vrstica (obračunani → 23/23a/25/26).
    Brez IR twin-a Minimax DDV-O polja 23–26 ostanejo 0.
    """
    ddv = add(journal, "DDV")
    kwargs = dict(
        date_ddv=date_ddv,
        date_booking=date_booking,
        partner_code_value=partner_code_value,
        invoice_number=invoice_number,
        date_invoice=date_invoice,
        reporting=reporting,
        rates=rates,
        date_received=date_received,
        date_service=date_service,
        self_assessment=self_assessment,
        real_estate=real_estate,
        fixed_assets=fixed_assets,
    )
    _add_ddv_row(ddv, book=book, **kwargs)
    # SA: druga DDV vrstica v knjigo IR (obračunani DDV) — enaka osnova/znesek
    if self_assessment and str(book or "").upper() == "PR":
        _add_ddv_row(
            ddv,
            book="IR",
            linked_self_assessment=invoice_number[:250],
            **kwargs,
        )


def add_line(
    lines: etree._Element,
    *,
    date: str,
    description: str,
    account: str,
    partner: str | None = None,
    due: str | None = None,
    service_date: str | None = None,
    reference: str | None = None,
    debit: Decimal = ZERO,
    credit: Decimal = ZERO,
) -> None:
    line = add(lines, "VrsticaTemeljnice")
    add(line, "DatumKnjizbe", date)
    add(line, "OpisVrsticeTemeljnice", description[:250])
    add(line, "SifraKonta", account)
    if partner:
        add(line, "SifraStranke", partner)
    if due:
        add(line, "DatumZapadlosti", due)
    if service_date:
        add(line, "DatumOpravljanja", service_date)
    if reference:
        add(line, "VezaZaPlacilo", reference[:30])
    add(line, "SifraDenarneEnote", "EUR")
    if debit != ZERO:
        add(line, "ZnesekVBremeVDenarniEnoti", fmt(debit))
    if credit != ZERO:
        add(line, "ZnesekVDobroVDenarniEnoti", fmt(credit))
    if debit != ZERO:
        add(line, "ZnesekVBremeVDomaciDenarniEnoti", fmt(debit))
    if credit != ZERO:
        add(line, "ZnesekVDobroVDomaciDenarniEnoti", fmt(credit))


def make_header(temeljnice: etree._Element, kind: str, date: str, invoice: str) -> etree._Element:
    journal = add(temeljnice, "Temeljnica")
    header = add(journal, "GlavaTemeljnice")
    add(header, "SifraVrsteTemeljnice", kind)
    add(header, "DatumTemeljnice", date)
    add(header, "OpisGlaveTemeljnice", invoice[:250])
    return journal


def reporting_value(row: dict) -> str:
    """Minimax API: Obracun | Samoprijava | SamoprijavaObresti (ne številka 1/2/3)."""
    raw = str(row.get("OBRAVNAVA") or "1").strip()
    folded = raw.casefold().replace("č", "c").replace("ć", "c")
    if folded in {"3", "samoprijavaobresti"} or (
        "samoprijava" in folded and "obrest" in folded
    ):
        return "SamoprijavaObresti"
    if folded in {"2", "samoprijava"}:
        return "Samoprijava"
    return "Obracun"


def boolean_value(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"1", "D", "DA", "R", "TRUE", "YES", "Y"}:
            return True
        if normalized in {"0", "N", "NE", "FALSE", "NO"}:
            return False
    return bool(value)


def vat_is_deductible_row(row: dict) -> bool:
    for field in ("__ddv_se_odbija__", "MINIMAX_DDV_SE_ODBIJA", "DDV_SE_ODBIJA"):
        parsed = boolean_value(row.get(field))
        if parsed is not None:
            return parsed
    for field in ("__reprezentanca__", "REPREZENTANCA", "R"):
        parsed = boolean_value(row.get(field))
        if parsed is not None:
            return not parsed
    return True


def source_self_assessment_row(row: dict) -> bool:
    return any(amount(row, f"P{i}") != ZERO for i in (9, 10, 11))


def is_self_assessment_row(row: dict) -> bool:
    for field in ("__samoobdavcitev__", "MINIMAX_SAMOOBDAVCITEV", "SAMOOBDAVCITEV"):
        parsed = boolean_value(row.get(field))
        if parsed is not None:
            return parsed
    return source_self_assessment_row(row)


def is_kir_self_assessment(row: dict, kpr_invoice_numbers: set[str]) -> bool:
    reverse_vat = amount(row, *(f"P{i}" for i in range(17, 27)))
    return str(row.get("P3") or "") in kpr_invoice_numbers and reverse_vat != ZERO


def build_issued(kir_rows: list[dict], kpr_rows: list[dict]) -> tuple[etree._Element, list[dict]]:
    kpr_numbers = {
        str(row.get("P3") or "")
        for row in kpr_rows
        if source_self_assessment_row(row) or is_self_assessment_row(row)
    }
    included = [row for row in kir_rows if not is_kir_self_assessment(row, kpr_numbers)]
    parties = []
    for row in included:
        payment = str(row.get("__payment_account__") or "1200").strip() or "1200"
        # Integra Paragoni: gotovina/kartice — brez Stranke / Končni kupci
        if payment in {"1000", "1650"}:
            continue
        parties.append(party_from_kir(row))
    root, temeljnice = make_root(parties)
    audit: list[dict] = []

    for row in included:
        partner = party_from_kir(row)
        invoice = str(row.get("P3") or "").strip()
        description = str(row.get("__opis__") or invoice).strip()[:250] or invoice
        line_description = (
            str(row.get("__opis_knjizba__") or description).strip()[:250] or description
        )
        date_invoice = str(row.get("P4") or row.get("P2"))[:10]
        date_ddv = str(row.get("P2") or date_invoice)[:10]

        taxable = amount(row, "P7")
        exempt = amount(row, "P9", "P10", "P11")
        non_taxable = amount(row, "P8", "P12", "P13", "P27")
        vat = {"S": amount(row, "P14"), "Z": amount(row, "P15"), "0": amount(row, "P16")}
        rates = issued_invoice_vat_rates(row)

        net = taxable + exempt + non_taxable
        output_vat = sum(vat.values(), ZERO)
        gross = net + output_vat

        payment = str(row.get("__payment_account__") or "1200").strip() or "1200"
        cash_card = payment in {"1000", "1650"}
        partner_code = "" if cash_card else partner["code"]
        journal_type = str(row.get("__journal_type__") or ("DI" if cash_card else "IR")).strip().upper() or "IR"
        vat_book = "IR"  # DDV knjiga IR tudi ko je vrsta temeljnice DI

        journal = make_header(temeljnice, journal_type, date_invoice, description)
        add_ddv(
            journal,
            book=vat_book,
            date_ddv=date_ddv,
            date_booking=date_ddv,
            partner_code_value=partner_code,
            invoice_number=invoice,
            date_invoice=date_invoice,
            date_service=date_invoice,
            reporting=reporting_value(row),
            rates=rates,
        )
        lines = add(journal, "VrsticeTemeljnice")
        debit_partner = "" if cash_card else partner_code
        add_line(
            lines,
            date=date_invoice,
            description=line_description,
            account=payment,
            partner=debit_partner or None,
            due=date_invoice if debit_partner else None,
            service_date=date_invoice if debit_partner else None,
            reference=invoice,
            debit=gross,
        )
        revenue_account = str(row.get("__konto__") or "7601").strip() or "7601"
        add_line(lines, date=date_invoice, description=line_description, account=revenue_account, credit=net)
        for code in ("S", "Z", "0"):
            if vat[code] != ZERO:
                add_line(
                    lines, date=date_invoice, description=line_description,
                    account=RATE_INFO[code][2], credit=vat[code],
                )

        assert gross == net + output_vat
        audit.append({
            "kind": "IR", "invoice": invoice, "party": partner["name"],
            "net": net, "vat": output_vat, "gross": gross,
            "residual": ZERO,
        })

    for row in kir_rows:
        if is_kir_self_assessment(row, kpr_numbers):
            audit.append({
                "kind": "KIR-samoobdavčitev", "invoice": str(row.get("P3") or ""),
                "party": str(row.get("P5") or ""), "net": ZERO,
                "vat": amount(row, *(f"P{i}" for i in range(17, 27))),
                "gross": ZERO, "residual": ZERO,
            })
    return root, audit


def supplier_account(country: str) -> str:
    if country == "SI":
        return "2200"
    if country in EU_COUNTRIES:
        return "2211"
    return "2210"


def build_received(kpr_rows: list[dict]) -> tuple[etree._Element, list[dict]]:
    parties = [party_from_kpr(row) for row in kpr_rows]
    root, temeljnice = make_root(parties)
    audit: list[dict] = []

    for row in kpr_rows:
        partner = party_from_kpr(row)
        invoice = str(row.get("P3") or "").strip()
        description = str(row.get("__opis__") or invoice).strip()[:250] or invoice
        line_description = (
            str(row.get("__opis_knjizba__") or description).strip()[:250] or description
        )
        date_booking = str(row.get("P2") or row.get("P5") or row.get("P4"))[:10]
        date_received = str(row.get("P4") or date_booking)[:10]
        date_invoice = str(row.get("P5") or date_received)[:10]

        domestic = amount(row, "P8")
        domestic_reverse = amount(row, "P9")
        eu_goods = amount(row, "P10")
        eu_services = amount(row, "P11")
        real_estate_taxed = amount(row, "P12")
        fixed_assets_taxed = amount(row, "P13")
        exempt = amount(row, "P14", "P15", "P16")
        # P12/P13 sta »od tega« OS (AOP 34/35) — osnova je že v P8 (AOP 31).
        taxable = domestic + domestic_reverse + eu_goods + eu_services
        service_total = domestic_reverse + eu_services
        goods_total = taxable - service_total
        self_assessment = is_self_assessment_row(row)
        vat_deductible = vat_is_deductible_row(row)
        # Tujci storitve (OpenAI/Fiverr): znesek je pogosto v P8, ne P11 —
        # sicer gre v Osnova (blago) in Minimax ne mapira pravilno v polje 25.
        vat_kind = str(row.get("__vat_kind__") or "").strip().lower()
        if vat_kind == "foreign_services" and taxable != ZERO:
            service_total = taxable
            goods_total = ZERO
        elif vat_kind in {"foreign_goods", "mrn"} and taxable != ZERO:
            goods_total = taxable
            service_total = ZERO

        input_vat = {
            "S": amount(row, "P18"),
            "Z": amount(row, "P19"),
            "0": amount(row, "P20"),
        }
        non_deductible_vat = amount(row, "P17")
        flat_rate_vat = amount(row, "P21")
        allocated, residual = allocate_bases(taxable, input_vat)

        rates: list[dict] = []
        for code, base in allocated.items():
            service_base = ZERO
            if taxable != ZERO and service_total != ZERO:
                service_base = (base * service_total / taxable).quantize(CENT, rounding=ROUND_HALF_UP)
            goods_base = base - service_base
            rate = {"code": code}
            if not vat_deductible:
                service_vat = ZERO
                if base != ZERO and service_base != ZERO:
                    service_vat = (input_vat[code] * service_base / base).quantize(CENT, rounding=ROUND_HALF_UP)
                goods_vat = input_vat[code] - service_vat
                if goods_base != ZERO:
                    rate["NeodbitiDDVOsnova"] = goods_base
                    rate["NeodbitiDDV"] = goods_vat
                if service_base != ZERO:
                    rate["StoritevNeodbitiDDVOsnova"] = service_base
                    rate["StoritevNeodbitiDDV"] = service_vat
            elif goods_base != ZERO:
                rate["Osnova"] = goods_base
                rate["DDV"] = input_vat[code]
            else:
                rate["StoritevOsnova"] = service_base
                rate["StoritevDDV"] = input_vat[code]
            rates.append(rate)

        if taxable != ZERO and not allocated:
            if service_total != ZERO and goods_total == ZERO:
                rates.append({"code": "N", "StoritevOsnova": taxable})
            else:
                rates.append({"code": "N", "Osnova": taxable})
        if exempt != ZERO:
            rates.append({"code": "O", "Osnova": exempt})

        net = taxable + exempt
        reported_vat = sum(input_vat.values(), ZERO) + flat_rate_vat
        deductible_vat = reported_vat if vat_deductible else ZERO
        expense = net + non_deductible_vat + (ZERO if vat_deductible else reported_vat)
        if self_assessment:
            payable = net + non_deductible_vat
        else:
            payable = net + non_deductible_vat + reported_vat

        journal = make_header(temeljnice, "PR", date_booking, description)
        # DDV obdobje = datum prejema (ne knjižbe). Če je maj zaključen, gre
        # listina s prejemom v juniju v junijski DDV (npr. EGIR 189).
        vat_period_date = date_received or date_booking
        add_ddv(
            journal,
            book="PR",
            date_ddv=vat_period_date,
            date_booking=vat_period_date,
            partner_code_value=partner["code"],
            invoice_number=invoice,
            date_invoice=date_invoice,
            date_received=date_received,
            date_service=date_invoice,
            reporting=reporting_value(row),
            rates=rates,
            self_assessment=self_assessment,
            real_estate=real_estate_taxed + amount(row, "P15"),
            fixed_assets=fixed_assets_taxed + amount(row, "P16"),
        )

        lines = add(journal, "VrsticeTemeljnice")
        payable_account = str(row.get("__placilo__") or "").strip() or supplier_account(partner["country"])
        add_line(
            lines, date=date_booking, description=line_description,
            account=payable_account, partner=partner["code"],
            due=date_invoice, service_date=date_invoice, reference=invoice, credit=payable,
        )
        # Strošek / DDV konti: brez stranke in brez DatumOpravljanja/Zapadlosti
        # (Minimax Account.CustomerEntry=N, InvoiceAccounting=N → sicer HTTP 409).
        expense_account = str(row.get("__konto__") or "4190").strip() or "4190"
        add_line(lines, date=date_booking, description=line_description, account=expense_account, debit=expense)
        for code in ("S", "Z", "0"):
            if input_vat[code] != ZERO and vat_deductible:
                add_line(
                    lines, date=date_booking, description=line_description,
                    account=RATE_INFO[code][1], debit=input_vat[code],
                )
        if flat_rate_vat != ZERO and vat_deductible:
            add_line(lines, date=date_booking, description=line_description, account="16003", debit=flat_rate_vat)
        if self_assessment:
            for code in ("S", "Z", "0"):
                if input_vat[code] != ZERO:
                    add_line(
                        lines, date=date_booking, description=line_description,
                        account=RATE_INFO[code][2], credit=input_vat[code],
                    )
            if flat_rate_vat != ZERO:
                add_line(lines, date=date_booking, description=line_description, account="26003", credit=flat_rate_vat)

        total_debit = expense + deductible_vat
        total_credit = payable + (reported_vat if self_assessment else ZERO)
        if total_debit != total_credit:
            raise ValueError(f"Neuravnotežena PR temeljnica {invoice}: {total_debit} != {total_credit}")

        audit.append({
            "kind": "PR-samoobdavčitev" if self_assessment else "PR",
            "invoice": invoice, "party": partner["name"], "net": net,
            "vat": deductible_vat, "reported_vat": reported_vat,
            "vat_deductible": vat_deductible,
            "self_assessment": self_assessment,
            "representation": not vat_deductible,
            "gross": payable, "residual": residual,
        })

    return root, audit


def write_and_validate(root: etree._Element, output: Path, xsd_path: Path) -> None:
    tree = etree.ElementTree(root)
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    schema.assertValid(tree)
    etree.indent(root, space="  ")
    tree.write(str(output), encoding="utf-8", xml_declaration=True, pretty_print=True)
    schema.assertValid(etree.parse(str(output)))


def total(audit: list[dict], key: str, kinds: set[str] | None = None) -> Decimal:
    return sum(
        (row[key] for row in audit if kinds is None or row["kind"] in kinds),
        ZERO,
    )


def main() -> int:
    if len(sys.argv) != 4:
        print("Uporaba: convert_ddv_json_to_minimax.py VHOD.json IZHODNA_MAPA SHEMA.xsd")
        return 2

    input_path = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    xsd_path = Path(sys.argv[3]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))["DDV_KIR_KPR"]
    header = payload["Glava"]
    kir_rows = payload.get("Lista_KIR", {}).get("KIR", [])
    kpr_rows = payload.get("Lista_KPR", {}).get("KPR", [])
    period = f"{header['OBDOBJE_OD']}_{header['OBDOBJE_DO']}"

    issued_root, issued_audit = build_issued(kir_rows, kpr_rows)
    received_root, received_audit = build_received(kpr_rows)

    issued_path = output_dir / f"Minimax_izdani_racuni_{period}.xml"
    received_path = output_dir / f"Minimax_prejeti_racuni_{period}.xml"
    report_path = output_dir / f"Minimax_pregled_pretvorbe_{period}.txt"

    write_and_validate(issued_root, issued_path, xsd_path)
    write_and_validate(received_root, received_path, xsd_path)

    actual_ir = [row for row in issued_audit if row["kind"] == "IR"]
    tax_only = [row for row in issued_audit if row["kind"] == "KIR-samoobdavčitev"]
    self_assessed_pr = [row for row in received_audit if row["kind"] == "PR-samoobdavčitev"]
    residuals = [
        row for row in actual_ir + received_audit if abs(row["residual"]) > CENT
    ]

    lines = [
        "PRETVORBA FURS DDV_KIR_KPR -> MINIMAX XML",
        f"Vir: {input_path}",
        f"Davčna številka: {header.get('TaxPayerID', '')}",
        f"Obdobje: {header['OBDOBJE_OD']} do {header['OBDOBJE_DO']}",
        f"Uradna XSD: {SCHEMA_URL}",
        "",
        f"Izdani računi: {len(actual_ir)} (od {len(kir_rows)} KIR vrstic)",
        f"  Neto: {fmt(total(actual_ir, 'net'))} EUR",
        f"  Izhodni DDV: {fmt(total(actual_ir, 'vat'))} EUR",
        f"  Terjatve: {fmt(total(actual_ir, 'gross'))} EUR",
        f"Prejeti računi: {len(received_audit)}",
        f"  Neto/oproščene osnove: {fmt(total(received_audit, 'net'))} EUR",
        f"  Odbitni DDV: {fmt(total(received_audit, 'vat'))} EUR",
        f"  Obveznosti do dobaviteljev: {fmt(total(received_audit, 'gross'))} EUR",
        f"Prejeti računi s samoobdavčitvijo: {len(self_assessed_pr)}",
        "",
        "POSEBNOSTI",
    ]
    if tax_only:
        for row in tax_only:
            lines.append(
                f"- KIR {row['invoice']} / {row['party']} ({fmt(row['vat'])} EUR) ni izdan račun; "
                "vključen je v ustrezen PR kot samoobdavčitev."
            )
    else:
        lines.append("- Ni zaznanih KIR vrstic samoobdavčitve, povezanih s KPR.")

    lines.extend([
        "",
        "UPORABLJENE KNJIGOVODSKE PREDPOSTAVKE",
        "- Prihodki izdanih računov: konto 7601; terjatve: 1200.",
        "- Prejeti računi: splošni konto stroška 4000; obveznosti: 2200/2211/2210.",
        "- DDV: 16000/16001/16002 in 26000/26001/26002.",
        "- JSON nima kontov, zapadlosti, naslovov in razčlenitve postavk; zapadlost je zato enaka datumu listine.",
        "- Šifra stranke je sestavljena iz države in davčne identifikacije; naslov je izpuščen.",
        "- Pri več DDV stopnjah je osnova razdeljena iz zneskov DDV, celotni zneski iz JSON pa ostanejo nespremenjeni.",
        "",
        "PREVERJANJE",
        "- Obe XML datoteki sta veljavni po preneseni uradni Minimax XSD.",
        "- Vse temeljnice so dvostavno uravnotežene.",
        f"- Prilagoditve razdelitve osnov pri več DDV stopnjah (> 0,01 EUR): {len(residuals)}.",
    ])
    for row in residuals:
        lines.append(
            f"  - {row['invoice']} / {row['party']}: {fmt(row['residual'])} EUR "
            "(agregirana osnova je ohranjena)."
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(issued_path)
    print(received_path)
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
