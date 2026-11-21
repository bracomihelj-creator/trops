"""Seznam novih firm → SQLite (ready), nato Sinhroniziraj Minimax."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from trops_studio.config import KONCNI_KUPCI_CODE
from trops_studio.db import Database
from trops_studio.money import normalize_text, normalize_vat_id, tax_digits
from trops_studio.parties_ensure import (
    ACTION_KONCNI,
    ACTION_SI_AJPES,
    ACTION_TUJEC,
    collect_firms_needing_minimax,
)
from trops_studio.sync_state import SYNC_READY
from trops_studio.ui.stranke_dialog import StrankeDialog
from trops_studio.ui.tooltip import ToolTip


class NoveFirmeDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Tk,
        db: Database,
        *,
        org_id: str,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.db = db
        self.org_id = str(org_id or "").strip()
        self.on_done = on_done
        self.items: list[dict[str, Any]] = []
        self.checked: dict[str, bool] = {}
        self._by_key: dict[str, dict[str, Any]] = {}

        self.title("Nove firme → SQL (nato Minimax)")
        self.transient(master)
        self.grab_set()
        self.geometry("980x580")
        self.minsize(800, 440)

        self.status = tk.StringVar(value="")
        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        ttk.Label(
            top,
            text="Samo partnerji, ki jih ni v SQLite ali so brez Minimax šifre.",
            style="Muted.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            top,
            text=(
                f"SI z davčno → Minimax API (addbytaxnumber) · "
                f"brez davčne → Končni kupci {KONCNI_KUPCI_CODE} · "
                f"EU/tretja → AI + SQL, nato Minimax API"
            ),
            style="Muted.TLabel",
        ).pack(anchor="w")

        bar = ttk.Frame(self, padding=(12, 0, 12, 6))
        bar.pack(fill="x")
        btn_refresh = ttk.Button(bar, text="Osveži", command=self.refresh)
        btn_refresh.pack(side="left")
        btn_all = ttk.Button(bar, text="Vse označi", command=lambda: self._set_all(True))
        btn_all.pack(side="left", padx=6)
        btn_none = ttk.Button(bar, text="Vse odznači", command=lambda: self._set_all(False))
        btn_none.pack(side="left")
        btn_si = ttk.Button(bar, text="Samo SI+davčna", command=lambda: self._set_by_action({ACTION_SI_AJPES}))
        btn_si.pack(side="left", padx=(12, 0))
        btn_k = ttk.Button(bar, text="Samo Končni", command=lambda: self._set_by_action({ACTION_KONCNI}))
        btn_k.pack(side="left", padx=6)
        btn_import = ttk.Button(
            bar,
            text="Potrdi v SQL",
            style="Accent.TButton",
            command=self.import_selected,
        )
        btn_import.pack(side="right")
        btn_close = ttk.Button(bar, text="Zapri", command=self.destroy)
        btn_close.pack(side="right", padx=(0, 8))
        ToolTip(btn_refresh, "Ponovno preberi seznam iz SQLite / IR / PR.")
        ToolTip(btn_all, "Označi vse vrstice (tudi tujce).")
        ToolTip(btn_none, "Odznači vse.")
        ToolTip(btn_si, "Označi samo SI z davčno.")
        ToolTip(btn_k, f"Označi samo brez davčne → Končni kupci {KONCNI_KUPCI_CODE}.")
        ToolTip(
            btn_import,
            "Potrdi označene samo v SQLite (sync_status=ready).\n"
            "Minimax API: glavni gumb »Sinhroniziraj Minimax«.\n"
            "Tujci: dvoklik → ročni obrazec Stranke.",
        )
        ToolTip(btn_close, "Zapri.")

        frame = ttk.Frame(self, padding=(12, 0, 12, 6))
        frame.pack(fill="both", expand=True)
        cols = ("chk", "action", "status", "name", "vat", "country", "city", "source")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ybar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        headings = {
            "chk": ("Chk", 42),
            "action": ("Ukrep", 140),
            "status": ("Stanje", 110),
            "name": ("Naziv", 240),
            "vat": ("Davčna / DDV", 120),
            "country": ("Drž.", 50),
            "city": ("Kraj", 110),
            "source": ("Vir", 90),
        }
        for key, (title, width) in headings.items():
            self.tree.heading(key, text=title)
            self.tree.column(
                key,
                width=width,
                minwidth=40,
                anchor="center" if key in {"chk", "country"} else "w",
            )
        self.tree.tag_configure("checked", background="#1d3a2a", foreground="#c8f7d4")
        self.tree.tag_configure("tujec", background="#3a2a20", foreground="#f0d0b0")
        self.tree.tag_configure("koncni", background="#1e2a3a", foreground="#c8d6f0")
        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-1>", self._click_chk)

        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", padding=(12, 0, 12, 12)).pack(fill="x")
        self.refresh()

    def _row_key(self, item: dict[str, Any]) -> str:
        if item.get("party_id"):
            return f"p:{item['party_id']}"
        tax = str(item.get("tax_number") or "")
        vat = str(item.get("vat_id") or "")
        name = str(item.get("name") or "").casefold()
        return f"m:{tax or vat or name}"

    def _default_checked(self, item: dict[str, Any]) -> bool:
        # Tujce privzeto ne označuj — zahtevajo ročni vnos.
        return str(item.get("action")) != ACTION_TUJEC

    def refresh(self) -> None:
        self.items = collect_firms_needing_minimax(self.db)
        prev = dict(self.checked)
        self.checked.clear()
        self._by_key.clear()
        self.tree.delete(*self.tree.get_children())
        counts = {ACTION_SI_AJPES: 0, ACTION_KONCNI: 0, ACTION_TUJEC: 0}
        for item in self.items:
            key = self._row_key(item)
            self._by_key[key] = item
            self.checked[key] = prev.get(key, self._default_checked(item))
            mark = "✓" if self.checked[key] else ""
            vat = item.get("vat_id") or item.get("tax_number") or ""
            action = str(item.get("action") or "")
            counts[action] = counts.get(action, 0) + 1
            tags: list[str] = []
            if self.checked[key]:
                tags.append("checked")
            if action == ACTION_TUJEC:
                tags.append("tujec")
            elif action == ACTION_KONCNI:
                tags.append("koncni")
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    mark,
                    item.get("action_label") or "",
                    item.get("status") or "",
                    item.get("name") or "",
                    vat,
                    item.get("country") or "",
                    item.get("city") or "",
                    item.get("source") or "",
                ),
                tags=tuple(tags),
            )
        n = len(self.items)
        marked = sum(1 for v in self.checked.values() if v)
        self.status.set(
            f"{n} novih · SI {counts.get(ACTION_SI_AJPES, 0)} · "
            f"Končni {counts.get(ACTION_KONCNI, 0)} · tujci {counts.get(ACTION_TUJEC, 0)} · "
            f"označenih {marked} · Org {self.org_id or '?'}"
            if n
            else "Ni novih firm — vse so v SQLite z Minimax šifro."
        )

    def _set_all(self, value: bool) -> None:
        for key in list(self.checked):
            self.checked[key] = value
        self._redraw_marks()

    def _set_by_action(self, actions: set[str]) -> None:
        for key, item in self._by_key.items():
            self.checked[key] = str(item.get("action")) in actions
        self._redraw_marks()

    def _redraw_marks(self) -> None:
        for key in self.tree.get_children():
            vals = list(self.tree.item(key, "values"))
            on = bool(self.checked.get(key))
            vals[0] = "✓" if on else ""
            item = self._by_key.get(key) or {}
            action = str(item.get("action") or "")
            tags: list[str] = []
            if on:
                tags.append("checked")
            if action == ACTION_TUJEC:
                tags.append("tujec")
            elif action == ACTION_KONCNI:
                tags.append("koncni")
            self.tree.item(key, values=vals, tags=tuple(tags))
        marked = sum(1 for v in self.checked.values() if v)
        self.status.set(
            f"{len(self.items)} novih · označenih {marked} · Org {self.org_id or '?'}"
        )

    def _toggle_selected(self, _event: object | None = None) -> str:
        for key in self.tree.selection():
            self.checked[key] = not bool(self.checked.get(key))
        self._redraw_marks()
        return "break"

    def _on_double(self, _event: object) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = self._by_key.get(sel[0])
        if not item:
            return
        if str(item.get("action")) == ACTION_TUJEC:
            self._open_manual(item)
        else:
            self._toggle_selected()

    def _click_chk(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return None
        col = self.tree.identify_column(event.x)
        if col != "#1":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        self.checked[row] = not bool(self.checked.get(row))
        self._redraw_marks()
        return "break"

    def _open_manual(self, item: dict[str, Any]) -> None:
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
                "is_foreign": 1,
                "source": "manual",
            }
        dialog = StrankeDialog(
            self,
            self.db,
            party=party,
            org_id=self.org_id,
            on_saved=self.on_done,
        )
        self.wait_window(dialog)
        if self.on_done:
            self.on_done()
        self.refresh()

    def import_selected(self) -> None:
        selected = [item for item in self.items if self.checked.get(self._row_key(item))]
        if not selected:
            messagebox.showinfo("SQL", "Označi vsaj eno firmo.", parent=self)
            return
        n_si = sum(1 for i in selected if i.get("action") == ACTION_SI_AJPES)
        n_k = sum(1 for i in selected if i.get("action") == ACTION_KONCNI)
        n_t = sum(1 for i in selected if i.get("action") == ACTION_TUJEC)
        if not messagebox.askyesno(
            "Potrdi v SQL",
            f"Shranim v SQLite (ready), brez Minimax API:\n\n"
            f"• SI z davčno: {n_si}\n"
            f"• Končni kupci: {n_k}\n"
            f"• Tujci (ročno): {n_t}\n\n"
            "Nato »Sinhroniziraj Minimax« na glavnem oknu.",
            parent=self,
        ):
            return
        staged = 0
        skipped = 0
        for raw in selected:
            item = dict(raw)
            action = str(item.get("action") or "")
            if action == ACTION_TUJEC:
                skipped += 1
                continue
            name = normalize_text(item.get("name")) or "Neznana stranka"
            payload = {
                "vat_id": normalize_vat_id(item.get("vat_id") or ""),
                "tax_number": tax_digits(item.get("tax_number") or item.get("vat_id") or ""),
                "country": item.get("country") or "SI",
                "name": name,
                "address": item.get("address") or "",
                "postal_code": item.get("postal_code") or "",
                "city": item.get("city") or "",
                "is_foreign": 1 if item.get("is_foreign") else 0,
                "source": "sql_stage",
                "sync_status": SYNC_READY,
                "minimax_code": "",
                "notes": "Pripravljeno v SQL — čaka Sinhroniziraj Minimax",
            }
            if action == ACTION_KONCNI:
                payload["notes"] = f"Končni kupci → {KONCNI_KUPCI_CODE} (ob sync)"
            party_id = item.get("party_id")
            if party_id:
                self.db.upsert_party(payload, party_id=int(party_id))
                self.db.set_party_sync(int(party_id), SYNC_READY)
            else:
                new_id = self.db.upsert_party(payload)
                self.db.set_party_sync(new_id, SYNC_READY)
            staged += 1
        msg = (
            f"V SQL pripravljeno: {staged} (ready).\n"
            f"Tujci za ročni vnos: {skipped}.\n\n"
            "Zdaj na glavnem oknu: »Sinhroniziraj Minimax«."
        )
        messagebox.showinfo("Potrdi v SQL", msg, parent=self)
        self.status.set(f"SQL ready: {staged}")
        if self.on_done:
            self.on_done()
        self.refresh()
