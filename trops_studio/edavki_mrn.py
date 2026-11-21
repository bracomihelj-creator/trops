"""Spletno branje MRN (carinske deklaracije) z eDavkov — kot konto 62 prek Chrome razširitve.

MRN = samo BLAGO (carina) → konti 16030/26046 in DDV-O polje 26.
Storitve (OpenAI/Fiverr) in druga SA (npr. Foshan) NISO MRN.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import threading
import webbrowser
from dataclasses import dataclass, field
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from trops_studio.edavki_links import (
    EDAVKI_MRN_DECLARATIONS_URL,
    PROJEST_NAME,
    PROJEST_TAX_ID,
)
from trops_studio.money import decimal_value, money_text, normalize_text
from trops_studio.vat_accounts import extract_mrn_codes

ZERO = Decimal("0.00")
MRN_TRIGGER = EDAVKI_MRN_DECLARATIONS_URL


@dataclass
class MrnRow:
    mrn: str
    vat: Decimal
    tip: str = ""
    verzija: str = ""
    kontrola: str = ""
    datum_priprave: str = ""
    datum_sprejema: str = ""
    datum_sprostitve: str = ""
    vat_text: str = ""
    opombe: str = ""


@dataclass
class MrnLookup:
    ok: bool
    rows: list[MrnRow] = field(default_factory=list)
    all_rows: list[MrnRow] = field(default_factory=list)
    total_vat: Decimal = ZERO
    source: str = ""
    detail: str = ""
    date_from: str = ""
    date_to: str = ""
    tax_number: str = ""
    error: str = ""
    empty: bool = False

    @property
    def codes(self) -> list[str]:
        return [r.mrn for r in self.rows]

    def codes_text(self) -> str:
        return ", ".join(self.codes) if self.codes else "—"


class _MrnHandler(BaseHTTPRequestHandler):
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

    def do_GET(self) -> None:
        body = (
            b"<!doctype html><meta charset=utf-8><title>MRN</title>"
            b"<p>eDavki MRN</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _open_in_chrome(url: str, *, background: bool = True) -> None:
    chrome_candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for browser in chrome_candidates:
        if not browser.is_file():
            continue
        args = [str(browser), "--new-tab", url]
        try:
            kwargs: dict[str, Any] = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            }
            if background and hasattr(subprocess, "STARTUPINFO"):
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 7
                kwargs["startupinfo"] = si
            subprocess.Popen(args, **kwargs)
            return
        except OSError:
            continue
    webbrowser.open(url)


def _parse_payload(payload: Mapping[str, Any]) -> MrnLookup:
    if not payload:
        return MrnLookup(ok=False, error="Prazen odgovor razširitve.")
    if not payload.get("ok"):
        return MrnLookup(
            ok=False,
            error=str(payload.get("error") or "MRN ni prebran."),
            detail=str(payload.get("warning") or ""),
            tax_number=str(payload.get("taxNumber") or ""),
            date_from=str(payload.get("dateFrom") or ""),
            date_to=str(payload.get("dateTo") or ""),
        )
    def _rows_from(raw_list: Any) -> list[MrnRow]:
        out: list[MrnRow] = []
        for raw in raw_list or []:
            if not isinstance(raw, dict):
                continue
            mrn = normalize_text(raw.get("mrn")).upper()
            if not mrn:
                continue
            vat = decimal_value(raw.get("vat") if raw.get("vat") not in (None, "") else raw.get("vatText"))
            out.append(
                MrnRow(
                    mrn=mrn,
                    vat=vat,
                    tip=normalize_text(raw.get("tip")),
                    verzija=normalize_text(raw.get("verzija")),
                    kontrola=normalize_text(raw.get("kontrola")),
                    datum_priprave=normalize_text(raw.get("datumPriprave")),
                    datum_sprejema=normalize_text(raw.get("datumSprejema")),
                    datum_sprostitve=normalize_text(raw.get("datumSprostitve")),
                    vat_text=normalize_text(raw.get("vatText")) or money_text(vat),
                    opombe=normalize_text(raw.get("opombe")),
                )
            )
        return out

    unique = _rows_from(payload.get("rows"))
    all_rows = _rows_from(payload.get("allRows")) or unique
    total = decimal_value(payload.get("totalVat"))
    if not total and unique:
        total = sum((r.vat for r in unique), ZERO)
    empty = bool(payload.get("empty")) or not unique
    return MrnLookup(
        ok=True,
        rows=unique,
        all_rows=all_rows,
        total_vat=total,
        source="eDavki MRN (Chrome)",
        detail=(
            "Za izbrano obdobje ni podatkov."
            if empty
            else f"{len(unique)} deklaracij (blago → 16030/26046)"
        ),
        date_from=str(payload.get("dateFrom") or ""),
        date_to=str(payload.get("dateTo") or ""),
        tax_number=str(payload.get("taxNumber") or ""),
        empty=empty,
    )


def fetch_edavki_mrn(
    *,
    date_from: str,
    date_to: str,
    tax_number: str = PROJEST_TAX_ID,
    company_name: str = PROJEST_NAME,
    timeout_sec: float = 45.0,
) -> MrnLookup:
    """Online prenos MRN (brez CSV). Zahteva Chrome + razširitev ≥ 1.4.11."""
    result_box: dict[str, Any] = {"payload": None, "event": threading.Event()}

    class Handler(_MrnHandler):
        pass

    Handler.result_box = result_box
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report_url = f"http://127.0.0.1:{port}/mrn"
    query = urlencode(
        {
            "kirkpr_edavki_mrn": report_url,
            "kirkpr_tax": re.sub(r"\D", "", tax_number or ""),
            "kirkpr_firm": str(company_name or "").strip()[:120],
            "kirkpr_from": str(date_from or "").strip(),
            "kirkpr_to": str(date_to or "").strip(),
        }
    )
    try:
        # Sproži razširitev prek localhost (ne nov eDavki zavihek).
        _open_in_chrome(f"http://127.0.0.1:{port}/go?{query}")
        if not result_box["event"].wait(timeout_sec):
            return MrnLookup(
                ok=False,
                error=(
                    "Chrome ni vrnil MRN v času. Preveri prijavo v eDavkih in "
                    "razširitev Minimax podjetja (v1.4.11+)."
                ),
                date_from=date_from,
                date_to=date_to,
            )
        parsed = _parse_payload(result_box.get("payload") or {})
        if not parsed.date_from:
            parsed.date_from = date_from
        if not parsed.date_to:
            parsed.date_to = date_to
        wanted = re.sub(r"\D", "", tax_number or "")
        got = re.sub(r"\D", "", parsed.tax_number or "")
        if wanted and got and wanted != got:
            return MrnLookup(
                ok=False,
                error=(
                    f"Napačna firma na eDavkih: davčna {got}, "
                    f"pričakovano {wanted} ({company_name}). "
                    "Zamenjaj zavezanca in ponovi MRN prenesi."
                ),
                tax_number=got,
                date_from=date_from,
                date_to=date_to,
            )
        return parsed
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass


def _mrn_date_stamp(value: str) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    if len(text) == 8:
        if text[:2] in {"20", "19"}:
            return text
        return text[4:8] + text[2:4] + text[0:2]
    return text or "obdobje"


def save_mrn_csv(lookup: MrnLookup, folder: Path) -> Path | None:
    """Shrani MRN tabelo v mapo (Excel ;). Če ni vrstic, ne piše datoteke."""
    if not lookup.ok or lookup.empty or not lookup.rows:
        return None
    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = f"{_mrn_date_stamp(lookup.date_from)}-{_mrn_date_stamp(lookup.date_to)}"
    path = dest / f"MRN_{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            ["MRN", "Tip", "Verzija", "Datum sprejema", "Datum sprostitve", "DDV", "Opombe"]
        )
        for row in lookup.rows:
            writer.writerow(
                [
                    row.mrn,
                    row.tip,
                    row.verzija,
                    row.datum_sprejema,
                    row.datum_sprostitve,
                    row.vat_text or money_text(row.vat),
                    row.opombe,
                ]
            )
    return path


def apply_mrn_to_pr_rows(
    pr_rows: list[dict[str, Any]],
    lookup: MrnLookup,
    *,
    db: Any = None,
) -> dict[str, int]:
    """
    Označi PR kot MRN samo, če dokument/opomba že vsebuje točno to MRN kodo.

    NE ujemaj po znesku DDV (Foshan 1.602,64 ≠ samodejni MRN).
    """
    if not lookup.ok or not lookup.rows:
        return {"matched": 0, "updated": 0}
    by_code = {r.mrn.upper(): r for r in lookup.rows}

    matched = 0
    updated = 0
    for pr in pr_rows:
        found_codes = extract_mrn_codes(
            pr.get("notes"),
            pr.get("document_no"),
            pr.get("internal_no"),
        )
        mrn_row = None
        for code in found_codes:
            if code in by_code:
                mrn_row = by_code[code]
                break
        if mrn_row is None:
            continue
        matched += 1
        try:
            raw = json.loads(pr.get("raw_json") or "{}")
            if not isinstance(raw, dict):
                raw = {}
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
        if raw.get("supplier_kind") == "MRN" and mrn_row.mrn in str(pr.get("notes") or ""):
            continue
        raw["supplier_kind"] = "MRN"
        raw["MRN"] = mrn_row.mrn
        raw["26 uvoz - MRN"] = mrn_row.mrn
        notes = normalize_text(pr.get("notes"))
        tag = f"MRN {mrn_row.mrn}"
        if mrn_row.mrn not in notes:
            notes = f"{tag} | {notes}".strip(" |") if notes else tag
        payload = {
            **pr,
            "notes": notes,
            "raw_json": raw,
            "self_assessment": 1,
            "vat_deductible": 1,
            "sync_status": pr.get("sync_status"),
        }
        if db is not None and pr.get("id"):
            db.upsert_pr(payload, int(pr["id"]))
        else:
            pr.update(payload)
            pr["raw_json"] = json.dumps(raw, ensure_ascii=False)
        updated += 1
    return {"matched": matched, "updated": updated}


def lookup_to_info(lookup: MrnLookup) -> dict[str, Any]:
    return {
        "info_mrn_codes": lookup.codes,
        "info_mrn_text": lookup.codes_text(),
        "info_mrn_amount": lookup.total_vat,
        "info_ddvo_26": lookup.total_vat,
        "edavki_mrn_source": lookup.source,
        "edavki_mrn_detail": lookup.detail,
    }


__all__ = [
    "MrnLookup",
    "MrnRow",
    "apply_mrn_to_pr_rows",
    "fetch_edavki_mrn",
    "lookup_to_info",
    "save_mrn_csv",
]
