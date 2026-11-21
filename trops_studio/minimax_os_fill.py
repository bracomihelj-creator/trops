"""Prenos v OS: na PROJEST → seznam OS → Edit → vpis."""

from __future__ import annotations

import logging

import json
import time
from typing import Any, Mapping

from trops_studio.chrome_cdp import (
    CdpSession,
    activate_page,
    find_debug_endpoint,
    list_pages,
    open_new_tab,
)
from trops_studio.minimax_runtime import MINIMAX_OS_EDIT_URL, MINIMAX_OS_LIST_URL, _open_minimax_url
from trops_studio.os_cdp_fill import fill_os_form
from trops_studio.os_keyboard_fill import fill_os_via_keyboard

MINIMAX_ORGS_URL = "https://moj.minimax.si/SI/VA/WebUI/Zacetek/Zacetek.aspx"
PROJEST_ORG_ID = "179535"
PROJEST_ORG_NAME = "PROJEST d.o.o."

_ACTIVE_ORG_JS = r"""
(() => {
  const nav = document.querySelector("ul.mm-menu li span.mm-header-dropdown a, ul.mm-menu span.mm-header-dropdown a");
  const title = String(document.title || "");
  return String((nav && nav.textContent) || title || "").replace(/\s+/g, " ").trim();
})()
""".strip()

_KIND_JS = r"""
(() => {
  const path = String(location.pathname || "");
  const has = (sel) => !!document.querySelector(sel);
  if (has("input.os-dobavitelj") || has('input[name="Dobavitelj"]') || has("input.os-listina")) {
    return "form";
  }
  if (/OsnovnoSredstvoEdit/i.test(path)) return "form_loading";
  if (has("#PPC_ctl04_ctl00_bNov") || (/OsnovnoSredstvo\.aspx/i.test(path) && !/Edit/i.test(path))) {
    return "list";
  }
  if (/ZacetekOrganizacije/i.test(path)) return "dash";
  if (has("table.home-table-organizacije") || /Zacetek\.aspx/i.test(path)) return "orgs";
  return "other";
})()
""".strip()


def _click_org_js(org_id: str, org_name: str) -> str:
    data = json.dumps({"org_id": org_id, "org_name": org_name}, ensure_ascii=False)
    return f"""
(() => {{
  const p = {data};
  const row = (p.org_id && document.querySelector('tr[data-organizacijaid="' + p.org_id + '"]'))
    || Array.from(document.querySelectorAll("table.home-table-organizacije tr.prijava, tr[data-organizacijaid]"))
      .find((tr) => (tr.textContent || "").toUpperCase().includes((p.org_name || "").toUpperCase()));
  if (!row) return "no_org";
  const link = row.querySelector("a") || row;
  link.click();
  return "clicked_org";
}})()
""".strip()


_CLICK_NOV_JS = r"""
(() => {
  const dest = "https://moj.minimax.si/SI/VA/WebUI/OsnovnoSredstvo/OsnovnoSredstvoEdit.aspx";
  const nov = document.querySelector("#PPC_ctl04_ctl00_bNov");
  if (nov) {
    try { nov.scrollIntoView({ block: "center", inline: "nearest" }); } catch (e) {}
    nov.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
    nov.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
    nov.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
    nov.click();
  }
  if (!/OsnovnoSredstvoEdit/i.test(String(location.pathname || ""))) {
    location.href = dest;
  }
  return "clicked_nov";
})()
""".strip()


_FOCUS_STEVILKA_JS = r"""
(() => {
  const el = document.querySelector("input.os-stevilka, input[name='Stevilka']");
  if (el) el.focus();
  return !!(el && document.activeElement === el);
})()
""".strip()

_ACTIVE_KIND_JS = r"""
(() => {
  const el = document.activeElement;
  if (!el) return "";
  const name = String(el.getAttribute("name") || "");
  const cls = String(el.className || "");
  const group = el.closest(".input-group");
  const label = String((group && group.innerText) || "").replace(/\s+/g, " ").toLowerCase();
  const gcls = [cls, group && group.className].filter(Boolean).join(" ");
  if (name === "Stevilka" || /os-stevilka/.test(gcls) || label.includes("inventarna")) return "stevilka";
  if (name === "Naziv" || /os-naziv/.test(gcls)) return "naziv";
  if (/os-datum-pridobitve/.test(gcls) || label.includes("datum pridobitve")) return "datum_pridobitve";
  if (name === "Dobavitelj" || /os-dobavitelj/.test(gcls)) return "dobavitelj";
  if (name === "Listina" || /os-listina/.test(gcls) || label.includes("listina")) return "listina";
  if (/os-amortizacijska/.test(gcls) || label.includes("amortizacijska skupina")) return "amort";
  if (/vos-datum/.test(gcls)) return "datum_zac";
  if (label.includes("nabavna")) return "nabava";
  return "";
})()
""".strip()


