"""Trops Studio 5.0.00 — motor: AppService + akcije za spletni UI (naloge, DDV-O, potrditve)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trops_studio import APP_TITLE, __version__ as APP_VERSION  # noqa: E402
from trops_studio.money import parse_date  # noqa: E402
from trops_studio.sync_state import SYNC_ERROR, SYNC_READY, SYNC_SYNCED  # noqa: E402
from trops_studio_web.accounts_parties import AccountsPartiesMixin, InputError  # noqa: E402
from trops_studio_web.ui_prefs import load_ui_prefs, save_ui_pref  # noqa: E402
from trops_studio_web.service import AppService, _safe  # noqa: E402

__all__ = ["APP_TITLE", "APP_VERSION", "AppService", "BadRequest", "Motor"]
log = logging.getLogger(__name__)


def _same_value(a: Any, b: Any) -> bool:
    """Primerja vrednost iz baze in iz obrazca (zneski: 39,50 == 39.50 == 39.5)."""
    sa = "" if a is None else str(a).strip()
    sb = "" if b is None else str(b).strip()
    if sa == sb:
        return True

    def _num(x: str) -> float | None:
        t = x.replace(" ", "")
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return None

    na, nb = _num(sa or "0"), _num(sb or "0")
    if na is not None and nb is not None:
        return abs(na - nb) < 0.005
    # datum iz obrazca (2026-10-01) proti datumu z uro v bazi
    return len(sb) == 10 and sa[:10] == sb


class BadRequest(InputError):
    """Neveljaven vhod iz UI → HTTP 400 z JSON {ok:false,error}."""


def parse_id(value: Any) -> int:
    try:
        rid = int(str(value).strip())
    except (TypeError, ValueError):
        raise BadRequest(f"Neveljaven ID: {value!r}") from None
    if rid <= 0:
        raise BadRequest(f"Neveljaven ID: {value!r}")
    return rid


def parse_ids(values: Any) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise BadRequest("ids mora biti seznam.")
    return [parse_id(v) for v in values]


class Motor(AccountsPartiesMixin, AppService):
    """Javni motor za host.py."""

    @property
    def version(self) -> str:
        return str(APP_VERSION)

    # ------------------------------------------------------------ osnova
    def boot(self) -> dict[str, Any]:
        data = self.bootstrap()
        if not isinstance(data, dict):
            return {"ok": False, "error": "Bootstrap ni uspel."}
        data.setdefault("ok", True)
        from trops_studio.config import SETTINGS_ERRORS

        if SETTINGS_ERRORS:
            data["warnings"] = list(data.get("warnings") or []) + list(SETTINGS_ERRORS)
        data["ui"] = load_ui_prefs()
        data["version"] = APP_VERSION
        data["title"] = APP_TITLE
        return data

    def set_ui_pref(self, key: Any, value: Any) -> dict[str, Any]:
        """Videz (Trops 4 / Trops 5) ali tema → settings.local.json. Ne vpliva na podatke."""
        return save_ui_pref(key, value)

    def get_row(self, kind: str, row_id: Any) -> dict[str, Any]:
        rid = parse_id(row_id)
        return self.get_pr(rid) if str(kind).upper() == "PR" else self.get_ir(rid)

    def save_row(self, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise BadRequest("Manjka vrstica.")
        data = dict(payload)
        if data.get("id") not in (None, ""):
            data["id"] = parse_id(data["id"])
            existing = self.get_row(kind, data["id"])
            if not existing.get("ok"):
                raise BadRequest(existing.get("error") or "Vrstica ne obstaja.")
            merged = dict(existing["row"])
            changed = any(not _same_value(merged.get(k), v) for k, v in data.items() if k != "id")
            # Spremenjena vrstica se vrne v »local« (enako kot Tk urejevalnik), razen če UI izrecno pošlje status.
            # Shranjevanje brez sprememb ohrani status sinhronizacije (ni ponovnega pošiljanja v Minimax).
            if "sync_status" not in data and changed:
                merged.pop("sync_status", None)
            for key in [k for k in merged if k.endswith(("_display", "_si", "_label")) or k in {"checked", "region", "has_account", "si_vat_err"}]:
                merged.pop(key, None)
            merged.update(data)
            data = merged
        return self.save_pr(data) if str(kind).upper() == "PR" else self.save_ir(data)

    def set_chk(self, kind: str, row_id: Any, checked: bool) -> dict[str, Any]:
        return super().set_chk(kind, parse_id(row_id), checked)

    def set_chk_all(self, kind: str, checked: bool, ids: Any = None) -> dict[str, Any]:
        """ids=None → vse filtrirane vrstice (Vse označi / Odznači)."""
        return super().set_chk_all(kind, checked, None if ids is None else parse_ids(ids))

    def confirm_selected(self, kind: str, ids: Any) -> dict[str, Any]:
        id_list = parse_ids(ids)
        if not id_list:
            raise BadRequest("Ni označenih vrstic za potrditev.")
        res = super().confirm_selected(kind, id_list)
        if res.get("ok"):
            res["msg"] = f"Potrjenih {res.get('confirmed', 0)} vrstic ({str(kind).upper()}) — pripravljene za Minimax."
        return res

    def delete_rows(self, kind: str, ids: Any) -> dict[str, Any]:
        id_list = parse_ids(ids)
        if not id_list:
            raise BadRequest("Ni označenih vrstic.")
        res = super().delete_rows(kind, id_list)
        res["msg"] = f"Izbrisanih {res.get('deleted', 0)} vrstic."
        return res

    def apply_account(self, kind: str, account: str, ids: Any, remember: bool = True) -> dict[str, Any]:
        id_list = parse_ids(ids)
        if not id_list:
            raise BadRequest("Ni označenih vrstic.")
        if not str(account or "").strip():
            raise BadRequest("Vnesi konto.")
        if str(kind).upper() == "IR":
            res = self.apply_ir_account(id_list, account, remember)
        else:
            res = self.apply_pr_account(id_list, account, remember)
        res["msg"] = f"Konto {res.get('account')} nastavljen na {res.get('count')} vrstic."
        return res

    # ------------------------------------------------------------ predogledi pred tveganimi akcijami
    def sync_preview(self, scope: str = "ALL") -> dict[str, Any]:
        with self._lock:
            scope_u = str(scope or "ALL").upper()
            db = self.db
            ir = [] if scope_u == "PR" else db.list_ir_by_sync(SYNC_READY) + db.list_ir_by_sync(SYNC_ERROR)
            pr = [] if scope_u == "IR" else db.list_pr_by_sync(SYNC_READY) + db.list_pr_by_sync(SYNC_ERROR)
            books = self._active_ir_books()
            if books:
                ir = [r for r in ir if str(r.get("book") or "") in books]
            synced = 0
            if scope_u != "PR":
                synced += len(db.list_ir_by_sync(SYNC_SYNCED))
            if scope_u != "IR":
                synced += len(db.list_pr_by_sync(SYNC_SYNCED))
            parties = len(db.list_parties_by_sync(SYNC_READY)) if scope_u == "ALL" else 0
            return {
                "ok": True,
                "scope": scope_u,
                "ir": len(ir),
                "pr": len(pr),
                "parties": parties,
                "synced_recheck": synced,
                "company": (self._company_payload() or {}).get("name", ""),
                "org": (self._company_payload() or {}).get("org", ""),
            }

    def _period_row_ids(self) -> tuple[list[int], list[int]]:
        ir_ids: list[int] = []
        pr_ids: list[int] = []
        for rows, keys, out in (
            (self.db.list_ir(), ("document_date", "booking_date"), ir_ids),
            (self.db.list_pr(), ("received_date", "document_date", "booking_date"), pr_ids),
        ):
            for row in rows:
                for key in keys:
                    raw = row.get(key)
                    if not raw:
                        continue
                    try:
                        parsed = parse_date(raw)
                    except Exception:
                        parsed = None
                    if parsed is None:
                        continue
                    if self.filter_from_date <= parsed <= self.filter_to_date:
                        out.append(int(row["id"]))
                    break
        return ir_ids, pr_ids

    def delete_preview(self) -> dict[str, Any]:
        with self._lock:
            ir_ids, pr_ids = self._period_row_ids()
            p = self._period_payload()
            return {"ok": True, "ir": len(ir_ids), "pr": len(pr_ids), "from": p.get("from"), "to": p.get("to"), "label": p.get("label")}

    def delete_import_for_period(self) -> dict[str, Any]:
        res = super().delete_import_for_period()
        d = res.get("deleted") or {}
        res["msg"] = f"Izbrisano IR {d.get('ir', 0)}, PR {d.get('pr', 0)} (vrstice brez datuma ostanejo)."
        return res

    # ------------------------------------------------------------ uvoz
    def import_vasco_paths(self, paths: Any = None) -> dict[str, Any]:
        from trops_studio.vasco_discover import classify_selected_files

        if isinstance(paths, list):
            files = [Path(str(p)) for p in paths if str(p).strip()]
            if not files:
                raise BadRequest("Izberi vsaj eno Vasco datoteko (IF* = IR, kp* = PR).")
            missing = [str(p) for p in files if not p.is_file()]
            if missing:
                raise BadRequest("Datoteka ne obstaja: " + ", ".join(missing))
            ir_files, pr_files = classify_selected_files(files)
            payload = {"ir_files": [str(p) for p in ir_files], "pr_files": [str(p) for p in pr_files]}
        else:
            payload = dict(paths or {})
            if not any(payload.values()):
                raise BadRequest("Izberi Vasco datoteke.")
        res = super().import_vasco_paths(payload)
        res["msg"] = "Vasco uvoz končan."
        return res

    def import_kirkpr_path(self, path: str) -> dict[str, Any]:
        res = super().import_kirkpr_path(path)
        if res.get("ok"):
            res["msg"] = f"KIR/KPR uvoz končan: {Path(path).name}"
        return res

    def learn_accounts(self) -> dict[str, Any]:
        with self._lock:
            res = self.db.learn_account_rules_from_rows()
            return {"ok": True, "msg": f"Konti iz zgodovine: PR {res.get('pr', 0)}, IR {res.get('ir', 0)} pravil."}

    def export_kirkpr_xml(self) -> dict[str, Any]:
        """Minimax/KirKpr XML (IR + PR) za filtrirane vrstice obdobja, validirano proti XSD."""
        from trops_studio.companies import company_name, company_zst
        from trops_studio.config import DEFAULT_MINIMAX_OUT, TROPS_ROOT
        from trops_studio.xml_export import export_minimax_xml_for_kirkpr

        with self._lock:
            ir_rows, pr_rows = self._filtered_ir(), self._filtered_pr()
            if not ir_rows and not pr_rows:
                raise BadRequest("Ni IR/PR vrstic za izvoz.")
            label, out_dir = "PROJEST", DEFAULT_MINIMAX_OUT
            if self.active_company:
                zst = company_zst(self.active_company) or ""
                name = company_name(self.active_company)
                label = f"{zst}_{name}" if zst else name
                if zst and (TROPS_ROOT / zst).is_dir():
                    out_dir = TROPS_ROOT / zst / "MiniMax"
            res = export_minimax_xml_for_kirkpr(self.db, output_dir=out_dir, ir_rows=ir_rows, pr_rows=pr_rows, company_label=label)
            return _safe({"ok": True, "msg": res.message.split("\n", 1)[0], "detail": res.message, "folder": str(out_dir)})

    # ------------------------------------------------------------ DDV-O
    def _ddvo_context(self) -> dict[str, Any]:
        ir_rows, pr_rows = self._period_rows()
        if not ir_rows and not pr_rows:
            raise BadRequest("V obdobju ni IR/PR vrstic za DDV-O.")
        return {
            "ir_rows": ir_rows,
            "pr_rows": pr_rows,
            "period_from": self.filter_from_date,
            "period_to": self.filter_to_date,
            "company": self.active_company,
        }

    def ddvo_export(self) -> dict[str, Any]:
        from trops_studio.ddvo_actions import export_pdf_xml

        with self._lock:
            ctx = self._ddvo_context()
            result = export_pdf_xml(ctx.pop("ir_rows"), ctx.pop("pr_rows"), **ctx)
            folder = str(result.pdf_path.parent) if result.pdf_path else ""
            return _safe({"ok": True, "msg": result.message.split("\n", 1)[0], "xml": result.xml_path, "pdf": result.pdf_path, "folder": folder})

    def ddvo_preview_pdf(self) -> dict[str, Any]:
        from trops_studio.ddvo_actions import preview_pdf

        with self._lock:
            ctx = self._ddvo_context()
            path = preview_pdf(ctx.pop("ir_rows"), ctx.pop("pr_rows"), **ctx)
            self.open_path(str(path))
            return _safe({"ok": True, "msg": f"Predogled: {Path(path).name}", "pdf": path})

    def ddvo_virman(self) -> dict[str, Any]:
        from trops_studio.ddvo_actions import create_virman_package

        with self._lock:
            ctx = self._ddvo_context()
            pkg = create_virman_package(ctx.pop("ir_rows"), ctx.pop("pr_rows"), **ctx)
            self._last_package = {
                "paths": [str(p) for p in (pkg.pdf_path, pkg.virman_path) if p],
                "obligation": str(getattr(pkg, "obligation", "0")),
                "payment": str(getattr(pkg, "payment", "0")),
                "period": (self.filter_from_date, self.filter_to_date),
                "company": self._company_db_key,
            }
            return _safe({
                "ok": True,
                "msg": str(pkg.message).split("\n", 1)[0],
                "detail": pkg.message,
                "folder": getattr(pkg, "package_dir", None),
                "paths": self._last_package["paths"],
            })

    def ddvo_email_draft(self) -> dict[str, Any]:
        """Samo osnutek — NIČ ne pošlje. Pošiljanje je ločena, potrjena akcija."""
        from trops_studio.ddvo_actions import GMAIL_SMTP_CC, GMAIL_SMTP_FROM, ddvo_client_mail_draft

        last = getattr(self, "_last_package", None)
        if not last or last.get("company") != self._company_db_key or last.get("period") != (self.filter_from_date, self.filter_to_date):
            self.ddvo_virman()
            last = self._last_package
        with self._lock:
            to_addr, subject, body = ddvo_client_mail_draft(
                company=self.active_company,
                period_from=self.filter_from_date,
                period_to=self.filter_to_date,
                obligation=Decimal(last["obligation"] or "0"),
                payment=Decimal(last["payment"] or "0"),
            )
            return _safe({
                "ok": True,
                "from": GMAIL_SMTP_FROM,
                "to": to_addr,
                "cc": GMAIL_SMTP_CC,
                "subject": subject,
                "body_html": body,
                "attachments": last["paths"],
                "warning": "" if to_addr else "Manjka e-pošta stranke (polje Email v evidenci firm).",
            })

    def ddvo_email_send(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Pošlje izključno po izrecni potrditvi v UI (confirm=true)."""
        from trops_studio.ddvo_actions import send_gmail_email

        if body.get("confirm") is not True:
            raise BadRequest("Pošiljanje zahteva izrecno potrditev.")
        to_addr = str(body.get("to") or "").strip()
        subject = str(body.get("subject") or "").strip()
        if "@" not in to_addr:
            raise BadRequest("Vnesi veljaven e-naslov prejemnika.")
        if not subject:
            raise BadRequest("Manjka zadeva.")
        last = getattr(self, "_last_package", None) or {}
        allowed = set(last.get("paths") or [])
        attachments = [Path(p) for p in (body.get("attachments") or []) if str(p) in allowed]
        note = send_gmail_email(
            to_addr=to_addr,
            subject=subject,
            body_html=str(body.get("body_html") or ""),
            cc=str(body.get("cc") or ""),
            attachments=attachments,
        )
        return {"ok": True, "msg": note.split("\n", 1)[0], "detail": note}

    # ------------------------------------------------------------ eDavki MRN
    def fetch_edavki_mrn(self) -> dict[str, Any]:
        from trops_studio.companies import company_name, company_tax
        from trops_studio.edavki_mrn import fetch_edavki_mrn
        from trops_studio.ui.period import format_si_date

        company = self.active_company or {}
        lookup = fetch_edavki_mrn(
            date_from=format_si_date(self.filter_from_date),
            date_to=format_si_date(self.filter_to_date),
            tax_number=company_tax(company) or "",
            company_name=company_name(company) or "",
            timeout_sec=50.0,
        )
        rows = list(getattr(lookup, "rows", []) or [])
        ok = bool(getattr(lookup, "ok", False))
        total = getattr(lookup, "total_vat", None)
        return _safe({
            "ok": ok,
            "error": "" if ok else (getattr(lookup, "error", "") or "MRN ni uspel."),
            "msg": f"eDavki MRN: {len(rows)} vrstic" + (f", DDV {total} EUR" if total is not None else ""),
            "count": len(rows),
            "codes": lookup.codes_text() if ok and hasattr(lookup, "codes_text") else "",
        })

    # ------------------------------------------------------------ Integra
    def integra_info(self) -> dict[str, Any]:
        info = super().integra_info()
        n = len(info.get("candidates") or []) + len(info.get("baks") or [])
        info["status"] = f"Najdenih kopij: {n}" if n else "V SQL mapi ni ZIP/BAK kopij."
        info["year"] = self.filter_from_date.year
        return info

    def integra_restore(self, candidate: str = "") -> dict[str, Any]:
        info = super().integra_info()
        allowed = {str(Path(p)) for p in (info.get("candidates") or []) + (info.get("baks") or [])}
        if not candidate or str(Path(candidate)) not in allowed:
            raise BadRequest("Izberi eno od najdenih ZIP/BAK kopij v SQL mapi.")
        res = super().integra_restore(candidate)
        if res.get("ok"):
            res["msg"] = f"RESTORE uspešen: {Path(candidate).name}"
        return res

    def integra_kisanal(self, year: Any = "") -> dict[str, Any]:
        res = super().integra_kisanal(year or self.filter_from_date.year)
        if res.get("ok"):
            res["msg"] = str((res.get("kisanal") or {}).get("message") or "UrejanjeKisanal končan.").split("\n", 1)[0]
        return res

    # ------------------------------------------------------------ ostalo
    def open_path(self, path: str) -> dict[str, Any]:
        if not path:
            raise BadRequest("Manjka pot.")
        if sys.platform != "win32":
            return {"ok": False, "error": "Odpiranje map deluje samo na Windows."}
        return super().open_path(path)

    def open_classic_ui(self) -> dict[str, Any]:
        """Klasični Tk urejevalnik (polni PR/IR obrazci, Stranke, VAT API, OS fill …)."""
        script = ROOT / "run_trops.py"
        if not script.is_file():
            return {"ok": False, "error": "Klasični vmesnik ni nameščen."}
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        cmd = [str(pyw if pyw.is_file() else exe), str(script), "--db", str(self.db.path)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags)
        return {"ok": True, "msg": "Klasični vmesnik se odpira. Po zaprtju klikni Osveži."}

    def check_minimax_api(self) -> dict[str, Any]:
        res = super().check_minimax_api()
        res.setdefault("msg", res.get("message", ""))
        return res

    def sync_minimax_parties(self) -> dict[str, Any]:
        res = super().sync_minimax_parties()
        res.setdefault("msg", res.get("message", ""))
        return res

    def missing_parties(self, book: str = "PR") -> dict[str, Any]:
        res = super().missing_parties(book)
        res["msg"] = f"Manjkajočih strank: {res.get('count', 0)}"
        return res
