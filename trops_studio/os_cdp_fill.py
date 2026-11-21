"""CDP vpis OS — selektorji iz izpolnjenega Hitri zajema + 20 % amort. skupina."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from trops_studio.chrome_cdp import CdpSession

# Iz izpolnjenega obrazca (Hitri zajem): 20,00% Oprema, vozila, mehanizacija
AMORT_ID = "1017686"
AMORT_QUERY = "20"
AMORT_LABEL = "Oprema, vozila, mehanizacija"

_FIELDS = (
    (
        "naziv",
        [
            "input.os-naziv",
            "input[name='Naziv']",
            "fieldset:nth-of-type(1) > div.form-vertical.labels-left > div.input-group.required:nth-of-type(2) > input.os-naziv.input",
        ],
        "text",
    ),
    ("datum_pridobitve", [".os-datum-pridobitve input"], "date"),
    (
        "dobavitelj",
        [
            "input.os-dobavitelj",
            "input[name='Dobavitelj']",
            "fieldset:nth-of-type(1) > div.form-vertical.labels-left > div.input-group.required:nth-of-type(4) > input.os-dobavitelj.input",
        ],
        "text",
    ),
    (
        "listina",
        [
            "input.os-listina",
            "input[name='Listina']",
            "fieldset:nth-of-type(1) > div.form-vertical.labels-left > div.input-group.required:nth-of-type(5) > input.os-listina.input",
        ],
        "text",
    ),
    ("datum_zac", [".vos-datum input"], "date"),
    (
        "nabava",
        [
            "fieldset:nth-of-type(2) > div.form-vertical.labels-left > div.input-group:nth-of-type(2) > input.input.text-align-right",
        ],
        "amount",
    ),
)


def _parse(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _js_find_set(selectors: list[str], value: str, kind: str) -> str:
    return f"""
(() => {{
  const sels = {json.dumps(selectors, ensure_ascii=False)};
  const value = {json.dumps(value, ensure_ascii=False)};
  const kind = {json.dumps(kind)};
  const find = () => {{
    for (const s of sels) {{
      const el = document.querySelector(s);
      if (el && el.getClientRects().length) return el;
    }}
    return document.querySelector(sels[0]);
  }};
  const protoSet = (el, val) => {{
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
  }};
  const fire = (el, val) => {{
    try {{
      el.dispatchEvent(new InputEvent("input", {{ bubbles: true, data: String(val), inputType: "insertText" }}));
    }} catch (e) {{
      el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    }}
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }};
  const el = find();
  if (!el) return JSON.stringify({{ ok: false, found: false }});
  if (kind === "date") {{
    const m = String(value).match(/^(\\d{{1,2}})\\.(\\d{{1,2}})\\.(\\d{{2,4}})$/);
    if (!m) return JSON.stringify({{ ok: false, found: true, value: el.value }});
    let y = +m[3]; if (y < 100) y += 2000;
    const d = +m[1], mo = +m[2];
    const date = new Date(y, mo - 1, d);
    const pad = (n) => String(n).padStart(2, "0");
    const si = pad(d) + "." + pad(mo) + "." + y;
    const $ = window.jQuery || window.$;
    el.focus();
    if ($ && $.fn && $(el).datepicker) {{
      $(el).datepicker("setDate", date);
      try {{
        if (el.id && $.datepicker._selectDate) {{
          $.datepicker._selectDate("#" + el.id, pad(d) + "." + pad(mo) + "." + String(y).slice(-2));
        }}
      }} catch (e) {{}}
      $(el).trigger("input").trigger("change");
    }}
    protoSet(el, si);
    fire(el, si);
    return JSON.stringify({{ ok: true, found: true, value: el.value }});
  }}
  el.scrollIntoView({{ block: "center" }});
  el.focus();
  try {{ el.select(); }} catch (e) {{}}
  protoSet(el, value);
  fire(el, value);
  return JSON.stringify({{ ok: !!(el.value || "").trim(), found: true, value: el.value || "" }});
}})()
""".strip()


def _js_focus(selectors: list[str]) -> str:
    return f"""
