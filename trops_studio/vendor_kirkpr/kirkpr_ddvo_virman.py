"""SEPA virman (pain.001) za plačilo DDV na FURS / PDP proračun države.

Struktura usklajena z Minimax izvozom (glej TROPS\\…\\Virmani\\*_Virman_DDV_*.xml).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from xml.dom import minidom
from xml.etree import ElementTree as ET

import kirkpr_company_registry as company_registry
import kirkpr_minimax_core as core


def _easter_sunday(year: int) -> date:
    """Gregorian Computus (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def slovenia_public_holidays(year: int) -> set[date]:
    """Državni prazniki SI (fiksni + velikonočna nedelja/ponedeljek)."""
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        date(year, 1, 2),
        date(year, 2, 8),
        easter,
        easter + timedelta(days=1),
        date(year, 4, 27),
        date(year, 5, 1),
        date(year, 5, 2),
        date(year, 6, 25),
        date(year, 8, 15),
        date(year, 10, 31),  # dan reformacije
        date(year, 11, 1),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def previous_business_day(d: date) -> date:
    """Če sobota/nedelja/praznik → prestavi na prejšnji delovnik (npr. 31.10 → 30.10)."""
    cur = d
    while cur.weekday() >= 5 or cur in slovenia_public_holidays(cur.year):
        cur = cur - timedelta(days=1)
    return cur

# FURS / UJP — prehodni davčni podračun (proračun države), DDV šifra 62006.
FURS_CREDITOR_NAME = "PREHODNI DAVČNI PODRAČUN - PRORAČUN DRŽAVE"
FURS_CREDITOR_IBAN = "SI56011008881000030"
FURS_CREDITOR_BIC = "BSLJSI2X"
FURS_CREDITOR_ADDR1 = "Gregorčičeva ulica 20"
FURS_CREDITOR_ADDR2 = "1000 Ljubljana"
FURS_DDV_CHARGE_CODE = "62006"
FURS_PURPOSE_CODE = "VATX"  # Minimax / banke za DDV

# Vir: Banka Slovenije, seznam BIC in nacionalnih oznak dodeljevalcev IBAN
# (oktober 2026). Dvomestna oznaka + 3 mesta enote določi banka (npr. 02312 → NLB).
# Petmestne oznake so plačilne institucije. 91001 Petrol Pay nima BIC.
# Združene oznake (03 SKB, 05 Abanka, 06 Banka Celje) na seznamu BS niso več.
_SI_BANK_BIC = {
    "91002": "PWSRSI22",  # Dinaro d.o.o.
}

_SI_BANK_PREFIX_BIC = {
    "01": "BSLJSI2X",  # Banka Slovenije
    "02": "LJBASI2X",  # NLB
    "04": "KBMASI2X",  # OTP banka
    "07": "GORESI2X",  # Gorenjska banka
    "10": "BAKOSI2X",  # Intesa Sanpaolo
    "19": "SZKBSI2X",  # Deželna banka Slovenije
    "29": "BACXSI22",  # UniCredit
    "30": "LJBASI2X",  # NLB (prevzeta oznaka)
    "33": "HAABSI22",  # Addiko
    "34": "KSPKSI22",  # Sparkasse
    "35": "BFKKSI22",  # BKS
    "38": "SIDRSI22",  # SID banka
    "60": "HLONSI22",  # Hranilnica LON
    "61": "HDELSI22",  # Delavska hranilnica
    "64": "HKVISI22",  # Primorska hranilnica Vipava
    "79": "KDDSSI22",  # KDD
}

_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class DdvoVirmanPackage:
    payment: Decimal
    obligation: Decimal
    konto62_credit: Decimal
    reference: str
    creditor_iban: str
    debtor_iban: str
    execution_date: date
    pdf_path: Path
    virman_path: Path
    out_dir: Path
    virman_dir: Path
    email_to: str


def normalize_iban(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def normalize_bic(value: Any) -> str:
    """8- ali 11-mestni BIC (XXX na koncu → 8 mest, kot Minimax)."""
    bic = re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())
    if len(bic) >= 11 and bic.endswith("XXX"):
        bic = bic[:8]
    elif len(bic) > 11:
        bic = bic[:11]
    return bic[:11]


def bic_from_iban(iban: str) -> str:
    """BIC plačnika iz SI IBAN (5-mestna nacionalna oznaka / družina banke)."""
    clean = normalize_iban(iban)
    if len(clean) < 9 or not clean.startswith("SI"):
        return ""
    code5 = clean[4:9]
    code4 = clean[4:8]
    code2 = clean[4:6]
    raw = (
        _SI_BANK_BIC.get(code5)
        or _SI_BANK_BIC.get(code4)
        or _SI_BANK_PREFIX_BIC.get(code2)
        or ""
    )
    return normalize_bic(raw)


def company_iban(record: Mapping[str, Any] | None) -> str:
    """IBAN plačnika: najprej trr_evidenca/AJPES, nato TRR→SI IBAN iz Evidence."""
    try:
        import kirkpr_ajpes_iban as ajpes_iban

        found = ajpes_iban.resolve_payer_ibans(record)
        if found.selected:
            return found.selected
    except Exception:
        pass
    if not record:
        return ""
    for key, value in record.items():
        key_l = str(key).casefold()
        if "ransakcijski" in key_l or key_l in {"iban", "trr", "bančni račun", "bancni racun"}:
            iban = normalize_iban(value)
            if iban.startswith("SI") and len(iban) >= 15:
                return iban
            # DURS TRR (29000-00…) → SI IBAN
            try:
                import kirkpr_ajpes_iban as ajpes_iban

                converted = ajpes_iban.resolve_payer_ibans({"Transakcijski račun": value}).selected
                if converted:
                    return converted
            except Exception:
                pass
            if iban:
                return iban
    return ""


def company_email(record: Mapping[str, Any] | None) -> str:
    if not record:
        return ""
    for key in ("Email", "E-mail", "eMail", "email", "Mail"):
        value = str(record.get(key) or "").strip()
        if value and "@" in value:
            return normalize_outlook_recipients(value)
    for key, value in record.items():
        if "mail" in str(key).casefold():
            text = str(value or "").strip()
            if text and "@" in text:
                return normalize_outlook_recipients(text)
    return ""


def normalize_outlook_recipients(raw: str) -> str:
    """Več naslovov → Outlook oblika z `;` (vejica sproži Preverjanje imen)."""
    text = str(raw or "").replace("\r", "\n")
    parts: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[\n;]+", text):
        for piece in chunk.split(","):
            addr = piece.strip().strip("<>").strip()
            if not addr or "@" not in addr:
                # Dopusti tudi »Ime <a@b.com>« — že očiščeno zgoraj; sicer SMTP-only.
                continue
            # Če je še »Ime a@b.com«, vzemi zadnji token z @.
            if " " in addr and "<" not in addr:
                tokens = [t for t in addr.replace("<", " ").replace(">", " ").split() if "@" in t]
                if tokens:
                    addr = tokens[-1].strip(".,;")
            key = addr.casefold()
            if key in seen:
                continue
            seen.add(key)
            parts.append(addr)
    return "; ".join(parts)


def parse_outlook_recipients(raw: str) -> list[str]:
    text = normalize_outlook_recipients(raw)
    return [p.strip() for p in text.split(";") if p.strip()]


def _apply_outlook_to(mail: Any, to_addr: str) -> str:
    """Nastavi Za: vsak SMTP naslov posebej z `;` (brez Preverjanje imen).

    Vejica v To: = eno »ime« → dialog. ResolveAll pri gmail odpira isti dialog.
    """
    addrs = parse_outlook_recipients(to_addr)
    joined = "; ".join(addrs)
    try:
        # Počisti morebitne stare prejemnike.
        while int(getattr(mail.Recipients, "Count", 0) or 0) > 0:
            mail.Recipients.Remove(1)
    except Exception:
        pass
    mail.To = ""
    for addr in addrs:
        try:
            recip = mail.Recipients.Add(addr)
            try:
                recip.Type = 1  # olTo
            except Exception:
                pass
        except Exception:
            continue
    # Zavarovanje: če Recipients ni sprejel, vseeno nastavi To z `;`.
    try:
        if int(getattr(mail.Recipients, "Count", 0) or 0) < len(addrs):
            mail.To = joined
    except Exception:
        mail.To = joined
    if not str(getattr(mail, "To", "") or "").strip():
        mail.To = joined
    return joined

def furs_ddv_reference(tax_number: str) -> str:
    """Prikaz / e-pošta: SI19 49142275-62006."""
    tax = re.sub(r"\D", "", str(tax_number or ""))
    if not tax:
        raise core.KirkprError("Za virman DDV manjka davčna številka zavezanca.")
    return f"SI19 {tax}-{FURS_DDV_CHARGE_CODE}"


def furs_ddv_reference_sepa(tax_number: str) -> str:
    """SEPA CdtrRefInf/Ref (brez presledka): SI1949142275-62006."""
    return furs_ddv_reference(tax_number).replace(" ", "")


def default_ddv_due_date(period_to: str | date | None = None) -> date:
    """Zadnji delovni dan meseca po koncu obdobja DDV-O.

    MiniMax Obračun DDV julij (01.07.2026–31.07.2026) → izvršitev avgust;
    če 31.08. / 31.10. pade na vikend ali praznik → prejšnji delovnik
    (npr. september → 31.10. praznik/sobota → 30.10.).
    """
    if isinstance(period_to, datetime):
        end = period_to.date()
    elif isinstance(period_to, date):
        end = period_to
    else:
        text = str(period_to or "").strip()
        end = None
        m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
        if m:
            try:
                end = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                end = None
        if end is None:
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
            if m:
                try:
                    end = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    end = None
        if end is None:
            end = date.today()
    year, month = end.year, end.month + 1
    if month > 12:
        year += 1
        month = 1
    last = calendar.monthrange(year, month)[1]
    return previous_business_day(date(year, month, last))


def remittance_period_label(period_from: str, period_to: str) -> str:
    """Npr. '4-6.2026' za apr–jun 2026 (kot Minimax AddtlRmtInf)."""
    try:
        d0 = datetime.strptime(str(period_from)[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(str(period_to)[:10], "%Y-%m-%d").date()
    except ValueError:
        return str(period_to or period_from or "")
    if d0.year == d1.year and d0.month == d1.month:
        return f"{d1.month}.{d1.year}"
    if d0.year == d1.year:
        return f"{d0.month}-{d1.month}.{d1.year}"
    return f"{d0.month}.{d0.year}-{d1.month}.{d1.year}"


def split_slovenian_address(raw: str) -> tuple[str, str]:
    """Vrne (AdrLine1, AdrLine2) kot Minimax: ulica / pošta+kraj."""
    text = " ".join(str(raw or "").replace("\n", " ").split()).strip()
    if not text:
        return "", ""
    post_m = re.search(r"\b(\d{4})\s+(.+)$", text)
    if post_m:
        city = re.sub(r"\s*-\s*", " ", post_m.group(2).strip(" ,"))
        post_line = f"{post_m.group(1)} {city}"
        before = text[: post_m.start()].strip(" ,")
        parts = [p.strip() for p in before.split(",") if p.strip()]
        street = ""
        for part in reversed(parts):
            if any(ch.isdigit() for ch in part) or re.search(
                r"\b(ulica|cesta|trg|pot|naselje)\b", part, re.I
            ):
                street = part
                break
        if not street and parts:
            street = parts[-1]
        # Minimax: "Trtnikova ulica 008" — vodilne ničle v hišni št.
        street = _pad_house_number(street)
        return street or before, post_line
    return text, ""


def _pad_house_number(street: str) -> str:
    match = re.search(r"^(.*?)(\d+)([A-Za-z]?)$", street.strip())
    if not match:
        return street
    prefix, num, suffix = match.group(1), match.group(2), match.group(3)
    if len(num) >= 3:
        return street
    return f"{prefix}{num.zfill(3)}{suffix}".strip()


def _el(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, f"{{{_NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def _pstl_adr_lines(parent: ET.Element, line1: str = "", line2: str = "") -> None:
    adr = _el(parent, "PstlAdr")
    _el(adr, "Ctry", "SI")
    if line1:
        _el(adr, "AdrLine", line1[:70])
    if line2:
        _el(adr, "AdrLine", line2[:70])


def build_furs_ddv_pain001_xml(
    *,
    payer_name: str,
    payer_iban: str,
    payer_tax_id: str,
    amount: Decimal,
    payer_street: str = "",
    payer_city: str = "",
    payer_bic: str = "",
    remittance: str = "",
    execution_date: date | None = None,
    period_from: str = "",
    period_to: str = "",
) -> str:
    """pain.001.001.03 — enaka oblika kot Minimax DDV virman."""
    amount = core.decimal_value(amount)
    if amount <= ZERO:
        raise core.KirkprError("Znesek virmana mora biti večji od 0.")
    iban_pay = normalize_iban(payer_iban)
    if not iban_pay.startswith("SI"):
        raise core.KirkprError("Za virman DDV potrebuješ IBAN plačnika (SI…).")
    sepa_ref = furs_ddv_reference_sepa(payer_tax_id)
    ET.register_namespace("", _NS)
    ET.register_namespace("xsi", _XSI)
    root = ET.Element(
        f"{{{_NS}}}Document",
        {f"{{{_XSI}}}schemaLocation": f"{_NS} ./pain.001.001.03.xsd"},
    )
    cstmr = _el(root, "CstmrCdtTrfInitn")
    now = datetime.now()
    amt_txt = f"{amount:.2f}"
    msg_id = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}/0001"
    cre = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
    pmt_inf_id = f"{int(now.timestamp() * 100) % 100000000:08d}"
    # EndToEndId kot Minimax: SI00 + lastna številka (ne SI19 ref / davčna).
    tax = re.sub(r"\D", "", payer_tax_id or "")
    e2e = f"SI00{int(now.timestamp() * 1000) % 10000000:07d}"[:35]
    exec_dt = execution_date or date.today()
    if period_from and period_to:
        addtl = f"Plačilo DDV za: {remittance_period_label(period_from, period_to)}"
    else:
        addtl = (remittance or f"Plačilo DDV ({sepa_ref})")[:140]

    line1, line2 = payer_street, payer_city
    if line1 and not line2 and "," not in line1:
        # Če je podan samo NASLOV kot ena vrstica, razčleni.
        line1, line2 = split_slovenian_address(line1)
    elif not line1 and line2:
        line1, line2 = split_slovenian_address(line2)

    grp = _el(cstmr, "GrpHdr")
    _el(grp, "MsgId", msg_id[:35])
    _el(grp, "CreDtTm", cre)
    _el(grp, "NbOfTxs", "1")
    _el(grp, "CtrlSum", amt_txt)
    init = _el(grp, "InitgPty")
    _el(init, "Nm", (payer_name or "Placnik")[:70])
    if tax:
        othr = _el(_el(_el(init, "Id"), "OrgId"), "Othr")
        _el(othr, "Id", tax[:35])
        _el(_el(othr, "SchmeNm"), "Cd", "TXID")

    pmt = _el(cstmr, "PmtInf")
    _el(pmt, "PmtInfId", pmt_inf_id[:35])
    _el(pmt, "PmtMtd", "TRF")
    _el(pmt, "ReqdExctnDt", exec_dt.isoformat())

    dbtr = _el(pmt, "Dbtr")
    _el(dbtr, "Nm", (payer_name or "Placnik")[:70])
    _pstl_adr_lines(dbtr, line1, line2)

    dbtr_acct = _el(pmt, "DbtrAcct")
    _el(_el(dbtr_acct, "Id"), "IBAN", iban_pay)
    _el(dbtr_acct, "Ccy", "EUR")

    bic_pay = normalize_bic(payer_bic) or bic_from_iban(iban_pay)
    if not bic_pay:
        raise core.KirkprError(
            f"Ne najdem BIC banke za IBAN {iban_pay}. "
            "Dopolni šifrant bank ali vnesi BIC plačnika."
        )
    # DbtrAgt je v pain.001.001.03 obvezen (brez njega Hal@bank SAXParseException).
    _el(_el(_el(pmt, "DbtrAgt"), "FinInstnId"), "BIC", bic_pay)

    tx = _el(pmt, "CdtTrfTxInf")
    _el(_el(tx, "PmtId"), "EndToEndId", e2e)
    tp = _el(tx, "PmtTpInf")
    _el(tp, "InstrPrty", "NORM")
    _el(_el(tp, "SvcLvl"), "Cd", "SEPA")
    _el(_el(tp, "LclInstrm"), "Prtry", "SEPA")

    inst = _el(_el(tx, "Amt"), "InstdAmt", amt_txt)
    inst.set("Ccy", "EUR")
    _el(tx, "ChrgBr", "SLEV")
    _el(_el(_el(tx, "CdtrAgt"), "FinInstnId"), "BIC", FURS_CREDITOR_BIC)

    cdtr = _el(tx, "Cdtr")
    _el(cdtr, "Nm", FURS_CREDITOR_NAME[:70])
    _pstl_adr_lines(cdtr, FURS_CREDITOR_ADDR1, FURS_CREDITOR_ADDR2)
    _el(_el(_el(tx, "CdtrAcct"), "Id"), "IBAN", FURS_CREDITOR_IBAN)
    _el(_el(tx, "Purp"), "Cd", FURS_PURPOSE_CODE)

    rmt = _el(tx, "RmtInf")
    strd = _el(rmt, "Strd")
    cref = _el(strd, "CdtrRefInf")
    _el(_el(_el(cref, "Tp"), "CdOrPrtry"), "Cd", "SCOR")
    _el(cref, "Ref", sepa_ref)
    _el(strd, "AddtlRmtInf", addtl[:140])

    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    text = pretty.decode("utf-8")
    # Minimax: encoding="UTF-8" (velike črke).
    text = text.replace('encoding="utf-8"', 'encoding="UTF-8"', 1)
    if text.startswith("<?xml"):
        lines = text.splitlines()
        out = [lines[0]]
        out.extend(ln for ln in lines[1:] if ln.strip())
        return "\n".join(out) + "\n"
    return text


def virman_filename(company_name: str, period_from: str, period_to: str) -> str:
    firm = company_registry.safe_name(company_name, "firma")
    period = company_registry.safe_name(f"{period_from}_{period_to}", "obdobje")
    return f"{firm}_VIRMAN_DDV-O_{period}.xml"


def client_pdf_filename(company_name: str, period_from: str, period_to: str) -> str:
    firm = company_registry.safe_name(company_name, "firma")
    period = company_registry.safe_name(f"{period_from}_{period_to}", "obdobje")
    return f"{firm}_DDV-O_{period}.pdf"


def write_virman_package(
    out_dir: Path,
    *,
    company: Mapping[str, Any],
    period_from: str,
    period_to: str,
    obligation: Decimal,
    konto62_credit: Decimal,
    payment: Decimal,
    source_pdf: Path,
    payer_iban: str = "",
    execution_date: date | None = None,
    remittance: str = "",
    virman_dir: Path | None = None,
) -> DdvoVirmanPackage:
    """Shrani DDV PDF v DDV\\ in SEPA virman.xml v Virmani\\ (kot Minimax)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = company_registry.company_name(company)
    tax = company_registry.company_tax_number(company)
    iban = normalize_iban(payer_iban) or company_iban(company)
    address = str(company.get("NASLOV") or company.get("Naslov") or "").strip()
    street, city = split_slovenian_address(address)
    exec_dt = execution_date or default_ddv_due_date(period_to)
    xml_text = build_furs_ddv_pain001_xml(
        payer_name=name,
        payer_iban=iban,
        payer_tax_id=tax,
        amount=payment,
        payer_street=street,
        payer_city=city,
        remittance=remittance,
        execution_date=exec_dt,
        period_from=period_from,
        period_to=period_to,
    )
    # PDF ostane v DDV; virman gre v TROPS\{Zšt}\Virmani.
    if virman_dir is not None:
        vdir = Path(virman_dir)
    else:
        try:
            paths = company_registry.company_paths(company, period_from, period_to)
            vdir = paths.virmani_root
        except (TypeError, ValueError):
            vdir = out_dir
    vdir.mkdir(parents=True, exist_ok=True)

    pdf_target = out_dir / client_pdf_filename(name, period_from, period_to)
    virman_target = vdir / virman_filename(name, period_from, period_to)
    source = Path(source_pdf)
    if source.resolve() != pdf_target.resolve():
        pdf_target.write_bytes(source.read_bytes())
    else:
        pdf_target = source
    virman_target.write_text(xml_text, encoding="utf-8")
    return DdvoVirmanPackage(
        payment=core.decimal_value(payment),
        obligation=core.decimal_value(obligation),
        konto62_credit=core.decimal_value(konto62_credit),
        reference=furs_ddv_reference(tax),
        creditor_iban=FURS_CREDITOR_IBAN,
        debtor_iban=iban,
        execution_date=exec_dt,
        pdf_path=pdf_target,
        virman_path=virman_target,
        out_dir=out_dir,
        virman_dir=vdir,
        email_to=company_email(company),
    )


def period_label_short(period_from: str, period_to: str) -> str:
    """Npr. 2026/06 ali 2026/04–06."""
    start = str(period_from or "")[:10]
    end = str(period_to or "")[:10]
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d").date()
        d1 = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return end or start or ""
    if d0.year == d1.year and d0.month == d1.month:
        return f"{d1.year}/{d1.month:02d}"
    if d0.year == d1.year:
        return f"{d1.year}/{d0.month:02d}–{d1.month:02d}"
    return f"{d0.year}/{d0.month:02d}–{d1.year}/{d1.month:02d}"


DEFAULT_SIGNATURE_LINES = (
    "Braco MIHELJ",
    "tel.: 041.653.170",
    "eMail:",
    "braco.mihelj@gmail.com",
    "bracom@windowslive.com",
    "braco.mihelj@iCloud.com",
    "info@quickmb.si",
    "info@quickmb.com",
    "quickmb@outlook.com",
)

DEFAULT_OUTLOOK_FROM = "info@quickmb.com"
OUTLOOK_FROM_ACCOUNTS = (
    "braco.mihelj@gmail.com",
    "bracom@windowslive.com",
    "info@quickmb.com",
    "info@quickmb.si",
)

# Ista pošta v Outlooku je lahko kot .com ali .si — strogo mapiranje.
_OUTLOOK_FROM_ALIASES: dict[str, tuple[str, ...]] = {
    "info@quickmb.com": ("info@quickmb.com", "info@quickmb.si"),
    "info@quickmb.si": ("info@quickmb.si", "info@quickmb.com"),
    "bracom@windowslive.com": ("bracom@windowslive.com",),
    "braco.mihelj@gmail.com": ("braco.mihelj@gmail.com",),
}


def format_konto62_client_notice(konto62: Any, *, html: bool = False) -> str:
    """Obvestilo stranki o stanju konta 62 (v dobro / še neplačano). Prazno, če je 0.

    Besedilo urejaš v formi »Besedila {…}« (datoteka ddvo_placeholder_texts.json).
    """
    import kirkpr_ddvo_placeholder_texts as placeholder_texts

    return placeholder_texts.format_konto62_notice_from_texts(konto62, html=html)


def format_si_money(amount: Any) -> str:
    value = core.decimal_value(amount)
    text = f"{value:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_presezek_obvestilo(excess: Any, vracilo: bool = False) -> str:
    """HTML blok za e-pošto, ko je polje 52 (presežek) > 0 — kot DDV-O Oddaje 1.0.64+."""
    amount = core.decimal_value(excess)
    if amount <= ZERO:
        return ""
    amt = format_si_money(amount)
    if vracilo:
        detail = (
            '<strong><span style="color:#1565C0">Zahtevano je vračilo presežka.</span></strong>'
        )
    else:
        detail = (
            '<strong><span style="color:#1565C0">DDV ostane '
            "(vračilo ni zahtevano).</span></strong>"
        )
    return (
        f"<p></p>\n"
        f'<p><strong><span style="color:#1565C0">V obračunu DDV-O je presežek: '
        f"{amt} EUR.</span></strong><br>\n{detail}</p>\n"
    )


def format_priloga_obvestilo(*, has_payment: bool, has_excess: bool = False) -> str:
    """Besedilo o priponkah (PDF ± virman) — kot Oddaje."""
    if has_payment:
        return (
            '<span style="color:#1565C0">V prilogi sta obračun DDV-O (PDF) '
            "in plačilni nalog (virman.xml, QR koda).</span>"
        )
    if has_excess:
        return (
            '<span style="color:#1565C0">V prilogi je obračun DDV-O (PDF). '
            "Plačilni nalog ni potreben (presežek).</span>"
        )
    return '<span style="color:#1565C0">V prilogi je obračun DDV-O (PDF).</span>'


def format_placilo_block(payment: Any) -> str:
    """HTML vrstica »Znesek za plačilo« — kot Oddaje (18 pt, rdeče)."""
    pay = core.decimal_value(payment)
    if pay <= ZERO:
        return ""
    return (
        '<div><span style="font-family:Calibri,sans-serif;font-size:18pt;">'
        f'<p><strong><span style="color:#C62828">Znesek za plačilo: '
        f"{format_si_money(pay)} EUR</span></strong></p></span></div>"
    )


def format_payment_lines(obligation: Any, konto62_credit: Any, payment: Any) -> tuple[str, str]:
    """Vrstici za e-pošto: obvestilo o 62 (če obstaja) + znesek za plačilo."""
    obl = core.decimal_value(obligation)
    saldo = core.edavki_konto62_saldo(konto62_credit)
    pay = core.decimal_value(payment)

    def si(amount: Decimal) -> str:
        text = f"{amount:,.2f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")

    notice = format_konto62_client_notice(saldo, html=False)
    line1 = notice
    if notice and obl != 0:
        line1 = f"Obveznost DDV-O: {si(obl)} EUR. {notice}"
    elif not notice and saldo == 0:
        line1 = ""
    line2 = f"Znesek za plačilo: {si(pay)} EUR"
    return line1, line2


def build_ddvo_client_email(
    *,
    company_name: str,
    period_from: str,
    period_to: str,
    obligation: Any,
    konto62_credit: Any,
    payment: Any,
    reference: str = "",
    creditor_iban: str = FURS_CREDITOR_IBAN,
    execution_date: date | None = None,
    postscript: str = "",
    html: bool = False,
) -> tuple[str, str]:
    """Vrne (zadeva, telo) za sporočilo stranki — urejljivo pred Outlookom."""
    nagovor = str(company_name or "").strip()
    parts = nagovor.split()
    short_label = parts[0].rstrip(".,") if parts else nagovor
    period = period_label_short(period_from, period_to)
    line1, line2 = format_payment_lines(obligation, konto62_credit, payment)
    subject = f"DDV za obdobje ({period}) — {short_label}"
    lines = [
        f"Spoštovani/a, ({short_label}).",
        "",
        f"DDV za obdobje ({period})",
        "",
    ]
    obl = core.decimal_value(obligation)
    if obl != 0:
        def si(amount: Decimal) -> str:
            text = f"{amount:,.2f}"
            return text.replace(",", "X").replace(".", ",").replace("X", ".")

        lines.append(f"Obveznost DDV-O: {si(obl)} EUR")
    notice = format_konto62_client_notice(konto62_credit, html=False)
    if notice:
        lines.append(notice)
    lines.extend(
        [
            line2,
            "",
            "V prilogi sta obračun DDV-O (PDF) in plačilni nalog (virman.xml).",
        ]
    )
    if reference:
        lines.append(f"Referenca: {reference}")
    if creditor_iban:
        lines.append(f"IBAN prejemnika: {creditor_iban}")
    if execution_date:
        lines.append(f"Datum izvršitve: {execution_date.strftime('%d.%m.%Y')}")
    ps = str(postscript or "").strip()
    if ps:
        lines.extend(["", "p.s.:", ps])
    lines.extend(["", "Lep pozdrav,", ""])
    lines.extend(DEFAULT_SIGNATURE_LINES)
    body = "\n".join(lines)
    if html:
        esc = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        esc = esc.replace(
            line2.replace("&", "&amp;"),
            f"<strong>{line2}</strong>",
        )
        html_body = "<br>\n".join(esc.split("\n"))
        return subject, f"<div style='font-family:Calibri,Arial,sans-serif;font-size:11pt;'>{html_body}</div>"
    return subject, body


def _outlook_zero_paragraph_spacing(mail: Any) -> bool:
    """Outlook Word: SpaceBefore/After = 0 (sicer se ob Send razvleče)."""
    try:
        editor = mail.GetInspector.WordEditor
        if editor is None:
            return False
        rng = editor.Content
        fmt = rng.ParagraphFormat
        fmt.SpaceAfter = 0
        fmt.SpaceBefore = 0
        try:
            # wdLineSpaceSingle = 0
            fmt.LineSpacingRule = 0
        except Exception:
            pass
        return True
    except Exception:
        return False


def compose_outlook_with_attachments(
    *,
    to_addr: str,
    subject: str,
    body: str,
    attachments: list[Path],
    html: bool = False,
    from_smtp: str = DEFAULT_OUTLOOK_FROM,
    deferred_send: datetime | None = None,
    read_receipt: bool = True,
    delivery_receipt: bool = True,
    line_height: str = "1.35",
    para_spacing_px: int = 4,
    upn_qr_png: Path | str | None = None,
    send_now: bool = True,
    cc: str = "",
    bcc: str = "",
) -> tuple[bool, str]:
    """Sestavi Outlook sporočilo s priponkami in ga pošlje (privzeto).

    - from_smtp: račun pošiljatelja (iz comboboxa) — mora obstajati v Outlooku
    - deferred_send: odloženo pošiljanje (Outlook Outbox do tega časa)
    - read_receipt / delivery_receipt: zahteva potrdilo o odprtju / prejemu
    - line_height / para_spacing_px: razmiki kot v Transkriptu
    - upn_qr_png: PNG UPN QR → vdelava v HTML kot cid:ddvo_upn_qr
    - send_now: True = Send() brez ročnega klikа; False = samo Display osnutka
    """
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False, "Manjka pywin32 (win32com) — odprem mapo; priponi ročno."
    try:
        import kirkpr_upn_qr as upn_qr

        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        notes: list[str] = []
        wanted = str(from_smtp or DEFAULT_OUTLOOK_FROM).strip() or DEFAULT_OUTLOOK_FROM

        account = _pick_outlook_account(outlook, wanted)
        applied_from = _apply_send_account(mail, account, wanted)
        if applied_from:
            notes.append(f"Od: {applied_from}")
        elif account is None:
            available = list_outlook_account_addresses(outlook)
            avail_txt = ", ".join(available) if available else "(ni računov)"
            notes.append(
                f"POZOR: račun {wanted} ni v Outlooku — pusti privzeti Od. "
                f"Razpoložljivi: {avail_txt}"
            )
        else:
            notes.append(
                f"POZOR: Od {wanted} najden, a Outlook ga ni sprejel — preveri Od: ročno"
            )

        to_norm = _apply_outlook_to(mail, to_addr or "")
        if not to_norm:
            return False, "Manjka prejemnik (Za:)."
        notes.append(f"Za: {to_norm}")
        cc_norm = normalize_outlook_recipients(cc)
        bcc_norm = normalize_outlook_recipients(bcc)
        if cc_norm:
            try:
                mail.CC = cc_norm
                notes.append(f"KP/CC: {cc_norm}")
            except Exception as exc:
                notes.append(f"KP/CC ni uspel ({exc})")
        if bcc_norm:
            try:
                mail.BCC = bcc_norm
                notes.append(f"SKP/BCC: {bcc_norm}")
            except Exception as exc:
                notes.append(f"SKP/BCC ni uspel ({exc})")
        mail.Subject = subject

        qr_path = Path(upn_qr_png) if upn_qr_png else None
        body_html = str(body or "")
        qr_embedded = False
        if qr_path is not None and qr_path.is_file():
            body_html = upn_qr.inject_upn_qr_img(body_html)
            try:
                att = mail.Attachments.Add(str(qr_path.resolve()))
                # PR_ATTACH_CONTENT_ID
                att.PropertyAccessor.SetProperty(
                    "http://schemas.microsoft.com/mapi/proptag/0x3712001F",
                    upn_qr.UPN_QR_CID,
                )
                try:
                    # PR_ATTACHMENT_HIDDEN — skrij iz seznama priponk (samo v telesu).
                    att.PropertyAccessor.SetProperty(
                        "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B",
                        True,
                    )
                except Exception:
                    pass
                qr_embedded = True
                notes.append("UPN QR v telesu")
            except Exception as exc:
                notes.append(f"UPN QR ni vdelan ({exc})")

        if html or ("<" in body_html and "</" in body_html):
            try:
                import kirkpr_ddvo_email_templates as email_tpl

                # olFormatHTML = 2 — Word/Outlook naj ohrani HTML.
                mail.BodyFormat = 2
                mail.HTMLBody = email_tpl.wrap_outlook_html(
                    body_html,
                    line_height=line_height,
                    para_spacing_px=para_spacing_px,
                    reformat=False,
                )
            except Exception:
                mail.HTMLBody = body_html
        else:
            mail.Body = body_html

        # HTMLBody lahko resetira Od — nastavi še enkrat (Invoke 64209).
        applied_from = _apply_send_account(mail, account, wanted) or applied_from
        try:
            mail.ReadReceiptRequested = bool(read_receipt)
        except Exception:
            pass
        try:
            mail.OriginatorDeliveryReportRequested = bool(delivery_receipt)
        except Exception:
            pass
        if read_receipt:
            notes.append("potrdilo o odprtju")
        if delivery_receipt:
            notes.append("potrdilo o prejemu")
        notes.append(f"vrstica {line_height} / odstavek {para_spacing_px}px")

        if deferred_send is not None:
            try:
                mail.DeferredDeliveryTime = deferred_send
                notes.append(f"odloženo: {deferred_send.strftime('%d.%m.%Y %H:%M')}")
            except Exception as exc:
                notes.append(f"odloženo ni uspelo ({exc})")

        for path in attachments:
            if not Path(path).is_file():
                continue
            if qr_embedded and qr_path is not None and Path(path).resolve() == qr_path.resolve():
                continue
            mail.Attachments.Add(str(Path(path).resolve()))

        # Pred pošiljanjem znova Od: + To: (Word/HTML včasih pobriše).
        _apply_send_account(mail, account, wanted)
        _apply_outlook_to(mail, to_norm)

        final_smtp = _mail_send_account_smtp(mail) or applied_from
        wanted_cf = wanted.casefold()
        aliases = {a.casefold() for a in _OUTLOOK_FROM_ALIASES.get(wanted, (wanted,))}
        aliases.add(wanted_cf)
        ok_from = bool(final_smtp) and final_smtp.casefold() in aliases
        detail = " · ".join(notes) if notes else "sporočilo"

        if not send_now:
            mail.Display(False)
            # Word razmik šele po Display (sicer E_INVALIDARG).
            if _outlook_zero_paragraph_spacing(mail):
                notes.append("razmik Word=0")
            applied_after = _apply_send_account(mail, account, wanted)
            if applied_after:
                final_smtp = applied_after
            detail = " · ".join(notes) if notes else "osnutek"
            if account is None or not ok_from:
                return (
                    True,
                    f"Outlook osnutek je odprt ({detail}). "
                    f"Preveri Od: — želeno {wanted}, trenutno {final_smtp or '(privzeto)'}!",
                )
            return True, f"Outlook osnutek je odprt ({detail})."

        # Pošlji takoj (pregled je bil v urejevalniku) — brez dialoga Preverjanje imen.
        # Ne kliči Word GetInspector pred Send (parameter incorrect).
        try:
            mail.Send()
        except Exception as exc:
            try:
                mail.Display(False)
                _outlook_zero_paragraph_spacing(mail)
                _apply_send_account(mail, account, wanted)
                _apply_outlook_to(mail, to_norm)
            except Exception:
                pass
            return (
                False,
                f"Outlook Send ni uspel ({exc}). Osnutek odprt za ročno pošiljanje. ({detail})",
            )
        if account is None or not ok_from:
            return (
                True,
                f"E-pošta poslana / v Outbox ({detail}). "
                f"Preveri Od: — želeno {wanted}, uporabljeno {final_smtp or '(neznano)'}!",
            )
        if deferred_send is not None:
            return True, f"E-pošta v Outbox (odloženo) · {detail}."
        return True, f"E-pošta poslana · {detail}."
    except Exception as exc:
        return False, f"Outlook ni uspel: {exc}"


def list_outlook_account_addresses(outlook: Any | None = None) -> list[str]:
    """Seznam SMTP naslovov iz Outlook Session.Accounts (za combobox / diagnostiko)."""
    try:
        if outlook is None:
            import win32com.client  # type: ignore

            outlook = win32com.client.Dispatch("Outlook.Application")
        accounts = outlook.Session.Accounts
    except Exception:
        return []
    rows: list[str] = []
    for index in range(1, int(accounts.Count) + 1):
        try:
            account = accounts.Item(index)
            smtp = str(getattr(account, "SmtpAddress", "") or "").strip()
            if smtp and smtp not in rows:
                rows.append(smtp)
        except Exception:
            continue
    return rows


def _account_smtp(account: Any) -> str:
    return str(getattr(account, "SmtpAddress", "") or "").strip()


def _mail_send_account_smtp(mail: Any) -> str:
    """Dejansko nastavljeni SendUsingAccount (prazno = ni nastavljen)."""
    try:
        current = mail.SendUsingAccount
    except Exception:
        return ""
    if current is None:
        return ""
    return _account_smtp(current)


def _set_send_using_account(mail: Any, account: Any) -> bool:
    """Nastavi račun pošiljatelja.

    Na mnogih Outlook zgradbah ``mail.SendUsingAccount = account`` tiho ne
    deluje (branje vrne None). Zanesljiv način: OLE Invoke dispid 64209.
    """
    if account is None:
        return False
    # 1) Klasika — včasih deluje
    try:
        mail.SendUsingAccount = account
    except Exception:
        pass
    if _mail_send_account_smtp(mail):
        return True
    # 2) Znani workaround (pywin32 / Outlook)
    try:
        mail._oleobj_.Invoke(*(64209, 0, 8, 0, account))
    except Exception:
        pass
    return bool(_mail_send_account_smtp(mail))


def _apply_send_account(mail: Any, account: Any | None, wanted_smtp: str) -> str:
    """Nastavi SendUsingAccount; vrne dejanski SMTP ali ''."""
    wanted = str(wanted_smtp or "").strip()
    if account is not None:
        if _set_send_using_account(mail, account):
            return _mail_send_account_smtp(mail) or _account_smtp(account) or wanted
    if wanted:
        try:
            mail.SentOnBehalfOfName = wanted
        except Exception:
            pass
    return ""


def _pick_outlook_account(outlook: Any, preferred_smtp: str = "") -> Any | None:
    """Najdi Outlook račun — točen SMTP, alias .com/.si, ali DisplayName z e-naslovom."""
    preferred = str(preferred_smtp or "").strip().casefold()
    if not preferred:
        return None
    aliases = {
        a.casefold()
        for a in _OUTLOOK_FROM_ALIASES.get(preferred, (preferred,))
    }
    aliases.add(preferred)
    try:
        accounts = outlook.Session.Accounts
    except Exception:
        return None

    exact: Any | None = None
    alias_hit: Any | None = None
    display_hit: Any | None = None
    for index in range(1, int(accounts.Count) + 1):
        try:
            account = accounts.Item(index)
        except Exception:
            continue
        smtp = _account_smtp(account).casefold()
        display = str(getattr(account, "DisplayName", "") or "").casefold()
        if smtp and smtp == preferred:
            exact = account
            break
        if smtp and smtp in aliases and alias_hit is None:
            alias_hit = account
        # DisplayName pogosto vsebuje SMTP tudi ko SmtpAddress obstaja
        if preferred in display or any(a in display for a in aliases):
            if display_hit is None:
                display_hit = account
    return exact or alias_hit or display_hit


def parse_deferred_send_si(text: str) -> datetime | None:
    """Razčleni »dd.mm.yyyy HH:MM« ali »dd.mm.yyyy«. Prazno = None."""
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H.%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%d.%m.%Y":
                # Samo datum → 8:00 (delovni začetek).
                dt = dt.replace(hour=8, minute=0, second=0, microsecond=0)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Neveljaven datum/čas odložitve: {raw!r} (pričakovano dd.mm.yyyy HH:MM)")


__all__ = [
    "DdvoVirmanPackage",
    "DEFAULT_OUTLOOK_FROM",
    "OUTLOOK_FROM_ACCOUNTS",
    "DEFAULT_SIGNATURE_LINES",
    "FURS_CREDITOR_IBAN",
    "FURS_CREDITOR_NAME",
    "FURS_DDV_CHARGE_CODE",
    "FURS_PURPOSE_CODE",
    "bic_from_iban",
    "normalize_bic",
    "build_ddvo_client_email",
    "build_furs_ddv_pain001_xml",
    "client_pdf_filename",
    "company_email",
    "company_iban",
    "compose_outlook_with_attachments",
    "default_ddv_due_date",
    "format_konto62_client_notice",
    "format_payment_lines",
    "format_placilo_block",
    "format_presezek_obvestilo",
    "format_priloga_obvestilo",
    "format_si_money",
    "furs_ddv_reference",
    "furs_ddv_reference_sepa",
    "list_outlook_account_addresses",
    "normalize_iban",
    "normalize_outlook_recipients",
    "parse_deferred_send_si",
    "parse_outlook_recipients",
    "period_label_short",
    "remittance_period_label",
    "split_slovenian_address",
    "virman_filename",
    "write_virman_package",
]
