from __future__ import annotations

import json
import re
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Any, Mapping

from trops_studio.config import DATA_DIR

UI_PREFS_PATH = DATA_DIR / "ui_prefs.json"

DEFAULT_COLORS: dict[str, str] = {
    "bg": "#0b1220",
    "panel": "#101a2f",
    "panel_alt": "#15213a",
    "card": "#17243d",
    "header": "#20345d",
    "accent": "#4f8cff",
    "purple": "#8b7cff",
    "success": "#34c77b",
    "warning": "#ffcc66",
    "danger": "#ef5350",
    "text": "#f3f6ff",
    "muted": "#a5b0c8",
    "input": "#0d172a",
    "line": "#2a3b60",
}

_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def default_ui_prefs() -> dict[str, Any]:
    colors = dict(DEFAULT_COLORS)
    return {
        "colors": colors,
        "font_family": "Segoe UI",
        "font_size": 10,
        "heading_font_size": 9,
        "button_font_family": "Segoe UI Semibold",
        "button_font_size": 10,
        "button_bold": True,
        "button_bg": colors["header"],
        "button_fg": colors["text"],
        "button_hover": colors["accent"],
        "button_accent_bg": colors["accent"],
        "button_accent_fg": colors["text"],
        "button_success_bg": colors["success"],
        "button_success_fg": "#07170e",
        "button_danger_bg": colors["danger"],
        "button_danger_fg": "#ffffff",
        "button_padding_x": 12,
        "button_padding_y": 8,
    }


def normalize_hex(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if _HEX_RE.match(text):
        if not text.startswith("#"):
            text = f"#{text}"
        return f"#{text[1:].upper()}"
    return fallback


def _int_pref(value: Any, fallback: int, *, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, number))


