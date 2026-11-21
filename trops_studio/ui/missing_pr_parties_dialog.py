"""Manjkajoče IR/PR stranke pred sync v Minimax: SI→poveži, EU/tretja→AI+SQL→API."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence

from trops_studio.db import Database
from trops_studio.minimax_parties import import_parties_to_minimax
from trops_studio.money import sanitize_display_text
from trops_studio.parties_ensure import (
    ACTION_KONCNI,
    ACTION_SI_AJPES,
    ACTION_TUJEC,
    absorb_all_minimax_duplicates,
    collect_missing_ir_parties,
    collect_missing_pr_parties,
    stage_journal_parties_to_sql,
)
from trops_studio.ui.stranke_dialog import StrankeDialog
from trops_studio.ui.tooltip import ToolTip


class MissingJournalPartiesDialog(tk.Toplevel):
    """Listview manjkajočih kupcev (IR) / dobaviteljev (PR) pred oddajo temeljnic.

    review_mode=True: pregled iz zavihka Stranke (IR/PR preklop, brez »Nadaljuj sync«).
    """

    def __init__(
        self,
        master: tk.Misc,
        db: Database,
        *,
        org_id: str,
        book: str = "PR",
        rows: Sequence[dict[str, Any]] | None = None,
        on_done: Callable[[], None] | None = None,
        review_mode: bool = False,
    ) -> None:
        super().__init__(master)
        self.db = db
        self.org_id = str(org_id or "").strip()
        self.book = (book or "PR").upper()
        if self.book not in {"IR", "PR"}:
            self.book = "PR"
        self.rows = list(rows or [])
        self._fixed_rows = rows is not None  # sync: fiksne vrstice; pregled: vedno vsi iz DB
        self.on_done = on_done
        self.review_mode = bool(review_mode)
        self.items: list[dict[str, Any]] = []
        self.checked: dict[str, bool] = {}
        self._by_key: dict[str, dict[str, Any]] = {}
        self.resolved = False

        self.transient(master)
        self.grab_set()
        self.geometry("1020x560")
        self.minsize(820, 420)

        self.status = tk.StringVar(value="")
        self._hint1 = tk.StringVar(value="")
        self._hint2 = tk.StringVar(value="")
        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        if self.review_mode:
            switch = ttk.Frame(top)
            switch.pack(fill="x", pady=(0, 6))
            ttk.Label(switch, text="Knjiga:", style="Muted.TLabel").pack(side="left")
            self._book_var = tk.StringVar(value=self.book)
            for code, label in (("IR", "IR (kupci)"), ("PR", "PR (dobavitelji)")):
                ttk.Radiobutton(
                    switch,
                    text=label,
                    value=code,
                    variable=self._book_var,
                    command=self._on_book_change,
                ).pack(side="left", padx=(8, 0))
            ToolTip(switch, "Preklopi med manjkajočimi kupci (IR) in dobavitelji (PR) v Minimaxu.")
        ttk.Label(top, textvariable=self._hint1, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(top, textvariable=self._hint2, style="Muted.TLabel").pack(anchor="w")

        bar = ttk.Frame(self, padding=(12, 0, 12, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="Osveži", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Vse označi", command=lambda: self._set_all(True)).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Vse odznači", command=lambda: self._set_all(False)).pack(side="left", padx=6)
        btn_run = ttk.Button(
            bar,
            text="Obdelaj označene",
            style="Accent.TButton",
            command=self.process_selected,
        )
        btn_run.pack(side="left", padx=(12, 0))
        ToolTip(
            btn_run,
            "SI: poveži, če je že v Minimaxu (tam jo dodaš ti).\n"
            "EU/tretja: prenesi iz SQL v Minimax (po AI).\n"
            "Končni: šifra 01345.",
        )
        btn_manual = ttk.Button(bar, text="Odpri (AI / uredi)", command=self._edit_focused)
        btn_manual.pack(side="left", padx=8)
        ToolTip(
            btn_manual,
            "Odpri obrazec: Išči v Minimax, AI, shrani SQL, nato Prenesi.",
        )
        if self.review_mode:
            ttk.Button(bar, text="Zapri", style="Success.TButton", command=self.destroy).pack(side="right")
        else:
            ttk.Button(bar, text="Nadaljuj sync", style="Success.TButton", command=self._continue).pack(
                side="right"
            )
            ttk.Button(bar, text="Prekliči", command=self.destroy).pack(side="right", padx=(0, 8))

        frame = ttk.Frame(self, padding=(12, 0, 12, 6))
        frame.pack(fill="both", expand=True)
        cols = ("chk", "action", "status", "name", "vat", "country", "city", "doc")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ybar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        for key in cols:
            self.tree.heading(key, text=key)
            self.tree.column(key, width=100, minwidth=40)
        self.tree.tag_configure("checked", background="#1d3a2a", foreground="#c8f7d4")
        self.tree.tag_configure("tujec", background="#3a2a20", foreground="#f0d0b0")
        self.tree.tag_configure("si", background="#1e2a3a", foreground="#c8d6f0")
        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-1>", self._click_chk)

        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", padding=(12, 0, 12, 12)).pack(fill="x")
        self._apply_book_labels()
        self.refresh()

    def _on_book_change(self) -> None:
        self.book = (self._book_var.get() or "PR").upper()
        self.rows = []
        self._fixed_rows = False
        self.checked.clear()
        self._apply_book_labels()
        self.refresh()

    def _apply_book_labels(self) -> None:
        if self.book == "IR":
            role = "kupcev"
            title = "IR stranke manjkajo v Minimax"
            hint1 = (
                "Pregled kupcev iz IR, ki jih še ni v Minimaxu (brez MM šifre)."
                if self.review_mode
                else "Pred oddajo IR temeljnic uredite manjkajoče kupce z ID za DDV (SI…/DE…/IT…)."
            )
            hint2 = (
                "1 SI dodaj v Minimax → Obdelaj (poveži).  "
                "2 EU/tretja: Odpri (AI) → SQL → Obdelaj.  "
                "Brez DDV → Končni 01345."
            )
            name_col = "Kupec"
            doc_col = "IR listina"
            continue_warn = "Oddaja IR za te vrstice bo verjetno padla."
        else:
            role = "dobaviteljev"
            title = "PR stranke manjkajo v Minimax"
            hint1 = (
                "Pregled dobaviteljev iz PR, ki jih še ni v Minimaxu (brez MM šifre)."
                if self.review_mode
                else "Pred oddajo PR temeljnic uredite manjkajoče dobavitelje."
            )
            hint2 = (
                "1 SI dodaj v Minimax → Obdelaj (poveži).  "
                "2 EU/tretja: Odpri (AI) → SQL → Obdelaj."
            )
            name_col = "Dobavitelj"
            doc_col = "PR listina"
            continue_warn = "Oddaja PR za te vrstice bo verjetno padla."
        if self.review_mode:
            title = f"Stranke IR/PR → Minimax · {self.book}"
        self._role = role
        self._continue_warn = continue_warn
        self.title(title)
        self._hint1.set(hint1)
        self._hint2.set(hint2)
        headings = {
            "chk": ("Chk", 42),
            "action": ("Ukrep", 150),
            "status": ("Stanje", 130),
            "name": (name_col, 240),
            "vat": ("Davčna / DDV", 120),
            "country": ("Drž.", 50),
            "city": ("Kraj", 100),
            "doc": (doc_col, 110),
        }
        for key, (title_h, width) in headings.items():
            self.tree.heading(key, text=title_h)
            self.tree.column(
                key,
                width=width,
                minwidth=40,
                anchor="center" if key in {"chk", "country"} else "w",
            )

    def _collect(self) -> list[dict[str, Any]]:
        rows = self.rows if self._fixed_rows else None
        if self.book == "IR":
            return collect_missing_ir_parties(self.db, rows)
        return collect_missing_pr_parties(self.db, rows)

    def _doc_value(self, item: dict[str, Any]) -> str:
        return str(item.get("document") or item.get("pr_document") or "")

    def _row_key(self, item: dict[str, Any]) -> str:
        if item.get("party_id"):
            return f"p:{item['party_id']}"
        tax = str(item.get("tax_number") or "")
        vat = str(item.get("vat_id") or "")
        name = str(item.get("name") or "").casefold()
        return f"m:{tax or vat or name}"

    def refresh(self) -> None:
        # Adobe/placeholder dvojniki z že obstajajočo MM šifro → ven iz SQL in seznama
        try:
            absorb_all_minimax_duplicates(self.db)
        except Exception:
            pass
        self.items = self._collect()
        prev = dict(self.checked)
        self.checked.clear()
        self._by_key.clear()
        self.tree.delete(*self.tree.get_children())
        n_si = n_manual = 0
        for item in self.items:
            key = self._row_key(item)
            self._by_key[key] = item
            action = str(item.get("action") or "")
            # privzeto označi vse (tudi tujce) — za »Dodaj v Stranke«
            default = True
            self.checked[key] = prev.get(key, default)
            if action == ACTION_SI_AJPES:
                n_si += 1
            else:
                n_manual += 1
            tags: list[str] = []
            if self.checked[key]:
                tags.append("checked")
            tags.append("si" if action == ACTION_SI_AJPES else "tujec")
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    "✓" if self.checked[key] else "",
                    item.get("action_label") or "",
                    item.get("status") or "",
                    item.get("name") or "",
                    item.get("vat_id") or item.get("tax_number") or "",
                    item.get("country") or "",
                    item.get("city") or "",
                    self._doc_value(item),
                ),
                tags=tuple(tags),
            )
        if not self.items:
            self.status.set(
                f"Vse {self.book} stranke imajo Minimax šifro."
                + ("" if self.review_mode else " — lahko nadaljuješ sync.")
            )
        else:
            self.status.set(
                f"Manjka {len(self.items)} · SI {n_si} · ročno {n_manual} · Org {self.org_id or '?'}"
            )

    def _set_all(self, value: bool) -> None:
        for key in list(self.checked):
            self.checked[key] = value
        self._redraw()

    def _set_by_action(self, actions: set[str]) -> None:
        for key, item in self._by_key.items():
            self.checked[key] = str(item.get("action")) in actions
        self._redraw()

    def _redraw(self) -> None:
        for key, item in self._by_key.items():
            mark = "✓" if self.checked.get(key) else ""
            vals = list(self.tree.item(key, "values"))
            if vals:
                vals[0] = mark
                self.tree.item(key, values=vals)
            tags = ["checked"] if self.checked.get(key) else []
            tags.append("si" if item.get("action") == ACTION_SI_AJPES else "tujec")
            self.tree.item(key, tags=tuple(tags))

    def _click_chk(self, event: tk.Event) -> None:
        if self.tree.identify_column(event.x) != "#1":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.checked[row] = not bool(self.checked.get(row))
        self._redraw()

    def _toggle_selected(self, _event: object | None = None) -> str:
        row = self.tree.focus()
        if row:
            self.checked[row] = not bool(self.checked.get(row))
            self._redraw()
        return "break"

    def _on_double(self, _event: object | None = None) -> None:
        self._edit_focused()

    def _edit_focused(self) -> None:
        row = self.tree.focus() or (self.tree.selection()[0] if self.tree.selection() else "")
        item = self._by_key.get(row)
        if not item:
            messagebox.showinfo("Ročno", "Izberi vrstico.", parent=self)
            return
        party = None
        if item.get("party_id"):
            party = self.db.get_party(int(item["party_id"]))
        if party is None:
            party = {
                "vat_id": item.get("vat_id") or "",
                "tax_number": item.get("tax_number") or "",
                "country": item.get("country") or "",
                "name": item.get("name") or "",
                "address": item.get("address") or "",
                "postal_code": item.get("postal_code") or "",
                "city": item.get("city") or "",
                "is_foreign": 1 if item.get("action") == ACTION_TUJEC else 0,
                "source": "manual",
            }
        # Alias = naziv z listine (Open AI, llc), da po shramba/MM povežemo PR/IR
        journal_name = sanitize_display_text(item.get("name"))
        aliases = [journal_name] if journal_name else []
        dialog = StrankeDialog(
            self,
            self.db,
            party=party,
            org_id=self.org_id,
            on_saved=self.refresh,
            name_aliases=aliases,
        )
        self.wait_window(dialog)
        if self.on_done:
            self.on_done()
        self.refresh()

    def add_selected_to_parties(self) -> None:
        selected = [
            item for item in self.items if self.checked.get(self._row_key(item))
        ]
        if not selected:
            # če nič ni označeno — dodaj vse na seznamu
            selected = list(self.items)
        if not selected:
            messagebox.showinfo("Stranke", "Ni manjkajočih za dodajanje.", parent=self)
            return
        if not messagebox.askyesno(
            "Dodaj v Stranke",
            f"Shranim {len(selected)} firm v SQLite Stranke\n"
            "(tudi tujce / tretje države) in povežem listine?\n\n"
            "Minimax še ne — to stori »Poveži / posodobi Minimax« ali sync.",
            parent=self,
        ):
            return
        self.status.set(f"Dodajam v Stranke: {len(selected)} …")
        self.update_idletasks()
        try:
            result = stage_journal_parties_to_sql(self.db, selected)
        except Exception as exc:
            messagebox.showerror("Stranke", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Stranke",
            f"V Stranke: {result.get('staged', 0)}\n"
            f"Povezanih listin: {result.get('linked', 0)}\n\n"
            "Odpri stranko (dvoklik) za dopolnitev, nato Minimax.",
            parent=self,
        )
        if self.on_done:
            self.on_done()
        self.refresh()

    def process_selected(self) -> None:
        selected = [item for item in self.items if self.checked.get(self._row_key(item))]
        if not selected:
            messagebox.showinfo("Stranke", "Označi vsaj eno vrstico.", parent=self)
            return
        if not self.org_id:
            messagebox.showerror("Minimax", "Manjka Org_ID.", parent=self)
            return
        si_or_koncni = [
            item
            for item in selected
            if item.get("action") in {ACTION_SI_AJPES, ACTION_KONCNI}
        ]
        foreign = [item for item in selected if item.get("action") == ACTION_TUJEC]
        self.status.set(f"Obdelujem {len(selected)} …")
        self.update_idletasks()
        parts: list[str] = []
        try:
            if si_or_koncni:
                result = import_parties_to_minimax(
                    self.db, self.org_id, si_or_koncni, use_ajpes=False, allow_create=False
                )
                parts.append(result.message)
                if result.failed:
                    parts.extend(result.failed[:8])
            if foreign:
                try:
                    stage_journal_parties_to_sql(self.db, foreign)
                except Exception:
                    pass
                result = import_parties_to_minimax(
                    self.db, self.org_id, foreign, use_ajpes=False, allow_create=True
                )
                parts.append(result.message)
                if result.failed:
                    parts.extend(result.failed[:8])
        except Exception as exc:
            messagebox.showerror("Minimax", str(exc), parent=self)
            return
        messagebox.showinfo("Stranke → Minimax", "\n".join(parts) or "Ni sprememb.", parent=self)
        if self.on_done:
            self.on_done()
        self.refresh()

    def _continue(self) -> None:
        still = self._collect()
        if still:
            n = len(still)
            if not messagebox.askyesno(
                "Še manjka",
                f"Še {n} {self._role} nima Minimax šifre.\n"
                f"{self._continue_warn}\n\n"
                "Nadaljujem vseeno?",
                parent=self,
            ):
                return
        self.resolved = True
        self.destroy()


class MissingPrPartiesDialog(MissingJournalPartiesDialog):
    """Kompatibilnost: PR manjkajoče stranke."""

    def __init__(
        self,
        master: tk.Misc,
        db: Database,
        *,
        org_id: str,
        pr_rows: Sequence[dict[str, Any]] | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            db,
            org_id=org_id,
            book="PR",
            rows=pr_rows,
            on_done=on_done,
        )


class MissingIrPartiesDialog(MissingJournalPartiesDialog):
    """IR manjkajoče stranke (SI/DE/IT…)."""

    def __init__(
        self,
        master: tk.Misc,
        db: Database,
        *,
        org_id: str,
        ir_rows: Sequence[dict[str, Any]] | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            db,
            org_id=org_id,
            book="IR",
            rows=ir_rows,
            on_done=on_done,
        )
