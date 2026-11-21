"""Access-podoben urejevalnik IR: statusi, kupec, konto prihodka, predogled knjižb."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

from trops_studio.account_choices import (
    account_cache_has_minimax,
    account_code_from_choice,
    ensure_choice,
    filter_account_choices,
    load_account_choices,
    parse_party_choice,
    party_choices,
    warm_account_cache_minimax,
)
from trops_studio.config import DEFAULT_IR_EU_REVENUE_ACCOUNT, DEFAULT_IR_REVENUE_ACCOUNT
from trops_studio.db import Database
from trops_studio.ir_list_view import apply_ir_eu_sale
from trops_studio.journal_preview import preview_ir_journals
from trops_studio.money import (
    ProjestError,
    date_text,
    decimal_value,
    ir_imported_name_locked,
    money_text,
    normalize_text,
    normalize_vat_id,
    tax_digits,
)
from trops_studio.row_status import DEFAULT_ROW_STATUS, ROW_STATUSES, STATUS_SHRANJENO, normalize_status
from trops_studio.sync_state import SYNC_READY
from trops_studio.parties_ensure import _strip_name_markers, resolve_party_for_journal_row
from trops_studio.ui.filtered_combo import FilteredCombobox
from trops_studio.ui.stranke_dialog import StrankeDialog
from trops_studio.ui.tooltip import ToolTip


def _money_var(value: Any) -> str:
    if value in (None, ""):
        return "0,00"
    return money_text(value)


def _date_var(value: Any) -> str:
    return date_text(value) if value else ""


class IrEditorDialog(tk.Toplevel):
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
        self._parties = list(parties) if parties is not None else []
        self._org_id = str(org_id or "").strip()
        self._account_choices = load_account_choices(db, self._org_id or None, fetch_minimax=False)
        self._acct_combos: list[FilteredCombobox] = []
        self._party_labels: list[str] = []
        self._vars: dict[str, tk.StringVar] = {}
        self._party_id: Any = row.get("party_id")
        self.remember_var = tk.BooleanVar(value=bool(remember_default))
        self._loading = True

        title = f"Uredi IR #{self._row_id}" if self._row_id else "Nov IR"
        self.title(title)
        self.transient(master)
        self.grab_set()
        self.configure(bg="#101a2f")
        self.minsize(920, 700)

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
        ttk.Checkbutton(
            buttons, text="Zapomni konto za kupca", variable=self.remember_var
        ).pack(side="left")
        ToolTip(
            btn_confirm,
            "Potrdi v SQL (Shranjeno + ready). Osnutki v Minimax šele prek »Sinhroniziraj Minimax« (API).",
        )

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
        self._fit_window(preferred_w=1100, preferred_h=920)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
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
        ttk.Button(nav, text="‹", width=3, command=lambda: self._nav(-1)).pack(side="left")
        ttk.Button(nav, text="›", width=3, command=lambda: self._nav(1)).pack(side="left", padx=(4, 10))
        ttk.Label(nav, text="Knjiga").pack(side="left")
        ttk.Entry(nav, textvariable=self._var("book"), width=14).pack(side="left", padx=(6, 14))
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
            "Sortiranje napak: Popravi / Popravljeno / Shranjeno / Manjka konto / Poglej.",
        )

        from trops_studio.ui.date_picker import make_date_entry

        dates = ttk.Frame(head)
        dates.pack(fill="x", pady=(8, 0))
        date_keys = {"document_date", "booking_date"}
        for i, (key, label) in enumerate(
            (
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
        dates.columnconfigure((0, 1, 2, 3), weight=1)

        ttk.Label(head, text="Opis (opombe)").pack(anchor="w", pady=(8, 0))
        ttk.Entry(head, textvariable=self._var("notes")).pack(fill="x")

    def _party_filter(self, needle: str) -> list[str]:
        return party_choices(self.db.search_parties(needle, limit=150))

    def _build_party(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Kupec / stranka", padding=10)
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
            "Zamenjaj kupca iz SQLite šifranta.\n"
            "Tipkaj *vnos* (naziv, DDV, MM šifra) → izberi → Naziv/DDV se posodobita.",
        )
        btn_party = ttk.Button(box, text="Odpri stranko", command=self._open_party_dialog)
        btn_party.grid(row=0, column=2, sticky="w", padx=(8, 0))
        ToolTip(
            btn_party,
            "Odpri obrazec Stranke za tega kupca.\n"
            "Uredi SI / EU / tretja država / ni zavezanec, DDV, Minimax …",
        )
        ttk.Label(box, text="Naziv").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(box, textvariable=self._var("party_name")).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(6, 0)
        )
        ttk.Label(box, text="ID za DDV").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(box, textvariable=self._var("vat_id"), width=20).grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0)
        )
        box.columnconfigure(1, weight=1)

    def _build_amounts(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Zneski / konto prihodka", padding=10)
        box.pack(fill="x", pady=(0, 10))
        rows = (
            ("Osnova", "net"),
            ("DDV 22%", "vat_22"),
            ("DDV 9,5%", "vat_95"),
            ("Oproščeno", "exempt"),
            ("Ne gre v knjigo", "excluded"),
            ("Skupaj", "total"),
        )
        for i, (label, key) in enumerate(rows):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(box, textvariable=self._var(key), width=14).grid(
                row=i, column=1, sticky="w", padx=(8, 16), pady=3
            )
        ttk.Label(box, text="Konto prihodka").grid(row=0, column=2, sticky="w")
        code = account_code_from_choice(str(self._row.get("account") or "")) or DEFAULT_IR_REVENUE_ACCOUNT
        seed = ensure_choice(self._account_choices[:50], code)

        def _provider(needle: str) -> list[str]:
            return filter_account_choices(self._account_choices, needle)

        acct = FilteredCombobox(
            box,
            textvariable=self._var("account"),
            values=seed,
            width=36,
            filter_provider=_provider,
        )
        acct.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        ToolTip(
            acct,
            "Kontni plan (Minimax API).\n"
            "Tipkaj šifro ali del naziva — filtrira sproti (npr. 762 → …).\n"
            f"EU kupec: {DEFAULT_IR_EU_REVENUE_ACCOUNT} (blago, AOP 12 / KIR P10, Minimax splošna osnova brez DDV).",
        )
        self._acct_combos.append(acct)
        box.columnconfigure(3, weight=1)
        for key in ("net", "vat_22", "vat_95", "exempt", "excluded"):
            self._var(key).trace_add("write", lambda *_a: self._update_total())

    def _build_journals(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Analitika — predogled knjižb (konto / debet / kredit)", padding=10)
        box.pack(fill="x", expand=False, pady=(4, 0))
        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Osveži knjižbe", command=self._refresh_journals).pack(side="left")
        ttk.Button(
            bar,
            text="Dodatna knjižba",
            command=lambda: messagebox.showinfo(
                "Dodatna knjižba",
                "Shranjevanje ločenih knjižb pride v naslednji fazi.\n"
                "Zdaj je predogled iz zneskov/kontov.",
                parent=self,
            ),
        ).pack(side="left", padx=8)
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
        self.journal_tree.pack(fill="x", expand=False)

    def _warm_accounts_from_minimax(self) -> None:
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
                if not choices:
                    return
                self._account_choices = choices
                for combo in self._acct_combos:
                    try:
                        code = account_code_from_choice(str(combo.get() or ""))
                        combo.set_values(ensure_choice(choices, code))
                    except tk.TclError:
                        pass

            try:
                self.after(0, apply)
            except tk.TclError:
                pass

        try:
            if (
                account_cache_has_minimax(self._org_id, self.db)
                and not self.db.minimax_accounts_need_refresh(self._org_id)
            ):
                choices = load_account_choices(self.db, self._org_id, fetch_minimax=False)
                self._account_choices = choices
                for combo in self._acct_combos:
                    try:
                        code = account_code_from_choice(str(combo.get() or ""))
                        combo.set_values(ensure_choice(choices, code))
                    except tk.TclError:
                        pass
                return
        except Exception:
            pass
        threading.Thread(target=work, daemon=True, name="mm-accounts-ir").start()

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
        mapping = {
            "book": str(row.get("book") or "Darila"),
            "status": normalize_status(row.get("status")),
            "document_date": _date_var(row.get("document_date")),
            "booking_date": _date_var(row.get("booking_date")),
            "document_no": str(row.get("document_no") or ""),
            "seq": str(row.get("seq") or "0"),
            "notes": str(row.get("notes") or ""),
            "party_name": str(row.get("party_name") or ""),
            "vat_id": str(row.get("vat_id") or ""),
            "net": _money_var(row.get("net")),
            "vat_22": _money_var(row.get("vat_22")),
            "vat_95": _money_var(row.get("vat_95")),
            "exempt": _money_var(row.get("exempt")),
            "excluded": _money_var(row.get("excluded")),
            "total": _money_var(row.get("total")),
            "account": str(row.get("account") or DEFAULT_IR_REVENUE_ACCOUNT),
        }
        for key, value in mapping.items():
            self._var(key).set(value)
        name, vat = mapping["party_name"], mapping["vat_id"]
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
            # Listina brez ID = FO: ne prepiši naziva/davčne s stranko (Krajnik ≠ OSOVNIKAR).
            if vat and not ir_imported_name_locked(vat):
                self._var("party_name").set(_strip_name_markers(str(party.get("name") or name)))
                party_vat = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
                if party_vat:
                    self._var("vat_id").set(party_vat)
        else:
            self._party_id = None
        if label and label not in self._party_labels:
            self._party_labels = [label, *self._party_labels]
            self.party_combo.set_values(self._party_labels)
        self._var("party_label").set(label)
        self._apply_eu_rules()
        self._update_total()

    def _current_party(self) -> dict[str, Any] | None:
        if self._party_id:
            party = self.db.get_party(int(self._party_id))
            if party:
                return party
        vat = normalize_vat_id(self._var("vat_id").get()) if "vat_id" in self._vars else ""
        return self.db.find_party_by_tax(vat) if vat else None

    def _apply_eu_rules(self) -> None:
        """EU kupec: 76301 + oproščeno → splošna osnova (blago, brez DDV)."""
        if "account" not in self._vars:
            return
        preview = {
            "party_name": self._var("party_name").get() if "party_name" in self._vars else "",
            "vat_id": self._var("vat_id").get() if "vat_id" in self._vars else "",
            "net": self._var("net").get() if "net" in self._vars else "0",
            "vat_22": self._var("vat_22").get() if "vat_22" in self._vars else "0",
            "vat_95": self._var("vat_95").get() if "vat_95" in self._vars else "0",
            "exempt": self._var("exempt").get() if "exempt" in self._vars else "0",
            "account": account_code_from_choice(self._var("account").get()),
            "eu_goods": self._row.get("eu_goods") if self._row else "0",
            "eu_services": self._row.get("eu_services") if self._row else "0",
        }
        classified = apply_ir_eu_sale(preview, self._current_party())
        self._var("account").set(str(classified.get("account") or DEFAULT_IR_REVENUE_ACCOUNT))
        if "net" in self._vars:
            shown = decimal_value(classified.get("net")) + decimal_value(classified.get("eu_goods"))
            self._var("net").set(money_text(shown))
        if "exempt" in self._vars:
            self._var("exempt").set(money_text(decimal_value(classified.get("exempt"))))

    def _apply_party_from_label(self, label: str) -> None:
        name, vat = parse_party_choice(label)
        locked = ir_imported_name_locked(
            self._var("vat_id").get() if "vat_id" in self._vars else ""
        )
        if name and not locked:
            self._var("party_name").set(name)
        if vat and not locked:
            self._var("vat_id").set(vat)
        party = self.db.find_party_by_tax(vat) if vat else None
        if party is None and name:
            for row in self.db.search_parties(name, limit=20):
                if normalize_text(row.get("name")).casefold() == name.casefold():
                    if not vat or normalize_vat_id(row.get("vat_id")) == normalize_vat_id(vat):
                        party = row
                        break
        if locked:
            party_tax = tax_digits((party or {}).get("vat_id") or (party or {}).get("tax_number"))
            if party and not party_tax:
                self._party_id = party.get("id")
            return
        self._party_id = party.get("id") if party else None
        if party:
            self._var("party_name").set(normalize_text(party.get("name")))
            self._var("vat_id").set(normalize_vat_id(party.get("vat_id") or party.get("tax_number")))

    def _on_party_selected(self, _event: object | None = None) -> None:
        self._apply_party_from_label(self._var("party_label").get())
        self._apply_eu_rules()
        return "break" if _event and getattr(_event, "keysym", "") == "Return" else None

    def _open_party_dialog(self) -> None:
        """Odpri obrazec Stranke (SI/EU/tretja/ni zavezanec) za trenutnega kupca."""
        vat = normalize_vat_id(self._var("vat_id").get()) if "vat_id" in self._vars else ""
        name = normalize_text(self._var("party_name").get()) if "party_name" in self._vars else ""
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
                foreign, country = True, ""
            party = {
                "name": name,
                "vat_id": vat,
                "tax_number": vat[2:] if vat.startswith("SI") and len(vat) > 2 else "",
                "country": country,
                "is_foreign": 1 if foreign else 0,
                "source": "ir_editor",
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
        name = normalize_text(self._var("party_name").get()) if "party_name" in self._vars else ""
        if party is None and vat:
            party = self.db.find_party_by_tax(vat)
        if party is None and name:
            for row in self.db.search_parties(name, limit=20):
                if normalize_text(row.get("name")).casefold() == name.casefold():
                    party = row
                    break
        if not party:
            return
        if ir_imported_name_locked(vat):
            if tax_digits(party.get("vat_id") or party.get("tax_number")):
                return
            self._party_id = party.get("id")
            return
        labels = party_choices([party])
        label = labels[0] if labels else normalize_text(party.get("name"))
        self._party_id = party.get("id")
        if label not in self._party_labels:
            self._party_labels = [label, *self._party_labels]
        try:
            self.party_combo.set_values(self._party_labels)
        except tk.TclError:
            pass
        self._var("party_label").set(label)
        self._var("party_name").set(normalize_text(party.get("name")))
        self._var("vat_id").set(normalize_vat_id(party.get("vat_id") or party.get("tax_number")))

    def _update_total(self) -> None:
        try:
            total = (
                decimal_value(self._var("net").get())
                + decimal_value(self._var("vat_22").get())
                + decimal_value(self._var("vat_95").get())
                + decimal_value(self._var("exempt").get())
                + decimal_value(self._var("excluded").get())
            )
            self._var("total").set(money_text(total))
        except Exception:
            pass

    def _refresh_journals(self) -> None:
        self.journal_tree.delete(*self.journal_tree.get_children())
        preview_row = {
            "document_no": self._var("document_no").get(),
            "notes": self._var("notes").get(),
            "net": self._var("net").get(),
            "vat_22": self._var("vat_22").get(),
            "vat_95": self._var("vat_95").get(),
            "exempt": self._var("exempt").get(),
            "excluded": self._var("excluded").get(),
            "total": self._var("total").get(),
            "account": account_code_from_choice(self._var("account").get()),
        }
        for line in preview_ir_journals(preview_row):
            self.journal_tree.insert(
                "",
                "end",
                values=(
                    line["konto"],
                    money_text(line["debet"]) if line["debet"] else "",
                    money_text(line["kredit"]) if line["kredit"] else "",
                    line["opis"],
                ),
            )

    def load_row(self, row: Mapping[str, Any]) -> None:
        """Naloži drugo IR vrstico v isto okno (hitra navigacija ‹ ›)."""
        self._row = dict(row)
        self._row_id = int(row["id"]) if row.get("id") else None
        self.title(f"Uredi IR #{self._row_id}" if self._row_id else "Nov IR")
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

    def _save(self, confirm: bool = False) -> None:
        try:
            payload: dict[str, Any] = {
                "id": self._row_id,
                "book": normalize_text(self._var("book").get()) or "Darila",
                "status": (
                    STATUS_SHRANJENO
                    if confirm
                    else (normalize_status(self._var("status").get()) or DEFAULT_ROW_STATUS)
                ),
                "document_date": normalize_text(self._var("document_date").get()),
                "booking_date": normalize_text(self._var("booking_date").get()),
                "document_no": normalize_text(self._var("document_no").get()),
                "seq": int(decimal_value(self._var("seq").get() or "0")),
                "notes": normalize_text(self._var("notes").get()),
                "party_name": normalize_text(self._var("party_name").get()),
                "vat_id": normalize_vat_id(self._var("vat_id").get()),
                "net": decimal_value(self._var("net").get()),
                "vat_22": decimal_value(self._var("vat_22").get()),
                "vat_95": decimal_value(self._var("vat_95").get()),
                "exempt": decimal_value(self._var("exempt").get()),
                "excluded": decimal_value(self._var("excluded").get()),
                "total": decimal_value(self._var("total").get()),
                "account": account_code_from_choice(self._var("account").get())
                or DEFAULT_IR_REVENUE_ACCOUNT,
                "party_id": self._party_id,
                "remember": bool(self.remember_var.get()),
                "confirm_for_minimax": bool(confirm),
            }
            payload.update(apply_ir_eu_sale(payload, self._current_party()))
            if confirm:
                payload["sync_status"] = SYNC_READY
            self._on_save(payload)
        except (ProjestError, ValueError) as exc:
            messagebox.showerror("Neveljaven vnos", str(exc), parent=self)
            return
        self.destroy()
