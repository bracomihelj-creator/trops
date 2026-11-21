"""Knjige IR/PR — enako kot KirKpr: vir/povzetek, chk stolpcev, Skupaj Σ, DDV-O oznake."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from typing import Any, Callable, Mapping, Sequence

from trops_studio.ddvo_calc import ir_row_to_kir, pr_access_info, pr_row_to_kpr
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path
from trops_studio.money import money_text
from trops_studio.ui.collapsible import CollapsibleSection
from trops_studio.ui.pill import pill
from trops_studio.ui.search import haystack_matches, search_tokens
from trops_studio.ui.tooltip import ToolTip

ZERO = Decimal("0.00")


def _ddvo_codes(book: str, column: str) -> tuple[str, ...]:
    field = column.upper() if column.startswith("p") else ""
    if not field.startswith("P"):
        return ()
    try:
        ensure_kirkpr_on_path()
        from kirkpr_minimax_core import ddvo_codes_for_field  # type: ignore

        return tuple(ddvo_codes_for_field(book, field))
    except Exception:
        return ()


def _with_ddvo(book: str, headings: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col, text in headings.items():
        codes = _ddvo_codes(book, col)
        out[col] = f"{text} →{'+'.join(codes)}" if codes else text
    return out


def _ir_spec() -> tuple[tuple[str, ...], dict[str, str], dict[str, int]]:
    columns = (
        "zapst", "obdobje", "p2", "p3", "p4", "p5", "p6ds", "p6",
        "p7", "p8", "p9", "p10", "p11", "p12", "p13",
        "p14", "p15", "p16", "p17", "p18", "p19", "p20", "p21", "p22",
        "p23", "p24", "p25", "p26", "p27",
    )
    headings = {
        "zapst": "1 ZŠT", "obdobje": "2 Obdobje", "p2": "3 Dat knj", "p3": "4 Listina",
        "p4": "Dat list", "p5": "Kupec", "p6ds": "ID za DDV", "p6": "Drž",
        "p7": "7 Vred brez DDV", "p8": "8 Samoobd", "p9": "9 Oprošč",
        "p10": "10 EU blago", "p11": "11 EU stor", "p12": "12 Prod dalj", "p13": "13 Montaža",
        "p14": "14 DDV 22%", "p15": "15 DDV 9,5%", "p16": "16 DDV 5%",
        "p17": "17 EU DDV 22%", "p18": "18 EU stor 22%", "p19": "19 EU DDV 9,5%",
        "p20": "20 EU stor 9,5%", "p21": "21 EU DDV 5%", "p22": "22 EU stor 5%",
        "p23": "23 Samoobd 22%", "p24": "24 Samoobd 9,5%", "p25": "25 Samoobd 5%",
        "p26": "26 Uvoz DDV", "p27": "27 Neobdavč",
    }
    widths = {
        "zapst": 55, "obdobje": 80, "p2": 90, "p3": 140, "p4": 90, "p5": 180,
        "p6ds": 105, "p6": 40, "p7": 110, "p8": 95, "p9": 95, "p10": 100, "p11": 100,
        "p12": 95, "p13": 90, "p14": 100, "p15": 100, "p16": 90, "p17": 105, "p18": 105,
        "p19": 105, "p20": 105, "p21": 100, "p22": 100, "p23": 105, "p24": 105, "p25": 100,
        "p26": 100, "p27": 90,
    }
    return columns, _with_ddvo("IR", headings), widths


def _pr_spec() -> tuple[tuple[str, ...], dict[str, str], dict[str, int]]:
    columns = (
        "zapst", "obdobje", "p2", "p4", "p3", "opombe", "p5", "p6", "p7ds", "p7",
        "p8", "p9", "p10", "p11", "p12", "p13", "p14", "p15", "p16",
        "p17", "p18", "p19", "p20", "p21",
    )
    headings = {
        "zapst": "1 ZŠT", "obdobje": "2 Obdobje", "p2": "3 Dat knj", "p4": "4 Dat pr",
        "p3": "5 Listina", "opombe": "Opombe (veza)", "p5": "6 Dat list", "p6": "7 Dobavitelj",
        "p7ds": "ID za DDV",
        "p7": "Drž", "p8": "8-Vred brez DDV", "p9": "9 Samoobd", "p10": "10 Prid BL",
        "p11": "11 Prej ST", "p12": "12 Neprem", "p13": "13 OS", "p14": "14-Vred ON",
        "p15": "15 Opr nepr", "p16": "16 Opr OS", "p17": "17 Neodb DDV",
        "p18": "18 VST 22%", "p19": "19 VST 9,5%", "p20": "20 VST 5%", "p21": "21 Pavšal",
    }
    widths = {
        "zapst": 55, "obdobje": 80, "p2": 90, "p4": 90, "p3": 140, "opombe": 100, "p5": 90, "p6": 190,
        "p7ds": 105, "p7": 40, "p8": 110, "p9": 95, "p10": 100, "p11": 100, "p12": 90,
        "p13": 85, "p14": 110, "p15": 95, "p16": 90, "p17": 100, "p18": 100, "p19": 100,
        "p20": 95, "p21": 90,
    }
    return columns, _with_ddvo("PR", headings), widths


def _money_columns(book: str) -> tuple[str, ...]:
    if book == "IR":
        return tuple(f"p{i}" for i in range(7, 28))
    return tuple(f"p{i}" for i in range(8, 22))


def _format_obdobje(raw: str, filter_from: Any = None, filter_to: Any = None) -> str:
    if filter_from and filter_to and getattr(filter_from, "month", None) != getattr(filter_to, "month", None):
        if getattr(filter_from, "day", 1) == 1:
            return f"{filter_from.month:02d}-{filter_to.month:02d}.{str(filter_from.year)[-2:]}"
    text = str(raw or "").strip()
    if len(text) == 4 and text.isdigit():
        return f"{int(text[:2]):02d}.{text[2:]}"
    return text


def _fmt_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-":
        return f"{text[8:10]}.{text[5:7]}.{text[:4]}"
    return text


def _cell(row: Mapping[str, Any], column: str, *, book: str, filter_from=None, filter_to=None) -> str:
    if column == "zapst":
        return str(row.get("ZAPST") or "")
    if column == "obdobje":
        return _format_obdobje(str(row.get("OBDOBJE") or ""), filter_from, filter_to)
    field = column.upper()
    if column in _money_columns(book):
        return money_text(row.get(field))
    if field in {"P2", "P4", "P5"}:
        return _fmt_date(row.get(field))
    return str(row.get(field) or "")


class KnjigePanel:
    """KirKpr-style: Knjige — vir/povzetek + Knjiga IR/PR z chk in Skupaj."""

    def __init__(
        self,
        parent: ttk.Frame,
        *,
        colors: Mapping[str, str],
        pack_search: Callable[..., None],
    ) -> None:
        self.colors = dict(colors)
        self.pack_search = pack_search
        self.ir_search_var = tk.StringVar(value="")
        self.pr_search_var = tk.StringVar(value="")
        self.view_var = tk.StringVar(value="Predogled: SQLite (Projest)")
        self.summary_var = tk.StringVar(value="Najprej uvozi IR/PR — potem se izračunajo sumarni zneski.")
        self.ddvo_status_var = tk.StringVar(value="DDV-O — ni izračuna")
        self.column_vars: dict[str, dict[str, tk.BooleanVar]] = {"IR": {}, "PR": {}}
        self.totals_amounts: dict[str, dict[str, Decimal]] = {"IR": {}, "PR": {}}
        self.totals_headings: dict[str, dict[str, str]] = {"IR": {}, "PR": {}}
        self.totals_inner: dict[str, tk.Misc | None] = {"IR": None, "PR": None}
        self.info_inner: dict[str, tk.Misc | None] = {"IR": None, "PR": None}
        self.trees: dict[str, ttk.Treeview | None] = {"IR": None, "PR": None}
        self.visible_counts = {"IR": 0, "PR": 0}
        self._filter_from = None
        self._filter_to = None
        self._ir_source: list[dict[str, Any]] = []
        self._pr_source: list[dict[str, Any]] = []
        self._pr_sqlite: list[Mapping[str, Any]] = []
        self._pr_info: dict[str, Any] = {}

        panel_bg = self.colors.get("panel", "#101a2f")
        tools_sec = CollapsibleSection(
            parent, "Knjige — vir / povzetek",
            bg=panel_bg, muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True, padx=8, pady=6,
            accent=self.colors.get("purple", "#6b4cff"),
        )
        tools_sec.pack(fill="x", pady=(0, 6))
        tools = tools_sec.body

        head = tk.Frame(tools, bg=panel_bg)
        head.pack(fill="x")
        left = tk.Frame(head, bg=panel_bg)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="Knjige IR / PR", bg=panel_bg, fg=self.colors.get("text", "#f3f6ff"), font=("Segoe UI", 11, "bold"), anchor="w").pack(anchor="w")
        tk.Label(left, textvariable=self.view_var, bg=panel_bg, fg=self.colors.get("muted", "#a5b0c8"), font=("Segoe UI", 9), anchor="w").pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(head, bg=panel_bg)
        actions.pack(side="right")
        self.btn_sqlite = pill(actions, "SQLite", lambda: self._set_view("sqlite"), kind="grey")
        self.btn_sqlite.pack(side="left")
        self.btn_sqlite.set_active(True)
        ToolTip(self.btn_sqlite, "Knjige iz Projest SQLite (uvoženi Excel/Vasco).")

        tk.Label(
            tools, textvariable=self.summary_var,
            bg=panel_bg, fg=self.colors.get("muted", "#a5b0c8"),
            font=("Segoe UI", 9), wraplength=1100, justify="left", anchor="w",
        ).pack(anchor="w", fill="x", pady=(8, 0))
        self.ddvo_badge = tk.Label(
            tools, textvariable=self.ddvo_status_var,
            bg="#1d3a2a", fg="#c8f7d4",
            font=("Segoe UI Semibold", 9), padx=10, pady=4, anchor="w",
        )
        self.ddvo_badge.pack(anchor="w", pady=(6, 0))

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True)
        self.ir_frame = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(6, 6))
        self.pr_frame = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(6, 6))
        self.notebook.add(self.ir_frame, text="  Knjiga IR  ")
        self.notebook.add(self.pr_frame, text="  Knjiga PR  ")
        self._rebuild("IR")
        self._rebuild("PR")

    def tab_title(self) -> str:
        return f"  Knjige IR {self.visible_counts['IR']} / PR {self.visible_counts['PR']}  "

    def select_book(self, book: str) -> None:
        self.notebook.select(0 if book.upper() == "IR" else 1)

    def set_ddvo_status(self, text: str, *, ok: bool | None = None) -> None:
        self.ddvo_status_var.set(text)
        if ok is True:
            self.ddvo_badge.configure(bg="#1d3a2a", fg="#c8f7d4")
        elif ok is False:
            self.ddvo_badge.configure(bg="#5b3717", fg="#fff0c7")
        else:
            self.ddvo_badge.configure(bg="#20345d", fg="#a5b0c8")

    def _set_view(self, mode: str) -> None:
        self.view_var.set("Predogled: SQLite (Projest)")
        self.btn_sqlite.set_active(True)

    def refresh(
        self,
        ir_rows: Sequence[Mapping[str, Any]],
        pr_rows: Sequence[Mapping[str, Any]],
        *,
        filter_from=None,
        filter_to=None,
    ) -> None:
        self._filter_from = filter_from
        self._filter_to = filter_to
        self._ir_source = [ir_row_to_kir(row) for row in ir_rows]
        self._pr_sqlite = list(pr_rows)
        self._pr_source = [pr_row_to_kpr(row) for row in pr_rows]
        self._populate("IR")
        self._populate("PR")
        period = ""
        if filter_from and filter_to:
            period = f"{filter_from.isoformat()} – {filter_to.isoformat()}: "
        excl = self._pr_info.get("info_excluded") or ZERO
        neo = self._pr_info.get("info_neodbitni") or ZERO
        self.summary_var.set(
            f"{period}SQLite knjiga FURS: IR {self.visible_counts['IR']}, PR {self.visible_counts['PR']}. "
            f"INFO: Ne gre v knjigo {money_text(excl)} • Neodbitni {money_text(neo)}."
        )

    def _rebuild(self, book: str) -> None:
        frame = self.ir_frame if book == "IR" else self.pr_frame
        for child in frame.winfo_children():
            child.destroy()
        columns, headings, widths = _ir_spec() if book == "IR" else _pr_spec()

        top = ttk.Frame(frame, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 6))
        title = "Knjiga izdanih računov (FURS KIR / SQLite)" if book == "IR" else "Knjiga prejetih računov (FURS KPR / SQLite)"
        ttk.Label(top, text=title, style="SectionTitle.TLabel").pack(side="left")
        search_var = self.ir_search_var if book == "IR" else self.pr_search_var
        self.pack_search(
            top, search_var,
            on_change=lambda b=book: self._populate(b),
            clear_command=lambda b=book: self._clear_search(b),
            tip=f"Išči knjigo {book}: listina, partner, znesek, DDV …",
        )

        self._build_column_checks(frame, book, columns, headings)
        self._build_totals_bar(frame, book, columns, headings)

        tree_frame = ttk.Frame(frame, style="Panel.TFrame")
        tree_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        ybar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        money = set(_money_columns(book))
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths.get(col, 90), minwidth=40, anchor="e" if col in money else "w")
        tree.tag_configure("odd", background="#101c31")
        self.trees[book] = tree
        self._apply_displaycolumns(book)

    def _clear_search(self, book: str) -> None:
        (self.ir_search_var if book == "IR" else self.pr_search_var).set("")
        self._populate(book)

    def _build_column_checks(
        self,
        parent: ttk.Frame,
        book: str,
        columns: tuple[str, ...],
        headings: dict[str, str],
    ) -> None:
        panel_bg = self.colors.get("panel", "#101a2f")
        sec = CollapsibleSection(
            parent, "Stolpci",
            bg=panel_bg, muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True, padx=6, pady=4,
            accent=self.colors.get("header", "#20345d"),
        )
        sec.pack(fill="x", pady=(0, 4))
        wrap = sec.body
        tools = tk.Frame(wrap, bg=panel_bg)
        tools.pack(fill="x")
        tk.Label(tools, text="Stolpci:", bg=panel_bg, fg=self.colors.get("muted", "#a5b0c8"), font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        host = tk.Frame(tools, bg=panel_bg)
        host.pack(side="left")
        btn_all = pill(host, "Vse označi", lambda: self._set_all_columns(book, True), kind="grey")
        btn_all.pack(side="left", padx=(0, 4))
        btn_none = pill(host, "Vse odznači", lambda: self._set_all_columns(book, False), kind="grey")
        btn_none.pack(side="left", padx=(0, 4))
        pill(host, "Neničelni", lambda: self._hide_zero_columns(book), kind="blue").pack(side="left", padx=(0, 4))
        pill(host, "Zneski", lambda: self._money_columns_only(book), kind="grey").pack(side="left", padx=(0, 4))
        ToolTip(btn_all, "Označi vse stolpce (prikaži vse).")
        ToolTip(btn_none, "Odznači vse stolpce (skrij vse).")
        ToolTip(host, "Vse označi / odznači = chk. Neničelni = skrij stolpce z 0,00. Zneski = identiteta + zneskovni.")

        scroll_row = tk.Frame(wrap, bg=panel_bg)
        scroll_row.pack(fill="x", pady=(4, 0))
        canvas = tk.Canvas(scroll_row, height=32, highlightthickness=0, bg=panel_bg)
        hbar = ttk.Scrollbar(scroll_row, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hbar.set)
        canvas.pack(side="top", fill="x", expand=True)
        hbar.pack(side="bottom", fill="x")
        inner = ttk.Frame(canvas, style="Panel.TFrame")
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, height=inner.winfo_reqheight())

        inner.bind("<Configure>", _sync)

        prev = self.column_vars.get(book) or {}
        vars_map: dict[str, tk.BooleanVar] = {}
        for column in columns:
            old = prev.get(column)
            var = tk.BooleanVar(value=bool(old.get()) if old is not None else True)
            vars_map[column] = var
            full = headings[column]
            if " →" in full:
                base, _, ddvo = full.partition(" →")
                short = (base[:13] + "…" if len(base) > 14 else base) + f" →{ddvo}"
            else:
                short = full if len(full) <= 18 else full[:16] + "…"
            tip = f"Stolpec: {full}"
            codes = _ddvo_codes(book, column)
            if codes:
                tip += f"\nDDV-O obrazec: polje {'+'.join(codes)}"
            chk = ttk.Checkbutton(
                inner, text=short, variable=var,
                command=lambda b=book: self._apply_displaycolumns(b),
            )
            chk.pack(side="left", padx=(0, 8))
            ToolTip(chk, tip)
        self.column_vars[book] = vars_map

    def _build_totals_bar(
        self,
        parent: ttk.Frame,
        book: str,
        columns: tuple[str, ...],
        headings: dict[str, str],
    ) -> None:
        card_bg = "#1e2d4a"
        title = "Skupaj" if book == "IR" else "Skupaj + INFO (Access)"
        sec = CollapsibleSection(
            parent, title,
            bg=card_bg, muted="#9eb0d0",
            initially_open=True, padx=8, pady=6,
            accent="#6b4cff",
        )
        sec.pack(fill="x", pady=(0, 6))
        bar = sec.body
        # Ena vrstica: Skupaj levo, INFO (Access) desno — manj višine.
        row = tk.Frame(bar, bg=card_bg)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=card_bg)
        inner.pack(side="left", fill="both", expand=True, anchor="nw")
        self.totals_inner[book] = inner
        self.totals_amounts[book] = {}
        self.totals_headings[book] = {col: headings[col] for col in columns if col in _money_columns(book)}
        tk.Label(inner, text="(ni zneskov — uvozi podatke / osveži)", bg=card_bg, fg="#9eb0d0", font=("Segoe UI", 9)).pack(side="left")
        if book == "PR":
            info_wrap = tk.Frame(row, bg=card_bg)
            info_wrap.pack(side="right", anchor="n", padx=(12, 0))
            tk.Label(
                info_wrap,
                text="INFO",
                bg=card_bg, fg="#9eb0d0", font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(0, 6), pady=(6, 0))
            info = tk.Frame(info_wrap, bg=card_bg)
            info.pack(side="left", anchor="n")
            self.info_inner[book] = info
            tk.Label(info, text="(INFO)", bg=card_bg, fg="#9eb0d0", font=("Segoe UI", 9)).pack(side="left")
        else:
            self.info_inner[book] = None

    def _set_all_columns(self, book: str, value: bool) -> None:
        for var in (self.column_vars.get(book) or {}).values():
            var.set(value)
        self._apply_displaycolumns(book)

    def _money_columns_only(self, book: str) -> None:
        money = set(_money_columns(book))
        identity = {"zapst", "obdobje", "p2", "p3", "p4", "p5", "p6", "p6ds", "p7", "p7ds", "opombe"}
        for col, var in (self.column_vars.get(book) or {}).items():
            var.set(col in identity or col in money)
        self._apply_displaycolumns(book)

    def _hide_zero_columns(self, book: str) -> None:
        money = set(_money_columns(book))
        amounts = self.totals_amounts.get(book) or {}
        identity = {"zapst", "obdobje", "p2", "p3", "p4", "p5", "p6", "p6ds", "p7", "p7ds", "opombe"}
        for col, var in (self.column_vars.get(book) or {}).items():
            if col in identity:
                var.set(True)
            elif col in money:
                var.set(Decimal(str(amounts.get(col, 0) or 0)) != 0)
            else:
                var.set(True)
        self._apply_displaycolumns(book)

    def _apply_displaycolumns(self, book: str) -> None:
        tree = self.trees.get(book)
        if tree is None:
            return
        vars_map = self.column_vars.get(book) or {}
        all_cols = list(tree["columns"])
        visible = [c for c in all_cols if vars_map.get(c) is None or bool(vars_map[c].get())]
        if not visible and all_cols:
            visible = [all_cols[0]]
            if visible[0] in vars_map:
                vars_map[visible[0]].set(True)
        tree.configure(displaycolumns=visible)
        self._render_totals_chips(book)

    def _render_totals_chips(self, book: str) -> None:
        inner = self.totals_inner.get(book)
        if inner is None:
            return
        card_bg = "#1e2d4a"
        chip_bg = "#2a3f66"
        for child in inner.winfo_children():
            child.destroy()
        vars_map = self.column_vars.get(book) or {}
        amounts = self.totals_amounts.get(book) or {}
        headings = self.totals_headings.get(book) or {}
        chips: list[tuple[str, Decimal, str]] = []
        for column in _money_columns(book):
            if vars_map.get(column) is not None and not bool(vars_map[column].get()):
                continue
            amount = amounts.get(column, ZERO)
            if not amount:
                continue
            chips.append((column, amount, headings.get(column, column.upper())))
        if not chips:
            tk.Label(
                inner, text="Skupaj: 0,00 (ni neničelnih zneskov v vklopljenih stolpcih)",
                bg=card_bg, fg="#9eb0d0", font=("Segoe UI", 9),
            ).pack(side="left")
        else:
            for start in range(0, len(chips), 6):
                row_frame = tk.Frame(inner, bg=card_bg)
                row_frame.pack(fill="x", anchor="w", pady=(0, 2))
                for _column, amount, title in chips[start : start + 6]:
                    chip = tk.Frame(row_frame, bg=chip_bg, padx=8, pady=4)
                    chip.pack(side="left", padx=(0, 8), pady=2)
                    tk.Label(chip, text=title, bg=chip_bg, fg="#c8d6f0", font=("Segoe UI", 8)).pack(anchor="w")
                    tk.Label(chip, text=money_text(amount), bg=chip_bg, fg="#ffe08a", font=("Segoe UI", 11, "bold")).pack(anchor="e")
        if book == "PR":
            self._render_info_chips()

    def _render_info_chips(self) -> None:
        """Access INFO čipi desno ob Skupaj PR (isto kot DDV-O INFO)."""
        host = self.info_inner.get("PR")
        if host is None:
            return
        card_bg = "#1e2d4a"
        chip_bg = "#3a3220"
        for child in host.winfo_children():
            child.destroy()
        info = self._pr_info or {}
        items: list[tuple[str, str]] = [
            ("21 (22) uvoz", money_text(info.get("info_uvoz_21_22"))),
            ("Ne gre v knjigo", money_text(info.get("info_excluded"))),
            ("26 uvoz — MRN", str(info.get("info_mrn_text") or "—")),
            ("26 uvoz — znesek", money_text(info.get("info_mrn_amount"))),
            ("17-Neodbitni DDV", money_text(info.get("info_neodbitni"))),
            ("16/35-OPR OS", money_text(info.get("info_opr_os"))),
        ]
        # Ena vrstica desno ob Skupaj.
        row_frame = tk.Frame(host, bg=card_bg)
        row_frame.pack(anchor="e")
        for title, value in items:
            chip = tk.Frame(row_frame, bg=chip_bg, padx=8, pady=4)
            chip.pack(side="left", padx=(0, 8), pady=2)
            tk.Label(chip, text=title, bg=chip_bg, fg="#e8d9a8", font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(chip, text=value, bg=chip_bg, fg="#ffe08a", font=("Segoe UI", 11, "bold")).pack(anchor="e")
            ToolTip(chip, "Samo INFO (Access) — ne vpliva na DDV-O izračun.")

    def _populate(self, book: str) -> None:
        tree = self.trees.get(book)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        rows = self._ir_source if book == "IR" else self._pr_source
        tokens = search_tokens((self.ir_search_var if book == "IR" else self.pr_search_var).get())
        columns = list(tree["columns"])
        money_cols = _money_columns(book)
        totals = {col: ZERO for col in money_cols}
        visible = 0
        matched_pr_sqlite: list[Mapping[str, Any]] = []
        for index, row in enumerate(rows):
            values = [
                _cell(row, col, book=book, filter_from=self._filter_from, filter_to=self._filter_to)
                for col in columns
            ]
            if tokens and not haystack_matches(tokens, values):
                continue
            for col in money_cols:
                totals[col] += Decimal(str(row.get(col.upper()) or 0))
            tags = ("odd",) if visible % 2 else ()
            tree.insert("", "end", iid=f"{book.lower()}:{index}", values=values, tags=tags)
            if book == "PR" and index < len(self._pr_sqlite):
                matched_pr_sqlite.append(self._pr_sqlite[index])
            visible += 1
        self.totals_amounts[book] = totals
        self.visible_counts[book] = visible
        if book == "PR":
            self._pr_info = pr_access_info(matched_pr_sqlite if matched_pr_sqlite else self._pr_sqlite)
        self._hide_zero_columns(book)
        nonzero = [f"{c.upper()}={money_text(v)}" for c, v in totals.items() if v]
        tip = ", ".join(nonzero[:12])
        if len(nonzero) > 12:
            tip += " …"
        self.notebook.tab(0 if book == "IR" else 1, text=f"  Knjiga {book}  {visible}  ")
        if tip:
            base = self.summary_var.get().split(" | Σ")[0]
            self.summary_var.set(f"{base} | Σ {book}: {tip}")