def _fill_js(payload: Mapping[str, str]) -> str:
    data = json.dumps(
        {
            "datum": str(payload.get("datum") or ""),
            "dobavitelj": str(payload.get("dobavitelj") or ""),
            "listina": str(payload.get("listina") or ""),
            "nabava": str(payload.get("nabava") or ""),
            "naziv": str(payload.get("naziv") or ""),
        },
        ensure_ascii=False,
    )
    return f"""
(() => {{
  const p = {data};
  const q = (sel) => document.querySelector(sel);
  const protoSet = (el, val) => {{
    const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement : window.HTMLInputElement;
    const desc = Object.getOwnPropertyDescriptor(proto.prototype, "value");
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
  }};
  const visible = (el) => {{
    if (!el || el.disabled || el.type === "hidden") return false;
    if (el.classList && el.classList.contains("mm-select-offscreen")) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }};
  const tabStops = () => {{
    const root = q("#MainForm") || document;
    return [...root.querySelectorAll("input, textarea")].filter((el) => {{
      if (!visible(el)) return false;
      if (el.tabIndex < 0) return false;
      if (el.closest(".mm-submenu, header, #mMHelpInput")) return false;
      return true;
    }});
  }};
  const fieldKind = (el) => {{
    if (!el) return "";
    const name = String(el.getAttribute("name") || "");
    const cls = String(el.className || "");
    const group = el.closest(".input-group");
    const label = String((group && group.innerText) || "").replace(/\\s+/g, " ").toLowerCase();
    const gcls = [cls, group && group.className].filter(Boolean).join(" ");
    if (name === "Stevilka" || /os-stevilka/.test(gcls) || label.includes("inventarna")) return "stevilka";
    if (name === "Naziv" || /os-naziv/.test(gcls)) return "naziv";
    if (/os-datum-pridobitve/.test(gcls) || label.includes("datum pridobitve")) return "datum_pridobitve";
    if (name === "Dobavitelj" || /os-dobavitelj/.test(gcls)) return "dobavitelj";
    if (name === "Listina" || /os-listina/.test(gcls) || label.includes("listina")) return "listina";
    if (/os-amortizacijska/.test(gcls) || label.includes("amortizacijska skupina")) return "amort";
    if (label.includes("% amort")) return "proc";
    if (/vos-datum/.test(gcls)) return "datum_zac";
    if (label.includes("nabavna")) return "nabava";
    if (label.includes("neamortiz") || label.includes("popravek") || label.includes("količina") || label.includes("kolicina")) return "skip";
    return "";
  }};
  const sendTab = (from) => {{
    const ev = {{ key: "Tab", code: "Tab", keyCode: 9, which: 9, bubbles: true, cancelable: true }};
    if (from) {{
      from.dispatchEvent(new KeyboardEvent("keydown", ev));
      from.dispatchEvent(new Event("change", {{ bubbles: true }}));
      from.blur();
    }}
    const stops = tabStops();
    const idx = from ? stops.indexOf(from) : -1;
    const next = idx >= 0 ? stops[idx + 1] : stops[0];
    if (next) {{
      next.focus();
      next.dispatchEvent(new FocusEvent("focusin", {{ bubbles: true }}));
    }}
    if (from) from.dispatchEvent(new KeyboardEvent("keyup", ev));
    return document.activeElement;
  }};
  const typeVal = (el, val) => {{
    if (!el || val == null || val === "") return false;
    el.focus();
    try {{ el.select(); }} catch (e) {{}}
    protoSet(el, val);
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, data: String(val), inputType: "insertReplacementText" }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    if (window.jQuery) {{
      try {{
        const $el = window.jQuery(el);
        $el.val(val).trigger("input").trigger("change");
        const parts = String(val).split(".");
        if (parts.length === 3 && $el.datepicker) {{
          $el.datepicker("setDate", new Date(+parts[2], +parts[1] - 1, +parts[0]));
        }}
      }} catch (e) {{}}
    }}
    return true;
  }};
  const want = {{
    naziv: p.naziv || p.dobavitelj || "",
    datum_pridobitve: p.datum || "",
    dobavitelj: p.dobavitelj || "",
    listina: p.listina || "",
    datum_zac: p.datum || "",
    nabava: p.nabava || ""
  }};
  const start = q("input.os-stevilka") || q('input[name="Stevilka"]');
  if (start) start.focus();
  let el = start && document.activeElement === start ? start : document.activeElement;
  if (!el || el === document.body) el = start;
  const filled = [];
  const seen = {{}};
  for (let i = 0; i < 22; i++) {{
    el = sendTab(el);
    const kind = fieldKind(el);
    if (!kind || kind === "stevilka" || kind === "skip" || kind === "amort" || kind === "proc") continue;
    if (seen[kind]) continue;
    if (want[kind] && typeVal(el, want[kind])) {{
      filled.push(kind);
      seen[kind] = true;
    }}
    if (seen.nabava && seen.listina && seen.dobavitelj) break;
  }}
  const amort = q(".os-amortizacijska-skupina .mm-select-input");
  if (amort) {{ try {{ amort.focus(); }} catch (e) {{}} }}
  const naziv = q("input.os-naziv") || q('input[name="Naziv"]');
  const dob = q("input.os-dobavitelj") || q('input[name="Dobavitelj"]');
  const listina = q("input.os-listina") || q('input[name="Listina"]');
  const nabava = q("fieldset:nth-of-type(2) input.input.text-align-right");
  return JSON.stringify({{
    ok: !!(dob && dob.value) || !!(listina && listina.value) || filled.length > 0,
    filled,
    svelte: !!q("#osnovno-sredstvo-edit-app-state"),
    values: {{
      dobavitelj: dob ? dob.value : "",
      listina: listina ? listina.value : "",
      nabava: nabava ? nabava.value : "",
      naziv: naziv ? naziv.value : ""
    }}
  }});
}})()
""".strip()


