"""Trops Studio 5.0.00 — pywebview + Edge WebView2 (vzorec Evidence 8).

HTTP API + statični ui/ ; js_api Bridge samo za datotečne dialoge / zapiranje.
Poslovno jedro: motor.Motor → trops_studio (+ AppService).
"""
from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UI = ROOT / "ui"
HOST = "127.0.0.1"

from motor import APP_TITLE, APP_VERSION, BadRequest, Motor, parse_id  # noqa: E402
from trops_studio_web.accounts_parties import InputError  # noqa: E402
from trops_studio.config import WEBVIEW_PROFILE_DIR  # noqa: E402
from trops_studio.log_setup import setup_logging  # noqa: E402
from trops_studio_web.jobs import JobManager  # noqa: E402

log = logging.getLogger("trops.host")


class NotFound(LookupError):
    pass


class Bridge:
    """Datotečni izbirnik in zapiranje — brez Tk (kot Evidence 8)."""

    def _dialog(self, kind_name: str, file_types: Any = None, directory: bool = False) -> str:
        try:
            import webview
        except Exception:
            return ""
        wins = webview.windows
        if not wins:
            return ""
        fd = getattr(webview, "FileDialog", None)
        if directory:
            kind = getattr(fd, "FOLDER", None) if fd else None
            if kind is None:
                kind = getattr(webview, "FOLDER_DIALOG", 20)
        else:
            kind = getattr(fd, kind_name, None) if fd else None
            if kind is None:
                kind = getattr(webview, "OPEN_DIALOG" if kind_name == "OPEN" else "SAVE_DIALOG", 10)
        kwargs: Dict[str, Any] = {}
        if file_types:
            kwargs["file_types"] = tuple(file_types) if isinstance(file_types, (list, tuple)) else (file_types,)
        result = wins[0].create_file_dialog(kind, **kwargs)
        if not result:
            return ""
        if isinstance(result, (list, tuple)):
            return str(result[0] or "")
        return str(result)

    def pick_file(self, file_types: Any = None) -> str:
        return self._dialog("OPEN", file_types or ("Vse (*.*)",))

    def pick_excel(self) -> str:
        return self._dialog("OPEN", ("Excel (*.xls;*.xlsx;*.xlsm)", "Vse (*.*)"))

    def pick_excel_multi(self) -> list:
        try:
            import webview
        except Exception:
            return []
        if not webview.windows:
            return []
        fd = getattr(webview, "FileDialog", None)
        kind = getattr(fd, "OPEN", None) if fd else getattr(webview, "OPEN_DIALOG", 10)
        result = webview.windows[0].create_file_dialog(
            kind, allow_multiple=True, file_types=("Vasco Excel (*.xls;*.xlsx;*.xlsm)", "Vse (*.*)")
        )
        return [str(p) for p in (result or [])]

    def pick_folder(self) -> str:
        return self._dialog("FOLDER", directory=True)

    def pick_zip_bak(self) -> str:
        return self._dialog("OPEN", ("ZIP/BAK (*.zip;*.bak)", "Vse (*.*)"))

    def close_window(self) -> None:
        try:
            import webview
        except Exception:
            return
        for w in webview.windows:
            try:
                w.destroy()
            except Exception:
                pass


