"""ListView: vsi podatki iz spleta/AI (+ VIES), prepis v obrazec Stranke."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable
from webbrowser import open as open_url

from trops_studio.party_web_ai import PartyWebResult, google_search_url
from trops_studio.ui.tooltip import ToolTip


class PartyWebResultsDialog(tk.Toplevel):
    """Prikaže čim več pridobljenih podatkov (Podatek | Vrednost)."""

    def __init__(
        self,
        master: tk.Misc,
        result: PartyWebResult,
        *,
        query_name: str = "",
        query_vat: str = "",
        query_country: str = "",
        on_apply: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.result = result
        self.on_apply = on_apply
        self.query_name = query_name
        self.query_vat = query_vat
        self.query_country = query_country
        self.applied = False

        self.title("Najdi na spletu — rezultati")
        self.transient(master)
        self.grab_set()
        self.geometry("820x560")
        self.minsize(640, 420)

        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        ttk.Label(
            top,
            text=result.message or "Pridobljeni podatki (preveri pred shranjevanjem).",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w")
        if result.used_ai:
            ttk.Label(top, text="Vir: splet + AI", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(self, padding=(12, 0, 12, 6))
        bar.pack(fill="x")
        btn_apply = ttk.Button(bar, text="Prepiši v obrazec", style="Success.TButton", command=self._apply)
        btn_apply.pack(side="left")
        ToolTip(
            btn_apply,
            "Prepiše VIES naziv/naslov + DDV v obrazec Stranke\n"
            "(ulica, pošta, kraj, država, vrsta EU/SI/tretja).",
        )
        eu = self._first_eu_entity()
        if eu:
            btn_eu = ttk.Button(
                bar,
                text=f"Uporabi EU: {eu.get('vat_id') or eu.get('country')}",
                style="Accent.TButton",
                command=lambda: self._apply_entity(eu),
            )
            btn_eu.pack(side="left", padx=8)
            ToolTip(
                btn_eu,
                f"Prepiši EU subjekt v obrazec:\n{eu.get('name')} · {eu.get('vat_id')}\n"
                f"{eu.get('headquarters') or ''}",
            )
        ttk.Button(bar, text="Google", command=self._open_google).pack(side="left", padx=8)
        ttk.Button(bar, text="Zapri", command=self.destroy).pack(side="right")

        frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        frame.pack(fill="both", expand=True)
        cols = ("field", "value")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ybar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        self.tree.heading("field", text="Podatek")
        self.tree.heading("value", text="Vrednost")
        self.tree.column("field", width=220, minwidth=120, stretch=False)
        self.tree.column("value", width=520, minwidth=200, stretch=True)
        self.tree.tag_configure("section", background="#1e2a3a", foreground="#c8d6f0")
        self.tree.tag_configure("warn", background="#3a2a20", foreground="#f0d0b0")
        self.tree.tag_configure("ok", background="#1d3a2a", foreground="#c8f7d4")

        self._populate()
        self.tree.bind("<Double-1>", lambda _e: self._apply())

    def _populate(self) -> None:
        rows = self.result.as_listview_rows()
        if not rows:
            self.tree.insert("", "end", values=("—", "Ni podatkov"), tags=("warn",))
            return
        for label, value, tag in rows:
            tags = (tag,) if tag else ()
            self.tree.insert("", "end", values=(label, value), tags=tags)

    def _open_google(self) -> None:
        open_url(google_search_url(self.query_name, self.query_vat, self.query_country))

    def _first_eu_entity(self) -> dict[str, str] | None:
        for ent in self.result.related_entities or []:
            if ent.get("vat_id") and str(ent.get("country") or "").upper() not in {"", "IL"}:
                return ent
        return None

    def _entity_to_updates(self, ent: dict[str, str]) -> dict[str, str]:
        from trops_studio.money import normalize_vat_id
        from trops_studio.party_web_ai import _split_headquarters, _split_vies_address

        def _clean(val: str) -> str:
            text = str(val or "").strip()
            return "" if text in {"", "-", "—", "."} else text

        name = _clean(ent.get("vies_name") or "") or _clean(ent.get("name") or "")
        address = _clean(ent.get("address") or "")
        postal = _clean(ent.get("postal_code") or "")
        city = _clean(ent.get("city") or "")
        vies_addr = _clean(ent.get("vies_address") or "")
        if vies_addr:
            split = _split_vies_address(vies_addr)
            address = address or split.get("address") or vies_addr
            postal = postal or split.get("postal_code") or ""
            city = city or split.get("city") or ""
        hq = _clean(ent.get("headquarters") or "")
        if hq:
            split = _split_headquarters(hq)
            address = address or split.get("address") or hq
            postal = postal or split.get("postal_code") or ""
            city = city or split.get("city") or ""
        vat = normalize_vat_id(ent.get("vat_id"))
        country = _clean(ent.get("country") or "").upper()[:2]
        if not country and len(vat) >= 2 and vat[:2].isalpha():
            country = vat[:2]
        tax = vat[2:] if vat and len(vat) > 2 and vat[:2].isalpha() else ""
        mapping = {
            "name": name,
            "vat_id": vat,
            "tax_number": tax,
            "address": address,
            "postal_code": postal,
            "city": city,
            "country": country,
            "registration_no": _clean(ent.get("registration_no") or ""),
        }
        return {k: v for k, v in mapping.items() if str(v or "").strip()}

    def _apply_entity(self, ent: dict[str, str]) -> None:
        updates = self._entity_to_updates(ent)
        if not updates:
            messagebox.showinfo("Prepis", "Ni polj za prepis.", parent=self)
            return
        preview = "\n".join(f"• {k}: {v}" for k, v in updates.items())
        note = ent.get("vies") or ent.get("notes") or ""
        if not messagebox.askyesno(
            "Uporabi EU subjekt",
            f"Prepišem EU subjekt v obrazec?\n\n{preview}"
            + (f"\n\n{note}" if note else ""),
            parent=self,
        ):
            return
        if self.on_apply:
            self.on_apply(updates)
        self.applied = True
        self.destroy()

    def _apply(self) -> None:
        updates = self.result.as_form_updates()
        if not updates:
            messagebox.showinfo("Prepis", "Ni polj za prepis v obrazec.", parent=self)
            return
        preview = "\n".join(f"• {k}: {v}" for k, v in updates.items())
        if not messagebox.askyesno(
            "Prepiši v obrazec",
            f"Prepišem ta polja?\n\n{preview}",
            parent=self,
        ):
            return
        if self.on_apply:
            self.on_apply(updates)
        self.applied = True
        self.destroy()