def _page_url(page: Mapping[str, Any]) -> str:
    return str(page.get("url") or "")


def _is_projest(text: str) -> bool:
    return "PROJEST" in str(text or "").upper()


def _tab_rank(page: Mapping[str, Any]) -> int:
    url = _page_url(page)
    title = str(page.get("title") or "")
    if "OsnovnoSredstvoEdit" in url:
        return 0
    if "OsnovnoSredstvo.aspx" in url:
        return 1
    if "ZacetekOrganizacije" in url and _is_projest(title):
        return 2
    if "Zacetek.aspx" in url:
        return 3
    if _is_projest(title):
        return 4
    if "moj.minimax.si" in url.casefold():
        return 5
    return 9


def _pick_tab(pages: list[Mapping[str, Any]], *, prefer_id: str = "") -> dict[str, Any] | None:
    if prefer_id:
        for page in pages:
            if str(page.get("id") or "") == prefer_id:
                return dict(page)
    ranked = [dict(page) for page in pages if "moj.minimax.si" in _page_url(page).casefold()]
    if not ranked:
        return None
    ranked.sort(key=_tab_rank)
    return ranked[0]


def _session_for(page: Mapping[str, Any]) -> CdpSession:
    ws = str(page.get("webSocketDebuggerUrl") or "").strip()
    if not ws:
        raise RuntimeError("Zavihek nima CDP WebSocket.")
    return CdpSession(ws)


def _reconnect(host: str, port: int, prefer: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], CdpSession]:
    time.sleep(0.8)
    prefer_id = str((prefer or {}).get("id") or "")
    page = _pick_tab(list_pages(host, port), prefer_id=prefer_id) or (dict(prefer) if prefer else None)
    if page is None:
        raise RuntimeError("Ni Minimax zavihka.")
    activate_page(host, port, str(page.get("id") or ""))
    session = _session_for(page)
    session.connect()
    return page, session


def _kind(session: CdpSession) -> str:
    try:
        return str(session.evaluate(_KIND_JS) or "other")
    except Exception:
        return "other"


def _wait_kind(session: CdpSession, *wanted: str, timeout: float = 12.0) -> str:
    deadline = time.time() + timeout
    last = "other"
    while time.time() < deadline:
        last = _kind(session)
        if last in wanted:
            return last
        time.sleep(0.4)
    return last


