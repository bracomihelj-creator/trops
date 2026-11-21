from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence
from webbrowser import open as open_url

from trops_studio.ajpes_client import eprs_url_by_tax, lookup_si_company
from trops_studio.db import Database
from trops_studio.minimax_parties import (
    customer_tax_digits,
    find_customer_by_code,
    import_minimax_customer_to_sql,
    open_minimax_client,
    push_party_to_minimax,
    search_customers_by_name,
    taxes_match_party_and_customer,
)
from trops_studio.money import (
    infer_country_code,
    national_tax_id,
    normalize_text,
    normalize_vat_id,
    sanitize_display_text,
    tax_digits,
)
from trops_studio.party_web_ai import (
    AI_SETTINGS_PATH,
    ensure_ai_settings_template,
    lookup_party_on_web,
)
from trops_studio.parties_ensure import absorb_duplicate_parties, link_journal_rows_to_party
from trops_studio.sync_state import SYNC_READY, SYNC_SYNCED
from trops_studio.ui.tooltip import ToolTip
from trops_studio.vies_client import (
    EU_VAT_COUNTRIES,
    VIES_WEB_URL,
    check_eu_vat,
    is_eu_vat_id,
    split_eu_vat,
)


class StrankeDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        db: Database,
        *,
        party: dict[str, Any] | None = None,
        org_id: str = "",
        on_saved: Callable[[], None] | None = None,
        auto_vies: bool = False,
        name_aliases: Sequence[str] | None = None,
    ) -> None:
        super().__init__(master)
        self.db = db
        self.org_id = str(org_id or "").strip()
        self.on_saved = on_saved
        self.party_id = int(party["id"]) if party and party.get("id") else None
        self._saved_once = bool(self.party_id)
        self._auto_vies = bool(auto_vies)
        self.title("Nova stranka" if not self.party_id else f"Stranka #{self.party_id}")
        self.transient(master)
        self.grab_set()
        self.geometry("780x780")
        self.minsize(700, 660)

        seed = party or {}
        raw_name = str(seed.get("name") or "")
        # Skrij notranji razločevalni priponk [MM:…] / [DS:…] v obrazcu
        display_name = re.sub(r"\s*\[(?:MM|DS):[^\]]+\]\s*$", "", raw_name).strip() or raw_name
        # Alias nazivi iz IR/PR / združenih dvojnikov (za odstranitev s seznama manjkajočih)
        self._name_aliases: list[str] = []
        for alias in name_aliases or ():
            text = sanitize_display_text(alias)
            if text and text not in self._name_aliases:
                self._name_aliases.append(text)
        if display_name and display_name not in self._name_aliases:
            self._name_aliases.append(display_name)
        self.vars = {
            "vat_id": tk.StringVar(value=str(seed.get("vat_id") or "")),
            "tax_number": tk.StringVar(value=str(seed.get("tax_number") or "")),
            "country": tk.StringVar(value=str(seed.get("country") or "SI")),
            "name": tk.StringVar(value=display_name),
            "address": tk.StringVar(value=str(seed.get("address") or "")),
            "postal_code": tk.StringVar(value=str(seed.get("postal_code") or "")),
            "city": tk.StringVar(value=str(seed.get("city") or "")),
            "registration_no": tk.StringVar(value=str(seed.get("registration_no") or "")),
            "ajpes_code": tk.StringVar(value=str(seed.get("ajpes_code") or "")),
            "email": tk.StringVar(value=str(seed.get("email") or "")),
            "phone": tk.StringVar(value=str(seed.get("phone") or "")),
            "iban": tk.StringVar(value=str(seed.get("iban") or "")),
            "notes": tk.StringVar(value=str(seed.get("notes") or "")),
            "minimax_code": tk.StringVar(value=str(seed.get("minimax_code") or "")),
        }
        self.is_foreign = tk.BooleanVar(value=bool(seed.get("is_foreign")))
        self.party_kind = tk.StringVar(
            value=self._infer_party_kind(
                vat_id=seed.get("vat_id"),
                tax_number=seed.get("tax_number"),
                country=seed.get("country"),
                is_foreign=bool(seed.get("is_foreign")),
                name=seed.get("name"),
            )
        )
        self._kind_updating = False
        self.sync_label = tk.StringVar(value="")
        self.status = tk.StringVar(value="")

        form = ttk.Frame(self, padding=16)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        # Status shranjevanja (vedno viden)
        banner = ttk.Frame(form)
        banner.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(banner, textvariable=self.sync_label).pack(anchor="w")

        # Vrsta stranke — takoj zgoraj (SI / EU / tretja / ni zavezanec)
        kind_box = ttk.LabelFrame(form, text="Vrsta stranke (DDV / regija)", padding=8)
        kind_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        for text, val in (
            ("SI zavezanec", "SI"),
            ("EU", "EU"),
            ("Tretja država", "THIRD"),
            ("Ni zavezanec", "NONE"),
        ):
            ttk.Radiobutton(
                kind_box,
                text=text,
                variable=self.party_kind,
                value=val,
                command=self._on_party_kind,
            ).pack(side="left", padx=(0, 14))
        ToolTip(
            kind_box,
            "SI — AJPES + domači DDV\n"
            "EU — tujec z EU ID za DDV (VIES)\n"
            "Tretja država — zunaj EU; ID za DDV obvezen (FURS), npr. IL001\n"
            "Ni zavezanec — brez DDV (Minimax SubjectToVAT=N)",
        )

        rows = [
            ("Davčna / ID za DDV", "vat_id"),
            ("Davčna / lokalni ID", "tax_number"),
            ("Država", "country"),
            ("Naziv", "name"),
            ("Naslov", "address"),
            ("Pošta", "postal_code"),
            ("Kraj", "city"),
            ("Matična", "registration_no"),
            ("AJPES šifra", "ajpes_code"),
            ("E-pošta", "email"),
            ("Telefon", "phone"),
            ("TRR / IBAN", "iban"),
            ("Opombe", "notes"),
            ("Minimax šifra", "minimax_code"),
        ]
        field_start = 2
        self._entries: dict[str, ttk.Entry] = {}
        for index, (label, key) in enumerate(rows, start=field_start):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=4, padx=(0, 10))
            entry = ttk.Entry(form, textvariable=self.vars[key])
            entry.grid(row=index, column=1, sticky="ew", pady=4)
            self._entries[key] = entry
            if key == "minimax_code":
                ToolTip(
                    entry,
                    "Ročni vnos Minimax šifre.\n"
                    "Ob »Poveži / posodobi Minimax«: če šifra obstaja, preveri davčno —\n"
                    "ujemanje → ne doda nove, lahko posodobi podatke.",
                )
            if key == "iban":
                ToolTip(entry, "TRR / IBAN iz AJPES eRTR (kot EvidencaFirm).")
            if key == "tax_number":
                ToolTip(
                    entry,
                    "Lokalna davčna / nacionalni del ID za DDV.\n"
                    "Lahko vsebuje črke (npr. IE: 6388047V, CY: …T).\n"
                    "VIES: Država + ta vrednost → npr. IE6388047V.",
                )

        # VIES ob DDV
        vies_row = ttk.Frame(form)
        vies_row.grid(row=field_start, column=2, sticky="nw", padx=(8, 0), pady=4)
        btn_vies = ttk.Button(vies_row, text="VIES preveri", command=self.check_vies)
        btn_vies.pack(anchor="w")
        ToolTip(btn_vies, "Preveri EU ID za DDV prek VIES API (brez brskalnika).\nDržava + lokalni ID (tudi s črko): IE + 6388047V → IE6388047V.")
        btn_vies_web = ttk.Button(vies_row, text="VIES splet", command=self.open_vies_web)
        btn_vies_web.pack(anchor="w", pady=(4, 0))
        ToolTip(btn_vies_web, f"Odpri spletni VIES obrazec:\n{VIES_WEB_URL}")

        # Najdi na spletu + Minimax iskanje ob Nazivu
        name_row_index = next(i for i, (_lab, key) in enumerate(rows, start=field_start) if key == "name")
        web_side = ttk.Frame(form)
        web_side.grid(row=name_row_index, column=2, sticky="nw", padx=(8, 0), pady=4)
        self.web_btn = ttk.Button(web_side, text="Najdi na spletu", command=self.find_on_web)
        self.web_btn.pack(anchor="w")
        ToolTip(
            self.web_btn,
            "Spletno iskanje + AI → predlaga naziv, naslov, pošto, kraj …\n"
            f"AI ključ: {AI_SETTINGS_PATH.name} ali OPENAI_API_KEY.\n"
            "Vedno preveri pred shranjevanjem.",
        )
        btn_mm_search = ttk.Button(
            web_side, text="Išči v Minimax", style="Accent.TButton", command=self.search_minimax_name
        )
        btn_mm_search.pack(anchor="w", pady=(4, 0))
        ToolTip(
            btn_mm_search,
            "Označi del naziva (npr. Open AI) in išči v Minimax API.\n"
            "Izberi zadetek → prepiše obrazec in shrani v SQL.",
        )

        # Preveri MM šifro
        mm_row_index = next(i for i, (_lab, key) in enumerate(rows, start=field_start) if key == "minimax_code")
        mm_side = ttk.Frame(form)
        mm_side.grid(row=mm_row_index, column=2, sticky="nw", padx=(8, 0), pady=4)
        btn_check_mm = ttk.Button(mm_side, text="Preveri šifro", command=self.check_minimax_code)
        btn_check_mm.pack(anchor="w")
        ToolTip(btn_check_mm, "Poišči šifro v Minimaxu in primerjaj davčno.")

        chk_row = field_start + len(rows)
        ttk.Checkbutton(
            form,
            text="Tuja stranka (brez AJPES — ročni vnos)",
            variable=self.is_foreign,
            command=self._on_foreign_toggle,
        ).grid(row=chk_row, column=0, columnspan=2, sticky="w", pady=(6, 0))

        actions = ttk.Frame(form)
        actions.grid(row=chk_row + 1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self.ajpes_btn = ttk.Button(actions, text="AJPES (opcijsko)", command=self.fetch_ajpes)
        self.ajpes_btn.pack(side="left")
        self.mm_btn = ttk.Button(
            actions,
            text="Prenesi / poveži Minimax",
            style="Accent.TButton",
            command=self.push_minimax,
        )
        self.mm_btn.pack(side="left", padx=(12, 0))
        ToolTip(
            self.mm_btn,
            "Shrani v SQL, nato:\n"
            "• SI z davčno → addbytaxnumber (Minimax iz javne baze, tudi TRR)\n"
            "• MM šifra obstaja + davčna OK → poveži (osvežitev: MM Posodobi podatke stranke)\n"
            "• MM šifra + davčna ≠ → napaka\n"
            "• EU/tretja po AI+SQL → prenesi v Minimax API",
        )

        ttk.Button(actions, text="Shrani", style="Success.TButton", command=self.save).pack(side="right")
        ttk.Button(actions, text="Zapri", command=self.destroy).pack(side="right", padx=(0, 8))

        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", padding=(16, 0, 16, 12)).pack(fill="x")
        self._on_party_kind()
        self._refresh_save_banner()
        if self._auto_vies:
            self.after(200, self.check_vies)

    @staticmethod
    def _infer_party_kind(
        *,
        vat_id: Any = "",
        tax_number: Any = "",
        country: Any = "",
        is_foreign: bool = False,
        name: Any = "",
    ) -> str:
        from trops_studio.pr_list_view import infer_party_kind

        return infer_party_kind(
            vat_id=vat_id,
            tax_number=tax_number,
            country=country,
            is_foreign=is_foreign,
            name=name,
        )

    def _sync_party_kind_from_fields(self) -> None:
        if self._kind_updating:
            return
        kind = self._infer_party_kind(
            vat_id=self.vars["vat_id"].get(),
            tax_number=self.vars["tax_number"].get(),
            country=self.vars["country"].get(),
            is_foreign=bool(self.is_foreign.get()),
            name=self.vars["name"].get(),
        )
        self._kind_updating = True
        try:
            self.party_kind.set(kind)
        finally:
            self._kind_updating = False

    def _on_party_kind(self) -> None:
        if self._kind_updating:
            return
        kind = self.party_kind.get() or "SI"
        self._kind_updating = True
        try:
            if kind == "SI":
                self.is_foreign.set(False)
                self.vars["country"].set("SI")
                self.ajpes_btn.configure(state="normal")
                if not self._saved_once:
                    self.status.set("SI zavezanec — uporabi AJPES po davčni.")
            elif kind == "EU":
                self.is_foreign.set(True)
                cc = normalize_text(self.vars["country"].get())[:2].upper()
                vat = normalize_vat_id(self.vars["vat_id"].get())
                if cc in ("", "SI"):
                    if len(vat) >= 2 and vat[:2] in EU_VAT_COUNTRIES and vat[:2] != "SI":
                        self.vars["country"].set(vat[:2])
                    else:
                        self.vars["country"].set("")
                self.ajpes_btn.configure(state="disabled")
                if not self._saved_once:
                    self.status.set("EU stranka — ID za DDV preveri z VIES.")
            elif kind == "THIRD":
                self.is_foreign.set(True)
                if normalize_text(self.vars["country"].get())[:2].upper() == "SI":
                    self.vars["country"].set("")
                self.ajpes_btn.configure(state="disabled")
                # FURS: ID za DDV (npr. IL001) — predlagaj država+001, če prazno
                cc = normalize_text(self.vars["country"].get())[:2].upper()
                vat = normalize_vat_id(self.vars["vat_id"].get())
                if cc and cc != "SI" and not vat:
                    self.vars["vat_id"].set(f"{cc}001")
                if not self._saved_once:
                    self.status.set(
                        "Tretja država — ID za DDV obvezen (FURS), npr. IL001. Brez VIES."
                    )
            else:  # NONE
                self.is_foreign.set(False)
                if not normalize_text(self.vars["country"].get()):
                    self.vars["country"].set("SI")
                self.ajpes_btn.configure(state="normal")
                if not self._saved_once:
                    self.status.set(
                        "Ni DDV zavezanec — davčna lahko prazna (Minimax SubjectToVAT=N)."
                    )
        finally:
            self._kind_updating = False

    def _refresh_save_banner(self) -> None:
        mm = normalize_text(self.vars["minimax_code"].get())
        if self.party_id and self._saved_once:
            if mm:
                self.sync_label.set(f"✓ Shranjeno v SQL (id={self.party_id}) · Minimax šifra {mm}")
            else:
                self.sync_label.set(
                    f"✓ Shranjeno v SQL (id={self.party_id}) · še ni v Minimaxu — uporabi »Prenesi v Minimax«"
                )
            self.title(f"Stranka #{self.party_id} — shranjena")
        elif self.party_id:
            self.sync_label.set(f"Stranka #{self.party_id}" + (f" · MM {mm}" if mm else " · brez MM šifre"))
            self.title(f"Stranka #{self.party_id}")
        else:
            self.sync_label.set("Nova stranka — še ni shranjena. Izpolni in klikni Shrani.")
            self.title("Nova stranka")
        self.mm_btn.configure(state="normal" if self.org_id else "disabled")

    def _on_foreign_toggle(self) -> None:
        foreign = self.is_foreign.get()
        self.ajpes_btn.configure(state="disabled" if foreign else "normal")
        if foreign:
            inferred = infer_country_code(
                postal_code=self.vars["postal_code"].get(),
                address=self.vars["address"].get(),
                city=self.vars["city"].get(),
                vat_id=self.vars["vat_id"].get(),
                country="",  # samo iz naslova
            )
            if inferred == "SI":
                # Naslov je SI — »tuja« ni smiselna
                self.after_idle(lambda: self._force_si_domestic())
                return
            if self.vars["country"].get().strip().upper() == "SI":
                self.vars["country"].set("")
        elif not self.vars["country"].get().strip():
            self.vars["country"].set("SI")
        self._sync_party_kind_from_fields()
        if not self._saved_once:
            self.status.set(
                "Tuja stranka — izpolni obrazec ročno. EU DDV preveri z VIES."
                if foreign
                else "SI stranka — uporabi AJPES po davčni (če je zavezanec)."
            )

    def _force_si_domestic(self) -> None:
        self.is_foreign.set(False)
        self.vars["country"].set("SI")
        self.ajpes_btn.configure(state="normal")
        self._sync_party_kind_from_fields()
        self.status.set("Naslov kaže na SI — odznačen »Tuja stranka«.")

    def _apply_country_from_address(self) -> str:
        """Nastavi državo iz naslova/pošte; SI → ni tuja."""
        inferred = infer_country_code(
            country=self.vars["country"].get(),
            postal_code=self.vars["postal_code"].get(),
            address=self.vars["address"].get(),
            city=self.vars["city"].get(),
            vat_id=self.vars["vat_id"].get() or self.vars["tax_number"].get(),
        )
        if inferred:
            self.vars["country"].set(inferred)
        if inferred == "SI":
            self.is_foreign.set(False)
            self.ajpes_btn.configure(state="normal")
        return inferred

    def open_eprs(self) -> None:
        open_url(eprs_url_by_tax(self.vars["vat_id"].get() or self.vars["tax_number"].get()))

    def open_vies_web(self) -> None:
        open_url(VIES_WEB_URL)

    def find_on_web(self) -> None:
        """Splet + AI → ListView z vsemi podatki → prepis v obrazec."""
        name = sanitize_display_text(self.vars["name"].get())
        vat = normalize_vat_id(self.vars["vat_id"].get() or self.vars["tax_number"].get())
        country = normalize_text(self.vars["country"].get())[:2].upper()
        if not name and not vat:
            messagebox.showinfo("Najdi na spletu", "Vnesi naziv ali ID za DDV.", parent=self)
            return
        ensure_ai_settings_template()
        self.web_btn.configure(state="disabled")
        self.status.set("Iščem na spletu + VIES + AI …")
        self.update_idletasks()

        def worker() -> None:
            err: Exception | None = None
            result = None
            try:
                result = lookup_party_on_web(name=name, vat_id=vat, country=country, check_vies=True)
            except Exception as exc:
                err = exc

            def finish() -> None:
                from trops_studio.ui.party_web_results_dialog import PartyWebResultsDialog

                self.web_btn.configure(state="normal")
                if err is not None:
                    self.status.set("Iskanje ni uspelo.")
                    messagebox.showerror("Najdi na spletu", str(err), parent=self)
                    return
                assert result is not None
                self.status.set(result.message)

                def _is_blank(val: str) -> bool:
                    text = sanitize_display_text(val).strip()
                    return not text or text in {"-", "—", ".", "n/a", "N/A"}

                def _name_should_replace(current: str, proposed: str) -> bool:
                    """VIES/daljši uradni naziv brez vprašanja; sicer potrdi."""
                    if not current or _is_blank(current):
                        return True
                    if current.casefold() == proposed.casefold():
                        return True
                    cur_cf, prop_cf = current.casefold(), proposed.casefold()
                    # T-SHIRT MAKERS → T-SHIRT MAKERS S.R.L.
                    if cur_cf in prop_cf or prop_cf.startswith(cur_cf):
                        return True
                    return messagebox.askyesno(
                        "Naziv",
                        f"Obstoječi naziv:\n{current}\n\nPredlog:\n{proposed}\n\nZamenjam?",
                        parent=self,
                    )

                def apply_updates(updates: dict[str, str]) -> None:
                    for key, value in updates.items():
                        if key not in self.vars:
                            continue
                        value = sanitize_display_text(str(value or "")) if key != "country" else str(value or "").strip().upper()
                        if not value:
                            continue
                        current = (
                            sanitize_display_text(self.vars[key].get())
                            if key != "country"
                            else self.vars[key].get().strip()
                        )
                        if key == "name":
                            if not _name_should_replace(current, value):
                                continue
                        elif current and not _is_blank(current) and current.casefold() != value.casefold():
                            # Neprazno polje — prepiši, če je predlog boljši (naslov iz VIES)
                            if key in {"address", "postal_code", "city", "vat_id", "tax_number", "country"}:
                                pass  # vedno prepiši iz spleta/VIES
                            else:
                                continue
                        self.vars[key].set(value)
                    # Država iz DDV / naslova; EU / tretja → vrsta stranke
                    country = self._apply_country_from_address()
                    vat = normalize_vat_id(self.vars["vat_id"].get())
                    if not country and len(vat) >= 2 and vat[:2].isalpha():
                        country = vat[:2]
                        self.vars["country"].set(country)
                    if vat and len(vat) > 2 and vat[:2].isalpha():
                        if _is_blank(self.vars["tax_number"].get()):
                            self.vars["tax_number"].set(vat[2:])
                    if country and country != "SI":
                        self.is_foreign.set(True)
                        self.ajpes_btn.configure(state="disabled")
                    self._sync_party_kind_from_fields()
                    # Opombe: samo dodatki (ne podvajaj sedeža, če je že v Naslov)
                    bits: list[str] = []
                    if result.tax_file:
                        bits.append(f"Davčna datoteka: {result.tax_file}")
                    hq = sanitize_display_text(result.headquarters)
                    addr = sanitize_display_text(self.vars["address"].get())
                    if hq and hq.casefold() not in addr.casefold() and _is_blank(addr):
                        bits.append(f"Sedež: {hq}")
                    if result.vies_status:
                        bits.append(f"VIES: {result.vies_status}")
                    if result.website:
                        bits.append(result.website)
                    note_extra = " · ".join(bits) if bits else ""
                    if note_extra:
                        notes = sanitize_display_text(self.vars["notes"].get())
                        if note_extra not in notes:
                            self.vars["notes"].set((notes + " · " if notes else "") + note_extra)
                    kind = self.party_kind.get()
                    self.status.set(
                        f"Prepisano iz VIES/spleta · vrsta: {kind} — preveri in shrani."
                    )

                PartyWebResultsDialog(
                    self,
                    result,
                    query_name=name,
                    query_vat=vat,
                    query_country=country,
                    on_apply=apply_updates,
                )

            try:
                self.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True, name="party-web-ai").start()

    def _name_search_query(self) -> str:
        """Označen del naziva, sicer celoten naziv."""
        entry = self._entries.get("name")
        if entry is not None:
            try:
                if entry.selection_present():
                    sel = str(entry.selection_get() or "").strip()
                    if sel:
                        return sel
            except tk.TclError:
                pass
        return sanitize_display_text(self.vars["name"].get())

    def search_minimax_name(self) -> None:
        """Išči v Minimax API po označenem delu naziva → prepis v obrazec + SQL."""
        if not self.org_id:
            messagebox.showerror("Minimax", "Manjka Org_ID — izberi podjetje.", parent=self)
            return
        query = self._name_search_query()
        if len(query) < 2:
            messagebox.showinfo(
                "Minimax iskanje",
                "Označi del naziva (npr. Open AI) ali vnesi vsaj 2 znaka.",
                parent=self,
            )
            return
        self.status.set(f"Minimax API: iščem »{query}« …")
        self.update_idletasks()
        try:
            client = open_minimax_client(self.org_id)
            hits = search_customers_by_name(client, query)
        except Exception as exc:
            messagebox.showerror("Minimax", str(exc), parent=self)
            self.status.set("Minimax iskanje ni uspelo.")
            return
        if not hits:
            self.status.set(f"Minimax: ni zadetkov za »{query}«.")
            messagebox.showinfo(
                "Minimax iskanje",
                f"Ni strank za »{query}«.\n"
                "Poskusi krajši niz (npr. samo Open) ali drug del naziva.",
                parent=self,
            )
            return
        chosen = hits[0] if len(hits) == 1 else self._pick_minimax_hit(hits, query)
        if not chosen:
            self.status.set("Minimax iskanje preklicano.")
            return
        try:
            # Ohrani izvirni naziv iz IR/PR pred prepisom iz Minimaxa
            prior_name = sanitize_display_text(self.vars["name"].get())
            if prior_name and prior_name not in self._name_aliases:
                self._name_aliases.append(prior_name)
            if query and query not in self._name_aliases:
                self._name_aliases.append(query)
            party_id, party = import_minimax_customer_to_sql(
                self.db,
                chosen,
                party_id=self.party_id,
            )
        except Exception as exc:
            messagebox.showerror("SQL", str(exc), parent=self)
            self.status.set("Prepis v SQL ni uspel.")
            return
        self.party_id = int(party_id)
        self._saved_once = True
        self._apply_party_dict(party)
        linked = self._link_journals_after_minimax()
        self._sync_journal_vat_from_party()
        code = normalize_text(party.get("minimax_code"))
        try:
            from trops_studio.party_aliases import remember_party_alias

            remember_party_alias(
                query,
                canonical=str(party.get("name") or ""),
                minimax_code=code,
            )
            for alias in self._name_aliases:
                remember_party_alias(
                    alias,
                    canonical=str(party.get("name") or ""),
                    minimax_code=code,
                )
        except Exception:
            pass
        self.status.set(
            f"Minimax → SQL: {sanitize_display_text(party.get('name'))}"
            + (f" · šifra {code}" if code else "")
            + f" · id={self.party_id}"
            + (f" · povezanih listin {linked}" if linked else "")
        )
        self._refresh_save_banner()
        if self.on_saved:
            self.on_saved()
        messagebox.showinfo(
            "Minimax → SQL",
            f"Najdeno in shranjeno.\n\n"
            f"Naziv: {sanitize_display_text(party.get('name')) or '—'}\n"
            f"MM šifra: {code or '—'}\n"
            f"ID za DDV: {party.get('vat_id') or '—'}\n"
            f"Država: {party.get('country') or '—'}\n"
            f"SQL id: {self.party_id}"
            + (f"\nPovezanih IR/PR: {linked}" if linked else "")
            + "\n\nStranka izpade s seznama manjkajočih (Osveži).",
            parent=self,
        )

    def _pick_minimax_hit(self, hits: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
        """ListView izbira med Minimax zadetki."""
        dlg = tk.Toplevel(self)
        dlg.title(f"Minimax zadetki — »{query}«")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("720x380")
        ttk.Label(
            dlg,
            text=f"{len(hits)} zadetkov — dvoklik ali »Uporabi« za prepis v SQL.",
            style="Muted.TLabel",
            padding=(12, 10, 12, 4),
        ).pack(anchor="w")
        frame = ttk.Frame(dlg, padding=(12, 0, 12, 8))
        frame.pack(fill="both", expand=True)
        cols = ("code", "name", "tax", "country", "city")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ybar.set)
        tree.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        headings = {
            "code": ("MM šifra", 80),
            "name": ("Naziv", 280),
            "tax": ("Davčna", 100),
            "country": ("Drž.", 50),
            "city": ("Kraj", 120),
        }
        for key, (title, width) in headings.items():
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=40)
        by_iid: dict[str, dict[str, Any]] = {}
        for i, row in enumerate(hits[:80]):
            code = str(row.get("Code") or "")
            name = sanitize_display_text(row.get("Name") or "")
            tax = str(row.get("TaxNumber") or row.get("VATIdentificationNumber") or "")
            country = ""
            cobj = row.get("Country")
            if isinstance(cobj, dict):
                country = str(cobj.get("Name") or cobj.get("Code") or "")[:2]
            city = sanitize_display_text(row.get("City") or "")
            iid = f"h{i}"
            by_iid[iid] = row
            tree.insert("", "end", iid=iid, values=(code, name, tax, country, city))
        chosen: dict[str, Any] = {"row": None}

        def accept(_event: object | None = None) -> None:
            sel = tree.focus() or (tree.selection()[0] if tree.selection() else "")
            if not sel or sel not in by_iid:
                messagebox.showinfo("Minimax", "Izberi vrstico.", parent=dlg)
                return
            chosen["row"] = by_iid[sel]
            dlg.destroy()

        tree.bind("<Double-1>", accept)
        bar = ttk.Frame(dlg, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="Uporabi", style="Success.TButton", command=accept).pack(side="right")
        ttk.Button(bar, text="Prekliči", command=dlg.destroy).pack(side="right", padx=(0, 8))
        if tree.get_children():
            first = tree.get_children()[0]
            tree.selection_set(first)
            tree.focus(first)
        self.wait_window(dlg)
        return chosen["row"]

    def _apply_party_dict(self, party: dict[str, Any]) -> None:
        """Napolni obrazec iz SQL/Minimax party dict."""
        raw_name = str(party.get("name") or "")
        display_name = re.sub(r"\s*\[(?:MM|DS):[^\]]+\]\s*$", "", raw_name).strip() or raw_name
        mapping = {
            "vat_id": party.get("vat_id") or "",
            "tax_number": party.get("tax_number") or "",
            "country": party.get("country") or "",
            "name": display_name,
            "address": party.get("address") or "",
            "postal_code": party.get("postal_code") or "",
            "city": party.get("city") or "",
            "registration_no": party.get("registration_no") or "",
            "ajpes_code": party.get("ajpes_code") or "",
            "email": party.get("email") or "",
            "phone": party.get("phone") or "",
            "iban": party.get("iban") or "",
            "notes": party.get("notes") or "",
            "minimax_code": party.get("minimax_code") or "",
        }
        for key, value in mapping.items():
            if key in self.vars:
                self.vars[key].set(str(value or ""))
        country = normalize_text(mapping["country"])[:2].upper()
        self.is_foreign.set(bool(party.get("is_foreign")) or (country not in {"", "SI"}))
        self.ajpes_btn.configure(state="disabled" if self.is_foreign.get() else "normal")
        self._sync_party_kind_from_fields()

    def _link_journals_after_minimax(self) -> int:
        """Poveži IR/PR + odstrani SQL dvojnike → izpade s seznama manjkajočih."""
        if not self.party_id:
            return 0
        code = normalize_text(self.vars["minimax_code"].get())
        if not code:
            fresh = self.db.get_party(int(self.party_id)) or {}
            code = normalize_text(fresh.get("minimax_code"))
            if code:
                self.vars["minimax_code"].set(code)
            else:
                return 0
        aliases = list(self._name_aliases)
        cur = sanitize_display_text(self.vars["name"].get())
        if cur and cur not in aliases:
            aliases.append(cur)
        # Naziv v SQL (lahko z [MM:…]) — tudi za ujemanje
        try:
            stored = sanitize_display_text(
                (self.db.get_party(int(self.party_id)) or {}).get("name")
            )
            if stored and stored not in aliases:
                aliases.append(stored)
        except Exception:
            pass
        linked = 0
        try:
            linked = link_journal_rows_to_party(self.db, int(self.party_id), names=aliases)
        except Exception:
            linked = 0
        try:
            absorb_duplicate_parties(self.db, int(self.party_id))
        except Exception:
            pass
        return linked

    def _sync_journal_vat_from_party(self) -> int:
        """Po prepisu iz Minimaxa: na IR/PR te stranke vpiši ID za DDV."""
        if not self.party_id:
            return 0
        party = self.db.get_party(int(self.party_id)) or {}
        vat = normalize_vat_id(party.get("vat_id"))
        if not vat:
            return 0
        updated = 0
        pid = int(self.party_id)
        for row in self.db.list_pr():
            if int(row.get("party_id") or 0) != pid:
                continue
            old = normalize_vat_id(row.get("vat_id"))
            if old == vat:
                continue
            if old and old[:2].isalpha() and not old.startswith("SI"):
                continue
            payload = dict(row)
            payload["vat_id"] = vat
            self.db.upsert_pr(payload, int(row["id"]))
            updated += 1
        for row in self.db.list_ir():
            if int(row.get("party_id") or 0) != pid:
                continue
            old = normalize_vat_id(row.get("vat_id"))
            if old == vat:
                continue
            if old and old[:2].isalpha() and not old.startswith("SI"):
                continue
            payload = dict(row)
            payload["vat_id"] = vat
            self.db.upsert_ir(payload, int(row["id"]))
            updated += 1
        return updated

    def check_vies(self) -> None:
        """Samo VIES API — ne odpira brskalnika (za splet uporabi »VIES splet«)."""
        vat = normalize_vat_id(self.vars["vat_id"].get())
        country = normalize_text(self.vars["country"].get())[:2].upper()
        # Nacionalni del z morebitnimi črkami (IE6388047V, ne samo cifre)
        tax_body = national_tax_id(
            self.vars["tax_number"].get() or vat,
            country=country,
        )
        if not vat and tax_body:
            cc = country if country in EU_VAT_COUNTRIES else ""
            if not cc and len(tax_digits(tax_body)) == 8 and tax_body.isdigit():
                cc = "SI"
            if cc:
                vat = f"{cc}{tax_body}"
                country = cc
                # Shrani lokalni del z črkami (ne stripaj)
                if not sanitize_display_text(self.vars["tax_number"].get()):
                    self.vars["tax_number"].set(tax_body)
        if not vat:
            # morda je v tax_number že polni IE…
            maybe = normalize_vat_id(self.vars["tax_number"].get())
            if is_eu_vat_id(maybe):
                vat = maybe
        country_from_vat, number = split_eu_vat(vat)
        if country_from_vat and not self.vars["country"].get().strip():
            self.vars["country"].set(country_from_vat)
        if not is_eu_vat_id(vat):
            self.status.set(
                "Za VIES: ID za DDV (IE6388047V) ali Država + lokalni ID (IE + 6388047V)."
            )
            messagebox.showinfo(
                "VIES",
                "Vnesi EU ID za DDV, npr. IE6388047V / DE813161057,\n"
                "ali Država (IE) + Davčna/lokalni ID (6388047V — tudi s črko).\n\n"
                "Spletni obrazec: gumb »VIES splet«.",
                parent=self,
            )
            return
        self.status.set(f"VIES API: preverjam {country_from_vat}{number} …")
        self.update_idletasks()
        result = check_eu_vat(vat)
        self.status.set(result.message)
        # Kratka opomba v notes (brez podvajanja)
        if result.ok and result.valid:
            note_bit = result.message
        elif result.ok and result.valid is False:
            note_bit = "VIES: ni DDV zavezanec — ID za DDV prazen"
        else:
            note_bit = result.message
        notes = sanitize_display_text(self.vars["notes"].get())
        for old in (
            "VIES: Ni ID za DDV — VIES ni preverjen",
            "VIES ni preverjen",
            "Ni ID za DDV (ni nujno zavezanec) — po potrebi VIES preveri",
        ):
            notes = notes.replace(old, "").strip(" ·")
        if "VIES:" in notes.upper() or "Ni ID za DDV" in notes:
            parts = [
                p
                for p in notes.split(" · ")
                if p.strip()
                and not p.strip().upper().startswith("VIES")
                and "Ni ID za DDV" not in p
            ]
            notes = " · ".join(parts)
        self.vars["notes"].set((notes + " · " if notes else "") + note_bit)
        if not result.ok:
            messagebox.showwarning("VIES", result.message, parent=self)
            return
        if result.valid:
            full_vat = f"{result.country}{result.vat_number}"
            self.vars["vat_id"].set(full_vat)
            # Lokalni del z morebitno črko
            self.vars["tax_number"].set(result.vat_number)
            if result.name and not sanitize_display_text(self.vars["name"].get()):
                self.vars["name"].set(sanitize_display_text(result.name))
            if result.address and not sanitize_display_text(self.vars["address"].get()):
                lines = [ln.strip() for ln in result.address.replace("\r", "\n").split("\n") if ln.strip()]
                if lines:
                    self.vars["address"].set(lines[0])
                    if len(lines) > 1 and not self.vars["city"].get().strip():
                        self.vars["city"].set(lines[-1])
            if result.country:
                self.vars["country"].set(result.country)
                if result.country != "SI":
                    self.is_foreign.set(True)
                else:
                    self.is_foreign.set(False)
            messagebox.showinfo(
                "VIES — JE V SISTEMU",
                f"{result.message}\n\n"
                f"ID: {full_vat}\n"
                f"Naziv: {result.name or '—'}\n"
                f"Naslov: {result.address or '—'}",
                parent=self,
            )
        else:
            # Ni zavezanec / ni v VIES — ne piši SI+DŠ v ID za DDV
            self.vars["vat_id"].set("")
            messagebox.showwarning(
                "VIES — NI V SISTEMU",
                f"{result.message}\n\n"
                "Ni davčni zavezanec za DDV — polje ID za DDV ostane prazno.\n"
                "Davčna (lokalni ID) ostane; v Minimax gre kot SubjectToVAT=N.",
                parent=self,
            )

    def fetch_ajpes(self) -> None:
        if self.is_foreign.get():
            messagebox.showinfo("AJPES", "Za tujce AJPES ni na voljo. Izpolni obrazec ročno / VIES.", parent=self)
            return
        self.status.set("AJPES (EvidencaFirm): ePRS + podjetje.asp + eRTR …")
        self.update_idletasks()
        result = lookup_si_company(
            self.vars["vat_id"].get() or self.vars["tax_number"].get(),
            sanitize_display_text(self.vars["name"].get()),
            entity_id=self.vars["ajpes_code"].get(),
        )
        if result.needs_login:
            self.status.set(result.message)
            messagebox.showwarning("AJPES prijava", result.message, parent=self)
            return
        if not result.ok:
            self.status.set(result.message)
            if result.candidates:
                names = "\n".join(f"• {c.get('name')} ({c.get('tax_number')})" for c in result.candidates[:8])
                messagebox.showinfo("AJPES zadetki", f"{result.message}\n\n{names}", parent=self)
            else:
                messagebox.showerror("AJPES", result.message, parent=self)
            return
        self.vars["name"].set(sanitize_display_text(result.name))
        # AJPES da davčno (cifre); ID za DDV (SI…) samo če je že eksplicitno zavezanec / VIES
        self.vars["tax_number"].set(result.tax_number)
        # Ne prepiši SI+DŠ v ID za DDV — ni vsak davčni zavezanec
        self.vars["vat_id"].set("")
        self.vars["address"].set(sanitize_display_text(result.address))
        self.vars["postal_code"].set(result.postal_code)
        self.vars["city"].set(sanitize_display_text(result.city))
        self.vars["registration_no"].set(result.registration_no)
        if result.ajpes_code:
            self.vars["ajpes_code"].set(result.ajpes_code)
        if result.email:
            self.vars["email"].set(result.email)
        if result.phone:
            self.vars["phone"].set(result.phone)
        if result.iban:
            self.vars["iban"].set(result.iban)
        elif result.ibans:
            self.vars["iban"].set(result.ibans[0])
        self.vars["country"].set("SI")
        self.is_foreign.set(False)
        notes = sanitize_display_text(self.vars["notes"].get())
        hint = "Ni ID za DDV (ni nujno zavezanec) — po potrebi VIES preveri"
        extra_bits = []
        if result.iban or result.ibans:
            n_trr = len(result.ibans) if result.ibans else 1
            extra_bits.append(f"TRR iz AJPES: {n_trr}")
        if result.email:
            extra_bits.append("e-pošta OK")
        if result.phone:
            extra_bits.append("telefon OK")
        if "Ni ID za DDV" not in notes and "VIES:" not in notes.upper():
            self.vars["notes"].set((notes + " · " if notes else "") + hint)
        bits = " · ".join(extra_bits)
        self.status.set(
            "AJPES OK — davčna, kontakt"
            + (f", {bits}" if bits else "")
            + "; ID za DDV prazen (ni samodejno SI+DŠ)."
        )

    def _payload(self) -> dict[str, Any] | None:
        name = sanitize_display_text(self.vars["name"].get())
        if not name:
            messagebox.showerror("Stranka", "Naziv je obvezen.", parent=self)
            return None
        country = self._apply_country_from_address()
        kind = self.party_kind.get() or "SI"
        if kind == "SI":
            foreign = False
            self.is_foreign.set(False)
            if not country:
                country = "SI"
        elif kind in ("EU", "THIRD"):
            foreign = True
            self.is_foreign.set(True)
        elif kind == "NONE":
            foreign = False
            self.is_foreign.set(False)
            if not country:
                country = "SI"
        else:
            foreign = self.is_foreign.get()
        if country == "SI" and kind not in ("EU", "THIRD"):
            foreign = False
            self.is_foreign.set(False)
        vat = normalize_vat_id(self.vars["vat_id"].get())
        country_code = country or normalize_text(self.vars["country"].get())[:2].upper()
        if country_code == "SI" or (not foreign and not country_code):
            tax = tax_digits(self.vars["tax_number"].get() or vat)
        else:
            tax = national_tax_id(self.vars["tax_number"].get() or vat, country=country_code)
        # SI brez davčne / »Ni zavezanec« — Minimax SubjectToVAT=N
        if kind == "NONE" or (not foreign and not tax):
            self.status.set(
                "SI brez davčne → v Minimaxu kot ni zavezanec (SubjectToVAT=N). "
                "Če imaš davčno, vnesi jo ali AJPES."
            )
        existing_mm = normalize_text(self.vars["minimax_code"].get())
        # ID za DDV samo če je vpisan (ne inventiraj SI+davčna — ni vsak zavezanec)
        return {
            "vat_id": vat,
            "tax_number": tax,
            "country": country_code or ("XX" if foreign else "SI"),
            "name": name,
            "address": sanitize_display_text(self.vars["address"].get()),
            "postal_code": self.vars["postal_code"].get(),
            "city": sanitize_display_text(self.vars["city"].get()),
            "registration_no": self.vars["registration_no"].get(),
            "ajpes_code": self.vars["ajpes_code"].get(),
            "email": self.vars["email"].get(),
            "phone": self.vars["phone"].get(),
            "iban": self.vars["iban"].get(),
            "notes": self.vars["notes"].get(),
            "is_foreign": foreign,
            "source": "ajpes" if not foreign and tax else "manual",
            "minimax_code": existing_mm,
            "sync_status": SYNC_SYNCED if existing_mm else SYNC_READY,
        }

    def check_minimax_code(self) -> None:
        """Preveri ročno MM šifro v Minimaxu + ujemanje davčne."""
        if not self.org_id:
            messagebox.showerror("Minimax", "Manjka Org_ID — izberi podjetje.", parent=self)
            return
        code = normalize_text(self.vars["minimax_code"].get())
        if not code:
            messagebox.showinfo("Minimax", "Vnesi Minimax šifro.", parent=self)
            return
        self.status.set(f"Iščem šifro {code} v Minimaxu …")
        self.update_idletasks()
        try:
            client = open_minimax_client(self.org_id)
            found = find_customer_by_code(client, code)
        except Exception as exc:
            messagebox.showerror("Minimax", str(exc), parent=self)
            self.status.set("Preverjanje šifre ni uspelo.")
            return
        if not found:
            self.status.set(f"Šifra {code} ni v Minimaxu — SI jo dodaj tam, EU/tretjo prenesi po AI+SQL.")
            messagebox.showinfo(
                "Minimax šifra",
                f"Šifra »{code}« v Minimaxu ne obstaja.\n"
                "SI: dodaj stranko v Minimax. EU/tretja: po AI+SQL »Poveži / posodobi Minimax«.",
                parent=self,
            )
            return
        party_preview = {
            "vat_id": normalize_vat_id(self.vars["vat_id"].get()),
            "tax_number": tax_digits(self.vars["tax_number"].get() or self.vars["vat_id"].get()),
        }
        mm_tax = customer_tax_digits(found)
        local_tax = tax_digits(party_preview.get("tax_number") or party_preview.get("vat_id"))
        match = taxes_match_party_and_customer(party_preview, found)
        mm_name = sanitize_display_text(found.get("Name") or found.get("name"))
        self.status.set(
            f"Šifra {code} najdena · davčna {'OK' if match else 'NE UJEMA'} "
            f"(SQL {local_tax or '—'} / MM {mm_tax or '—'})"
        )
        if match:
            messagebox.showinfo(
                "Minimax šifra — OK",
                f"Šifra {code} obstaja.\n"
                f"Naziv v MM: {mm_name or '—'}\n"
                f"Davčna: SQL {local_tax or '—'} = MM {mm_tax or '—'}\n\n"
                "Ne bo dodana nova — lahko posodobiš podatke z gumbom spodaj.",
                parent=self,
            )
        else:
            messagebox.showwarning(
                "Minimax šifra — davčna ≠",
                f"Šifra {code} obstaja, a davčna se ne ujema.\n\n"
                f"SQL: {local_tax or '—'}\n"
                f"Minimax: {mm_tax or '—'}\n"
                f"Naziv MM: {mm_name or '—'}\n\n"
                "Nova stranka se ne bo dodala. Popravi davčno ali šifro.",
                parent=self,
            )

    def save(self, *, quiet: bool = False) -> bool:
        payload = self._payload()
        if not payload:
            return False
        party_id = self.db.upsert_party(payload, self.party_id)
        self.party_id = party_id
        self._saved_once = True
        # Osveži MM šifro iz baze
        fresh = self.db.get_party(party_id) or {}
        self.vars["minimax_code"].set(str(fresh.get("minimax_code") or ""))
        linked = 0
        if normalize_text(self.vars["minimax_code"].get()):
            # Po shramba v SQL: poveži IR/PR (tudi alias nazive z listine)
            linked = self._link_journals_after_minimax()
        self._refresh_save_banner()
        self.status.set(
            f"Shranjeno v SQLite (id={party_id})"
            + (f" · povezanih listin {linked}" if linked else "")
            + "."
        )
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass
        if not quiet:
            mm = normalize_text(self.vars["minimax_code"].get())
            messagebox.showinfo(
                "Shranjeno",
                f"Stranka je shranjena v SQLite.\n\n"
                f"ID: {party_id}\n"
                f"Naziv: {payload['name']}\n"
                f"Minimax šifra: {mm or '— (še ni)'}"
                + (f"\nPovezanih IR/PR: {linked}" if linked else "")
                + (
                    "\n\nZ MM šifro izpade s seznama manjkajočih (Osveži)."
                    if mm
                    else "\n\nOkno ostane odprto — lahko preneseš v Minimax ali zapreš."
                ),
                parent=self,
            )
        return True

    def push_minimax(self) -> None:
        if not self.org_id:
            messagebox.showerror(
                "Minimax",
                "Manjka Org_ID — najprej izberi podjetje v glavnem oknu.",
                parent=self,
            )
            return
        if not self.save(quiet=True):
            return
        assert self.party_id
        self.status.set("Prenašam v Minimax …")
        self.update_idletasks()
        try:
            result = push_party_to_minimax(self.db, self.org_id, int(self.party_id))
        except Exception as exc:
            messagebox.showerror("Minimax", str(exc), parent=self)
            self.status.set("Prenos v Minimax ni uspel.")
            return
        fresh = self.db.get_party(int(self.party_id)) or {}
        if fresh:
            self._apply_party_dict(fresh)
        else:
            self.vars["minimax_code"].set(str(result.code or ""))
        if result.ok:
            self._link_journals_after_minimax()
            self._sync_journal_vat_from_party()
        self._refresh_save_banner()
        self.status.set(result.message)
        if result.ok:
            messagebox.showinfo(
                "Minimax",
                f"{result.message}\n\nŠifra: {result.code or self.vars['minimax_code'].get() or '—'}\n"
                "Stranka izpade s seznama manjkajočih (Osveži).",
                parent=self,
            )
            if self.on_saved:
                try:
                    self.on_saved()
                except Exception:
                    pass
        else:
            messagebox.showerror("Minimax", result.message, parent=self)
