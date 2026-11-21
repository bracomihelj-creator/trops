"""DateEntry (dtpicker) z obliko dd.mm.yyyy, vezan na StringVar."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import ttk
from typing import Any

from trops_studio.money import date_text, parse_date


def _parse_si_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return parse_date(value)
    except Exception:
        text = str(value or "").strip()
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def make_date_entry(
    parent: tk.Misc,
    textvariable: tk.StringVar | None = None,
    *,
    width: int = 12,
    **kwargs: Any,
) -> tk.Widget:
    """
    Ustvari DateEntry (koledar). Če tkcalendar ni na voljo → navaden Entry.
    Oblika: dd.mm.yyyy. Sinhronizira z StringVar.
    """
    try:
        from tkcalendar import DateEntry
    except ImportError:
        return ttk.Entry(parent, textvariable=textvariable, width=width)

    style_kw = {
        "width": width,
        "date_pattern": "dd.mm.yyyy",
        "showweeknumbers": False,
        "borderwidth": 1,
        "background": "#20345d",
        "foreground": "#f3f6ff",
        "headersbackground": "#2a3f66",
        "headersforeground": "#f3f6ff",
        "selectbackground": "#4f8cff",
        "selectforeground": "#ffffff",
        "normalbackground": "#15213a",
        "normalforeground": "#f3f6ff",
        "weekendbackground": "#1a2744",
        "weekendforeground": "#ffcc66",
        "othermonthforeground": "#6a7a96",
        "othermonthbackground": "#101a2f",
        "othermonthweforeground": "#6a7a96",
        "othermonthwebackground": "#101a2f",
    }
    style_kw.update(kwargs)
    # locale lahko manjka na Windows — ne vsiljuj
    try:
        entry = DateEntry(parent, **style_kw)
    except Exception:
        style_kw.pop("locale", None)
        entry = DateEntry(parent, **style_kw)

    if textvariable is None:
        return entry

    updating = {"on": False}

    def to_var(_event: object | None = None) -> None:
        if updating["on"]:
            return
        updating["on"] = True
        try:
            textvariable.set(date_text(entry.get_date()))
        except Exception:
            pass
        finally:
            updating["on"] = False

    def from_var(*_args: object) -> None:
        if updating["on"]:
            return
        parsed = _parse_si_date(textvariable.get())
        if parsed is None:
            return
        updating["on"] = True
        try:
            if entry.get_date() != parsed:
                entry.set_date(parsed)
        except Exception:
            pass
        finally:
            updating["on"] = False

    initial = _parse_si_date(textvariable.get())
    if initial is not None:
        try:
            entry.set_date(initial)
        except Exception:
            pass
    else:
        # prazen datum — pusti današnji v DateEntry, a ne prepiši praznega StringVar
        pass

    entry.bind("<<DateEntrySelected>>", to_var, add="+")
    entry.bind("<Return>", to_var, add="+")
    # FocusOut samo, če StringVar že ima datum (ne vsili današnjega v prazno polje)
    def on_focus_out(_event: object | None = None) -> None:
        if str(textvariable.get() or "").strip():
            to_var()

    entry.bind("<FocusOut>", on_focus_out, add="+")
    textvariable.trace_add("write", from_var)
    return entry
