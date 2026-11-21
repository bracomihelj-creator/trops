"""Access-podoben urejevalnik PR: statusi, stranka, konti, predogled knjižb."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

from trops_studio.account_choices import (
    account_cache_has_minimax,
    account_code_from_choice,
    ensure_choice,
    filter_account_choices,
    is_known_account_code,
    load_account_choices,
    parse_party_choice,
    party_choices,
    resolve_committed_account,
    warm_account_cache_minimax,
)
from trops_studio.accounts import allocate_pr_accounts
from trops_studio.db import Database
from trops_studio.journal_preview import (
    extra_journal_lines,
    extra_lines_net,
    journal_imbalance,
    normalize_extra_journal_line,
    preview_pr_journals,
    serialize_extra_journal_lines,
)
from trops_studio.minimax_os_fill import open_and_fill_osnovno_sredstvo
from trops_studio.os_accounts import (
    DEFAULT_OS_CONTRA,
    OS_KPR_EXEMPT_LABELS,
    OS_KPR_TAXED_LABELS,
    default_os_kpr_field,
    first_fixed_asset_account,
    is_fixed_asset_account,
    os_aop_hint,
    os_kpr_code,
    os_kpr_label,
    resolve_os_allocations,
    resolve_os_book,
)
from trops_studio.money import (
    ProjestError,
    date_text,
    decimal_value,
    is_nonzero,
    money_text,
    normalize_text,
    normalize_vat_id,
)
from trops_studio.pr_list_view import is_si_ds_vat, pr_si_vat_on_non_domestic
from trops_studio.parties_ensure import _strip_name_markers, resolve_party_for_journal_row
from trops_studio.pr_vat_flags import flags_offer_text, resolve_pr_vat_flags, source_self_assessment_pr
from trops_studio.row_status import DEFAULT_ROW_STATUS, ROW_STATUSES, STATUS_SHRANJENO, normalize_status
from trops_studio.sync_state import SYNC_READY
from trops_studio.ui.filtered_combo import FilteredCombobox
from trops_studio.ui.stranke_dialog import StrankeDialog
from trops_studio.ui.tooltip import ToolTip
from trops_studio.edavki_links import (
    PROJEST_NAME,
    PROJEST_TAX_ID,
    open_edavki_mrn_dates,
)
from trops_studio.vat_accounts import (
    infer_supplier_kind,
    is_third_country_digital_supplier,
    kind_label,
    payable_account,
    pr_vat_kind,
    row_supplier_kind,
    supplier_kind_label,
)


def _money_var(value: Any) -> str:
    if value in (None, ""):
        return "0,00"
    return money_text(value)


def _date_var(value: Any) -> str:
    return date_text(value) if value else ""


class PrEditorDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Tk,
        db: Database,
        *,
        row: Mapping[str, Any],
        parties: Sequence[Mapping[str, Any]] | None = None,
        org_id: str = "",
        neighbor_ids: Sequence[int] | None = None,
        on_save: Callable[[dict[str, Any]], None],
        on_navigate: Callable[[int], Mapping[str, Any] | None] | None = None,
        remember_default: bool = False,
    ) -> None:
        super().__init__(master)
        self.db = db
        self._on_save = on_save
        self._get_neighbor_row = on_navigate
        self._row = dict(row)
        self._row_id = int(row["id"]) if row.get("id") else None
        self._neighbors = [int(x) for x in (neighbor_ids or [])]
        # Uporabi predani cache iz glavnega okna — ne list_parties() ob vsakem Odpri
        self._parties = list(parties) if parties is not None else []
        self._org_id = str(org_id or "").strip()
        self._account_choices = load_account_choices(db, self._org_id or None, fetch_minimax=False)
        self._acct_combos: list[FilteredCombobox] = []
        self._party_labels: list[str] = []
        self._vars: dict[str, tk.StringVar] = {}
        self._party_id: Any = row.get("party_id")
        self.remember_var = tk.BooleanVar(value=bool(remember_default))
        self.self_assessment_var = tk.BooleanVar(value=False)
        self.vat_deductible_var = tk.BooleanVar(value=True)
        self.supplier_kind_var = tk.StringVar(value="SI")
        self._vat_offer_var = tk.StringVar(value="")
        self._suppress_vat_trace = False
        self._loading = True
        self._kind_updating = False
        self._extra_lines: list[dict[str, Any]] = []
        self._pay_manual = False
        self._suppress_pay_trace = False

        title = f"Uredi PR #{self._row_id}" if self._row_id else "Nov PR"
        self.title(title)
        self.transient(master)
        self.grab_set()
        self.configure(bg="#101a2f")
        self.minsize(980, 780)

        buttons = ttk.Frame(self, padding=(14, 8, 14, 14))
        buttons.pack(side="bottom", fill="x")
        ttk.Button(buttons, text="Prekliči", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Shrani", style="Success.TButton", command=self._save).pack(
            side="right", padx=(0, 8)
        )
        btn_confirm = ttk.Button(
            buttons, text="Potrdi → Minimax", command=lambda: self._save(confirm=True)
        )
        btn_confirm.pack(side="right", padx=(0, 8))
        flags = ttk.Frame(buttons)
        flags.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(
            flags,
            text="Zapomni si konto, samoobdavčitev in DDV se odbija za dobavitelja",
            variable=self.remember_var,
        ).pack(anchor="w")
        ttk.Checkbutton(
            flags, text="Samoobdavčitev", variable=self.self_assessment_var, command=self._on_vat_flags_change
        ).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(
            flags, text="DDV se odbija", variable=self.vat_deductible_var, command=self._on_vat_flags_change
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(flags, textvariable=self._vat_offer_var, style="Muted.TLabel", wraplength=560).pack(
            anchor="w", pady=(4, 0)
        )
        ToolTip(
            flags,
            "Kot v KIR/KPR: samoobdavčitev (P9–P11) knjiži obračunani DDV v dobro (2600x);\n"
            "»DDV se odbija« knjiži vhodni DDV v breme (1600x). Brez odbitka gre DDV v strošek.",
        )
        ToolTip(btn_confirm, "Potrdi v SQL (ready). Minimax sync ločeno po potrditvi.")

        outer = ttk.Frame(self, padding=(14, 14, 14, 0))
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, bg="#101a2f", borderwidth=0)
        ybar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=ybar.set)
        ybar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, padding=(0, 0, 8, 8))
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_id, width=max(e.width, 1)))

        def _wheel(event: tk.Event) -> None:
            if getattr(event, "delta", 0):
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self._scroll_canvas = canvas

        self._build_header(body)
        self._build_party(body)
        self._build_amounts(body)
        self._build_journals(body)
        self._fill_from_row(self._row)
        self._refresh_journals()
        self._loading = False
        self._fit_window(preferred_w=1180, preferred_h=960)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        # Minimax kontni plan v ozadju — ne blokira odprtja
        if self._org_id:
            self.after(50, self._warm_accounts_from_minimax)

    def _var(self, key: str, value: str = "") -> tk.StringVar:
        if key not in self._vars:
            self._vars[key] = tk.StringVar(value=value)
        return self._vars[key]

    def _build_header(self, parent: ttk.Frame) -> None:
        head = ttk.LabelFrame(parent, text="Glava / status", padding=10)
        head.pack(fill="x", pady=(0, 10))
        nav = ttk.Frame(head)
        nav.pack(fill="x")
        btn_prev = ttk.Button(nav, text="‹", width=3, command=lambda: self._nav(-1))
        btn_prev.pack(side="left")
        btn_next = ttk.Button(nav, text="›", width=3, command=lambda: self._nav(1))
        btn_next.pack(side="left", padx=(4, 10))
        ToolTip(btn_prev, "Prejšnji PR v filtru.")
        ToolTip(btn_next, "Naslednji PR v filtru.")

        ttk.Label(nav, text="ID / veza").pack(side="left")
        veza = ttk.Entry(nav, textvariable=self._var("internal_no"), width=18)
        veza.pack(side="left", padx=(6, 14))
        ToolTip(veza, "Vasco Opombe / interna veza (npr. 260186).")

        ttk.Label(nav, text="Status").pack(side="left")
        status = ttk.Combobox(
            nav,
            textvariable=self._var("status"),
            values=list(ROW_STATUSES),
            width=16,
            state="readonly",
        )
        status.pack(side="left", padx=(6, 0))
        ToolTip(
            status,
            "Za sortiranje napak iz Excela:\n"
            "Popravi / Popravljeno / Shranjeno / Manjka konto / Poglej.\n"
            "OSNUTEK = legacy uvoz.",
        )

        from trops_studio.ui.date_picker import make_date_entry

        dates = ttk.Frame(head)
        dates.pack(fill="x", pady=(8, 0))
        date_keys = {"received_date", "document_date", "booking_date"}
        for i, (key, label) in enumerate(
            (
                ("received_date", "Datum prejema"),
                ("document_date", "Datum listine"),
                ("booking_date", "Datum knjižbe"),
                ("document_no", "Številka listine"),
                ("seq", "ZŠ"),
            )
        ):
            cell = ttk.Frame(dates)
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 8))
            ttk.Label(cell, text=label).pack(anchor="w")
            if key in date_keys:
                make_date_entry(cell, self._var(key), width=14).pack(fill="x")
            else:
                ttk.Entry(cell, textvariable=self._var(key), width=14).pack(fill="x")
        dates.columnconfigure((0, 1, 2, 3, 4), weight=1)

        ttk.Label(head, text="Opis (opombe)").pack(anchor="w", pady=(8, 0))
        ttk.Entry(head, textvariable=self._var("notes")).pack(fill="x")

    def _party_filter(self, needle: str) -> list[str]:
        """Živ filter strank iz SQLite (*vnos* po nazivu / DDV / MM)."""
        return party_choices(self.db.search_parties(needle, limit=150))

    def _build_party(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Dobavitelj / stranka", padding=10)
        box.pack(fill="x", pady=(0, 10))
        ttk.Label(box, text="Stranka (šifrant)").grid(row=0, column=0, sticky="w")
        self.party_combo = FilteredCombobox(
            box,
            textvariable=self._var("party_label"),
            values=self._party_labels,
            width=60,
            filter_provider=self._party_filter,
        )
        self.party_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.party_combo.bind("<<ComboboxSelected>>", self._on_party_selected)
        self.party_combo.bind("<Return>", self._on_party_selected)
        ToolTip(
            self.party_combo,
            "Zamenjaj stranko iz SQLite šifranta.\n"
            "Tipkaj *vnos* (npr. qui, 14702215, MM šifra) → izberi → Naziv/DDV se posodobita.",
        )
        btn_party = ttk.Button(box, text="Odpri stranko", command=self._open_party_dialog)
        btn_party.grid(row=0, column=2, sticky="w", padx=(8, 0))
        ToolTip(
            btn_party,
            "Odpri obrazec Stranke za to dobavitelja.\n"
            "Uredi SI / EU / tretja država / ni zavezanec, DDV, Minimax …",
        )
        ttk.Label(box, text="Naziv").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(box, textvariable=self._var("supplier_name")).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(6, 0)
        )
        ttk.Label(box, text="ID za DDV").grid(row=2, column=0, sticky="w", pady=(6, 0))
        vat_entry = ttk.Entry(box, textvariable=self._var("vat_id"), width=20)
        vat_entry.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        self._si_vat_warn = tk.StringVar(value="")
        warn_lab = ttk.Label(
            box, textvariable=self._si_vat_warn, foreground="#e07070", wraplength=420
        )
        warn_lab.grid(row=3, column=0, columnspan=2, sticky="w", padx=(0, 0), pady=(2, 0))
        self._var("vat_id").trace_add("write", lambda *_a: self._refresh_si_vat_warning())
        self._var("supplier_name").trace_add("write", lambda *_a: self._refresh_si_vat_warning())
        kind_wrap = ttk.Frame(box)
        kind_wrap.grid(row=2, column=2, rowspan=2, sticky="nw", padx=(10, 0), pady=(6, 0))
        kind_row = ttk.Frame(kind_wrap)
        kind_row.pack(anchor="w")
        ttk.Label(kind_row, text="Opredelitev:").pack(side="left", padx=(0, 6))
        for text, val in (
            ("Domači", "SI"),
            ("EU", "EU"),
            ("Tretje države", "THIRD"),
            ("Nezavezanec", "NONE"),
        ):
            ttk.Radiobutton(
                kind_row,
                text=text,
                variable=self.supplier_kind_var,
                value=val,
                command=self._on_supplier_kind_change,
            ).pack(side="left", padx=(0, 8))
        kind_row2 = ttk.Frame(kind_wrap)
        kind_row2.pack(anchor="w", pady=(4, 0))
        for text, val in (
            ("Uvoz", "UVOZ"),
            ("MRN", "MRN"),
        ):
            ttk.Radiobutton(
                kind_row2,
                text=text,
                variable=self.supplier_kind_var,
                value=val,
                command=self._on_supplier_kind_change,
            ).pack(side="left", padx=(0, 10))
        btn_mrn = ttk.Button(kind_row2, text="MRN eDavki", command=self._open_edavki_mrn)
        btn_mrn.pack(side="left", padx=(4, 0))
        ToolTip(
            kind_wrap,
            "Opredelitev → Minimax + knjigi IR/PR → DDV-O:\n"
            "• Domači → plačilo 2200, DDV 16000/26000 → odbitni 41\n"
            "• EU blago (P10) → 2211, 16040/26040 → obračun 23, odbitek 41\n"
            "• EU storitve (P11) → 2211, 16044/26044 → obračun 23a, odbitek 41\n"
            "• Tretje države / izven EU (OpenAI, Fiverr, CN) → 2210,\n"
            "    16042/26042 → obračun 25 (NI 23!), odbitek 41\n"
            "• Tretje države blago (brez MRN) → 2210, 16030/26046 → obračun 25\n"
            "• Uvoz (plačan carini, brez SA) → 2210, 16030 — samo odbitni 41, ni 26\n"
            "• MRN = blago + samoobdavčitev uvoza (ni plačila DDV carini):\n"
            "    16030/26046 → obračun 26 + odbitek 41 (npr. Foshan, SAAMIA)\n"
            "Polje 41 = nabave + EU + uvoz + tujci (ne samo EU).",
        )
        ToolTip(
            btn_mrn,
            "Odpre eDavki, vpiše datume te listine in klikne Išči.",
        )
        box.columnconfigure(1, weight=1)

    def _acct_combo(self, parent: tk.Misc, key: str, width: int = 36) -> FilteredCombobox:
        code = account_code_from_choice(self._var(key).get()) if key in self._vars else ""
        # Kratek začetni seznam — polni plan pride prek filter_provider / warm
        seed = ensure_choice(self._account_choices[:50], code)

        def _provider(needle: str) -> list[str]:
            return filter_account_choices(self._account_choices, needle)

        combo = FilteredCombobox(
            parent,
            textvariable=self._var(key),
            values=seed,
            width=width,
            filter_provider=_provider,
        )
        ToolTip(
            combo,
            "Samo knjižljivi konti iz Minimax (AllowedPosting ≠ N).\n"
            "Lokalne šifre, ki jih v Minimax ni (npr. 4179), niso dovoljene.\n"
            "Tipkaj / izberi iz seznama — Enter ali zapusti polje potrdi.",
        )
        self._acct_combos.append(combo)
        return combo

    def _apply_account_choices(self, choices: list[str]) -> None:
        if not choices:
            return
        self._account_choices = choices
        for combo in self._acct_combos:
            try:
                code = account_code_from_choice(str(combo.get() or ""))
                # Celoten plan v univerzum/provider; set_values ne pokvari tipkanja
                combo.set_values(ensure_choice(choices, code))
            except tk.TclError:
                pass

    def _warm_accounts_from_minimax(self) -> None:
        """Kontni plan Minimax — SQL / ozadje; ob manjkajočem AllowedPosting → API."""
        if not self._org_id:
            return

        def work() -> None:
            try:
                choices = warm_account_cache_minimax(self.db, self._org_id)
            except Exception:
                choices = []

            def apply() -> None:
                try:
                    if not self.winfo_exists():
                        return
                except tk.TclError:
                    return
                self._apply_account_choices(choices)

            try:
                self.after(0, apply)
            except tk.TclError:
                pass

        # Hitri SQL v UI niti, če so že knjižljivi konti z meta
        try:
            if (
                account_cache_has_minimax(self._org_id, self.db)
                and not self.db.minimax_accounts_need_refresh(self._org_id)
            ):
                self._apply_account_choices(
                    load_account_choices(self.db, self._org_id, fetch_minimax=False)
                )
                return
        except Exception:
            pass
        threading.Thread(target=work, daemon=True, name="mm-accounts-pr").start()

    def _amount_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        amount_key: str,
        account_key: str | None = None,
        *,
        tip: str = "",
    ) -> None:
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self._var(amount_key), width=12).grid(
            row=row, column=1, sticky="w", padx=(6, 8), pady=3
        )
        if account_key:
            self._acct_combo(parent, account_key).grid(row=row, column=2, sticky="ew", pady=3)
        if tip:
            ToolTip(lbl, tip)

    def _build_amounts(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(0, 10))
        left = ttk.LabelFrame(grid, text="Osnova / nabave", padding=10)
        mid = ttk.LabelFrame(grid, text="DDV / odhodek", padding=10)
        right = ttk.LabelFrame(grid, text="Plačilo", padding=10)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        mid.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right.pack(side="left", fill="both", expand=True)

        self._amount_row(left, 0, "08 — osnova brez DDV", "net_taxable", "odhodek01")
        self._os_kpr_var = tk.StringVar(value=OS_KPR_TAXED_LABELS[1])
        self._os_kpr_ex_var = tk.StringVar(value=OS_KPR_EXEMPT_LABELS[1])
        self._var("os_amount")
        self._var("os_amount_ex")
        self._var("os_contra")
        self._amount_row(left, 1, "14 — oproščene nabave", "exempt_on", "odhodek07")
        # 9a deli konto z 14 — en combobox (dva na istem StringVar sta pokvarila vnos → 0000)
        self._amount_row(left, 2, "9a — 76.a člen", "f76a")
        ttk.Label(left, text="(konto = 14)", style="Muted.TLabel").grid(
            row=2, column=2, sticky="w", pady=3
        )
        self._amount_row(left, 3, "10 — pridobitve BL EU", "eu_goods", "odhodek10")
        self._amount_row(left, 4, "11 — prejete ST EU", "eu_services", "odhodek11")
        self._var("eu_goods").trace_add("write", lambda *_a: self._refresh_si_vat_warning())
        self._var("eu_services").trace_add("write", lambda *_a: self._refresh_si_vat_warning())
        self._amount_row(
            left, 5, "Ne gre v knjigo (ni v DDV)", "excluded", "odhodek_excluded",
            tip=(
                "Znesek NI v DDV sistemu (KIR/KPR/DDV-O).\n"
                "Knjiži se samo temeljnica: odhodek + plačilo (brez 160xx/260xx).\n"
                "Npr. BKS kreditodajalec → 9729/2200; druga → 4190/2200."
            ),
        )
        left.columnconfigure(2, weight=1)

        self._amount_row(mid, 0, "18 — DDV 22%", "vat_22")
        self._amount_row(mid, 1, "19 — DDV 9,5%", "vat_95")
        self._amount_row(mid, 2, "20 — DDV 5%", "vat_5")
        self._amount_row(mid, 3, "17 — neodbitni", "nondeduct_22")
        mid.columnconfigure(2, weight=1)

        ttk.Label(right, text="Plačilo (bruto)").grid(row=0, column=0, sticky="w")
        self._pay_total = tk.StringVar(value="0,00")
        pay_entry = ttk.Entry(right, textvariable=self._pay_total, width=12)
        pay_entry.grid(row=0, column=1, sticky="w", padx=(6, 8))
        ttk.Label(right, text="Konto plačila").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._acct_combo(right, "placilo").grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        right.columnconfigure(2, weight=1)
        ToolTip(
            pay_entry,
            "Seštevek (krog): kvadrati 08+DDV naj se ujemajo s tem zneskom.\n"
            "Lahko popraviš (npr. 2200). Če ne štima, opozorilo + razlika.",
        )
        ToolTip(
            right,
            "Konto plačila — kredit v predogledu:\n"
            "2200 domači / nezavezanec · 2211 EU · 2210 tujec (tretja).\n"
            "Znesek lahko popraviš; če kvadrati ≠ krog, temeljnica ne štima.",
        )
        self._pay_total.trace_add("write", lambda *_a: self._on_pay_total_changed())

        for key in (
            "net_taxable", "vat_22", "vat_95", "vat_5", "f76a", "eu_goods",
            "eu_services", "exempt_on", "excluded", "nondeduct_22",
            "odhodek01", "odhodek07", "odhodek10", "odhodek11", "odhodek_excluded", "placilo",
            "os_amount", "os_amount_ex",
        ):
            self._var(key).trace_add("write", lambda *_a: self._on_amounts_changed())

    def _build_journals(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Analitika — predogled knjižb (konto / debet / kredit)", padding=10)
        box.pack(fill="x", expand=False, pady=(4, 0))
        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Osveži knjižbe", command=self._refresh_journals).pack(side="left")
        btn_add = ttk.Button(bar, text="Dodaj vrstico", command=self._add_extra_line)
        btn_add.pack(side="left", padx=8)
        btn_edit = ttk.Button(bar, text="Uredi vrstico", command=self._edit_selected_extra)
        btn_edit.pack(side="left")
        btn_del = ttk.Button(bar, text="Odstrani vrstico", command=self._remove_selected_extra)
        btn_del.pack(side="left", padx=8)
        self._btn_os = ttk.Button(bar, text="Prenos v OS", command=self._open_minimax_os)
        self._btn_os.pack(side="left")
        ToolTip(
            btn_add,
            "Dodatna vrstica: konto, debet, kredit.\n"
            "V obrazcu 08 ostane 200 na 0470.\n"
            "V vrstici knjižbe 0470 popraviš na 1.000 →\n"
            "ponudi minus 800, konto (1300) in 2 polji DDV-O (12/13 in 14/15).",
        )
        ToolTip(btn_edit, "Uredi 08/0470 ali dodatno vrstico (dvojni klik).")
        ToolTip(btn_del, "Odstrani izbrano dodatno vrstico.")
        ToolTip(
            self._btn_os,
            "Seznam → +Nov → vpiše samo: datum knjižbe, dobavitelj,\n"
            "PR# + št. listine, nabavna vrednost 0470.\n"
            "Amortizacijsko skupino vneseš sam. Ne shrani sam.",
        )
        self._journal_status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._journal_status, style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        self._balance_warn = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._balance_warn, foreground="#e07070").pack(
            side="left", padx=(10, 0)
        )

        self._os_banner_text = tk.StringVar(value="")
        self._os_banner = tk.Frame(box, bg="#243656", highlightbackground="#ffcc66", highlightthickness=1)
        banner_inner = tk.Frame(self._os_banner, bg="#243656")
        banner_inner.pack(fill="x", padx=10, pady=8)
        tk.Label(
            banner_inner,
            textvariable=self._os_banner_text,
            bg="#243656",
            fg="#ffcc66",
            justify="left",
            anchor="w",
            wraplength=980,
            font=("Segoe UI", 9),
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            banner_inner,
            text="Skrij",
            command=self._hide_os_transfer_banner,
            bg="#20345d",
            fg="#f3f6ff",
            relief="flat",
            padx=10,
            pady=2,
            cursor="hand2",
        ).pack(side="right", padx=(10, 0), anchor="n")

        cols = ("konto", "debet", "kredit", "opis")
        self.journal_tree = ttk.Treeview(box, columns=cols, show="headings", height=12)
        for col, title, w in (
            ("konto", "Konto", 90),
            ("debet", "Debet", 100),
            ("kredit", "Kredit", 100),
            ("opis", "Opis", 420),
        ):
            self.journal_tree.heading(col, text=title)
            self.journal_tree.column(col, width=w, anchor="e" if col in {"debet", "kredit"} else "w")
        self.journal_tree.tag_configure("extra", foreground="#7ec8e3")
        self.journal_tree.tag_configure("os", foreground="#f0c14b")
        self.journal_tree.pack(fill="x", expand=False)
        self.journal_tree.bind("<Double-1>", lambda _e: self._edit_selected_extra())

    def _fit_window(self, *, preferred_w: int, preferred_h: int) -> None:
        """Višje okno, da je analitika spodaj vidna brez stiskanja."""
        self.update_idletasks()
        sw = max(self.winfo_screenwidth(), 1024)
        sh = max(self.winfo_screenheight(), 768)
        w = min(preferred_w, sw - 32)
        h = min(preferred_h, sh - 64)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.after(30, lambda: self._scroll_canvas.yview_moveto(0.0))

    def _fill_from_row(self, row: Mapping[str, Any]) -> None:
        was_loading = self._loading
        self._loading = True
        self._suppress_vat_trace = True
        try:
            mapping = {
                "internal_no": str(row.get("internal_no") or ""),
                "status": normalize_status(row.get("status")),
                "received_date": _date_var(row.get("received_date")),
                "document_date": _date_var(row.get("document_date")),
                "booking_date": _date_var(row.get("booking_date")),
                "document_no": str(row.get("document_no") or ""),
                "seq": str(row.get("seq") or "0"),
                "notes": str(row.get("notes") or ""),
                "supplier_name": str(row.get("supplier_name") or ""),
                "vat_id": str(row.get("vat_id") or ""),
                "net_taxable": _money_var(row.get("net_taxable")),
                "exempt_on": _money_var(row.get("exempt_on")),
                "f76a": _money_var(row.get("f76a")),
                "eu_goods": _money_var(row.get("eu_goods")),
                "eu_services": _money_var(row.get("eu_services")),
                "excluded": _money_var(row.get("excluded")),
                "vat_22": _money_var(row.get("vat_22")),
                "vat_95": _money_var(row.get("vat_95")),
                "vat_5": _money_var(row.get("vat_5")),
                "nondeduct_22": _money_var(row.get("nondeduct_22")),
            }
            accounts = allocate_pr_accounts(row)
            mapping.update(
                {
                    "odhodek01": accounts["odhodek01"],
                    "odhodek07": accounts["odhodek07"],
                    "odhodek10": accounts["odhodek10"],
                    "odhodek11": accounts["odhodek11"],
                    "odhodek_excluded": accounts["odhodek_excluded"],
                    "placilo": accounts["placilo"],
                }
            )
            os_field, os_amt, os_contra = resolve_os_book(row)
            if not os_field:
                os_field = default_os_kpr_field(accounts["odhodek01"])
            mapping["os_amount"] = "0,00"
            mapping["os_amount_ex"] = "0,00"
            mapping["os_contra"] = os_contra or DEFAULT_OS_CONTRA
            taxed = exempt = None
            for field, amount in resolve_os_allocations(row):
                if field in {"12", "13"} and taxed is None:
                    taxed = (field, amount)
                elif field in {"14", "15"} and exempt is None:
                    exempt = (field, amount)
                elif taxed is None:
                    taxed = (field, amount)
            if taxed:
                mapping["os_amount"] = _money_var(taxed[1])
                os_field = taxed[0]
            elif is_nonzero(os_amt):
                mapping["os_amount"] = _money_var(os_amt)
            if exempt:
                mapping["os_amount_ex"] = _money_var(exempt[1])
            if hasattr(self, "_os_kpr_var"):
                self._os_kpr_var.set(os_kpr_label(os_field) or OS_KPR_TAXED_LABELS[1])
            if hasattr(self, "_os_kpr_ex_var"):
                self._os_kpr_ex_var.set(
                    os_kpr_label(exempt[0]) if exempt else OS_KPR_EXEMPT_LABELS[1]
                )
            for key, value in mapping.items():
                self._var(key).set(value)
            # party: DDV / naziv listine; napačen party_id (prazen DDV) zavrnemo
            name = mapping["supplier_name"]
            vat = mapping["vat_id"]
            label = f"{name} [{vat}]" if name and vat else name
            party = resolve_party_for_journal_row(
                self.db,
                party_id=row.get("party_id"),
                vat_id=vat,
                name=name,
            )
            if party:
                labels = party_choices([party])
                label = labels[0] if labels else label
                self._party_id = party.get("id")
                if vat:
                    self._var("supplier_name").set(_strip_name_markers(str(party.get("name") or name)))
                    party_vat = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
                    if party_vat:
                        self._var("vat_id").set(party_vat)
            else:
                self._party_id = None
            if label:
                self._party_labels = [label]
                try:
                    self.party_combo.set_values(self._party_labels)
                except tk.TclError:
                    pass
            self._var("party_label").set(label)
            self._sync_supplier_kind(party=party, row=row, apply_accounts=False)
            self._apply_vat_flags_from_row(row)
            self._extra_lines = extra_journal_lines(row)
            self._pay_manual = False
            self._update_pay_total()
            raw_pay = {}
            try:
                prev = json.loads(row.get("raw_json") or "{}")
                if isinstance(prev, dict):
                    raw_pay = prev
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_pay = {}
            override = row.get("placilo_amount")
            if override is None:
                override = raw_pay.get("placilo_amount")
            if override not in (None, ""):
                self._pay_manual = True
                self._suppress_pay_trace = True
                try:
                    self._pay_total.set(money_text(override))
                finally:
                    self._suppress_pay_trace = False
            self._refresh_si_vat_warning()
        finally:
            self._suppress_vat_trace = False
            self._loading = was_loading

    def _sync_supplier_kind(
        self,
        *,
        party: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
        apply_accounts: bool = True,
    ) -> None:
        """Nastavi radio SI/EU/Tretje države/Nezavezanec iz stranke ali vrstice."""
        src = dict(row or {})
        if "vat_id" not in src and "vat_id" in self._vars:
            src["vat_id"] = self._var("vat_id").get()
        if "supplier_name" not in src and "supplier_name" in self._vars:
            src["supplier_name"] = self._var("supplier_name").get()
        # ohrani shranjeno opredelitev (raw_json / supplier_kind)
        stored = row_supplier_kind(src)
        if stored:
            src["supplier_kind"] = stored
        kind = infer_supplier_kind(src, party)
        self._kind_updating = True
        try:
            self.supplier_kind_var.set(kind)
        finally:
            self._kind_updating = False
        if apply_accounts:
            self._apply_supplier_kind_accounts(kind)
            return
        # Ob nalaganju: generične 220x uskladi z opredelitvijo (2850 ipd. ostane)
        if "placilo" in self._vars:
            cur = account_code_from_choice(self._var("placilo").get())
            if cur in ("", "2200", "2210", "2211"):
                self._var("placilo").set(payable_account(kind))

    def _open_edavki_mrn(self) -> None:
        date_from = (
            self._var("received_date").get()
            or self._var("document_date").get()
            or self._var("booking_date").get()
        )
        date_to = (
            self._var("booking_date").get()
            or self._var("document_date").get()
            or date_from
        )
        open_edavki_mrn_dates(
            date_from=date_from,
            date_to=date_to,
            tax_number=PROJEST_TAX_ID,
            company_name=PROJEST_NAME,
        )

    def _apply_supplier_kind_accounts(self, kind: str) -> None:
        """Posodobi plačilo 2200/2211/2210 in predlagaj SA/VD po tipu stranke."""
        placilo = payable_account(kind)
        if "placilo" in self._vars:
            self._var("placilo").set(placilo)

        self._suppress_vat_trace = True
        try:
            if kind == "UVOZ":
                # Uvozni DDV: odbija se, NI samoobdavčitev (ni polje 26)
                self.self_assessment_var.set(False)
                self.vat_deductible_var.set(True)
            elif kind == "MRN":
                # MRN: samoobdavčitev uvoza → DDV-O 26 + odbitni 16030
                self.self_assessment_var.set(True)
                self.vat_deductible_var.set(True)
            elif kind in ("EU", "THIRD"):
                # B2B / reverse charge — privzeto samoobdavčitev + odbitni DDV
                self.self_assessment_var.set(True)
                self.vat_deductible_var.set(True)
                if kind == "THIRD":
                    # Tretje: nabava → 08 (AOP 31), DDV → 25; ne P10/P11/9a
                    extra = decimal_value(0)
                    for key in ("eu_services", "eu_goods", "f76a"):
                        if key in self._vars:
                            extra += decimal_value(self._var(key).get())
                            self._var(key).set(money_text(0))
                    if is_nonzero(extra) and "net_taxable" in self._vars:
                        self._var("net_taxable").set(
                            money_text(decimal_value(self._var("net_taxable").get()) + extra)
                        )
                    od_from = ""
                    for src in ("odhodek11", "odhodek10", "odhodek07"):
                        if src in self._vars:
                            code = account_code_from_choice(self._var(src).get())
                            if code and not od_from:
                                od_from = code
                            self._var(src).set("")
                    if od_from and "odhodek01" in self._vars and not account_code_from_choice(self._var("odhodek01").get()):
                        self._var("odhodek01").set(od_from)
            elif kind == "NONE":
                self.self_assessment_var.set(False)
        finally:
            self._suppress_vat_trace = False

        sa = bool(self.self_assessment_var.get())
        vd = bool(self.vat_deductible_var.get())
        tip = kind_label(pr_vat_kind({**self._payload_preview(), "supplier_kind": kind}))
        self._vat_offer_var.set(
            f"{supplier_kind_label(kind)} → plačilo {placilo}, DDV ({tip}); "
            f"{flags_offer_text(sa, vd, 'opredelitev stranke')}"
        )
        self._update_pay_total()
        if hasattr(self, "journal_tree"):
            self._refresh_journals()

    def _on_supplier_kind_change(self) -> None:
        if self._kind_updating or self._loading:
            return
        self._apply_supplier_kind_accounts(self.supplier_kind_var.get() or "SI")
        self._refresh_si_vat_warning()

    def _refresh_si_vat_warning(self) -> None:
        if not hasattr(self, "_si_vat_warn"):
            return
        vat = normalize_vat_id(self._var("vat_id").get()) if "vat_id" in self._vars else ""
        kind = self.supplier_kind_var.get() or "SI"
        sa = bool(self.self_assessment_var.get()) if hasattr(self, "self_assessment_var") else False
        preview = {
            "vat_id": vat,
            "supplier_name": (
                normalize_text(self._var("supplier_name").get())
                if "supplier_name" in self._vars
                else ""
            ),
            "eu_goods": self._var("eu_goods").get() if "eu_goods" in self._vars else 0,
            "eu_services": self._var("eu_services").get() if "eu_services" in self._vars else 0,
            "supplier_kind": kind,
        }
        if is_si_ds_vat(vat) and (
            kind in {"EU", "THIRD", "UVOZ", "MRN"} or pr_si_vat_on_non_domestic(preview)
        ):
            self._si_vat_warn.set(
                "Kontrola: ni Domači — ID za DDV ne sme biti SI + slovenska DŠ. "
                "Vpiši tuji ID (BG…, NL…) ali nastavi Domači."
            )
        elif is_third_country_digital_supplier(preview):
            if sa:
                self._si_vat_warn.set(
                    "Opomba: digitalni dobavitelj iz tretje države (npr. OpenAI/Fiverr) "
                    "je samoobdavčitev po AOP 25 (ne EU 23/23a)."
                )
            else:
                self._si_vat_warn.set(
                    "Opomba: digitalni dobavitelj iz tretje države (npr. OpenAI/Fiverr) "
                    "običajno potrebuje samoobdavčitev (AOP 25, ne EU 23/23a)."
                )
        else:
            self._si_vat_warn.set("")

    def _supplier_rule(self) -> dict[str, Any] | None:
        vat = normalize_vat_id(self._var("vat_id").get()) if "vat_id" in self._vars else ""
        name = normalize_text(self._var("supplier_name").get()) if "supplier_name" in self._vars else ""
        return self.db.find_account_rule(vat_id=vat, name=name, party_kind="supplier")

    def _apply_vat_flags_from_row(self, row: Mapping[str, Any]) -> None:
        rule = self.db.find_account_rule(
            vat_id=str(row.get("vat_id") or ""),
            name=str(row.get("supplier_name") or ""),
            party_kind="supplier",
        )
        sa, vd, offer = resolve_pr_vat_flags(row, rule=rule)
        self._suppress_vat_trace = True
        try:
            self.self_assessment_var.set(sa)
            self.vat_deductible_var.set(vd)
        finally:
            self._suppress_vat_trace = False
        self._vat_offer_var.set(flags_offer_text(sa, vd, offer))

    def _clear_accounts_for_zero_amounts(self) -> None:
        """Znesek = 0 → počisti konto; <> 0 (tudi storno) ohrani konto."""
        pairs = (
            ("net_taxable", "odhodek01"),
            ("exempt_on", "odhodek07"),
            ("f76a", "odhodek07"),
            ("eu_goods", "odhodek10"),
            ("eu_services", "odhodek11"),
            ("excluded", "odhodek_excluded"),
        )
        # 14 in 9a delita odhodek07 — počisti samo, če sta oba 0
        exempt = decimal_value(self._var("exempt_on").get()) if "exempt_on" in self._vars else 0
        f76a = decimal_value(self._var("f76a").get()) if "f76a" in self._vars else 0
        for amt_key, acct_key in pairs:
            if amt_key not in self._vars or acct_key not in self._vars:
                continue
            if acct_key == "odhodek07":
                if is_nonzero(exempt) or is_nonzero(f76a):
                    continue
            elif is_nonzero(self._var(amt_key).get()):
                continue
            if self._var(acct_key).get().strip():
                self._var(acct_key).set("")

    def _on_amounts_changed(self) -> None:
        if self._loading or self._suppress_vat_trace:
            return
        self._clear_accounts_for_zero_amounts()
        # Če uporabnik še ni ročno shranil zastavic, ponudi P9–P11
        if source_self_assessment_pr(self._payload_preview()):
            if self._row.get("self_assessment") is None and self._row.get("vat_deductible") is None:
                rule = self._supplier_rule()
                if not (rule and rule.get("self_assessment") is not None):
                    self._suppress_vat_trace = True
                    try:
                        self.self_assessment_var.set(True)
                        self.vat_deductible_var.set(True)
                    finally:
                        self._suppress_vat_trace = False
                    self._vat_offer_var.set(
                        flags_offer_text(True, bool(self.vat_deductible_var.get()), "KPR P9–P11")
                    )
        self._update_pay_total()
        if hasattr(self, "journal_tree"):
            self._refresh_journals()

    def _on_vat_flags_change(self) -> None:
        if self._suppress_vat_trace or self._loading:
            return
        sa = bool(self.self_assessment_var.get())
        vd = bool(self.vat_deductible_var.get())
        self._vat_offer_var.set(flags_offer_text(sa, vd, "ročno"))
        self._update_pay_total()
        if hasattr(self, "journal_tree"):
            self._refresh_journals()

    def _apply_party_from_label(self, label: str) -> None:
        name, vat = parse_party_choice(label)
        if name:
            self._var("supplier_name").set(name)
        if vat:
            self._var("vat_id").set(vat)
        party = self.db.find_party_by_tax(vat) if vat else None
        if party is None and name:
            for row in self.db.search_parties(name, limit=20):
                if normalize_text(row.get("name")).casefold() == name.casefold():
                    if not vat or normalize_vat_id(row.get("vat_id")) == normalize_vat_id(vat):
                        party = row
                        break
        self._party_id = party.get("id") if party else None
        if party:
            # uskladi Naziv/DDV z SQL vrstico
            self._var("supplier_name").set(normalize_text(party.get("name")))
            self._var("vat_id").set(normalize_vat_id(party.get("vat_id") or party.get("tax_number")))
        self._sync_supplier_kind(party=party, apply_accounts=True)

    def _on_party_selected(self, _event: object | None = None) -> None:
        self._apply_party_from_label(self._var("party_label").get())
        return "break" if _event and getattr(_event, "keysym", "") == "Return" else None

    def _open_party_dialog(self) -> None:
        """Odpri obrazec Stranke (SI/EU/tretja/ni zavezanec) za trenutnega dobavitelja."""
        vat = normalize_vat_id(self._var("vat_id").get()) if "vat_id" in self._vars else ""
        name = normalize_text(self._var("supplier_name").get()) if "supplier_name" in self._vars else ""
        party: dict[str, Any] | None = None
        if self._party_id:
            party = self.db.get_party(int(self._party_id))
        if party is None and vat:
            party = self.db.find_party_by_tax(vat)
        if party is None:
            if vat.startswith("SI"):
                foreign, country = False, "SI"
            elif vat:
                foreign = True
                country = vat[:2] if len(vat) >= 2 and vat[:2].isalpha() else ""
            else:
                # brez DDV na PR — pogosto tujec; v obrazcu lahko preklopiš na Ni zavezanec
                foreign, country = True, ""
            party = {
                "name": name,
                "vat_id": vat,
                "tax_number": vat[2:] if vat.startswith("SI") and len(vat) > 2 else "",
                "country": country,
                "is_foreign": 1 if foreign else 0,
                "source": "pr_editor",
            }
        dialog = StrankeDialog(
            self,
            self.db,
            party=party,
            org_id=self._org_id,
            on_saved=self._reload_party_from_db,
            name_aliases=[name] if name else None,
        )
        self.wait_window(dialog)
        if getattr(dialog, "party_id", None):
            self._party_id = dialog.party_id
        self._reload_party_from_db()

    def _reload_party_from_db(self) -> None:
        party = None
        if self._party_id:
            party = self.db.get_party(int(self._party_id))
        vat = normalize_vat_id(self._var("vat_id").get()) if "vat_id" in self._vars else ""
        name = normalize_text(self._var("supplier_name").get()) if "supplier_name" in self._vars else ""
        if party is None and vat:
            party = self.db.find_party_by_tax(vat)
        if party is None and name:
            for row in self.db.search_parties(name, limit=20):
                if normalize_text(row.get("name")).casefold() == name.casefold():
                    party = row
                    break
        if not party:
            return
        labels = party_choices([party])
        label = labels[0] if labels else normalize_text(party.get("name"))
        self._party_id = party.get("id")
        self._party_labels = [label]
        try:
            self.party_combo.set_values(self._party_labels)
        except tk.TclError:
            pass
        self._var("party_label").set(label)
        self._var("supplier_name").set(normalize_text(party.get("name")))
        self._var("vat_id").set(normalize_vat_id(party.get("vat_id") or party.get("tax_number")))
        self._sync_supplier_kind(party=party, apply_accounts=True)

    def _squares_total(self):
        """Seštevek kvadratov (08 + ostale osnove + DDV, razen pri SA)."""
        net = (
            decimal_value(self._var("net_taxable").get())
            + decimal_value(self._var("f76a").get())
            + decimal_value(self._var("eu_goods").get())
            + decimal_value(self._var("eu_services").get())
            + decimal_value(self._var("exempt_on").get())
            + decimal_value(self._var("excluded").get())
            + decimal_value(self._var("nondeduct_22").get())
        )
        vat = (
            decimal_value(self._var("vat_22").get())
            + decimal_value(self._var("vat_95").get())
            + decimal_value(self._var("vat_5").get())
        )
        return net if self.self_assessment_var.get() else (net + vat)

    def _update_pay_total(self) -> None:
        if self._pay_manual:
            return
        try:
            self._suppress_pay_trace = True
            self._pay_total.set(money_text(self._squares_total()))
        except Exception:
            self._pay_total.set("0,00")
        finally:
            self._suppress_pay_trace = False

    def _on_pay_total_changed(self) -> None:
        if self._loading or self._suppress_pay_trace:
            return
        self._pay_manual = True
        if hasattr(self, "journal_tree"):
            self._refresh_journals()

    def _acct_committed(self, key: str, *, fallback: str = "", default: str = "") -> str:
        """Konto iz polja — samo popolna šifra (ne '4' med tipkanjem)."""
        raw = self._var(key).get() if key in self._vars else ""
        code = resolve_committed_account(raw, fallback=fallback or str(self._row.get(key) or ""))
        return code or default

    def _payload_preview(self) -> dict[str, Any]:
        kind = self.supplier_kind_var.get() or "SI"
        return {
            "document_no": self._var("document_no").get(),
            "internal_no": self._var("internal_no").get(),
            "notes": self._var("notes").get(),
            "net_taxable": self._var("net_taxable").get(),
            "f76a": self._var("f76a").get(),
            "eu_goods": self._var("eu_goods").get(),
            "eu_services": self._var("eu_services").get(),
            "exempt_on": self._var("exempt_on").get(),
            "vat_22": self._var("vat_22").get(),
            "vat_95": self._var("vat_95").get(),
            "vat_5": self._var("vat_5").get(),
            "excluded": self._var("excluded").get(),
            "nondeduct_22": self._var("nondeduct_22").get() if "nondeduct_22" in self._vars else "0",
            "odhodek01": self._acct_committed("odhodek01"),
            "odhodek07": self._acct_committed("odhodek07"),
            "odhodek10": self._acct_committed("odhodek10"),
            "odhodek11": self._acct_committed("odhodek11"),
            "odhodek_excluded": self._acct_committed("odhodek_excluded"),
            "placilo": self._acct_committed("placilo", default=payable_account(kind)),
            "supplier_kind": kind,
            "self_assessment": bool(self.self_assessment_var.get()),
            "vat_deductible": bool(self.vat_deductible_var.get()),
            "os_kpr": os_kpr_code(self._os_kpr_var.get()) if hasattr(self, "_os_kpr_var") else "",
            "os_amount": self._os_amount_total(),
            "os_contra": self._acct_committed("os_contra", default=DEFAULT_OS_CONTRA),
            "os_allocations": self._os_allocations_from_vars(),
            "extra_journal_lines": serialize_extra_journal_lines(self._extra_lines),
            "placilo_amount": (
                decimal_value(self._pay_total.get()) if self._pay_manual else None
            ),
        }

    def _os_amount_total(self):
        taxed = decimal_value(self._var("os_amount").get()) if "os_amount" in self._vars else 0
        exempt = decimal_value(self._var("os_amount_ex").get()) if "os_amount_ex" in self._vars else 0
        return taxed + exempt

    def _os_allocations_from_vars(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        field = os_kpr_code(self._os_kpr_var.get()) if hasattr(self, "_os_kpr_var") else ""
        amount = decimal_value(self._var("os_amount").get()) if "os_amount" in self._vars else 0
        if field and is_nonzero(amount):
            out.append({"kpr": field, "amount": str(amount)})
        field_ex = os_kpr_code(self._os_kpr_ex_var.get()) if hasattr(self, "_os_kpr_ex_var") else ""
        amount_ex = decimal_value(self._var("os_amount_ex").get()) if "os_amount_ex" in self._vars else 0
        if field_ex and is_nonzero(amount_ex):
            out.append({"kpr": field_ex, "amount": str(amount_ex)})
        return out

    def _refresh_journals(self) -> None:
        self.journal_tree.delete(*self.journal_tree.get_children())
        extra_i = 0
        expense = self._acct_committed("odhodek01")
        for i, line in enumerate(preview_pr_journals(self._payload_preview())):
            extra = bool(line.get("extra"))
            konto = str(line.get("konto") or "")
            opis = str(line.get("opis") or "")
            if extra:
                iid = f"extra:{extra_i}"
                extra_i += 1
            elif konto == expense and opis.startswith("08 >"):
                iid = "auto:osnova08"
            elif line.get("payment") or "plačilo" in opis:
                iid = "auto:placilo"
            else:
                iid = f"auto:{i}"
            tags: list[str] = []
            if extra:
                tags.append("extra")
            if is_fixed_asset_account(konto):
                tags.append("os")
            if line.get("kpr_diff") and line.get("kredit"):
                debet_txt = f"-{money_text(line['kredit'])}"
                kredit_txt = ""
            else:
                debet_txt = money_text(line["debet"]) if line["debet"] else ""
                kredit_txt = money_text(line["kredit"]) if line["kredit"] else ""
            self.journal_tree.insert(
                "",
                "end",
                iid=iid,
                values=(line["konto"], debet_txt, kredit_txt, opis),
                tags=tuple(tags),
            )
        self._refresh_journal_status()
        self._refresh_balance_warning()
        self._refresh_os_button()

    def _default_extra_opis(self) -> str:
        desc = normalize_text(
            (self._var("document_no").get() if "document_no" in self._vars else "")
            or (self._var("internal_no").get() if "internal_no" in self._vars else "")
            or (self._var("notes").get() if "notes" in self._vars else "")
        )
        return f"{desc} — dodatna knjižba" if desc else "dodatna knjižba"

    def _os_accounts_in_play(self) -> list[str]:
        codes: list[str] = []
        for key in ("odhodek01", "odhodek07", "odhodek10", "odhodek11"):
            code = self._acct_committed(key) if key in self._vars else ""
            if is_fixed_asset_account(code) and code not in codes:
                codes.append(code)
        for line in self._extra_lines:
            code = account_code_from_choice(str(line.get("konto") or ""))
            if is_fixed_asset_account(code) and code not in codes:
                codes.append(code)
        return codes

    def _refresh_os_button(self) -> None:
        if not hasattr(self, "_btn_os"):
            return
        codes = self._os_accounts_in_play()
        label = f"Prenos v OS ({', '.join(codes)})" if codes else "Prenos v OS"
        try:
            self._btn_os.configure(text=label)
        except tk.TclError:
            pass
        if hasattr(self, "_os_banner") and self._os_banner.winfo_ismapped():
            self._os_banner_text.set(self._os_transfer_summary())

    def _refresh_journal_status(self) -> None:
        if not hasattr(self, "_journal_status"):
            return
        kpr = decimal_value(self._var("net_taxable").get()) if "net_taxable" in self._vars else 0
        os_field = os_kpr_code(self._os_kpr_var.get()) if hasattr(self, "_os_kpr_var") else ""
        os_amt = decimal_value(self._var("os_amount").get()) if "os_amount" in self._vars else 0
        preview = extra_lines_net(self._payload_preview())
        if is_nonzero(os_amt):
            preview = sum(
                (
                    decimal_value(line.get("debet")) - decimal_value(line.get("kredit"))
                    for line in preview_pr_journals(self._payload_preview())
                    if line.get("extra")
                ),
                decimal_value(0),
            )
        bits: list[str] = []
        if is_nonzero(os_amt) and os_field:
            bits.append(f"KPR {os_field}={money_text(os_amt)} → AOP {os_aop_hint(os_field) or '35'}")
        if is_nonzero(os_amt) or self._extra_lines:
            if preview == kpr:
                bits.append(f"knjižba {money_text(preview)} = KPR 08 {money_text(kpr)}")
            else:
                bits.append(f"knjižba {money_text(preview)} ≠ KPR 08 {money_text(kpr)}")
        self._journal_status.set(" · ".join(bits))

    def _refresh_balance_warning(self) -> None:
        if not hasattr(self, "_balance_warn"):
            return
        squares = self._squares_total()
        circle = decimal_value(self._pay_total.get())
        gap = squares - circle
        lines = preview_pr_journals(self._payload_preview())
        imb = journal_imbalance(lines)
        parts: list[str] = []
        if is_nonzero(gap):
            parts.append(
                f"Kvadrati {money_text(squares)} ≠ krog {money_text(circle)} · razlika {money_text(gap)}"
            )
        if is_nonzero(imb):
            parts.append(f"Temeljnica ne štima · razlika {money_text(imb)}")
        self._balance_warn.set(" · ".join(parts))

    def _edit_payment_line(self, values: Sequence[Any] | None = None) -> None:
        """Popravi seštevek 2200 (krog). Če ≠ kvadrati, opozorilo + razlika."""
        current = decimal_value(self._pay_total.get())
        if values and len(values) >= 3:
            debit = decimal_value(str(values[1]).lstrip("-") if values[1] else 0)
            credit = decimal_value(values[2] or 0)
            if str(values[1]).startswith("-"):
                current = -debit
            elif is_nonzero(credit):
                current = credit
            elif is_nonzero(debit):
                current = -debit
        win = tk.Toplevel(self)
        win.title("Plačilo 2200")
        win.transient(self)
        win.grab_set()
        win.configure(bg="#101a2f")
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=(
                f"Kvadrati (08+DDV) = {money_text(self._squares_total())}.\n"
                "Popravi znesek konta plačila (2200). Če se ne ujema s krogom, "
                "temeljnica ne štima — pokažemo razliko."
            ),
            wraplength=460,
        ).pack(anchor="w")
        ttk.Label(body, text="Plačilo (kredit / minus = debet)").pack(anchor="w", pady=(10, 0))
        amt_var = tk.StringVar(value=money_text(current))
        ttk.Entry(body, textvariable=amt_var, width=14).pack(anchor="w", pady=(4, 0))

        def _ok() -> None:
            self._pay_manual = True
            self._suppress_pay_trace = True
            try:
                self._pay_total.set(money_text(decimal_value(amt_var.get())))
            finally:
                self._suppress_pay_trace = False
            win.destroy()
            self._refresh_journals()

        def _auto() -> None:
            self._pay_manual = False
            win.destroy()
            self._update_pay_total()
            self._refresh_journals()

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Prekliči", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Shrani znesek", style="Success.TButton", command=_ok).pack(
            side="right", padx=(0, 8)
        )
        ttk.Button(btns, text="Iz kvadratov", command=_auto).pack(side="left")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: _ok())

    def _kpr_osnova(self):
        return decimal_value(self._var("net_taxable").get()) if "net_taxable" in self._vars else 0

    def _osnova_08_konto(self) -> str:
        return self._acct_committed("odhodek01")

    def _osnova_08_seed(self) -> dict[str, Any]:
        expense = self._osnova_08_konto()
        kpr = self._kpr_osnova()
        shown = kpr + self._os_amount_total()
        return {
            "konto": expense,
            "debet": shown if is_nonzero(shown) else kpr,
            "kredit": 0,
            "opis": self._default_extra_opis(),
        }

    def _last_kpr_diff_konto(self) -> str:
        for line in reversed(self._extra_lines):
            if line.get("kpr_diff"):
                return str(line.get("konto") or "")
        return "1300"

    def _selected_extra_index(self) -> int | None:
        sel = self.journal_tree.selection()
        if not sel:
            return None
        iid = str(sel[0])
        if not iid.startswith("extra:"):
            return None
        try:
            index = int(iid.split(":", 1)[1])
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(self._extra_lines):
            return index
        return None

    def _add_extra_line(self) -> None:
        self._edit_extra_line(None)

    def _edit_selected_extra(self) -> None:
        index = self._selected_extra_index()
        if index is not None:
            line = self._extra_lines[index]
            split = (
                str(line.get("konto") or "") == self._osnova_08_konto()
                and not line.get("kpr_diff")
            )
            self._edit_extra_line(index, split_osnova=split)
            return
        sel = self.journal_tree.selection()
        if sel:
            iid = str(sel[0])
            values = self.journal_tree.item(sel[0], "values")
            konto = str(values[0] or "") if values else ""
            if iid == "auto:osnova08" or konto == self._osnova_08_konto():
                self._edit_extra_line(None, seed=self._osnova_08_seed(), split_osnova=True)
                return
            if iid == "auto:placilo" or konto == self._acct_committed("placilo"):
                self._edit_payment_line(values)
                return
            messagebox.showinfo(
                "Knjižba",
                "Avtomatski DDV spremeniš v KPR zneskih.\n"
                "08 (0470) in plačilo 2200 lahko urediš v vrstici.",
                parent=self,
            )
            return
        self._add_extra_line()

    def _remove_selected_extra(self) -> None:
        index = self._selected_extra_index()
        if index is None:
            messagebox.showinfo(
                "Odstrani vrstico",
                "Izberi dodatno vrstico (modro) in jo odstrani.",
                parent=self,
            )
            return
        removed = self._extra_lines.pop(index)
        if removed.get("kpr_diff") or str(removed.get("konto") or "") == self._osnova_08_konto():
            self._extra_lines = [
                line
                for line in self._extra_lines
                if not line.get("kpr_diff")
                and str(line.get("konto") or "") != self._osnova_08_konto()
            ]
        self._refresh_journals()

    def _ask_kpr_diff_account(self, diff, *, main_konto: str, preset: str = "") -> dict[str, Any] | None:
        """Ponudi minus 800, konto in 2 polji DDV-O (12/13 ter 14/15)."""
        result: dict[str, Any] = {}
        win = tk.Toplevel(self)
        win.title("Dodaj knjižbo v minus")
        win.transient(self)
        win.grab_set()
        win.configure(bg="#101a2f")
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)
        kpr = self._kpr_osnova()
        minus = abs(diff)
        ttk.Label(
            body,
            text=(
                f"Obrazec 08 = {money_text(kpr)} na {main_konto}.\n"
                f"V vrstici {main_konto} = {money_text(kpr + diff)}.\n"
                f"Dodaj knjižbo v minus: {money_text(minus)}."
            ),
            wraplength=500,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Konto (minus)").grid(row=1, column=0, sticky="w", pady=(12, 0))
        konto_var = tk.StringVar(value=preset or self._last_kpr_diff_konto() or DEFAULT_OS_CONTRA)

        def _provider(needle: str) -> list[str]:
            return filter_account_choices(self._account_choices, needle)

        combo = FilteredCombobox(
            body,
            textvariable=konto_var,
            values=ensure_choice(self._account_choices[:50], konto_var.get()),
            width=42,
            filter_provider=_provider,
        )
        combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        ttk.Label(body, text="Znesek v minus").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(body, text=money_text(minus)).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        default_taxed = os_kpr_code(self._os_kpr_var.get()) if hasattr(self, "_os_kpr_var") else ""
        if default_taxed not in {"12", "13"}:
            default_taxed = default_os_kpr_field(main_konto)
        taxed_var = tk.StringVar(value=os_kpr_label(default_taxed) or OS_KPR_TAXED_LABELS[1])
        taxed_amt = tk.StringVar(value=money_text(minus))
        ttk.Label(body, text="DDV-O 12 ali 13").grid(row=3, column=0, sticky="w", pady=(12, 0))
        taxed_row = ttk.Frame(body)
        taxed_row.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        ttk.Combobox(
            taxed_row,
            textvariable=taxed_var,
            values=list(OS_KPR_TAXED_LABELS),
            width=28,
            state="readonly",
        ).pack(side="left")
        ttk.Entry(taxed_row, textvariable=taxed_amt, width=10).pack(side="left", padx=(6, 0))

        default_ex = os_kpr_code(self._os_kpr_ex_var.get()) if hasattr(self, "_os_kpr_ex_var") else "15"
        if default_ex not in {"14", "15"}:
            default_ex = "15"
        exempt_var = tk.StringVar(value=os_kpr_label(default_ex) or OS_KPR_EXEMPT_LABELS[1])
        exempt_amt = tk.StringVar(value=_money_var(self._var("os_amount_ex").get()) if "os_amount_ex" in self._vars else "0,00")
        ttk.Label(body, text="DDV-O 14 ali 15").grid(row=4, column=0, sticky="w", pady=(8, 0))
        exempt_row = ttk.Frame(body)
        exempt_row.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Combobox(
            exempt_row,
            textvariable=exempt_var,
            values=list(OS_KPR_EXEMPT_LABELS),
            width=28,
            state="readonly",
        ).pack(side="left")
        ttk.Entry(exempt_row, textvariable=exempt_amt, width=10).pack(side="left", padx=(6, 0))
        ttk.Label(
            body,
            text="12 → AOP 31+34 · 13 → AOP 31+35 · 14 → AOP 33 · 15 → AOP 34",
            style="Muted.TLabel",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        body.columnconfigure(1, weight=1)

        def _ok() -> None:
            try:
                combo.event_generate("<FocusOut>")
            except tk.TclError:
                pass
            code = account_code_from_choice(konto_var.get())
            field = os_kpr_code(taxed_var.get())
            field_ex = os_kpr_code(exempt_var.get())
            amt = decimal_value(taxed_amt.get())
            amt_ex = decimal_value(exempt_amt.get())
            if not code:
                messagebox.showerror("Konto", "Izberi konto za minus (npr. 1300).", parent=win)
                return
            if code == main_konto:
                messagebox.showerror("Konto", f"Minusa ne knjiži na isti konto {main_konto}.", parent=win)
                return
            if not is_nonzero(amt) and not is_nonzero(amt_ex):
                messagebox.showerror("DDV-O", "Vpiši znesek v 12/13 ali 14/15.", parent=win)
                return
            if is_nonzero(amt) and not field:
                messagebox.showerror("DDV-O", "Izberi 12 ali 13.", parent=win)
                return
            if is_nonzero(amt_ex) and not field_ex:
                messagebox.showerror("DDV-O", "Izberi 14 ali 15.", parent=win)
                return
            if self._org_id and not is_known_account_code(self.db, self._org_id, code):
                messagebox.showerror("Konto", f"Konto {code} ni v Minimax šifrantu.", parent=win)
                return
            result["konto"] = code
            result["os_kpr"] = field
            result["os_amount"] = amt
            result["os_kpr_ex"] = field_ex
            result["os_amount_ex"] = amt_ex
            win.destroy()

        btns = ttk.Frame(body)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Prekliči", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Dodaj knjižbo v minus", style="Success.TButton", command=_ok).pack(
            side="right", padx=(0, 8)
        )
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: _ok())
        combo.focus_set()
        self.wait_window(win)
        return result or None

    def _apply_osnova_split(self, line: dict[str, Any]) -> bool:
        """V vrstici 0470: 200 → 1000, potem minus 800 + konto + 2 polji DDV-O."""
        kpr = self._kpr_osnova()
        signed = decimal_value(line.get("debet")) - decimal_value(line.get("kredit"))
        diff = signed - kpr
        expense = str(line.get("konto") or "")
        if not is_nonzero(diff):
            self._var("os_amount").set("0,00")
            self._var("os_amount_ex").set("0,00")
            self._extra_lines = [
                item
                for item in self._extra_lines
                if str(item.get("konto") or "") != expense and not item.get("kpr_diff")
            ]
            return True
        picked = self._ask_kpr_diff_account(diff, main_konto=expense)
        if not picked:
            return False
        self._var("os_amount").set(money_text(picked.get("os_amount") or 0))
        self._var("os_amount_ex").set(money_text(picked.get("os_amount_ex") or 0))
        self._var("os_contra").set(picked["konto"])
        if hasattr(self, "_os_kpr_var") and picked.get("os_kpr"):
            self._os_kpr_var.set(os_kpr_label(str(picked["os_kpr"])))
        if hasattr(self, "_os_kpr_ex_var") and picked.get("os_kpr_ex"):
            self._os_kpr_ex_var.set(os_kpr_label(str(picked["os_kpr_ex"])))
        self._extra_lines = [
            item
            for item in self._extra_lines
            if str(item.get("konto") or "") != expense
            and str(item.get("konto") or "") != picked["konto"]
            and not item.get("kpr_diff")
        ]
        return True

    def _edit_extra_line(
        self,
        index: int | None,
        *,
        seed: Mapping[str, Any] | None = None,
        split_osnova: bool = False,
    ) -> None:
        existing = dict(self._extra_lines[index]) if index is not None else dict(seed or {})
        win = tk.Toplevel(self)
        win.title("Uredi vrstico" if index is not None or seed else "Dodaj vrstico")
        win.transient(self)
        win.grab_set()
        win.configure(bg="#101a2f")
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Konto").grid(row=0, column=0, sticky="w")
        konto_var = tk.StringVar(value=str(existing.get("konto") or self._osnova_08_konto() or ""))
        has_debit = existing.get("debet") not in (None, "", 0)
        has_credit = existing.get("kredit") not in (None, "", 0)
        debit_var = tk.StringVar(value=_money_var(existing.get("debet")) if has_debit else "")
        credit_var = tk.StringVar(value=_money_var(existing.get("kredit")) if has_credit else "")
        if seed and not has_debit and not has_credit:
            debit_var.set(_money_var(self._kpr_osnova()))
        opis_var = tk.StringVar(value=str(existing.get("opis") or self._default_extra_opis()))
        hint_var = tk.StringVar(value="")

        def _provider(needle: str) -> list[str]:
            return filter_account_choices(self._account_choices, needle)

        combo = FilteredCombobox(
            body,
            textvariable=konto_var,
            values=ensure_choice(self._account_choices[:50], konto_var.get()),
            width=42,
            filter_provider=_provider,
        )
        combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(body, text="Debet").grid(row=1, column=0, sticky="w")
        ttk.Entry(body, textvariable=debit_var, width=14).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=3
        )
        ttk.Label(body, text="Kredit").grid(row=2, column=0, sticky="w")
        ttk.Entry(body, textvariable=credit_var, width=14).grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=3
        )
        ttk.Label(body, text="Opis").grid(row=3, column=0, sticky="w")
        ttk.Entry(body, textvariable=opis_var, width=42).grid(
            row=3, column=1, sticky="ew", padx=(8, 0), pady=3
        )
        ttk.Label(body, textvariable=hint_var, style="Muted.TLabel", wraplength=420).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        body.columnconfigure(1, weight=1)

        def _update_hint(*_a: object) -> None:
            kpr = self._kpr_osnova()
            signed = decimal_value(debit_var.get()) - decimal_value(credit_var.get())
            code = account_code_from_choice(konto_var.get())
            expense = self._osnova_08_konto()
            if code and code == expense and is_nonzero(signed - kpr):
                hint_var.set(
                    f"KPR 08 = {money_text(kpr)} · {code} = {money_text(signed)} · "
                    f"razlika {money_text(abs(signed - kpr))} — po shrani izberi konto."
                )
            else:
                hint_var.set("Če 08 = 200 in 0470 = 1.000, razliko 800 poknjiži npr. na 1300.")

        konto_var.trace_add("write", _update_hint)
        debit_var.trace_add("write", _update_hint)
        credit_var.trace_add("write", _update_hint)
        _update_hint()

        def _ok() -> None:
            try:
                combo.event_generate("<FocusOut>")
            except tk.TclError:
                pass
            line = normalize_extra_journal_line(
                {
                    "konto": account_code_from_choice(konto_var.get()),
                    "debet": debit_var.get(),
                    "kredit": credit_var.get(),
                    "opis": normalize_text(opis_var.get()) or self._default_extra_opis(),
                }
            )
            if not line:
                messagebox.showerror(
                    "Neveljaven vnos",
                    "Vpiši konto in debet ali kredit (lahko negativno).",
                    parent=win,
                )
                return
            if self._org_id and not is_known_account_code(self.db, self._org_id, line["konto"]):
                messagebox.showerror(
                    "Neveljaven konto",
                    f"Konto {line['konto']} ni v Minimax šifrantu.",
                    parent=win,
                )
                return
            expense = self._osnova_08_konto()
            do_split = split_osnova or (
                line["konto"] == expense and not existing.get("kpr_diff")
            )
            win.destroy()
            if do_split:
                if not self._apply_osnova_split(line):
                    return
            elif index is None:
                self._extra_lines.append(line)
            else:
                self._extra_lines[index] = line
            self._refresh_journals()

        btns = ttk.Frame(body)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Prekliči", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Shrani vrstico", style="Success.TButton", command=_ok).pack(
            side="right", padx=(0, 8)
        )
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: _ok())
        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 120}")
        if split_osnova:
            # Fokus na znesek — konto 0470 je že iz 08
            try:
                body.grid_slaves(row=1, column=1)[0].focus_set()
            except (IndexError, tk.TclError):
                combo.focus_set()
        else:
            combo.focus_set()

    def _os_nabava_amount(self):
        """Znesek konta OS (0470 = 1000), ne samo KPR 08."""
        kpr08 = decimal_value(self._var("net_taxable").get()) if "net_taxable" in self._vars else 0
        os_amt = self._os_amount_total()
        return kpr08 + os_amt if is_nonzero(os_amt) else kpr08

    def _os_listina_text(self) -> str:
        doc = normalize_text(
            self._var("document_no").get() if "document_no" in self._vars else ""
        )
        if self._row_id:
            return f"PR#{self._row_id}, {doc}" if doc else f"PR#{self._row_id}"
        return f"PR, {doc}" if doc else "PR"

    def _os_webui_payload(self) -> dict[str, str]:
        raw_date = (
            (self._var("booking_date").get() if "booking_date" in self._vars else "")
            or (self._var("document_date").get() if "document_date" in self._vars else "")
            or (self._var("received_date").get() if "received_date" in self._vars else "")
        )
        try:
            booking = date_text(raw_date) or normalize_text(raw_date)
        except ProjestError:
            booking = normalize_text(raw_date)
        supplier = normalize_text(
            _strip_name_markers(
                self._var("supplier_name").get() if "supplier_name" in self._vars else ""
            )
        )
        if " (" in supplier:
            supplier = supplier.split(" (", 1)[0].strip() or supplier
        return {
            "datum": booking,
            "dobavitelj": supplier,
            "naziv": supplier,
            "listina": self._os_listina_text(),
            "nabava": money_text(self._os_nabava_amount()),
            "konto": first_fixed_asset_account(*self._os_accounts_in_play()),
            "org_id": self._org_id or "179535",
            "org_name": "PROJEST d.o.o.",
        }

    def _open_minimax_os(self, konto: str = "", silent: bool = False) -> None:
        code = first_fixed_asset_account(
            konto,
            *self._os_accounts_in_play(),
        )
        if not code and not silent:
            messagebox.showinfo(
                "Prenos v OS",
                "Ni konta osnovnega sredstva (0470, 0210, 01–04).\n"
                "Dodaj vrstico ali izberi konto OS, nato znova Prenos v OS.",
                parent=self,
            )
            return
        payload = self._os_webui_payload()
        self._show_os_transfer_banner()

        def work() -> None:
            result = open_and_fill_osnovno_sredstvo(payload)
            try:
                self.after(0, lambda: self._on_os_fill_done(result, silent=silent))
            except tk.TclError:
                pass

        threading.Thread(target=work, daemon=True, name="mm-os-fill").start()

    def _on_os_fill_done(self, result: Mapping[str, Any], *, silent: bool = False) -> None:
        if not self.winfo_exists():
            return
        msg = str(result.get("message") or "")
        self._os_banner_text.set(self._os_transfer_summary() + (f"\n{msg}" if msg else ""))
        self._show_os_transfer_banner()
        if silent or result.get("ok"):
            return
        messagebox.showerror("Minimax", msg or "Osnovnih sredstev ni bilo mogoče odpreti.", parent=self)

    def _os_transfer_summary(self) -> str:
        payload = self._os_webui_payload()
        return "\n".join(
            (
                "Prenos v OS — PROJEST. Amortizacija: 20 % (Oprema, vozila, mehanizacija).",
                f"Datum pridobitve / Datum: {payload.get('datum') or '—'}",
                f"Dobavitelj: {payload.get('dobavitelj') or '—'}",
                f"Listina: {payload.get('listina') or '—'}",
                f"Nabavna vrednost: {payload.get('nabava') or '—'}",
            )
        )

    def _show_os_transfer_banner(self) -> None:
        if not hasattr(self, "_os_banner"):
            return
        self._os_banner_text.set(self._os_transfer_summary())
        if not self._os_banner.winfo_ismapped():
            self._os_banner.pack(fill="x", pady=(0, 8), before=self.journal_tree)

    def _hide_os_transfer_banner(self) -> None:
        if hasattr(self, "_os_banner"):
            self._os_banner.pack_forget()

    def load_row(self, row: Mapping[str, Any]) -> None:
        """Naloži drugo PR vrstico v isto okno (hitra navigacija ‹ ›)."""
        self._row = dict(row)
        self._row_id = int(row["id"]) if row.get("id") else None
        self.title(f"Uredi PR #{self._row_id}" if self._row_id else "Nov PR")
        self._hide_os_transfer_banner()
        self._fill_from_row(self._row)
        self._refresh_journals()

    def _nav(self, delta: int) -> None:
        if not self._get_neighbor_row or not self._neighbors or self._row_id is None:
            return
        try:
            index = self._neighbors.index(int(self._row_id))
        except ValueError:
            return
        nxt = index + int(delta)
        if not (0 <= nxt < len(self._neighbors)):
            return
        row = self._get_neighbor_row(self._neighbors[nxt])
        if row:
            self.load_row(row)

    def _flush_account_combos(self) -> None:
        """Potrdi tipkanje v comboboxih (enoznačen zadetek) pred shrani/predogledom."""
        for combo in self._acct_combos:
            try:
                combo.event_generate("<FocusOut>")
            except tk.TclError:
                pass

    def _save(self, confirm: bool = False) -> None:
        try:
            self._flush_account_combos()
            payload: dict[str, Any] = {
                "id": self._row_id,
                "internal_no": normalize_text(self._var("internal_no").get()),
                "status": (
                    STATUS_SHRANJENO
                    if confirm
                    else (normalize_status(self._var("status").get()) or DEFAULT_ROW_STATUS)
                ),
                "received_date": normalize_text(self._var("received_date").get()),
                "document_date": normalize_text(self._var("document_date").get()),
                "booking_date": normalize_text(self._var("booking_date").get()),
                "document_no": normalize_text(self._var("document_no").get()),
                "seq": int(decimal_value(self._var("seq").get() or "0")),
                "notes": normalize_text(self._var("notes").get()),
                "supplier_name": normalize_text(self._var("supplier_name").get()),
                "vat_id": normalize_vat_id(self._var("vat_id").get()),
                "tax_number": normalize_text(self._var("vat_id").get()),
                "net_taxable": decimal_value(self._var("net_taxable").get()),
                "exempt_on": decimal_value(self._var("exempt_on").get()),
                "f76a": decimal_value(self._var("f76a").get()),
                "eu_goods": decimal_value(self._var("eu_goods").get()),
                "eu_services": decimal_value(self._var("eu_services").get()),
                "excluded": decimal_value(self._var("excluded").get()),
                "vat_22": decimal_value(self._var("vat_22").get()),
                "vat_95": decimal_value(self._var("vat_95").get()),
                "vat_5": decimal_value(self._var("vat_5").get()),
                "nondeduct_22": decimal_value(self._var("nondeduct_22").get()),
                "odhodek01": self._acct_committed("odhodek01"),
                "odhodek07": self._acct_committed("odhodek07"),
                "odhodek10": self._acct_committed("odhodek10"),
                "odhodek11": self._acct_committed("odhodek11"),
                "odhodek_excluded": self._acct_committed("odhodek_excluded"),
                "os_kpr": os_kpr_code(self._os_kpr_var.get()) if hasattr(self, "_os_kpr_var") else "",
                "os_amount": self._os_amount_total(),
                "os_contra": self._acct_committed("os_contra", default=DEFAULT_OS_CONTRA),
                "os_allocations": self._os_allocations_from_vars(),
                "placilo": self._acct_committed(
                    "placilo",
                    default=payable_account(self.supplier_kind_var.get() or "SI"),
                ),
                "self_assessment": bool(self.self_assessment_var.get()),
                "vat_deductible": bool(self.vat_deductible_var.get()),
                "party_id": self._party_id,
                "remember": bool(self.remember_var.get()),
                "confirm_for_minimax": bool(confirm),
            }
            kind = self.supplier_kind_var.get() or "SI"
            if kind == "EU" and infer_supplier_kind(payload) == "THIRD":
                kind = "THIRD"
                self.supplier_kind_var.set("THIRD")
            if kind == "THIRD":
                extra = (
                    decimal_value(payload.get("eu_services"))
                    + decimal_value(payload.get("eu_goods"))
                    + decimal_value(payload.get("f76a"))
                )
                if is_nonzero(extra):
                    payload["net_taxable"] = decimal_value(payload.get("net_taxable")) + extra
                    payload["eu_services"] = decimal_value("0")
                    payload["eu_goods"] = decimal_value("0")
                    payload["f76a"] = decimal_value("0")
                    od_from = payload.get("odhodek11") or payload.get("odhodek10") or payload.get("odhodek07")
                    if od_from and not payload.get("odhodek01"):
                        payload["odhodek01"] = od_from
                    payload["odhodek11"] = ""
                    payload["odhodek10"] = ""
            # Vsak odhodek = svoj konto; samo šifre iz Minimax knjižljivega plana
            def _require_mm(code: str, where: str) -> str:
                code = account_code_from_choice(code)
                if not code:
                    raise ProjestError(f"{where}: manjka konto.")
                if self._org_id and not is_known_account_code(self.db, self._org_id, code):
                    raise ProjestError(
                        f"{where}: konto {code} ni v Minimax šifrantu "
                        f"(AllowedPosting knjižljiv). Izberi drugega."
                    )
                return code

            if is_nonzero(payload["net_taxable"]):
                payload["odhodek01"] = _require_mm(payload["odhodek01"], "Osnova 08")
            else:
                payload["odhodek01"] = ""
            if is_nonzero(payload["exempt_on"]) or is_nonzero(payload["f76a"]):
                code07 = payload["odhodek07"] or payload["odhodek01"]
                payload["odhodek07"] = _require_mm(code07, "14 / 9a")
            else:
                payload["odhodek07"] = ""
            if is_nonzero(payload["eu_goods"]):
                payload["odhodek10"] = _require_mm(
                    payload["odhodek10"] or payload["odhodek07"] or payload["odhodek01"],
                    "10 — BL EU",
                )
            else:
                payload["odhodek10"] = ""
            if is_nonzero(payload["eu_services"]):
                payload["odhodek11"] = _require_mm(
                    payload["odhodek11"] or payload["odhodek07"] or payload["odhodek01"],
                    "11 — ST EU",
                )
            else:
                payload["odhodek11"] = ""
            if is_nonzero(payload["excluded"]):
                payload["odhodek_excluded"] = _require_mm(
                    payload["odhodek_excluded"], "Ne gre v knjigo (ni v DDV)"
                )
            else:
                payload["odhodek_excluded"] = ""
            if payload["placilo"] and self._org_id:
                if not is_known_account_code(self.db, self._org_id, payload["placilo"]):
                    raise ProjestError(
                        f"Konto plačila {payload['placilo']} ni v Minimax šifrantu."
                    )
            if confirm:
                payload["sync_status"] = SYNC_READY
            # Ohrani Vasco raw_json + zapiši opredelitev (Uvoz/MRN/…)
            raw: dict[str, Any] = {}
            try:
                prev = json.loads(self._row.get("raw_json") or "{}")
                if isinstance(prev, dict):
                    raw = dict(prev)
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = {}
            raw["supplier_kind"] = kind
            raw["os_kpr"] = payload["os_kpr"]
            raw["os_amount"] = str(payload["os_amount"])
            raw["os_contra"] = payload["os_contra"]
            raw["os_allocations"] = payload["os_allocations"]
            if self._pay_manual:
                raw["placilo_amount"] = str(decimal_value(self._pay_total.get()))
            else:
                raw.pop("placilo_amount", None)
            payload["placilo_amount"] = raw.get("placilo_amount")
            raw["extra_journal_lines"] = serialize_extra_journal_lines(self._extra_lines)
            payload["supplier_kind"] = raw["supplier_kind"]
            payload["extra_journal_lines"] = raw["extra_journal_lines"]
            payload["raw_json"] = raw
            if is_si_ds_vat(payload["vat_id"]) and (
                payload["supplier_kind"] in {"EU", "THIRD", "UVOZ", "MRN"}
                or pr_si_vat_on_non_domestic(payload)
            ):
                raise ProjestError(
                    "EU / tujec ne sme imeti ID za DDV SI+DŠ.\n"
                    "Vpiši tuji ID za DDV (npr. BG…, NL…) ali spremeni opredelitev na Domači."
                )
            self._on_save(payload)
        except (ProjestError, ValueError) as exc:
            messagebox.showerror("Neveljaven vnos", str(exc), parent=self)
            return
        self.destroy()