(() => {{
  const sels = {json.dumps(selectors, ensure_ascii=False)};
  for (const s of sels) {{
    const el = document.querySelector(s);
    if (!el || !el.getClientRects().length) continue;
    el.scrollIntoView({{ block: "center" }});
    el.focus();
    try {{ el.select(); }} catch (e) {{}}
    return true;
  }}
  return false;
}})()
""".strip()


_READ_JS = r"""
(() => {
  const v = (sel) => {
    const el = document.querySelector(sel);
    return el ? String(el.value || "") : "";
  };
  return JSON.stringify({
    naziv: v("input.os-naziv"),
    dobavitelj: v("input.os-dobavitelj"),
    listina: v("input.os-listina"),
    datum: v(".os-datum-pridobitve input"),
    datum_zac: v(".vos-datum input"),
    nabava: v("fieldset:nth-of-type(2) > div.form-vertical.labels-left > div.input-group:nth-of-type(2) > input.input.text-align-right"),
    amort: v(".os-amortizacijska-skupina .mm-select-input"),
    amort_id: v(".os-amortizacijska-skupina input.mm-select-offscreen")
  });
})()
""".strip()

_AMORT_OPEN_JS = f"""
(() => {{
  const wrap = document.querySelector(".mMDropDownList.os-amortizacijska-skupina");
  if (!wrap) return "no_wrap";
  const inp = wrap.querySelector("input.mm-select-input");
  if (!inp) return "no_input";
  inp.scrollIntoView({{ block: "center" }});
  inp.click();
  inp.focus();
  const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  if (desc && desc.set) desc.set.call(inp, {json.dumps(AMORT_QUERY)});
  else inp.value = {json.dumps(AMORT_QUERY)};
  inp.dispatchEvent(new Event("input", {{ bubbles: true }}));
  inp.dispatchEvent(new KeyboardEvent("keydown", {{ bubbles: true, key: "ArrowDown", code: "ArrowDown" }}));
  return "opened";
}})()
""".strip()

_AMORT_PICK_JS = f"""
(() => {{
  const wantId = {json.dumps(AMORT_ID)};
  const nodes = document.querySelectorAll(
    ".mm-select-results li, .mm-select-results [role=option], [role=listbox] [role=option], .mm-select-dropdown li"
  );
  for (const n of nodes) {{
    const t = String(n.innerText || n.textContent || "").replace(/\\s+/g, " ");
    if (!t) continue;
    if (/20\\s*[,.]?\\s*00\\s*%/.test(t) || (/oprema/i.test(t) && /vozila/i.test(t))) {{
      n.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true, cancelable: true }}));
      n.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true, cancelable: true }}));
      n.click();
      return "picked:" + t.slice(0, 80);
    }}
  }}
  const off = document.querySelector(".os-amortizacijska-skupina input.mm-select-offscreen");
  if (off) {{
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    if (desc && desc.set) desc.set.call(off, wantId);
    else off.value = wantId;
    off.dispatchEvent(new Event("input", {{ bubbles: true }}));
    off.dispatchEvent(new Event("change", {{ bubbles: true }}));
    return "id:" + wantId;
  }}
  return "no_option";
}})()
""".strip()


def _looks_filled(got: str, want: str, kind: str) -> bool:
    g = str(got or "").strip()
    w = str(want or "").strip()
    if not w:
        return bool(g)
    if kind == "amount":
        def num(s: str) -> float | None:
            t = s.replace(" ", "").replace(".", "").replace(",", ".")
            try:
                return float(t)
            except ValueError:
                return None

        a, b = num(g), num(w)
        if a is None or b is None:
            return False
        return abs(a - b) < 0.02 and a != 0
    if kind == "date":
        return g.replace(" ", "") == w.replace(" ", "") or w[:5] in g
    return w.lower() in g.lower() or g.lower() in w.lower()


def _type_cdp(session: CdpSession, selectors: list[str], value: str) -> bool:
    try:
        if not session.evaluate(_js_focus(selectors)):
            return False
        session.select_all()
        session.insert_text(value)
        time.sleep(0.12)
        session.press_tab()
        return True
    except Exception:
        return False


def _fill_amort(session: CdpSession) -> str:
    try:
        opened = str(session.evaluate(_AMORT_OPEN_JS, timeout=6.0) or "")
    except Exception as exc:
        return f"err:{exc}"
    if not opened.startswith("open"):
        return opened
    time.sleep(0.55)
    try:
        session.insert_text(AMORT_QUERY)
    except Exception:
        pass
    time.sleep(0.45)
    try:
        return str(session.evaluate(_AMORT_PICK_JS, timeout=6.0) or "no_pick")
    except Exception as exc:
        return f"err:{exc}"


def fill_os_form(session: CdpSession, payload: Mapping[str, str]) -> dict[str, Any]:
    values = {
        "naziv": str(payload.get("naziv") or payload.get("dobavitelj") or ""),
        "datum_pridobitve": str(payload.get("datum") or ""),
        "dobavitelj": str(payload.get("dobavitelj") or ""),
        "listina": str(payload.get("listina") or ""),
        "datum_zac": str(payload.get("datum") or ""),
        "nabava": str(payload.get("nabava") or ""),
    }
    filled: list[str] = []
    for key, selectors, kind in _FIELDS:
        val = values.get(key) or ""
        if not val:
            continue
        try:
            session.evaluate(_js_find_set(selectors, val, kind), timeout=8.0)
        except Exception:
            pass
        time.sleep(0.2)
        if kind != "date":
            _type_cdp(session, selectors, val)
        time.sleep(0.35)
        read = _parse(session.evaluate(_READ_JS, timeout=5.0))
        got = {
            "naziv": read.get("naziv"),
            "dobavitelj": read.get("dobavitelj"),
            "listina": read.get("listina"),
            "datum_pridobitve": read.get("datum"),
            "datum_zac": read.get("datum_zac"),
            "nabava": read.get("nabava"),
        }.get(key, "")
        if _looks_filled(str(got or ""), val, kind):
            filled.append(key)
    amort = _fill_amort(session)
    if str(amort).startswith("picked") or str(amort).startswith("id"):
        filled.append("amort_20")
    read = _parse(session.evaluate(_READ_JS, timeout=6.0))
    ok = _looks_filled(str(read.get("dobavitelj") or ""), values["dobavitelj"], "text") or _looks_filled(
        str(read.get("listina") or ""), values["listina"], "text"
    )
    shown = ", ".join(filled)
    return {
        "ok": True,
        "cdp": True,
        "filled": ok,
        "fields": filled,
        "values": read,
        "amort": amort,
        "message": (
            f"Vpisano: {shown or '—'}. Skupina 20 %: {AMORT_LABEL}."
            if ok
            else "Rdeča polja (Dobavitelj, Listina, Nabava) niso ostala vpisana. Ponovi Prenos v OS."
        ),
    }