def _parse_fill(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _active_org(session: CdpSession) -> str:
    try:
        return str(session.evaluate(_ACTIVE_ORG_JS) or "")
    except Exception:
        return ""


def _on_projest(session: CdpSession, page: Mapping[str, Any]) -> bool:
    if _is_projest(_active_org(session)):
        return True
    return _is_projest(str(page.get("title") or ""))


def _nav_same_tab(
    host: str, port: int, page: Mapping[str, Any], session: CdpSession, url: str
) -> tuple[dict[str, Any], CdpSession]:
    session.navigate(url)
    session.close()
    return _reconnect(host, port, page)


def _fill_form(session: CdpSession, payload: Mapping[str, str]) -> dict[str, Any]:
    return fill_os_form(session, payload)


def open_and_fill_osnovno_sredstvo(payload: Mapping[str, str]) -> dict[str, Any]:
    typed = fill_os_via_keyboard(payload)
    if typed.get("filled"):
        return typed

    endpoint = find_debug_endpoint()
    if endpoint is None:
        if not typed.get("window"):
            _open_minimax_url(MINIMAX_OS_EDIT_URL)
            time.sleep(2.4)
        typed = fill_os_via_keyboard(payload)
        if typed.get("filled"):
            return typed
        return {
            "ok": bool(typed.get("window")),
            "cdp": False,
            "filled": False,
            "message": typed.get("message")
            or "Minimax OS okno ni v ospredju. Klikni v Inventarno številko in ponovi Prenos v OS.",
        }

    host, port = endpoint
    page = _pick_tab(list_pages(host, port))
    if page is None:
        page = open_new_tab(host, port, MINIMAX_OS_LIST_URL)
        if page is None:
            opened = _open_minimax_url(MINIMAX_OS_LIST_URL)
            return {
                "ok": opened,
                "cdp": True,
                "filled": False,
                "message": "CDP je aktiven, a zavihka ni bilo mogoče odpreti.",
            }
        time.sleep(1.0)

    session: CdpSession | None = None
    try:
        page, session = _reconnect(host, port, page)
        kind = _wait_kind(session, "form", "list", "dash", "orgs", timeout=5.0)
        if kind == "form":
            result = _fill_form(session, payload)
            if result.get("filled"):
                return result
            typed = fill_os_via_keyboard(payload)
            return typed if typed.get("filled") else result

        if kind != "orgs" and not _on_projest(session, page):
            page, session = _nav_same_tab(host, port, page, session, MINIMAX_ORGS_URL)
            kind = _wait_kind(session, "orgs", timeout=6.0)

        if kind == "orgs":
            clicked = str(session.evaluate(_click_org_js(PROJEST_ORG_ID, PROJEST_ORG_NAME)) or "")
            if not clicked.startswith("clicked"):
                return {
                    "ok": False,
                    "cdp": True,
                    "filled": False,
                    "message": "Na seznamu organizacij ni PROJEST d.o.o. (179535).",
                }
            session.close()
            page, session = _reconnect(host, port, page)
            kind = _wait_kind(session, "dash", "list", "form", timeout=8.0)

        if kind != "list":
            page, session = _nav_same_tab(host, port, page, session, MINIMAX_OS_LIST_URL)
            kind = _wait_kind(session, "list", timeout=8.0)
        if kind != "list":
            return {
                "ok": False,
                "cdp": True,
                "filled": False,
                "message": "Seznam OS ni odprt. Ostani na Osnovna sredstva in ponovi Prenos v OS.",
            }
        session.evaluate(_CLICK_NOV_JS)
        session.close()
        page, session = _reconnect(host, port, page)
        if _wait_kind(session, "form", timeout=8.0) != "form":
            page, session = _nav_same_tab(host, port, page, session, MINIMAX_OS_EDIT_URL)
        if _wait_kind(session, "form", timeout=10.0) != "form":
            return {
                "ok": True,
                "cdp": True,
                "filled": False,
                "message": "+Nov / Edit OS se ni odprl. Ponovi Prenos v OS na seznamu.",
            }
        result = _fill_form(session, payload)
        if result.get("filled"):
            return result
        typed = fill_os_via_keyboard(payload)
        return typed if typed.get("filled") else result
    except Exception as exc:
        return {
            "ok": True,
            "cdp": True,
            "filled": False,
            "message": f"Polnjenje ni uspelo ({exc}). Ponovi Prenos v OS.",
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                logging.getLogger(__name__).warning("Obnovljiva napaka (minimax_os_fill.py:466)", exc_info=True)