def merge_ui_prefs(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    prefs = default_ui_prefs()
    if not raw:
        return prefs
    incoming_colors = raw.get("colors") if isinstance(raw.get("colors"), Mapping) else {}
    for key, default in DEFAULT_COLORS.items():
        prefs["colors"][key] = normalize_hex(
            incoming_colors.get(key) or raw.get(key),
            default,
        )
    colors = prefs["colors"]
    prefs["font_family"] = str(raw.get("font_family") or prefs["font_family"]).strip() or "Segoe UI"
    prefs["font_size"] = _int_pref(raw.get("font_size"), 10, lo=8, hi=18)
    prefs["heading_font_size"] = _int_pref(raw.get("heading_font_size"), 9, lo=8, hi=16)
    prefs["button_font_family"] = (
        str(raw.get("button_font_family") or prefs["button_font_family"]).strip() or prefs["font_family"]
    )
    prefs["button_font_size"] = _int_pref(raw.get("button_font_size"), 10, lo=8, hi=18)
    prefs["button_bold"] = bool(raw.get("button_bold", True))
    prefs["button_bg"] = normalize_hex(raw.get("button_bg"), colors["header"])
    prefs["button_fg"] = normalize_hex(raw.get("button_fg"), colors["text"])
    prefs["button_hover"] = normalize_hex(raw.get("button_hover"), colors["accent"])
    prefs["button_accent_bg"] = normalize_hex(raw.get("button_accent_bg"), colors["accent"])
    prefs["button_accent_fg"] = normalize_hex(raw.get("button_accent_fg"), colors["text"])
    prefs["button_success_bg"] = normalize_hex(raw.get("button_success_bg"), colors["success"])
    prefs["button_success_fg"] = normalize_hex(raw.get("button_success_fg"), "#07170e")
    prefs["button_danger_bg"] = normalize_hex(raw.get("button_danger_bg"), colors["danger"])
    prefs["button_danger_fg"] = normalize_hex(raw.get("button_danger_fg"), "#ffffff")
    prefs["button_padding_x"] = _int_pref(raw.get("button_padding_x"), 12, lo=4, hi=24)
    prefs["button_padding_y"] = _int_pref(raw.get("button_padding_y"), 8, lo=2, hi=18)
    return prefs


def load_ui_prefs(path: Path | None = None) -> dict[str, Any]:
    target = path or UI_PREFS_PATH
    if not target.is_file():
        return default_ui_prefs()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default_ui_prefs()
    return merge_ui_prefs(payload if isinstance(payload, dict) else {})


def save_ui_prefs(prefs: Mapping[str, Any], path: Path | None = None) -> Path:
    target = path or UI_PREFS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = merge_ui_prefs(prefs)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _button_font(prefs: Mapping[str, Any]) -> tuple[str, int, str] | tuple[str, int]:
    family = str(prefs.get("button_font_family") or "Segoe UI Semibold")
    size = int(prefs.get("button_font_size") or 10)
    if prefs.get("button_bold", True):
        return (family, size, "bold")
    return (family, size)


def apply_style(root: tk.Misc, prefs: Mapping[str, Any] | None = None) -> dict[str, str]:
    merged = merge_ui_prefs(prefs if prefs is not None else load_ui_prefs())
    colors = dict(merged["colors"])
    ui_font = (str(merged["font_family"]), int(merged["font_size"]))
    heading_font = (str(merged["font_family"]), int(merged["heading_font_size"]), "bold")
    title_font = (str(merged["font_family"]), max(16, int(merged["font_size"]) + 10), "bold")
    section_font = (str(merged["font_family"]), max(11, int(merged["font_size"]) + 2), "bold")
    muted_font = (str(merged["font_family"]), max(8, int(merged["font_size"]) - 1))
    btn_font = _button_font(merged)
    pad_x = int(merged["button_padding_x"])
    pad_y = int(merged["button_padding_y"])

    style = ttk.Style(root)
    style.theme_use("clam")
    root.option_add("*Font", ui_font)
    style.configure(".", background=colors["bg"], foreground=colors["text"], font=ui_font)
    style.configure("TFrame", background=colors["bg"])
    style.configure("Panel.TFrame", background=colors["panel"])
    style.configure("Card.TFrame", background=colors["card"])
    style.configure("Header.TFrame", background=colors["panel_alt"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["text"], font=ui_font)
    style.configure("Muted.TLabel", background=colors["panel"], foreground=colors["muted"], font=muted_font)
    style.configure("Card.TLabel", background=colors["card"], foreground=colors["text"], font=ui_font)
    style.configure("CardMuted.TLabel", background=colors["card"], foreground=colors["muted"], font=muted_font)
    style.configure(
        "SectionTitle.TLabel",
        background=colors["panel"],
        foreground=colors["text"],
        font=section_font,
    )
    style.configure(
        "HeaderTitle.TLabel",
        background=colors["panel_alt"],
        foreground=colors["text"],
        font=title_font,
    )
    style.configure(
        "HeaderSub.TLabel",
        background=colors["panel_alt"],
        foreground=colors["muted"],
        font=ui_font,
    )
    style.configure(
        "SummaryValue.TLabel",
        background=colors["card"],
        foreground=colors["text"],
        font=(str(merged["font_family"]), max(14, int(merged["font_size"]) + 6), "bold"),
    )
    style.configure("Status.TLabel", background=colors["panel"], foreground=colors["muted"], padding=(14, 8))
    style.configure(
        "TButton",
        background=merged["button_bg"],
        foreground=merged["button_fg"],
        borderwidth=0,
        padding=(pad_x, pad_y),
        font=btn_font,
    )
    style.map(
        "TButton",
        background=[("active", merged["button_hover"]), ("disabled", colors["line"])],
        foreground=[("disabled", colors["muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=merged["button_accent_bg"],
        foreground=merged["button_accent_fg"],
        font=btn_font,
    )
    style.map(
        "Accent.TButton",
        background=[("active", _lighten(merged["button_accent_bg"])), ("disabled", colors["line"])],
    )
    style.configure(
        "Success.TButton",
        background=merged["button_success_bg"],
        foreground=merged["button_success_fg"],
        font=btn_font,
    )
    style.map(
        "Success.TButton",
        background=[("active", _lighten(merged["button_success_bg"])), ("disabled", "#35534a")],
    )
    style.configure(
        "Danger.TButton",
        background=merged["button_danger_bg"],
        foreground=merged["button_danger_fg"],
        font=btn_font,
    )
    style.map(
        "Danger.TButton",
        background=[("active", _lighten(merged["button_danger_bg"])), ("disabled", colors["line"])],
    )
    style.configure("TEntry", fieldbackground=colors["input"], foreground=colors["text"], insertcolor=colors["text"])
    style.configure(
        "TCombobox",
        fieldbackground=colors["input"],
        foreground=colors["text"],
        background=colors["input"],
        arrowcolor=colors["text"],
        font=ui_font,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", colors["input"])],
        foreground=[("readonly", colors["text"])],
    )
    style.configure(
        "Period.TCombobox",
        fieldbackground=colors["input"],
        foreground=colors["warning"],
        background=colors["header"],
        arrowcolor=colors["warning"],
        font=(str(merged["font_family"]), max(10, int(merged["font_size"]) + 1), "bold"),
        padding=6,
    )
    style.map(
        "Period.TCombobox",
        fieldbackground=[("readonly", colors["input"]), ("!disabled", colors["input"])],
        foreground=[("readonly", colors["warning"]), ("!disabled", colors["warning"])],
        background=[("readonly", colors["header"]), ("active", colors["accent"])],
        arrowcolor=[("readonly", colors["warning"])],
    )
    root.option_add("*TCombobox*Listbox.font", (str(merged["font_family"]), max(10, int(merged["font_size"]) + 1), "bold"))
    root.option_add("*TCombobox*Listbox.foreground", colors["warning"])
    root.option_add("*TCombobox*Listbox.background", colors["input"])
    style.configure("TNotebook", background=colors["bg"], borderwidth=0, tabmargins=(0, 6, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=colors["panel"],
        foreground=colors["muted"],
        padding=(18, 10),
        font=(str(merged["font_family"]), int(merged["font_size"]), "bold"),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", colors["header"]), ("active", colors["card"])],
        foreground=[("selected", colors["text"])],
    )
    style.configure(
        "Treeview",
        background=colors["panel"],
        fieldbackground=colors["panel"],
        foreground=colors["text"],
        rowheight=max(24, int(merged["font_size"]) * 2 + 8),
        bordercolor=colors["line"],
        font=ui_font,
    )
    style.configure(
        "Treeview.Heading",
        background=colors["header"],
        foreground=colors["text"],
        font=heading_font,
        padding=(8, 8),
    )
    style.map("Treeview", background=[("selected", colors["accent"])], foreground=[("selected", "#ffffff")])
    style.configure("TCheckbutton", background=colors["panel"], foreground=colors["text"], font=ui_font)
    style.map("TCheckbutton", background=[("active", colors["panel"])])
    style.configure("Card.TCheckbutton", background=colors["card"], foreground=colors["text"])
    style.map("Card.TCheckbutton", background=[("active", colors["card"])])
    style.configure("Filter.TCheckbutton", background=colors["panel"], foreground=colors["text"])
    style.configure("TRadiobutton", background=colors["panel"], foreground=colors["text"], font=ui_font)
    style.map("TRadiobutton", background=[("active", colors["panel"])])
    style.configure("TLabelframe", background=colors["panel"], foreground=colors["text"])
    style.configure("TLabelframe.Label", background=colors["panel"], foreground=colors["muted"])
    style.configure("TPanedwindow", background=colors["bg"])
    style.configure("TSpinbox", fieldbackground=colors["input"], foreground=colors["text"], background=colors["input"])
    style.configure("Horizontal.TScale", background=colors["panel"])
    return colors


def _lighten(hex_color: str, amount: int = 28) -> str:
    color = normalize_hex(hex_color, "#4f8cff")
    red = min(255, int(color[1:3], 16) + amount)
    green = min(255, int(color[3:5], 16) + amount)
    blue = min(255, int(color[5:7], 16) + amount)
    return f"#{red:02X}{green:02X}{blue:02X}"


def remap_tk_colors(root: tk.Misc, old_colors: Mapping[str, str], new_colors: Mapping[str, str]) -> None:
    """Posodobi obstoječe tk.Frame/Label barve, ko se tema spremeni v živo."""
    mapping = {
        str(value).strip().lower(): new_colors[key]
        for key, value in old_colors.items()
        if key in new_colors and str(value).strip()
    }
    options = (
        "bg",
        "background",
        "fg",
        "foreground",
        "insertbackground",
        "highlightbackground",
        "selectbackground",
        "selectforeground",
        "activebackground",
        "activeforeground",
        "buttonbackground",
        "troughcolor",
    )

    def walk(widget: tk.Misc) -> None:
        for option in options:
            try:
                current = str(widget.cget(option) or "").strip().lower()
            except tk.TclError:
                continue
            replacement = mapping.get(current)
            if not replacement:
                continue
            try:
                widget.configure(**{option: replacement})
            except tk.TclError:
                pass
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            walk(child)

    walk(root)


def apply_tk_font_family(root: tk.Misc, family: str) -> None:
    family = str(family or "Segoe UI").strip() or "Segoe UI"
    tk_classes = {
        "Label", "Button", "Entry", "Text", "Checkbutton", "Radiobutton",
        "Listbox", "Spinbox", "Scale", "LabelFrame", "Message",
    }

    def walk(widget: tk.Misc) -> None:
        try:
            cls = str(widget.winfo_class() or "")
        except tk.TclError:
            cls = ""
        spec = None
        if cls in tk_classes:
            try:
                spec = widget.cget("font")
            except tk.TclError:
                spec = None
        if spec:
            try:
                font = tkfont.Font(font=spec)
                widget.configure(
                    font=(
                        family,
                        font.actual("size"),
                        font.actual("weight"),
                        font.actual("slant"),
                    )
                )
            except (tk.TclError, ValueError):
                pass
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            walk(child)

    walk(root)


def apply_ui_prefs_to_root(
    root: tk.Misc,
    prefs: Mapping[str, Any] | None = None,
    *,
    previous_colors: Mapping[str, str] | None = None,
) -> dict[str, str]:
    merged = merge_ui_prefs(prefs)
    colors = apply_style(root, merged)
    try:
        root.configure(bg=colors["bg"])
    except tk.TclError:
        pass
    if previous_colors:
        remap_tk_colors(root, previous_colors, colors)
    apply_tk_font_family(root, str(merged.get("font_family") or "Segoe UI"))
    return colors
