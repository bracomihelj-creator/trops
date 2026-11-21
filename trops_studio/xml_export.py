"""Izvoz Minimax XML (Stranke + Temeljnice) za uvoz / KirKpr."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from trops_studio.accounts import resolve_pr_excluded_account, resolve_pr_placilo
from trops_studio.config import (
    DEFAULT_IR_REVENUE_ACCOUNT,
    DEFAULT_MINIMAX_OUT,
    DEFAULT_PR_EXCLUDED_ACCOUNT,
    DEFAULT_PR_EXPENSE_ACCOUNT,
)
from trops_studio.ir_list_view import apply_ir_eu_sale, ir_customer_country
from trops_studio.db import Database
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path, minimax_xsd_path
from trops_studio.journal_preview import extra_journal_lines
from trops_studio.money import decimal_value, is_nonzero, normalize_text, normalize_vat_id, tax_digits

ZERO = Decimal("0.00")


@dataclass
class ExportResult:
    ir_path: Path
    pr_path: Path
    ir_count: int
    pr_count: int
    parties: int
    message: str = ""


def _iso(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()[:10]
    if text:
        return text
    return fallback or date.today().isoformat()


def _party_map(db: Database) -> dict[str, dict[str, Any]]:
    """Ključ = predpona+davčna / vat / MM šifra — DE in SI se ne prekrivata."""
    out: dict[str, dict[str, Any]] = {}
    for party in db.list_parties():
        tax = tax_digits(party.get("tax_number") or party.get("vat_id"))
        vat = normalize_vat_id(party.get("vat_id"))
        cc = (normalize_text(party.get("country") or "")[:2] or "SI").upper()
        if vat:
            out[vat] = party
        if tax:
            prefix = vat[:2] if len(vat) >= 2 and vat[:2].isalpha() else cc
            out[f"{prefix}{tax}"] = party
            if prefix == "SI":
                out[tax] = party
        code = normalize_text(party.get("minimax_code"))
        if code:
            out[f"code:{code}"] = party
    return out


def _sifra(party: Mapping[str, Any] | None, *, name: str, vat_id: str, zapst: int) -> str:
    from trops_studio.parties_ensure import party_fits_journal

    if party:
        fits, _ = party_fits_journal(party, name=name, vat_id=vat_id)
        if not fits:
            party = None
    if party:
        code = normalize_text(party.get("minimax_code"))
        if code:
            return code[:30]
        tax = tax_digits(party.get("tax_number") or party.get("vat_id") or vat_id)
        country = normalize_text(party.get("country") or "SI")[:2].upper() or "SI"
        if tax:
            return f"{country}{tax}"[:30]
    tax = tax_digits(vat_id)
    if tax:
        country = "SI"
        vat = normalize_vat_id(vat_id)
        if len(vat) >= 2 and vat[:2].isalpha():
            country = vat[:2]
        return f"{country}{tax}"[:30]
    slug = "".join(ch for ch in name.upper() if ch.isalnum())[:20] or "STRANKA"
    return f"{slug}-{zapst}"[:30]


def _party_xml_dict(party: Mapping[str, Any] | None, *, name: str, vat_id: str, zapst: int) -> dict[str, str]:
    from trops_studio.parties_ensure import party_fits_journal

    if party:
        fits, _ = party_fits_journal(party, name=name, vat_id=vat_id)
        if not fits:
            party = None
    sifra = _sifra(party, name=name, vat_id=vat_id, zapst=zapst)
    display = normalize_text(name) or (normalize_text(party.get("name")) if party else "") or "Neznana stranka"
    vat = normalize_vat_id(vat_id)
    tax = tax_digits(vat_id)
    if party:
        country = normalize_text(party.get("country") or "SI")[:2].upper() or "SI"
        if len(vat) >= 2 and vat[:2].isalpha():
            country = vat[:2]
        return {
            "code": sifra,
            "name": display,
            "country": country,
            "tax_id": tax,
            "address": normalize_text(party.get("address")),
            "postal_code": normalize_text(party.get("postal_code")),
            "city": normalize_text(party.get("city")),
        }
    country = "SI"
    vat = normalize_vat_id(vat_id)
    if len(vat) >= 2 and vat[:2].isalpha():
        country = vat[:2]
    return {
        "code": sifra,
        "name": name or "Neznana stranka",
        "country": country,
        "tax_id": tax_digits(vat_id),
        "address": "",
        "postal_code": "",
        "city": "",
    }


def ir_to_kir(row: Mapping[str, Any], *, party: Mapping[str, Any] | None, zapst: int) -> dict[str, Any]:
    classified = apply_ir_eu_sale(row, party)
    doc = _iso(classified.get("document_date") or classified.get("booking_date"))
    book = _iso(classified.get("booking_date") or doc)
    vat = normalize_vat_id(classified.get("vat_id"))
    pdict = _party_xml_dict(
        party,
        name=normalize_text(classified.get("party_name")),
        vat_id=vat,
        zapst=zapst,
    )
    country = ir_customer_country(classified, party)
    if country:
        pdict["country"] = country
    account = normalize_text(classified.get("account")) or DEFAULT_IR_REVENUE_ACCOUNT
    from trops_studio.journal_preview import _ir_payment_account, integra_ir_journal_type

    payment = _ir_payment_account(row)
    journal_type = integra_ir_journal_type(row)
    return {
        "ZAPST": zapst,
        "P2": book,
        "P3": normalize_text(classified.get("document_no")),
        "P4": doc,
        "P5": pdict["name"],
        "P6": pdict["country"],
        "P6DS": pdict["tax_id"] or vat,
        "P7": decimal_value(classified.get("net") or classified.get("base_22")),
        "P8": decimal_value(classified.get("reverse_charge")),
        "P9": decimal_value(classified.get("exempt")),
        "P10": decimal_value(classified.get("eu_goods")),
        "P11": decimal_value(classified.get("eu_services")),
        "P12": ZERO,
        "P13": ZERO,
        "P14": decimal_value(classified.get("vat_22")),
        "P15": decimal_value(classified.get("vat_95")),
        "P16": ZERO,
        "P27": decimal_value(classified.get("excluded")),
        "OBRAVNAVA": "1",
        "__konto__": account,
        "__payment_account__": payment,
        "__journal_type__": journal_type,
        "__opis__": normalize_text(row.get("document_no")),
        "__party_code__": pdict["code"],
        "__party__": pdict,
    }


def pr_to_kpr(row: Mapping[str, Any], *, party: Mapping[str, Any] | None, zapst: int) -> dict[str, Any]:
    from trops_studio.pr_vat_flags import resolve_pr_vat_flags

    received = _iso(row.get("received_date") or row.get("document_date") or row.get("booking_date"))
    doc = _iso(row.get("document_date") or received)
    book = _iso(row.get("booking_date") or received)
    vat = normalize_vat_id(row.get("vat_id"))
    pdict = _party_xml_dict(
        party,
        name=normalize_text(row.get("supplier_name")),
        vat_id=vat,
        zapst=zapst,
    )
    expense = normalize_text(row.get("odhodek01")) or DEFAULT_PR_EXPENSE_ACCOUNT
    excluded = decimal_value(row.get("excluded"))
    self_assessment, vat_deductible, offer_from = resolve_pr_vat_flags(row)
    from trops_studio.vat_accounts import pr_vat_kind, row_supplier_kind, third_country_kpr_bases, vat_accounts

    kind = pr_vat_kind({**dict(row), "supplier_kind": row_supplier_kind(row) or row.get("supplier_kind")})
    vin22, vout22 = vat_accounts(kind, "22")
    vin95, vout95 = vat_accounts(kind, "95")
    vin5, vout5 = vat_accounts(kind, "5")
    from trops_studio.os_accounts import add_os_amount_to_kpr

    bases = third_country_kpr_bases({**dict(row), "supplier_kind": row.get("supplier_kind") or row_supplier_kind(row)})

    mapped = {
        "ZAPST": zapst,
        "P2": book,
        "P3": normalize_text(row.get("document_no")),
        "P4": received,
        "P5": doc,
        "P6": pdict["name"],
        "P7": pdict["country"],
        "P7DS": pdict["tax_id"] or vat,
        "P8": bases["P8"],
        "P9": bases["P9"],
        "P10": bases["P10"],
        "P11": bases["P11"],
        "P12": decimal_value(row.get("exempt_non")),
        "P13": decimal_value(row.get("exempt_os")),
        "P14": decimal_value(row.get("exempt_on")),
        "P15": ZERO,
        "P16": ZERO,
        "P17": decimal_value(row.get("nondeduct_22")) + decimal_value(row.get("nondeduct_95")),
        "P18": decimal_value(row.get("vat_22")),
        "P19": decimal_value(row.get("vat_95")),
        "P20": decimal_value(row.get("vat_5")),
        "P21": ZERO,
        "OBRAVNAVA": "1",
        "__konto__": expense,
        "__opis__": normalize_text(row.get("document_no") or row.get("internal_no")),
        "__party_code__": pdict["code"],
        "__party__": pdict,
        "__excluded__": excluded,
        "__placilo__": resolve_pr_placilo(row),
        "__excluded_account__": resolve_pr_excluded_account(row),
        "__konto10__": normalize_text(row.get("odhodek10")),
        "__konto11__": normalize_text(row.get("odhodek11")),
        "__konto07__": normalize_text(row.get("odhodek07")),
        "__samoobdavcitev__": self_assessment,
        "__ddv_se_odbija__": vat_deductible,
        "__vat_offer_from__": offer_from,
        "__vat_kind__": kind,
        "__vat_in_22__": vin22,
        "__vat_out_22__": vout22,
        "__vat_in_95__": vin95,
        "__vat_out_95__": vout95,
        "__vat_in_5__": vin5,
        "__vat_out_5__": vout5,
        "__extra_lines__": extra_journal_lines(row),
    }
    add_os_amount_to_kpr(mapped, row)
    return mapped


def _import_xml_helpers():
    ensure_kirkpr_on_path()
    import convert_ddv_json_to_minimax as mx  # type: ignore

    return mx


def _make_root_with_addresses(mx: Any, parties: Iterable[dict[str, str]]) -> tuple[Any, Any]:
    """make_root + opcijski naslov (kot v stranke_PROJEST.XML)."""
    from lxml import etree

    root = etree.Element(mx.q("miniMAXUvozKnjigovodstvo"), nsmap={None: mx.NS, "xsi": mx.XSI})
    root.set(f"{{{mx.XSI}}}schemaLocation", f"{mx.NS} {mx.SCHEMA_URL}")
    stranke = mx.add(root, "Stranke")
    unique = {party["code"]: party for party in parties if party.get("code")}
    for party in sorted(unique.values(), key=lambda item: item["code"]):
        stranka = mx.add(stranke, "Stranka")
        mx.add(stranka, "Sifra", party["code"])
        mx.add(stranka, "Naziv", party["name"][:250])
        if party.get("address"):
            mx.add(stranka, "Naslov", party["address"][:250])
        mx.add(stranka, "KraticaDrzave", party["country"])
        if party.get("postal_code"):
            mx.add(stranka, "PostnaStevilka", party["postal_code"][:20])
        if party.get("city"):
            mx.add(stranka, "NazivPoste", party["city"][:100])
        if party.get("tax_id"):
            mx.add(stranka, "DavcniZavezanec", "D")
            mx.add(stranka, "DavcnaStevilka", party["tax_id"][:30])
            mx.add(
                stranka,
                "IdentifikacijskaStevilka",
                mx.party_identity(party["country"], party["tax_id"])[:30],
            )
        mx.add(stranka, "SifraDenarneEnote", "EUR")
        mx.add(stranka, "Uporaba", "D")
    return root, mx.add(root, "Temeljnice")


def _build_ir_journals(mx: Any, temeljnice: Any, kir_rows: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for row in kir_rows:
        partner_code = str(row.get("__party_code__") or "")
        invoice = str(row.get("P3") or "").strip()
        description = str(row.get("__opis__") or invoice).strip()[:250] or invoice
        date_invoice = str(row.get("P4") or row.get("P2"))[:10]
        date_ddv = str(row.get("P2") or date_invoice)[:10]
        taxable = mx.amount(row, "P7")
        exempt = mx.amount(row, "P9", "P10", "P11")
        non_taxable = mx.amount(row, "P8", "P12", "P13", "P27")
        vat = {"S": mx.amount(row, "P14"), "Z": mx.amount(row, "P15"), "0": mx.amount(row, "P16")}
        rates = mx.issued_invoice_vat_rates(dict(row))
        net = taxable + exempt + non_taxable
        output_vat = sum(vat.values(), ZERO)
        gross = net + output_vat
        # Integra: DR… → vrsta IR; Paragoni 100* → vrsta DI; DDV knjiga vedno IR
        journal_type = str(row.get("__journal_type__") or "IR").strip().upper() or "IR"
        vat_book = "IR"  # Minimax: KnjigaDDV IR tudi za DI temeljnice
        journal = mx.make_header(temeljnice, journal_type, date_invoice, description)
        mx.add_ddv(
            journal,
            book=vat_book,
            date_ddv=date_ddv,
            date_booking=date_ddv,
            partner_code_value=partner_code,
            invoice_number=invoice,
            date_invoice=date_invoice,
            date_service=date_invoice,
            reporting="Obracun",
            rates=rates,
        )
        lines = mx.add(journal, "VrsticeTemeljnice")
        # Integra Paragoni: 1000/1650 brez šifre stranke; Fakture/Projest: 1200 + partner
        payment = str(row.get("__payment_account__") or "1200").strip() or "1200"
        debit_partner = "" if payment in {"1000", "1650"} else partner_code
        mx.add_line(
            lines,
            date=date_invoice,
            description=description,
            account=payment,
            partner=debit_partner or None,
            due=date_invoice if debit_partner else None,
            service_date=date_invoice if debit_partner else None,
            reference=invoice,
            debit=gross,
        )
        revenue = str(row.get("__konto__") or DEFAULT_IR_REVENUE_ACCOUNT).strip() or DEFAULT_IR_REVENUE_ACCOUNT
        mx.add_line(lines, date=date_invoice, description=description, account=revenue, credit=net)
        for code in ("S", "Z", "0"):
            if vat[code] != ZERO:
                mx.add_line(
                    lines,
                    date=date_invoice,
                    description=description,
                    account=mx.RATE_INFO[code][2],
                    credit=vat[code],
                )
        count += 1
    return count


def _xml_line_konto(line: Any, ns: Mapping[str, str]) -> str:
    els = line.xpath("./m:SifraKonta", namespaces=ns)
    return str(els[0].text or "").strip() if els else ""


def _xml_line_amount(line: Any, ns: Mapping[str, str], tag: str) -> Decimal:
    els = line.xpath(f"./m:{tag}", namespaces=ns)
    return decimal_value(els[0].text) if els else ZERO


def _set_xml_line_amounts(mx: Any, line: Any, ns: Mapping[str, str], debit: Decimal, credit: Decimal) -> None:
    for tag in (
        "ZnesekVBremeVDenarniEnoti",
        "ZnesekVDobroVDenarniEnoti",
        "ZnesekVBremeVDomaciDenarniEnoti",
        "ZnesekVDobroVDomaciDenarniEnoti",
    ):
        for el in line.xpath(f"./m:{tag}", namespaces=ns):
            line.remove(el)
    if debit != ZERO:
        mx.add(line, "ZnesekVBremeVDenarniEnoti", mx.fmt(debit))
        mx.add(line, "ZnesekVBremeVDomaciDenarniEnoti", mx.fmt(debit))
    if credit != ZERO:
        mx.add(line, "ZnesekVDobroVDenarniEnoti", mx.fmt(credit))
        mx.add(line, "ZnesekVDobroVDomaciDenarniEnoti", mx.fmt(credit))


def _inject_pr_extra_lines(
    mx: Any,
    node: Any,
    ns: Mapping[str, str],
    extras: Sequence[Mapping[str, Any]],
    *,
    placilo: str,
    date_received: str,
    description: str,
) -> None:
    if not extras:
        return
    extra_accounts = {str(item.get("konto") or "").strip() for item in extras}
    extra_accounts.discard("")
    parents = node.xpath(".//m:VrsticeTemeljnice", namespaces=ns)
    if not parents:
        return
    parent = parents[0]
    for line in list(node.xpath(".//m:VrsticaTemeljnice", namespaces=ns)):
        konto = _xml_line_konto(line, ns)
        if konto and konto in extra_accounts and konto != placilo:
            parent.remove(line)
    for extra in extras:
        konto = str(extra.get("konto") or "").strip()
        debit = decimal_value(extra.get("debet"))
        credit = decimal_value(extra.get("kredit"))
        if not konto or (debit == ZERO and credit == ZERO):
            continue
        opis = str(extra.get("opis") or description).strip()[:250] or description
        mx.add_line(
            parent,
            date=date_received,
            description=opis,
            account=konto,
            debit=debit,
            credit=credit,
        )
    pay_line = None
    debit_sum = ZERO
    credit_sum = ZERO
    for line in node.xpath(".//m:VrsticaTemeljnice", namespaces=ns):
        konto = _xml_line_konto(line, ns)
        debit = _xml_line_amount(line, ns, "ZnesekVBremeVDenarniEnoti")
        credit = _xml_line_amount(line, ns, "ZnesekVDobroVDenarniEnoti")
        if konto == placilo and pay_line is None:
            pay_line = line
            continue
        debit_sum += debit
        credit_sum += credit
    delta = debit_sum - credit_sum
    if pay_line is None:
        if not is_nonzero(delta):
            return
        if delta > ZERO:
            mx.add_line(parent, date=date_received, description=description, account=placilo, credit=delta)
        else:
            mx.add_line(parent, date=date_received, description=description, account=placilo, debit=-delta)
        return
    if delta > ZERO:
        _set_xml_line_amounts(mx, pay_line, ns, ZERO, delta)
    elif delta < ZERO:
        _set_xml_line_amounts(mx, pay_line, ns, -delta, ZERO)
    else:
        parent.remove(pay_line)


def _build_pr_journals(mx: Any, temeljnice: Any, kpr_rows: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for row in kpr_rows:
        partner_code = str(row.get("__party_code__") or "")
        invoice = str(row.get("P3") or "").strip()
        description = str(row.get("__opis__") or invoice).strip()[:250] or invoice
        date_booking = str(row.get("P2") or row.get("P5") or row.get("P4"))[:10]
        date_received = str(row.get("P4") or date_booking)[:10]
        date_invoice = str(row.get("P5") or date_received)[:10]
        excluded = decimal_value(row.get("__excluded__"))
        placilo = str(row.get("__placilo__") or "2200").strip() or "2200"
        expense = str(row.get("__konto__") or DEFAULT_PR_EXPENSE_ACCOUNT).strip() or DEFAULT_PR_EXPENSE_ACCOUNT
        excluded_account = str(row.get("__excluded_account__") or DEFAULT_PR_EXCLUDED_ACCOUNT)

        line_description = (
            str(row.get("__opis_knjizba__") or description).strip()[:250] or description
        )
        # »Ne gre v knjigo« = ni v DDV sistemu: samo temeljnica, brez DDV bloka.
        if excluded != ZERO and mx.amount(row, "P8", "P9", "P10", "P11", "P18", "P19", "P20") == ZERO:
            journal = mx.make_header(temeljnice, "PR", date_received, description)
            lines = mx.add(journal, "VrsticeTemeljnice")
            # Odhodek (4190/9729/…) + plačilo 22xx; stranko/datume doda API po Account zastavicah.
            mx.add_line(
                lines,
                date=date_received,
                description=line_description,
                account=excluded_account,
                partner=partner_code or None,
                debit=excluded,
            )
            mx.add_line(
                lines,
                date=date_received,
                description=line_description,
                account=placilo,
                partner=partner_code,
                due=date_received,
                service_date=date_invoice or date_received,
                reference=invoice[:30],
                credit=excluded,
            )
            extras = list(row.get("__extra_lines__") or [])
            if extras:
                _inject_pr_extra_lines(
                    mx,
                    journal,
                    {"m": mx.NS},
                    extras,
                    placilo=placilo,
                    date_received=date_received,
                    description=line_description,
                )
            count += 1
            continue

        # Standardni PR — uporabi KirKpr build_received logiko za eno vrstico prek
        # začasnega root-a in prenesi Temeljnica node.
        single_root, _audit = mx.build_received([dict(row)])
        ns = {"m": mx.NS}
        nodes = single_root.xpath("./m:Temeljnice/m:Temeljnica", namespaces=ns)
        vat_map = {
            "16000": str(row.get("__vat_in_22__") or "16000"),
            "16001": str(row.get("__vat_in_95__") or "16001"),
            "16002": str(row.get("__vat_in_5__") or "16002"),
            "26000": str(row.get("__vat_out_22__") or "26000"),
            "26001": str(row.get("__vat_out_95__") or "26001"),
            "26002": str(row.get("__vat_out_5__") or "26004"),
            "26004": str(row.get("__vat_out_5__") or "26004"),
        }
        # Stranka: CustomerEntry≠N (12xx/22xx/9729). Datumi/veza: samo 12xx/22xx.
        for node in nodes:
            for header in node.xpath(".//m:DDVGlava", namespaces=ns):
                sif = header.xpath("./m:SifraStranke", namespaces=ns)
                if partner_code and sif:
                    sif[0].text = partner_code
                if date_invoice and not header.xpath("./m:DatumOpravljanja", namespaces=ns):
                    mx.add(header, "DatumOpravljanja", date_invoice)
            for line in node.xpath(".//m:VrsticaTemeljnice", namespaces=ns):
                konto_el = line.xpath("./m:SifraKonta", namespaces=ns)
                konto = str(konto_el[0].text or "").strip() if konto_el else ""
                if konto == "4000" and konto_el:
                    konto_el[0].text = expense
                    konto = expense
                if konto in ("2200", "2210", "2211") and placilo and konto_el:
                    konto_el[0].text = placilo
                    konto = placilo
                if konto in vat_map and konto_el and vat_map[konto] != konto:
                    konto_el[0].text = vat_map[konto]
                    konto = vat_map[konto]
                digits = "".join(ch for ch in konto if ch.isdigit())
                allow_dates = digits.startswith(("12", "22"))
                # 9729: CustomerEntry=D (stranka DA), datumi NE
                allow_party = allow_dates or konto == "9729"
                sif_els = line.xpath("./m:SifraStranke", namespaces=ns)
                if allow_party and partner_code:
                    if sif_els:
                        sif_els[0].text = partner_code
                    else:
                        mx.add(line, "SifraStranke", partner_code)
                elif not allow_party:
                    for el in sif_els:
                        line.remove(el)
                if not allow_dates:
                    for bad in ("DatumOpravljanja", "DatumZapadlosti", "VezaZaPlacilo"):
                        for el in line.xpath(f"./m:{bad}", namespaces=ns):
                            line.remove(el)
            extras = list(row.get("__extra_lines__") or [])
            if extras:
                _inject_pr_extra_lines(
                    mx,
                    node,
                    ns,
                    extras,
                    placilo=placilo,
                    date_received=date_received,
                    description=line_description,
                )
            temeljnice.append(node)
            count += 1
        _ = date_booking
    return count


def export_minimax_xml_for_kirkpr(
    db: Database,
    *,
    output_dir: Path | None = None,
    ir_rows: Sequence[Mapping[str, Any]] | None = None,
    pr_rows: Sequence[Mapping[str, Any]] | None = None,
    company_label: str = "PROJEST",
    validate: bool = True,
) -> ExportResult:
    """
    Ustvari Minimax XML (IR + PR), ki ga KirKpr / Minimax lahko uvozita.
    Šifre strank: prednost Minimax Code iz SQLite parties.
    """
    mx = _import_xml_helpers()
    parties_idx = _party_map(db)
    ir_src = list(ir_rows if ir_rows is not None else db.list_ir())
    pr_src = list(pr_rows if pr_rows is not None else db.list_pr())

    kir: list[dict[str, Any]] = []
    for index, row in enumerate(ir_src, start=1):
        tax = tax_digits(row.get("vat_id"))
        vat = normalize_vat_id(row.get("vat_id"))
        party = parties_idx.get(tax) or parties_idx.get(vat)
        if row.get("party_id"):
            party = db.get_party(int(row["party_id"])) or party
        kir.append(ir_to_kir(row, party=party, zapst=index))

    kpr: list[dict[str, Any]] = []
    for index, row in enumerate(pr_src, start=1):
        tax = tax_digits(row.get("vat_id") or row.get("tax_number"))
        vat = normalize_vat_id(row.get("vat_id"))
        party = parties_idx.get(tax) or parties_idx.get(vat)
        if row.get("party_id"):
            party = db.get_party(int(row["party_id"])) or party
        mapped = pr_to_kpr(row, party=party, zapst=index)
        # build_received pričakuje party_from_kpr code — podtaknemo P7DS/ime;
        # šifro vsilimo prek __party_code__ in popravka spodaj.
        mapped["__party_code_override__"] = mapped["__party_code__"]
        kpr.append(mapped)

    party_dicts = [row["__party__"] for row in kir + kpr if row.get("__party__")]
    root_ir, tem_ir = _make_root_with_addresses(mx, party_dicts)
    ir_count = _build_ir_journals(mx, tem_ir, kir)

    # Za PR: patch party_from_kpr codes by temporarily wrapping
    # Easiest: monkeypatch party_from_kpr to use override map
    code_by_zapst = {int(r["ZAPST"]): r["__party_code__"] for r in kpr}
    original_party_from_kpr = mx.party_from_kpr

    def party_from_kpr_override(row: dict) -> dict:
        base = original_party_from_kpr(row)
        zap = int(row.get("ZAPST") or 0)
        if zap in code_by_zapst:
            base["code"] = code_by_zapst[zap]
        party_meta = row.get("__party__") or {}
        if party_meta.get("name"):
            base["name"] = party_meta["name"]
        if party_meta.get("country"):
            base["country"] = party_meta["country"]
        if party_meta.get("tax_id"):
            base["tax_id"] = party_meta["tax_id"]
        return base

    mx.party_from_kpr = party_from_kpr_override
    try:
        root_pr, tem_pr = _make_root_with_addresses(mx, party_dicts)
        pr_count = _build_pr_journals(mx, tem_pr, kpr)
    finally:
        mx.party_from_kpr = original_party_from_kpr

    out = Path(output_dir or DEFAULT_MINIMAX_OUT)
    out.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in company_label) or "PROJEST"
    ir_path = out / f"KirKpr_IR_{safe}.XML"
    pr_path = out / f"KirKpr_PR_{safe}.XML"
    xsd = minimax_xsd_path() if validate else None
    if validate and xsd is not None:
        mx.write_and_validate(root_ir, ir_path, xsd)
        mx.write_and_validate(root_pr, pr_path, xsd)
    else:
        from lxml import etree

        for root, path in ((root_ir, ir_path), (root_pr, pr_path)):
            tree = etree.ElementTree(root)
            etree.indent(root, space="  ")
            tree.write(str(path), encoding="utf-8", xml_declaration=True, pretty_print=True)

    return ExportResult(
        ir_path=ir_path,
        pr_path=pr_path,
        ir_count=ir_count,
        pr_count=pr_count,
        parties=len({p["code"] for p in party_dicts if p.get("code")}),
        message=(
            f"XML za KirKpr/Minimax: IR {ir_count}, PR {pr_count}, "
            f"stranke {len({p['code'] for p in party_dicts if p.get('code')})}.\n"
            f"{ir_path}\n{pr_path}"
        ),
    )
