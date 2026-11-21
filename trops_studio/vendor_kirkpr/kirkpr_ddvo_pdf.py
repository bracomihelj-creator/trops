"""Izvoz kontrolnega DDV-O v PDF prek uradnega eDavki prikaza.

Shema:  http://edavki.durs.si/Documents/Schemas/DDV_O_11.xsd
Prikaz: https://edavki.durs.si/Documents/Transforms/DDV_O_11.7-display-sl.xslt
        (isti XSLT kot hslsig:DisplayTransformDigest v eDavkih)

Pot: Envelope XML → XSLT → HTML → PDF (Edge/Chrome).
"""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import kirkpr_ddvo_xml as ddvo_xml
import kirkpr_minimax_core as core

ZERO = Decimal("0")
FORM_VERSION = "e-DDV_O_11.7"
XSLT_NAME = "DDV_O_11.7-display-sl.xslt"
DISPLAY_TRANSFORM_URL = (
    "https://edavki.durs.si/Documents/Transforms/DDV_O_11.7-display-sl.xslt"
)
TRANSFORMS_DIR = Path(__file__).with_name("ddvo_transforms")
LOGO_NAME = "durs_znak.png"


def default_ddvo_pdf_name(dataset: core.KirkprDataset, *, firm_slug: str = "") -> str:
    _ = firm_slug
    return ddvo_xml.default_ddvo_pdf_name(dataset)


def _find_browser() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    which_edge = shutil.which("msedge")
    which_chrome = shutil.which("chrome")
    if which_edge:
        candidates.insert(0, Path(which_edge))
    if which_chrome:
        candidates.insert(0, Path(which_chrome))
    return next((p for p in candidates if p.is_file()), None)


def _xslt_path() -> Path:
    path = TRANSFORMS_DIR / XSLT_NAME
    if not path.is_file():
        raise core.KirkprError(
            f"Manjka uradni eDavki XSLT prikaz:\n{path}\n"
            f"Pričakovano: {DISPLAY_TRANSFORM_URL}"
        )
    return path


def _logo_data_uri() -> str:
    logo = TRANSFORMS_DIR / LOGO_NAME
    if not logo.is_file():
        return ""
    raw = logo.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _print_css() -> str:
    logo = _logo_data_uri()
    logo_css = (
        f"background-image: url('{logo}') !important; "
        "background-position: top right !important; "
        "background-repeat: no-repeat !important; "
        "background-size: 140px auto !important;"
        if logo
        else ""
    )
    return f"""
<style type="text/css">
html, body {{ background: #ffffff !important; color: #000 !important; }}
body.sign {{
  background: #ffffff !important;
  font-family: Arial, Helvetica, Verdana, sans-serif !important;
  font-size: 9pt !important;
  margin: 0 !important;
  padding: 8px 12px !important;
}}
div.document {{ background: #ffffff !important; }}
div.commonheader {{
  display: block !important;
  padding: 0.5em 0.8em 0.2em 0.2em !important;
  min-height: 52px !important;
  {logo_css}
}}
div.commonheader table td {{
  color: #000 !important;
  font-size: 9pt !important;
  padding: 1px 8px 1px 0 !important;
}}
div.signareafile {{
  background: #ffffff !important;
  padding: 2px 0 !important;
  margin: 0 !important;
}}
.signareafile h1 {{
  font-size: 18px !important;
  margin: 6px 0 8px 0 !important;
  font-weight: bold !important;
  color: #1c1c1c !important;
}}
table.tablesignbullet {{
  margin: 0.15em 0 6px 0 !important;
  border: 1px solid #738294 !important;
  background: #fafafa !important;
  width: 100% !important;
}}
table.tablesignbullet td {{
  padding: 0.25em 6px !important;
  border-bottom: 1px solid #f1f1f1 !important;
  vertical-align: middle !important;
  font-size: 8.5pt !important;
}}
table.tablesignbullet tr.first td {{
  background: #b8ccce !important;
  border-bottom: 2px solid #016a73 !important;
  font-weight: bold !important;
}}
table.tablesignbullet tr:nth-child(even) td {{ background-color: #f7f7f7; }}
table.tablesignbullet tr.first:nth-child(even) td {{ background: #b8ccce !important; }}
table.tablesignbullet td.lblmenu {{ background: #f1f1f1 !important; }}
table.tablesignbullet td.input {{ background: #ffffff !important; }}
table.tablesignform {{ border-top: 1px solid #b9d3e1 !important; width: 100% !important; margin-top: 8px !important; }}
.ddvo-kontrolni {{
  font-size: 8pt; color: #333; margin: 0 0 4px 0;
}}
@media print {{
  @page {{ size: A4; margin: 8mm; }}
  html {{ zoom: 0.96; }}
  body.sign {{ padding: 0 !important; }}
}}
</style>
"""


