"""Nastavitve videza: gumbi, ozadja, pisave."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, ttk
from typing import Any, Callable, Mapping

from trops_studio.ui.styles import (
    DEFAULT_COLORS,
    default_ui_prefs,
    merge_ui_prefs,
    normalize_hex,
)
from trops_studio.ui.tooltip import ToolTip

COLOR_FIELDS: tuple[tuple[str, str], ...] = (
    ("bg", "Ozadje okna"),
    ("panel", "Paneli / tabele"),
    ("panel_alt", "Glava"),
    ("card", "Kartice"),
    ("header", "Trakovi / heading"),
    ("text", "Besedilo"),
    ("muted", "Utišano besedilo"),
    ("input", "Polja (vnos)"),
    ("line", "Črte / disabled"),
    ("accent", "Poudarek"),
    ("purple", "Vijolična"),
    ("success", "Uspeh"),
    ("warning", "Opozorilo"),
    ("danger", "Nevarno"),
)

BUTTON_FIELDS: tuple[tuple[str, str], ...] = (
    ("button_bg", "Gumb ozadje"),
    ("button_fg", "Gumb pisava"),
    ("button_hover", "Gumb hover"),
    ("button_accent_bg", "Poudarek ozadje"),
    ("button_accent_fg", "Poudarek pisava"),
    ("button_success_bg", "Uspeh ozadje"),
    ("button_success_fg", "Uspeh pisava"),
    ("button_danger_bg", "Nevarno ozadje"),
    ("button_danger_fg", "Nevarno pisava"),
)


class UiPrefsDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        prefs: Mapping[str, Any] | None = None,
        *,
        on_apply: Callable[[dict[str, Any], bool], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.on_apply = on_apply
        self.title("Videz — gumbi, barve, pisave")
        self.transient(master)
        self.geometry("720x640")
        self.minsize(640, 520)
        self.prefs = merge_ui_prefs(prefs)
        self._vars: dict[str, tk.Variable] = {}
        self._swatches: dict[str, tk.Label] = {}

        hint = ttk.Frame(self, padding=(12, 12, 12, 6))
        hint.pack(fill="x")
        ttk.Label(
            hint,
            text="Spremeni barve gumbov, ozadij in pisav. Uporabi = takoj v oknu; Shrani = ostane ob naslednjem zagonu.",
            style="Muted.TLabel",
            wraplength=680,
        ).pack(anchor="w")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        nb.add(self._build_buttons_tab(nb), text="  Gumbi  ")
        nb.add(self._build_colors_tab(nb), text="  Ozadja / barve  ")
        nb.add(self._build_fonts_tab(nb), text="  Pisave  ")

        bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="Ponastavi privzeto", command=self._reset).pack(side="left")
        ttk.Button(bar, text="Zapri", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Shrani", style="Accent.TButton", command=lambda: self._emit(persist=True)).pack(
            side="right", padx=(0, 8)
        )
        ttk.Button(bar, text="Uporabi", command=lambda: self._emit(persist=False)).pack(side="right", padx=(0, 8))

    def _color_var(self, key: str, value: str) -> tk.StringVar:
        var = tk.StringVar(value=normalize_hex(value, "#000000"))
        self._vars[key] = var
        return var

    def _add_color_row(self, parent: tk.Misc, key: str, label: str, value: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=22).pack(side="left")
        var = self._color_var(key, value)
        entry = ttk.Entry(row, textvariable=var, width=10)
        entry.pack(side="left", padx=(6, 6))
        swatch = tk.Label(
            row,
            width=4,
            bg=normalize_hex(value, "#20345d"),
            relief="ridge",
            cursor="hand2",
        )
        swatch.pack(side="left")
        self._swatches[key] = swatch
        var.trace_add("write", lambda *_a, k=key: self._sync_swatch(k))
        swatch.bind("<Button-1>", lambda _e, k=key: self._pick(k))
        ToolTip(swatch, "Klikni za izbiro barve.")
        ttk.Button(row, text="…", width=3, command=lambda k=key: self._pick(k)).pack(side="left", padx=(6, 0))

    def _sync_swatch(self, key: str) -> None:
        swatch = self._swatches.get(key)
        var = self._vars.get(key)
        if swatch is None or var is None:
            return
        color = normalize_hex(var.get(), "")
        if color:
            try:
                swatch.configure(bg=color)
            except tk.TclError:
                pass

    def _pick(self, key: str) -> None:
        var = self._vars.get(key)
        if var is None:
            return
        current = normalize_hex(var.get(), "#20345D")
        picked = colorchooser.askcolor(color=current, title="Izberi barvo", parent=self)
        if not picked or not picked[1]:
            return
        var.set(normalize_hex(picked[1], current))
        self._sync_swatch(key)
        self._emit(persist=False)

    def _build_buttons_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        ttk.Label(tab, text="Barve gumbov (navadni, poudarek, uspeh, nevarno)", style="SectionTitle.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        for key, label in BUTTON_FIELDS:
            self._add_color_row(tab, key, label, str(self.prefs.get(key) or ""))
        pad = ttk.Frame(tab)
        pad.pack(fill="x", pady=(12, 0))
        ttk.Label(pad, text="Odmik (padding)", width=22).pack(side="left")
        self._vars["button_padding_x"] = tk.IntVar(value=int(self.prefs.get("button_padding_x") or 12))
        self._vars["button_padding_y"] = tk.IntVar(value=int(self.prefs.get("button_padding_y") or 8))
        ttk.Label(pad, text="X").pack(side="left", padx=(6, 4))
        ttk.Spinbox(pad, from_=4, to=24, width=4, textvariable=self._vars["button_padding_x"]).pack(side="left")
        ttk.Label(pad, text="Y").pack(side="left", padx=(10, 4))
        ttk.Spinbox(pad, from_=2, to=18, width=4, textvariable=self._vars["button_padding_y"]).pack(side="left")
        preview = ttk.Frame(tab, padding=(0, 16, 0, 0))
        preview.pack(fill="x")
        ttk.Label(preview, text="Predogled", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(preview)
        row.pack(anchor="w")
        ttk.Button(row, text="Navaden").pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Poudarek", style="Accent.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Uspeh", style="Success.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Izbriši", style="Danger.TButton").pack(side="left")
        return tab

    def _build_colors_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        canvas = tk.Canvas(tab, highlightthickness=0, bg=DEFAULT_COLORS["bg"])
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        ttk.Label(inner, text="Ozadja in barve vmesnika", style="SectionTitle.TLabel").pack(anchor="w", pady=(0, 8))
        colors = self.prefs.get("colors") if isinstance(self.prefs.get("colors"), dict) else DEFAULT_COLORS
        for key, label in COLOR_FIELDS:
            self._add_color_row(inner, f"color:{key}", label, str(colors.get(key) or DEFAULT_COLORS[key]))
        return tab

    def _build_fonts_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        families = sorted({str(name) for name in tkfont.families() if str(name).strip()}, key=str.casefold)
        preferred = ["Segoe UI", "Segoe UI Semibold", "Calibri", "Arial", "Tahoma", "Verdana", "Consolas"]
        ordered = [name for name in preferred if name in families] + [n for n in families if n not in preferred]

        ttk.Label(tab, text="Pisava vmesnika", style="SectionTitle.TLabel").pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 12))
        self._vars["font_family"] = tk.StringVar(value=str(self.prefs.get("font_family") or "Segoe UI"))
        combo = ttk.Combobox(row, textvariable=self._vars["font_family"], values=ordered, width=28)
        combo.pack(side="left")
        ttk.Label(row, text="Velikost").pack(side="left", padx=(12, 4))
        self._vars["font_size"] = tk.IntVar(value=int(self.prefs.get("font_size") or 10))
        ttk.Spinbox(row, from_=8, to=18, width=4, textvariable=self._vars["font_size"]).pack(side="left")
        ttk.Label(row, text="Heading").pack(side="left", padx=(12, 4))
        self._vars["heading_font_size"] = tk.IntVar(value=int(self.prefs.get("heading_font_size") or 9))
        ttk.Spinbox(row, from_=8, to=16, width=4, textvariable=self._vars["heading_font_size"]).pack(side="left")

        ttk.Label(tab, text="Pisava gumbov", style="SectionTitle.TLabel").pack(anchor="w", pady=(8, 0))
        brow = ttk.Frame(tab)
        brow.pack(fill="x", pady=(6, 8))
        self._vars["button_font_family"] = tk.StringVar(
            value=str(self.prefs.get("button_font_family") or "Segoe UI Semibold")
        )
        ttk.Combobox(brow, textvariable=self._vars["button_font_family"], values=ordered, width=28).pack(side="left")
        ttk.Label(brow, text="Velikost").pack(side="left", padx=(12, 4))
        self._vars["button_font_size"] = tk.IntVar(value=int(self.prefs.get("button_font_size") or 10))
        ttk.Spinbox(brow, from_=8, to=18, width=4, textvariable=self._vars["button_font_size"]).pack(side="left")
        self._vars["button_bold"] = tk.BooleanVar(value=bool(self.prefs.get("button_bold", True)))
        ttk.Checkbutton(brow, text="Krepko", variable=self._vars["button_bold"]).pack(side="left", padx=(12, 0))

        ttk.Label(
            tab,
            text="Predogled: sprememba pisave se vidi na gumbu Uporabi in v glavnem oknu.",
            style="Muted.TLabel",
            wraplength=640,
        ).pack(anchor="w", pady=(16, 0))
        return tab

    def _collect(self) -> dict[str, Any]:
        data = default_ui_prefs()
        colors = dict(DEFAULT_COLORS)
        for key in DEFAULT_COLORS:
            var = self._vars.get(f"color:{key}")
            if var is not None:
                colors[key] = normalize_hex(var.get(), DEFAULT_COLORS[key])
        data["colors"] = colors
        for key in (
            "button_bg",
            "button_fg",
            "button_hover",
            "button_accent_bg",
            "button_accent_fg",
            "button_success_bg",
            "button_success_fg",
            "button_danger_bg",
            "button_danger_fg",
            "font_family",
            "button_font_family",
        ):
            var = self._vars.get(key)
            if var is not None:
                data[key] = var.get()
        for key in (
            "font_size",
            "heading_font_size",
            "button_font_size",
            "button_padding_x",
            "button_padding_y",
        ):
            var = self._vars.get(key)
            if var is not None:
                try:
                    data[key] = int(var.get())
                except (TypeError, ValueError, tk.TclError):
                    pass
        bold = self._vars.get("button_bold")
        if bold is not None:
            data["button_bold"] = bool(bold.get())
        return merge_ui_prefs(data)

    def _reset(self) -> None:
        self.prefs = default_ui_prefs()
        for key, default in DEFAULT_COLORS.items():
            var = self._vars.get(f"color:{key}")
            if var is not None:
                var.set(default)
        for key in (
            "button_bg",
            "button_fg",
            "button_hover",
            "button_accent_bg",
            "button_accent_fg",
            "button_success_bg",
            "button_success_fg",
            "button_danger_bg",
            "button_danger_fg",
        ):
            var = self._vars.get(key)
            if var is not None:
                var.set(str(self.prefs.get(key)))
        self._vars["font_family"].set(str(self.prefs["font_family"]))
        self._vars["button_font_family"].set(str(self.prefs["button_font_family"]))
        self._vars["font_size"].set(int(self.prefs["font_size"]))
        self._vars["heading_font_size"].set(int(self.prefs["heading_font_size"]))
        self._vars["button_font_size"].set(int(self.prefs["button_font_size"]))
        self._vars["button_padding_x"].set(int(self.prefs["button_padding_x"]))
        self._vars["button_padding_y"].set(int(self.prefs["button_padding_y"]))
        self._vars["button_bold"].set(bool(self.prefs["button_bold"]))
        self._emit(persist=False)

    def _emit(self, *, persist: bool) -> None:
        self.prefs = self._collect()
        if self.on_apply:
            self.on_apply(self.prefs, persist)
