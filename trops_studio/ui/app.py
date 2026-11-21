from __future__ import annotations

import os
import re
import threading
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping, Sequence
from webbrowser import open as open_url

from trops_studio import APP_TITLE, __version__
from trops_studio.accounts import (
    allocate_pr_accounts,
    remember_customer_rule,
    remember_supplier_rule,
    repair_pr_eu_rows,
)
from trops_studio.companies import (
    company_ddv_cadence,
    company_key,
    company_name,
    company_org_id,
    company_source_kind,
    company_tax,
    company_zst,
    find_company,
    load_companies,
)
from trops_studio.config import (
    DEFAULT_INTEGRA_SQL,
    DEFAULT_IR_DARILA,
    DEFAULT_IR_EU_REVENUE_ACCOUNT,
    DEFAULT_IR_FITNES,
    DEFAULT_IR_REVENUE_ACCOUNT,
    DEFAULT_MINIMAX_OUT,
    DEFAULT_PR,
    DEFAULT_PR_EXCLUDED_ACCOUNT,
    DEFAULT_PR_EXPENSE_ACCOUNT,
    TROPS_ROOT,
    company_db_path,
)
from trops_studio.db import Database
from trops_studio.excel_map import import_vasco_files_to_db
from trops_studio.kirkpr_import import import_kirkpr_file_to_db
from trops_studio.minimax_parties import sync_customers_from_minimax
from trops_studio.minimax_runtime import check_minimax_api, open_minimax_temeljnice
from trops_studio.minimax_sync import confirm_documents, sync_ready_to_minimax
from trops_studio.money import (
    date_text,
    decimal_value,
    is_nonzero,
    money_text,
    normalize_vat_id,
    parse_date,
)
from trops_studio.ddvo_calc import compute_ddvo, pr_access_info
from trops_studio.edavki_links import (
    PROJEST_NAME,
    PROJEST_TAX_ID,
)
from trops_studio.edavki_mrn import fetch_edavki_mrn
from trops_studio.mrn_workbook import (
    deklaracija_xls_path,
    load_csv_into_deklaracija_xls,
    mrn_folder,
    mrn_period_stamp,
    save_edavki_mrn_csv,
)
from trops_studio.ir_list_view import apply_ir_eu_sale, ir_customer_country, ir_customer_region, ir_display_osnova
from trops_studio.pr_list_view import (
    apply_pr_si_vat_flag,
    odhodek_summary,
    pr_corrected_region,
    pr_odhodek_lines,
    pr_p8_amount,
    pr_si_vat_on_non_domestic,
    pr_supplier_region,
    region_label,
)
from trops_studio.parties_ensure import (
    collect_firms_needing_minimax,
    collect_missing_ir_parties,
    collect_missing_pr_parties,
    ensure_missing_via_ajpes,
    merge_parties,
    repair_party_names,
)
from trops_studio.session_prefs import load_session, parse_iso_date, save_session
from trops_studio.sync_state import SYNC_ERROR, SYNC_READY, SYNC_SYNCED
from trops_studio.vasco_discover import (
    cleanup_temp_dir,
    resolve_vasco_sources,
    snapshot_last_vasco_import,
)
from trops_studio.xml_export import export_minimax_xml_for_kirkpr
from trops_studio.ui.period import (
    PERIOD_CHOICES,
    bounds_from_period_stamp,
    default_period_for_ddv_cadence,
    format_si_date,
    infer_period_stamp,
    month_bounds,
    parse_si_date,
    period_bounds,
    period_label_for_range,
    period_stamp,
    previous_month_bounds,
    revision_suffix,
)
from trops_studio.ui.collapsible import CollapsibleSection
from trops_studio.ui.ddvo_tab import DdvoTab
from trops_studio.ui.knjige import KnjigePanel
from trops_studio.ui.konti_tab import KontiTab
from trops_studio.ui.vse_knjizbe_tab import VseKnjizbeTab
from trops_studio.ui.missing_pr_parties_dialog import (
    MissingIrPartiesDialog,
    MissingJournalPartiesDialog,
    MissingPrPartiesDialog,
)
from trops_studio.ui.progress_dialog import ProgressDialog
from trops_studio.ui.vat_api_check_dialog import VatApiCheckDialog
from trops_studio.ui.nove_firme_dialog import NoveFirmeDialog
from trops_studio.account_choices import (
    account_code_from_choice,
    clear_account_cache,
    ensure_choice,
    filter_account_choices,
    load_account_choices,
    warm_account_cache_minimax,
)
from trops_studio.ui.filtered_combo import FilteredCombobox
from trops_studio.ui.ir_editor import IrEditorDialog
from trops_studio.ui.pr_editor import PrEditorDialog
from trops_studio.ui.search import haystack_matches, row_search_chunks, search_tokens
from trops_studio.ui.stranke_dialog import StrankeDialog
from trops_studio.ui.styles import apply_style, apply_ui_prefs_to_root, load_ui_prefs, merge_ui_prefs, save_ui_prefs
from trops_studio.ui.tooltip import ToolTip
from trops_studio.row_status import (
    DEFAULT_ROW_STATUS,
    STATUS_FILTER_CHOICES,
    status_filter_matches,
)

IR_BOOKS = ("Darila", "Fitness", "Paragoni", "Fakture", "KIR")
NAVIGATION_DEFAULT_WIDTH = 280
NAVIGATION_MIN_WIDTH = 220


