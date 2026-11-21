"""Predloge e-pošte za DDV + virman (HTML, lokalno shranjevanje)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import kirkpr_minimax_core as core

try:
    import kirkpr_ddvo_virman as ddvo_virman
except ImportError:  # pragma: no cover
    ddvo_virman = None  # type: ignore

TEMPLATES_NAME = "ddvo_email_templates.json"
DEFAULT_TEMPLATE_ID = "ddvo_virman"
_DEFAULT_FROM = "info@quickmb.com"
_DEFAULT_LINE_HEIGHT = "1.35"
_DEFAULT_PARA_SPACING_PX = 4

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _default_from_smtp() -> str:
    if ddvo_virman is not None:
        return str(getattr(ddvo_virman, "DEFAULT_OUTLOOK_FROM", _DEFAULT_FROM) or _DEFAULT_FROM)
    return _DEFAULT_FROM


def templates_path(base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else Path(core.config_path()).parent
    return root / TEMPLATES_NAME


def normalize_email_html(body: str) -> str:
    """Ohrani HTML kot ga uredi uporabnik (kot Transkript/šifrant).

    Ne briši ``</p><br>`` ali ``<br><br>`` — to so namerni razmiki.
    Samo poenoti konce vrstic, odstrani robne prazne in stisni
    zaporedne prazne ``<p></p>`` (sicer se ob shranjevanju napihne belina).
    """
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    if not text:
        return ""
    text = re.sub(
        r"(?:<p(?:\s[^>]*)?>\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*){2,}",
        "<p></p>\n",
        text,
        flags=re.I,
    )
    return text + "\n"


def strip_br_after_paragraph(body: str) -> str:
    """Opcijsko: odstrani <br> takoj za </p> (ročni gumb, ne samodejno)."""
    text = re.sub(r"</p>\s*(?:<br\s*/?>\s*)+", "</p>\n", str(body or ""), flags=re.I)
    return text.strip() + ("\n" if text.strip() else "")


# Transkript / Outlook: razmik prek inline stilov na <p> (Word-prijazno).


def html_body_to_lines(fragment: str) -> list[str]:
    """Splošči HTML v seznam vrstic (ohranjeni strong/span); prazne max 1 zapored.

    - ``<br>`` znotraj odstavka → ena nova vrstica (``<br>\\n`` ne sme dati dveh)
    - ``</p><br>`` ali prazni ``<p></p>`` → namerna prazna vrstica med odstavki
    """
    text = str(fragment or "").strip() or ""
    # Prazni odstavki = namerna belina.
    text = re.sub(
        r"<(?:p|div)(?:\s[^>]*)?>\s*(?:&nbsp;|<br\s*/?>)?\s*</(?:p|div)\s*>",
        "\n\n",
        text,
        flags=re.I,
    )
    # </p><br> = konec odstavka + prazna vrstica (ne samo </p>).
    text = re.sub(
        r"</(?:p|div)\s*>[ \t]*(?:<br\s*/?>[ \t]*\n?)+",
        "\n\n",
        text,
        flags=re.I,
    )
    # <br> znotraj odstavka (+ morebitni whitespace) = ena vrstica.
    text = re.sub(r"<br\s*/?>[ \t]*\n?", "\n", text, flags=re.I)
    # Ne požri namernih \\n\\n (zato [ \\t]* namesto \\s*).
    text = re.sub(r"</(?:p|div)\s*>[ \t]*", "\n", text, flags=re.I)
    text = re.sub(r"<(?:p|div)(?:\s[^>]*)?>[ \t]*", "", text, flags=re.I)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [ln.rstrip() for ln in text.split("\n")]
    while raw_lines and not raw_lines[0].strip():
        raw_lines.pop(0)
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()
    lines: list[str] = []
    blank_run = 0
    for ln in raw_lines:
        if not ln.strip() or ln.strip() == "&nbsp;":
            blank_run += 1
            if blank_run == 1:
                lines.append("")
            continue
        blank_run = 0
        lines.append(ln.strip())
    return lines or ["&nbsp;"]


def _line_height_css(line_height: str) -> str:
    """Word/Outlook: raje odstotek (115%) kot enota 1.15."""
    raw = str(line_height or _DEFAULT_LINE_HEIGHT).strip() or _DEFAULT_LINE_HEIGHT
    try:
        val = float(raw.replace(",", ".").rstrip("%"))
    except ValueError:
        return "135%"
    if val <= 0:
        return "135%"
    if val <= 3.5:  # 1.0 … 2.0 → 100% … 200%
        return f"{int(round(val * 100))}%"
    return f"{int(round(val))}%"


def _px_to_pt(px: int) -> str:
    """px → pt za Word (približno 0.75)."""
    pt = max(0.0, min(36.0, float(px) * 0.75))
    if pt == int(pt):
        return f"{int(pt)}pt"
    return f"{pt:.1f}pt"


def paragraph_style(*, line_height: str = "", para_spacing_px: int | None = None) -> str:
    """Slog za vsebino — brez spodnjega margina (razmik = prazna vrstica / spacer).

    Tako Outlook ostane enak belem polju: Enter = nova vrstica (br),
    Enter+Enter = ena prazna vrstica.
    """
    _ = para_spacing_px  # ohranjeno za kompatibilnost klicateljev
    lh = _line_height_css(line_height or _DEFAULT_LINE_HEIGHT)
    return (
        f"margin:0;padding:0;line-height:{lh};"
        "mso-line-height-rule:exactly;"
        "mso-margin-top-alt:0;mso-margin-bottom-alt:0;"
        "font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#111111;"
    )


def spacer_style(*, para_spacing_px: int = _DEFAULT_PARA_SPACING_PX) -> str:
    """Kompakten razmik — Outlook ob Send sicer napihne prazne <p>."""
    try:
        px = int(para_spacing_px)
    except (TypeError, ValueError):
        px = _DEFAULT_PARA_SPACING_PX
    # Majhna fiksna višina (ne 11+px), sicer Word ob pošiljanju podvoji belino.
    h_pt = max(6, min(12, 6 + max(0, min(4, px // 2))))
    h = f"{h_pt}pt"
    return (
        f"margin:0;padding:0;line-height:{h};font-size:{h};"
        "mso-line-height-rule:exactly;"
        "mso-margin-top-alt:0;mso-margin-bottom-alt:0;"
    )


def collapse_empty_paragraphs_for_outlook(fragment: str) -> str:
    """Prazne <p></p> med odstavki → <br>&nbsp; v prejšnjem <p> (brez ločenega odstavka).

    Outlook Word ob Send doda Space After na vsak prazen <p> → razvlečen e-mail;
    v osnutku je to manj opazno. Združitev v <br> ohrani eno prazno vrstico.
    """
    text = normalize_email_html(fragment)
    if not text.strip():
        return text
    # Več zaporednih praznih → ena.
    text = re.sub(
        r"(?:<p(?:\s[^>]*)?>\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*){2,}",
        "<p></p>\n",
        text,
        flags=re.I,
    )

    def _merge(match: re.Match[str]) -> str:
        before = match.group(1)
        # Če se predhodni odstavek že konča z <br>, ne dodajaj še enega.
        if re.search(r"<br\s*/?>\s*$", before, flags=re.I):
            return f"<p>{before}<br>\n&nbsp;</p>\n"
        return f"<p>{before}<br>\n&nbsp;</p>\n"

    # </p> + prazen <p> + naslednji <p> → vstavi br v prvi odstavek.
    text = re.sub(
        r"<p(?:\s[^>]*)?>(.*?)</p>\s*<p(?:\s[^>]*)?>\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*(?=<p\b)",
        _merge,
        text,
        flags=re.I | re.S,
    )
    # Preostali osamljeni prazni <p> na koncu / med → en tanek spacer.
    return text


def apply_spacing_to_html(
    fragment: str,
    *,
    line_height: str = _DEFAULT_LINE_HEIGHT,
    para_spacing_px: int = _DEFAULT_PARA_SPACING_PX,
) -> str:
    """Prepiši telo: zaporedne vrstice → en <p> z <br>; prazna = <br>&nbsp; (ne ločen <p>)."""
    lines = html_body_to_lines(fragment)
    style = paragraph_style(line_height=line_height, para_spacing_px=para_spacing_px)
    parts: list[str] = []
    run: list[str] = []

    def _flush(*, trailing_blank: bool = False) -> None:
        nonlocal run
        if not run:
            return
        body = "<br>\n".join(run)
        if trailing_blank:
            body = f"{body}<br>\n&nbsp;"
        parts.append(f'<p style="{style}">{body}</p>')
        run = []

    pending_blank = False
    for ln in lines:
        if not ln.strip():
            if run:
                pending_blank = True
                _flush(trailing_blank=True)
                pending_blank = False
            continue
        if pending_blank and not run:
            pending_blank = False
        run.append(ln)
    _flush(trailing_blank=False)
    return "\n".join(parts) + ("\n" if parts else "")


def prepare_outlook_fragment(
    fragment: str,
    *,
    line_height: str = _DEFAULT_LINE_HEIGHT,
    para_spacing_px: int = _DEFAULT_PARA_SPACING_PX,
) -> str:
    """Word/Outlook: <p style=\"margin + line-height\"> kot Transkript (ne surovi <br>)."""
    return apply_spacing_to_html(
        fragment,
        line_height=line_height,
        para_spacing_px=para_spacing_px,
    )


