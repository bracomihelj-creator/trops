"""Samodejno branje preplačila DDV (konto 62) z eDavkov eKartice."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import kirkpr_minimax_core as core

ZERO = Decimal("0.00")
MINIMAX_TRIGGER = "https://moj.minimax.si/SI/VA/WebUI/Zacetek/Zacetek.aspx"
EKARTICA_URL = (
    "https://edavki.durs.si/EdavkiPortal/PersonalPortal/CommonPages/Documents/EKarticaV2.aspx"
)
DEPUTY_LIST_URL = (
    "https://edavki.durs.si/EdavkiPortal/PersonalPortal/Pages/Logout/DeputyList.aspx"
)
# Sprožilec za branje konta 62: eKartica (NE Minimax prijava).
KONTO62_TRIGGER = EKARTICA_URL


@dataclass(frozen=True)
class Konto62Lookup:
    credit: Decimal
    source: str
    raw_saldo: str = ""
    detail: str = ""


def _konto62_webapps() -> tuple[Path, ...]:
    from trops_studio.config import KONTO62_WEBAPP_CANDIDATES

    return tuple(KONTO62_WEBAPP_CANDIDATES)


def _downloads_dirs() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "Downloads",
        home / "Prenosi",
        *_konto62_webapps(),
    ]
    return [p for p in candidates if p.is_dir()]


def lookup_from_text(text: str, *, tax_number: str = "") -> Konto62Lookup | None:
    credit = core.parse_edavki_konto62_from_text(text)
    if credit is None:
        return None
    tax = re.sub(r"\D", "", tax_number or "")
    if tax and tax not in re.sub(r"\D", "", text) and "62" in text:
        # Če je v besedilu druga davčna, vseeno sprejmi vrstico 62 (stran je za aktivnega zavezanca).
        pass
    return Konto62Lookup(credit=credit, source="besedilo", detail="parse eKartica / JSON")


def lookup_from_clipboard(clipboard_text: str, *, tax_number: str = "") -> Konto62Lookup | None:
    found = lookup_from_text(clipboard_text, tax_number=tax_number)
    if found is None:
        return None
    return Konto62Lookup(credit=found.credit, source="odložišče", detail=found.detail)


def lookup_from_recent_captures(
    *,
    tax_number: str = "",
    max_files: int = 60,
    max_age_days: int = 14,
) -> Konto62Lookup | None:
    tax = re.sub(r"\D", "", tax_number or "")
    cutoff = time.time() - max_age_days * 86400
    files: list[Path] = []
    for folder in _downloads_dirs():
        for path in folder.glob("*.json"):
            try:
                if path.stat().st_mtime >= cutoff:
                    files.append(path)
            except OSError:
                continue
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:max_files]:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if tax and tax not in re.sub(r"\D", "", text) and "FURS_EDAVKI" not in text and "eKartica" not in text:
            continue
        if "62" not in text:
            continue
        found = lookup_from_text(text, tax_number=tax)
        if found is not None and found.credit > ZERO:
            return Konto62Lookup(
                credit=found.credit,
                source="zajem JSON",
                detail=path.name,
            )
    return None


def lookup_from_saved(config_value: Any) -> Konto62Lookup | None:
    try:
        credit = core.edavki_konto62_credit(config_value)
    except core.KirkprError:
        return None
    if credit <= ZERO:
        return None
    return Konto62Lookup(credit=credit, source="shranjeno", detail="zadnja potrditev za firmo")


class _Konto62Handler(BaseHTTPRequestHandler):
    result_box: dict[str, Any]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        self.result_box["payload"] = payload
        self.result_box["event"].set()
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _open_in_chrome(url: str, *, incognito: bool = True, background: bool = True) -> None:
    """Odpre URL v Chromu — privzeto incognito + v ozadju (brez kraje fokusa)."""
    chrome_candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for browser in chrome_candidates:
        if not browser.is_file():
            continue
        is_chrome = "chrome" in browser.name.casefold()
        is_edge = "msedge" in browser.name.casefold()
        args = [str(browser)]
        if is_chrome or is_edge:
            if incognito:
                args.append("--incognito")
            args.append("--new-window")
        else:
            args.append("--new-tab")
        args.append(url)
        try:
            kwargs: dict[str, Any] = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if background and hasattr(subprocess, "STARTUPINFO"):
                # Windows: odpri minimizirano, brez aktivacije (ostani na KIR/KPR formi).
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
                kwargs["startupinfo"] = si
            subprocess.Popen(args, **kwargs)
            return
        except OSError:
            continue
    webbrowser.open(url)


def lookup_from_chrome_extension(
    *,
    tax_number: str = "",
    company_name: str = "",
    timeout_sec: float = 28.0,
) -> Konto62Lookup | None:
    """Sproži Chrome razširitev: odpre eKartico / zamenja zavezanca / prebere 62."""
    result_box: dict[str, Any] = {"payload": None, "event": threading.Event()}

    class Handler(_Konto62Handler):
        pass

    Handler.result_box = result_box
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report_url = f"http://127.0.0.1:{port}/k62"
    query = urlencode(
        {
            "kirkpr_edavki_k62": report_url,
            "kirkpr_tax": re.sub(r"\D", "", tax_number or ""),
            "kirkpr_firm": str(company_name or "").strip()[:120],
        }
    )
    try:
        _open_in_chrome(f"{KONTO62_TRIGGER}?{query}")
        if not result_box["event"].wait(timeout_sec):
            return None
        payload = result_box.get("payload") or {}
        # ok:false z credit 0 / prazno → obravnavaj kot 0 EUR (ni preplačila).
        if payload.get("ok") is False and payload.get("credit") in (None, "", "0", "0.00", "0,00"):
            return Konto62Lookup(credit=ZERO, source="eDavki eKartica", raw_saldo="0,00", detail="ni preplačila")
        if not payload.get("ok") and payload.get("credit") in (None, ""):
            # Če je konto 62 nič / ni najden, prepiši 0.
            err = str(payload.get("error") or "")
            if "ni najden" in err.casefold() or "62" in err:
                return Konto62Lookup(credit=ZERO, source="eDavki eKartica", raw_saldo="0,00", detail=err[:120])
            return None
        credit_raw = payload.get("credit")
        if credit_raw in (None, ""):
            return Konto62Lookup(credit=ZERO, source="eDavki eKartica", raw_saldo="0,00", detail="prazno → 0")
        credit = core.edavki_konto62_credit(credit_raw)
        # 0,00 je veljavno (ni preplačila) — ne obravnavaj kot napako.
        detail = "Chrome: eKartica"
        if payload.get("taxNumber"):
            detail += f" · DS {payload.get('taxNumber')}"
        return Konto62Lookup(
            credit=credit,
            source="eDavki eKartica",
            raw_saldo=str(payload.get("saldo") or format(credit, ".2f")),
            detail=detail,
        )
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass


def resolve_edavki_konto62(
    *,
    tax_number: str = "",
    company_name: str = "",
    clipboard_text: str = "",
    saved_value: Any = None,
    use_chrome: bool = False,
    chrome_timeout_sec: float = 28.0,
) -> Konto62Lookup | None:
    """Vrstni red: odložišče → JSON zajem → (izbirno) eKartica → shranjeno.

    Privzeto NE odpira brskalnika (virman iz lokalnih podatkov). Chrome/eKartica
    samo ob izrecnem »Preberi z eDavkov«. Če ni podatka, vrne None → UI prepiše 0.
    """
    if clipboard_text:
        found = lookup_from_clipboard(clipboard_text, tax_number=tax_number)
        if found is not None:
            return found
    found = lookup_from_recent_captures(tax_number=tax_number)
    if found is not None:
        return found
    if use_chrome:
        found = lookup_from_chrome_extension(
            tax_number=tax_number,
            company_name=company_name,
            timeout_sec=chrome_timeout_sec,
        )
        if found is not None:
            return found
    found = lookup_from_saved(saved_value)
    if found is not None:
        return found
    return None


def open_ekartica_tab(*, tax_number: str = "", company_name: str = "") -> None:
    """Odpre Zamenjavo zavezanca (če je DS) ali eKartico — preklop naredi razširitev."""
    _ = company_name
    tax = re.sub(r"\D", "", tax_number or "")
    _open_in_chrome(DEPUTY_LIST_URL if tax else EKARTICA_URL)


__all__ = [
    "Konto62Lookup",
    "EKARTICA_URL",
    "lookup_from_clipboard",
    "lookup_from_recent_captures",
    "lookup_from_chrome_extension",
    "open_ekartica_tab",
    "resolve_edavki_konto62",
]