def _si_date(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        y, m, d = text[:10].split("-")
        return f"{d}.{m}.{y}"
    return text


def _enrich_commonheader(
    html: str,
    *,
    contact_name: str = "",
    period_from: str = "",
    period_to: str = "",
) -> str:
    """Dopolni eDavki glavo (brez lažnega podpisa) — kontrolni izpis."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    period = f"{_si_date(period_from)} do {_si_date(period_to)}".strip()
    depositor = (contact_name or "").strip().upper() or "—"
    rows = (
        "<tr><td><b>Sistem:</b></td><td>edavki.durs.si</td></tr>"
        f"<tr><td><b>Kontrolni izpis:</b></td><td>{now}</td></tr>"
        f"<tr><td><b>Obdobje:</b></td><td>{period}</td></tr>"
        f"<tr><td><b>Pripravil:</b></td><td>{depositor}</td></tr>"
        "<tr><td><b>Prikaz:</b></td>"
        f"<td>e-DDV_O_11.7 · {XSLT_NAME}</td></tr>"
    )
    note = (
        '<p class="ddvo-kontrolni">Kontrolni izpis (KirKpr) — prikaz z uradnim '
        f'eDavki XSLT: {DISPLAY_TRANSFORM_URL}</p>'
    )
    replacement = (
        f'<div class="commonheader">\n'
        f'<table cellspacing="0"><tbody>{rows}</tbody></table>\n'
        f"{note}<p>&#160;</p>\n</div>"
    )
    pattern = re.compile(
        r'<div class="commonheader">.*?</div>\s*(?=<div class="signareafile">)',
        re.DOTALL | re.IGNORECASE,
    )
    if pattern.search(html):
        return pattern.sub(replacement + "\n", html, count=1)
    # Če XSLT glave ni, jo vstavi pred obrazec
    marker = '<div class="signareafile">'
    if marker in html:
        return html.replace(marker, replacement + "\n" + marker, 1)
    return replacement + html


def xml_to_display_html(
    xml_bytes: bytes,
    *,
    contact_name: str = "",
    period_from: str = "",
    period_to: str = "",
) -> str:
    """Envelope XML → HTML z uradnim DDV_O_11.7-display-sl.xslt."""
    try:
        from lxml import etree
    except ImportError as exc:
        raise core.KirkprError(
            "Za eDavki prikaz DDV-O je potreben paket lxml."
        ) from exc

    transform = etree.XSLT(etree.parse(str(_xslt_path())))
    result = transform(etree.fromstring(xml_bytes))
    html = str(result)
    html = _enrich_commonheader(
        html,
        contact_name=contact_name,
        period_from=period_from,
        period_to=period_to,
    )
    inject = '<meta charset="utf-8"/>' + _print_css()
    if "</head>" in html:
        html = html.replace("</head>", inject + "</head>", 1)
    elif "<head>" in html:
        html = html.replace("<head>", "<head>" + inject, 1)
    else:
        html = f"<html><head>{inject}</head><body class='sign'>{html}</body></html>"
    return html


def _html_to_pdf_browser(html: str, target: Path) -> Path:
    browser = _find_browser()
    if browser is None:
        raise core.KirkprError(
            "Za PDF v eDavki obliki je potreben Microsoft Edge ali Google Chrome "
            "(headless print-to-pdf)."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ddvo_pdf_") as tmp:
        html_path = Path(tmp) / "ddvo_edavki.html"
        html_path.write_text(html, encoding="utf-8")
        out_pdf = Path(tmp) / "out.pdf"
        cmd = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={out_pdf.resolve()}",
            "--no-pdf-header-footer",
            html_path.resolve().as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0 or not out_pdf.is_file() or out_pdf.stat().st_size < 500:
            detail = (proc.stderr or proc.stdout or "").strip()[:500]
            raise core.KirkprError(
                "Edge/Chrome ni uspel izdelati PDF iz eDavki XSLT prikaza."
                + (f"\n{detail}" if detail else "")
            )
        shutil.copyfile(out_pdf, target)
    return target


def build_ddvo_pdf(
    dataset: core.KirkprDataset,
    target: Path | str,
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
    also_write_html: bool = False,
) -> Path:
    """Shrani PDF z uradnim eDavki XSLT prikazom. Brez reportlab rezerve."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_kwargs = dict(
        company_name=company_name,
        address=address,
        address1=address1,
        city=city,
        post_number=post_number,
        post_name=post_name,
        contact_name=contact_name,
        contact_phone=contact_phone,
        taxpayer_type=taxpayer_type,
    )
    xml_bytes = ddvo_xml.build_ddvo_xml_bytes(dataset, **xml_kwargs)
    html = xml_to_display_html(
        xml_bytes,
        contact_name=contact_name,
        period_from=dataset.period_from,
        period_to=dataset.period_to,
    )
    if also_write_html:
        path.with_suffix(".html").write_text(html, encoding="utf-8")
    return _html_to_pdf_browser(html, path)


def write_ddvo_preview_html(
    dataset: core.KirkprDataset,
    target: Path | str,
    **kwargs: Any,
) -> Path:
    """Shrani HTML prikaz (isti XSLT kot eDavki)."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = ddvo_xml.build_ddvo_xml_bytes(dataset, **kwargs)
    path.write_text(
        xml_to_display_html(
            xml_bytes,
            contact_name=str(kwargs.get("contact_name") or ""),
            period_from=dataset.period_from,
            period_to=dataset.period_to,
        ),
        encoding="utf-8",
    )
    return path