def _json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.motor = Motor()
        self.jobs = JobManager()
        self.token = secrets.token_urlsafe(32)
        super().__init__((HOST, 0), Handler)
        self.allowed_host = f"{HOST}:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: AppServer

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _ok_origin(self) -> bool:
        host = (self.headers.get("Host") or "").split("%")[0]
        return host == self.server.allowed_host

    def _ticket_ok(self) -> bool:
        if not self._ok_origin():
            return False
        cookie = self.headers.get("Cookie") or ""
        if f"trops5={self.server.token}" in cookie:
            return True
        q = parse_qs(urlparse(self.path).query)
        tickets = q.get("ticket") or []
        return bool(tickets) and tickets[0] == self.server.token

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_resp(self, code: int, obj: Any, extra: Optional[Dict[str, str]] = None) -> None:
        if isinstance(obj, dict) and obj.get("ok") is False:
            obj = normalize_result(obj)
        self._send(code, _json(obj), "application/json; charset=utf-8", extra)

    def _error(self, code: int, message: str) -> None:
        self._json_resp(code, {"ok": False, "error": message, "msg": message})

    def _exception(self, exc: Exception) -> None:
        if isinstance(exc, (BadRequest, InputError)):
            self._error(400, str(exc))
        elif isinstance(exc, NotFound):
            self._error(404, str(exc))
        elif isinstance(exc, (RuntimeError,)) and "Druga naloga" in str(exc):
            self._error(409, str(exc))
        else:
            log.error("Napaka v API: %s\n%s", exc, traceback.format_exc())
            self._error(500, f"Notranja napaka: {exc} (podrobnosti v data/logs/trops.log)")

    def _read_json(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or "0")
        if n < 0 or n > 4_000_000:
            return {}
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        q = parse_qs(parsed.query)
        extra = {"Set-Cookie": f"trops5={self.server.token}; HttpOnly; SameSite=Strict; Path=/"}

        if path.startswith("/ui/"):
            if not self._ok_origin():
                self._json_resp(403, {"ok": False, "msg": "Ni veljavne seje."})
                return
            rel = path[4:].lstrip("/")
            fp = (UI / rel).resolve()
            if UI.resolve() not in fp.parents and fp != UI.resolve():
                self._json_resp(403, {"ok": False})
                return
            if not fp.is_file():
                self._json_resp(404, {"ok": False, "msg": "Datoteka ni najdena."})
                return
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            self._send(200, fp.read_bytes(), ctype)
            return

        if not self._ticket_ok():
            self._json_resp(403, {"ok": False, "msg": "Ni veljavne seje."})
            return

        if path in ("/", "/index.html"):
            html = (UI / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8", extra)
            return

        m = self.server.motor
        try:
            if path == "/api/boot":
                self._json_resp(200, m.boot())
                return
            if path == "/api/companies":
                search = (q.get("q") or [""])[0]
                rows = m.list_companies(search)
                warn = "" if m.companies else "Seznam podjetij ni dosegljiv (EvidencaFirm / KirKpr). Preveri settings.json."
                self._json_resp(200, {"ok": True, "rows": rows, "warning": warn})
                return
            if path == "/api/ir":
                self._json_resp(200, m.list_ir())
                return
            if path == "/api/pr":
                self._json_resp(200, m.list_pr())
                return
            if path == "/api/parties":
                search = (q.get("q") or [""])[0]
                self._json_resp(200, m.list_parties(search))
                return
            if path == "/api/ddvo":
                self._json_resp(200, m.compute_ddvo())
                return
            if path == "/api/knjige":
                book = (q.get("book") or ["IR"])[0]
                self._json_resp(200, m.knjige_data(book))
                return
            if path == "/api/konti":
                self._json_resp(200, m.konti_data())
                return
            if path == "/api/analysis":
                self._json_resp(200, m.analysis_text())
                return
            if path == "/api/knjizbe":
                search = (q.get("q") or [""])[0]
                self._json_resp(200, m.knjizbe_data(search))
                return
            if path == "/api/integra":
                self._json_resp(200, m.integra_info())
                return
            if path == "/api/job":
                job = self.server.jobs.get((q.get("id") or [""])[0])
                if job is None:
                    self._json_resp(404, {"ok": False, "error": "Naloga ne obstaja.", "msg": "Naloga ne obstaja."})
                    return
                job["ok"] = job.get("state") != "error"
                if job.get("result") is not None:
                    job["result"] = normalize_result(job["result"])
                self._json_resp(200, job)
                return
            if path == "/api/party":
                res = m.party_get(parse_id((q.get("id") or [""])[0]))
                if res.get("ok") is False:
                    self._error(404, str(res.get("error")))
                    return
                self._json_resp(200, res)
                return
            if path == "/api/account_map":
                self._json_resp(200, m.account_map_info())
                return
            if path == "/api/row":
                kind = (q.get("kind") or ["IR"])[0]
                rid = (q.get("id") or [""])[0]
                res = m.get_row(kind, rid)
                if isinstance(res, dict) and res.get("ok") is False:
                    self._error(404, str(res.get("error") or res.get("msg") or "Vrstica ne obstaja."))
                    return
                self._json_resp(200, res)
                return
            self._error(404, f"Neznan GET: {path}")
        except Exception as exc:
            self._exception(exc)

    def do_POST(self) -> None:
        if not self._ticket_ok():
            self._json_resp(403, {"ok": False, "msg": "Ni veljavne seje."})
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        body = self._read_json()
        m = self.server.motor
        try:
            if path == "/api/action":
                self._json_resp(200, dispatch_action(m, body, self.server.jobs))
                return
            if path == "/api/company/select":
                self._json_resp(
                    200,
                    m.select_company(
                        key=str(body.get("key") or ""),
                        zst=str(body.get("zst") or ""),
                        name=str(body.get("name") or ""),
                        org=str(body.get("org") or ""),
                    ),
                )
                return
            if path == "/api/period":
                self._json_resp(
                    200,
                    m.set_period(
                        period_from=str(body.get("from") or body.get("period_from") or ""),
                        period_to=str(body.get("to") or body.get("period_to") or ""),
                        label=str(body.get("label") or ""),
                        year=str(body.get("year") or ""),
                        rev=str(body.get("rev") or ""),
                    ),
                )
                return
            if path == "/api/filters":
                self._json_resp(200, m.set_filters(body.get("filters") or body))
                return
            if path == "/api/row/save":
                kind = str(body.get("kind") or "IR").upper()
                payload = body.get("row") if isinstance(body.get("row"), dict) else body
                self._json_resp(200, m.save_row(kind, payload))
                return
            self._error(404, f"Neznan POST: {path}")
        except Exception as exc:
            self._exception(exc)


# Akcije, ki lahko trajajo dolgo (API, SQL, datoteke) → ozadna naloga + polling.
LONG_ACTIONS = {
    "sync_ready": "Sinhronizacija z Minimax",
    "sync_parties": "Minimax↓ stranke",
    "check_api": "Preverjanje Minimax API",
    "fetch_mrn": "eDavki MRN",
    "import_vasco": "Uvoz Vasco",
    "import_kirkpr": "Uvoz KIR/KPR",
    "integra_restore": "Obnova TROPS (RESTORE)",
    "integra_kisanal": "UrejanjeKisanal",
    "ddvo_export": "DDV-O XML + PDF",
    "export_kirkpr_xml": "Izvoz XML za KirKpr/Minimax",
    "ddvo_preview_pdf": "DDV-O predogled PDF",
    "ddvo_virman": "DDV-O PDF + virman",
    "ddvo_email_draft": "Osnutek e-pošte DDV-O",
    "ddvo_email_send": "Pošiljanje e-pošte DDV-O",
    "minimax_accounts_sync": "Kontni plan iz Minimax",
    "party_ajpes": "AJPES poizvedba",
    "party_vies": "VIES preverba",
}


def _kind(body: Dict[str, Any]) -> str:
    kind = str(body.get("kind") or "IR").upper()
    if kind not in {"IR", "PR"}:
        raise BadRequest("kind mora biti IR ali PR.")
    return kind


def _actions(m: Motor) -> Dict[str, Callable[[Dict[str, Any]], Any]]:
    return {
        "refresh": lambda b: m.refresh_all(),
        "shift_period": lambda b: m.shift_period(-1 if int(b.get("delta") or 1) < 0 else 1),
        "reset_period": lambda b: m.reset_period(),
        "set_chk": lambda b: m.set_chk(_kind(b), b.get("id"), bool(b.get("checked"))),
        "set_chk_all": lambda b: m.set_chk_all(_kind(b), bool(b.get("checked")), b.get("ids")),
        "confirm": lambda b: m.confirm_selected(_kind(b), b.get("ids") or []),
        "delete_rows": lambda b: m.delete_rows(_kind(b), b.get("ids") or []),
        "apply_account": lambda b: m.apply_account(_kind(b), str(b.get("account") or ""), b.get("ids") or [], bool(b.get("remember", True))),
        "defaults": lambda b: m.default_accounts(),
        "sync_preview": lambda b: m.sync_preview(str(b.get("scope") or "ALL")),
        "sync_ready": lambda b: m.sync_ready_minimax(str(b.get("scope") or "ALL")),
        "sync_parties": lambda b: m.sync_minimax_parties(),
        "check_api": lambda b: m.check_minimax_api(),
        "missing_parties": lambda b: m.missing_parties(str(b.get("book") or "PR")),
        "delete_preview": lambda b: m.delete_preview(),
        "delete_import_period": lambda b: m.delete_import_for_period() if b.get("confirm") is True else _need_confirm(),
        "import_kirkpr": lambda b: m.import_kirkpr_path(str(b.get("path") or "")),
        "import_vasco": lambda b: m.import_vasco_paths(b.get("paths")),
        "integra_set_dir": lambda b: m.integra_set_sql_dir(str(b.get("path") or "")),
        "integra_restore": lambda b: m.integra_restore(str(b.get("candidate") or "")) if b.get("confirm") is True else _need_confirm(),
        "integra_kisanal": lambda b: m.integra_kisanal(b.get("year") or ""),
        "open_path": lambda b: m.open_path(str(b.get("path") or "")),
        "open_classic": lambda b: m.open_classic_ui(),
        "fetch_mrn": lambda b: m.fetch_edavki_mrn(),
        "ddvo_export": lambda b: m.ddvo_export(),
        "export_kirkpr_xml": lambda b: m.export_kirkpr_xml(),
        "learn_accounts": lambda b: m.learn_accounts(),
        "ddvo_preview_pdf": lambda b: m.ddvo_preview_pdf(),
        "ddvo_virman": lambda b: m.ddvo_virman(),
        "ddvo_email_draft": lambda b: m.ddvo_email_draft(),
        "ddvo_email_send": lambda b: m.ddvo_email_send(b),
        "account_map_save": lambda b: m.account_map_save(b.get("maps"), bool(b.get("apply_data")), b.get("confirm") is True),
        "minimax_accounts_sync": lambda b: m.minimax_accounts_sync(),
        "party_save": lambda b: m.party_save(b.get("party") if isinstance(b.get("party"), dict) else None),
        "party_ajpes": lambda b: m.party_ajpes(b.get("party") if isinstance(b.get("party"), dict) else {}),
        "party_vies": lambda b: m.party_vies(b.get("party") if isinstance(b.get("party"), dict) else {}),
        "set_ui_pref": lambda b: m.set_ui_pref(b.get("key"), b.get("value")),
    }


# Tvegane akcije: brez izrecnega confirm=true se ne začnejo (niti kot ozadna naloga).
CONFIRM_ACTIONS = {"delete_import_period", "integra_restore", "ddvo_email_send"}


def _need_confirm() -> Dict[str, Any]:
    raise BadRequest("Akcija zahteva potrditev.")


def normalize_result(res: Any) -> Any:
    """Enoten format: {ok, msg?, error?}. Napaka je vedno v `error` IN `msg`."""
    if isinstance(res, dict):
        if res.get("ok") is False:
            err = str(res.get("error") or res.get("msg") or res.get("message") or "Napaka.")
            res["error"] = err
            res["msg"] = err
        elif "msg" not in res and res.get("message"):
            res["msg"] = str(res.get("message"))
    return res


def dispatch_action(m: Motor, body: Dict[str, Any], jobs: Optional[JobManager] = None) -> Dict[str, Any]:
    """Enotni /api/action dispečer."""
    name = str(body.get("name") or "").strip()
    if not name:
        raise BadRequest("Manjka name.")
    table = _actions(m)
    fn = table.get(name)
    if fn is None:
        raise NotFound(f"Neznana akcija: {name}")
    if name in CONFIRM_ACTIONS and body.get("confirm") is not True:
        _need_confirm()
    if jobs is not None and name in LONG_ACTIONS and not body.get("sync"):
        return jobs.start(LONG_ACTIONS[name], lambda b: normalize_result(fn(b)), dict(body), m)
    if jobs is not None and jobs.busy and name not in {"set_chk", "set_chk_all"}:
        raise BadRequest("Naloga v ozadju še teče — počakaj na zaključek.")
    return normalize_result(fn(body))


def desktop() -> int:
    setup_logging()
    if sys.platform != "win32":
        raise SystemExit("Namizni zagon je namenjen Windows 10/11.")
    if not (UI / "index.html").is_file():
        raise SystemExit(f"Manjka UI: {UI / 'index.html'}")
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "Manjka pywebview. Zaženi INSTALL.pyw ali: py -3.10 -m pip install pywebview"
        ) from exc

    WEBVIEW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    server = AppServer()
    threading.Thread(target=server.serve_forever, name="trops-4-api", daemon=True).start()
    url = f"http://{server.allowed_host}/?ticket={server.token}"
    webview.create_window(
        f"{APP_TITLE} {APP_VERSION}",
        url,
        width=1480,
        height=940,
        min_size=(1100, 720),
        background_color="#f4f7fc",
        text_select=True,
        js_api=Bridge(),
    )
    webview.start(
        gui="edgechromium",
        debug=False,
        private_mode=False,
        storage_path=str(WEBVIEW_PROFILE_DIR),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(desktop() or 0)