class ProjestStudioApp:
    def __init__(self, root: tk.Tk, db: Database | None = None) -> None:
        self.root = root
        self.db = db or Database()
        self.ui_prefs = load_ui_prefs()
        self.colors = apply_style(root, self.ui_prefs)
        self.company_registry_path, self.companies = load_companies()
        self.active_company: dict[str, Any] | None = None
        self._company_db_key = ""
        self._suppress_company_select = False
        self.navigation_width = NAVIGATION_DEFAULT_WIDTH
        self._period_filter_updating = False

        self.filter_from_date, self.filter_to_date = previous_month_bounds()
        self.data_span_from: date | None = None
        self.data_span_to: date | None = None
        self._session = load_session()
        self._restore_period_from_session()

        self.ir_darila_var = tk.StringVar(value=str(DEFAULT_IR_DARILA))
        self.ir_fitnes_var = tk.StringVar(value=str(DEFAULT_IR_FITNES))
        self.pr_var = tk.StringVar(value=str(DEFAULT_PR))
        saved_sql_dir = str(self._session.get("integra_sql_dir") or "").strip()
        self.integra_sql_var = tk.StringVar(
            value=saved_sql_dir or str(DEFAULT_INTEGRA_SQL)
        )
        self.integra_auto_irpr = self._session_bool(
            self._session.get("integra_auto_irpr"),
            default=True,
        )
        self.company_var = tk.StringVar(value="Podjetje: ni izbrano")
        self.company_search_var = tk.StringVar(value=str(self._session.get("company_search") or ""))
        self.source_var = tk.StringVar(value="Izberi podjetje — Vir/poti: Vasco, Integra ali KIR/KPR.")
        self.format_var = tk.StringVar(value="Baza: SQLite")
        self.period_var = tk.StringVar(value="Obdobje: —")
        self.member_var = tk.StringVar(value="Vsebina: —")
        self.status_var = tk.StringVar(value=f"SQLite: {self.db.path}")
        self.last_import_var = tk.StringVar(value="Zadnji uvoz: —")
        self.filter_info_var = tk.StringVar(value="")
        self.filter_month_var = tk.StringVar(value=period_label_for_range(self.filter_from_date, self.filter_to_date))
        self.filter_year_var = tk.StringVar(value=str(self.filter_from_date.year))
        self.filter_from_var = tk.StringVar(value=format_si_date(self.filter_from_date))
        self.filter_to_var = tk.StringVar(value=format_si_date(self.filter_to_date))
        self.filter_rev_var = tk.StringVar(value="vse")

        self.ir_search_var = tk.StringVar(value="")
        self.pr_search_var = tk.StringVar(value="")
        self.party_search_var = tk.StringVar(value="")
        self.ir_selection_var = tk.StringVar(value="Izbranih IR: 0")
        self.pr_selection_var = tk.StringVar(value="Izbranih PR: 0")
        self.ir_account_var = tk.StringVar(value=DEFAULT_IR_REVENUE_ACCOUNT)
        self.pr_account_var = tk.StringVar(value=DEFAULT_PR_EXPENSE_ACCOUNT)
        self.ir_account_name_var = tk.StringVar(value="")
        self.pr_account_name_var = tk.StringVar(value="")
        self.remember_customer_var = tk.BooleanVar(value=True)
        self.remember_supplier_var = tk.BooleanVar(value=True)
        self.ir_book_vars = {book: tk.BooleanVar(value=book in {"Darila", "Fitness"}) for book in IR_BOOKS}
        self.ir_status_filter = tk.StringVar(value="VSI")
        self.pr_status_filter = tk.StringVar(value="VSI")
        self.ir_amount_filter = tk.StringVar(value="VSE")  # VSE | NONZERO
        self.pr_amount_filter = tk.StringVar(value="VSE")
        self.pr_filter_si = tk.BooleanVar(value=False)
        self.pr_filter_foreign = tk.BooleanVar(value=False)
        self.pr_filter_excluded = tk.BooleanVar(value=False)
        self.pr_filter_eu10 = tk.BooleanVar(value=False)
        self.pr_filter_eu11 = tk.BooleanVar(value=False)
        self.pr_filter_exempt = tk.BooleanVar(value=False)
        self.pr_filter_76a = tk.BooleanVar(value=False)
        self.pr_filter_multi = tk.BooleanVar(value=False)
        self.pr_filter_si_vat = tk.BooleanVar(value=False)
        self.pr_filter_vat = tk.BooleanVar(value=False)
        self.ir_filter_si = tk.BooleanVar(value=False)
        self.ir_filter_eu = tk.BooleanVar(value=False)
        self.ir_filter_foreign = tk.BooleanVar(value=False)
        self.ir_filter_vat = tk.BooleanVar(value=False)
        self.chk_state: dict[str, bool] = {}
        self.ir_totals_inner: tk.Misc | None = None
        self.pr_totals_inner: tk.Misc | None = None
        self._sync_running = False
        self._import_running = False
        self._last_vat_reports: dict[str, Any] = {}

        self.summary_vars = {
            "ir_count": tk.StringVar(value="0"),
            "ir_value": tk.StringVar(value="0,00 EUR"),
            "pr_count": tk.StringVar(value="0"),
            "pr_value": tk.StringVar(value="0,00 EUR"),
            "parties": tk.StringVar(value="0"),
            "parties_detail": tk.StringVar(value="Minimax šifrant"),
        }

        self._ir_cache: list[dict[str, Any]] = []
        self._pr_cache: list[dict[str, Any]] = []
        self._party_cache: list[dict[str, Any]] = []

        root.title(f"{APP_TITLE} {__version__}")
        root.geometry("1540x940")
        root.minsize(1180, 720)
        root.configure(bg=self.colors["bg"])
        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()
        self._sync_period_filter_vars()
        self._populate_company_tree()
        self._clear_data_view()
        self._restore_company_from_session()
        self._update_source_panel()

    # ------------------------------------------------------------------ layout
    def _build_source_section(self, container: ttk.Frame) -> None:
        """Vir/poti: Projest (Vasco), Integra (SQL) ali KIR/KPR (ostale firme)."""
        source_sec = CollapsibleSection(
            container,
            "Vir / poti",
            bg=self.colors["card"],
            muted=self.colors["muted"],
            initially_open=True,
            padx=12,
            pady=8,
            accent=self.colors["accent"],
        )
        source_sec.pack(fill="x", pady=(12, 0))
        self.ui_source_section = source_sec
        self._source_host = source_sec.body
        card = self.colors["card"]
        muted = self.colors["muted"]
        text = self.colors["text"]
        accent = self.colors["accent"]

        # --- Projest (Vasco poti) ---
        self._source_projest = tk.Frame(self._source_host, bg=card)
        tk.Label(
            self._source_projest,
            text="IR\nPR",
            bg=accent,
            fg="#ffffff",
            font=("Segoe UI Semibold", 10),
            padx=12,
            pady=7,
        ).pack(side="left", padx=(0, 12))
        proj_info = tk.Frame(self._source_projest, bg=card)
        proj_info.pack(side="left", fill="x", expand=True)
        tk.Label(
            proj_info,
            textvariable=self.company_var,
            bg=card,
            fg=muted,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            proj_info,
            textvariable=self.source_var,
            bg=card,
            fg=text,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).pack(anchor="w")
        meta = tk.Frame(proj_info, bg=card)
        meta.pack(fill="x", pady=(4, 0))
        tk.Label(meta, textvariable=self.format_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(
            side="left", padx=(0, 18)
        )
        tk.Label(meta, textvariable=self.period_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(
            side="left", padx=(0, 18)
        )
        tk.Label(meta, textvariable=self.member_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left")
        proj_right = tk.Frame(self._source_projest, bg=card)
        proj_right.pack(side="right")
        paths = tk.Frame(proj_right, bg=card)
        paths.pack(anchor="e")
        for label, var in (
            ("Darila", self.ir_darila_var),
            ("Fitness", self.ir_fitnes_var),
            ("PR", self.pr_var),
        ):
            row = tk.Frame(paths, bg=card)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=card, fg=muted, width=8, anchor="w").pack(side="left")
            ttk.Entry(row, textvariable=var, width=42).pack(side="left", padx=4)
            ttk.Button(row, text="…", width=3, command=lambda v=var: self._choose_path(v)).pack(side="left")
        tk.Label(
            proj_right,
            textvariable=self.last_import_var,
            bg=card,
            fg=muted,
            font=("Segoe UI", 8),
            anchor="e",
            justify="right",
        ).pack(anchor="e", pady=(4, 0))
        proj_btns = tk.Frame(proj_right, bg=card)
        proj_btns.pack(anchor="e", pady=(8, 0))
        open_btn = ttk.Button(proj_btns, text="Uvozi Vasco", style="Accent.TButton", command=self.import_vasco)
        open_btn.pack(side="left", padx=(0, 8))
        btn_kirkpr = ttk.Button(proj_btns, text="Uvozi KIR/KPR", command=self.import_kirkpr)
        btn_kirkpr.pack(side="left", padx=(0, 8))
        btn_hist = ttk.Button(proj_btns, text="Konti iz zgodovine", command=self.learn_accounts_from_history)
        btn_hist.pack(side="left")
        ToolTip(
            open_btn,
            "Uvozi VSE listine iz Vasco (mapa/ZIP).\n"
            "Že v bazi ne podvajam; v seznamu brišeš/popravljaš (Ctrl+O).",
        )
        ToolTip(
            btn_kirkpr,
            "Uvozi FURS KIR/KPR (ZIP, JSON, XML ali CSV) v SQLite — kot v KirKpr Studio.\n"
            "Nato DDV-O in Sinhroniziraj Minimax v tem oknu; ločena KirKpr app ni potrebna.",
        )
        ToolTip(btn_hist, "Projest: nauči kontov iz že uvoženih PR/IR v SQLite zgodovini.")

        # --- Integra (SQL TROPS) ---
        self._source_integra = tk.Frame(self._source_host, bg=card)
        tk.Label(
            self._source_integra,
            text="SQL",
            bg=accent,
            fg="#ffffff",
            font=("Segoe UI Semibold", 10),
            padx=12,
            pady=14,
        ).pack(side="left", padx=(0, 12))
        int_info = tk.Frame(self._source_integra, bg=card)
        int_info.pack(side="left", fill="x", expand=True)
        tk.Label(
            int_info,
            textvariable=self.company_var,
            bg=card,
            fg=muted,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            int_info,
            textvariable=self.source_var,
            bg=card,
            fg=text,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).pack(anchor="w")
        int_meta = tk.Frame(int_info, bg=card)
        int_meta.pack(fill="x", pady=(4, 0))
        tk.Label(int_meta, textvariable=self.format_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(
            side="left", padx=(0, 18)
        )
        tk.Label(int_meta, textvariable=self.period_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left")
        int_right = tk.Frame(self._source_integra, bg=card)
        int_right.pack(side="right")
        sql_row = tk.Frame(int_right, bg=card)
        sql_row.pack(fill="x", pady=1)
        tk.Label(sql_row, text="SQL pot", bg=card, fg=muted, width=8, anchor="w").pack(side="left")
        ttk.Entry(sql_row, textvariable=self.integra_sql_var, width=42).pack(side="left", padx=4)
        ttk.Button(sql_row, text="…", width=3, command=self._choose_integra_sql_dir).pack(side="left")
        int_btns = tk.Frame(int_right, bg=card)
        int_btns.pack(anchor="e", pady=(8, 0))
        btn_integra = ttk.Button(
            int_btns, text="Integra", style="Accent.TButton", command=self._integra_source_action
        )
        btn_integra.pack(side="left", padx=(0, 8))
        btn_int_kirkpr = ttk.Button(int_btns, text="Uvozi KIR/KPR", command=self.import_kirkpr)
        btn_int_kirkpr.pack(side="left")
        ToolTip(
            btn_integra,
            "Integra: SQL TROPS → SQLite (v razvoju).\n"
            "1) Obnovi TROPS iz ZIP/BAK\n"
            "2) gumb zažene obdelavo v SQLite.",
        )
        ToolTip(
            btn_int_kirkpr,
            "Uvozi FURS KIR/KPR (ZIP/JSON/XML/CSV) v SQLite.\n"
            "Dodatek k Integra — po potrebi.",
        )

        # --- Ostale firme (KLUG, …): FURS KIR/KPR ---
        self._source_kirkpr = tk.Frame(self._source_host, bg=card)
        tk.Label(
            self._source_kirkpr,
            text="KIR\nKPR",
            bg=accent,
            fg="#ffffff",
            font=("Segoe UI Semibold", 10),
            padx=12,
            pady=7,
        ).pack(side="left", padx=(0, 12))
        kk_info = tk.Frame(self._source_kirkpr, bg=card)
        kk_info.pack(side="left", fill="x", expand=True)
        tk.Label(
            kk_info,
            textvariable=self.company_var,
            bg=card,
            fg=muted,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            kk_info,
            textvariable=self.source_var,
            bg=card,
            fg=text,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).pack(anchor="w")
        kk_meta = tk.Frame(kk_info, bg=card)
        kk_meta.pack(fill="x", pady=(4, 0))
        tk.Label(kk_meta, textvariable=self.format_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(
            side="left", padx=(0, 18)
        )
        tk.Label(kk_meta, textvariable=self.period_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left")
        kk_right = tk.Frame(self._source_kirkpr, bg=card)
        kk_right.pack(side="right")
        kk_btns = tk.Frame(kk_right, bg=card)
        kk_btns.pack(anchor="e", pady=(8, 0))
        btn_kk = ttk.Button(
            kk_btns, text="Uvozi KIR/KPR", style="Accent.TButton", command=self.import_kirkpr
        )
        btn_kk.pack(side="left")
        ToolTip(
            btn_kk,
            "Uvozi FURS KIR/KPR (ZIP, JSON, XML ali CSV) v SQLite.\n"
            "Privzeti vir za firme zunaj Projest/Integra — nato DDV-O / Sinhroniziraj.",
        )

        self._source_visible = True
        self._source_kind_shown = ""

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Uvozi Vasco…", command=self.import_vasco, accelerator="Ctrl+O")
        file_menu.add_command(label="Uvozi Vasco (3 datoteke)…", command=self.import_vasco_fixed_paths)
        file_menu.add_command(label="Uvozi FURS KIR/KPR…", command=self.import_kirkpr)
        file_menu.add_command(label="Briši uvoz obdobja…", command=self.delete_import_for_period)
        file_menu.add_command(label="Konti iz SQLite zgodovine…", command=self.learn_accounts_from_history)
        file_menu.add_command(label="Kontni plan iz Minimax → SQL…", command=self.sync_minimax_accounts)
        file_menu.add_command(label="Konti Trops → Minimax…", command=self.open_account_map_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Stranke iz Minimax (pull)…", command=self.sync_minimax_parties)
        file_menu.add_command(label="Manjkajoče stranke IR/PR…", command=self.open_missing_journal_parties)
        file_menu.add_command(label="Zadnja preverba IR…", command=lambda: self.open_last_vat_session("IR"))
        file_menu.add_command(label="Zadnja preverba PR…", command=lambda: self.open_last_vat_session("PR"))
        file_menu.add_command(label="Zadnja FO…", command=lambda: self.open_last_vat_session("IR", mode="fo"))
        file_menu.add_command(label="Preveri Minimax API…", command=self.check_minimax_api)
        file_menu.add_command(label="Sinhroniziraj Minimax (po potrditvi)…", command=self.sync_ready_minimax)
        file_menu.add_command(label="Briši Minimax osnutke obdobja…", command=self.cleanup_minimax_drafts)
        file_menu.add_command(label="Izvozi XML za KirKpr…", command=self.export_xml_for_kirkpr)
        file_menu.add_separator()
        file_menu.add_command(label="Osveži", command=self.refresh_all, accelerator="F5")
        file_menu.add_separator()
        file_menu.add_command(label="Izhod", command=self.root.destroy)
        menu.add_cascade(label="Datoteka", menu=file_menu)
        settings_menu = tk.Menu(menu, tearoff=0)
        settings_menu.add_command(
            label="Videz (gumbi, barve, pisave)…",
            command=self.open_ui_prefs,
        )
        settings_menu.add_command(
            label="SMTP (Gmail) — test / predogled…",
            command=self.open_smtp_compose,
        )
        menu.add_cascade(label="Nastavitve", menu=settings_menu)
        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(
            label="O programu",
            command=lambda: messagebox.showinfo(
                APP_TITLE,
                f"{APP_TITLE} {__version__}\n\n"
                "Več podjetij (TROPS Zšt):\n"
                "  • Projest — Vasco IF*/kp*\n"
                "  • Integra — SQL TROPS → SQLite\n"
                "  • FURS KIR/KPR — ZIP/JSON/XML/CSV (brez ločene KirKpr app)\n\n"
                "SQLite-first:\n"
                "  1) usklajevanje / knjiženje / dodajanje v SQL\n"
                "  2) Potrdi (ready)\n"
                "  3) Sinhroniziraj Minimax (stranke API + IR/PR osnutki API)\n\n"
                "XML→Minimax = ročni uvoz (fallback).\n"
                "Pull šifranta: Minimax↓ stranke.",
                parent=self.root,
            ),
        )
        menu.add_cascade(label="Pomoč", menu=help_menu)
        self.root.config(menu=menu)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=(18, 16, 18, 0))
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container, style="Header.TFrame", padding=(22, 16))
        header.pack(fill="x")
        title_box = ttk.Frame(header, style="Header.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text=APP_TITLE, style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="1 Uvoz  →  2 Preveri IR/PR  →  3 Manjkajoče stranke  →  4 Potrdi  →  5 Minimax",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        actions = ttk.Frame(header, style="Header.TFrame")
        actions.pack(side="right")
        btn_mm = ttk.Button(actions, text="1 Minimax↓", command=self.sync_minimax_parties)
        btn_mm.pack(side="left", padx=(0, 8))
        btn_missing = ttk.Button(actions, text="3 Manjkajoče", command=self.open_missing_journal_parties)
        btn_missing.pack(side="left", padx=(0, 8))
        btn_sync = ttk.Button(
            actions, text="5 Sinhroniziraj", style="Accent.TButton", command=self.sync_ready_minimax
        )
        btn_sync.pack(side="left", padx=(0, 8))
        btn_stranke = ttk.Button(actions, text="Stranke", command=lambda: self.notebook.select(5))
        btn_stranke.pack(side="left", padx=(0, 8))
        btn_refresh = ttk.Button(actions, text="Osveži", command=self.refresh_all)
        btn_refresh.pack(side="left", padx=(0, 8))
        btn_mrn = ttk.Button(actions, text="MRN prenesi", command=self._fetch_edavki_mrn)
        btn_mrn.pack(side="left")
        ToolTip(
            btn_mm,
            "Korak 1: prenesi šifrant strank iz Minimax → SQL.\n"
            "SI stranke najprej dodaš v Minimaxu.",
        )
        ToolTip(
            btn_missing,
            "Korak 3: SI poveži iz Minimaxa.\n"
            "EU/tretja: AI → SQL → Prenesi v Minimax.",
        )
        ToolTip(
            btn_sync,
            "Korak 5: ready IR + PR → Minimax osnutki.\n"
            "Najprej korak 4: Potrdi izbrane na zavihku knjige.",
        )
        ToolTip(
            btn_stranke,
            "Zavihek Stranke: šifrant SQL.\n"
            "SI dodaš v Minimax · EU/tretja AI→SQL→API.",
        )
        ToolTip(btn_refresh, "Osveži tabele IR/PR/Stranke/Knjige (F5).")
        ToolTip(
            btn_mrn,
            "eDavki: Datum od/do + Išči.\n"
            "Če so deklaracije → CSV v D:\\Trops\\{Zšt}\\DDV\\MRN\n"
            "in uvoz v DDV_Deklaracija_*.xls; primerjava s poljem 26.",
        )
        self._build_source_section(container)
        self._build_period_filter_bar(container)

        summary_sec = CollapsibleSection(
            container, "Povzetek IR / PR",
            bg=self.colors["bg"], muted=self.colors["muted"],
            initially_open=True, padx=4, pady=4, accent=self.colors["purple"],
        )
        summary_sec.pack(fill="x", pady=(10, 0))
        self.ui_summary_section = summary_sec
        summary = ttk.Frame(summary_sec.body)
        summary.pack(fill="x")
        summary.columnconfigure((0, 1, 2), weight=1, uniform="summary")
        self._summary_card(summary, 0, "IZDANI RAČUNI (IR)", self.summary_vars["ir_count"], self.summary_vars["ir_value"], self.colors["accent"])
        self._summary_card(summary, 1, "PREJETI RAČUNI (PR)", self.summary_vars["pr_count"], self.summary_vars["pr_value"], self.colors["purple"])
        self._summary_card(summary, 2, "STRANKE", self.summary_vars["parties"], self.summary_vars["parties_detail"], self.colors["warning"])

        self.workspace_paned = ttk.Panedwindow(container, orient="horizontal")
        self.workspace_paned.pack(fill="both", expand=True, pady=(10, 8))
        navigation = ttk.Frame(self.workspace_paned, style="Card.TFrame", padding=(10, 10), width=self.navigation_width)
        content = ttk.Frame(self.workspace_paned, style="Panel.TFrame")
        self.workspace_paned.add(navigation, weight=0)
        self.workspace_paned.add(content, weight=1)
        self._build_navigation(navigation)

        self.notebook = ttk.Notebook(content)
        self.notebook.pack(fill="both", expand=True)
        ir_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        pr_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        knjige_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        ddvo_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        konti_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        parties_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        analysis_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        knjizbe_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        self.notebook.add(ir_tab, text="  Izdani računi (IR)  ")
        self.notebook.add(pr_tab, text="  Prejeti računi (PR)  ")
        self.notebook.add(ddvo_tab, text="  DDV-O  ")
        self.notebook.add(knjige_tab, text="  Knjige IR / PR  ")
        self.notebook.add(konti_tab, text="  KONTI  ")
        self.notebook.add(parties_tab, text="  Stranke  ")
        self.notebook.add(analysis_tab, text="  Analitika  ")
        self.notebook.add(knjizbe_tab, text="  Vse knjižbe  ")
        self._build_ir_tab(ir_tab)
        self._build_pr_tab(pr_tab)
        self.ddvo_tab = DdvoTab(
            ddvo_tab,
            colors=self.colors,
            pack_search=self._pack_tab_search,
            summary_card=self._summary_card,
        )
        self.ddvo_tab.set_recalc_callback(self._refresh_knjige_and_ddvo)
        self.ddvo_tab.set_helpers(
            get_company=lambda: self.active_company,
            status=lambda text: self.status_var.set(text),
            open_pr=lambda rid: self._open_row_editor("PR", int(rid)),
            fetch_mrn=self._fetch_edavki_mrn,
        )
        self.knjige_panel = KnjigePanel(
            knjige_tab,
            colors=self.colors,
            pack_search=self._pack_tab_search,
        )
        self.konti_tab = KontiTab(
            konti_tab,
            colors=self.colors,
            pack_search=self._pack_tab_search,
            on_open_document=lambda kind, rid: self._open_row_editor(kind, int(rid)),
        )
        self._build_parties_tab(parties_tab)
        self.analysis_box = tk.Text(
            analysis_tab, bg=self.colors["panel"], fg=self.colors["text"],
            insertbackground=self.colors["text"], relief="flat", padx=16, pady=12, wrap="word",
        )
        self.analysis_box.pack(fill="both", expand=True)
        self.vse_knjizbe_tab = VseKnjizbeTab(
            knjizbe_tab,
            colors=self.colors,
            pack_search=self._pack_tab_search,
            get_db_path=lambda: Path(self.db.path) if self.db else None,
            get_period=lambda: (self.filter_from_date, self.filter_to_date),
            get_database=lambda: self.db,
            get_org_id=lambda: company_org_id(self.active_company) if self.active_company else "",
            get_master=lambda: self.root,
            on_after_transfer=self.refresh_all,
        )
        self.notebook.bind("<<NotebookTabChanged>>", self._on_main_notebook_tab_changed, add="+")

        status = ttk.Frame(self.root, style="Panel.TFrame")
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(status, text="Ctrl+O uvoz  •  F5 osveži  •  Ctrl+A izberi vse  •  Space chk", style="Status.TLabel").pack(side="right")

    def _summary_card(
        self,
        parent: ttk.Frame,
        column: int,
        title: str,
        value_var: tk.StringVar,
        detail_var: tk.StringVar,
        accent: str,
        *,
        on_click: Callable[[], None] | None = None,
        columns: int = 3,
    ) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame")
        pad_right = 0 if column >= max(columns - 1, 0) else 6
        outer.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, pad_right))
        tk.Frame(outer, bg=accent, height=4).pack(fill="x")
        content = ttk.Frame(outer, style="Card.TFrame", padding=(16, 11))
        content.pack(fill="both", expand=True)
        title_txt = title + ("  · klik za seznam" if on_click else "")
        ttk.Label(content, text=title_txt, style="CardMuted.TLabel").pack(anchor="w")
        line = ttk.Frame(content, style="Card.TFrame")
        line.pack(fill="x", pady=(3, 0))
        ttk.Label(line, textvariable=value_var, style="SummaryValue.TLabel").pack(side="left")
        ttk.Label(line, textvariable=detail_var, style="CardMuted.TLabel").pack(side="right", anchor="s", pady=(7, 0))
        if on_click:
            def _bind(widget: tk.Misc) -> None:
                widget.bind("<Button-1>", lambda _e: on_click())
                try:
                    widget.configure(cursor="hand2")
                except tk.TclError:
                    pass
                for child in widget.winfo_children():
                    _bind(child)

            _bind(outer)
        return outer

    def _build_period_filter_bar(self, parent: ttk.Frame) -> None:
        period_sec = CollapsibleSection(
            parent, "Obdobje",
            bg=self.colors["card"], muted=self.colors["muted"],
            initially_open=True, padx=10, pady=8, accent=self.colors["purple"],
        )
        period_sec.pack(fill="x", pady=(10, 0))
        self.ui_period_section = period_sec
        bar = period_sec.body
        card = self.colors["card"]
        muted = self.colors["muted"]
        warn = self.colors["warning"]
        tk.Label(bar, text="Mesec", bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="‹", width=3, command=lambda: self.shift_period_filter(-1)).pack(side="left")
        self.filter_month_combo = ttk.Combobox(
            bar, textvariable=self.filter_month_var, values=PERIOD_CHOICES,
            state="readonly", width=14, style="Period.TCombobox",
        )
        self.filter_month_combo.pack(side="left", padx=(6, 4))
        self.filter_month_combo.bind("<<ComboboxSelected>>", self._on_period_month_year_changed)
        ToolTip(self.filter_month_combo, "Mesec ali razpon (januar–december). Bold + rumena za boljšo berljivost.")
        year_spin = tk.Spinbox(
            bar, from_=2000, to=2100, textvariable=self.filter_year_var, width=6,
            command=self._on_period_month_year_changed, bg=self.colors["input"], fg=warn,
            buttonbackground=self.colors["header"], relief="flat", insertbackground=warn,
            font=("Segoe UI", 11, "bold"),
        )
        year_spin.pack(side="left", padx=(0, 4))
        year_spin.bind("<Return>", self._on_period_month_year_changed)
        year_spin.bind("<FocusOut>", self._on_period_month_year_changed)
        next_btn = ttk.Button(bar, text="›", width=3, command=lambda: self.shift_period_filter(1))
        next_btn.pack(side="left", padx=(0, 10))
        ToolTip(next_btn, "Naslednji mesec (ni skrči — klikni naslov »Obdobje« za skrči/razširi).")
        tk.Label(bar, text="Oznaka", bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.filter_rev_combo = ttk.Combobox(
            bar, textvariable=self.filter_rev_var, values=("vse",),
            state="readonly", width=10,
        )
        self.filter_rev_combo.pack(side="left", padx=(0, 14))
        self.filter_rev_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_period_filter())
        ToolTip(self.filter_rev_combo, "Zaključen mesec ostane. Nov uvoz istega meseca: -2, -3, -4.")
        from trops_studio.ui.date_picker import make_date_entry

        tk.Label(bar, text="Datum od", bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        from_entry = make_date_entry(bar, self.filter_from_var, width=12)
        from_entry.pack(side="left")
        from_entry.bind("<Return>", self._on_period_dates_changed, add="+")
        from_entry.bind("<<DateEntrySelected>>", self._on_period_dates_changed, add="+")
        from_entry.bind("<FocusOut>", self._on_period_dates_changed, add="+")
        tk.Label(bar, text="Datum do", bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left", padx=(12, 6))
        to_entry = make_date_entry(bar, self.filter_to_var, width=12)
        to_entry.pack(side="left")
        to_entry.bind("<Return>", self._on_period_dates_changed, add="+")
        to_entry.bind("<<DateEntrySelected>>", self._on_period_dates_changed, add="+")
        to_entry.bind("<FocusOut>", self._on_period_dates_changed, add="+")
        ttk.Button(bar, text="Uporabi", style="Accent.TButton", command=self.apply_period_filter).pack(side="left", padx=(14, 6))
        ttk.Button(bar, text="Vsa obdobja", command=self.reset_period_filter_to_data).pack(side="left", padx=(0, 10))
        btn_del_month = ttk.Button(bar, text="Briši uvoz obdobja", command=self.delete_import_for_period)
        btn_del_month.pack(side="left", padx=(0, 10))
        ToolTip(btn_del_month, "Izbriši IR in PR v trenutno izbranem obdobju (SQLite).")
        tk.Label(bar, textvariable=self.filter_info_var, bg=card, fg=muted, font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)

    def _on_main_notebook_tab_changed(self, _event: Any = None) -> None:
        """Na DDV-O / Knjige / KONTI skrči zgornje +/- panele → več prostora."""
        try:
            tab = self.notebook.select()
            text = self.notebook.tab(tab, "text")
        except tk.TclError:
            return
        if "Analitika" in str(text) or "Analiza" in str(text):
            self._update_analysis()
        if "Vse knjižbe" in str(text):
            try:
                self.vse_knjizbe_tab.refresh()
            except Exception:
                pass
        is_dense = (
            "Knjige" in str(text)
            or "KONTI" in str(text)
            or "DDV-O" in str(text)
            or "Vse knjižbe" in str(text)
        )
        sections = {
            "source": getattr(self, "ui_source_section", None),
            "period": getattr(self, "ui_period_section", None),
            "summary": getattr(self, "ui_summary_section", None),
        }
        if is_dense:
            if getattr(self, "_ui_sections_before_dense", None) is None:
                self._ui_sections_before_dense = {
                    key: bool(getattr(sec, "_open", True)) if sec is not None else True
                    for key, sec in sections.items()
                }
            for sec in sections.values():
                if sec is not None:
                    sec.set_open(False)
        else:
            saved = getattr(self, "_ui_sections_before_dense", None)
            if saved:
                for key, sec in sections.items():
                    if sec is not None:
                        sec.set_open(bool(saved.get(key, True)))
                self._ui_sections_before_dense = None

    def _mrn_save_dir(self) -> Path:
        return mrn_folder(company_zst(self.active_company or {}))

    def _fetch_edavki_mrn(self) -> None:
        """eDavki Išči → CSV v DDV\\MRN → Excel; primerjava s poljem 26."""
        date_from = format_si_date(self.filter_from_date) or self.filter_from_var.get()
        date_to = format_si_date(self.filter_to_date) or self.filter_to_var.get()
        company = self.active_company or {}
        tax = company_tax(company) or PROJEST_TAX_ID
        name = company_name(company) or PROJEST_NAME
        folder = self._mrn_save_dir()
        period = mrn_period_stamp(self.filter_from_date, date_from)
        xls_path = deklaracija_xls_path(folder, tax)
        self.status_var.set(f"eDavki MRN: iščem {date_from} – {date_to} …")

        def work() -> None:
            err = ""
            lookup = None
            saved: Path | None = None
            try:
                lookup = fetch_edavki_mrn(
                    date_from=date_from,
                    date_to=date_to,
                    tax_number=tax,
                    company_name=name,
                    timeout_sec=50.0,
                )
                if lookup.ok and lookup.rows:
                    saved = save_edavki_mrn_csv(lookup, folder, period=period)
            except Exception as exc:
                err = str(exc)

            def finish() -> None:
                if err:
                    messagebox.showerror("MRN", err, parent=self.root)
                    self.status_var.set("eDavki MRN: napaka")
                    return
                assert lookup is not None
                if not lookup.ok:
                    messagebox.showwarning("MRN", lookup.error or "MRN ni prebran.", parent=self.root)
                    self.status_var.set("eDavki MRN: ni podatka")
                    return
                if lookup.empty or not lookup.rows:
                    messagebox.showinfo(
                        "MRN",
                        "Za izbrano obdobje ni podatkov.\n\n"
                        f"{date_from} – {date_to}\n"
                        f"{name} / {tax}",
                        parent=self.root,
                    )
                    self.status_var.set(f"eDavki MRN: ni podatkov ({date_from} – {date_to})")
                    return
                if saved is None:
                    self.status_var.set("eDavki MRN: so deklaracije, CSV ni shranjen.")
                    return
                if xls_path.is_file():
                    try:
                        excel_note = load_csv_into_deklaracija_xls(xls_path, saved)
                    except Exception as exc:
                        excel_note = f"Excel uvoz: {exc}"
                        try:
                            os.startfile(str(xls_path))
                            os.startfile(str(saved))
                        except OSError:
                            pass
                else:
                    excel_note = f"Ni {xls_path.name} — samo CSV."
                field26 = decimal_value(0)
                try:
                    ir_rows, pr_rows = self._period_rows()
                    summary = compute_ddvo(
                        ir_rows,
                        pr_rows,
                        period_from=self.filter_from_date,
                        period_to=self.filter_to_date,
                    )
                    field26 = decimal_value(summary.get("info_ddvo_26"))
                except Exception:
                    field26 = decimal_value(0)
                mrn_amt = decimal_value(lookup.total_vat)
                diff = mrn_amt - field26
                ok26 = abs(diff) < decimal_value("0.50")
                if hasattr(self, "ddvo_tab") and self.ddvo_tab:
                    try:
                        self.ddvo_tab.apply_edavki_mrn(lookup, field26=field26)
                    except TypeError:
                        self.ddvo_tab.apply_edavki_mrn(lookup)
                    except Exception:
                        pass
                cmp_line = (
                    f"eDavki MRN (dedup): {money_text(mrn_amt)} EUR\n"
                    f"DDV-O polje 26:     {money_text(field26)} EUR\n"
                    f"Razlika:            {money_text(diff)} EUR"
                    + ("  — OK" if ok26 else "  — PREVERI")
                )
                self.status_var.set(
                    f"eDavki MRN: {len(lookup.rows)}× → {saved.name}"
                    + (" · 26 OK" if ok26 else f" · 26 razlika {money_text(diff)}")
                )
                messagebox.showinfo(
                    "MRN",
                    f"Shranjeno:\n{saved}\n\n"
                    f"{excel_note}\n\n"
                    f"{cmp_line}",
                    parent=self.root,
                )

            try:
                self.root.after(0, finish)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True, name="edavki-mrn").start()

    def _build_navigation(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="PODJETJA", style="CardMuted.TLabel").pack(anchor="w", padx=4, pady=(2, 5))
        search = ttk.Entry(parent, textvariable=self.company_search_var)
        search.pack(fill="x", padx=4, pady=(0, 6))
        search.bind("<KeyRelease>", lambda _e: self._populate_company_tree())
        self.company_tree = ttk.Treeview(parent, columns=("zst", "name", "org"), show="headings", selectmode="browse", height=12)
        self.company_tree.heading("zst", text="Zšt")
        self.company_tree.heading("name", text="Naziv")
        self.company_tree.heading("org", text="Org")
        self.company_tree.column("zst", width=45, anchor="center")
        self.company_tree.column("name", width=150)
        self.company_tree.column("org", width=55, anchor="center")
        self.company_tree.pack(fill="both", expand=True, padx=2, pady=(0, 8))
        self.company_tree.bind("<<TreeviewSelect>>", self._on_company_select)
        ttk.Label(parent, text="VSEBINA", style="CardMuted.TLabel").pack(anchor="w", padx=4, pady=(4, 5))
        self.nav_tree = ttk.Treeview(parent, show="tree", selectmode="browse", height=8)
        self.nav_tree.pack(fill="x", padx=2)
        self.nav_tree.insert("", "end", iid="nav:ir", text="Izdani računi (IR)")
        self.nav_tree.insert("", "end", iid="nav:pr", text="Prejeti računi (PR)")
        self.nav_tree.insert("", "end", iid="nav:ddvo", text="Obrazec DDV-O")
        knjige = self.nav_tree.insert("", "end", iid="nav:knjige", text="Knjige IR/PR", open=True)
        self.nav_tree.insert(knjige, "end", iid="nav:knjiga_ir", text="  Knjiga IR")
        self.nav_tree.insert(knjige, "end", iid="nav:knjiga_pr", text="  Knjiga PR")
        self.nav_tree.insert("", "end", iid="nav:konti", text="KONTI (pivot)")
        self.nav_tree.insert("", "end", iid="nav:parties", text="Stranke")
        self.nav_tree.insert("", "end", iid="nav:analysis", text="Analitika")
        self.nav_tree.insert("", "end", iid="nav:knjizbe", text="Vse knjižbe")
        self.nav_tree.bind("<<TreeviewSelect>>", self._on_navigation_select)

    def _pack_tab_search(
        self,
        parent: ttk.Frame,
        variable: tk.StringVar,
        *,
        on_change: Callable[[], None],
        clear_command: Callable[[], None],
        tip: str,
    ) -> None:
        box = ttk.Frame(parent, style="Panel.TFrame")
        box.pack(side="right")
        ttk.Label(box, text="Išči", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(box, textvariable=variable, width=28)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: on_change())
        entry.bind("<Return>", lambda _e: on_change())
        ttk.Button(box, text="×", width=3, command=clear_command).pack(side="left", padx=(4, 0))
        ToolTip(entry, tip)

    def _build_ir_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Pregled izdanih računov", style="SectionTitle.TLabel").pack(side="left")
        btn_ir_api = ttk.Button(
            top, text="2 Preveri IR", style="Accent.TButton",
            command=lambda: self.check_journal_vat_api("IR"),
        )
        btn_ir_api.pack(side="left", padx=(12, 0))
        ToolTip(
            btn_ir_api,
            "Korak 2: SI samo Minimax · EU Minimax+VIES · tretje ime v Minimaxu.\n"
            "Zadnja seja in e-pošta sta v oknu preverbe.",
        )
        btn_ir_fo = ttk.Button(
            top,
            text="Fizične osebe",
            command=lambda: self.check_journal_vat_api("IR", mode="fo"),
        )
        btn_ir_fo.pack(side="left", padx=(8, 0))
        ToolTip(
            btn_ir_fo,
            "IR brez predpone (FO). Če AJPES reče zavezanec → v potrditev Projestu.\n"
            "E-pošta je v oknu preverbe.",
        )
        self._pack_tab_search(
            top, self.ir_search_var, on_change=self._populate_ir_tree,
            clear_command=self.clear_ir_search,
            tip="Išči IR: listina, kupec, znesek, DDV, datum, knjiga, konto, status …",
        )

        books = ttk.Frame(parent, style="Panel.TFrame")
        books.pack(fill="x", pady=(0, 6))
        ttk.Label(books, text="Knjige:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        # Darila/Fitness samo Projest (Vasco); Integra ima Paragoni + Fakture.
        self._ir_books_projest = ttk.Frame(books, style="Panel.TFrame")
        self._ir_books_projest.pack(side="left")
        for book in ("Darila", "Fitness"):
            chk = ttk.Checkbutton(
                self._ir_books_projest, text=book, variable=self.ir_book_vars[book],
                style="Filter.TCheckbutton", command=self._populate_ir_tree,
            )
            chk.pack(side="left", padx=(0, 10))
            ToolTip(chk, f"Prikaži / skrij IR knjigo {book} (Projest / Vasco).")
        self._ir_book_paragoni_chk = ttk.Checkbutton(
            books, text="Paragoni", variable=self.ir_book_vars["Paragoni"],
            style="Filter.TCheckbutton", command=self._populate_ir_tree,
        )
        self._ir_book_paragoni_chk.pack(side="left", padx=(0, 10))
        ToolTip(self._ir_book_paragoni_chk, "Prikaži / skrij IR knjigo Paragoni.")
        chk_fak = ttk.Checkbutton(
            books, text="Fakture", variable=self.ir_book_vars["Fakture"],
            style="Filter.TCheckbutton", command=self._populate_ir_tree,
        )
        chk_fak.pack(side="left", padx=(0, 10))
        ToolTip(chk_fak, "Prikaži / skrij IR knjigo Fakture.")
        self._ir_book_kir_chk = ttk.Checkbutton(
            books, text="KIR", variable=self.ir_book_vars["KIR"],
            style="Filter.TCheckbutton", command=self._populate_ir_tree,
        )
        self._ir_book_kir_chk.pack(side="left", padx=(0, 10))
        ToolTip(
            self._ir_book_kir_chk,
            "Prikaži / skrij IR iz FURS KIR/KPR uvoza.\n"
            "Pri KLUG in podobnih firmah je to privzeta knjiga.",
        )
        ttk.Button(books, text="Vse knjige", command=self._select_all_ir_books).pack(side="left", padx=(8, 4))
        ttk.Button(books, text="Brez knjig", command=self._clear_all_ir_books).pack(side="left", padx=(0, 4))
        self._ir_btn_darila_fitness = ttk.Button(
            books, text="Samo Darila+Fitness", command=self._select_default_ir_books,
        )
        self._ir_btn_darila_fitness.pack(side="left", padx=(0, 10))
        self._ir_btn_vse_oznaci = ttk.Button(
            books, text="Vse označi", command=lambda: self._set_chk_all_visible("IR", True),
        )
        self._ir_btn_vse_oznaci.pack(side="left", padx=(8, 4))
        ttk.Button(books, text="Vse odznači", command=lambda: self._set_chk_all_visible("IR", False)).pack(side="left")
        btn_ir_xls = ttk.Button(books, text="Odpri Excel IR", command=self.open_excel_ir)
        btn_ir_xls.pack(side="left", padx=(8, 4))
        ToolTip(btn_ir_xls, "Odpri Excel zadnjega uvoza (Darila + Fitness).")
        ToolTip(books, "Knjige = filter prikaza. Vse označi / odznači = stolpec Chk (za Potrdi).")
        self._ir_books_kind_shown = ""
        self._update_ir_book_filters_for_company()

        filters = ttk.Frame(parent, style="Panel.TFrame")
        filters.pack(fill="x", pady=(0, 6))
        ttk.Label(filters, text="Status:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        ir_status_labels = [label for label, _value in STATUS_FILTER_CHOICES]
        self._ir_status_label_to_value = {label: value for label, value in STATUS_FILTER_CHOICES}
        self._ir_status_combo = ttk.Combobox(
            filters, values=ir_status_labels, width=14, state="readonly",
        )
        self._ir_status_combo.set("Vsi")
        self._ir_status_combo.pack(side="left", padx=(0, 8))
        self._ir_status_combo.bind("<<ComboboxSelected>>", self._on_ir_status_combo)
        ToolTip(
            self._ir_status_combo,
            "Filtriraj po statusu (Popravi / Popravljeno / Manjka konto …)\n"
            "za sortiranje napak iz Excela.",
        )
        ttk.Label(filters, text="Znesek:", style="Muted.TLabel").pack(side="left", padx=(16, 8))
        for label, value in (("Vse", "VSE"), ("<> 0", "NONZERO")):
            ttk.Radiobutton(
                filters, text=label, value=value, variable=self.ir_amount_filter,
                command=self._populate_ir_tree,
            ).pack(side="left", padx=(0, 8))
        ToolTip(filters, "Znesek: Vse = vse vrstice; <> 0 = skrij vrstice z 0,00 (osnova + DDV + skupaj).")

        origin = ttk.Frame(parent, style="Panel.TFrame")
        origin.pack(fill="x", pady=(0, 6))
        ttk.Label(origin, text="Regija:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        for text, var in (
            ("Domači", self.ir_filter_si),
            ("EU", self.ir_filter_eu),
            ("Tretje države", self.ir_filter_foreign),
        ):
            ttk.Checkbutton(
                origin, text=text, variable=var, command=self._populate_ir_tree,
            ).pack(side="left", padx=(0, 10))
        chk_vat = ttk.Checkbutton(
            origin,
            text="ID DDV zavezanci",
            variable=self.ir_filter_vat,
            command=self._populate_ir_tree,
        )
        chk_vat.pack(side="left", padx=(16, 0))
        ToolTip(
            origin,
            "Filtri (OR — prikaži vrstice, ki zadenejo katero koli kljukico):\n"
            "• Domači — SI\n"
            "• EU — HR, CZ, DE, AT … (EU brez SI)\n"
            "• Tretje države — US, CN, GB, CH …\n"
            "Brez označbe = vse.",
        )
        ToolTip(
            chk_vat,
            "Samo IR z vpisanim ID za DDV (polje ni prazno).\n"
            "Brez kljukice = vsi, tudi brez davčne.",
        )

        self.ir_totals_inner = self._build_list_totals_bar(parent, "Skupaj IR (vidne vrstice)")
        self.ir_tree = self._make_tree(
            parent,
            (
                "chk", "zapst", "book", "date", "invoice", "party", "tax_id",
                "net", "vat_22", "vat_95", "vat", "gross", "region", "account", "status",
            ),
            {
                "chk": ("Chk", 42), "zapst": ("ZŠ", 55), "book": ("Knjiga", 80), "date": ("Datum", 95),
                "invoice": ("Listina", 140), "party": ("Kupec", 210), "tax_id": ("ID za DDV", 110),
                "net": ("Osnova", 90), "vat_22": ("DDV 22%", 80), "vat_95": ("DDV 9,5%", 80),
                "vat": ("DDV", 80), "gross": ("Skupaj", 95), "region": ("Regija", 90),
                "account": ("Konto", 75), "status": ("Status", 95),
            },
        )
        self.ir_tree.bind("<<TreeviewSelect>>", self._on_ir_selection)
        self.ir_tree.bind("<Double-1>", self._on_ir_double_click)
        self.ir_tree.bind("<Return>", lambda _e: self.edit_selected("IR"))
        self.ir_tree.bind("<Control-a>", self._select_all_ir)
        self.ir_tree.bind("<space>", lambda _e: self._toggle_chk("IR"))
        self.ir_tree.bind("<Button-1>", self._on_ir_tree_click, add="+")

        bar = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 10, 2, 1))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.ir_selection_var, style="Muted.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(bar, text="Konto prihodka:", style="TLabel").pack(side="left", padx=(0, 6))
        self.ir_account_combo = FilteredCombobox(
            bar,
            textvariable=self.ir_account_var,
            values=self._account_choices("customer"),
            width=36,
            filter_provider=lambda n: filter_account_choices(self._account_choice_list(), n),
        )
        self.ir_account_combo.pack(side="left", padx=(0, 8))
        ToolTip(self.ir_account_combo, "Kontni plan Minimax — tipkaj šifro, filtrira sproti.")
        ttk.Label(bar, textvariable=self.ir_account_name_var, style="Muted.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Uporabi za izbrane", style="Accent.TButton", command=self.apply_ir_account).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Nastavi 7620", command=lambda: self.set_selected_ir_account(DEFAULT_IR_REVENUE_ACCOUNT)).pack(side="left", padx=(0, 6))
        btn_eu_acc = ttk.Button(bar, text="Nastavi 76301", command=lambda: self.set_selected_ir_account(DEFAULT_IR_EU_REVENUE_ACCOUNT))
        btn_eu_acc.pack(side="left", padx=(0, 10))
        ToolTip(btn_eu_acc, "Prodaja blaga v EU: 76301, splošna osnova brez DDV (ne oproščeno).")
        ttk.Checkbutton(bar, text="Zapomni si za kupca", variable=self.remember_customer_var).pack(side="left")
        ttk.Button(bar, text="Izbriši", style="Danger.TButton", command=lambda: self.delete_selected("IR")).pack(side="right")
        ttk.Button(bar, text="Dodaj", command=lambda: self.add_row("IR")).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Odpri / popravi", command=lambda: self.edit_selected("IR")).pack(side="right", padx=(0, 8))
        btn_sync_ir = ttk.Button(
            bar, text="5 Sinhroniziraj knjigo", style="Accent.TButton",
            command=lambda: self.sync_ready_minimax(scope="IR"),
        )
        btn_sync_ir.pack(side="right", padx=(0, 8))
        btn_confirm_ir = ttk.Button(bar, text="4 Potrdi", command=lambda: self.confirm_selected("IR"))
        btn_confirm_ir.pack(side="right", padx=(0, 8))
        ToolTip(btn_confirm_ir, "Korak 4: označi IR → Shranjeno + ready. Še ne gre v Minimax.")
        ToolTip(
            btn_sync_ir,
            "Korak 5: ready IR → Minimax osnutki.\n"
            "Brez ID → Končni 01345. Manjkajoče SI/EU najprej korak 3.",
        )

    def _build_pr_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Pregled in kontiranje prejetih računov", style="SectionTitle.TLabel").pack(side="left")
        btn_pr_xls = ttk.Button(top, text="Odpri Excel PR", command=self.open_excel_pr)
        btn_pr_xls.pack(side="left", padx=(12, 0))
        ToolTip(btn_pr_xls, "Odpri Excel zadnjega uvoza (PR / KPF).")
        btn_pr_ctrl = ttk.Button(top, text="Kontrola PR", command=self._run_pr_si_vat_control)
        btn_pr_ctrl.pack(side="left", padx=(8, 0))
        ToolTip(
            btn_pr_ctrl,
            "Naknadno: tujec / EU z ID za DDV SI+DŠ.\n"
            "Ob uvozu se isto označi (status Popravi).\n"
            "Vklopi filter »SI+DŠ na EU« in pokaže seznam.",
        )
        btn_pr_api = ttk.Button(
            top, text="2 Preveri PR", style="Accent.TButton",
            command=lambda: self.check_journal_vat_api("PR"),
        )
        btn_pr_api.pack(side="left", padx=(8, 0))
        ToolTip(
            btn_pr_api,
            "Korak 2: SI samo Minimax · EU Minimax+VIES · tretje ime (Open AI).\n"
            "Zadnja seja in e-pošta sta v oknu preverbe.",
        )
        self._pack_tab_search(
            top, self.pr_search_var, on_change=self._populate_pr_tree,
            clear_command=self.clear_pr_search,
            tip="Išči PR: listina, dobavitelj, znesek, DDV, datum, konto, interna …",
        )

        filters = ttk.Frame(parent, style="Panel.TFrame")
        filters.pack(fill="x", pady=(0, 6))
        ttk.Label(filters, text="Status:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        pr_status_choices = list(STATUS_FILTER_CHOICES) + [("Brez konta", "NO_ACCOUNT")]
        pr_status_labels = [label for label, _value in pr_status_choices]
        self._pr_status_label_to_value = {label: value for label, value in pr_status_choices}
        self._pr_status_combo = ttk.Combobox(
            filters, values=pr_status_labels, width=14, state="readonly",
        )
        self._pr_status_combo.set("Vsi")
        self._pr_status_combo.pack(side="left", padx=(0, 8))
        self._pr_status_combo.bind("<<ComboboxSelected>>", self._on_pr_status_combo)
        ToolTip(
            self._pr_status_combo,
            "Filtriraj po statusu (Popravi / Manjka konto / Brez konta …)\n"
            "za sortiranje napak uvoza iz Excela.",
        )
        ttk.Label(filters, text="Znesek:", style="Muted.TLabel").pack(side="left", padx=(16, 8))
        for label, value in (("Vse", "VSE"), ("<> 0", "NONZERO")):
            ttk.Radiobutton(
                filters, text=label, value=value, variable=self.pr_amount_filter,
                command=self._populate_pr_tree,
            ).pack(side="left", padx=(0, 8))
        ttk.Button(filters, text="Vse označi", command=lambda: self._set_chk_all_visible("PR", True)).pack(side="right", padx=(0, 4))
        ttk.Button(filters, text="Vse odznači", command=lambda: self._set_chk_all_visible("PR", False)).pack(side="right", padx=(0, 8))

        origin = ttk.Frame(parent, style="Panel.TFrame")
        origin.pack(fill="x", pady=(0, 6))
        ttk.Label(origin, text="Filter:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        for text, var in (
            ("Domači", self.pr_filter_si),
            ("Tretje države", self.pr_filter_foreign),
            ("EU 10", self.pr_filter_eu10),
            ("EU 11", self.pr_filter_eu11),
            ("14 - oproščeno", self.pr_filter_exempt),
            ("76.a člen", self.pr_filter_76a),
            ("Ne gre v knjigo", self.pr_filter_excluded),
            ("Več odhodkov", self.pr_filter_multi),
            ("SI+DŠ na EU", self.pr_filter_si_vat),
        ):
            ttk.Checkbutton(
                origin,
                text=text,
                variable=var,
                command=self._populate_pr_tree,
            ).pack(side="left", padx=(0, 10))
        chk_pr_vat = ttk.Checkbutton(
            origin,
            text="ID DDV zavezanci",
            variable=self.pr_filter_vat,
            command=self._populate_pr_tree,
        )
        chk_pr_vat.pack(side="left", padx=(16, 0))
        ToolTip(
            chk_pr_vat,
            "Samo PR z vpisanim ID za DDV (polje ni prazno).\n"
            "Brez kljukice = vsi, tudi brez davčne.",
        )
        ToolTip(
            origin,
            "Filtri (OR — vse kljukice so neodvisne, lahko vse hkrati):\n"
            "Tretje države + EU 10 + EU 11 + Domači + 14 …\n"
            "• Domači — SI z osnovo 08/14/9a (ne čisti excl)\n"
            "• Tretje države — samo izven EU (US, CN, GB, CH, IL …)\n"
            "• EU 10 — P10 <> 0 in dobavitelj EU\n"
            "• EU 11 — P11 <> 0 in dobavitelj EU\n"
            "• 14 - oproščeno — tip 14 (exempt_on → DDV-O 33)\n"
            "• 76.a člen — tip 9a (samoobdavčitev)\n"
            "• Ne gre v knjigo — znesek izključene nabave\n"
            "• Več odhodkov — 2+ tipa odhodka (+/−)\n"
            "• SI+DŠ na EU — ni Domači, a ima ID za DDV SI + davčno\n"
            "Brez označbe = vse.",
        )

        self.pr_totals_inner = self._build_list_totals_bar(parent, "Skupaj PR (vidne vrstice)")
        self.pr_tree = self._make_tree(
            parent,
            (
                "chk", "zapst", "date", "invoice", "internal", "party", "tax_id", "region",
                "tip", "p8", "net", "exempt", "f76a", "vat_22", "vat_95", "vat_5", "vat", "excluded",
                "odhodek", "odhodek07", "odhodek10", "odhodek11", "odhodek_excl",
                "placilo", "status",
            ),
            {
                "chk": ("Chk", 42), "zapst": ("ZŠ", 50), "date": ("Prejem", 90), "invoice": ("Listina", 120),
                "internal": ("Interna", 75), "party": ("Dobavitelj", 180), "tax_id": ("ID za DDV", 100),
                "region": ("Regija", 70), "tip": ("Tip", 70),
                "p8": ("8 - domači in tretje drž.", 130),
                "net": ("Osnova", 85),
                "exempt": ("14 - oproščeno", 100),
                "f76a": ("76.a", 75),
                "vat_22": ("DDV 22%", 75), "vat_95": ("DDV 9,5%", 75),
                "vat_5": ("DDV 5%", 70), "vat": ("DDV", 75),
                "excluded": ("Ne gre €", 80),
                "odhodek": ("Odhodek01", 70),
                "odhodek07": ("Odh.07", 65),
                "odhodek10": ("Odh.10", 65),
                "odhodek11": ("Odh.11", 65),
                "odhodek_excl": ("Ne gre konto", 85),
                "placilo": ("Plačilo", 65), "status": ("Status", 85),
            },
            hierarchical=True,
        )
        self.pr_tree.bind("<<TreeviewSelect>>", self._on_pr_selection)
        self.pr_tree.bind("<Double-1>", self._on_pr_double_click)
        self.pr_tree.bind("<Return>", lambda _e: self.edit_selected("PR"))
        self.pr_tree.bind("<Control-a>", self._select_all_pr)
        self.pr_tree.bind("<space>", lambda _e: self._toggle_chk("PR"))
        self.pr_tree.bind("<Button-1>", self._on_pr_tree_click, add="+")

        bar = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 10, 2, 1))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.pr_selection_var, style="Muted.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(bar, text="Konto:", style="TLabel").pack(side="left", padx=(0, 6))
        self.pr_account_combo = FilteredCombobox(
            bar,
            textvariable=self.pr_account_var,
            values=self._account_choices("supplier"),
            width=36,
            filter_provider=lambda n: filter_account_choices(self._account_choice_list(), n),
        )
        self.pr_account_combo.pack(side="left", padx=(0, 8))
        ToolTip(self.pr_account_combo, "Kontni plan Minimax — tipkaj šifro, filtrira sproti.")
        ttk.Label(bar, textvariable=self.pr_account_name_var, style="Muted.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Uporabi za izbrane", style="Accent.TButton", command=self.apply_pr_account).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Nastavi 4190", command=lambda: self.set_selected_pr_account("4190")).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(bar, text="Zapomni si za dobavitelja", variable=self.remember_supplier_var).pack(side="left")
        ttk.Button(bar, text="Izbriši", style="Danger.TButton", command=lambda: self.delete_selected("PR")).pack(side="right")
        ttk.Button(bar, text="Dodaj", command=lambda: self.add_row("PR")).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Odpri / popravi", command=lambda: self.edit_selected("PR")).pack(side="right", padx=(0, 8))
        btn_sync_pr = ttk.Button(
            bar, text="5 Sinhroniziraj knjigo", style="Accent.TButton",
            command=lambda: self.sync_ready_minimax(scope="PR"),
        )
        btn_sync_pr.pack(side="right", padx=(0, 8))
        btn_confirm_pr = ttk.Button(bar, text="4 Potrdi", command=lambda: self.confirm_selected("PR"))
        btn_confirm_pr.pack(side="right", padx=(0, 8))
        ToolTip(btn_confirm_pr, "Korak 4: označi PR → Shranjeno + ready. Še ne gre v Minimax.")
        ToolTip(
            btn_sync_pr,
            "Korak 5: ready PR → Minimax osnutki.\n"
            "Manjkajoče SI/EU najprej korak 3.",
        )

    def _build_parties_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Stranke / partnerji", style="SectionTitle.TLabel").pack(side="left")
        self._pack_tab_search(
            top, self.party_search_var, on_change=self._populate_parties_tree,
            clear_command=lambda: (self.party_search_var.set(""), self._populate_parties_tree()),
            tip="Išči stranke: naziv, davčna, kraj, država …",
        )
        bar = ttk.Frame(parent, style="Panel.TFrame")
        bar.pack(fill="x", pady=(0, 6))
        self.party_selection_var = tk.StringVar(value="Označenih: 0")
        ttk.Label(bar, textvariable=self.party_selection_var, style="Muted.TLabel").pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(bar, text="Vse označi", command=lambda: self._set_chk_all_parties(True)).pack(
            side="left"
        )
        ttk.Button(bar, text="Vse odznači", command=lambda: self._set_chk_all_parties(False)).pack(
            side="left", padx=(4, 8)
        )
        btn_merge = ttk.Button(
            bar, text="Združi označene", command=self.merge_selected_parties
        )
        btn_merge.pack(side="left", padx=(0, 8))
        btn_new = ttk.Button(bar, text="Nova", command=lambda: self.open_stranke(foreign=True))
        btn_new.pack(side="left")
        btn_edit = ttk.Button(bar, text="Uredi", command=self.edit_selected_party)
        btn_edit.pack(side="left", padx=6)
        btn_del = ttk.Button(bar, text="Izbriši", style="Danger.TButton", command=self.delete_selected_party)
        btn_del.pack(side="left", padx=6)
        btn_missing = ttk.Button(
            bar,
            text="3 Manjkajoče IR/PR",
            style="Accent.TButton",
            command=self.open_missing_journal_parties,
        )
        btn_missing.pack(side="left", padx=(16, 6))
        ToolTip(
            btn_merge,
            "Označi (Chk) več nazivov iste firme → ena SQL stranka → Išči v Minimax.",
        )
        ToolTip(btn_new, "Nova stranka. SI najprej dodaj v Minimax; EU/tretja: AI → SQL → API.")
        ToolTip(btn_edit, "Uredi izbrano stranko (Išči v Minimax / prenesi).")
        ToolTip(btn_del, "Izbriši označene iz SQLite (ne iz Minimaxa).")
        ToolTip(
            btn_missing,
            "Korak 3: SI poveži iz Minimaxa · EU/tretja AI → SQL → API.",
        )
        hint = ttk.Label(
            parent,
            text=(
                "Tok: 1 Minimax↓  →  2 Preveri IR/PR  →  3 Manjkajoče  "
                "(SI v Minimax / EU AI→SQL→API)  →  4 Potrdi  →  5 Sinhroniziraj"
            ),
            style="Muted.TLabel",
        )
        hint.pack(fill="x", pady=(0, 6))
        self.party_tree = self._make_tree(
            parent,
            ("chk", "id", "name", "vat", "mm", "country", "city", "foreign", "source"),
            {
                "chk": ("Chk", 42),
                "id": ("ID", 50), "name": ("Naziv", 240), "vat": ("ID za DDV", 120),
                "mm": ("MM šifra", 80), "country": ("Država", 60), "city": ("Kraj", 120),
                "foreign": ("Tuja", 50), "source": ("Vir", 90),
            },
        )
        self.party_tree.bind("<Double-1>", lambda _e: self.edit_selected_party())
        self.party_tree.bind("<space>", lambda _e: self._toggle_chk_parties())
        self.party_tree.bind("<Button-1>", self._on_party_tree_click, add="+")
        ToolTip(
            self.party_tree,
            "Chk = označi za združitev / brisanje.\n"
            "MM šifra = šifra v Minimaxu. Vir: minimax / ajpes / placeholder …",
        )

    def _build_list_totals_bar(self, parent: ttk.Frame, title: str) -> tk.Frame:
        """Sumarni zneski nad tabelo IR/PR (rumeni čipi, kot Knjige)."""
        card_bg = "#1e2d4a"
        bar = tk.Frame(parent, bg=card_bg, highlightbackground="#6b4cff", highlightthickness=1, padx=10, pady=6)
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(bar, text=title, bg=card_bg, fg="#ffffff", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        inner = tk.Frame(bar, bg=card_bg)
        inner.pack(fill="x", pady=(3, 0))
        tk.Label(inner, text="(ni zneskov)", bg=card_bg, fg="#9eb0d0", font=("Segoe UI", 9)).pack(side="left")
        return inner

    def _render_list_totals(
        self,
        inner: tk.Misc | None,
        chips: Sequence[tuple[str, Decimal]],
        *,
        show_zeros: bool = True,
    ) -> None:
        """Sumarni čipi po stolpcih (vsi zneski, tudi 0,00 — usklajeno s tabelo)."""
        if inner is None:
            return
        card_bg = "#1e2d4a"
        chip_bg = "#2a3f66"
        muted_chip = "#243554"
        for child in inner.winfo_children():
            child.destroy()
        rows = list(chips) if show_zeros else [(t, a) for t, a in chips if a]
        if not rows:
            tk.Label(inner, text="Skupaj: 0,00", bg=card_bg, fg="#9eb0d0", font=("Segoe UI", 9)).pack(side="left")
            return
        for title, amount in rows:
            bg = chip_bg if amount else muted_chip
            chip = tk.Frame(inner, bg=bg, padx=7, pady=2)
            chip.pack(side="left", padx=(0, 6), pady=1)
            tk.Label(chip, text=title, bg=bg, fg="#c8d6f0", font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(
                chip,
                text=money_text(amount),
                bg=bg,
                fg="#ffe08a" if amount else "#8a9bb8",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="e")

    def _make_tree(
        self,
        parent: ttk.Frame,
        columns: tuple[str, ...],
        meta: dict[str, tuple[str, int]],
        *,
        hierarchical: bool = False,
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        show = "tree headings" if hierarchical else "headings"
        tree = ttk.Treeview(frame, columns=columns, show=show, selectmode="extended")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        if hierarchical:
            tree.heading("#0", text="")
            tree.column("#0", width=28, minwidth=24, stretch=False, anchor="center")
        money_cols = {
            "net", "p8", "exempt", "f76a", "vat", "vat_22", "vat_95", "vat_5",
            "gross", "id", "zapst", "excluded",
        }
        for name in columns:
            title, width = meta[name]
            tree.heading(name, text=title, command=lambda c=name, t=tree: self._sort_tree(t, c, False))
            tree.column(
                name,
                width=width,
                minwidth=40,
                anchor=(
                    "e"
                    if name in money_cols
                    else "center"
                    if name in {"chk", "book", "status", "foreign", "region", "tip"}
                    else "w"
                ),
            )
        tree.tag_configure("odd", background="#101c31")
        tree.tag_configure("checked", background="#1d3a2a", foreground="#c8f7d4")
        tree.tag_configure("no_account", background="#5b3717", foreground="#fff0c7")
        tree.tag_configure("si_vat", background="#5a1c1c", foreground="#ffd0d0")
        tree.tag_configure("child", foreground="#9eb0d0")
        return tree

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.import_vasco())
        self.root.bind("<F5>", lambda _e: self.refresh_all())
        self.root.bind("<Control-f>", lambda _e: self._focus_active_search())

    # ------------------------------------------------------ session prefs
    @staticmethod
    def _session_bool(value: Any, *, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().casefold()
        if text in {"1", "true", "da", "yes", "on"}:
            return True
        if text in {"0", "false", "ne", "no", "off"}:
            return False
        return default

    def _restore_period_from_session(self) -> None:
        start = parse_iso_date(self._session.get("period_from"))
        end = parse_iso_date(self._session.get("period_to"))
        label = str(self._session.get("period_label") or "").strip()
        year_raw = str(self._session.get("period_year") or "").strip()
        if start and end and end >= start:
            self.filter_from_date, self.filter_to_date = start, end
            return
        if label:
            try:
                year = int(year_raw) if year_raw else previous_month_bounds()[0].year
            except ValueError:
                year = previous_month_bounds()[0].year
            bounds = period_bounds(year, label)
            if bounds:
                self.filter_from_date, self.filter_to_date = bounds

    def _restore_company_from_session(self) -> None:
        key = str(self._session.get("company_key") or "").strip()
        if not key:
            return
        company = find_company(self.companies, key)
        if not company:
            return
        self._suppress_company_select = True
        try:
            if self.company_tree.exists(key):
                self.company_tree.selection_set(key)
                self.company_tree.focus(key)
                self.company_tree.see(key)
        except tk.TclError:
            pass
        finally:
            self._suppress_company_select = False
        self.active_company = company
        self.company_var.set(f"Podjetje: {company_zst(company) or '—'} • {company_name(company)}")
        # Obnovi zadnje shranjeno obdobje — ne prepisuj s privzetim mesecem.
        start = parse_iso_date(self._session.get("period_from"))
        end = parse_iso_date(self._session.get("period_to"))
        if start and end and end >= start:
            self.filter_from_date, self.filter_to_date = start, end
            self._sync_period_filter_vars()
            label = period_label_for_range(start, end)
            self.filter_info_var.set(f"Zadnje obdobje: {label} {start.year}")
        else:
            self._apply_company_period_default(company)
        self._update_source_panel()
        # Ob zagonu: naloži SQL podjetja brez dodatnega dialoga.
        self._activate_company_db(company, load_data=True, confirm=False)

    def _persist_session(self) -> None:
        key = company_key(self.active_company) if self.active_company else ""
        save_session(
            {
                "company_key": key,
                "company_search": self.company_search_var.get().strip(),
                "period_from": self.filter_from_date.isoformat(),
                "period_to": self.filter_to_date.isoformat(),
                "period_label": period_label_for_range(self.filter_from_date, self.filter_to_date),
                "period_year": str(self.filter_from_date.year),
                "integra_sql_dir": self.integra_sql_var.get().strip(),
                "integra_auto_irpr": bool(self.integra_auto_irpr),
            }
        )
        self._session = {
            "company_key": key,
            "company_search": self.company_search_var.get().strip(),
            "period_from": self.filter_from_date.isoformat(),
            "period_to": self.filter_to_date.isoformat(),
            "period_label": period_label_for_range(self.filter_from_date, self.filter_to_date),
            "period_year": str(self.filter_from_date.year),
            "integra_sql_dir": self.integra_sql_var.get().strip(),
            "integra_auto_irpr": bool(self.integra_auto_irpr),
        }

    # ----------------------------------------------------------- period/filter
    def _apply_company_period_default(self, company: Mapping[str, Any] | None) -> None:
        """Mesečni zavezanec → prejšnji mesec; tromesečni → prejšnji kvartal."""
        if not company:
            return
        cadence = company_ddv_cadence(company)
        start, end = default_period_for_ddv_cadence(cadence)
        self.filter_from_date, self.filter_to_date = start, end
        self._sync_period_filter_vars()
        label = period_label_for_range(start, end)
        if cadence == "quarterly":
            self.filter_info_var.set(
                f"Tromesečni zavezanec · privzeto {format_si_date(start)} – {format_si_date(end)}"
            )
        elif cadence == "yearly":
            self.filter_info_var.set(
                f"Letni zavezanec · privzeto {format_si_date(start)} – {format_si_date(end)}"
            )
        else:
            self.filter_info_var.set(f"Mesečni zavezanec · privzeto {label} {start.year}")

    def _sync_period_filter_vars(self) -> None:
        self._period_filter_updating = True
        try:
            self.filter_month_var.set(period_label_for_range(self.filter_from_date, self.filter_to_date))
            self.filter_year_var.set(str(self.filter_from_date.year))
            self.filter_from_var.set(format_si_date(self.filter_from_date))
            self.filter_to_var.set(format_si_date(self.filter_to_date))
        finally:
            self._period_filter_updating = False

    def shift_period_filter(self, delta: int) -> None:
        label = period_label_for_range(self.filter_from_date, self.filter_to_date)
        try:
            index = PERIOD_CHOICES.index(label)
        except ValueError:
            index = max(0, self.filter_from_date.month - 1)
        index = (index + int(delta)) % len(PERIOD_CHOICES)
        bounds = period_bounds(self.filter_from_date.year, PERIOD_CHOICES[index]) or month_bounds(self.filter_from_date.year, self.filter_from_date.month)
        self.filter_from_date, self.filter_to_date = bounds
        self._sync_period_filter_vars()
        self.apply_period_filter()

    def _on_period_month_year_changed(self, _event: Any = None) -> None:
        if self._period_filter_updating:
            return
        try:
            year = int(str(self.filter_year_var.get()).strip())
        except ValueError:
            year = self.filter_from_date.year
        bounds = period_bounds(year, self.filter_month_var.get()) or month_bounds(year, self.filter_from_date.month)
        self.filter_from_date, self.filter_to_date = bounds
        self._sync_period_filter_vars()
        self.apply_period_filter()

    def _on_period_dates_changed(self, _event: Any = None) -> None:
        if self._period_filter_updating:
            return
        start = parse_si_date(self.filter_from_var.get())
        end = parse_si_date(self.filter_to_var.get())
        if start is None or end is None:
            return
        self.filter_from_date = start
        self.filter_to_date = end if end >= start else start
        self._sync_period_filter_vars()
        self.apply_period_filter()

    def reset_period_filter_to_data(self) -> None:
        if self.data_span_from and self.data_span_to:
            self.filter_from_date, self.filter_to_date = self.data_span_from, self.data_span_to
            self._sync_period_filter_vars()
        self.apply_period_filter()

    def apply_period_filter(self) -> None:
        start = parse_si_date(self.filter_from_var.get()) or self.filter_from_date
        end = parse_si_date(self.filter_to_var.get()) or self.filter_to_date
        if end < start:
            start, end = end, start
        self.filter_from_date, self.filter_to_date = start, end
        self._sync_period_filter_vars()
        self._refresh_period_rev_choices()
        self._persist_session()
        self._populate_ir_tree()
        self._populate_pr_tree()
        self._update_header_and_summary()
        self._refresh_knjige_and_ddvo()
        self._update_analysis()
        try:
            self.vse_knjizbe_tab.refresh()
        except Exception:
            pass

    def _period_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ir_rows = [
            row for row in self._ir_cache
            if self._row_in_period(row, date_keys=("document_date", "booking_date"))
        ]
        pr_rows = [
            row for row in self._pr_cache
            if self._row_in_period(row, date_keys=("received_date", "document_date", "booking_date"))
        ]
        return ir_rows, pr_rows

    def _refresh_knjige_and_ddvo(self) -> None:
        if not hasattr(self, "knjige_panel") or not hasattr(self, "ddvo_tab"):
            return
        ir_rows, pr_rows = self._period_rows()
        self.knjige_panel.refresh(
            ir_rows,
            pr_rows,
            filter_from=self.filter_from_date,
            filter_to=self.filter_to_date,
        )
        tax = company_tax(self.active_company) if self.active_company else ""
        name = company_name(self.active_company) if self.active_company else ""
        ddvo_ok: bool | None = None
        try:
            self.ddvo_tab.refresh(
                ir_rows,
                pr_rows,
                period_from=self.filter_from_date,
                period_to=self.filter_to_date,
                company_tax=tax,
                company_name=name,
                company=self.active_company,
            )
            ctrl = self.ddvo_tab.control_var.get()
            ddvo_ok = ctrl.startswith("Kontrola OK")
            self.knjige_panel.set_ddvo_status(
                "DDV-O — KONTROLA OK" if ddvo_ok else ctrl.split("•")[0].strip() or "DDV-O",
                ok=ddvo_ok,
            )
            self.notebook.tab(
                2,
                text="  DDV-O • KONTROLA OK  " if ddvo_ok else "  DDV-O • PREVERI  ",
            )
        except Exception as exc:
            self.ddvo_tab.control_var.set(f"DDV-O izračun ni uspel: {exc}")
            self.knjige_panel.set_ddvo_status(f"DDV-O — napaka: {exc}", ok=False)
        self.notebook.tab(3, text=self.knjige_panel.tab_title())
        if hasattr(self, "konti_tab"):
            try:
                self.konti_tab.refresh(
                    ir_rows,
                    pr_rows,
                    period_from=self.filter_from_date,
                    period_to=self.filter_to_date,
                )
                self.notebook.tab(4, text=self.konti_tab.tab_title())
            except Exception as exc:
                self.status_var.set(f"KONTI: {exc}")

    def _selected_period_rev(self) -> int | None:
        raw = str(self.filter_rev_var.get() or "vse").strip().casefold()
        if raw in {"", "vse", "all"}:
            return None
        if raw in {"osnovni", "1"}:
            return 1
        digits = re.sub(r"\D", "", raw)
        return int(digits) if digits else None

    def _row_matches_period_rev(self, row: Mapping[str, Any]) -> bool:
        wanted = self._selected_period_rev()
        if wanted is None:
            return True
        return max(1, int(row.get("period_rev") or 1)) == wanted

    def _refresh_period_rev_choices(self, preferred: int | None = None) -> None:
        combo = getattr(self, "filter_rev_combo", None)
        if combo is None:
            return
        try:
            revs = self.db.list_period_revisions(self.filter_from_date, self.filter_to_date)
        except Exception:
            revs = []
        labels = ["vse"]
        for rev in revs:
            labels.append("osnovni" if rev <= 1 else f"-{rev}")
        combo.configure(values=tuple(labels))
        current = str(self.filter_rev_var.get() or "vse")
        if preferred is not None:
            want = "osnovni" if preferred <= 1 else f"-{preferred}"
            if want in labels:
                self.filter_rev_var.set(want)
                return
        if current not in labels:
            self.filter_rev_var.set("vse")

    def _row_in_period(self, row: dict[str, Any], *, date_keys: tuple[str, ...]) -> bool:
        if not self._row_matches_period_rev(row):
            return False
        for key in date_keys:
            raw = row.get(key)
            if not raw:
                continue
            try:
                parsed = parse_date(raw)
            except Exception:
                parsed = None
            if parsed is None:
                continue
            return self.filter_from_date <= parsed <= self.filter_to_date
        return True

    # -------------------------------------------------------------- companies
    def _populate_company_tree(self) -> None:
        self.company_tree.delete(*self.company_tree.get_children())
        query = re.sub(r"\s+", " ", self.company_search_var.get().strip().casefold())
        terms = query.split() if query else []
        for company in self.companies:
            zst = company_zst(company)
            name = company_name(company)
            org = company_org_id(company)
            tax = company_tax(company)
            haystack = " ".join((zst, name, tax, org)).casefold()
            if terms and any(term not in haystack for term in terms):
                continue
            self.company_tree.insert("", "end", iid=company_key(company), values=(zst or "—", name, org or "—"))

    def _on_company_select(self, _event: tk.Event | None = None) -> None:
        if self._suppress_company_select:
            return
        selection = self.company_tree.selection()
        if not selection:
            return
        company = find_company(self.companies, selection[0])
        if not company:
            return
        key = company_key(company)
        # Ista firma že aktivna z naloženimi podatki — ne sprašuj znova.
        if key == self._company_db_key and self.active_company and company_key(self.active_company) == key:
            if self._ir_cache or self._pr_cache or self._party_cache:
                return
        self.active_company = company
        self.company_var.set(f"Podjetje: {company_zst(company) or '—'} • {company_name(company)}")
        self._apply_company_period_default(company)
        self._clear_data_view()
        self._update_source_panel()
        self.status_var.set(f"Izbrano: {company_name(company)} — potrdi nalaganje iz SQLite")
        self._activate_company_db(company, load_data=True, confirm=True)
        self._persist_session()
        self.root.after(30, self._warm_account_combos)

    def _clear_data_view(self) -> None:
        """Izprazni IR/PR/stranke prikaze (pred menjavo / nalaganjem firme)."""
        self._ir_cache = []
        self._pr_cache = []
        self._party_cache = []
        self.chk_state.clear()
        self._last_vat_reports = {}
        self.data_span_from = None
        self.data_span_to = None
        for tree_name in ("ir_tree", "pr_tree", "party_tree"):
            tree = getattr(self, tree_name, None)
            if tree is not None:
                try:
                    tree.delete(*tree.get_children())
                except tk.TclError:
                    pass
        try:
            self._update_header_and_summary()
        except Exception:
            pass
        try:
            self._refresh_knjige_and_ddvo()
        except Exception:
            pass

    def _activate_company_db(
        self,
        company: Mapping[str, Any],
        *,
        load_data: bool,
        confirm: bool,
    ) -> None:
        """Preklopi SQLite na podjetje; ob potrditvi naloži podatke (ali uvoz/API hint)."""
        zst = company_zst(company)
        name = company_name(company)
        path = company_db_path(zst)
        key = company_key(company)

        clear_account_cache()
        self.db = Database(path)
        self._company_db_key = key
        from trops_studio.vat_api_check import load_company_vat_reports

        self._last_vat_reports = load_company_vat_reports(zst)
        self.status_var.set(f"SQLite: {self.db.path}")
        self._restore_last_vasco_import()
        self._update_ir_book_filters_for_company()

        if confirm:
            exists = path.is_file() and path.stat().st_size > 0
            detail = f"SQLite:\n{path}"
            if exists:
                detail += "\n\nDatoteka obstaja — naložim IR/PR/stranke, če so že v bazi."
            else:
                detail += "\n\nBaza je prazna / nova — sledi uvoz ali Minimax API."
            if not messagebox.askyesno(
                "Podjetje",
                f"Naložim podatke za:\n{zst or '—'} • {name}\n\n{detail}",
                parent=self.root,
            ):
                self.status_var.set(f"Firma {name}: prikaz prazen (nalaganje preklicano). SQL: {path.name}")
                return

        if not load_data:
            return

        self.refresh_all()
        has_rows = bool(self._ir_cache or self._pr_cache)
        has_parties = bool(self._party_cache)
        if has_rows:
            self.status_var.set(
                f"{name}: SQL IR {len(self._ir_cache)} / PR {len(self._pr_cache)} / "
                f"stranke {len(self._party_cache)}"
            )
            return

        self._prompt_empty_company_source(has_parties=has_parties)

    def _prompt_empty_company_source(self, *, has_parties: bool = False) -> None:
        """Ni IR/PR v SQL → napoti na uvoz ali Minimax API."""
        kind = company_source_kind(self.active_company)
        name = company_name(self.active_company or {})
        parties_note = (
            f"\nStranke v SQL: {len(self._party_cache)} (lahko že iz Minimax pull)."
            if has_parties
            else "\nStranke: prazno — lahko Minimax↓ stranke."
        )
        if kind == "projest":
            body = (
                f"Za {name} v SQLite ni IR/PR.\n\n"
                "Naprej:\n"
                "  • Vir/poti → Uvozi Vasco (ali Uvozi KIR/KPR)\n"
                "  • ali Minimax↓ stranke / Minimax API"
            )
        elif kind == "integra":
            body = (
                f"Za {name} v SQLite ni IR/PR.\n\n"
                "Naprej:\n"
                "  • Vir/poti → SQL pot + gumb Integra\n"
                "  • ali Uvozi KIR/KPR / Minimax API"
            )
        else:
            body = (
                f"Za {name} v SQLite ni IR/PR.\n\n"
                "Naprej:\n"
                "  • Vir/poti → Uvozi KIR/KPR (FURS ZIP/JSON)\n"
                "  • ali Minimax↓ stranke / Minimax API"
            )
        self.status_var.set(f"{name}: SQL prazen — uvoz ali Minimax API")
        messagebox.showinfo("Ni podatkov v SQLite", body + parties_note, parent=self.root)

    def _available_ir_books(self) -> tuple[str, ...]:
        """IR knjige: Integra = Paragoni/Fakture(+KIR); kirkpr = KIR; Projest = vse."""
        kind = company_source_kind(self.active_company)
        if kind == "integra":
            return ("Paragoni", "Fakture", "KIR") if "KIR" in IR_BOOKS else ("Paragoni", "Fakture")
        if kind == "kirkpr":
            return ("KIR",) if "KIR" in IR_BOOKS else IR_BOOKS
        return IR_BOOKS

    def _update_ir_book_filters_for_company(self) -> None:
        """Projest: Darila/Fitness; Integra: Paragoni/Fakture; kirkpr: KIR."""
        frame = getattr(self, "_ir_books_projest", None)
        btn = getattr(self, "_ir_btn_darila_fitness", None)
        if frame is None:
            return
        kind = company_source_kind(self.active_company)
        prev = getattr(self, "_ir_books_kind_shown", None)
        changed = kind != prev
        self._ir_books_kind_shown = kind

        if kind == "integra":
            if frame.winfo_manager():
                frame.pack_forget()
            if btn is not None and btn.winfo_manager():
                btn.pack_forget()
            if changed:
                for book, var in self.ir_book_vars.items():
                    var.set(book in {"Paragoni", "Fakture", "KIR"})
        elif kind == "kirkpr":
            if frame.winfo_manager():
                frame.pack_forget()
            if btn is not None and btn.winfo_manager():
                btn.pack_forget()
            if changed:
                for book, var in self.ir_book_vars.items():
                    var.set(book == "KIR")
        else:
            anchor = getattr(self, "_ir_book_paragoni_chk", None)
            if not frame.winfo_manager():
                if anchor is not None:
                    frame.pack(side="left", before=anchor)
                else:
                    frame.pack(side="left")
            if btn is not None and not btn.winfo_manager():
                before = getattr(self, "_ir_btn_vse_oznaci", None)
                if before is not None:
                    btn.pack(side="left", padx=(0, 10), before=before)
                else:
                    btn.pack(side="left", padx=(0, 10))
            if changed:
                for book, var in self.ir_book_vars.items():
                    var.set(book in {"Darila", "Fitness"})
        if changed:
            try:
                self._populate_ir_tree()
            except Exception:
                pass

    def _update_source_panel(self) -> None:
        """Vir/poti vedno viden: Projest / Integra / KIR/KPR (ostale firme)."""
        kind = company_source_kind(self.active_company) if self.active_company else "kirkpr"
        self._update_ir_book_filters_for_company()
        sec = getattr(self, "ui_source_section", None)
        if sec is None:
            return
        summary = getattr(self, "ui_summary_section", None)
        period = getattr(self, "ui_period_section", None)

        if not getattr(self, "_source_visible", False):
            pack_kwargs: dict[str, Any] = {"fill": "x", "pady": (12, 0)}
            if period is not None and period.winfo_manager():
                pack_kwargs["before"] = period
            elif summary is not None and summary.winfo_manager():
                pack_kwargs["before"] = summary
            sec.pack(**pack_kwargs)
            self._source_visible = True

        if kind == getattr(self, "_source_kind_shown", None):
            return

        self._source_projest.pack_forget()
        self._source_integra.pack_forget()
        if getattr(self, "_source_kirkpr", None) is not None:
            self._source_kirkpr.pack_forget()
        if kind == "projest":
            self.ir_darila_var.set(str(DEFAULT_IR_DARILA))
            self.ir_fitnes_var.set(str(DEFAULT_IR_FITNES))
            self.pr_var.set(str(DEFAULT_PR))
            self.source_var.set("Uvozi Vasco (IF* / kp*) v SQLite delovno bazo.")
            self.format_var.set("Vir: Vasco → SQLite")
            self._restore_last_vasco_import()
            self._source_projest.pack(fill="x")
        elif kind == "integra":
            if not self.integra_sql_var.get().strip():
                self.integra_sql_var.set(str(DEFAULT_INTEGRA_SQL))
            self.source_var.set("SQL TROPS → SQLite (brez kisanal.dbf / popa.dbf).")
            self.format_var.set("Vir: SQL TROPS → SQLite")
            self._source_integra.pack(fill="x")
        else:
            # kirkpr — KLUG in ostale firme
            self.source_var.set("Uvozi FURS KIR/KPR (ZIP/JSON/XML/CSV) v SQLite.")
            self.format_var.set("Vir: FURS KIR/KPR → SQLite")
            if getattr(self, "_source_kirkpr", None) is not None:
                self._source_kirkpr.pack(fill="x")
        self._source_kind_shown = kind

    def _choose_integra_sql_dir(self) -> None:
        initial = Path(self.integra_sql_var.get().strip() or str(DEFAULT_INTEGRA_SQL))
        folder = filedialog.askdirectory(
            parent=self.root,
            title="Mapa SQL TROPS (Integra)",
            initialdir=str(initial if initial.is_dir() else initial.parent),
        )
        if folder:
            self.integra_sql_var.set(folder)
            self._persist_session()

    def _integra_source_action(self) -> None:
        """Odpri formo Integra (ZIP/BAK → SQL TROPS → …)."""
        from trops_studio.ui.integra_dialog import IntegraDialog

        def _sync_sql_dir(path: str) -> None:
            self.integra_sql_var.set(path)
            self._persist_session()

        def _sync_auto_irpr(enabled: bool) -> None:
            self.integra_auto_irpr = bool(enabled)
            self._persist_session()

        def _open_vse_knjizbe() -> None:
            try:
                self.notebook.select(7)
                self.vse_knjizbe_tab.refresh()
            except Exception:
                pass

        IntegraDialog(
            self.root,
            sql_dir=self.integra_sql_var.get().strip() or str(DEFAULT_INTEGRA_SQL),
            on_sql_dir_changed=_sync_sql_dir,
            auto_irpr_default=self.integra_auto_irpr,
            on_auto_irpr_changed=_sync_auto_irpr,
            on_open_vse_knjizbe=_open_vse_knjizbe,
        )
        self._persist_session()

    def _on_navigation_select(self, _event: tk.Event | None = None) -> None:
        item = (self.nav_tree.selection() or [""])[0]
        mapping = {
            "nav:ir": 0,
            "nav:pr": 1,
            "nav:ddvo": 2,
            "nav:knjige": 3,
            "nav:knjiga_ir": 3,
            "nav:knjiga_pr": 3,
            "nav:konti": 4,
            "nav:parties": 5,
            "nav:analysis": 6,
            "nav:knjizbe": 7,
        }
        if item in mapping:
            self.notebook.select(mapping[item])
            if item in {"nav:knjige", "nav:knjiga_ir"}:
                self.knjige_panel.select_book("IR")
            elif item == "nav:knjiga_pr":
                self.knjige_panel.select_book("PR")
            elif item in {"nav:ddvo", "nav:konti"}:
                self._refresh_knjige_and_ddvo()
            elif item == "nav:analysis":
                self._update_analysis()
            elif item == "nav:knjizbe":
                try:
                    self.vse_knjizbe_tab.refresh()
                except Exception:
                    pass

    # --------------------------------------------------------------- populate
    def refresh_all(self, *, rebuild_journals: bool = False) -> None:
        """Osveži prikaz. Knjižbe se ne pregrajujejo (že ob shrani vrstice)."""
        if rebuild_journals:
            try:
                repair_pr_eu_rows(self.db)
            except Exception:
                pass
            try:
                rebuilt = self.db.rebuild_all_journal_lines()
                self.status_var.set(
                    f"Osveženo · knjižbe IR {rebuilt.get('ir_docs', 0)} / "
                    f"PR {rebuilt.get('pr_docs', 0)} (DDV konti 160/260)"
                )
            except Exception:
                pass
        self._ir_cache = self.db.list_ir()
        self._pr_cache = self.db.list_pr()
        self._refresh_period_rev_choices()
        self._party_cache = self.db.list_parties()
        for row in self._ir_cache:
            self.chk_state.setdefault(f"ir:{row['id']}", False)
        for row in self._pr_cache:
            self.chk_state.setdefault(f"pr:{row['id']}", False)
        for row in self._party_cache:
            self.chk_state.setdefault(f"party:{row['id']}", False)
        self._compute_data_span()
        self._populate_ir_tree()
        self._populate_pr_tree()
        self._populate_parties_tree()
        self._refresh_pending_mm_async()
        self._update_header_and_summary()
        self._update_analysis()
        self._refresh_knjige_and_ddvo()
        try:
            self.vse_knjizbe_tab.refresh()
        except Exception:
            pass

    def refresh_after_edit(self, kind: str) -> None:
        """Po shrani ene vrstice: samo ta knjiga + povzetek (brez pregradnje vseh knjižb)."""
        kind_u = kind.upper()
        if kind_u == "IR":
            self._ir_cache = self.db.list_ir()
            for row in self._ir_cache:
                self.chk_state.setdefault(f"ir:{row['id']}", False)
            self._populate_ir_tree()
        else:
            self._pr_cache = self.db.list_pr()
            for row in self._pr_cache:
                self.chk_state.setdefault(f"pr:{row['id']}", False)
            self._populate_pr_tree()
        self._update_header_and_summary()
        self._refresh_knjige_and_ddvo()

    def _compute_data_span(self) -> None:
        dates: list[date] = []
        for row in self._ir_cache:
            for key in ("document_date", "booking_date"):
                try:
                    parsed = parse_date(row.get(key))
                except Exception:
                    parsed = None
                if parsed:
                    dates.append(parsed)
        for row in self._pr_cache:
            for key in ("received_date", "document_date", "booking_date"):
                try:
                    parsed = parse_date(row.get(key))
                except Exception:
                    parsed = None
                if parsed:
                    dates.append(parsed)
        if dates:
            self.data_span_from, self.data_span_to = min(dates), max(dates)

    def _active_ir_books(self) -> set[str]:
        return {book for book, var in self.ir_book_vars.items() if var.get()}

    def _populate_ir_tree(self) -> None:
        tree = self.ir_tree
        tree.delete(*tree.get_children())
        tokens = search_tokens(self.ir_search_var.get())
        books = self._active_ir_books()
        status_filter = self.ir_status_filter.get()
        nonzero_only = self.ir_amount_filter.get() == "NONZERO"
        only_si = bool(self.ir_filter_si.get())
        only_eu = bool(self.ir_filter_eu.get())
        only_third = bool(self.ir_filter_foreign.get())
        only_vat = bool(self.ir_filter_vat.get())
        any_region = only_si or only_eu or only_third
        parties_by_vat = self._party_by_vat_index()
        parties_by_id = self._party_by_id_index()
        visible = 0
        totals = {
            "net": Decimal("0"),
            "eu_12": Decimal("0"),
            "vat_22": Decimal("0"),
            "vat_95": Decimal("0"),
            "vat": Decimal("0"),
            "gross": Decimal("0"),
        }
        for row in self._ir_cache:
            book = str(row.get("book") or "")
            if books and book not in books:
                continue
            if not self._row_in_period(row, date_keys=("document_date", "booking_date")):
                continue
            key = f"ir:{row['id']}"
            checked = bool(self.chk_state.get(key))
            if status_filter == "CHK" and not checked:
                continue
            if status_filter not in {"VSI", "CHK"} and not status_filter_matches(
                row.get("status"), status_filter, has_account=bool(row.get("account"))
            ):
                continue
            party = self._party_for_pr_row(row, by_vat=parties_by_vat, by_id=parties_by_id)
            classified = apply_ir_eu_sale(row, party)
            region = ir_customer_region(classified, party)
            if any_region:
                if not (
                    (only_si and region == "SI")
                    or (only_eu and region == "EU")
                    or (only_third and region == "FOREIGN")
                ):
                    continue
            if only_vat and not normalize_vat_id(row.get("vat_id")):
                continue
            vat_22 = decimal_value(classified.get("vat_22"))
            vat_95 = decimal_value(classified.get("vat_95"))
            vat = vat_22 + vat_95
            net = ir_display_osnova(classified)
            eu_goods = decimal_value(classified.get("eu_goods"))
            gross = decimal_value(classified.get("total"))
            if not is_nonzero(gross):
                gross = net + vat
            if nonzero_only and not (is_nonzero(net) or is_nonzero(vat) or is_nonzero(gross)):
                continue
            chunks = row_search_chunks(
                row,
                extra=(
                    "IR",
                    book,
                    region_label(region),
                    money_text(net),
                    money_text(vat),
                    money_text(vat_22),
                    money_text(vat_95),
                    "☑" if checked else "☐",
                ),
            )
            if not haystack_matches(tokens, chunks):
                continue
            tags = ("checked",) if checked else (("odd",) if visible % 2 else ())
            tree.insert(
                "", "end", iid=key, tags=tags,
                values=(
                    "☑" if checked else "☐",
                    row.get("seq", ""),
                    book,
                    date_text(row.get("document_date")),
                    row.get("document_no", ""),
                    row.get("party_name", ""),
                    row.get("vat_id", ""),
                    money_text(net),
                    money_text(vat_22),
                    money_text(vat_95),
                    money_text(vat),
                    money_text(gross),
                    region_label(region),
                    classified.get("account", ""),
                    row.get("status", ""),
                ),
            )
            visible += 1
            totals["net"] += net
            totals["eu_12"] += eu_goods
            totals["vat_22"] += vat_22
            totals["vat_95"] += vat_95
            totals["vat"] += vat
            totals["gross"] += gross
        self._render_list_totals(
            self.ir_totals_inner,
            (
                ("Osnova", totals["net"]),
                ("12 — EU", totals["eu_12"]),
                ("DDV 22%", totals["vat_22"]),
                ("DDV 9,5%", totals["vat_95"]),
                ("DDV", totals["vat"]),
                ("Skupaj", totals["gross"]),
            ),
            show_zeros=True,
        )
        self.summary_vars["ir_count"].set(str(visible))
        self.summary_vars["ir_value"].set(f"{money_text(totals['net'])} EUR")
        self.notebook.tab(0, text=f"  Izdani računi (IR)  {visible}  ")
        self.ir_selection_var.set("Izbranih IR: 0")
        self.filter_info_var.set(
            f"Filter {format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)}"
            f" • IR {visible}/{len(self._ir_cache)}"
            f" • knjige: {', '.join(sorted(books)) or '—'}"
        )

    def _party_by_vat_index(self) -> dict[str, dict[str, Any]]:
        idx: dict[str, dict[str, Any]] = {}
        for party in self._party_cache:
            vat = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
            if vat and vat not in idx:
                idx[vat] = party
        return idx

    def _party_by_id_index(self) -> dict[int, dict[str, Any]]:
        idx: dict[int, dict[str, Any]] = {}
        for party in self._party_cache:
            try:
                pid = int(party["id"])
            except (KeyError, TypeError, ValueError):
                continue
            idx[pid] = party
        return idx

    def _party_for_pr_row(
        self,
        row: Mapping[str, Any],
        *,
        by_vat: dict[str, dict[str, Any]] | None = None,
        by_id: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Stranka za PR: najprej party_id, nato DDV (prazen DDV sicer skrije tujca)."""
        if by_id is None:
            by_id = self._party_by_id_index()
        if by_vat is None:
            by_vat = self._party_by_vat_index()
        if row.get("party_id"):
            try:
                party = by_id.get(int(row["party_id"]))
            except (TypeError, ValueError):
                party = None
            if party:
                return party
        vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        if vat:
            return by_vat.get(vat)
        return None

    def _populate_pr_tree(self) -> None:
        tree = self.pr_tree
        tree.delete(*tree.get_children())
        tokens = search_tokens(self.pr_search_var.get())
        status_filter = self.pr_status_filter.get()
        nonzero_only = self.pr_amount_filter.get() == "NONZERO"
        only_si = bool(self.pr_filter_si.get())
        only_third = bool(self.pr_filter_foreign.get())
        only_excluded = bool(self.pr_filter_excluded.get())
        only_eu10 = bool(self.pr_filter_eu10.get())
        only_eu11 = bool(self.pr_filter_eu11.get())
        only_exempt = bool(self.pr_filter_exempt.get())
        only_76a = bool(self.pr_filter_76a.get())
        only_multi = bool(self.pr_filter_multi.get())
        only_si_vat = bool(self.pr_filter_si_vat.get())
        only_vat = bool(self.pr_filter_vat.get())
        parties_by_vat = self._party_by_vat_index()
        parties_by_id = self._party_by_id_index()
        visible = 0
        si_vat_hits = 0
        totals = {
            "net": Decimal("0"),
            "p8": Decimal("0"),
            "exempt": Decimal("0"),
            "f76a": Decimal("0"),
            "eu_10": Decimal("0"),
            "eu_11": Decimal("0"),
            "vat_22": Decimal("0"),
            "vat_95": Decimal("0"),
            "vat_5": Decimal("0"),
            "vat": Decimal("0"),
            "excluded": Decimal("0"),
        }
        for row in self._pr_cache:
            if not self._row_in_period(row, date_keys=("received_date", "document_date", "booking_date")):
                continue
            key = f"pr:{row['id']}"
            checked = bool(self.chk_state.get(key))
            excluded_amt = decimal_value(row.get("excluded"))
            exempt_amt = (
                decimal_value(row.get("exempt_on"))
                + decimal_value(row.get("exempt_non"))
                + decimal_value(row.get("exempt_os"))
            )
            f76a_amt = decimal_value(row.get("f76a"))
            acc = allocate_pr_accounts(row)
            odhodek = acc["odhodek01"]
            odhodek07 = acc["odhodek07"]
            eu_g = decimal_value(row.get("eu_goods"))
            eu_s = decimal_value(row.get("eu_services"))
            has_eu10 = is_nonzero(eu_g)
            has_eu11 = is_nonzero(eu_s)
            has_eu_purchase = has_eu10 or has_eu11
            has_excl = is_nonzero(excluded_amt)
            has_exempt = is_nonzero(exempt_amt)
            has_76a = is_nonzero(f76a_amt)
            # Konti 10/11 samo če P10/P11 <> 0 (tudi storno)
            odhodek10 = acc["odhodek10"] if has_eu10 else ""
            odhodek11 = acc["odhodek11"] if has_eu11 else ""
            odhodek_excl = acc["odhodek_excluded"] if has_excl else ""
            lines = pr_odhodek_lines(row)
            party = self._party_for_pr_row(row, by_vat=parties_by_vat, by_id=parties_by_id)
            # Regija po državi (US/CN = tretja), ne po P10/P11
            geo = pr_supplier_region(row, party)
            si_vat_err = pr_si_vat_on_non_domestic(row, party)
            region = pr_corrected_region(row, party) if si_vat_err else geo

            has_acc = bool(odhodek or odhodek10 or odhodek11 or (has_excl and odhodek_excl))
            if only_vat and not normalize_vat_id(row.get("vat_id")):
                continue
            if status_filter == "CHK" and not checked:
                continue
            if status_filter == "NO_ACCOUNT" and has_acc:
                continue
            if status_filter not in {"VSI", "CHK", "NO_ACCOUNT"} and not status_filter_matches(
                row.get("status"), status_filter, has_account=has_acc
            ):
                continue
            # Vse kljukice = OR. Brez označbe = vse.
            # Tretje države = samo izven EU (regija FOREIGN), nikoli EU 10/11 ali SI/AT/DE.
            tips = {str(line.get("tip") or "") for line in lines}
            has_book_base = bool(tips & {"08", "14", "9a"})
            any_bucket = (
                only_si or only_third or only_eu10 or only_eu11
                or only_exempt or only_76a
                or only_excluded or only_multi or only_si_vat
            )
            if any_bucket:
                bucket_ok = False
                if (
                    only_si
                    and region == "SI"
                    and not has_eu_purchase
                    and has_book_base
                    and not si_vat_err
                ):
                    bucket_ok = True
                if only_third and region == "FOREIGN":
                    bucket_ok = True
                if only_eu10 and has_eu10 and region == "EU":
                    bucket_ok = True
                if only_eu11 and has_eu11 and region == "EU":
                    bucket_ok = True
                if only_exempt and has_exempt:
                    bucket_ok = True
                if only_76a and has_76a:
                    bucket_ok = True
                if only_excluded and has_excl:
                    bucket_ok = True
                if only_multi and len(lines) >= 2:
                    bucket_ok = True
                if only_si_vat and si_vat_err:
                    bucket_ok = True
                if not bucket_ok:
                    continue

            vat_22 = decimal_value(row.get("vat_22"))
            vat_95 = decimal_value(row.get("vat_95"))
            vat_5 = decimal_value(row.get("vat_5"))
            vat = vat_22 + vat_95 + vat_5
            # 8 = SI + tretje države (Excel F8); Osnova = F8 + EU 10/11
            # 5 % (F27) je »od tega« v F8, ne prištevek. 14 in 76.a sta ločena.
            p8_amt = pr_p8_amount(row, region)
            f8 = decimal_value(row.get("net_taxable"))
            if not is_nonzero(f8):
                f8 = decimal_value(row.get("base_5"))
            osnova = f8 + eu_g + eu_s
            if nonzero_only and not (
                is_nonzero(p8_amt)
                or is_nonzero(osnova)
                or is_nonzero(vat)
                or has_excl
                or has_exempt
                or has_76a
            ):
                continue
            chunks = row_search_chunks(
                row,
                extra=(
                    "PR",
                    region_label(region),
                    money_text(p8_amt),
                    money_text(osnova),
                    money_text(exempt_amt),
                    money_text(f76a_amt),
                    money_text(vat),
                    money_text(excluded_amt),
                    "oproščeno",
                    "14",
                    "76.a",
                    "☑" if checked else "☐",
                    odhodek,
                    odhodek07,
                    odhodek10,
                    odhodek11,
                    odhodek_excl,
                    odhodek_summary(lines),
                    "SI+DŠ" if si_vat_err else "",
                ),
            )
            if not haystack_matches(tokens, chunks):
                continue
            if si_vat_err:
                tags = ("si_vat",)
            elif checked:
                tags = ("checked",)
            elif not has_acc:
                tags = ("no_account",)
            else:
                tags = ("odd",) if visible % 2 else ()
            multi = len(lines) > 1
            # stolpec Odhodek01: pri EU-only pokaži konto 10/11
            odhodek_display = odhodek
            if not odhodek_display:
                odhodek_display = odhodek_summary(lines) if multi else (odhodek10 or odhodek11 or "")
            parent_values = (
                "☑" if checked else "☐",
                row.get("seq", ""),
                date_text(row.get("received_date")),
                row.get("document_no", ""),
                row.get("internal_no", ""),
                row.get("supplier_name", ""),
                row.get("vat_id", ""),
                ("EU · SI+DŠ" if si_vat_err and region == "EU" else (
                    "Tretja · SI+DŠ" if si_vat_err else region_label(region)
                )),
                f"{len(lines)}×" if multi else (lines[0]["tip"] if lines else ""),
                money_text(p8_amt) if is_nonzero(p8_amt) else "",
                money_text(osnova) if is_nonzero(osnova) else "",
                money_text(exempt_amt) if has_exempt else "",
                money_text(f76a_amt) if has_76a else "",
                money_text(vat_22),
                money_text(vat_95),
                money_text(vat_5),
                money_text(vat),
                money_text(excluded_amt) if has_excl else "",
                odhodek_display if not multi else odhodek_summary(lines),
                odhodek07,
                odhodek10,
                odhodek11,
                odhodek_excl if has_excl or odhodek_excl else "",
                row.get("placilo", ""),
                row.get("status", ""),
            )
            tree.insert(
                "",
                "end",
                iid=key,
                text="" if multi else "",
                open=False,
                tags=tags,
                values=parent_values,
            )
            if multi:
                p8_tips = {"08", "10", "11"} if region == "FOREIGN" else ({"08"} if region == "SI" else set())
                for line in lines:
                    tip = str(line["tip"])
                    child_iid = f"{key}:line:{tip}"
                    konto = str(line.get("konto") or "")
                    amt = money_text(line["amount"])
                    tree.insert(
                        key,
                        "end",
                        iid=child_iid,
                        text="·",
                        tags=("child",),
                        values=(
                            "",
                            "",
                            "",
                            "",
                            "",
                            line["label"],
                            "",
                            "",
                            tip,
                            amt if tip in p8_tips else "",
                            amt if tip in {"08", "10", "11"} else "",
                            amt if tip == "14" else "",
                            amt if tip == "9a" else "",
                            "",
                            "",
                            "",
                            "",
                            amt if tip == "excl" else "",
                            konto if tip == "08" else "",
                            konto if tip in {"14", "9a"} else "",
                            konto if tip == "10" else "",
                            konto if tip == "11" else "",
                            konto if tip == "excl" else "",
                            "",
                            "",
                        ),
                    )
            visible += 1
            if si_vat_err:
                si_vat_hits += 1
            totals["net"] += osnova
            totals["p8"] += p8_amt
            totals["exempt"] += exempt_amt
            totals["f76a"] += f76a_amt
            if region == "EU":
                totals["eu_10"] += eu_g
                totals["eu_11"] += eu_s
            totals["vat_22"] += vat_22
            totals["vat_95"] += vat_95
            totals["vat_5"] += vat_5
            totals["vat"] += vat
            totals["excluded"] += excluded_amt
        self._render_list_totals(
            self.pr_totals_inner,
            (
                ("Osnova", totals["net"]),
                ("8 — domači in tretje drž.", totals["p8"]),
                ("14 — oproščeno", totals["exempt"]),
                ("76.a", totals["f76a"]),
                ("10 — BL EU", totals["eu_10"]),
                ("11 — ST EU", totals["eu_11"]),
                ("DDV 22%", totals["vat_22"]),
                ("DDV 9,5%", totals["vat_95"]),
                ("DDV 5%", totals["vat_5"]),
                ("DDV", totals["vat"]),
                ("Ne gre €", totals["excluded"]),
            ),
            show_zeros=True,
        )
        self.summary_vars["pr_count"].set(str(visible))
        self.summary_vars["pr_value"].set(
            f"{money_text(totals['net'] + totals['exempt'] + totals['f76a'] + totals['excluded'])} EUR"
        )
        self.notebook.tab(1, text=f"  Prejeti računi (PR)  {visible}  ")
        self.pr_selection_var.set("Izbranih PR: 0")
        if si_vat_hits:
            self.status_var.set(
                f"PR kontrola: {si_vat_hits}× ni Domači, a ima ID za DDV SI+DŠ "
                f"(filter »SI+DŠ na EU«)."
            )

    def _populate_parties_tree(self) -> None:
        tree = self.party_tree
        tree.delete(*tree.get_children())
        tokens = search_tokens(self.party_search_var.get())
        visible = 0
        checked_n = 0
        for row in self._party_cache:
            key = f"party:{row['id']}"
            checked = bool(self.chk_state.get(key))
            chunks = row_search_chunks(
                row, extra=("stranka", "☑" if checked else "☐", str(row.get("minimax_code") or ""))
            )
            if not haystack_matches(tokens, chunks):
                continue
            tags = ("checked",) if checked else (("odd",) if visible % 2 else ())
            tree.insert(
                "",
                "end",
                iid=key,
                tags=tags,
                values=(
                    "☑" if checked else "☐",
                    row["id"],
                    row.get("name", ""),
                    row.get("vat_id", ""),
                    row.get("minimax_code", ""),
                    row.get("country", ""),
                    row.get("city", ""),
                    "DA" if row.get("is_foreign") else "NE",
                    row.get("source", ""),
                ),
            )
            visible += 1
            if checked:
                checked_n += 1
        self.summary_vars["parties"].set(str(visible))
        self._set_pending_mm_label()
        self.notebook.tab(5, text=f"  Stranke  {visible}  ")
        if hasattr(self, "party_selection_var"):
            self.party_selection_var.set(f"Označenih: {checked_n}")

    def _set_pending_mm_label(self) -> None:
        pending_mm = getattr(self, "_pending_mm", None)
        if pending_mm is None:
            text = "Minimax · preverjam šifrant …"
        elif pending_mm:
            text = f"Minimax · manjka šifra {pending_mm}"
        else:
            text = "Minimax šifrant usklajen"
        self.summary_vars["parties_detail"].set(text)

    def _refresh_pending_mm_async(self) -> None:
        """Število strank brez MM šifre (počasno ujemanje nazivov) — v ozadju, ne ob vsakem filtru."""
        self._pending_mm_gen = getattr(self, "_pending_mm_gen", 0) + 1
        gen = self._pending_mm_gen
        db = self.db

        def work() -> None:
            try:
                count: int | None = len(collect_firms_needing_minimax(db))
            except Exception:
                count = None

            def apply() -> None:
                if gen != self._pending_mm_gen or count is None:
                    return
                self._pending_mm = count
                self._set_pending_mm_label()

            try:
                self.root.after(0, apply)
            except Exception:
                pass

        def start() -> None:
            if gen == self._pending_mm_gen:
                threading.Thread(target=work, daemon=True, name="mm-pending-count").start()

        # najprej izriši okno — izračun je CPU (GIL) in bi upočasnil odpiranje
        self.root.after(800, start)

    def _update_header_and_summary(self) -> None:
        counts = self.db.counts()
        self.format_var.set(f"Baza: {self.db.path.name}")
        self.period_var.set(f"Obdobje: {format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)}")
        self.member_var.set(f"Vsebina: IR {counts['ir']} • PR {counts['pr']} • pravila {counts['rules']}")
        kind = company_source_kind(self.active_company)
        if kind == "projest":
            self.source_var.set(
                f"{Path(self.ir_darila_var.get()).name} + "
                f"{Path(self.ir_fitnes_var.get()).name} + "
                f"{Path(self.pr_var.get()).name}"
            )
        elif kind == "integra":
            self.source_var.set("SQL TROPS → SQLite (brez kisanal.dbf / popa.dbf).")
        else:
            self.source_var.set("Uvozi FURS KIR/KPR (ZIP/JSON/XML/CSV) v SQLite.")
        self.status_var.set(f"SQLite: {self.db.path} • prikazano po filtrih")

    def _update_analysis(self) -> None:
        if not hasattr(self, "analysis_box"):
            return
        counts = self.db.counts()
        ir_period, pr_period = self._period_rows()
        books_all = {book: 0 for book in IR_BOOKS}
        books_period = {book: 0 for book in IR_BOOKS}
        for row in self._ir_cache:
            book = str(row.get("book") or "")
            if book in books_all:
                books_all[book] += 1
        for row in ir_period:
            book = str(row.get("book") or "")
            if book in books_period:
                books_period[book] += 1

        ir_net = sum((decimal_value(r.get("net")) for r in ir_period), decimal_value(0))
        ir_vat = sum(
            (decimal_value(r.get("vat_22")) + decimal_value(r.get("vat_95")) for r in ir_period),
            decimal_value(0),
        )
        ir_gross = sum((decimal_value(r.get("total")) for r in ir_period), decimal_value(0))
        info = pr_access_info(pr_period)
        try:
            ddvo = compute_ddvo(
                ir_period,
                pr_period,
                period_from=self.filter_from_date,
                period_to=self.filter_to_date,
            )
        except Exception as exc:
            ddvo = {"error": str(exc)}

        period_txt = f"{format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)}"
        books_all_txt = ", ".join(f"{k} {v}" for k, v in books_all.items() if v) or "—"
        books_period_txt = ", ".join(f"{k} {v}" for k, v in books_period.items() if v) or "—"
        lines = [
            "ANALITIKA TROPS STUDIO",
            "",
            f"• SQLite: {self.db.path}",
            f"• Stranke: {counts['parties']}  •  kontna pravila: {counts['rules']}",
            f"• IR v bazi: {counts['ir']} ({books_all_txt})",
            f"• PR v bazi: {counts['pr']}",
            "",
            f"OBDOBJE (filter): {period_txt}",
            f"• IR v obdobju: {len(ir_period)} ({books_period_txt})",
            f"• PR v obdobju: {len(pr_period)}",
            f"• IR Osnova: {money_text(ir_net)} EUR",
            f"• IR DDV: {money_text(ir_vat)} EUR",
            f"• IR Skupaj: {money_text(ir_gross)} EUR",
        ]
        if "error" in ddvo:
            lines.append(f"• DDV-O: napaka — {ddvo['error']}")
        else:
            lines.extend(
                [
                    f"• PR Domači SLO DDV: {money_text(ddvo.get('domestic_input_vat'))} EUR",
                    f"• PR Prevalitev: {money_text(ddvo.get('prevalitev_input_vat'))} EUR",
                    f"• DDV-O obračunani: {money_text(ddvo.get('output_vat_exact'))} → {money_text(ddvo.get('output_vat'))} EUR",
                    f"• DDV-O odbitni: {money_text(ddvo.get('input_vat_exact'))} → {money_text(ddvo.get('input_vat'))} EUR",
                    f"• DDV-O polje 51 (obveznost): {money_text(ddvo.get('obligation'))} EUR",
                    f"• Access DDV za plačilo (IR−domači): {money_text(ddvo.get('access_payable'))} EUR",
                    f"• INFO Ne gre v knjigo: {money_text(info.get('info_excluded'))} EUR",
                    f"• INFO Neodbitni DDV: {money_text(info.get('info_neodbitni'))} EUR",
                    f"• INFO 21/22 uvoz: {money_text(info.get('info_uvoz_21_22'))} EUR",
                    f"• INFO 16/35 OPR OS: {money_text(info.get('info_opr_os'))} EUR",
                    f"• INFO MRN: {info.get('info_mrn_text') or '—'}",
                ]
            )
        if not ir_period and not pr_period:
            lines.extend(
                [
                    "",
                    "⚠ V izbranem obdobju ni IR/PR vrstic — nastavi Obdobje (npr. junij 2026) in Uporabi.",
                ]
            )
        lines.extend(
            [
                "",
                "Namig: panel Obdobje filtrira IR/PR/DDV-O/Knjige/Analitiko. "
                "Zaključen mesec se ne prepiše — nov uvoz gre pod oznako -2, -3, -4.",
            ]
        )
        self.analysis_box.configure(state="normal")
        self.analysis_box.delete("1.0", "end")
        self.analysis_box.insert("1.0", "\n".join(lines))
        self.analysis_box.configure(state="disabled")

    # ----------------------------------------------------------------- chk/sel
    def clear_ir_search(self) -> None:
        self.ir_search_var.set("")
        self._populate_ir_tree()

    def clear_pr_search(self) -> None:
        self.pr_search_var.set("")
        self._populate_pr_tree()

    def _select_all_ir_books(self) -> None:
        available = set(self._available_ir_books())
        for book, var in self.ir_book_vars.items():
            var.set(book in available)
        self._populate_ir_tree()

    def _clear_all_ir_books(self) -> None:
        for var in self.ir_book_vars.values():
            var.set(False)
        self._populate_ir_tree()

    def _select_default_ir_books(self) -> None:
        if company_source_kind(self.active_company) == "integra":
            defaults = {"Paragoni", "Fakture"}
        else:
            defaults = {"Darila", "Fitness"}
        for book, var in self.ir_book_vars.items():
            var.set(book in defaults)
        self._populate_ir_tree()

    def _on_ir_selection(self, _event: tk.Event | None = None) -> None:
        self.ir_selection_var.set(f"Izbranih IR: {len(self.ir_tree.selection())}")

    def _on_pr_selection(self, _event: tk.Event | None = None) -> None:
        self.pr_selection_var.set(f"Izbranih PR: {len(self.pr_tree.selection())}")

    def _select_all_ir(self, _event: tk.Event | None = None) -> str:
        self.ir_tree.selection_set(self.ir_tree.get_children(""))
        self._on_ir_selection()
        return "break"

    def _select_all_pr(self, _event: tk.Event | None = None) -> str:
        self.pr_tree.selection_set(self.pr_tree.get_children(""))
        self._on_pr_selection()
        return "break"

    @staticmethod
    def _root_tree_iid(item: str) -> str:
        """pr:12:line:excl → pr:12; ir:3 ostane ir:3."""
        parts = str(item).split(":")
        if len(parts) >= 2 and parts[0] in {"pr", "ir", "party"}:
            return f"{parts[0]}:{parts[1]}"
        return str(item)

    def _toggle_chk(self, kind: str) -> str:
        tree = self.ir_tree if kind == "IR" else self.pr_tree
        for item in tree.selection() or ():
            key = self._root_tree_iid(item)
            self.chk_state[key] = not bool(self.chk_state.get(key))
        if kind == "IR":
            self._populate_ir_tree()
        else:
            self._populate_pr_tree()
        return "break"

    def _set_chk_selected(self, kind: str, value: bool) -> None:
        tree = self.ir_tree if kind == "IR" else self.pr_tree
        for item in tree.selection():
            self.chk_state[self._root_tree_iid(item)] = value
        if kind == "IR":
            self._populate_ir_tree()
        else:
            self._populate_pr_tree()

    def _set_chk_all_visible(self, kind: str, value: bool) -> None:
        """Vse označi / odznači — Chk na vseh vidnih vrsticah + Treeview selection."""
        tree = self.ir_tree if kind == "IR" else self.pr_tree
        items = list(tree.get_children(""))
        for item in items:
            self.chk_state[item] = value
        if kind == "IR":
            self._populate_ir_tree()
        else:
            self._populate_pr_tree()
        # po rebuildu: uskladi selection z Chk (Potrdi / Uporabi konto)
        tree = self.ir_tree if kind == "IR" else self.pr_tree
        checked = [item for item in tree.get_children("") if self.chk_state.get(item)]
        if value and checked:
            tree.selection_set(checked)
        else:
            tree.selection_remove(*tree.selection())
        if kind == "IR":
            self._on_ir_selection()
        else:
            self._on_pr_selection()

    def _selected_ids(self, kind: str) -> list[int]:
        """ID-ji iz stolpca Chk; če noben ni označen, iz Treeview selection."""
        tree = self.ir_tree if kind == "IR" else self.pr_tree
        ids: list[int] = []
        for item in tree.get_children(""):
            if not self.chk_state.get(item):
                continue
            rid = self._id_from_tree_iid(item)
            if rid is not None:
                ids.append(rid)
        if ids:
            return ids
        for item in tree.selection():
            rid = self._id_from_tree_iid(item)
            if rid is not None:
                ids.append(rid)
        return ids

    @staticmethod
    def _id_from_tree_iid(item: str) -> int | None:
        parts = str(item).split(":")
        if len(parts) < 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def _edit_target_id(self, kind: str, *, prefer_iid: str = "") -> int | None:
        """ID za Odpri/dvojni klik: fokusirana / označena vrstica (ne Chk)."""
        tree = self.ir_tree if kind == "IR" else self.pr_tree
        if prefer_iid:
            rid = self._id_from_tree_iid(prefer_iid)
            if rid is not None:
                return rid
        focus = tree.focus()
        if focus:
            rid = self._id_from_tree_iid(focus)
            if rid is not None:
                return rid
        sel = tree.selection()
        if sel:
            return self._id_from_tree_iid(sel[0])
        return None

    def _on_ir_double_click(self, event: tk.Event) -> str:
        item = self.ir_tree.identify_row(event.y)
        if not item:
            return "break"
        self.ir_tree.selection_set(item)
        self.ir_tree.focus(item)
        rid = self._edit_target_id("IR", prefer_iid=item)
        if rid is not None:
            self._open_row_editor("IR", rid)
        return "break"

    def _on_pr_double_click(self, event: tk.Event) -> str:
        item = self.pr_tree.identify_row(event.y)
        if not item:
            return "break"
        self.pr_tree.selection_set(item)
        self.pr_tree.focus(item)
        rid = self._edit_target_id("PR", prefer_iid=item)
        if rid is not None:
            self._open_row_editor("PR", rid)
        return "break"

    def _on_ir_tree_click(self, event: tk.Event) -> None:
        if self.ir_tree.identify_column(event.x) == "#1":
            item = self.ir_tree.identify_row(event.y)
            if item:
                self.chk_state[item] = not bool(self.chk_state.get(item))
                self._populate_ir_tree()

    def _on_pr_tree_click(self, event: tk.Event) -> None:
        # #0 = drevo (+/−), #1 = Chk
        if self.pr_tree.identify_column(event.x) == "#1":
            item = self.pr_tree.identify_row(event.y)
            if item:
                key = self._root_tree_iid(item)
                self.chk_state[key] = not bool(self.chk_state.get(key))
                self._populate_pr_tree()

    def _account_choice_list(self) -> list[str]:
        org_id = company_org_id(self.active_company) if self.active_company else ""
        return load_account_choices(self.db, org_id or None, fetch_minimax=False)

    def _account_choices(self, kind: str) -> tuple[str, ...]:
        # kind ohranjen za združljivost; seznam = lokalni + (po warm) Minimax
        _ = kind
        return tuple(self._account_choice_list())

    def _warm_account_combos(self) -> None:
        """Prednaloži Minimax kontni plan v ozadju (hitrejše odprtje IR/PR)."""
        org_id = company_org_id(self.active_company) if self.active_company else ""
        if not org_id:
            return

        def work() -> None:
            try:
                choices = warm_account_cache_minimax(self.db, org_id)
            except Exception:
                choices = []

            def apply() -> None:
                if not choices:
                    return
                for combo in (
                    getattr(self, "ir_account_combo", None),
                    getattr(self, "pr_account_combo", None),
                ):
                    if combo is None:
                        continue
                    try:
                        code = account_code_from_choice(str(combo.get() or ""))
                        combo.set_values(ensure_choice(choices, code))
                    except tk.TclError:
                        pass

            try:
                self.root.after(0, apply)
            except tk.TclError:
                pass

        threading.Thread(target=work, daemon=True, name="mm-accounts-warm").start()

    def apply_ir_account(self) -> None:
        account = account_code_from_choice(self.ir_account_var.get())
        ids = self._selected_ids("IR")
        if not ids:
            messagebox.showinfo("Konto", "Izberi IR vrstice.", parent=self.root)
            return
        for row_id in ids:
            row = self.db.get_ir(row_id)
            if not row:
                continue
            row["account"] = account
            self.db.upsert_ir(row, row_id)
            if self.remember_customer_var.get():
                remember_customer_rule(self.db, row, source="ui")
        self.refresh_after_edit("IR")

    def apply_pr_account(self) -> None:
        account = account_code_from_choice(self.pr_account_var.get())
        ids = self._selected_ids("PR")
        if not ids:
            messagebox.showinfo("Konto", "Izberi PR vrstice.", parent=self.root)
            return
        for row_id in ids:
            row = self.db.get_pr(row_id)
            if not row:
                continue
            eu_g = decimal_value(row.get("eu_goods"))
            eu_s = decimal_value(row.get("eu_services"))
            net = decimal_value(row.get("net_taxable"))
            has_eu10 = is_nonzero(eu_g)
            has_eu11 = is_nonzero(eu_s)
            has_net = is_nonzero(net)
            # EU 10/11 <> 0 → konto na ustrezni stolpec; 08 samo če je osnova <> 0
            if has_eu10:
                row["odhodek10"] = account
            if has_eu11:
                row["odhodek11"] = account
            if has_net or not (has_eu10 or has_eu11):
                row["odhodek01"] = account
            elif not has_net and (has_eu10 or has_eu11):
                row["odhodek01"] = ""
            allocated = allocate_pr_accounts(row)
            row.update(allocated)
            self.db.upsert_pr(row, row_id)
            if self.remember_supplier_var.get():
                remember_supplier_rule(self.db, row, source="ui")
        self.refresh_after_edit("PR")

    def set_selected_ir_account(self, account: str) -> None:
        self.ir_account_var.set(account)
        self.apply_ir_account()

    def set_selected_pr_account(self, account: str) -> None:
        self.pr_account_var.set(account)
        self.apply_pr_account()

    # --------------------------------------------------------------- CRUD/UI
    def _choose_path(self, variable: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            filetypes=(("Excel", "*.xls *.xlsx *.xlsm"), ("Vse", "*.*")),
        )
        if selected:
            variable.set(selected)

    def _focus_active_search(self) -> None:
        try:
            index = int(self.notebook.index(self.notebook.select()))
        except Exception:
            index = 0
        # focus is soft — search vars already live; just clear hint in status
        self.status_var.set("Iskalnik je na zavihku desno (Išči).")

    def open_ui_prefs(self) -> None:
        from trops_studio.ui.ui_prefs_dialog import UiPrefsDialog

        UiPrefsDialog(self.root, self.ui_prefs, on_apply=self._apply_ui_prefs)

    def open_smtp_compose(self) -> None:
        from trops_studio.ddvo_actions import GMAIL_SMTP_FROM, client_email_to
        from trops_studio.ui.smtp_compose_dialog import SmtpComposeDialog

        to_addr = client_email_to(self.active_company) or GMAIL_SMTP_FROM
        SmtpComposeDialog(
            self.root,
            title="SMTP (Gmail) — test / predogled",
            to_addr=to_addr,
            subject="Trops Studio — test SMTP",
            body_html=(
                "<p>Test Gmail SMTP iz Trops Studio.</p>"
                "<p>Uredi besedilo, klikni <b>Test SMTP</b> (prijava, nato po želji nase) "
                "ali <b>Pošlji stranki</b>.</p>"
            ),
            on_sent=lambda note: self.status_var.set(note.split("\n", 1)[0]),
        )

    def _apply_ui_prefs(self, prefs: Mapping[str, Any], persist: bool) -> None:
        old = dict(self.colors)
        self.ui_prefs = merge_ui_prefs(prefs)
        self.colors = apply_ui_prefs_to_root(self.root, self.ui_prefs, previous_colors=old)
        if persist:
            path = save_ui_prefs(self.ui_prefs)
            self.status_var.set(f"Videz shranjen: {path.name}")
        else:
            self.status_var.set("Videz uporabljen — Shrani, če naj ostane ob naslednjem zagonu.")

    def check_minimax_api(self) -> None:
        if not self.active_company:
            messagebox.showinfo("Minimax API", "Najprej izberi podjetje.", parent=self.root)
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror("Minimax API", "Manjka Org_ID.", parent=self.root)
            return
        self.status_var.set(f"Preverjam Minimax API (Org {org_id}) …")
        self.root.update_idletasks()
        result = check_minimax_api(org_id)
        if result.ok:
            messagebox.showinfo("Minimax API", result.message, parent=self.root)
        else:
            messagebox.showerror("Minimax API", result.message, parent=self.root)
        self.status_var.set(result.message.split("\n", 1)[0])

    def open_account_map_dialog(self) -> None:
        """Preveri Trops konti ↔ Minimax in shrani zamenjave."""
        if not self.db:
            messagebox.showwarning("Konti Trops → Minimax", "Ni odprte baze.", parent=self.root)
            return
        org_id = company_org_id(self.active_company) if self.active_company else ""
        from trops_studio.ui.account_map_dialog import AccountMapDialog

        AccountMapDialog(
            self.root,
            self.db,
            org_id=org_id,
            force_open=True,
            on_saved=lambda _m: self.refresh_all(),
        )

    def sync_minimax_accounts(self) -> None:
        """Minimax kontni plan → SQLite (minimax_accounts)."""
        if not self.active_company:
            messagebox.showinfo(
                "Kontni plan",
                "Najprej izberi podjetje z Org_ID.",
                parent=self.root,
            )
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror("Kontni plan", "Pri podjetju manjka Org_ID.", parent=self.root)
            return
        existing = self.db.count_minimax_accounts(org_id)
        self.status_var.set(f"Berem Minimax kontni plan (Org {org_id}) …")
        self.root.update_idletasks()

        def work() -> None:
            try:
                choices = warm_account_cache_minimax(self.db, org_id, force=True)
                n = self.db.count_minimax_accounts(org_id)
                err = ""
            except Exception as exc:
                choices = []
                n = 0
                err = str(exc)

            def done() -> None:
                clear_account_cache()
                self._warm_account_combos()
                if err:
                    self.status_var.set("Kontni plan: napaka.")
                    messagebox.showerror("Kontni plan", err, parent=self.root)
                    return
                self.status_var.set(f"Kontni plan SQL: {n} kontov (Org {org_id}).")
                bookable = len(choices)
                messagebox.showinfo(
                    "Kontni plan → SQL",
                    f"Minimax → SQLite: {n} kontov (prej {existing}).\n"
                    f"Knjižljivih v izbiri: {bookable}\n"
                    f"(AllowedPosting ≠ N; sintetični 4/40/400 … izločeni)\n"
                    f"Org {org_id}\n\n"
                    "Uporaba v IR/PR comboboxih brez ponovnega API klica.",
                    parent=self.root,
                )

            try:
                self.root.after(0, done)
            except tk.TclError:
                pass

        threading.Thread(target=work, daemon=True, name="mm-accounts-sql").start()

    def sync_minimax_parties(self) -> None:
        if not self.active_company:
            messagebox.showinfo(
                "Minimax stranke",
                "Najprej izberi podjetje z Org_ID (npr. PROJEST).",
                parent=self.root,
            )
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror(
                "Minimax stranke",
                "Pri podjetju manjka Org_ID.",
                parent=self.root,
            )
            return
        self.status_var.set(f"Berem Minimax stranke (Org {org_id}) …")
        self.root.update_idletasks()
        try:
            result = sync_customers_from_minimax(self.db, org_id)
            linked = ensure_missing_via_ajpes(self.db, use_ajpes=False)
        except Exception as exc:
            self.status_var.set("Minimax sync ni uspel.")
            messagebox.showerror("Minimax stranke", str(exc), parent=self.root)
            return
        self.refresh_all()
        self.status_var.set(result.message)
        messagebox.showinfo(
            "Minimax stranke",
            f"{result.message}\nPovezava IR/PR: {linked.message}",
            parent=self.root,
        )

    def cleanup_minimax_drafts(self) -> None:
        """Briši Minimax IR osnutke obdobja (brez DDV — po neuspelem 409)."""
        if not self.active_company:
            messagebox.showinfo("Osnutki", "Najprej izberi podjetje.", parent=self.root)
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror("Osnutki", "Manjka Org_ID.", parent=self.root)
            return
        date_from = self.filter_from_date.isoformat()
        date_to = self.filter_to_date.isoformat()
        if not messagebox.askyesno(
            "Briši Minimax osnutke",
            f"Org {org_id}\nObdobje: {date_from} … {date_to}\n\n"
            "Izbrišem IR osnutke (Status=O) BREZ DDV-vrstic?\n"
            "(To so delno ustvarjene temeljnice po napaki 409.)\n\n"
            "Potrjene temeljnice se ne brišejo.",
            parent=self.root,
        ):
            return
        from trops_studio.minimax_draft_cleanup import (
            delete_draft_journals_for_period,
            reset_ir_error_to_ready,
        )

        self.status_var.set("Brišem Minimax osnutke …")
        self.root.update_idletasks()
        try:
            result = delete_draft_journals_for_period(
                org_id,
                date_from=date_from,
                date_to=date_to,
                books={"IR"},
                only_without_vat=True,
                progress=lambda msg: self.status_var.set(msg),
            )
        except Exception as exc:
            messagebox.showerror("Osnutki", str(exc), parent=self.root)
            self.status_var.set("Brisanje osnutkov ni uspelo.")
            return
        reset_n = reset_ir_error_to_ready(self.db)
        self.refresh_all()
        extra = ""
        if result.failed:
            extra = "\n\n" + "\n".join(result.failed[:12])
        messagebox.showinfo(
            "Osnutki",
            result.message
            + (f"\nSQL error→ready: {reset_n}" if reset_n else "")
            + extra
            + "\n\nDDV oddaja je popravljena (brez vsiljenega OD).\n"
            "Ponovno: Sinhroniziraj knjigo.",
            parent=self.root,
        )
        self.status_var.set(result.message)

    def sync_ready_minimax(self, scope: str = "ALL") -> None:
        """
        scope=ALL  → zgornji gumb: stranke + vsi IR/PR ready
        scope=IR   → spodnji: samo IR v aktivnih knjigah (filter)
        scope=PR   → spodnji: samo PR ready
        """
        if not self.active_company:
            messagebox.showinfo("Sinhronizacija", "Najprej izberi podjetje.", parent=self.root)
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror("Sinhronizacija", "Manjka Org_ID.", parent=self.root)
            return

        scope_u = (scope or "ALL").upper()
        books = self._active_ir_books()
        # synced štejemo tudi — če osnutka v MM ni (404), sync ga znova doda
        def _ir_candidates() -> list:
            rows = (
                self.db.list_ir_by_sync(SYNC_READY)
                + self.db.list_ir_by_sync(SYNC_ERROR)
                + self.db.list_ir_by_sync(SYNC_SYNCED)
            )
            return [r for r in rows if not books or str(r.get("book") or "") in books]

        def _pr_candidates() -> list:
            return (
                self.db.list_pr_by_sync(SYNC_READY)
                + self.db.list_pr_by_sync(SYNC_ERROR)
                + self.db.list_pr_by_sync(SYNC_SYNCED)
            )

        if scope_u == "IR":
            ir_ready = _ir_candidates()
            n_party, n_ir, n_pr = 0, len(ir_ready), 0
            books_label = ", ".join(sorted(books)) if books else "(nobena knjiga)"
            confirm_msg = (
                f"Org {org_id}\n\n"
                f"Samo ta knjiga / filter IR (+ DI Paragoni):\n"
                f"• Knjige: {books_label}\n"
                f"• IR kandidati: {n_ir} → osnutki (manjkajoče v MM doda)\n\n"
                "DR… → IR, 100* → DI.\n"
                "Nadaljujem?"
            )
            sync_kwargs: dict[str, Any] = {
                "push_parties": False,
                "kinds": {"IR"},
                "ir_books": books if books else set(),
            }
        elif scope_u == "PR":
            n_party, n_ir = 0, 0
            pr_ready_rows = _pr_candidates()
            n_pr = len(pr_ready_rows)
            confirm_msg = (
                f"Org {org_id}\n\n"
                f"Samo PR:\n"
                f"• PR kandidati: {n_pr} → osnutki (manjkajoče v MM doda)\n\n"
                "Manjkajoče stranke: SI → dodaj v Minimax, tujci → AI+SQL → API.\n"
                "Nadaljujem?"
            )
            sync_kwargs = {
                "push_parties": False,
                "kinds": {"PR"},
            }
        else:
            n_party = len(self.db.list_parties_by_sync(SYNC_READY))
            n_ir = len(_ir_candidates())
            pr_ready_rows = _pr_candidates()
            n_pr = len(pr_ready_rows)
            confirm_msg = (
                f"Org {org_id}\n\n"
                f"• Stranke ready: {n_party} → Minimax customers API\n"
                f"• IR/DI kandidati: {n_ir} → osnutki (manjkajoče doda)\n"
                f"• PR kandidati: {n_pr} → osnutki\n\n"
                "Celotna oddaja (vse knjige).\nNadaljujem?"
            )
            sync_kwargs = {
                "push_parties": True,
            }

        if not (n_party or n_ir or n_pr):
            messagebox.showinfo(
                "Sinhronizacija",
                "Ni IR/PR za oddajo v tem obsegu.\n"
                "Najprej Shrani / Prenos v IR, nato Sinhroniziraj.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno("Sinhroniziraj Minimax", confirm_msg, parent=self.root):
            return
        if self._sync_running:
            messagebox.showinfo("Sinhronizacija", "Sinhronizacija že teče.", parent=self.root)
            return

        # IR: listview manjkajočih kupcev z SI/DE/IT… (brez DDV → 01345)
        if scope_u in {"IR", "ALL"} and n_ir:
            if scope_u == "IR":
                ir_rows_for_check = list(ir_ready)
            else:
                ir_rows_for_check = _ir_candidates()
            missing_ir = collect_missing_ir_parties(self.db, ir_rows_for_check)
            if missing_ir:
                dlg = MissingIrPartiesDialog(
                    self.root,
                    self.db,
                    org_id=str(org_id),
                    ir_rows=ir_rows_for_check,
                    on_done=self.refresh_all,
                )
                self.root.wait_window(dlg)
                if not getattr(dlg, "resolved", False):
                    self.status_var.set("Sinhronizacija prekinjena (IR stranke).")
                    return

        # PR: listview manjkajočih strank (SI→AJPES, tujci/brez DS→ročno)
        if scope_u in {"PR", "ALL"} and n_pr:
            pr_rows_for_check = _pr_candidates()
            missing = collect_missing_pr_parties(self.db, pr_rows_for_check)
            if missing:
                dlg = MissingPrPartiesDialog(
                    self.root,
                    self.db,
                    org_id=str(org_id),
                    pr_rows=pr_rows_for_check,
                    on_done=self.refresh_all,
                )
                self.root.wait_window(dlg)
                if not getattr(dlg, "resolved", False):
                    self.status_var.set("Sinhronizacija prekinjena (PR stranke).")
                    return

        progress_dlg = ProgressDialog(
            self.root,
            title="Sinhronizacija Minimax",
            message=f"Oddaja v Minimax (Org {org_id}) …",
        )
        progress_dlg.set_progress(0, max(n_ir + n_pr, 1) if (n_ir or n_pr) else 0, detail="Priprava …")
        self._sync_running = True
        self.status_var.set("Sinhroniziram Minimax …")

        company_label = company_name(self.active_company) or "PROJEST"
        db_path = self.db.path

        def on_progress(message: str, current: int, total: int) -> None:
            def _ui() -> None:
                if total and total > 0:
                    progress_dlg.set_message("Sinhronizacija Minimax …", detail=message)
                    progress_dlg.set_progress(current, total, detail=message)
                else:
                    progress_dlg.set_message(message or "Sinhronizacija …")
                    progress_dlg.set_progress(0, 0, detail=message)
                self.status_var.set(message[:120] if message else "Sinhroniziram …")

            try:
                self.root.after(0, _ui)
            except Exception:
                pass

        def worker() -> None:
            err: Exception | None = None
            result = None
            try:
                # Ločen Database handle za ozadje (SQLite thread-safe)
                work_db = Database(db_path)
                result = sync_ready_to_minimax(
                    work_db,
                    org_id,
                    output_dir=DEFAULT_MINIMAX_OUT,
                    company_label=company_label,
                    push_journals_api=True,
                    export_xml=False,
                    progress=on_progress,
                    **sync_kwargs,
                )
            except Exception as exc:
                err = exc

            def finish() -> None:
                self._sync_running = False
                progress_dlg.close()
                if err is not None:
                    messagebox.showerror("Sinhronizacija", str(err), parent=self.root)
                    self.status_var.set("Sinhronizacija ni uspela.")
                    return
                assert result is not None
                self.refresh_all()
                extra = ""
                if result.parties_failed:
                    extra = "\n\n" + "\n".join(result.parties_failed[:12])
                if result.journal_failed:
                    extra += "\n\n" + "\n".join(result.journal_failed[:12])
                journals_ok = (result.ir_api_ok or 0) + (result.pr_api_ok or 0)
                msg = result.message + extra
                if journals_ok:
                    msg += "\n\nOdprem Minimax → Temeljnice (osnutki)."
                messagebox.showinfo("Sinhronizacija", msg, parent=self.root)
                if journals_ok:
                    open_minimax_temeljnice()
                self.status_var.set(result.message.split("\n", 1)[0])

            try:
                self.root.after(0, finish)
            except Exception:
                self._sync_running = False

        threading.Thread(target=worker, daemon=True, name="minimax-sync").start()

    def confirm_selected(self, kind: str) -> None:
        ids = self._selected_ids(kind)
        if not ids:
            messagebox.showinfo("Potrdi", "Izberi vsaj eno vrstico.", parent=self.root)
            return
        remember = (
            bool(self.remember_supplier_var.get())
            if kind == "PR"
            else bool(self.remember_customer_var.get())
        )
        remember_txt = (
            "\nKonte / nastavitve shranim k strankam (SQL) za naslednji uvoz."
            if remember
            else ""
        )
        if not messagebox.askyesno(
            "Potrdi → Minimax",
            f"Potrdim {len(ids)} {kind} v SQL (Shranjeno + ready)?\n"
            "Minimax sync nato z gumbom »Sinhroniziraj Minimax«."
            f"{remember_txt}",
            parent=self.root,
        ):
            return
        n = confirm_documents(self.db, kind, [int(i) for i in ids])
        remembered = 0
        for rid in ids:
            if kind == "PR":
                if remember:
                    row = self.db.get_pr(int(rid))
                    if row and remember_supplier_rule(self.db, row, source="confirm"):
                        remembered += 1
                continue
            row = self.db.get_ir(int(rid))
            if not row:
                continue
            fixed = apply_ir_eu_sale(row, self._party_for_pr_row(row))
            if (
                str(fixed.get("account") or "") != str(row.get("account") or "")
                or decimal_value(fixed.get("exempt")) != decimal_value(row.get("exempt"))
                or decimal_value(fixed.get("net")) != decimal_value(row.get("net"))
                or decimal_value(fixed.get("eu_goods")) != decimal_value(row.get("eu_goods"))
            ):
                self.db.upsert_ir(fixed, int(rid))
                row = fixed
            if remember and remember_customer_rule(self.db, row, source="confirm"):
                remembered += 1
        self.refresh_after_edit(kind)
        extra = f", zapomnjeno {remembered} strankam" if remember else ""
        self.status_var.set(f"Potrjeno {n} {kind} (ready{extra}).")

    def _persist_editor_row(self, kind: str, payload: dict[str, Any], *, base_id: int | None = None) -> int:
        """Shrani IR/PR + knjižbe v SQL; Potrdi nastavi sync_status=ready."""
        confirm = bool(payload.pop("confirm_for_minimax", False))
        remember = bool(payload.pop("remember", False))
        rid = payload.pop("id", None) or base_id
        if confirm:
            payload["sync_status"] = SYNC_READY
        if kind == "IR":
            current = self.db.get_ir(int(rid)) if rid else None
            merged = dict(current or {})
            merged.update(payload)
            merged.update(apply_ir_eu_sale(merged, self._party_for_pr_row(merged)))
            new_id = self.db.upsert_ir(merged, int(rid) if rid else None)
            merged["id"] = new_id
            self.db.replace_journal_lines("IR", new_id, merged)
            if confirm:
                self.db.set_row_sync("IR", new_id, SYNC_READY)
            if remember:
                remember_customer_rule(self.db, merged, source="ui")
            return new_id
        current = self.db.get_pr(int(rid)) if rid else None
        merged = dict(current or {})
        merged.update(payload)
        new_id = self.db.upsert_pr(merged, int(rid) if rid else None)
        merged["id"] = new_id
        self.db.replace_journal_lines("PR", new_id, merged)
        if confirm:
            self.db.set_row_sync("PR", new_id, SYNC_READY)
        if remember:
            remember_supplier_rule(self.db, merged, source="ui")
        return new_id

    def fill_missing_parties(self) -> None:
        self.status_var.set("Dopolnjujem manjkajoče stranke (AJPES) …")
        self.root.update_idletasks()
        try:
            result = ensure_missing_via_ajpes(self.db, use_ajpes=True)
        except Exception as exc:
            messagebox.showerror("AJPES", str(exc), parent=self.root)
            return
        self.refresh_all()
        extra = ""
        if result.needs_login:
            extra = "\n\nZa AJPES je potrebna prijava (EvidencaFirm / ajpes_config.json)."
        if result.failed:
            extra += "\n\n" + "\n".join(result.failed[:12])
            if len(result.failed) > 12:
                extra += f"\n… še {len(result.failed) - 12}"
        messagebox.showinfo("AJPES", result.message + extra, parent=self.root)
        self.status_var.set(result.message)

    def open_nove_firme(self) -> None:
        """Seznam firm, ki jih ni v SQLite / Minimaxu → uvoz prek customers API."""
        if not self.active_company:
            messagebox.showinfo(
                "Nove firme",
                "Najprej izberi podjetje z Org_ID (npr. PROJEST).",
                parent=self.root,
            )
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror(
                "Nove firme",
                "Pri podjetju manjka Org_ID.",
                parent=self.root,
            )
            return
        pending = collect_firms_needing_minimax(self.db)
        self.status_var.set(f"Nove firme: {len(pending)} kandidatov (Org {org_id}).")
        NoveFirmeDialog(self.root, self.db, org_id=org_id, on_done=self.refresh_all)

    def repair_party_names(self) -> None:
        """Počisti hieroglife (&#x…;) in SI nazive osveži iz AJPES (EvidencaFirm)."""
        if not messagebox.askyesno(
            "Popravi nazive",
            "Počistim hieroglife v nazivih strank in za pokvarjene SI\n"
            "pridobim podatke iz AJPES (kot Evidenca firm)?",
            parent=self.root,
        ):
            return
        self.status_var.set("Popravljam nazive strank …")
        self.root.update_idletasks()
        try:
            result = repair_party_names(self.db, use_ajpes=True)
        except Exception as exc:
            messagebox.showerror("Popravi nazive", str(exc), parent=self.root)
            return
        self.refresh_all()
        extra = ""
        if result.get("failed"):
            failed = result["failed"]
            extra = "\n\n" + "\n".join(failed[:12])
            if len(failed) > 12:
                extra += f"\n… še {len(failed) - 12}"
        messagebox.showinfo("Popravi nazive", result["message"] + extra, parent=self.root)
        self.status_var.set(result["message"])

    def export_xml_for_kirkpr(self) -> None:
        if not self.db.list_ir() and not self.db.list_pr():
            messagebox.showinfo("XML", "Ni IR/PR vrstic za izvoz.", parent=self.root)
            return
        # Izvoz filtriranih (vidnih) vrstic, če so filtri aktivni — sicer vse.
        ir_rows = [row for row in self._ir_cache if self._ir_row_visible(row)]
        pr_rows = [row for row in self._pr_cache if self._pr_row_visible(row)]
        if not ir_rows and not pr_rows:
            ir_rows = self.db.list_ir()
            pr_rows = self.db.list_pr()
        label = "PROJEST"
        if self.active_company:
            zst = company_zst(self.active_company) or ""
            name = company_name(self.active_company)
            label = f"{zst}_{name}" if zst else name
        out_dir = DEFAULT_MINIMAX_OUT
        if self.active_company:
            zst = company_zst(self.active_company)
            if zst:
                candidate = TROPS_ROOT / str(zst) / "MiniMax"
                if candidate.parent.is_dir():
                    out_dir = candidate
        self.status_var.set("Izvažam XML za KirKpr …")
        self.root.update_idletasks()
        try:
            result = export_minimax_xml_for_kirkpr(
                self.db,
                output_dir=out_dir,
                ir_rows=ir_rows,
                pr_rows=pr_rows,
                company_label=label,
                validate=True,
            )
        except Exception as exc:
            # Poskusi brez XSD validacije, če shema/lxml težava.
            try:
                result = export_minimax_xml_for_kirkpr(
                    self.db,
                    output_dir=out_dir,
                    ir_rows=ir_rows,
                    pr_rows=pr_rows,
                    company_label=label,
                    validate=False,
                )
                messagebox.showwarning(
                    "XML (brez XSD)",
                    f"Validacija XSD ni uspela ({exc}).\nDatoteke so vseeno zapisane:\n"
                    f"{result.ir_path}\n{result.pr_path}",
                    parent=self.root,
                )
                self.status_var.set(result.message)
                return
            except Exception as exc2:
                messagebox.showerror("XML izvoz", f"{exc}\n\n{exc2}", parent=self.root)
                self.status_var.set("XML izvoz ni uspel.")
                return
        self.status_var.set(result.message)
        msg = (
            f"{result.message}\n\n"
            "To sta datoteki za Minimax → Uvoz podatkov v XML obliki\n"
            "(shema miniMAXUvozKnjigovodstvo.xsd → Temeljnice / osnutki).\n\n"
            "Koraki v Minimaxu:\n"
            "1) Nastavitve organizacije → Uvoz podatkov v XML obliki\n"
            "2) Izberite datoteko → najprej IR XML, nato PR XML\n"
            "3) Preveri osnutke temeljnic v knjigovodstvu\n\n"
            "Oddaja mimo »Sinhroniziraj«: samo ta XML uvoz (ročno).\n"
            "Priporočeno: »Sinhroniziraj Minimax« (API osnutki, brez diska).\n"
            "Odprem mapo z XML?"
        )
        if messagebox.askyesno("XML → Minimax uvoz temeljnic", msg, parent=self.root):
            try:
                folder = result.ir_path.parent if result.ir_path else out_dir
                os.startfile(str(folder))  # type: ignore[attr-defined]
            except Exception:
                pass
        open_minimax_temeljnice()
        try:
            open_url("https://help.minimax.si/help/uvoz-podatkov-v-minimax-preko-xml-ja")
        except Exception:
            pass

    def _on_ir_status_combo(self, _event: object | None = None) -> None:
        label = self._ir_status_combo.get()
        self.ir_status_filter.set(self._ir_status_label_to_value.get(label, "VSI"))
        self._populate_ir_tree()

    def _on_pr_status_combo(self, _event: object | None = None) -> None:
        label = self._pr_status_combo.get()
        self.pr_status_filter.set(self._pr_status_label_to_value.get(label, "VSI"))
        self._populate_pr_tree()

    def _ir_row_visible(self, row: dict[str, Any]) -> bool:
        book = str(row.get("book") or "")
        if book in self.ir_book_vars and not self.ir_book_vars[book].get():
            return False
        status = self.ir_status_filter.get()
        if status == "CHK":
            return bool(self.chk_state.get(f"ir:{row['id']}"))
        if status != "VSI" and not status_filter_matches(
            row.get("status"), status, has_account=bool(row.get("account"))
        ):
            return False
        only_si = bool(self.ir_filter_si.get())
        only_eu = bool(self.ir_filter_eu.get())
        only_third = bool(self.ir_filter_foreign.get())
        if only_si or only_eu or only_third:
            party = self._party_for_pr_row(row)
            region = ir_customer_region(row, party)
            if not (
                (only_si and region == "SI")
                or (only_eu and region == "EU")
                or (only_third and region == "FOREIGN")
            ):
                return False
        if bool(self.ir_filter_vat.get()) and not normalize_vat_id(row.get("vat_id")):
            return False
        day = parse_date(row.get("document_date") or row.get("booking_date"))
        if day and (day < self.filter_from_date or day > self.filter_to_date):
            return False
        return self._row_matches_period_rev(row)

    def _pr_row_visible(self, row: dict[str, Any]) -> bool:
        status = self.pr_status_filter.get()
        odhodek = str(row.get("odhodek01") or "")
        if status == "CHK":
            return bool(self.chk_state.get(f"pr:{row['id']}"))
        if status == "NO_ACCOUNT":
            return not odhodek
        if status != "VSI" and not status_filter_matches(
            row.get("status"), status, has_account=bool(odhodek)
        ):
            return False
        day = parse_date(row.get("received_date") or row.get("document_date") or row.get("booking_date"))
        if day and (day < self.filter_from_date or day > self.filter_to_date):
            return False
        return self._row_matches_period_rev(row)

    def _finish_vasco_import(self, result: dict[str, int]) -> None:
        self.refresh_all()
        rev = int(result.get("period_rev") or 1)
        self._refresh_period_rev_choices(preferred=rev)
        self.apply_period_filter()
        added_ir = int(result.get("ir") or 0)
        added_pr = int(result.get("pr") or 0)
        skipped_ir = int(result.get("ir_skipped") or 0)
        skipped_pr = int(result.get("pr_skipped") or 0)
        ir_docs = [str(x) for x in (result.get("ir_docs") or [])]
        pr_docs = [str(x) for x in (result.get("pr_docs") or [])]
        for rid in result.get("ir_ids") or []:
            self.chk_state[f"ir:{int(rid)}"] = True
        for rid in result.get("pr_ids") or []:
            self.chk_state[f"pr:{int(rid)}"] = True
        if added_ir:
            self._populate_ir_tree()
        if added_pr:
            self._populate_pr_tree()

        def _doc_lines(kind: str, docs: list[str]) -> str:
            if not docs:
                return ""
            shown = docs[:12]
            extra = f" … +{len(docs) - 12}" if len(docs) > 12 else ""
            return f"\n{kind}: " + ", ".join(shown) + extra

        skip_line = f"\nPreskočeno (že v bazi): {skipped_ir} IR, {skipped_pr} PR"
        si_vat_n = int(result.get("pr_si_vat") or 0)
        si_line = ""
        if si_vat_n:
            si_line = f"\nKontrola PR: {si_vat_n}× tujec/EU z ID za DDV SI+DŠ → status Popravi"
        rev_txt = revision_suffix(int(result.get("period_rev") or 1)) or "osnovni"
        report = (
            f"Dodano: {added_ir} IR in {added_pr} PR"
            f"{_doc_lines('IR', ir_docs)}"
            f"{_doc_lines('PR', pr_docs)}"
            f"{skip_line}{si_line}\n"
            f"Oznaka: {rev_txt}\n"
            f"Batch: {result['batch_id']}\n"
            f"Konti iz zgodovine: PR {result.get('learned_pr', 0)}, "
            f"IR {result.get('learned_ir', 0)}"
        )
        messagebox.showinfo("Vasco uvoz", report, parent=self.root)
        status = f"Uvoz: dodano IR {added_ir} / PR {added_pr} · preskočeno IR {skipped_ir} / PR {skipped_pr}"
        self.filter_info_var.set(status)
        if si_vat_n:
            status += f" · PR SI+DŠ {si_vat_n}"
            self.pr_filter_si_vat.set(True)
            self._populate_pr_tree()
        self.status_var.set(status)
        if messagebox.askyesno(
            "Manjkajoče stranke",
            "Odprem manjkajoče stranke?\n\n"
            "SI z davčno: samodejno v Minimax API (addbytaxnumber).\n"
            "EU/tretja: preveri z AI → SQL → Minimax.",
            parent=self.root,
        ):
            self.open_missing_journal_parties()

    def _run_ajpes_after_import_async(self) -> None:
        """Neblokirajoče dopolnjevanje strank po uvozu."""
        progress = ProgressDialog(
            self.root,
            title="AJPES",
            message="Dopolnjujem manjkajoče stranke (AJPES) …",
        )
        db_path = self.db.path

        def worker() -> None:
            err: Exception | None = None
            result = None
            try:
                work_db = Database(db_path)
                result = ensure_missing_via_ajpes(work_db, use_ajpes=True)
            except Exception as exc:
                err = exc

            def finish() -> None:
                progress.close()
                if err is not None:
                    messagebox.showerror("AJPES", str(err), parent=self.root)
                    return
                assert result is not None
                self.refresh_all()
                extra = ""
                if result.needs_login:
                    extra = "\n\nZa AJPES je potrebna prijava (EvidencaFirm / ajpes_config.json)."
                if result.failed:
                    extra += "\n\n" + "\n".join(result.failed[:12])
                    if len(result.failed) > 12:
                        extra += f"\n… še {len(result.failed) - 12}"
                messagebox.showinfo("AJPES", result.message + extra, parent=self.root)
                self.status_var.set(result.message)

            try:
                self.root.after(0, finish)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True, name="vasco-ajpes").start()

    def _last_vasco_cache_dir(self, db_path: Path | None = None) -> Path:
        path = Path(db_path or self.db.path)
        return path.parent / f"{path.stem}-last-vasco"

    def _format_last_vasco_label(self, rec: Mapping[str, Any]) -> str:
        when = str(rec.get("imported_at") or "").strip()
        try:
            when_s = datetime.fromisoformat(when).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            when_s = when or "—"
        source = str(rec.get("source") or "")
        zip_path = str(rec.get("zip") or "").strip()
        directory = str(rec.get("dir") or "").strip()
        if source == "zip" and zip_path:
            return f"Zadnji uvoz: {when_s} · ZIP {Path(zip_path).name} · {Path(zip_path).parent}"
        return f"Zadnji uvoz: {when_s} · {directory or '—'}"

    def _apply_last_vasco_import(self, rec: Mapping[str, Any]) -> None:
        darila = str(rec.get("ir_darila") or "").strip()
        fitness = str(rec.get("ir_fitnes") or "").strip()
        pr_path = str(rec.get("pr") or "").strip()
        if darila and Path(darila).is_file():
            self.ir_darila_var.set(darila)
        if fitness and Path(fitness).is_file():
            self.ir_fitnes_var.set(fitness)
        if pr_path and Path(pr_path).is_file():
            self.pr_var.set(pr_path)
        if rec:
            self.last_import_var.set(self._format_last_vasco_label(rec))
        else:
            self.last_import_var.set("Zadnji uvoz: —")

    def _restore_last_vasco_import(self) -> None:
        try:
            rec = self.db.get_last_vasco_import()
        except Exception:
            rec = {}
        self._apply_last_vasco_import(rec)
        if rec:
            try:
                self.db.set_last_vasco_import(rec)
            except Exception:
                pass

    def _vasco_initial_dir(self) -> str:
        rec = {}
        try:
            rec = self.db.get_last_vasco_import()
        except Exception:
            pass
        for raw in (
            rec.get("zip") and str(Path(str(rec.get("zip"))).parent),
            rec.get("dir"),
            self.pr_var.get().strip() and str(Path(self.pr_var.get().strip()).parent),
            self.ir_darila_var.get().strip() and str(Path(self.ir_darila_var.get().strip()).parent),
        ):
            if not raw:
                continue
            path = Path(str(raw))
            if path.is_dir():
                return str(path)
            if path.is_file():
                return str(path.parent)
        return "."

    def _kirkpr_initial_dir(self) -> str:
        """Privzeta mapa FURS ZIP: D:\\Trops\\{Zšt}\\DDV (ali KIRKPR_Minimax)."""
        from trops_studio.config import TROPS_ROOT

        zst = company_zst(self.active_company or {})
        if zst:
            for cand in (
                TROPS_ROOT / zst / "DDV" / "KIRKPR_Minimax",
                TROPS_ROOT / zst / "DDV",
                TROPS_ROOT / zst,
            ):
                if cand.is_dir():
                    return str(cand)
        return self._vasco_initial_dir()

    def _excel_paths_to_open(self, kind: str) -> list[Path]:
        rec = {}
        try:
            rec = self.db.get_last_vasco_import()
        except Exception:
            pass
        if kind == "IR":
            candidates = [rec.get("ir_darila"), rec.get("ir_fitnes")]
            fallback = (self.ir_darila_var.get().strip(), self.ir_fitnes_var.get().strip())
        else:
            candidates = [rec.get("pr")]
            fallback = (self.pr_var.get().strip(),)
        paths = [Path(str(raw)) for raw in candidates if raw and Path(str(raw)).is_file()]
        if paths:
            return paths
        return [Path(raw) for raw in fallback if raw and Path(raw).is_file()]

    def _confirm_vasco_import_plan(
        self,
        paths: Sequence[Path],
        names: Sequence[str],
    ) -> tuple[bool, int, str, date, date] | None:
        found = "\n".join(names) if names else "Vasco datoteke"
        answer = messagebox.askyesnocancel(
            "Vasco uvoz",
            f"Najdeno:\n{found}\n\n"
            "Uvozim VSE listine iz datotek.\n"
            "Že v bazi ne podvajam; izbrisane spet dodam.\n"
            "Potem v seznamu brišeš / popravljaš po potrebi.\n\n"
            "DA = uvozi vse (brez podvajanja)\n"
            "NE = najprej zbriši to obdobje, nato uvozi vse na novo\n"
            "Prekliči = prekini",
            parent=self.root,
        )
        if answer is None:
            return None
        return self._import_period_plan(paths, replace_requested=not bool(answer))

    def _import_period_plan(
        self,
        paths: Sequence[Path],
        *,
        replace_requested: bool,
    ) -> tuple[bool, int, str, date, date] | None:
        """Poln uvoz v trenutni seznam; zamenjava obdobja samo na izrecni NE."""
        key = infer_period_stamp(paths, fallback=self.filter_from_date)
        bounds = bounds_from_period_stamp(key) or (self.filter_from_date, self.filter_to_date)
        start, end = bounds
        rev = self._selected_period_rev() or 1
        if replace_requested:
            return True, 1, key or period_stamp(start), start, end
        return False, rev, key or period_stamp(start), start, end

    def _run_vasco_import_async(
        self,
        ir_files: Sequence[Path],
        pr_files: Sequence[Path],
        replace: bool,
        temp_dir: Path | None = None,
        origin: Mapping[str, Any] | None = None,
        *,
        period_rev: int = 1,
        period_key: str = "",
        period_from: date | None = None,
        period_to: date | None = None,
    ) -> None:
        """Uvoz Vasco v ozadju (ProgressDialog) — UI ne zmrzne."""
        if self._import_running:
            messagebox.showinfo("Vasco", "Uvoz že teče.", parent=self.root)
            cleanup_temp_dir(temp_dir)
            return
        ir_list = [Path(p) for p in ir_files if Path(p).is_file()]
        pr_list = [Path(p) for p in pr_files if Path(p).is_file()]
        if not ir_list and not pr_list:
            cleanup_temp_dir(temp_dir)
            messagebox.showinfo("Vasco", "Ni datotek za uvoz (Darila / Fitness / PR).", parent=self.root)
            return

        self._import_running = True
        progress = ProgressDialog(
            self.root,
            title="Vasco uvoz",
            message=f"Uvažam IR {len(ir_list)}, PR {len(pr_list)} …",
        )
        self.status_var.set(f"Uvažam Vasco: IR {len(ir_list)}, PR {len(pr_list)} …")
        db_path = self.db.path
        cache_dir = self._last_vasco_cache_dir(db_path)
        used_temp = temp_dir is not None
        origin_payload = dict(origin or {})

        def worker() -> None:
            err: Exception | None = None
            result: dict[str, int] | None = None
            remembered: dict[str, str] | None = None
            try:
                work_db = Database(db_path)
                result = import_vasco_files_to_db(
                    work_db,
                    ir_files=ir_list,
                    pr_files=pr_list,
                    replace_existing=bool(replace),
                    period_rev=period_rev,
                    period_key=period_key,
                    period_from=period_from,
                    period_to=period_to,
                )
                remembered = snapshot_last_vasco_import(
                    cache_dir=cache_dir,
                    origin=origin_payload,
                    ir_files=ir_list,
                    pr_files=pr_list,
                    used_temp=used_temp,
                )
                work_db.set_last_vasco_import(remembered)
            except Exception as exc:
                err = exc
            finally:
                cleanup_temp_dir(temp_dir)

            def finish() -> None:
                self._import_running = False
                progress.close()
                if err is not None:
                    messagebox.showerror("Vasco uvoz", str(err), parent=self.root)
                    self.status_var.set("Vasco uvoz ni uspel.")
                    return
                assert result is not None
                if remembered:
                    self._apply_last_vasco_import(remembered)
                self._finish_vasco_import(result)

            try:
                self.root.after(0, finish)
            except Exception:
                self._import_running = False

        threading.Thread(target=worker, daemon=True, name="vasco-import").start()

    def import_kirkpr(self) -> None:
        """Uvoz FURS KIR/KPR (ZIP/JSON/XML/CSV) → SQLite IR/PR."""
        if self._import_running:
            messagebox.showinfo("KIR/KPR", "Uvoz že teče.", parent=self.root)
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="FURS KIR/KPR (ZIP / JSON / XML / CSV)",
            initialdir=self._kirkpr_initial_dir(),
            filetypes=(
                ("KIR/KPR", "*.zip *.json *.xml *.csv"),
                ("ZIP", "*.zip"),
                ("JSON", "*.json"),
                ("XML", "*.xml"),
                ("CSV", "*.csv"),
                ("Vse", "*.*"),
            ),
        )
        if not path:
            return
        source = Path(path)
        answer = messagebox.askyesnocancel(
            "Uvoz FURS KIR/KPR",
            f"Datoteka: {source.name}\n\n"
            "DA = uvozi (brez podvajanja listin, ki so že v bazi)\n"
            "NE = najprej zbriši trenutno obdobje, nato uvozi\n"
            "Prekliči = prekini",
            parent=self.root,
        )
        if answer is None:
            return
        replace = not bool(answer)
        key = period_stamp(self.filter_from_date)
        start, end = self.filter_from_date, self.filter_to_date
        rev = 1 if replace else (self._selected_period_rev() or 1)
        if replace:
            rev = 1
        self._run_kirkpr_import_async(
            source,
            replace=replace,
            period_rev=rev,
            period_key=key,
            period_from=start,
            period_to=end,
        )

    def _run_kirkpr_import_async(
        self,
        source: Path,
        *,
        replace: bool,
        period_rev: int = 1,
        period_key: str = "",
        period_from: date | None = None,
        period_to: date | None = None,
    ) -> None:
        if self._import_running:
            messagebox.showinfo("KIR/KPR", "Uvoz že teče.", parent=self.root)
            return
        if not Path(source).is_file():
            messagebox.showinfo("KIR/KPR", "Datoteka ne obstaja.", parent=self.root)
            return
        self._import_running = True
        progress = ProgressDialog(
            self.root,
            title="FURS KIR/KPR uvoz",
            message=f"Uvažam {Path(source).name} …",
        )
        self.status_var.set(f"Uvažam FURS KIR/KPR: {Path(source).name} …")
        db_path = self.db.path

        def worker() -> None:
            err: Exception | None = None
            result: dict[str, Any] | None = None
            try:
                work_db = Database(db_path)
                result = import_kirkpr_file_to_db(
                    work_db,
                    source,
                    replace_existing=bool(replace),
                    period_rev=period_rev,
                    period_key=period_key,
                    period_from=period_from,
                    period_to=period_to,
                )
            except Exception as exc:
                err = exc

            def finish() -> None:
                self._import_running = False
                progress.close()
                if err is not None:
                    messagebox.showerror("FURS KIR/KPR uvoz", str(err), parent=self.root)
                    self.status_var.set("FURS KIR/KPR uvoz ni uspel.")
                    return
                assert result is not None
                self._finish_kirkpr_import(result)

            try:
                self.root.after(0, finish)
            except Exception:
                self._import_running = False

        threading.Thread(target=worker, daemon=True, name="kirkpr-import").start()

    def _finish_kirkpr_import(self, result: dict[str, Any]) -> None:
        """Enako kot Vasco po uvozu — osveži tabele + poročilo."""
        if "KIR" in self.ir_book_vars:
            self.ir_book_vars["KIR"].set(True)
        self.refresh_all()
        rev = int(result.get("period_rev") or 1)
        self._refresh_period_rev_choices(preferred=rev)
        self.apply_period_filter()
        added_ir = int(result.get("ir") or 0)
        added_pr = int(result.get("pr") or 0)
        skipped_ir = int(result.get("ir_skipped") or 0)
        skipped_pr = int(result.get("pr_skipped") or 0)
        for rid in result.get("ir_ids") or []:
            self.chk_state[f"ir:{int(rid)}"] = True
        for rid in result.get("pr_ids") or []:
            self.chk_state[f"pr:{int(rid)}"] = True
        if added_ir:
            self._populate_ir_tree()
        if added_pr:
            self._populate_pr_tree()
        warn = result.get("warnings") or []
        warn_line = f"\nOpozorila: {'; '.join(str(w) for w in warn[:3])}" if warn else ""
        rev_txt = revision_suffix(rev) or "osnovni"
        fmt = str(result.get("source_format") or "")
        report = (
            f"FURS → SQLite\n"
            f"Format: {fmt or Path(str(result.get('source') or '')).suffix}\n"
            f"Dodano: {added_ir} IR (KIR) in {added_pr} PR (KPR)\n"
            f"Preskočeno (že v bazi): {skipped_ir} IR, {skipped_pr} PR\n"
            f"Oznaka: {rev_txt}\n"
            f"Batch: {result.get('batch_id')}"
            f"{warn_line}\n\n"
            "Nadaljuj z DDV-O in »Sinhroniziraj Minimax«."
        )
        messagebox.showinfo("FURS KIR/KPR uvoz", report, parent=self.root)
        self.status_var.set(
            f"FURS: IR {added_ir} / PR {added_pr} · preskočeno {skipped_ir}/{skipped_pr}"
        )
        self.filter_info_var.set(self.status_var.get())
        if messagebox.askyesno(
            "Manjkajoče stranke",
            "Odprem manjkajoče stranke?\n\n"
            "SI z davčno: samodejno v Minimax API.\n"
            "EU/tretja: preveri z AI → SQL → Minimax.",
            parent=self.root,
        ):
            self.open_missing_journal_parties()

    def import_vasco(self) -> None:
        """Uvoz Vasco: mapa / ZIP / poti iz glave (3 datoteke Darila/Fitness/PR)."""
        if self._import_running:
            messagebox.showinfo("Vasco", "Uvoz že teče.", parent=self.root)
            return
        choice = messagebox.askyesnocancel(
            "Vasco uvoz",
            "DA = mapa (3 datoteke Darila/Fitness/PR)\n"
            "NE = ZIP z istimi datotekami\n"
            "Prekliči = uporabi poti iz glave",
            parent=self.root,
        )
        temp_dir: Path | None = None
        origin: dict[str, str] = {"source": "header", "dir": "", "zip": ""}
        try:
            if choice is True:
                folder = filedialog.askdirectory(
                    parent=self.root,
                    title="Mapa z Vasco datotekami (Darila / Fitness / PR)",
                    initialdir=self._vasco_initial_dir(),
                )
                if not folder:
                    return
                origin = {"source": "folder", "dir": folder, "zip": ""}
                darila, fitness, pr, temp_dir = resolve_vasco_sources(folder=Path(folder))
            elif choice is False:
                zip_path = filedialog.askopenfilename(
                    parent=self.root,
                    title="ZIP z Vasco datotekami (Darila / Fitness / PR)",
                    initialdir=self._vasco_initial_dir(),
                    filetypes=(("ZIP", "*.zip"), ("Vse", "*.*")),
                )
                if not zip_path:
                    return
                origin = {
                    "source": "zip",
                    "dir": str(Path(zip_path).parent),
                    "zip": zip_path,
                }
                darila, fitness, pr, temp_dir = resolve_vasco_sources(zip_path=Path(zip_path))
            else:
                header_dir = self._vasco_initial_dir()
                origin = {"source": "header", "dir": header_dir, "zip": ""}
                darila, fitness, pr, temp_dir = resolve_vasco_sources(
                    ir_darila=Path(self.ir_darila_var.get().strip()) if self.ir_darila_var.get().strip() else None,
                    ir_fitnes=Path(self.ir_fitnes_var.get().strip()) if self.ir_fitnes_var.get().strip() else None,
                    pr_file=Path(self.pr_var.get().strip()) if self.pr_var.get().strip() else None,
                )
        except Exception as exc:
            cleanup_temp_dir(temp_dir)
            messagebox.showerror("Vasco", str(exc), parent=self.root)
            return

        ir_files = [p for p in (darila, fitness) if p is not None and Path(p).is_file()]
        pr_files = [pr] if pr is not None and Path(pr).is_file() else []
        if not ir_files and not pr_files:
            cleanup_temp_dir(temp_dir)
            messagebox.showinfo(
                "Vasco",
                "Ni datotek Darila / Fitness / PR (mapa, ZIP ali poti iz glave).",
                parent=self.root,
            )
            return

        names = []
        if darila and Path(darila).is_file():
            names.append(f"Darila: {Path(darila).name}")
        if fitness and Path(fitness).is_file():
            names.append(f"Fitness: {Path(fitness).name}")
        if pr and Path(pr).is_file():
            names.append(f"PR: {Path(pr).name}")
        plan = self._confirm_vasco_import_plan([*ir_files, *pr_files], names)
        if plan is None:
            cleanup_temp_dir(temp_dir)
            return
        replace, rev, pkey, pfrom, pto = plan
        self._run_vasco_import_async(
            ir_files,
            pr_files,
            replace,
            temp_dir=temp_dir,
            origin=origin,
            period_rev=rev,
            period_key=pkey,
            period_from=pfrom,
            period_to=pto,
        )

    def import_vasco_fixed_paths(self) -> None:
        """Uvoz treh vnaprej izbranih poti (Darila / Fitness / KPF)."""
        if self._import_running:
            messagebox.showinfo("Vasco", "Uvoz že teče.", parent=self.root)
            return
        ir_files: list[Path] = []
        for raw in (self.ir_darila_var.get().strip(), self.ir_fitnes_var.get().strip()):
            path = Path(raw) if raw else None
            if path is not None and path.is_file():
                ir_files.append(path)
        pr_files: list[Path] = []
        pr_raw = self.pr_var.get().strip()
        if pr_raw:
            pr_path = Path(pr_raw)
            if pr_path.is_file():
                pr_files.append(pr_path)
        if not ir_files and not pr_files:
            messagebox.showinfo(
                "Vasco",
                "Nobena pot iz glave ne kaže na obstoječo datoteko.",
                parent=self.root,
            )
            return
        header_dir = ""
        if ir_files:
            header_dir = str(ir_files[0].parent)
        elif pr_files:
            header_dir = str(pr_files[0].parent)
        names = [f"{path.name}" for path in [*ir_files, *pr_files]]
        plan = self._confirm_vasco_import_plan([*ir_files, *pr_files], names)
        if plan is None:
            return
        replace, rev, pkey, pfrom, pto = plan
        self._run_vasco_import_async(
            ir_files,
            pr_files,
            replace,
            origin={"source": "header", "dir": header_dir, "zip": ""},
            period_rev=rev,
            period_key=pkey,
            period_from=pfrom,
            period_to=pto,
        )

    def open_excel_ir(self) -> None:
        """Odpri Excel Darila + Fitness zadnjega uvoza."""
        paths = self._excel_paths_to_open("IR")
        opened = 0
        for path in paths:
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]
                opened += 1
            except Exception as exc:
                messagebox.showerror("Excel IR", f"{path.name}: {exc}", parent=self.root)
                return
        if not opened:
            messagebox.showinfo(
                "Excel IR",
                "Ni datotek zadnjega uvoza (Darila / Fitness).\n"
                "Najprej Uvozi Vasco.",
                parent=self.root,
            )

    def open_excel_pr(self) -> None:
        """Odpri Excel PR zadnjega uvoza."""
        paths = self._excel_paths_to_open("PR")
        if not paths:
            messagebox.showinfo(
                "Excel PR",
                "Ni PR datoteke zadnjega uvoza.\nNajprej Uvozi Vasco.",
                parent=self.root,
            )
            return
        path = paths[0]
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Excel PR", str(exc), parent=self.root)

    def _store_vat_report(self, report: Any, *, persist: bool = True) -> None:
        """Zapomni si zadnjo preverbo in jo shrani na disk (za gumb Zadnja seja)."""
        from trops_studio.vat_api_check import save_vat_api_session

        key = f"{report.book}:{report.mode}"
        self._last_vat_reports[key] = report
        self._last_vat_report = report
        if persist and self.active_company is not None:
            try:
                save_vat_api_session(
                    zst=company_zst(self.active_company),
                    book=report.book,
                    mode=report.mode,
                    period_from=self.filter_from_date.isoformat(),
                    period_to=self.filter_to_date.isoformat(),
                    report=report,
                )
            except OSError:
                pass
        self._open_vat_report_dialog(report)

    def _open_vat_report_dialog(self, report: Any, *, session_label: str = "") -> None:
        def open_party(pid: int) -> None:
            if not self.db:
                return
            party = self.db.get_party(int(pid))
            if party:
                self.open_stranke(party=party)

        VatApiCheckDialog(
            self.root,
            self.db,
            report,
            on_applied=self.refresh_all,
            on_open_party=open_party,
            on_force_refresh=lambda: self.check_journal_vat_api(
                report.book, mode=report.mode, force_refresh=True
            ),
            company=self.active_company,
            period_from=self.filter_from_date,
            period_to=self.filter_to_date,
            session_label=session_label,
        )

    def open_last_vat_session(self, book: str, *, mode: str = "vat") -> None:
        """Odpri zadnjo shranjeno preverbo IR/PR/FO — brez ponovnega klica API."""
        from trops_studio.vat_api_check import load_vat_api_session

        book = (book or "IR").upper()
        if book not in {"IR", "PR"}:
            book = "IR"
        mode = "fo" if mode == "fo" else "vat"
        title = "Zadnja FO" if mode == "fo" else f"Zadnja seja {book}"
        if not self.active_company:
            messagebox.showinfo(title, "Ni izbrane firme.", parent=self.root)
            return
        rec = load_vat_api_session(company_zst(self.active_company), book, mode)
        if not rec:
            report = (getattr(self, "_last_vat_reports", {}) or {}).get(f"{book}:{mode}")
            if report is not None:
                self._open_vat_report_dialog(report, session_label="zadnja seja (ta zagon)")
                return
            hint = (
                "Najprej zaženi »Preverba fizičnih oseb«."
                if mode == "fo"
                else f"Najprej zaženi »Preveri {book} z API«."
            )
            messagebox.showinfo(
                title,
                "Ni shranjene seje za to firmo.\n\n"
                f"{hint}\nNato je seznam tu, tudi po ponovnem zagonu.",
                parent=self.root,
            )
            return
        report = rec["report"]
        self._last_vat_reports[f"{book}:{mode}"] = report
        self._last_vat_report = report
        parts = ["zadnja seja"]
        if rec.get("label"):
            parts.append(str(rec["label"]))
        start = parse_iso_date(rec.get("period_from"))
        end = parse_iso_date(rec.get("period_to"))
        if start and end:
            parts.append(f"{format_si_date(start)} – {format_si_date(end)}")
        label = " · ".join(parts)
        self.status_var.set(f"{title}: {report.message}")
        self._open_vat_report_dialog(report, session_label=label)

    def check_journal_vat_api(
        self, book: str, *, mode: str = "vat", force_refresh: bool = False
    ) -> None:
        """Preveri IR ali PR obdobja po davčnih (AJPES / VIES / Minimax API)."""
        if self.db is None:
            messagebox.showinfo("Preveri z API", "Ni odprte baze.", parent=self.root)
            return
        book = (book or "IR").upper()
        if book not in {"IR", "PR"}:
            book = "IR"
        mode = "fo" if mode == "fo" else "vat"
        from trops_studio.vat_api_check import has_country_prefixed_vat_id, official_register

        ir_rows, pr_rows = self._period_rows()
        source = ir_rows if book == "IR" else pr_rows
        if book == "IR":
            books = self._active_ir_books()
            if books:
                source = [row for row in source if str(row.get("book") or "") in books]
        if not source:
            messagebox.showinfo(
                f"Preveri {book} z API",
                "V obdobju ni listin za preverbo.",
                parent=self.root,
            )
            return
        parties_by_vat = self._party_by_vat_index()
        parties_by_id = self._party_by_id_index()
        items: list[dict[str, Any]] = []
        skipped_no_vat = 0
        title = "Preverba fizičnih oseb" if mode == "fo" else f"Preveri {book} z API"
        for row in source:
            party = self._party_for_pr_row(row, by_vat=parties_by_vat, by_id=parties_by_id)
            vat = str(row.get("vat_id") or row.get("tax_number") or "")
            if book == "IR":
                prefixed = has_country_prefixed_vat_id(vat)
                checkable = bool(official_register(vat)) or prefixed
                if mode == "vat" and not checkable:
                    skipped_no_vat += 1
                    continue
                if mode == "fo" and prefixed:
                    continue
            if book == "IR":
                classified = apply_ir_eu_sale(row, party)
                region = ir_customer_region(classified, party)
                country = ir_customer_country(classified, party)
                name = str(row.get("party_name") or "")
                day = date_text(row.get("document_date") or row.get("booking_date"))
            else:
                region = pr_corrected_region(row, party)
                country = str((party or {}).get("country") or "")
                name = str(row.get("supplier_name") or "")
                day = date_text(row.get("received_date") or row.get("document_date"))
            items.append(
                {
                    "row_id": row.get("id"),
                    "party_id": (party or {}).get("id") or row.get("party_id"),
                    "document_no": row.get("document_no") or "",
                    "date": day,
                    "name": name,
                    "vat_id": vat,
                    "region": region,
                    "country": country,
                }
            )
        if book == "IR" and not items:
            if mode == "fo":
                messagebox.showinfo(
                    title,
                    "V obdobju ni IR brez predpone SI/DE/US\n"
                    "(fizične osebe / končni kupci).",
                    parent=self.root,
                )
            else:
                extra = f"\nIzločeno brez ID za DDV: {skipped_no_vat}." if skipped_no_vat else ""
                messagebox.showinfo(
                    title,
                    "V obdobju ni ID za DDV s predpono SI / EU / tretja država.\n"
                    "Brez predpone (FO) → »Preverba fizičnih oseb«."
                    f"{extra}",
                    parent=self.root,
                )
            return
        org_id = company_org_id(self.active_company) if self.active_company else ""
        cancelled = {"flag": False}
        progress = ProgressDialog(
            self.root,
            title=title,
            message=(
                "Znova pri Minimax / VIES / spletu …"
                if force_refresh
                else (
                    "Preverjam fizične osebe — shranjeni zadetki se uporabijo takoj …"
                    if mode == "fo"
                    else "Preverjam: SI Minimax, EU VIES, tretje splet …"
                )
            ),
            cancelable=True,
            on_cancel=lambda: cancelled.__setitem__("flag", True),
        )

        def worker() -> None:
            err: Exception | None = None
            report = None
            try:
                from trops_studio.vat_api_check import check_journal_vats

                report = check_journal_vats(
                    items,
                    book=book,
                    org_id=org_id,
                    mode=mode,
                    force_refresh=force_refresh,
                    progress=lambda cur, tot, msg: self.root.after(
                        0,
                        lambda c=cur, t=tot, m=msg: progress.set_progress(c, t, detail=m),
                    ),
                    cancelled=lambda: cancelled["flag"],
                )
            except Exception as exc:
                err = exc

            def done() -> None:
                progress.close()
                if err is not None:
                    messagebox.showerror(title, str(err), parent=self.root)
                    return
                if report is None:
                    return
                self.status_var.set(f"{book} API: {report.message}")
                self._store_vat_report(report)

            try:
                self.root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True, name=f"vat-api-{book}").start()

    def send_vat_irregularities(self, book: str, *, mode: str = "") -> None:
        """Pošlji stranki seznam drugačnih davčnih (zavezanci in/ali fizične osebe)."""
        from trops_studio.ddvo_actions import GMAIL_SMTP_CC, client_email_to
        from trops_studio.ui.smtp_compose_dialog import SmtpComposeDialog
        from trops_studio.vat_api_check import format_vat_irregularities_email, irregularity_rows

        book = (book or "IR").upper()
        reports = getattr(self, "_last_vat_reports", {}) or {}
        vat_report = reports.get(f"{book}:vat")
        fo_report = reports.get(f"{book}:fo")
        if mode == "fo":
            vat_report = None
        elif mode == "vat":
            fo_report = None
        vat_rows = irregularity_rows(vat_report) if vat_report else []
        fo_rows = irregularity_rows(fo_report) if fo_report else []
        if not vat_rows and not fo_rows:
            if mode == "fo" and fo_report is not None:
                hint = (
                    "V FO preverbi ni primerov s 8-mestno davčno brez SI, "
                    "kjer AJPES kaže firmo ali je v nazivu s.p."
                )
            elif mode == "fo":
                hint = "Najprej zaženi »Preverba fizičnih oseb«."
            else:
                hint = (
                    f"Najprej zaženi »Preveri {book} z API« "
                    "in po želji »Preverba fizičnih oseb«."
                )
            messagebox.showinfo("Pošlji seznam nepravilnosti", hint, parent=self.root)
            return
        to_addr = client_email_to(self.active_company)
        if not to_addr:
            messagebox.showerror(
                "Pošlji seznam nepravilnosti",
                "Manjka e-pošta stranke (polje Email v evidenci firm).",
                parent=self.root,
            )
            return
        period = (
            f"{format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)}"
        )
        extra = (
            [("V potrditev: listina ni zavezanec, AJPES je zavezanec", fo_rows)]
            if fo_rows and vat_rows
            else None
        )
        primary = vat_rows or fo_rows
        subject, body = format_vat_irregularities_email(
            primary,
            book=book,
            mode="fo" if fo_rows and not vat_rows else "vat",
            company_name=company_name(self.active_company or {}),
            period_label=period,
            extra_sections=extra,
        )
        SmtpComposeDialog(
            self.root,
            title="Pošlji seznam nepravilnosti — predogled SMTP",
            to_addr=to_addr,
            cc=GMAIL_SMTP_CC,
            subject=subject,
            body_html=body,
            on_sent=lambda note: self.status_var.set(note.split("\n", 1)[0]),
        )

    def _run_pr_si_vat_control(self) -> None:
        """Naknadna kontrola: tujec/EU z ID za DDV SI+DŠ."""
        if self.db is None:
            messagebox.showinfo("Kontrola PR", "Ni odprte baze.", parent=self.root)
            return
        parties_by_vat = self._party_by_vat_index()
        parties_by_id = self._party_by_id_index()
        hits: list[str] = []
        marked = 0
        for row in self._pr_cache:
            if not self._row_in_period(
                row, date_keys=("received_date", "document_date", "booking_date")
            ):
                continue
            party = self._party_for_pr_row(row, by_vat=parties_by_vat, by_id=parties_by_id)
            if not pr_si_vat_on_non_domestic(row, party):
                continue
            payload = dict(row)
            before_status = str(row.get("status") or "")
            before_notes = str(row.get("notes") or "")
            apply_pr_si_vat_flag(payload, party)
            if row.get("id") and (
                str(payload.get("status") or "") != before_status
                or str(payload.get("notes") or "") != before_notes
            ):
                self.db.upsert_pr(payload, int(row["id"]))
                row.update(payload)
                marked += 1
            hits.append(
                f"{row.get('seq') or '—'}  {row.get('supplier_name') or '—'}"
                f"  {row.get('vat_id') or '—'}  {row.get('document_no') or ''}"
            )
        self.pr_filter_si_vat.set(True)
        self._populate_pr_tree()
        if not hits:
            messagebox.showinfo(
                "Kontrola PR",
                "V obdobju ni tujca/EU z ID za DDV SI+DŠ.",
                parent=self.root,
            )
            self.status_var.set("Kontrola PR: brez napak")
            return
        preview = "\n".join(hits[:20])
        extra = f"\n… še {len(hits) - 20}" if len(hits) > 20 else ""
        mark_line = f"\nOznačeno Popravi: {marked}" if marked else ""
        messagebox.showwarning(
            "Kontrola PR",
            f"{len(hits)}× tujec/EU z ID za DDV SI+DŠ{mark_line}\n\n"
            f"{preview}{extra}\n\n"
            "Filter »SI+DŠ na EU« je vklopljen. Popravi ID (BG…, NL…).",
            parent=self.root,
        )
        self.status_var.set(f"Kontrola PR: {len(hits)}× SI+DŠ na tujcu")

    def delete_import_for_period(self) -> None:
        """Izbriši IR/PR v trenutno izbranem obdobju (SQLite)."""
        ir_rows, pr_rows = self._period_rows()
        n_ir, n_pr = len(ir_rows), len(pr_rows)
        if not n_ir and not n_pr:
            messagebox.showinfo(
                "Briši uvoz obdobja",
                f"V obdobju {format_si_date(self.filter_from_date)} – "
                f"{format_si_date(self.filter_to_date)} ni IR/PR vrstic.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Briši uvoz obdobja",
            f"Obdobje: {format_si_date(self.filter_from_date)} – "
            f"{format_si_date(self.filter_to_date)}\n\n"
            f"Izbrisati IR: {n_ir}, PR: {n_pr}?\n"
            "(Trajno iz SQLite.)",
            parent=self.root,
        ):
            return
        try:
            ir_ids = [int(r["id"]) for r in ir_rows if r.get("id") is not None]
            pr_ids = [int(r["id"]) for r in pr_rows if r.get("id") is not None]
            deleted_ir = self.db.delete_ir(ir_ids)
            deleted_pr = self.db.delete_pr(pr_ids)
        except Exception as exc:
            messagebox.showerror("Briši uvoz obdobja", str(exc), parent=self.root)
            return
        self.refresh_all()
        self.status_var.set(f"Izbrisano obdobje: IR {deleted_ir}, PR {deleted_pr}")
        messagebox.showinfo(
            "Briši uvoz obdobja",
            f"Izbrisano: IR {deleted_ir}, PR {deleted_pr}.",
            parent=self.root,
        )

    def learn_accounts_from_history(self) -> None:
        """Zapomni konti po strankah iz že vnešenih IR/PR (npr. maj → junij)."""
        result = self.db.learn_account_rules_from_rows()
        self.ir_account_combo.configure(values=self._account_choices("customer"))
        self.pr_account_combo.configure(values=self._account_choices("supplier"))
        messagebox.showinfo(
            "Konti iz zgodovine",
            f"Zapisana / posodobljena pravila:\n"
            f"PR (dobavitelji): {result['pr']}\n"
            f"IR (kupci): {result['ir']}\n\n"
            "Ob naslednjem Vasco uvozu se konti za znane stranke vpišejo samodejno.\n"
            "Nove PR stranke dobijo 4190 (lahko popraviš in zapomniš).",
            parent=self.root,
        )
        self.status_var.set(f"Konti iz zgodovine: PR {result['pr']}, IR {result['ir']}")

    def add_row(self, kind: str) -> None:
        org_id = company_org_id(self.active_company) if self.active_company else ""
        if kind == "IR":
            defaults: dict[str, Any] = {
                "book": "Darila", "seq": 0, "document_no": "", "party_name": "", "vat_id": "",
                "net": "0", "vat_22": "0", "vat_95": "0", "total": "0", "exempt": "0", "excluded": "0",
                "account": DEFAULT_IR_REVENUE_ACCOUNT,
                "status": DEFAULT_ROW_STATUS, "notes": "",
            }

            def save(payload: dict[str, Any]) -> None:
                self._persist_editor_row("IR", payload)
                self.refresh_after_edit("IR")

            IrEditorDialog(
                self.root,
                self.db,
                row=defaults,
                parties=self._party_cache,
                org_id=org_id,
                on_save=save,
                remember_default=bool(self.remember_customer_var.get()),
            )
        else:
            defaults = {
                "seq": 0, "document_no": "", "internal_no": "", "supplier_name": "", "vat_id": "",
                "net_taxable": "0", "vat_22": "0", "vat_95": "0", "vat_5": "0",
                "f76a": "0", "eu_goods": "0", "eu_services": "0", "exempt_on": "0",
                "excluded": "0", "nondeduct_22": "0",
                "odhodek01": DEFAULT_PR_EXPENSE_ACCOUNT,
                "odhodek07": "",
                "odhodek10": "",
                "odhodek11": "",
                "odhodek_excluded": DEFAULT_PR_EXCLUDED_ACCOUNT,
                "placilo": "2200",
                "status": DEFAULT_ROW_STATUS, "notes": "",
            }

            def save(payload: dict[str, Any]) -> None:
                self._persist_editor_row("PR", payload)
                self.refresh_after_edit("PR")

            PrEditorDialog(
                self.root,
                self.db,
                row=defaults,
                parties=self._party_cache,
                org_id=org_id,
                on_save=save,
                remember_default=bool(self.remember_supplier_var.get()),
            )

    def edit_selected(self, kind: str) -> None:
        rid = self._edit_target_id(kind)
        if rid is None:
            messagebox.showinfo("Uredi", "Izberi vrstico (klik v tabeli).", parent=self.root)
            return
        self._open_row_editor(kind, rid)

    def _visible_neighbor_ids(self, kind: str) -> list[int]:
        """Hitri sosedje za ‹ › — iz že naloženega cache (brez težkih filtrov)."""
        if kind == "IR":
            tree_ids = [self._id_from_tree_iid(i) for i in self.ir_tree.get_children("")]
        else:
            tree_ids = [self._id_from_tree_iid(i) for i in self.pr_tree.get_children("")]
        return [int(x) for x in tree_ids if x is not None]

    def _open_row_editor(self, kind: str, row_id: int) -> None:
        org_id = company_org_id(self.active_company) if self.active_company else ""
        neighbors = self._visible_neighbor_ids(kind)
        if kind == "IR":
            row = self.db.get_ir(row_id)
            if not row:
                return

            def save(payload: dict[str, Any]) -> None:
                self._persist_editor_row("IR", payload, base_id=row_id)
                self.refresh_after_edit("IR")

            IrEditorDialog(
                self.root,
                self.db,
                row=row,
                parties=self._party_cache,
                org_id=org_id,
                neighbor_ids=neighbors,
                on_save=save,
                on_navigate=lambda nid: self.db.get_ir(nid),
                remember_default=bool(self.remember_customer_var.get()),
            )
        else:
            row = self.db.get_pr(row_id)
            if not row:
                return

            def save(payload: dict[str, Any]) -> None:
                self._persist_editor_row("PR", payload, base_id=row_id)
                self.refresh_after_edit("PR")

            PrEditorDialog(
                self.root,
                self.db,
                row=row,
                parties=self._party_cache,
                org_id=org_id,
                neighbor_ids=neighbors,
                on_save=save,
                on_navigate=lambda nid: self.db.get_pr(nid),
                remember_default=bool(self.remember_supplier_var.get()),
            )

    def delete_selected(self, kind: str) -> None:
        ids = self._selected_ids(kind)
        if not ids:
            return
        if not messagebox.askyesno("Izbriši", f"Izbrisati {len(ids)} vrstic?", parent=self.root):
            return
        if kind == "IR":
            self.db.delete_ir(ids)
        else:
            self.db.delete_pr(ids)
        self.refresh_after_edit(kind)

    def open_stranke(
        self,
        foreign: bool = False,
        party: dict[str, Any] | None = None,
        *,
        auto_vies: bool = False,
        name_aliases: Sequence[str] | None = None,
    ) -> None:
        seed = dict(party or {})
        if foreign and not party:
            seed["is_foreign"] = 1
            seed["country"] = ""
        dialog = StrankeDialog(
            self.root,
            self.db,
            party=seed or None,
            org_id=company_org_id(self.active_company) if self.active_company else "",
            on_saved=self.refresh_all,
            auto_vies=auto_vies,
            name_aliases=name_aliases,
        )
        self.root.wait_window(dialog)
        self.refresh_all()

    def _checked_party_ids(self) -> list[int]:
        ids: list[int] = []
        for item in self.party_tree.get_children(""):
            if not self.chk_state.get(item):
                continue
            rid = self._id_from_tree_iid(item)
            if rid is not None:
                ids.append(rid)
        if ids:
            return ids
        for item in self.party_tree.selection():
            rid = self._id_from_tree_iid(item)
            if rid is not None:
                ids.append(rid)
        return ids

    def _toggle_chk_parties(self) -> str:
        for item in self.party_tree.selection() or ():
            self.chk_state[item] = not bool(self.chk_state.get(item))
        self._populate_parties_tree()
        return "break"

    def _set_chk_all_parties(self, value: bool) -> None:
        items = list(self.party_tree.get_children(""))
        for item in items:
            self.chk_state[item] = value
        self._populate_parties_tree()
        tree = self.party_tree
        checked = [item for item in tree.get_children("") if self.chk_state.get(item)]
        if value and checked:
            tree.selection_set(checked)
        else:
            tree.selection_remove(*tree.selection())

    def _on_party_tree_click(self, event: tk.Event) -> None:
        if self.party_tree.identify_column(event.x) != "#1":
            return
        item = self.party_tree.identify_row(event.y)
        if not item:
            return
        self.chk_state[item] = not bool(self.chk_state.get(item))
        self._populate_parties_tree()

    def merge_selected_parties(self) -> None:
        """Združi Chk-označene stranke v eno (Adobe tip), nato odpri šifriranje."""
        ids = self._checked_party_ids()
        if len(ids) < 2:
            messagebox.showinfo(
                "Združi stranke",
                "Označi (Chk) vsaj dve stranki z različnimi nazivi iste firme.",
                parent=self.root,
            )
            return
        names: list[str] = []
        for pid in ids:
            party = self.db.get_party(pid)
            if party:
                names.append(str(party.get("name") or f"#{pid}"))
        preview = "\n".join(f"• {n}" for n in names[:12])
        if len(names) > 12:
            preview += f"\n… (+{len(names) - 12})"
        if not messagebox.askyesno(
            "Združi stranke",
            f"Združim {len(ids)} strank v eno?\n\n{preview}\n\n"
            "IR/PR se vežejo na ohranjeno stranko (prednost: MM šifra).",
            parent=self.root,
        ):
            return
        try:
            keeper_id, removed, aliases = merge_parties(self.db, ids)
        except Exception as exc:
            messagebox.showerror("Združi stranke", str(exc), parent=self.root)
            return
        for pid in ids:
            self.chk_state.pop(f"party:{pid}", None)
        self.refresh_all()
        keeper = self.db.get_party(keeper_id) if keeper_id else None
        if not keeper:
            messagebox.showinfo(
                "Združi stranke",
                f"Združeno · odstranjenih {removed}.",
                parent=self.root,
            )
            return
        open_form = messagebox.askyesno(
            "Združi stranke",
            f"Združeno v #{keeper_id} · odstranjenih {removed}.\n\n"
            f"Naziv: {keeper.get('name') or '—'}\n"
            f"MM šifra: {keeper.get('minimax_code') or '— (še ni)'}\n\n"
            "Odprem obrazec za Išči v Minimax / šifriranje?",
            parent=self.root,
        )
        if open_form:
            self.open_stranke(party=keeper, name_aliases=aliases)

    def edit_selected_party(self) -> None:
        selection = self.party_tree.selection()
        if not selection:
            messagebox.showinfo("Stranke", "Izberi stranko.", parent=self.root)
            return
        party_id = int(str(selection[0]).split(":", 1)[1])
        party = self.db.get_party(party_id)
        if party:
            self.open_stranke(party=party)

    def check_party_vies(self) -> None:
        """Odpri obrazec Stranke za VIES preverjanje (izbrana ali prazna)."""
        selection = self.party_tree.selection()
        party = None
        if selection:
            try:
                party_id = int(str(selection[0]).split(":", 1)[1])
                party = self.db.get_party(party_id)
            except (IndexError, ValueError):
                party = None
        if party is None:
            self.open_stranke(foreign=True, auto_vies=True)
            return
        self.open_stranke(party=party, auto_vies=True)

    def open_missing_journal_parties(self, book: str = "PR") -> None:
        """Pregled strank iz IR/PR, ki še nimajo Minimax šifre (enaka forma kot pred sync)."""
        if not self.active_company:
            messagebox.showinfo("Stranke", "Najprej izberi podjetje.", parent=self.root)
            return
        org_id = company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror(
                "Stranke",
                "Podjetje nima Org_ID — nastavi Minimax organizacijo.",
                parent=self.root,
            )
            return
        dlg = MissingJournalPartiesDialog(
            self.root,
            self.db,
            org_id=str(org_id),
            book=book,
            review_mode=True,
            on_done=self.refresh_all,
        )
        self.root.wait_window(dlg)
        self.refresh_all()

    def delete_selected_party(self) -> None:
        ids = self._checked_party_ids()
        if not ids:
            messagebox.showinfo("Stranke", "Označi (Chk) ali izberi stranko.", parent=self.root)
            return
        label = f"{len(ids)} strank" if len(ids) > 1 else f"stranko #{ids[0]}"
        if not messagebox.askyesno("Stranke", f"Izbrisati {label}?", parent=self.root):
            return
        for party_id in ids:
            self.db.delete_party(party_id)
            self.chk_state.pop(f"party:{party_id}", None)
        self.refresh_all()

    def party_from_selected_pr(self) -> None:
        ids = self._selected_ids("PR")
        if not ids:
            messagebox.showinfo("Stranke", "Izberi PR vrstico.", parent=self.root)
            return
        row = self.db.get_pr(ids[0])
        if not row:
            return
        vat = str(row.get("vat_id") or "")
        foreign = bool(vat) and not vat.upper().startswith("SI")
        self.open_stranke(
            foreign=foreign,
            party={
                "vat_id": vat,
                "tax_number": row.get("tax_number") or "",
                "name": row.get("supplier_name") or "",
                "is_foreign": 1 if foreign else 0,
                "country": "" if foreign else "SI",
            },
        )

    def _sort_tree(self, tree: ttk.Treeview, column: str, reverse: bool) -> None:
        def key(item: str) -> tuple[int, Any]:
            value = tree.set(item, column)
            if column in {
                "zapst", "p8", "net", "exempt", "f76a", "vat", "vat_22",
                "vat_95", "vat_5", "gross", "id", "excluded",
            }:
                try:
                    return (0, decimal_value(value))
                except Exception:
                    pass
            return (1, str(value).casefold())

        items = sorted(tree.get_children(""), key=key, reverse=reverse)
        for position, item in enumerate(items):
            tree.move(item, "", position)
        tree.heading(column, command=lambda: self._sort_tree(tree, column, not reverse))


def run_app(db_path: Path | None = None) -> None:
    root = tk.Tk()
    ProjestStudioApp(root, Database(db_path) if db_path else Database())
    root.mainloop()