def wrap_outlook_html(
    fragment: str,
    *,
    line_height: str = _DEFAULT_LINE_HEIGHT,
    para_spacing_px: int = _DEFAULT_PARA_SPACING_PX,
    reformat: bool = True,
) -> str:
    """Cel HTML za Outlook — enak belmu polju (brez dodatnih marginov na vsak <p>).

    reformat=True  → splošči in znova sestavi odstavke (stari način)
    reformat=False → ohrani HTML iz belga urejevalnika (barve, krepko, <br>)
    """
    if reformat:
        frag = prepare_outlook_fragment(
            fragment,
            line_height=line_height,
            para_spacing_px=para_spacing_px,
        ).strip()
    else:
        frag = stamp_paragraph_styles(
            fragment,
            line_height=line_height,
            para_spacing_px=para_spacing_px,
        ).strip()
    frag = frag or f'<p style="{paragraph_style()}">&nbsp;</p>'
    low = frag.casefold()
    if low.startswith("<!doctype") or low.startswith("<html"):
        return frag
    lh = _line_height_css(line_height)
    return (
        "<!DOCTYPE html>\n"
        "<html xmlns:o='urn:schemas-microsoft-com:office:office' "
        "xmlns:w='urn:schemas-microsoft-com:office:word'>\n"
        "<head>\n"
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n'
        "<!--[if mso]>\n"
        "<style type=\"text/css\">\n"
        f"p {{ margin:0 !important; padding:0 !important; line-height:{lh} !important; "
        "mso-line-height-rule:exactly; mso-margin-top-alt:0; mso-margin-bottom-alt:0; "
        "mso-para-margin:0; }}\n"
        "strong, b { font-weight:bold !important; }\n"
        "span { mso-style-textfill-fill-color: inherit; }\n"
        "</style>\n"
        "<![endif]-->\n"
        "<style>\n"
        f"body {{ background:#ffffff; margin:0; padding:12px; line-height:{lh}; "
        "font-family:Calibri,Arial,sans-serif; font-size:11pt; color:#111111; }}\n"
        f"p {{ margin:0 0 0 0 !important; padding:0 !important; line-height:{lh}; "
        "font-family:Calibri,Arial,sans-serif; font-size:11pt; color:#111111; }}\n"
        "strong, b { font-weight:bold; }\n"
        "</style>\n"
        "</head>\n"
        '<body style="margin:0;padding:12px;font-family:Calibri,Arial,sans-serif;'
        'font-size:11pt;color:#111111;">\n'
        f"{frag}\n"
        "</body>\n"
        "</html>"
    )


