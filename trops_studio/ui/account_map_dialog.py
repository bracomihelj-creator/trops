"""Dialog: Trops konti → Minimax knjižljivi (shrani za naslednjič)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from trops_studio.account_choices import (
    account_code_from_choice,
    clear_account_cache,
    find_unmapped_accounts,
    load_account_choices,
    minimax_account_codes,
)
from trops_studio.db import Database
from trops_studio.ui.tooltip import ToolTip


class AccountMapDialog(tk.Toplevel):
    """Preveri skladnost kontov z Minimaxom in shrani zamenjave."""

    def __init__(
        self,
        master: tk.Misc,
        db: Database,
        *,
        org_id: str = "",
        title: str = "Konti Trops → Minimax",
        force_open: bool = False,
        on_saved: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.db = db
        self.org_id = str(org_id or "").strip()
        self.on_saved = on_saved
        self.confirmed = False
        self.saved_maps: dict[str, str] = {}
        self._rows: list[dict[str, Any]] = []
        self._choice_vars: dict[str, tk.StringVar] = {}
        self._mm_choices = load_account_choices(db, self.org_id, fetch_minimax=False)
        self._mm_codes = minimax_account_codes(db, self.org_id)

        self.title(title)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.geometry("920x520")
        self.minsize(720, 400)

        pad = ttk.Frame(self, padding=12)
        pad.pack(fill="both", expand=True)
        ttk.Label(
            pad,
            text=(
                "Konti, ki niso v Minimax knjižljivem planu.\n"
                "Izberi Minimax zamenjavo → Potrdi shrani mapiranje za IR / PR / vse knjižbe."
            ),
            style="Muted.TLabel",
            wraplength=860,
        ).pack(anchor="w")

        self.info_var = tk.StringVar(value="")
        ttk.Label(pad, textvariable=self.info_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))

        cols = ("trops", "count", "minimax")
        self.tree = ttk.Treeview(pad, columns=cols, show="headings", selectmode="browse", height=14)
        self.tree.heading("trops", text="Trops konto")
        self.tree.heading("count", text="× uporab")
        self.tree.heading("minimax", text="Minimax zamenjava")
        self.tree.column("trops", width=120, anchor="w")
        self.tree.column("count", width=80, anchor="e")
        self.tree.column("minimax", width=520, anchor="w")
        yscroll = ttk.Scrollbar(pad, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        ToolTip(self.tree, "Izberi vrstico, nato Minimax konto spodaj.")

        edit = ttk.Frame(self, padding=(12, 0, 12, 8))
        edit.pack(fill="x")
        ttk.Label(edit, text="Zamenjaj z:", style="Muted.TLabel").pack(side="left")
        self.combo_var = tk.StringVar(value="")
        self.combo = ttk.Combobox(
            edit, textvariable=self.combo_var, values=self._mm_choices, width=70
        )
        self.combo.pack(side="left", padx=(8, 0), fill="x", expand=True)
        self.combo.bind("<<ComboboxSelected>>", self._apply_combo)
        self.combo.bind("<Return>", self._apply_combo)
        ttk.Button(edit, text="Uporabi", command=self._apply_combo).pack(side="left", padx=(8, 0))

        btns = ttk.Frame(self, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="Prekliči", command=self._cancel).pack(side="right")
        ok = ttk.Button(
            btns,
            text="Potrdi in shrani",
            style="Accent.TButton",
            command=self._confirm,
        )
        ok.pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="Osveži", command=self.refresh).pack(side="left")
        self.apply_data_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            btns,
            text="Prepiši tudi v kisanal / IR / PR",
            variable=self.apply_data_var,
        ).pack(side="left", padx=(12, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.refresh()
        if not self._rows and not force_open:
            self.confirmed = True
            self.after(10, self.destroy)
            return
        self.wait_window(self)

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows = find_unmapped_accounts(self.db, self.org_id)
        # vključi tudi že izbrane v tej seji, če še niso resolved
        for trops, var in list(self._choice_vars.items()):
            if trops not in {r["trops_code"] for r in self._rows}:
                continue
        for row in self._rows:
            trops = row["trops_code"]
            if trops not in self._choice_vars:
                suggested = row.get("suggested") or ""
                label = self._label_for_code(suggested) if suggested else ""
                self._choice_vars[trops] = tk.StringVar(value=label)
            self.tree.insert(
                "",
                "end",
                iid=trops,
                values=(
                    trops,
                    row.get("count", 0),
                    self._choice_vars[trops].get() or "(izberi)",
                ),
            )
        n = len(self._rows)
        if not self._mm_codes:
            self.info_var.set(
                "Ni Minimax kontnega plana v SQL — najprej: Datoteka → Kontni plan iz Minimax → SQL."
            )
        else:
            self.info_var.set(
                f"{n} kontov zahteva zamenjavo · Org {self.org_id or '—'} · "
                f"{len(self._mm_codes)} knjižljivih MM"
            )

    def _label_for_code(self, code: str) -> str:
        code = account_code_from_choice(code)
        if not code:
            return ""
        for label in self._mm_choices:
            if account_code_from_choice(label) == code:
                return label
        return code

    def _on_select(self, _event: Any = None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        trops = sel[0]
        self.combo_var.set(self._choice_vars.get(trops, tk.StringVar()).get())

    def _apply_combo(self, _event: Any = None) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning(self.title(), "Najprej izberi Trops konto v tabeli.", parent=self)
            return
        trops = sel[0]
        label = self.combo_var.get().strip()
        code = account_code_from_choice(label)
        if not code or (self._mm_codes and code not in self._mm_codes):
            messagebox.showwarning(
                self.title(),
                "Izberi knjižljiv Minimax konto iz seznama.",
                parent=self,
            )
            return
        self._choice_vars.setdefault(trops, tk.StringVar()).set(self._label_for_code(code))
        self.tree.set(trops, "minimax", self._choice_vars[trops].get())

    def _collect_maps(self) -> dict[str, str] | None:
        maps: dict[str, str] = {}
        missing: list[str] = []
        for row in self._rows:
            trops = row["trops_code"]
            label = (self._choice_vars.get(trops) or tk.StringVar()).get()
            mm = account_code_from_choice(label)
            if not mm:
                missing.append(trops)
                continue
            if self._mm_codes and mm not in self._mm_codes:
                missing.append(trops)
                continue
            maps[trops] = mm
        if missing:
            messagebox.showwarning(
                self.title(),
                "Manjka Minimax zamenjava za:\n" + ", ".join(missing),
                parent=self,
            )
            return None
        return maps

    def _confirm(self) -> None:
        if not self._rows:
            self.confirmed = True
            self.destroy()
            return
        maps = self._collect_maps()
        if maps is None:
            return
        n = self.db.upsert_account_code_maps(maps, org_id=self.org_id, source="user")
        clear_account_cache()
        applied = {}
        if self.apply_data_var.get():
            applied = self.db.apply_account_code_maps_to_data(maps, org_id=self.org_id)
        self.saved_maps = maps
        self.confirmed = True
        detail = ""
        if applied:
            detail = (
                f"\nPrepisano: kisanal {applied.get('kisanal', 0)}, "
                f"IR {applied.get('ir', 0)}, PR {applied.get('pr', 0)}, "
                f"knjižbe {applied.get('journal', 0)}."
            )
        messagebox.showinfo(
            self.title(),
            f"Shranjenih {n} mapiranj za naslednjič.{detail}",
            parent=self,
        )
        if self.on_saved:
            try:
                self.on_saved(maps)
            except Exception:
                pass
        self.destroy()

    def _cancel(self) -> None:
        self.confirmed = False
        self.destroy()


def ensure_accounts_mapped(
    master: tk.Misc,
    db: Database,
    *,
    org_id: str = "",
    title: str = "Konti Trops → Minimax",
    block_if_cancel: bool = True,
) -> bool:
    """Odpri dialog, če obstajajo nemapirani konti. True = lahko nadaljuješ."""
    unmapped = find_unmapped_accounts(db, org_id)
    if not unmapped:
        return True
    dlg = AccountMapDialog(master, db, org_id=org_id, title=title, force_open=True)
    if dlg.confirmed:
        return True
    if block_if_cancel:
        return False
    return True
