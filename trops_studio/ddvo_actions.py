"""DDV-O dejanja kot v KirKpr: PDF/XML, predogled, virman, Gmail SMTP."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio.companies import company_name, company_tax, company_zst
from trops_studio.config import DEFAULT_MINIMAX_OUT, TROPS_ROOT
from trops_studio.ddvo_calc import build_dataset, compute_ddvo
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path
from trops_studio.money import money_text, normalize_text


@dataclass
class DdvoExportResult:
    pdf_path: Path | None = None
    xml_path: Path | None = None
    package_dir: Path | None = None
    virman_path: Path | None = None
    payment: Decimal = Decimal("0.00")
    obligation: Decimal = Decimal("0.00")
    message: str = ""


def _company_root(zst: str) -> Path | None:
    """Mapa podjetja ``TROPS_ROOT\\<Zšt>`` (npr. D:\\Trops\\21, D:\\Trops\\41) — kot KirKpr in MRN."""
    if not zst or not str(zst).isdigit():
        return None
    return Path(TROPS_ROOT) / str(int(zst)).zfill(2)


def _out_dir(company: Mapping[str, Any] | None = None) -> Path:
    """Izhodna mapa DDV-O: ``TROPS_ROOT\\<Zšt>\\DDV`` (5.1: prej napačno ``TROPS_ROOT\\21\\<Zšt>\\DDV``)."""
    root = _company_root(company_zst(company or {}))
    if root is not None and root.is_dir():
        path = root / "DDV"
        path.mkdir(parents=True, exist_ok=True)
        return path
    label = company_name(company or {}) or "PROJEST"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
    path = Path(DEFAULT_MINIMAX_OUT) / "DDV-O" / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pdf_kwargs(company: Mapping[str, Any] | None) -> dict[str, Any]:
    company = dict(company or {})
    return {
        "company_name": company_name(company),
        "address": normalize_text(
            company.get("NASLOV") or company.get("Naslov") or company.get("address") or ""
        ),
    }


def enrich_dataset_header(dataset: Any, company: Mapping[str, Any] | None) -> Any:
    tax = company_tax(company or {})
    name = company_name(company or {})
    header = dict(getattr(dataset, "header", {}) or {})
    if tax:
        header["TaxPayerID"] = tax
        header.setdefault("DavcnaStevilka", tax)
    if name:
        header.setdefault("TaxpayerName", name)
        header.setdefault("Naziv", name)
    addr = _pdf_kwargs(company).get("address") or ""
    if addr:
        header.setdefault("Address", addr)
        header.setdefault("NASLOV", addr)
    dataset.header = header
    return dataset


def make_dataset(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
    *,
    period_from: date | None,
    period_to: date | None,
    company: Mapping[str, Any] | None = None,
) -> Any:
    ensure_kirkpr_on_path()
    dataset = build_dataset(ir_rows, pr_rows, period_from=period_from, period_to=period_to)
    return enrich_dataset_header(dataset, company)


def export_pdf_xml(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
    *,
    period_from: date | None,
    period_to: date | None,
    company: Mapping[str, Any] | None = None,
) -> DdvoExportResult:
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_pdf as ddvo_pdf  # type: ignore
    import kirkpr_ddvo_xml as ddvo_xml  # type: ignore

    dataset = make_dataset(
        ir_rows, pr_rows, period_from=period_from, period_to=period_to, company=company
    )
    out = _out_dir(company)
    kwargs = _pdf_kwargs(company)
    pdf_path = out / ddvo_pdf.default_ddvo_pdf_name(dataset)
    xml_path = out / ddvo_xml.default_ddvo_xml_name(dataset)
    ddvo_pdf.build_ddvo_pdf(dataset, pdf_path, **kwargs)
    ddvo_xml.write_ddvo_xml(dataset, xml_path, **kwargs)
    return DdvoExportResult(
        pdf_path=pdf_path,
        xml_path=xml_path,
        message=f"DDV-O: {pdf_path.name} + {xml_path.name}\n{out}",
    )


def preview_pdf(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
    *,
    period_from: date | None,
    period_to: date | None,
    company: Mapping[str, Any] | None = None,
) -> Path:
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_pdf as ddvo_pdf  # type: ignore

    dataset = make_dataset(
        ir_rows, pr_rows, period_from=period_from, period_to=period_to, company=company
    )
    target = Path(tempfile.gettempdir()) / ddvo_pdf.default_ddvo_pdf_name(dataset)
    ddvo_pdf.build_ddvo_pdf(dataset, target, **_pdf_kwargs(company))
    return target


def open_path(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        logging.getLogger(__name__).warning("Datoteke %s ni mogoče odpreti", path, exc_info=True)


def create_virman_package(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
    *,
    period_from: date | None,
    period_to: date | None,
    company: Mapping[str, Any] | None = None,
    konto62_credit: Decimal | float | str = 0,
    payer_iban: str = "",
) -> DdvoExportResult:
    """Lokalni PDF + SEPA virman (kot KirKpr »PDF + virman«)."""
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_virman as ddvo_virman  # type: ignore

    exported = export_pdf_xml(
        ir_rows,
        pr_rows,
        period_from=period_from,
        period_to=period_to,
        company=company,
    )
    if not exported.pdf_path:
        return exported
    summary = compute_ddvo(ir_rows, pr_rows, period_from=period_from, period_to=period_to)
    obligation = Decimal(str(summary.get("obligation") or 0))
    company_rec = dict(company or {})
    credit = Decimal(str(konto62_credit or 0))
    payment = max(obligation - credit, Decimal("0.00"))
    package = ddvo_virman.write_virman_package(
        exported.pdf_path.parent,
        company=company_rec,
        period_from=str(period_from or ""),
        period_to=str(period_to or ""),
        obligation=obligation,
        konto62_credit=credit,
        payment=payment,
        source_pdf=exported.pdf_path,
        payer_iban=payer_iban or ddvo_virman.company_iban(company_rec),
        remittance=f"DDV-O {period_from} – {period_to}",
    )
    return DdvoExportResult(
        pdf_path=package.pdf_path,
        xml_path=exported.xml_path,
        package_dir=package.out_dir,
        virman_path=package.virman_path,
        payment=payment,
        obligation=obligation,
        message=(
            f"Paket DDV-O + virman\n"
            f"• PDF: {package.pdf_path}\n"
            f"• Virman: {package.virman_path}\n"
            f"• Polje 51: {money_text(obligation)} EUR\n"
            f"• Plačilo: {money_text(payment)} EUR"
        ),
    )


GMAIL_SMTP_FROM = "braco.mihelj@gmail.com"
GMAIL_SMTP_CC = "info@quickmb.com"


def client_email_to(company: Mapping[str, Any] | None) -> str:
    """E-naslov stranke iz evidence (Email)."""
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_virman as ddvo_virman  # type: ignore

    return str(ddvo_virman.company_email(dict(company or {})) or "").strip()


def compose_client_email(
    *,
    company: Mapping[str, Any] | None,
    period_from: date | None,
    period_to: date | None,
    obligation: Decimal | float | str,
    konto62_credit: Decimal | float | str = 0,
    payment: Decimal | float | str = 0,
    attachments: Sequence[Path] | None = None,
    send_now: bool = True,
    cc: str = GMAIL_SMTP_CC,
) -> str:
    """Pošlje DDV-O e-pošto prek Gmail SMTP (braco.mihelj@gmail.com)."""
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_smtp as ddvo_smtp  # type: ignore
    import kirkpr_ddvo_virman as ddvo_virman  # type: ignore

    company_rec = dict(company or {})
    to_addr = client_email_to(company_rec)
    if not to_addr:
        raise RuntimeError("Manjka e-pošta stranke (polje Email v evidenci firm).")
    ok, secret_note = ddvo_smtp.smtp_available()
    if not ok:
        raise RuntimeError(f"Gmail SMTP ni pripravljen: {secret_note}")
    subject, body = ddvo_virman.build_ddvo_client_email(
        company_name=company_name(company_rec),
        period_from=str(period_from or ""),
        period_to=str(period_to or ""),
        obligation=obligation,
        konto62_credit=konto62_credit,
        payment=payment,
        html=True,
    )
    if not send_now:
        return (
            f"Pripravljeno (ni poslano)\n"
            f"Od: {GMAIL_SMTP_FROM}\nZa: {to_addr}\n"
            f"Zadeva: {subject}"
        )
    return send_gmail_email(
        to_addr=to_addr,
        subject=subject,
        body_html=body,
        cc=cc,
        attachments=attachments,
    )


def send_gmail_email(
    *,
    to_addr: str,
    subject: str,
    body_html: str,
    cc: str = GMAIL_SMTP_CC,
    attachments: Sequence[Path] | None = None,
) -> str:
    """Pošlje Gmail SMTP (465/587) — skupni kanal za DDV-O in seznam nepravilnosti."""
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_smtp as ddvo_smtp  # type: ignore

    to_addr = str(to_addr or "").strip()
    if not to_addr:
        raise RuntimeError("Manjka e-pošta prejemnika.")
    ok, secret_note = ddvo_smtp.smtp_available()
    if not ok:
        raise RuntimeError(f"Gmail SMTP ni pripravljen: {secret_note}")
    mode = ddvo_smtp.send_smtp(
        to_addr=to_addr,
        subject=subject,
        body=body_html,
        attachments=list(attachments or ()),
        html=True,
        cc=cc,
    )
    kp = f"\nKP: {cc}" if str(cc or "").strip() else ""
    return (
        f"Poslano prek Gmail SMTP ({mode})\n"
        f"Od: {GMAIL_SMTP_FROM}\nZa: {to_addr}{kp}\n"
        f"Zadeva: {subject}"
    )


def send_vat_irregularities_email(
    *,
    company: Mapping[str, Any] | None,
    subject: str,
    body_html: str,
    cc: str = GMAIL_SMTP_CC,
    to_addr: str = "",
) -> str:
    """Pošlje seznam nepravilnih davčnih stranki prek Gmail SMTP."""
    dest = (to_addr or client_email_to(company)).strip()
    if not dest:
        raise RuntimeError("Manjka e-pošta stranke (polje Email v evidenci firm).")
    return send_gmail_email(
        to_addr=dest,
        subject=subject,
        body_html=body_html,
        cc=cc,
    )


def ddvo_client_mail_draft(
    *,
    company: Mapping[str, Any] | None,
    period_from: date | None,
    period_to: date | None,
    obligation: Decimal | float | str,
    konto62_credit: Decimal | float | str = 0,
    payment: Decimal | float | str = 0,
) -> tuple[str, str, str]:
    """Osnutek DDV-O sporočila: (Za, zadeva, HTML telo)."""
    ensure_kirkpr_on_path()
    import kirkpr_ddvo_virman as ddvo_virman  # type: ignore

    to_addr = client_email_to(company)
    subject, body = ddvo_virman.build_ddvo_client_email(
        company_name=company_name(dict(company or {})),
        period_from=str(period_from or ""),
        period_to=str(period_to or ""),
        obligation=obligation,
        konto62_credit=konto62_credit,
        payment=payment,
        html=True,
    )
    return to_addr, subject, body