def stamp_paragraph_styles(
    fragment: str,
    *,
    line_height: str = _DEFAULT_LINE_HEIGHT,
    para_spacing_px: int = _DEFAULT_PARA_SPACING_PX,
) -> str:
    """Nastavi margin/line-height na <p>; prazne odstavke združi (Outlook Send)."""
    text = collapse_empty_paragraphs_for_outlook(fragment)
    if not text.strip():
        return text
    style = paragraph_style(line_height=line_height, para_spacing_px=para_spacing_px)
    spacer = spacer_style(para_spacing_px=para_spacing_px)

    def _repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not inner.strip() or inner.strip().casefold() in {"&nbsp;", "<br>", "<br/>", "<br />"}:
            # Preostali prazni: tanek spacer (ne ločen velik odstavek).
            return f'<p style="{spacer}">&nbsp;</p>'
        return f'<p style="{style}">{inner}</p>'

    if re.search(r"<p\b", text, flags=re.I):
        stamped = re.sub(r"<p(?:\s[^>]*)?>(.*?)</p>", _repl, text, flags=re.I | re.S)
        stamped = re.sub(
            r"(?:<p style=\"[^\"]*\">\s*&nbsp;\s*</p>\s*){2,}",
            f'<p style="{spacer}">&nbsp;</p>\n',
            stamped,
            flags=re.I,
        )
        return stamped
    return apply_spacing_to_html(text, line_height=line_height, para_spacing_px=para_spacing_px)


