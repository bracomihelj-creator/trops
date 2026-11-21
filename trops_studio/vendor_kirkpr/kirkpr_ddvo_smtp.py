"""Gmail SMTP pošiljanje DDV e-pošte (alternativa Outlooku) + UPN QR inline."""

from __future__ import annotations

import mimetypes
import smtplib
import socket
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from trops_studio.config import SMTP_SECRET_CANDIDATES

SMTP_HOST = "smtp.gmail.com"
SENDER_EMAIL = "braco.mihelj@gmail.com"
SMTP_TIMEOUT = 15

_FORWARD_SECRET, _ODDAJE_SECRET, _EDAVKI_SECRET = SMTP_SECRET_CANDIDATES
_LOCAL_SECRET = Path(__file__).resolve().parent / "smtp_secret.bin"


class SmtpSendError(RuntimeError):
    pass


def _secret_candidates() -> list[Path]:
    return [_LOCAL_SECRET, _FORWARD_SECRET, _ODDAJE_SECRET, _EDAVKI_SECRET]


def smtp_secret_path() -> Path | None:
    return next((p for p in _secret_candidates() if p.is_file()), None)


def load_smtp_secret() -> str:
    try:
        import win32crypt  # type: ignore
    except ImportError as exc:
        raise SmtpSendError("Manjka pywin32 (win32crypt) za SMTP geslo.") from exc
    path = smtp_secret_path()
    if path is None:
        raise SmtpSendError(
            "Ni smtp_secret.bin (Gmail App Password).\n"
            "Ustvari ga v Minimax_forward\\server (setup_secret.py) ali skopiraj sem."
        )
    encrypted = path.read_bytes()
    decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
    return decrypted[1].decode("utf-8")


def _clean_password(value: str) -> str:
    return str(value or "").replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "").strip()


def _friendly_error(exc: BaseException) -> str:
    raw = str(exc)
    if isinstance(exc, smtplib.SMTPAuthenticationError) or "Username and Password not accepted" in raw:
        return "Gmail SMTP ne sprejme gesla (App Password)."
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in raw.lower():
        return "Povezava na Gmail SMTP je potekla."
    return raw or exc.__class__.__name__


def _prepare_html(
    body: str,
    *,
    qr_png: Path | None,
    line_height: str = "1.0",
    para_spacing_px: int = 4,
) -> str:
    """Ohrani HTML iz belega polja (barve, velikosti) — kot Oddaje wrap_mail_html."""
    import re

    text = str(body or "")
    # Če je že poln HTML iz wrapa, vzemi body.
    found = re.search(r"<body[^>]*>(.*)</body>", text, flags=re.I | re.S)
    if found:
        text = found.group(1)
    if qr_png is not None and qr_png.is_file():
        try:
            import kirkpr_upn_qr as upn_qr

            text = upn_qr.inject_upn_qr_img(text)
        except Exception:
            pass
    try:
        import kirkpr_ddvo_email_templates as email_tpl

        # reformat=False = ohrani span barve/font iz programa; samo razmiki.
        return email_tpl.wrap_outlook_html(
            text,
            line_height=line_height,
            para_spacing_px=para_spacing_px,
            reformat=False,
        )
    except Exception:
        return text


