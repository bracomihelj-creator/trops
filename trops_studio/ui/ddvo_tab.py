"""Zavihek DDV-O — sumarni kartici + tabela polj (kot KirKpr)."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

from trops_studio.companies import company_org_id
from trops_studio.ddvo_actions import (
    GMAIL_SMTP_CC,
    GMAIL_SMTP_FROM,
    client_email_to,
    create_virman_package,
    ddvo_client_mail_draft,
    export_pdf_xml,
    open_path,
    preview_pdf,
)
from trops_studio.ddvo_calc import compute_ddvo, iter_pr_vat_split_invoices
from trops_studio.edavki_links import (
    open_edavki_mrn_declarations,
)
from trops_studio.minimax_runtime import check_minimax_api
from trops_studio.money import date_text, decimal_value, money_text
from trops_studio.ui.collapsible import CollapsibleSection
from trops_studio.ui.search import haystack_matches, search_tokens
from trops_studio.ui.tooltip import ToolTip


class DdvoTab:
    def __init__(
        self,
        parent: ttk.Frame,
        *,
        colors: Mapping[str, str],
        pack_search: Callable[..., None],
        summary_card: Callable[..., None],
    ) -> None:
        self.colors = dict(colors)
        self.search_var = tk.StringVar(value="")
        self.taxpayer_var = tk.StringVar(value="Davčna številka: —")
        self.period_var = tk.StringVar(value="Obdobje: —")
        self.flags_var = tk.StringVar(value="Kontrola iz SQLite IR/PR (kot KirKpr)")
        self.output_var = tk.StringVar(value="0,00 EUR")
        self.output_detail_var = tk.StringVar(value="vsota polj 21–26")
        self.input_var = tk.StringVar(value="0,00 EUR")
        self.input_detail_var = tk.StringVar(value="vsota polj 41–43")
        self.result_var = tk.StringVar(value="0,00 EUR")
        self.result_detail_var = tk.StringVar(value="polje 51 / 52")
        self.control_var = tk.StringVar(value="Kontrolni podatek bo izračunan po uvozu IR/PR.")
        self.split_var = tk.StringVar(value="Prevalitev / domači DDV: —")
        self.amount_filter = tk.StringVar(value="NONZERO")  # VSE | NONZERO — privzeto skrij 0,00
        self.domestic_var = tk.StringVar(value="0,00 EUR")
        self.domestic_detail_var = tk.StringVar(value="SLO DDV (brez prevalitve)")
        self.prevalitev_var = tk.StringVar(value="0,00 EUR")
        self.prevalitev_detail_var = tk.StringVar(value="input = output (EU + tujci + uvoz)")
        self.info_uvoz_var = tk.StringVar(value="0,00")
        self.info_excluded_var = tk.StringVar(value="0,00")
        self.info_mrn_var = tk.StringVar(value="—")
        self.info_mrn_amt_var = tk.StringVar(value="0,00")
        self.info_neodbitni_var = tk.StringVar(value="0,00")
        self.info_opr_os_var = tk.StringVar(value="0,00")
        # Access 18/41, 19/42, 20/42a — (skupaj, prevalitev, SLO DDV)
        self.sa_18_total = tk.StringVar(value="0,00")
        self.sa_18_prev = tk.StringVar(value="0,00")
        self.sa_18_slo = tk.StringVar(value="0,00")
        self.sa_19_total = tk.StringVar(value="0,00")
        self.sa_19_prev = tk.StringVar(value="0,00")
        self.sa_19_slo = tk.StringVar(value="0,00")
        self.sa_20_total = tk.StringVar(value="0,00")
        self.sa_20_prev = tk.StringVar(value="0,00")
        self.sa_20_slo = tk.StringVar(value="0,00")
        self.sa_sum_total = tk.StringVar(value="0,00")
        self.sa_sum_prev = tk.StringVar(value="0,00")
        self.sa_sum_slo = tk.StringVar(value="0,00")
        self._fields: list[dict[str, Any]] = []
        self._ir_rows: list[Mapping[str, Any]] = []
        self._pr_rows: list[Mapping[str, Any]] = []
        self._period_from: date | None = None
        self._period_to: date | None = None
        self._company: dict[str, Any] = {}
        self._last_summary: dict[str, Any] = {}
        self._parent = parent
        self._get_company: Callable[[], Mapping[str, Any] | None] | None = None
        self._status: Callable[[str], None] | None = None
        self._open_pr: Callable[[int], None] | None = None
        self._fetch_mrn: Callable[[], None] | None = None
        self._recalc_callback: Callable[[], None] | None = None

        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 4))
        title_box = ttk.Frame(top, style="Panel.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="Kontrolni obrazec DDV-O (e-DDV_O_11.7)", style="SectionTitle.TLabel").pack(anchor="w")
        meta = ttk.Frame(title_box, style="Panel.TFrame")
        meta.pack(fill="x", pady=(3, 0))
        ttk.Label(meta, textvariable=self.taxpayer_var, style="Muted.TLabel").pack(side="left", padx=(0, 18))
        ttk.Label(meta, textvariable=self.period_var, style="Muted.TLabel").pack(side="left", padx=(0, 18))
        ttk.Label(meta, textvariable=self.flags_var, style="Muted.TLabel").pack(side="left")
        pack_search(
            top,
            self.search_var,
            on_change=self._populate_tree,
            clear_command=self.clear_search,
            tip="Išči DDV-O: polje, opis, vir, znesek …",
        )

        actions = ttk.Frame(parent, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 8))
        btn_preview = ttk.Button(actions, text="Predogled PDF", command=self._preview_pdf)
        btn_preview.pack(side="left")
        btn_export = ttk.Button(actions, text="Izvozi PDF+XML…", command=self._export_pdf_xml)
        btn_export.pack(side="left", padx=(8, 0))
        btn_virman = ttk.Button(actions, text="PDF + virman…", style="Accent.TButton", command=self._pdf_virman)
        btn_virman.pack(side="left", padx=(8, 0))
        btn_mail = ttk.Button(actions, text="E-pošta…", command=self._email_package)
        btn_mail.pack(side="left", padx=(8, 0))
        btn = ttk.Button(actions, text="Preračunaj", command=self._request_recalc)
        btn.pack(side="left", padx=(8, 0))
        btn_api = ttk.Button(actions, text="Preveri Minimax API", command=self._check_api)
        btn_api.pack(side="left", padx=(8, 0))
        btn_mrn = ttk.Button(actions, text="MRN prenesi", command=self._fetch_edavki_mrn)
        btn_mrn.pack(side="left", padx=(8, 0))
        ttk.Label(actions, text="Polja:", style="Muted.TLabel").pack(side="left", padx=(18, 8))
        for label, value in (("Vse", "VSE"), ("<> 0", "NONZERO")):
            ttk.Radiobutton(
                actions, text=label, value=value, variable=self.amount_filter,
                command=self._populate_tree,
            ).pack(side="left", padx=(0, 8))
        ToolTip(btn_preview, "Odpre DDV-O PDF (eDavki XSLT) — kot KirKpr Predogled.")
        ToolTip(btn_export, "Shrani PDF + XML v TROPS\\{Zšt}\\DDV (ali MiniMax\\DDV-O).")
        ToolTip(btn_virman, "Lokalni paket: DDV-O PDF + SEPA virman (brez Minimax prijave).")
        ToolTip(
            btn_mail,
            "Pošlje DDV-O PDF + virman prek Gmail SMTP\n"
            f"(Od: {GMAIL_SMTP_FROM}, KP: {GMAIL_SMTP_CC}).",
        )
        ToolTip(btn, "Ponovno izračuna DDV-O iz filtriranih IR/PR (SQLite).")
        ToolTip(btn_api, "Samostojen pregled Minimax API (prijava, org, konti, stranke).")
        ToolTip(
            btn_mrn,
            "eDavki: Datum od/do + Išči.\n"
            "Če so deklaracije → CSV v D:\\Trops\\{Zšt}\\DDV\\MRN\n"
            "in uvoz v DDV_Deklaracija_*.xls; primerjava s poljem 26.",
        )
        ToolTip(actions, "Vse = vsa DDV-O polja; <> 0 = skrij polja z 0,00. Polji 51/52 ostaneta.")
        self._recalc_callback: Callable[[], None] | None = None
        self._last_package_paths: list = []

        cards_sec = CollapsibleSection(
            parent, "DDV-O povzetek",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True, padx=4, pady=4,
            accent=self.colors.get("purple", "#6b4cff"),
        )
        cards_sec.pack(fill="x", pady=(0, 8))
        cards = ttk.Frame(cards_sec.body, style="Panel.TFrame")
        cards.pack(fill="x")
        cards.columnconfigure((0, 1, 2), weight=1, uniform="ddvo")
        summary_card(cards, 0, "OBRAČUNANI DDV", self.output_var, self.output_detail_var, self.colors["accent"])
        summary_card(cards, 1, "ODBITNI DDV", self.input_var, self.input_detail_var, self.colors.get("purple", "#8b7cff"))
        summary_card(cards, 2, "OBVEZNOST / PRESEŽEK", self.result_var, self.result_detail_var, self.colors["warning"])

        split_cards = ttk.Frame(cards_sec.body, style="Panel.TFrame")
        split_cards.pack(fill="x", pady=(8, 0))
        split_cards.columnconfigure((0, 1), weight=1, uniform="ddvo_split")
        card_dom = summary_card(
            split_cards, 0, "DOMAČI SLO DDV (PR)",
            self.domestic_var, self.domestic_detail_var, self.colors.get("success", "#34c77b"),
            on_click=lambda: self._show_vat_split_invoices("domestic"),
            columns=2,
        )
        card_prev = summary_card(
            split_cards, 1, "PREVALITEV (EU + tujci + uvoz)",
            self.prevalitev_var, self.prevalitev_detail_var, "#e6b84d",
            on_click=lambda: self._show_vat_split_invoices("prevalitev"),
            columns=2,
        )
        ToolTip(card_dom, "Klik → treeview PR faktur z domačim SLO DDV (brez samoobdavčitve).")
        ToolTip(
            card_prev,
            "Klik → PR s samoobdavčitvijo (Minimax 160xx/260xx).\n"
            "EU blago/storitve → DDV-O 23/23a; tujci (ne-EU) → 25; MRN uvoz → 26.\n"
            "Odbitni del gre v polje 41 (nabave + EU + uvoz), ne samo »EU«.",
        )

        self.split_label = tk.Label(
            cards_sec.body,
            textvariable=self.split_var,
            bg="#2a3560",
            fg="#ffe08a",
            anchor="w",
            padx=13,
            pady=7,
            font=("Segoe UI Semibold", 9),
            justify="left",
        )
        self.split_label.pack(fill="x", pady=(6, 0))

        self.control_label = tk.Label(
            cards_sec.body,
            textvariable=self.control_var,
            bg="#20345d",
            fg=self.colors["text"],
            anchor="w",
            padx=13,
            pady=8,
            font=("Segoe UI Semibold", 9),
        )
        self.control_label.pack(fill="x", pady=(6, 0))

        # Panel +/- : samoobdavčitve
        sa_sec = CollapsibleSection(
            parent,
            "Samoobdavčitve 1600 / 2600 — prevalitev | SLO DDV",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True,
            padx=8,
            pady=6,
            accent="#e6b84d",
        )
        sa_sec.pack(fill="x", pady=(0, 8))
        self._build_samoobdavcitev_split_panel(sa_sec.body)

        info_sec = CollapsibleSection(
            parent,
            "INFO — Uvoz (odbitni) vs MRN (samoobdavčitev → polje 26)",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=False,
            padx=8,
            pady=6,
            accent="#3a4a6a",
        )
        info_sec.pack(fill="x", pady=(0, 8))
        self._build_access_info_panel(info_sec.body)

        # Panel +/- : tabela polj
        fields_sec = CollapsibleSection(
            parent,
            "DDV-O polja (e-DDV_O)",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True,
            padx=4,
            pady=4,
            accent=self.colors.get("accent", "#4f7cff"),
        )
        fields_sec.pack(fill="both", expand=True)
        fields_sec.set_expand_body(True)

        columns = ("section", "code", "description", "source", "exact", "rounded", "diff", "status")
        headings = {
            "section": "Razdelek", "code": "Polje", "description": "Opis", "source": "Vir",
            "exact": "Točno", "rounded": "Zaokroženo", "diff": "Razlika", "status": "Status",
        }
        widths = {
            "section": 180, "code": 55, "description": 320, "source": 160,
            "exact": 100, "rounded": 100, "diff": 90, "status": 70,
        }
        frame = ttk.Frame(fields_sec.body, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(
                col,
                width=widths[col],
                minwidth=50,
                anchor="e" if col in {"exact", "rounded", "diff", "code"} else "w",
            )
        self.tree.tag_configure("odd", background="#101c31")
        self.tree.tag_configure("result", background="#2f2854", foreground="#eeeaff")

    def _build_samoobdavcitev_split_panel(self, parent: tk.Misc) -> None:
        """Access-stolpci: prevalitev | SLO DDV za 18/41, 19/42 (samoobdavčitve 1600/2600)."""
        bg = "#1a2744"
        muted = self.colors.get("muted", "#a5b0c8")
        text = self.colors.get("text", "#f3f6ff")
        accent = "#ffe08a"
        box = tk.Frame(parent, bg=bg, padx=4, pady=2)
        box.pack(fill="x")
        tk.Label(
            box,
            text="prevalitev = EU + tujci + uvoz/MRN (input=output → 41)  ·  SLO DDV = domači odbitni",
            bg=bg, fg=muted, font=("Segoe UI", 8), anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        grid = tk.Frame(box, bg=bg)
        grid.pack(fill="x")
        headers = ("", "skupaj", "prevalitev", "SLO DDV")
        for col, title in enumerate(headers):
            tk.Label(
                grid, text=title, bg="#2a3a5c", fg=accent if col else muted,
                font=("Segoe UI Semibold", 8), anchor="e" if col else "w",
                padx=8, pady=3,
            ).grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 2, 0))
            grid.columnconfigure(col, weight=1 if col else 2)

        rows = (
            ("18/41 — SPL 22% DDV", self.sa_18_total, self.sa_18_prev, self.sa_18_slo),
            ("19/42 — ZN 9,5% DDV", self.sa_19_total, self.sa_19_prev, self.sa_19_slo),
            ("20/42a — 5% DDV", self.sa_20_total, self.sa_20_prev, self.sa_20_slo),
            ("Skupaj odbitni", self.sa_sum_total, self.sa_sum_prev, self.sa_sum_slo),
        )
        for r, (label, v_tot, v_prev, v_slo) in enumerate(rows, start=1):
            row_bg = "#243456" if r % 2 else bg
            bold = r == len(rows)
            font = ("Segoe UI Semibold", 9) if bold else ("Segoe UI", 9)
            tk.Label(
                grid, text=label, bg=row_bg, fg=text, font=font, anchor="w", padx=8, pady=3,
            ).grid(row=r, column=0, sticky="nsew")
            for col, var in enumerate((v_tot, v_prev, v_slo), start=1):
                fg = "#ff8a8a" if col == 1 else text
                tk.Label(
                    grid, textvariable=var, bg=row_bg, fg=fg, font=font, anchor="e", padx=8, pady=3,
                ).grid(row=r, column=col, sticky="nsew", padx=(2, 0))
        ToolTip(
            box,
            "Minimax / knjigi IR+PR → DDV-O:\n"
            "• prevalitev — SA (160xx+260xx): EU→23/23a, tujci(ne-EU)→25, MRN→26\n"
            "• odbitni del = polje 41/42/42a (nabave + pridobitve EU + uvoz + tujci)\n"
            "• SLO DDV — domači odbitni (samo 160xx, brez SA)\n"
            "• skupaj = prevalitev + SLO DDV (= DDV-O 41 / 42 / 42a)",
        )

    def _set_samoobdavcitev_split(self, summary: Mapping[str, Any] | None = None) -> None:
        summary = summary or {}

        def _d(key: str) -> Decimal:
            try:
                return Decimal(str(summary.get(key) or 0))
            except Exception:
                return Decimal("0")

        p22, p95, p5 = _d("prevalitev_vat_22"), _d("prevalitev_vat_95"), _d("prevalitev_vat_5")
        d22, d95, d5 = _d("domestic_vat_22"), _d("domestic_vat_95"), _d("domestic_vat_5")
        self.sa_18_prev.set(money_text(p22))
        self.sa_18_slo.set(money_text(d22))
        self.sa_18_total.set(money_text(_d("access_18_41_total") or (p22 + d22)))
        self.sa_19_prev.set(money_text(p95))
        self.sa_19_slo.set(money_text(d95))
        self.sa_19_total.set(money_text(_d("access_19_42_total") or (p95 + d95)))
        self.sa_20_prev.set(money_text(p5))
        self.sa_20_slo.set(money_text(d5))
        self.sa_20_total.set(money_text(_d("access_20_42a_total") or (p5 + d5)))
        prev, slo = _d("prevalitev_input_vat"), _d("domestic_input_vat")
        self.sa_sum_prev.set(money_text(prev))
        self.sa_sum_slo.set(money_text(slo))
        self.sa_sum_total.set(money_text(prev + slo))

    def _build_access_info_panel(self, parent: tk.Misc) -> None:
        """Samo INFO — enako kot rdeči okvirji v Access knjigi PR."""
        bg = self.colors.get("panel", "#101a2f")
        muted = self.colors.get("muted", "#a5b0c8")
        text = self.colors.get("text", "#f3f6ff")
        warn = self.colors.get("warning", "#ffcc66")
        grid = tk.Frame(parent, bg=bg)
        grid.pack(fill="x")
        items = (
            (
                "Uvoz (odbitni)",
                self.info_uvoz_var,
                "Uvozni DDV se odbija, NI samoobdavčitev.\n"
                "Vasco F21+F22 + PR z opredelitvijo Uvoz.",
            ),
            (
                "Ne gre v knjigo",
                self.info_excluded_var,
                "Σ excluded — NI v DDV (KIR/KPR/DDV-O).\n"
                "Samo temeljnica (odhodek + plačilo), brez 160xx/260xx.",
            ),
            (
                "MRN kode",
                self.info_mrn_var,
                "Številke MRN iz opomb/dokumenta (eDavki oblika 26SI…).\n"
                "Gumb »MRN preveri« → eDavki seznam deklaracij.",
            ),
            (
                "26 MRN (SA)",
                self.info_mrn_amt_var,
                "Samoobdavčitev od uvoza → DDV-O polje 26.\n"
                "Σ DDV na PR z opredelitvijo MRN (ne navadni uvoz).",
            ),
            ("17-Neodbitni DDV", self.info_neodbitni_var, "Σ neodbitni 22% + 9,5%"),
            ("16/35-OPR OS", self.info_opr_os_var, "Vasco F18 (16-Vred OPR OS)"),
        )
        for col, (label, var, tip) in enumerate(items):
            cell = tk.Frame(grid, bg="#15213a", padx=8, pady=6, highlightbackground="#2a3b60", highlightthickness=1)
            cell.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0))
            grid.columnconfigure(col, weight=1, uniform="ddvo_info")
            tk.Label(cell, text=label, bg="#15213a", fg=muted, font=("Segoe UI", 8), anchor="w").pack(anchor="w")
            value_fg = warn if "MRN" in label and "znesek" not in label else text
            font = ("Segoe UI", 10, "bold") if "MRN" in label and "znesek" not in label else ("Segoe UI", 11, "bold")
            lab = tk.Label(cell, textvariable=var, bg="#15213a", fg=value_fg, font=font, anchor="e")
            lab.pack(anchor="e", fill="x")
            ToolTip(cell, tip)

    def set_recalc_callback(self, callback: Callable[[], None]) -> None:
        self._recalc_callback = callback

    def set_helpers(
        self,
        *,
        get_company: Callable[[], Mapping[str, Any] | None] | None = None,
        status: Callable[[str], None] | None = None,
        open_pr: Callable[[int], None] | None = None,
        fetch_mrn: Callable[[], None] | None = None,
    ) -> None:
        self._get_company = get_company
        self._status = status
        self._open_pr = open_pr
        self._fetch_mrn = fetch_mrn

    def _show_vat_split_invoices(self, kind: str) -> None:
        """Treeview PR faktur v DOMAČI SLO DDV ali PREVALITEV."""
        if not self._pr_rows:
            messagebox.showinfo(
                "DDV-O",
                "Ni PR vrstic v filtru obdobja.",
                parent=self._parent.winfo_toplevel(),
            )
            return
        split = iter_pr_vat_split_invoices(self._pr_rows)
        key = "prevalitev" if kind == "prevalitev" else "domestic"
        rows = list(split.get(key) or [])
        title = (
            "PREVALITEV (EU + tujci + uvoz) — SA 160xx/260xx"
            if key == "prevalitev"
            else "DOMAČI SLO DDV (PR) — brez prevalitve"
        )
        total = sum((item.get("vat_total") or Decimal("0") for item in rows), Decimal("0"))
        parent = self._parent.winfo_toplevel()
        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.transient(parent)
        dlg.geometry("980x520")
        dlg.minsize(780, 360)

        head = ttk.Frame(dlg, padding=(12, 10, 12, 4))
        head.pack(fill="x")
        ttk.Label(
            head,
            text=f"{title}\n{len(rows)} listin · Σ DDV {money_text(total)} EUR",
            style="Muted.TLabel",
            justify="left",
        ).pack(anchor="w")
        if key == "prevalitev":
            rev_out = self._last_summary.get("prevalitev_output_vat") or 0
            ttk.Label(
                head,
                text=(
                    f"SA + DDV se odbija → input (41–42) = output (23–25): "
                    f"{money_text(total)} vs {money_text(rev_out)}. "
                    f"Če DDV se ne odbija → samo obračunani (za plačilo)."
                ),
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(4, 0))
        else:
            ttk.Label(
                head,
                text="Domači odbitni DDV (brez samoobdavčitve). SA listine so v PREVALITEV.",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(4, 0))

        frame = ttk.Frame(dlg, padding=(12, 4, 12, 8))
        frame.pack(fill="both", expand=True)
        cols = (
            "seq", "date", "document", "supplier", "vat_id",
            "net", "eu10", "eu11", "f76a", "vat22", "vat95", "vat5", "vat",
        )
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        headings = {
            "seq": ("ZŠ", 45),
            "date": ("Datum", 90),
            "document": ("Listina", 120),
            "supplier": ("Dobavitelj", 200),
            "vat_id": ("ID za DDV", 100),
            "net": ("Osnova 08", 85),
            "eu10": ("10", 75),
            "eu11": ("11", 75),
            "f76a": ("76.a", 75),
            "vat22": ("DDV 22%", 75),
            "vat95": ("DDV 9,5%", 75),
            "vat5": ("DDV 5%", 70),
            "vat": ("Σ DDV", 80),
        }
        for col, (label, width) in headings.items():
            tree.heading(col, text=label)
            tree.column(col, width=width, minwidth=40, anchor="e" if col not in {"supplier", "document", "vat_id", "date", "seq"} else "w")

        by_iid: dict[str, dict[str, Any]] = {}
        for i, item in enumerate(sorted(rows, key=lambda r: (str(r.get("date") or ""), str(r.get("document_no") or "")))):
            iid = f"prsplit:{i}"
            by_iid[iid] = item
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    item.get("seq") or "",
                    date_text(item.get("date")),
                    item.get("document_no") or "",
                    item.get("supplier_name") or "",
                    item.get("vat_id") or "",
                    money_text(item.get("net_taxable")),
                    money_text(item.get("eu_goods")),
                    money_text(item.get("eu_services")),
                    money_text(item.get("f76a")),
                    money_text(item.get("vat_22")),
                    money_text(item.get("vat_95")),
                    money_text(item.get("vat_5")),
                    money_text(item.get("vat_total")),
                ),
            )

        def open_selected(_event: object | None = None) -> None:
            sel = tree.focus() or (tree.selection()[0] if tree.selection() else "")
            item = by_iid.get(sel)
            if not item or not item.get("id"):
                return
            if self._open_pr:
                try:
                    self._open_pr(int(item["id"]))
                except Exception as exc:
                    messagebox.showerror("PR", str(exc), parent=dlg)

        tree.bind("<Double-1>", open_selected)
        bar = ttk.Frame(dlg, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Label(
            bar,
            text="Dvoklik / Odpri → Uredi PR",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(bar, text="Odpri PR", command=open_selected).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Zapri", command=dlg.destroy).pack(side="right")
        self._set_status(f"{title}: {len(rows)} listin, Σ {money_text(total)} EUR")

    def _company_now(self) -> dict[str, Any]:
        if self._get_company:
            rec = self._get_company()
            if rec:
                return dict(rec)
        return dict(self._company)

    def _set_status(self, text: str) -> None:
        if self._status:
            self._status(text)

    def _require_rows(self) -> bool:
        if not self._ir_rows and not self._pr_rows:
            messagebox.showinfo("DDV-O", "Ni IR/PR vrstic v filtru obdobja.", parent=self._parent.winfo_toplevel())
            return False
        return True

    def _preview_pdf(self) -> None:
        if not self._require_rows():
            return
        try:
            path = preview_pdf(
                self._ir_rows,
                self._pr_rows,
                period_from=self._period_from,
                period_to=self._period_to,
                company=self._company_now(),
            )
            open_path(path)
            self._set_status(f"Predogled DDV-O: {path.name}")
        except Exception as exc:
            messagebox.showerror("Predogled PDF", str(exc), parent=self._parent.winfo_toplevel())

    def _export_pdf_xml(self) -> None:
        if not self._require_rows():
            return
        try:
            result = export_pdf_xml(
                self._ir_rows,
                self._pr_rows,
                period_from=self._period_from,
                period_to=self._period_to,
                company=self._company_now(),
            )
            self._set_status(result.message.split("\n", 1)[0])
            if messagebox.askyesno("DDV-O izvoz", f"{result.message}\n\nOdprem mapo?", parent=self._parent.winfo_toplevel()):
                if result.pdf_path:
                    open_path(result.pdf_path.parent)
        except Exception as exc:
            messagebox.showerror("Izvoz DDV-O", str(exc), parent=self._parent.winfo_toplevel())

    def _pdf_virman(self) -> None:
        if not self._require_rows():
            return
        try:
            result = create_virman_package(
                self._ir_rows,
                self._pr_rows,
                period_from=self._period_from,
                period_to=self._period_to,
                company=self._company_now(),
            )
            self._last_package_paths = [p for p in (result.pdf_path, result.virman_path) if p]
            messagebox.showinfo("PDF + virman", result.message, parent=self._parent.winfo_toplevel())
            self._set_status("DDV-O paket (PDF + virman) pripravljen.")
            if result.package_dir and messagebox.askyesno(
                "Paket", "Odprem mapo paketa?", parent=self._parent.winfo_toplevel()
            ):
                open_path(result.package_dir)
        except Exception as exc:
            messagebox.showerror("PDF + virman", str(exc), parent=self._parent.winfo_toplevel())

    def _email_package(self) -> None:
        if not self._require_rows():
            return
        top = self._parent.winfo_toplevel()
        try:
            company = self._company_now()
            to_addr = client_email_to(company)
            if not to_addr:
                messagebox.showerror(
                    "E-pošta DDV-O",
                    "Manjka e-pošta stranke (polje Email v evidenci firm).",
                    parent=top,
                )
                return
            if not self._last_package_paths:
                pkg = create_virman_package(
                    self._ir_rows,
                    self._pr_rows,
                    period_from=self._period_from,
                    period_to=self._period_to,
                    company=company,
                )
                self._last_package_paths = [p for p in (pkg.pdf_path, pkg.virman_path) if p]
                obligation = pkg.obligation
                payment = pkg.payment
            else:
                obligation = Decimal(str(self._last_summary.get("obligation") or 0))
                payment = obligation
            to_addr, subject, body = ddvo_client_mail_draft(
                company=company,
                period_from=self._period_from,
                period_to=self._period_to,
                obligation=obligation,
                payment=payment,
            )
            from trops_studio.ui.smtp_compose_dialog import SmtpComposeDialog

            SmtpComposeDialog(
                top,
                title="E-pošta DDV-O — predogled SMTP",
                to_addr=to_addr,
                cc=GMAIL_SMTP_CC,
                subject=subject,
                body_html=body,
                attachments=self._last_package_paths,
                on_sent=lambda note: self._set_status(note.split("\n", 1)[0]),
            )
        except Exception as exc:
            messagebox.showerror("E-pošta", str(exc), parent=top)

    def _fetch_edavki_mrn(self) -> None:
        """Odpre eDavki z datumi obdobja — delegira na glavno okno."""
        if self._fetch_mrn:
            self._fetch_mrn()
            return
        open_edavki_mrn_declarations()

    def apply_edavki_mrn(self, lookup: Any, field26: Any = None) -> None:
        """Posodobi INFO panel z online MRN in primerjavo s poljem 26."""
        if not lookup or not getattr(lookup, "ok", False):
            return
        self.info_mrn_var.set(lookup.codes_text())
        edavki = money_text(lookup.total_vat)
        if field26 is None:
            self.info_mrn_amt_var.set(edavki)
            self._set_status(f"eDavki MRN: {len(lookup.rows)}× · {edavki} EUR → polje 26")
            return
        form26 = money_text(field26)
        self.info_mrn_amt_var.set(f"{edavki} / 26: {form26}")
        diff = decimal_value(lookup.total_vat) - decimal_value(field26)
        mark = "OK" if abs(diff) < decimal_value("0.50") else f"razlika {money_text(diff)}"
        self._set_status(
            f"eDavki MRN: {len(lookup.rows)}× · {edavki} EUR vs DDV-O 26 {form26} — {mark}"
        )

    def _check_api(self) -> None:
        company = self._company_now()
        org = company_org_id(company)
        if not org:
            messagebox.showinfo(
                "Minimax API",
                "Izberi podjetje z Org_ID (glava Projest).",
                parent=self._parent.winfo_toplevel(),
            )
            return
        self._set_status(f"Preverjam Minimax API (Org {org}) …")
        try:
            result = check_minimax_api(org)
        except Exception as exc:
            messagebox.showerror("Minimax API", str(exc), parent=self._parent.winfo_toplevel())
            return
        if result.ok:
            messagebox.showinfo("Minimax API", result.message, parent=self._parent.winfo_toplevel())
        else:
            messagebox.showerror("Minimax API", result.message, parent=self._parent.winfo_toplevel())
        self._set_status(result.message.split("\n", 1)[0])

    def _request_recalc(self) -> None:
        if self._recalc_callback:
            self._recalc_callback()

    def clear_search(self) -> None:
        self.search_var.set("")
        self._populate_tree()

    def _set_info_from_summary(self, summary: Mapping[str, Any] | None = None) -> None:
        summary = summary or {}
        self.info_uvoz_var.set(money_text(summary.get("info_uvoz_21_22")))
        self.info_excluded_var.set(money_text(summary.get("info_excluded")))
        self.info_mrn_var.set(str(summary.get("info_mrn_text") or "—"))
        self.info_mrn_amt_var.set(money_text(summary.get("info_mrn_amount")))
        self.info_neodbitni_var.set(money_text(summary.get("info_neodbitni")))
        self.info_opr_os_var.set(money_text(summary.get("info_opr_os")))

    def refresh(
        self,
        ir_rows: Sequence[Mapping[str, Any]],
        pr_rows: Sequence[Mapping[str, Any]],
        *,
        period_from: date | None = None,
        period_to: date | None = None,
        company_tax: str = "",
        company_name: str = "",
        company: Mapping[str, Any] | None = None,
    ) -> None:
        self._ir_rows = list(ir_rows)
        self._pr_rows = list(pr_rows)
        self._period_from = period_from
        self._period_to = period_to
        if company:
            self._company = dict(company)
        if period_from and period_to:
            self.period_var.set(
                f"Obdobje: {period_from.strftime('%d.%m.%Y')} – {period_to.strftime('%d.%m.%Y')} · SQL"
            )
        else:
            self.period_var.set("Obdobje: —")
        tax_txt = company_tax or "—"
        name_txt = company_name or ""
        self.taxpayer_var.set(f"Davčna: {tax_txt}" + (f" • {name_txt}" if name_txt else ""))

        if not ir_rows and not pr_rows:
            self._fields = []
            self._last_summary = {}
            self.output_var.set("0,00 EUR")
            self.input_var.set("0,00 EUR")
            self.result_var.set("0,00 EUR")
            self.domestic_var.set("0,00 EUR")
            self.prevalitev_var.set("0,00 EUR")
            self.split_var.set("Prevalitev / domači DDV: ni podatkov.")
            self._set_info_from_summary({})
            self._set_samoobdavcitev_split({})
            self.control_var.set("Ni IR/PR vrstic v filtru obdobja.")
            self.flags_var.set("Kontrola iz SQLite IR/PR")
            self._populate_tree()
            return

        summary = compute_ddvo(ir_rows, pr_rows, period_from=period_from, period_to=period_to)
        self._last_summary = dict(summary)
        self._fields = list(summary.get("fields") or [])
        self._set_info_from_summary(summary)
        self._set_samoobdavcitev_split(summary)
        self.flags_var.set(
            f"Samoobdavčitev: {summary.get('self_assessment_count', '—')}  •  "
            f"DDV brez odbitka: {summary.get('vat_not_deducted_count', '—')}  •  "
            f"SQL IR {len(ir_rows)} / PR {len(pr_rows)}"
        )
        self.output_var.set(f"{money_text(summary.get('output_vat'))} EUR")
        self.input_var.set(f"{money_text(summary.get('input_vat'))} EUR")
        domestic = summary.get("domestic_input_vat") or 0
        prevalitev = summary.get("prevalitev_input_vat") or 0
        rev_out = summary.get("prevalitev_output_vat") or 0
        self.domestic_var.set(f"{money_text(domestic)} EUR")
        self.prevalitev_var.set(f"{money_text(prevalitev)} EUR")
        self.domestic_detail_var.set(
            f"22%: {money_text(summary.get('domestic_vat_22'))} • "
            f"9,5%: {money_text(summary.get('domestic_vat_95'))}"
        )
        try:
            bal = Decimal(str(prevalitev)) - Decimal(str(rev_out))
        except Exception:
            bal = Decimal("0")
        bal_txt = "OK" if bal == 0 else f"Δ {money_text(bal)}"
        self.prevalitev_detail_var.set(
            f"input {money_text(prevalitev)} = output {money_text(rev_out)} ({bal_txt}) • "
            f"sint. KIR {int(summary.get('synthetic_kir_count') or 0)}"
        )
        self.output_detail_var.set(
            f"IR {money_text(summary.get('domestic_output_vat'))} + prevalitev {money_text(rev_out)}"
        )
        self.input_detail_var.set(
            f"domači {money_text(domestic)} + prevalitev {money_text(prevalitev)}"
        )
        obligation = summary.get("obligation")
        excess = summary.get("excess")
        if excess and excess > 0:
            self.result_var.set(f"{money_text(excess)} EUR")
            self.result_detail_var.set("presežek (polje 52)")
        else:
            self.result_var.set(f"{money_text(obligation)} EUR")
            self.result_detail_var.set("obveznost (polje 51)")
        access_pay = summary.get("access_payable") or 0
        access_ex = summary.get("access_excess") or 0
        access_extra = Decimal(str(summary.get("access_extra_pr_vat") or 0))
        access_like = summary.get("access_pay_like") or 0
        if access_ex and Decimal(str(access_ex)) > 0:
            access_line = f"Access (IR−domači): presežek {money_text(access_ex)}"
        else:
            access_line = f"Projest plačilo (IR−SLO): {money_text(access_pay)}"
            if access_extra:
                access_line += (
                    f"  ·  Access včasih v PR še SA storitve (+{money_text(access_extra)}); "
                    f"tukaj grejo v prevalitev/25 (pravilno), ne v DDV skupaj PR"
                )
        self.split_var.set(
            f"Samoobdavčitve 1600/2600 — prevalitev: {money_text(prevalitev)} "
            f"(22% {money_text(summary.get('prevalitev_vat_22'))} + "
            f"9,5% {money_text(summary.get('prevalitev_vat_95'))}"
            + (
                f" + 5% {money_text(summary.get('prevalitev_vat_5'))}"
                if Decimal(str(summary.get("prevalitev_vat_5") or 0)) != 0
                else ""
            )
            + f")  •  SLO DDV: {money_text(domestic)}  •  {access_line}"
        )
        ok = bool(summary.get("control_ok"))
        self.control_var.set(
            f"Kontrola {'OK' if ok else 'ODSTOPANJE'} • "
            f"obračunani {money_text(summary.get('output_vat_exact'))} → {money_text(summary.get('output_vat'))} • "
            f"odbitni {money_text(summary.get('input_vat_exact'))} → {money_text(summary.get('input_vat'))} • "
            f"IR {len(ir_rows)} / PR {len(pr_rows)} / prevalitev {int(summary.get('prevalitev_count') or 0)}"
        )
        self.control_label.configure(bg="#1d3a2a" if ok else "#5b3717")
        self._populate_tree()

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        tokens = search_tokens(self.search_var.get())
        nonzero_only = self.amount_filter.get() == "NONZERO"
        visible = 0
        for index, field in enumerate(self._fields):
            code = str(field.get("code") or "")
            exact = field.get("exact") or 0
            rounded = field.get("value") or 0
            try:
                is_zero = Decimal(str(exact)) == 0 and Decimal(str(rounded)) == 0
            except Exception:
                is_zero = money_text(exact) == "0,00" and money_text(rounded) == "0,00"
            if nonzero_only and is_zero and code not in {"51", "52"}:
                continue
            values = (
                field.get("section", ""),
                code,
                field.get("label", ""),
                field.get("source", ""),
                money_text(exact),
                money_text(rounded),
                money_text(field.get("difference")),
                field.get("status", ""),
            )
            if tokens and not haystack_matches(tokens, values):
                continue
            tags = ("result",) if code in {"51", "52"} else (("odd",) if visible % 2 else ())
            self.tree.insert("", "end", iid=f"ddvo:{index}", values=values, tags=tags)
            visible += 1