def _default_body_html() -> str:
    """Daljši delovni vzorec (kot shranjena predloga »DDV + virman«)."""
    return (
        "<p>Spoštovani/a, <strong>{odgovorna_oseba}, ({firma})</strong>.</p>\n"
        "<p></p>\n"
        "<p><strong>DDV za obdobje ({obdobje})</strong><br>\n"
        '<span style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
        '<span style="color:#1565C0">Obračun DDV-O je oddan na E-davke.</span></span></p>\n'
        "<p></p>\n"
        '<p><strong><span style="color:#C62828">Znesek za plačilo: {placilo} EUR</span></strong></p>\n'
        "<p></p>\n"
        '<p><span style="color:#1565C0">V prilogi sta obračun DDV-O (PDF) '
        "in plačilni nalog (virman.xml).</span><br>\n"
        "Referenca: {referenca}<br>\n"
        "IBAN prejemnika: {iban}<br>\n"
        "Datum izvršitve: {datum}</p>\n"
        "{qr_block}\n"
        "{ps_block}\n"
        "<p></p>\n"
        "<p>Lep pozdrav,</p>\n"
        "<p></p>\n"
        "<p><strong>Braco MIHELJ</strong><br>\n"
        "tel.: 041.653.170</p>\n"
        "<p></p>\n"
        "<p><strong>eMail:</strong><br>\n"
        "braco.mihelj@gmail.com<br>\n"
        "bracom@windowslive.com<br>\n"
        "info@quickmb.com</p>\n"
    )


def _coerce_para_spacing(value: Any) -> int:
    try:
        px = int(value)
    except (TypeError, ValueError):
        px = _DEFAULT_PARA_SPACING_PX
    return max(0, min(48, px))