def send_smtp(
    *,
    to_addr: str,
    subject: str,
    body: str,
    attachments: list[str | Path],
    html: bool = True,
    reply_to: str = "",
    cc: str = "",
    bcc: str = "",
    upn_qr_png: str | Path | None = None,
    line_height: str = "1.35",
    para_spacing_px: int = 4,
) -> str:
    """Pošlje prek Gmail SMTP. Vrne način (smtp:465 / smtp:587)."""
    to_addr = str(to_addr or "").strip()
    if not to_addr:
        raise SmtpSendError("Manjka prejemnik.")
    password = _clean_password(load_smtp_secret())
    if not password:
        raise SmtpSendError("SMTP geslo je prazno.")

    qr_path = Path(upn_qr_png) if upn_qr_png else None
    if qr_path is not None and not qr_path.is_file():
        qr_path = None

    body_html = _prepare_html(
        body,
        qr_png=qr_path,
        line_height=line_height,
        para_spacing_px=para_spacing_px,
    )

    if html and qr_path is not None and "cid:ddvo_upn_qr" in body_html:
        msg: MIMEMultipart = MIMEMultipart("related")
        alt = MIMEMultipart("alternative")
        msg.attach(alt)
        alt.attach(MIMEText(body_html, "html", "utf-8"))
        img = MIMEImage(qr_path.read_bytes(), _subtype="png")
        img.add_header("Content-ID", "<ddvo_upn_qr>")
        img.add_header("Content-Disposition", "inline", filename=qr_path.name)
        msg.attach(img)
    else:
        msg = MIMEMultipart()
        subtype = "html" if html else "plain"
        msg.attach(MIMEText(body_html if html else (body or ""), subtype, "utf-8"))

    msg["From"] = formataddr(("Braco MIHELJ", SENDER_EMAIL))
    msg["To"] = to_addr
    cc_norm = str(cc or "").replace(",", ";").strip()
    bcc_norm = str(bcc or "").replace(",", ";").strip()
    if cc_norm:
        msg["Cc"] = cc_norm
    if bcc_norm:
        msg["Bcc"] = bcc_norm
    rt = str(reply_to or "").strip()
    if rt and rt.casefold() != SENDER_EMAIL.casefold():
        msg["Reply-To"] = rt
    msg["Subject"] = subject or "(brez zadeve)"

    skip_qr = qr_path.resolve() if qr_path is not None else None
    for raw in attachments:
        path = Path(raw)
        if not path.is_file():
            raise SmtpSendError(f"Priponka ne obstaja: {path}")
        if skip_qr is not None and path.resolve() == skip_qr:
            continue
        data = path.read_bytes()
        ctype, _ = mimetypes.guess_type(str(path))
        main, sub = (ctype or "application/octet-stream").split("/", 1)
        part = MIMEApplication(data, _subtype=sub if main == "application" else "octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)

    recipients = [a.strip() for a in to_addr.replace(";", ",").split(",") if a.strip()]
    if cc_norm:
        recipients.extend(a.strip() for a in cc_norm.replace(";", ",").split(",") if a.strip())
    if bcc_norm:
        recipients.extend(a.strip() for a in bcc_norm.replace(";", ",").split(",") if a.strip())
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for addr in recipients:
        key = addr.casefold()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(addr)
    recipients = uniq

    errors: list[str] = []
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=SMTP_TIMEOUT) as server:
            server.login(SENDER_EMAIL, password)
            server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        return "smtp:465"
    except Exception as exc:
        errors.append("465: " + _friendly_error(exc))
    try:
        with smtplib.SMTP(SMTP_HOST, 587, timeout=SMTP_TIMEOUT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SENDER_EMAIL, password)
            server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        return "smtp:587"
    except Exception as exc:
        errors.append("587: " + _friendly_error(exc))
    raise SmtpSendError(" | ".join(errors))


def smtp_available() -> tuple[bool, str]:
    """Preveri, ali je SMTP geslo na voljo (brez pošiljanja)."""
    path = smtp_secret_path()
    if path is None:
        return False, "Ni smtp_secret.bin"
    try:
        load_smtp_secret()
    except Exception as exc:
        return False, str(exc)
    return True, str(path)


def smtp_probe() -> tuple[bool, str]:
    """Prijava na Gmail SMTP brez pošiljanja — test pred oddajo."""
    ok, note = smtp_available()
    if not ok:
        return False, note
    password = _clean_password(load_smtp_secret())
    if not password:
        return False, "SMTP geslo je prazno."
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=SMTP_TIMEOUT) as server:
            server.login(SENDER_EMAIL, password)
        return True, "SMTP OK · Gmail 465 · prijava uspela."
    except Exception as exc465:
        try:
            with smtplib.SMTP(SMTP_HOST, 587, timeout=SMTP_TIMEOUT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SENDER_EMAIL, password)
            return True, "SMTP OK · Gmail 587 STARTTLS · prijava uspela."
        except Exception as exc587:
            return False, f"{_friendly_error(exc465)} | {_friendly_error(exc587)}"


__all__ = [
    "SENDER_EMAIL",
    "SmtpSendError",
    "load_smtp_secret",
    "send_smtp",
    "smtp_available",
    "smtp_probe",
    "smtp_secret_path",
]
