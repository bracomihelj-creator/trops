"""Listview IR/API ali PR/API: davčna, ime, dokument in razlike."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from datetime import date
from typing import Any, Callable, Mapping

from trops_studio.pr_list_view import region_label
from trops_studio.ui.tooltip import ToolTip
from trops_studio.vat_api_check import VatApiReport, VatApiRow, apply_api_to_party


class VatApiCheckDialog(tk.Toplevel):
    """Dva sklopa stolpcev: Trops (IR/PR) vs API (AJPES/VIES/Minimax)."""

    def __init__(
        self,
        master: tk.Misc,
        db: Any,
        report: VatApiReport,
        *,
        on_applied: Callable[[], None] | None = None,
        on_open_party: Callable[[int], None] | None = None,
        on_force_refresh: Callable[[], None] | None = None,
        company: Mapping[str, Any] | None = None,
        period_from: date | None = None,
        period_to: date | None = None,
        session_label: str = "",
    ) -> None:
        super().__init__(master)
        self.db = db
        self.report = report
        self.on_applied = on_applied
        self.on_open_party = on_open_party
        self.on_force_refresh = on_force_refresh
        self.company = company
        self.period_from = period_from
        self.period_to = period_to
        self.checked: dict[str, bool] = {}
        self._by_iid: dict[str, VatApiRow] = {}

        book = report.book
        fo = report.mode == "fo"
        title = (
            "Preverba fizičnih oseb — IR brez SI/DE/US"
            if fo
            else f"Preveri {book} — Minimax / VIES / splet"
        )
        if session_label:
            title = f"{title} · {session_label}"
        self.title(title)
        self.transient(master)
        self.geometry("1280x620")
        self.minsize(960, 420)

        self.status = tk.StringVar(
            value=f"{report.message} · {session_label}" if session_label else report.message
        )
        self.filter_var = tk.StringVar(value="ALL" if fo else "DIFF")
        self.update_name_var = tk.BooleanVar(value=False)

        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        ttk.Label(
            top,
            text=(
                "8 mest brez SI = na listini ni davčni zavezanec. "
                "Če AJPES ugotovi zavezanca (npr. JR GYM d.o.o.) → v potrditev Projestu."
                if fo
                else (
                    f"{book}: SI samo Minimax. EU Minimax+VIES. "
                    "Tretje: ime v Minimaxu (Open AI). Ne podvajaj šifer."
                )
            ),
            style="Muted.TLabel",
            wraplength=1180,
        ).pack(anchor="w")

        bar = ttk.Frame(self, padding=(12, 0, 12, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="Prikaz:", style="Muted.TLabel").pack(side="left")
        for label, value in (("Samo razlike", "DIFF"), ("Vse listine", "ALL")):
            ttk.Radiobutton(
                bar,
                text=label,
                value=value,
                variable=self.filter_var,
                command=self._fill,
            ).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Vse označi", command=lambda: self._set_all(True)).pack(
            side="left", padx=(16, 0)
        )
        ttk.Button(bar, text="Vse odznači", command=lambda: self._set_all(False)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Checkbutton(
            bar,
            text="Posodobi tudi naziv iz API",
            variable=self.update_name_var,
        ).pack(side="left", padx=(16, 0))
        btn_apply = ttk.Button(
            bar,
            text="Uporabi API na izbrane",
            style="Accent.TButton",
            command=self._apply_selected,
        )
        btn_apply.pack(side="left", padx=(12, 0))
        ToolTip(
            btn_apply,
            "Na označene vrstice z razliko: država + tujec/SI + davčna iz API.\n"
            "AJPES SI → Domači (is_foreign=0). Odpravi napačen tujec na slo firmi.",
        )
        ttk.Button(bar, text="Zapri", command=self.destroy).pack(side="right")
        if on_force_refresh:
            btn_refresh = ttk.Button(bar, text="Osveži z API", command=self._force_refresh)
            btn_refresh.pack(side="right", padx=(0, 8))
            ToolTip(
                btn_refresh,
                "Znova kliče VIES/splet; Minimax šifrant vedno živo.\n"
                "SI se ne kliče na AJPES. Shranjeni VIES/splet se sicer uporabijo.",
            )
        btn_mail = ttk.Button(
            bar,
            text="Pošlji seznam nepravilnosti",
            style="Success.TButton",
            command=self._send_irregularities,
        )
        btn_mail.pack(side="right", padx=(0, 8))
        ToolTip(
            btn_mail,
            "Stranki (e-pošta iz evidence) pošlje seznam v potrditev.\n"
            "8 mest brez SI + AJPES zavezanec. Označene vrstice, sicer vse. Gmail SMTP.",
        )

        frame = ttk.Frame(self, padding=(12, 0, 12, 6))
        frame.pack(fill="both", expand=True)
        cols = (
            "chk",
            "doc",
            "ir_vat",
            "ir_name",
            "ir_region",
            "api_vat",
            "api_name",
            "api_region",
            "api_src",
            "status",
            "diff",
        )
        ir_lbl = "IR" if book == "IR" else "PR"
        headings = {
            "chk": ("Chk", 42),
            "doc": ("Dokument", 130),
            "ir_vat": (f"{ir_lbl} davčna", 120),
            "ir_name": (f"{ir_lbl} ime", 210),
            "ir_region": (f"{ir_lbl} regija", 100),
            "api_vat": ("API davčna", 120),
            "api_name": ("API ime", 210),
            "api_region": ("API regija", 100),
            "api_src": ("API vir", 80),
            "status": ("Status", 220),
            "diff": ("Razlike", 240),
        }
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for key in cols:
            title, width = headings[key]
            self.tree.heading(key, text=title)
            self.tree.column(
                key,
                width=width,
                minwidth=36,
                stretch=key in {"ir_name", "api_name", "status", "diff"},
                anchor="center" if key in {"chk", "ir_region", "api_region", "api_src"} else "w",
            )
        self.tree.tag_configure("ok", background="#102418", foreground="#c8f7d4")
        self.tree.tag_configure("diff", background="#5a1c1c", foreground="#ffd0d0")
        self.tree.tag_configure("odd", background="#101c31")
        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-1>", self._click_chk, add="+")

        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", padding=(12, 0, 12, 12)).pack(
            fill="x"
        )
        self._fill()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _visible_rows(self) -> list[VatApiRow]:
        if self.filter_var.get() == "DIFF":
            return [row for row in self.report.rows if row.has_diff]
        return list(self.report.rows)

    def _fill(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._by_iid.clear()
        visible = self._visible_rows()
        for index, row in enumerate(visible):
            iid = f"{row.book}:{row.row_id}:{index}"
            self._by_iid[iid] = row
            checked = bool(self.checked.get(iid, row.has_diff))
            self.checked[iid] = checked
            tag = "diff" if row.has_diff else ("ok" if row.api.source else ("odd" if index % 2 else ""))
            api = row.api
            self.tree.insert(
                "",
                "end",
                iid=iid,
                tags=(tag, "checked") if checked and row.has_diff else (tag,),
                values=(
                    "☑" if checked else "☐",
                    row.document_no or "—",
                    row.trops_vat or "—",
                    row.trops_name or "—",
                    region_label(row.trops_region) or "—",
                    api.vat_id or "—",
                    api.name or "—",
                    region_label(api.region) if api.region else "—",
                    api.source or "—",
                    row.check_status or "—",
                    "; ".join(row.diffs) if row.diffs else "OK",
                ),
            )
        shown = len(visible)
        self.status.set(
            f"{self.report.message}  ·  prikaz {shown}"
            + (" (samo razlike)" if self.filter_var.get() == "DIFF" else "")
        )

    def _set_all(self, value: bool) -> None:
        for iid in self.tree.get_children():
            self.checked[iid] = value
        self._fill()

    def _toggle_selected(self, _event: tk.Event | None = None) -> str:
        for iid in self.tree.selection():
            self.checked[iid] = not bool(self.checked.get(iid))
        self._fill()
        return "break"

    def _click_chk(self, event: tk.Event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.tree.identify_column(event.x) != "#1":
            return None
        iid = self.tree.identify_row(event.y)
        if not iid:
            return None
        self.checked[iid] = not bool(self.checked.get(iid))
        self._fill()
        return "break"

    def _on_double(self, _event: tk.Event | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self._by_iid.get(selection[0])
        if row and row.party_id and self.on_open_party:
            self.on_open_party(int(row.party_id))

    def _apply_selected(self) -> None:
        if self.db is None:
            messagebox.showinfo(self.title(), "Ni odprte baze.", parent=self)
            return
        selected = [self._by_iid[iid] for iid, flag in self.checked.items() if flag and iid in self._by_iid]
        selected = [row for row in selected if row.has_diff]
        if not selected:
            messagebox.showinfo(
                self.title(),
                "Označi vrstice z razliko, nato Uporabi API.",
                parent=self,
            )
            return
        update_name = bool(self.update_name_var.get())
        errors: list[str] = []
        ok = 0
        for row in selected:
            err = apply_api_to_party(self.db, row, update_name=update_name)
            if err:
                errors.append(f"{row.document_no or row.trops_name}: {err}")
            else:
                ok += 1
                row.trops_region = row.api.region or row.trops_region
                row.trops_country = row.api.country or row.trops_country
                if row.api.vat_id:
                    row.trops_vat = row.api.vat_id
                if update_name and row.api.name:
                    row.trops_name = row.api.name
                row.diffs = []
        self._fill()
        if self.on_applied:
            self.on_applied()
        extra = ("\n\n" + "\n".join(errors[:8])) if errors else ""
        if len(errors) > 8:
            extra += f"\n… še {len(errors) - 8}"
        messagebox.showinfo(
            self.title(),
            f"Popravljeno strank: {ok}."
            + (f"\nNeuspešno: {len(errors)}.{extra}" if errors else ""),
            parent=self,
        )

    def _force_refresh(self) -> None:
        cb = self.on_force_refresh
        self.destroy()
        if cb:
            cb()

    def _send_irregularities(self) -> None:
        from trops_studio.companies import company_name
        from trops_studio.ddvo_actions import GMAIL_SMTP_CC, client_email_to
        from trops_studio.ui.period import format_si_date
        from trops_studio.ui.smtp_compose_dialog import SmtpComposeDialog
        from trops_studio.vat_api_check import (
            format_vat_irregularities_email,
            irregularity_rows,
            is_sp_vs_fo_row,
        )

        checked = [
            self._by_iid[iid]
            for iid, flag in self.checked.items()
            if flag and iid in self._by_iid
        ]
        if self.report.mode == "fo":
            checked = [row for row in checked if is_sp_vs_fo_row(row) or row.has_diff]
            rows = checked or irregularity_rows(self.report)
        else:
            checked = [row for row in checked if row.has_diff]
            rows = checked or irregularity_rows(self.report)
        if not rows:
            messagebox.showinfo(
                "Pošlji seznam nepravilnosti",
                "Ni primerov s.p. / 8-mestna davčna brez SI (AJPES firma) za pošiljanje."
                if self.report.mode == "fo"
                else "Ni razlik za pošiljanje.",
                parent=self,
            )
            return
        to_addr = client_email_to(self.company)
        if not to_addr:
            messagebox.showerror(
                "Pošlji seznam nepravilnosti",
                "Manjka e-pošta stranke (polje Email v evidenci firm).",
                parent=self,
            )
            return
        period = ""
        if self.period_from and self.period_to:
            period = f"{format_si_date(self.period_from)} – {format_si_date(self.period_to)}"
        subject, body = format_vat_irregularities_email(
            rows,
            book=self.report.book,
            mode=self.report.mode,
            company_name=company_name(self.company or {}),
            period_label=period,
        )
        SmtpComposeDialog(
            self,
            title="Pošlji seznam nepravilnosti — predogled SMTP",
            to_addr=to_addr,
            cc=GMAIL_SMTP_CC,
            subject=subject,
            body_html=body,
            on_sent=lambda note: self.status.set(note.split("\n", 1)[0]),
        )