def _row_from_raw(tid: str, row: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Enoten vzorec: ime, Od, zadeva, besedilo, razmiki, potrdila."""
    data = dict(row or {})
    return {
        "id": tid,
        "title": str(data.get("title") or tid).strip() or tid,
        "from_smtp": str(data.get("from_smtp") or _default_from_smtp()).strip() or _default_from_smtp(),
        "subject": str(data.get("subject") or "").strip(),
        "body": normalize_email_html(str(data.get("body") or "")),
        "line_height": str(data.get("line_height") or _DEFAULT_LINE_HEIGHT).strip() or _DEFAULT_LINE_HEIGHT,
        "para_spacing_px": _coerce_para_spacing(data.get("para_spacing_px")),
        "read_receipt": bool(data["read_receipt"]) if "read_receipt" in data else True,
        "delivery_receipt": bool(data["delivery_receipt"]) if "delivery_receipt" in data else True,
        "defer_send": bool(data["defer_send"]) if "defer_send" in data else False,
        "builtin": bool(data.get("builtin")) and tid == DEFAULT_TEMPLATE_ID,
    }


def template_body_preview(row: Mapping[str, Any], *, max_len: int = 70) -> str:
    """Prva vrstica vzorca (z {placeholders}, brez HTML) — za razlikovanje ob izboru."""
    lines = html_body_to_lines(str(row.get("body") or ""))
    for ln in lines:
        plain = re.sub(r"<[^>]+>", "", ln)
        plain = plain.replace("&nbsp;", " ").strip()
        if plain:
            return plain if len(plain) <= max_len else plain[: max_len - 1] + "…"
    return "—"


def template_summary_line(row: Mapping[str, Any]) -> str:
    """Kratka vrstica za seznam: Od · zadeva · začetek besedila."""
    from_smtp = str(row.get("from_smtp") or "—").strip() or "—"
    subject = str(row.get("subject") or "—").strip() or "—"
    if len(subject) > 36:
        subject = subject[:33] + "…"
    preview = template_body_preview(row, max_len=48)
    px = _coerce_para_spacing(row.get("para_spacing_px"))
    return f"Od: {from_smtp}  ·  Zadeva: {subject}  ·  «{preview}»  ·  odst.{px}px"


def default_templates() -> dict[str, dict[str, Any]]:
    return {
        DEFAULT_TEMPLATE_ID: _row_from_raw(
            DEFAULT_TEMPLATE_ID,
            {
                "title": "DDV + virman",
                "from_smtp": _default_from_smtp(),
                "subject": "DDV za obdobje ({obdobje}) — {nagovor}",
                "body": _default_body_html(),
                "line_height": "1.0",
                "para_spacing_px": _DEFAULT_PARA_SPACING_PX,
                "builtin": True,
            },
        )
    }


def load_templates(base_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    path = templates_path(base_dir)
    merged = default_templates()
    if not path.is_file():
        return merged
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return merged
    rows = raw.get("templates") if isinstance(raw, dict) else raw
    if not isinstance(rows, dict):
        return merged
    defaults = default_templates()
    for key, row in rows.items():
        if not isinstance(row, dict):
            continue
        tid = str(row.get("id") or key).strip() or str(key)
        body = normalize_email_html(str(row.get("body") or ""))
        subject = str(row.get("subject") or "").strip()
        if not body.strip():
            body = _default_body_html() if tid == DEFAULT_TEMPLATE_ID else ""
        if tid == DEFAULT_TEMPLATE_ID:
            dflt = defaults[DEFAULT_TEMPLATE_ID]
            if "{" not in body:
                body = str(dflt.get("body") or _default_body_html())
            if "{" not in subject:
                subject = str(dflt.get("subject") or "")
        merged[tid] = _row_from_raw(
            tid,
            {
                **row,
                "subject": subject,
                "body": body,
                "builtin": bool(row.get("builtin")) and tid == DEFAULT_TEMPLATE_ID,
            },
        )
    return merged


def save_all_templates(
    templates: dict[str, dict[str, Any]],
    base_dir: Path | None = None,
    *,
    active_template_id: str | None = None,
) -> Path:
    path = templates_path(base_dir)
    raw: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, json.JSONDecodeError):
            raw = {}
    active = active_template_id
    if active is None:
        active = str(raw.get("active_template_id") or DEFAULT_TEMPLATE_ID).strip()
    if active not in templates:
        active = DEFAULT_TEMPLATE_ID if DEFAULT_TEMPLATE_ID in templates else next(iter(templates), DEFAULT_TEMPLATE_ID)
    payload = {
        "active_template_id": active,
        "templates": {
            tid: _row_from_raw(tid, row)
            for tid, row in templates.items()
            if isinstance(row, dict)
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def get_active_template_id(base_dir: Path | None = None) -> str:
    path = templates_path(base_dir)
    templates = load_templates(base_dir)
    tid = DEFAULT_TEMPLATE_ID
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                tid = str(raw.get("active_template_id") or DEFAULT_TEMPLATE_ID).strip() or DEFAULT_TEMPLATE_ID
        except (OSError, json.JSONDecodeError):
            tid = DEFAULT_TEMPLATE_ID
    return tid if tid in templates else DEFAULT_TEMPLATE_ID


def set_active_template_id(template_id: str, base_dir: Path | None = None) -> str:
    templates = load_templates(base_dir)
    tid = str(template_id or DEFAULT_TEMPLATE_ID).strip() or DEFAULT_TEMPLATE_ID
    if tid not in templates:
        tid = DEFAULT_TEMPLATE_ID
    save_all_templates(templates, base_dir, active_template_id=tid)
    return tid


def resolve_template_id(*candidates: str, base_dir: Path | None = None) -> str:
    """Prvi obstoječi id med kandidati, sicer active, sicer privzeti."""
    templates = load_templates(base_dir)
    for cand in candidates:
        tid = str(cand or "").strip()
        if tid and tid in templates:
            return tid
    active = get_active_template_id(base_dir)
    if active in templates:
        return active
    return DEFAULT_TEMPLATE_ID if DEFAULT_TEMPLATE_ID in templates else next(iter(templates), DEFAULT_TEMPLATE_ID)


def get_template(template_id: str = "", base_dir: Path | None = None) -> dict[str, Any]:
    import kirkpr_upn_qr as upn_qr

    templates = load_templates(base_dir)
    tid = resolve_template_id(template_id, base_dir=base_dir) if template_id else get_active_template_id(base_dir)
    if tid not in templates:
        tid = DEFAULT_TEMPLATE_ID
    row = _row_from_raw(tid, templates.get(tid) or templates[DEFAULT_TEMPLATE_ID])
    row["body"] = upn_qr.ensure_qr_placeholder(str(row.get("body") or ""))
    return row


def ensure_qr_placeholder(body: str) -> str:
    import kirkpr_upn_qr as upn_qr

    return upn_qr.ensure_qr_placeholder(body)


def list_templates(base_dir: Path | None = None) -> list[dict[str, Any]]:
    rows = list(load_templates(base_dir).values())
    rows.sort(key=lambda r: (0 if r.get("id") == DEFAULT_TEMPLATE_ID else 1, str(r.get("title") or "").casefold()))
    return rows


def save_template(
    template_id: str,
    *,
    title: str,
    subject: str,
    body: str,
    from_smtp: str = "",
    line_height: str = "",
    para_spacing_px: int | None = None,
    read_receipt: bool | None = None,
    delivery_receipt: bool | None = None,
    defer_send: bool | None = None,
    base_dir: Path | None = None,
) -> str:
    tid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(template_id or "").strip()) or "ddvo_custom"
    templates = load_templates(base_dir)
    prev = templates.get(tid) or {}
    wanted_body = normalize_email_html(body)
    wanted_subject = str(subject or "").strip()
    templates[tid] = _row_from_raw(
        tid,
        {
            "title": title,
            "subject": wanted_subject,
            "body": wanted_body,
            "from_smtp": from_smtp or prev.get("from_smtp") or _default_from_smtp(),
            "line_height": line_height or prev.get("line_height") or _DEFAULT_LINE_HEIGHT,
            "para_spacing_px": (
                para_spacing_px
                if para_spacing_px is not None
                else prev.get("para_spacing_px", _DEFAULT_PARA_SPACING_PX)
            ),
            "read_receipt": (
                bool(prev.get("read_receipt", True)) if read_receipt is None else bool(read_receipt)
            ),
            "delivery_receipt": (
                bool(prev.get("delivery_receipt", True))
                if delivery_receipt is None
                else bool(delivery_receipt)
            ),
            "defer_send": (
                bool(prev.get("defer_send", False)) if defer_send is None else bool(defer_send)
            ),
            "builtin": tid == DEFAULT_TEMPLATE_ID,
        },
    )
    path = save_all_templates(templates, base_dir, active_template_id=tid)
    # Preveri zapis (brez tega se napaka »shrani« zlaže).
    check = get_template(tid, base_dir=base_dir)
    got_body = normalize_email_html(str(check.get("body") or ""))
    got_subject = str(check.get("subject") or "").strip()
    if got_body != wanted_body or got_subject != wanted_subject:
        raise OSError(
            f"Predloga ni ostala na disku ({path}). "
            f"Pričakovano {len(wanted_body)} znakov, prebrano {len(got_body)}."
        )
    return tid


def add_template(
    *,
    title: str,
    subject: str,
    body: str,
    code: str = "",
    from_smtp: str = "",
    line_height: str = "",
    para_spacing_px: int | None = None,
    base_dir: Path | None = None,
) -> str:
    tid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(code or title or "ddvo_custom").strip())
    if not tid:
        tid = "ddvo_custom"
    templates = load_templates(base_dir)
    if tid in templates:
        n = 2
        while f"{tid}_{n}" in templates:
            n += 1
        tid = f"{tid}_{n}"
    return save_template(
        tid,
        title=title,
        subject=subject,
        body=body,
        from_smtp=from_smtp,
        line_height=line_height,
        para_spacing_px=para_spacing_px,
        base_dir=base_dir,
    )


def rename_template(
    template_id: str,
    new_title: str,
    *,
    base_dir: Path | None = None,
) -> str:
    """Spremeni samo prikazno ime (naslov) predloge. Vrne id."""
    tid = str(template_id or "").strip() or DEFAULT_TEMPLATE_ID
    title = str(new_title or "").strip()
    if not title:
        raise ValueError("Ime predloge ne sme biti prazno.")
    templates = load_templates(base_dir)
    row = templates.get(tid)
    if not row:
        raise ValueError(f"Predloga «{tid}» ne obstaja.")
    return save_template(
        tid,
        title=title,
        subject=str(row.get("subject") or ""),
        body=str(row.get("body") or ""),
        from_smtp=str(row.get("from_smtp") or ""),
        line_height=str(row.get("line_height") or ""),
        para_spacing_px=_coerce_para_spacing(row.get("para_spacing_px")),
        base_dir=base_dir,
    )


def copy_template(
    template_id: str,
    *,
    new_title: str = "",
    subject: str | None = None,
    body: str | None = None,
    from_smtp: str | None = None,
    line_height: str | None = None,
    para_spacing_px: int | None = None,
    base_dir: Path | None = None,
) -> str:
    """Kopija predloge kot nova. Vrne id kopije."""
    src = get_template(template_id, base_dir=base_dir)
    base_title = (new_title or "").strip() or f"{src.get('title') or src['id']} (kopija)"
    return add_template(
        title=base_title,
        subject=str(src.get("subject") or "") if subject is None else str(subject),
        body=str(src.get("body") or "") if body is None else str(body),
        code=base_title,
        from_smtp=str(src.get("from_smtp") or "") if from_smtp is None else str(from_smtp),
        line_height=str(src.get("line_height") or "") if line_height is None else str(line_height),
        para_spacing_px=(
            _coerce_para_spacing(src.get("para_spacing_px"))
            if para_spacing_px is None
            else _coerce_para_spacing(para_spacing_px)
        ),
        base_dir=base_dir,
    )


def delete_template(template_id: str, *, base_dir: Path | None = None) -> str:
    """Izbriši uporabniško predlogo. Vgrajeno (privzeto) samo ponastavi. Vrne id, ki naj ostane aktiven."""
    tid = str(template_id or "").strip()
    if not tid:
        raise ValueError("Manjka id predloge.")
    templates = load_templates(base_dir)
    if tid == DEFAULT_TEMPLATE_ID:
        dflt = default_templates()[DEFAULT_TEMPLATE_ID]
        save_template(
            DEFAULT_TEMPLATE_ID,
            title=str(dflt.get("title") or "DDV + virman"),
            subject=str(dflt.get("subject") or ""),
            body=str(dflt.get("body") or ""),
            from_smtp=str(dflt.get("from_smtp") or ""),
            line_height=str(dflt.get("line_height") or ""),
            para_spacing_px=_coerce_para_spacing(dflt.get("para_spacing_px")),
            base_dir=base_dir,
        )
        return DEFAULT_TEMPLATE_ID
    if tid not in templates:
        raise ValueError(f"Predloga «{tid}» ne obstaja.")
    del templates[tid]
    save_all_templates(templates, base_dir, active_template_id=DEFAULT_TEMPLATE_ID)
    return DEFAULT_TEMPLATE_ID


_PREPLACILO_LINE_RE = re.compile(
    r"Obveznost\s+[\d.\s]+,\d{2}\s*EUR\s*[−\-–]\s*[\d.\s]+,\d{2}\s*EUR"
    r"\s*\(preplačilo konta 62\)\s*(?:<br\s*/?>)?\s*",
    re.I,
)


def _preplacilo_is_zero(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    try:
        return core.decimal_value(text) == 0
    except Exception:
        return text in {"0", "0,00", "0.00"}


def strip_zero_preplacilo_line(text: str, *, preplacilo: str = "") -> str:
    """Odstrani vrstico »Obveznost … (preplačilo konta 62)«, če je konto 62 = 0."""
    if not _preplacilo_is_zero(preplacilo):
        return str(text or "")
    return _PREPLACILO_LINE_RE.sub("", str(text or ""))


def render_placeholders(text: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(values.get(key, match.group(0)))

    out = _PLACEHOLDER_RE.sub(repl, str(text or ""))
    return strip_zero_preplacilo_line(out, preplacilo=str(values.get("preplacilo") or ""))


def restore_placeholders(text: str, values: Mapping[str, str] | None) -> str:
    """Obratno od render: zneske/firmo → {placeholders}, ohrani oblikovanje (barve…)."""
    out = str(text or "")
    if not values:
        return out
    items = [
        (str(k), str(v))
        for k, v in values.items()
        if not str(k).startswith("_") and str(v or "").strip()
    ]
    # Daljše vrednosti najprej (npr. cel ps_block pred kratkim nagovorom).
    items.sort(key=lambda kv: len(kv[1]), reverse=True)
    for key, val in items:
        placeholder = f"{{{key}}}"
        if placeholder in out:
            continue
        if val in out:
            out = out.replace(val, placeholder)
    return out


def plain_to_html(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return "<p></p>"
    if any(tag in raw.casefold() for tag in ("<p", "<div", "<br", "<strong", "<span")):
        return raw
    parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if not parts:
        parts = [raw]
    blocks: list[str] = []
    for part in parts:
        blocks.append("<p>" + part.replace("\n", "<br>\n") + "</p>")
    return "\n".join(blocks)


def build_placeholder_values(
    *,
    company_name: str,
    period_label: str,
    obligation: str,
    preplacilo: str,
    placilo: str,
    reference: str = "",
    iban: str = "",
    datum: str = "",
    postscript: str = "",
    odgovorna_oseba: str = "",
    payment_amount: Any = None,
    payer_name: str = "",
    payer_street: str = "",
    payer_city: str = "",
) -> dict[str, str]:
    from decimal import Decimal

    import kirkpr_upn_qr as upn_qr

    nagovor = str(company_name or "").strip().split()[0].rstrip(".,") if company_name else ""
    odg = str(odgovorna_oseba or "").strip()
    ps = str(postscript or "").strip()
    ps_block = ""
    if ps:
        ps_html = plain_to_html(ps).replace("<p>", '<p style="color:#C62828">')
        ps_block = f"<p><strong>p.s.:</strong></p>\n{ps_html}\n"

    qr_block = ""
    qr_png = ""
    try:
        amount = Decimal(str(payment_amount if payment_amount is not None else "0"))
    except Exception:
        amount = Decimal("0")
    if amount > 0 and ddvo_virman is not None:
        try:
            purpose = f"Placilo DDV {period_label}".strip()[:42]
            png_path = upn_qr.write_temp_upn_qr_png(
                amount=amount,
                payer_name=payer_name or company_name,
                payer_address=payer_street,
                payer_city=payer_city,
                recipient_name=ddvo_virman.FURS_CREDITOR_NAME,
                recipient_address=ddvo_virman.FURS_CREDITOR_ADDR1,
                recipient_city=ddvo_virman.FURS_CREDITOR_ADDR2,
                recipient_iban=iban or ddvo_virman.FURS_CREDITOR_IBAN,
                reference=reference,
                purpose_code=ddvo_virman.FURS_PURPOSE_CODE,
                purpose=purpose,
                payment_date=str(datum or "").strip(),
            )
            qr_png = str(png_path)
            qr_block = upn_qr.UPN_QR_MARKER
        except Exception:
            qr_block = ""
            qr_png = ""

    return {
        "nagovor": nagovor or str(company_name or "").strip(),
        "firma": str(company_name or "").strip(),
        "odgovorna_oseba": odg,
        "obdobje": str(period_label or "").strip(),
        "obveznost": str(obligation or "").strip(),
        "preplacilo": str(preplacilo or "").strip(),
        "placilo": str(placilo or "").strip(),
        "referenca": str(reference or "").strip(),
        "iban": str(iban or "").strip(),
        "datum": str(datum or "").strip(),
        "qr_block": qr_block,
        "ps_block": ps_block,
        "ps": ps,
        "_qr_png": qr_png,
    }


__all__ = [
    "DEFAULT_TEMPLATE_ID",
    "add_template",
    "build_placeholder_values",
    "collapse_empty_paragraphs_for_outlook",
    "copy_template",
    "default_templates",
    "delete_template",
    "ensure_qr_placeholder",
    "get_active_template_id",
    "get_template",
    "list_templates",
    "load_templates",
    "normalize_email_html",
    "plain_to_html",
    "html_body_to_lines",
    "apply_spacing_to_html",
    "paragraph_style",
    "prepare_outlook_fragment",
    "rename_template",
    "render_placeholders",
    "resolve_template_id",
    "restore_placeholders",
    "save_template",
    "set_active_template_id",
    "stamp_paragraph_styles",
    "strip_br_after_paragraph",
    "strip_zero_preplacilo_line",
    "template_body_preview",
    "template_summary_line",
    "templates_path",
    "wrap_outlook_html",
]
