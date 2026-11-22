"""Integra — forma za SQL TROPS korake (ZIP/BAK → SQL + izbira TROPS)."""

from __future__ import annotations

import datetime
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from trops_studio.config import DEFAULT_INTEGRA_SQL, company_db_path
from trops_studio.integra_kisanal import (
    kisanal_vrkn_summary,
    resolve_kont_dbf,
    urejanje_kisanal_to_sqlite,
)
from trops_studio.integra_irpr import import_kisanal_to_ir_pr
from trops_studio.integra_sql import (
    IntegraSqlError,
    TropsSqlTarget,
    begin_restore_preview,
    candidate_display,
    discover_trops_targets,
    find_detached_trops_targets,
    format_file_stamp,
    format_trops_sessions,
    list_sql_bak_files,
    list_sql_bck_candidates,
    list_sql_bck_zips,
    prepare_sql_bck,
    restore_bak_to_trops,
    trops_is_attached,
)
from trops_studio.ui.tooltip import ToolTip


class _PickDialog(tk.Toplevel):
    """Splošni izbirnik ene vrstice."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        subtitle: str,
        columns: tuple[tuple[str, str, int], ...],
        rows: list[tuple[str, ...]],
        empty_message: str = "Ni vnosov.",
    ) -> None:
        super().__init__(master)
        self.result_index: int | None = None
        self._n = len(rows)

        self.title(title)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.geometry("760x380")
        self.minsize(560, 280)

        pad = ttk.Frame(self, padding=12)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text=subtitle, wraplength=720).pack(anchor="w")

        col_ids = [c[0] for c in columns]
        self.tree = ttk.Treeview(pad, columns=col_ids, show="headings", selectmode="browse", height=12)
        for cid, heading, width in columns:
            self.tree.heading(cid, text=heading)
            self.tree.column(cid, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.tree.bind("<Double-1>", lambda _e: self._ok())

        for idx, values in enumerate(rows):
            self.tree.insert("", "end", iid=str(idx), values=values)
        if rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
        else:
            ttk.Label(pad, text=empty_message, style="Muted.TLabel").pack(anchor="w", pady=8)

        btns = ttk.Frame(pad)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Prekliči", command=self.destroy).pack(side="right")
        ok = ttk.Button(btns, text="Izberi", style="Accent.TButton", command=self._ok)
        ok.pack(side="right", padx=(0, 8))
        if not rows:
            ok.state(["disabled"])

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window(self)

    def _ok(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning(self.title(), "Izberi vrstico.", parent=self)
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if 0 <= idx < self._n:
            self.result_index = idx
            self.destroy()


class IntegraDialog(tk.Toplevel):
    """Forma Integra: ZIP/BAK iz SQL mape + preverba/izbira TROPS v SQL."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        sql_dir: str | Path | None = None,
        on_sql_dir_changed: Callable[[str], None] | None = None,
        auto_irpr_default: bool = True,
        on_auto_irpr_changed: Callable[[bool], None] | None = None,
        on_open_vse_knjizbe: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.on_sql_dir_changed = on_sql_dir_changed
        self.on_auto_irpr_changed = on_auto_irpr_changed
        self.on_open_vse_knjizbe = on_open_vse_knjizbe
        self.sql_dir_var = tk.StringVar(value=str(sql_dir or DEFAULT_INTEGRA_SQL))
        self.year_var = tk.StringVar(value=str(datetime.date.today().year))
        self.auto_irpr_var = tk.BooleanVar(value=bool(auto_irpr_default))
        self.auto_irpr_var.trace_add("write", lambda *_: self._notify_auto_irpr())
        self.zip_info_var = tk.StringVar(value="")
        self.bak_info_var = tk.StringVar(value="")
        self.trops_info_var = tk.StringVar(value="TROPS v SQL:  (še ni preverjeno)")
        self.status_var = tk.StringVar(value="Pripravljeno.")
        self.selected_trops: TropsSqlTarget | None = None
        self._trops_cache: list[TropsSqlTarget] = []

        self.title("Integra — SQL TROPS")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.geometry("980x720")
        self.minsize(860, 600)

        self._build()
        self.refresh_info()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, self._center)
        self.after(120, self._refresh_trops_async)

    def _center(self) -> None:
        try:
            self.update_idletasks()
            w, h = self.winfo_width(), self.winfo_height()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        except tk.TclError:
            pass

    def _build(self) -> None:
        pad = ttk.Frame(self, padding=14)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="Integra — SQL TROPS", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            pad,
            text="1) ZIP/BAK iz SQL mape → varnostna kopija TROPS → RESTORE zadnje kopije iz BAK v TROPS.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        path_row = ttk.Frame(pad)
        path_row.pack(fill="x", pady=(0, 8))
        ttk.Label(path_row, text="SQL pot", width=10).pack(side="left")
        ttk.Entry(path_row, textvariable=self.sql_dir_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(path_row, text="…", width=3, command=self._choose_sql_dir).pack(side="left")

        year_row = ttk.Frame(pad)
        year_row.pack(fill="x", pady=(0, 8))
        ttk.Label(year_row, text="Leto", width=10).pack(side="left")
        ttk.Entry(year_row, textvariable=self.year_var, width=8).pack(side="left", padx=6)
        ttk.Label(
            year_row,
            text="zamenjava kontov (KONT OLDSIFRA→KONTCTRL) + uvoz KISANAL/POPA",
            style="Muted.TLabel",
        ).pack(side="left", padx=(8, 0))

        info = ttk.LabelFrame(pad, text="Najdeno", padding=10)
        info.pack(fill="x", pady=(0, 12))
        ttk.Label(info, textvariable=self.zip_info_var, wraplength=700).pack(anchor="w")
        ttk.Label(info, textvariable=self.bak_info_var, wraplength=700).pack(anchor="w", pady=(4, 0))
        ttk.Label(info, textvariable=self.trops_info_var, wraplength=700).pack(anchor="w", pady=(4, 0))
        info_btns = ttk.Frame(info)
        info_btns.pack(anchor="e", pady=(8, 0))
        ttk.Button(info_btns, text="Osveži seznam", command=self.refresh_info).pack(side="left")
        ttk.Button(info_btns, text="Preveri TROPS", command=self._refresh_trops).pack(side="left", padx=(8, 0))

        btns = ttk.LabelFrame(pad, text="Dejanja", padding=10)
        btns.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(btns)
        row.pack(fill="x")
        btn_unpack = ttk.Button(
            row,
            text="Obnovi TROPS iz ZIP/BAK",
            style="Accent.TButton",
            command=self.razpakiraj_sql_bck,
        )
        btn_unpack.pack(side="left")
        ToolTip(
            btn_unpack,
            "Izberi ZIP ali BAK iz D:\\Trops\\20\\SQL:\n"
            "ZIP → razpakira .bak · varnostna kopija trenutne TROPS (MSSQL\\Backup) ·\n"
            "RESTORE zadnje kopije iz BAK v TROPS (tudi če TROPS ni priklopljen).",
        )
        btn_kis = ttk.Button(
            row,
            text="UrejanjeKisanal → SQLite",
            command=self.urejanje_kisanal_sqlite,
        )
        btn_kis.pack(side="left", padx=(8, 0))
        ToolTip(
            btn_kis,
            "UrejanjeKisanal v SQLite (popa + kisanal), brez Accessa in kisanal.dbf.\n"
            "Zamenjava kontov iz KONT*.DBF za izbrano leto,\n"
            "nato samodejni prenos IR/PR za isto obdobje.",
        )
        chk_auto = ttk.Checkbutton(
            row,
            text="Samodejni prenos IR/PR",
            variable=self.auto_irpr_var,
        )
        chk_auto.pack(side="left", padx=(14, 0))
        ToolTip(
            chk_auto,
            "Po UrejanjeKisanal: preveri konti ↔ Minimax\n"
            "in samodejno prenese 100/120→IR ter 220→PR za isto obdobje.",
        )
        btn_all = ttk.Button(row, text="Vse knjižbe", command=self._open_vse_knjizbe)
        btn_all.pack(side="left", padx=(8, 0))
        ToolTip(
            btn_all,
            "Odpre zavihek Vse knjižbe:\n"
            "Prenos v IR/PR (100/120 + 220) ·\n"
            "ostalo (BD/110) oddajamo posebej, če še ni v knjigi.",
        )

        log_fr = ttk.LabelFrame(pad, text="Dnevnik", padding=8)
        log_fr.pack(fill="both", expand=True)
        self.log = tk.Text(log_fr, height=8, wrap="word", relief="flat")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

        bottom = ttk.Frame(pad)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Label(bottom, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(bottom, text="Zapri", command=self.destroy).pack(side="right")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _sql_dir(self) -> Path:
        return Path(self.sql_dir_var.get().strip() or str(DEFAULT_INTEGRA_SQL))

    def _notify_sql_dir(self) -> None:
        if self.on_sql_dir_changed:
            self.on_sql_dir_changed(str(self._sql_dir()))

    def _notify_auto_irpr(self) -> None:
        if self.on_auto_irpr_changed:
            self.on_auto_irpr_changed(bool(self.auto_irpr_var.get()))

    def _choose_sql_dir(self) -> None:
        initial = self._sql_dir()
        folder = filedialog.askdirectory(
            parent=self,
            title="Mapa SQL TROPS (Integra) — izbor ZIP/BAK",
            initialdir=str(initial if initial.is_dir() else initial.parent),
        )
        if folder:
            self.sql_dir_var.set(folder)
            self._notify_sql_dir()
            self.refresh_info()

    def refresh_info(self) -> None:
        root = self._sql_dir()
        zips = list_sql_bck_zips(root)
        baks = list_sql_bak_files(root)
        self.zip_info_var.set(
            f"ZIP:  {len(zips)} v {root}" if zips else f"ZIP:  ni v {root}"
        )
        if baks:
            self.bak_info_var.set("BAK:  " + format_file_stamp(baks[0]) + (f"  · še {len(baks) - 1}" if len(baks) > 1 else ""))
        else:
            self.bak_info_var.set("BAK:  ni še")
        if self.selected_trops:
            self.trops_info_var.set("TROPS v SQL:  " + self.selected_trops.label)
        elif self._trops_cache:
            if len(self._trops_cache) == 1:
                self.trops_info_var.set("TROPS v SQL:  " + self._trops_cache[0].label)
            else:
                self.trops_info_var.set(f"TROPS v SQL:  {len(self._trops_cache)} zadetkov — ob dejanju izberi")
        else:
            self.trops_info_var.set("TROPS v SQL:  (še ni preverjeno)")

    def _refresh_trops_async(self) -> None:
        try:
            self._refresh_trops(silent=True)
        except Exception:
            pass

    def _refresh_trops(self, *, silent: bool = False) -> None:
        self.status_var.set("Iščem TROPS v SQL…")
        self.update_idletasks()
        try:
            targets = discover_trops_targets()
        except IntegraSqlError as exc:
            self._trops_cache = []
            self.selected_trops = None
            self.trops_info_var.set("TROPS v SQL:  ni najdeno")
            self.status_var.set("TROPS ni najden.")
            self._append_log(f"TROPS: {exc}")
            if not silent:
                messagebox.showerror("TROPS v SQL", str(exc), parent=self)
            return
        self._trops_cache = targets
        if len(targets) == 1:
            self.selected_trops = targets[0]
        elif self.selected_trops and all(t.key != self.selected_trops.key for t in targets):
            self.selected_trops = None
        self.refresh_info()
        if not targets:
            self.trops_info_var.set(
                "TROPS v SQL:  ni priklopljen — »Obnovi TROPS iz ZIP/BAK« ga obnovi iz BAK"
            )
            self.status_var.set("TROPS ni priklopljen v SQL.")
            self._append_log("TROPS: ni priklopljen v SQL.")
            return
        self.status_var.set(f"TROPS: {len(targets)} zadetek/-ov")
        self._append_log("TROPS najdeno:\n" + "\n".join(f"  • {t.label}" for t in targets))
        if not silent and len(targets) > 1:
            messagebox.showinfo(
                "TROPS v SQL",
                f"Najdenih je {len(targets)} TROPS baz.\n"
                "Ob »Obnovi TROPS iz ZIP/BAK« boš izbral cilj.",
                parent=self,
            )

    def _pick_source(self) -> Path | None:
        root = self._sql_dir()
        candidates = list_sql_bck_candidates(root)
        if not candidates:
            path = filedialog.askopenfilename(
                parent=self,
                title="Izberi ZIP ali BAK v SQL mapi",
                initialdir=str(root if root.is_dir() else root.parent),
                filetypes=(
                    ("SQL_bck", "*.zip;*.bak"),
                    ("ZIP", "*.zip"),
                    ("BAK", "*.bak"),
                    ("Vse", "*.*"),
                ),
            )
            return Path(path) if path else None

        rows: list[tuple[str, ...]] = []
        for path in candidates:
            kind, bak_txt, info = candidate_display(path)
            rows.append((kind, path.name, bak_txt, info))
        picker = _PickDialog(
            self,
            title="Izberi ZIP ali BAK",
            subtitle=f"Pot za razpakiranje:\n{root}",
            columns=(
                ("kind", "Tip", 60),
                ("file", "Datoteka", 240),
                ("bak", ".bak", 220),
                ("info", "Velikost / datum", 160),
            ),
            rows=rows,
            empty_message="V SQL mapi ni ZIP/BAK datotek.",
        )
        if picker.result_index is None:
            return None
        return candidates[picker.result_index]

    def _pick_trops(self, targets: list[TropsSqlTarget]) -> TropsSqlTarget | None:
        if not targets:
            return None
        if len(targets) == 1:
            return targets[0]
        rows = [
            (t.server, t.database, t.data_file or "—")
            for t in targets
        ]
        picker = _PickDialog(
            self,
            title="Izberi TROPS v SQL",
            subtitle="Najdenih je več baz TROPS — izberi cilj za razpakiranje / obnovitev:",
            columns=(
                ("server", "SQL strežnik", 200),
                ("db", "Baza", 100),
                ("mdf", "DATA datoteka", 400),
            ),
            rows=rows,
        )
        if picker.result_index is None:
            return None
        return targets[picker.result_index]

    def razpakiraj_sql_bck(self) -> None:
        root = self._sql_dir()
        source = self._pick_source()
        if source is None:
            self.status_var.set("Izbira datoteke preklicana.")
            return

        self.status_var.set("Iščem TROPS v SQL…")
        self.update_idletasks()
        try:
            targets = discover_trops_targets()
        except IntegraSqlError as exc:
            messagebox.showerror("TROPS v SQL", str(exc), parent=self)
            self.status_var.set("TROPS ni najden.")
            return
        self._trops_cache = targets
        attached_targets = targets
        detached_targets: list[TropsSqlTarget] = []
        if not attached_targets:
            detached_targets = find_detached_trops_targets(database="TROPS")
            if not detached_targets:
                messagebox.showerror(
                    "Obnovi TROPS iz ZIP/BAK",
                    "TROPS ni priklopljen in ne najdem SQL DATA poti za obnovitev.",
                    parent=self,
                )
                self.status_var.set("TROPS cilj ni najden.")
                return
            self._append_log(
                "TROPS ni priklopljen — izbiram cilj po SQL DATA poti instance."
            )
        trops = self._pick_trops(attached_targets or detached_targets)
        if trops is None:
            self.status_var.set("Izbira TROPS preklicana.")
            return
        self.selected_trops = trops
        self.refresh_info()

        self.status_var.set("Pripravljam BAK (ZIP/BAK) …")
        self.update_idletasks()
        try:
            prepared = prepare_sql_bck(root, source, trops=trops, overwrite=True)
            if prepared.bak_path is None:
                raise IntegraSqlError("Po pripravi ni .bak datoteke za obnovitev.")
            self.status_var.set("Preverjam seje in delam varnostno kopijo…")
            self.update_idletasks()
            preview = begin_restore_preview(prepared.bak_path, trops)
            staged = preview.staged
            backup_set = preview.backup_set
            set_count = preview.backup_set_count
            attached_now = preview.attached
        except IntegraSqlError as exc:
            self.status_var.set("Napaka — priprava BAK ni uspela.")
            self._append_log(f"NAPAKA: {exc}")
            messagebox.showerror("Obnovi TROPS iz ZIP/BAK", f"Ni uspešno.\n\n{exc}", parent=self)
            return

        kind = source.suffix.lower().lstrip(".")
        data_dir = trops.data_dir or Path("?")
        bak_path = prepared.bak_path
        safety_txt = (
            f"Varnostna kopija trenutne TROPS je v:\n{preview.safety_backup}\n\n"
            if preview.safety_backup
            else "Varnostna kopija trenutne TROPS ni nastala (baza še ne obstaja).\n\n"
        )
        sess_txt = format_trops_sessions(preview.sessions)
        if not messagebox.askyesno(
            "Obnovi TROPS iz ZIP/BAK",
            "Izvedem obnovitev?\n\n"
            f"Strežnik:\n{trops.server} / {trops.database}\n\n"
            f"Vir ({kind.upper()}):\n{source.name}\n"
            f"Pot kopije:\n{bak_path}\n"
            f"Kopija v BAK (zadnja polna):\n{backup_set.position}/{set_count}  {backup_set.label}\n\n"
            f"SQL DATA (cilj):\n{data_dir}\n"
            f"{Path(trops.data_file).name if trops.data_file else ''}\n"
            f"{Path(trops.log_file).name if trops.log_file else ''}\n\n"
            + safety_txt
            + sess_txt
            + "\n\nObstoječa baza TROPS bo zamenjana (REPLACE).",
            parent=self,
        ):
            self.status_var.set("Obnova preklicana.")
            return

        disconnect = False
        if preview.sessions:
            if not messagebox.askyesno(
                "Povezane seje",
                "TROPS ima povezane seje. Povezave prekinem samo, če to izrecno potrdiš.\n\n"
                + sess_txt
                + "\n\nPrekinem povezave in obnovim?\n"
                "Če izbereš Ne, obnova se ne začne.",
                parent=self,
            ):
                self.status_var.set("Obnova preklicana — povezave niso prekinjene.")
                return
            disconnect = True

        self.status_var.set("Obnavljam TROPS iz BAK…")
        self.update_idletasks()
        try:
            restored = restore_bak_to_trops(
                prepared.bak_path,
                trops,
                backup_set=backup_set,
                disconnect_sessions=disconnect,
                existing_safety=preview.safety_backup,
                safety_backup=preview.safety_backup is None,
            )
        except IntegraSqlError as exc:
            self.status_var.set("Napaka — obnovitev ni uspela.")
            self._append_log(f"NAPAKA: {exc}")
            messagebox.showerror(
                "Obnovi TROPS iz ZIP/BAK",
                f"Ni uspešno.\n\n{exc}",
                parent=self,
            )
            return

        self._notify_sql_dir()
        self.refresh_info()
        bak_name = prepared.bak_path.name if prepared.bak_path else "—"
        lines = [
            f"USPEŠNO ({prepared.source_kind}): {prepared.source_path.name}",
            f"  BAK: {bak_name}",
            f"  Staging: {staged}",
            f"  Kopija v BAK: {backup_set.position}/{set_count} · {backup_set.label}",
            f"  TROPS prej priklopljen: {'da' if attached_now else 'ne'}",
            f"  Varnostna kopija prej: {restored.safety_backup or '—'}",
            f"  TROPS: {trops.server} / {trops.database}",
            f"  DATA: {restored.data_file}",
            f"  LOG: {restored.log_file}",
        ]
        if prepared.extracted:
            lines.extend(f"  + {p.name}" for p in prepared.extracted)
        self._append_log("\n".join(lines))
        self.status_var.set(f"Uspešno · TROPS obnovljen · {bak_name}")
        messagebox.showinfo(
            "Obnovi TROPS iz ZIP/BAK — uspešno",
            "Uspešno!\n\n"
            "BAK je obnovljen v SQL bazo TROPS.\n\n"
            f"BAK:\n{bak_name}\n"
            f"Kopija v BAK:\n{backup_set.position}/{set_count}  {backup_set.label}\n\n"
            f"SQL DATA:\n{data_dir}\n"
            f"• {Path(restored.data_file).name}\n"
            f"• {Path(restored.log_file).name}\n\n"
            f"Varnostna kopija prej:\n{restored.safety_backup or '—'}\n\n"
            f"Strežnik:\n{trops.server}\n"
            f"Baza: {trops.database}",
            parent=self,
        )

    def _open_vse_knjizbe(self) -> None:
        if self.on_open_vse_knjizbe:
            self.on_open_vse_knjizbe()
            self.destroy()
        else:
            messagebox.showinfo(
                "Vse knjižbe",
                "Zavihek »Vse knjižbe« je v glavnem oknu Trops Studio\n"
                "(ob obdobju + filtri BD / IR / PR).",
                parent=self,
            )

    def _year(self) -> int:
        try:
            year = int(self.year_var.get().strip())
        except ValueError as exc:
            raise IntegraSqlError("Leto mora biti število (npr. 2026).") from exc
        if year < 1990 or year > 2100:
            raise IntegraSqlError(f"Neveljavno leto: {year}")
        return year

    def urejanje_kisanal_sqlite(self) -> None:
        """Call UrejanjeKisanal → SQLite + konti↔Minimax + samodejni prenos IR/PR."""
        try:
            year = self._year()
            kont_path = resolve_kont_dbf(year)
        except IntegraSqlError as exc:
            messagebox.showerror("UrejanjeKisanal", str(exc), parent=self)
            return

        db_path = company_db_path(20)
        if not messagebox.askyesno(
            "UrejanjeKisanal → SQLite",
            "Prenesem POPA + KISANAL iz SQL TROPS v SQLite?\n\n"
            f"Leto: {year}\n"
            f"KONT mapa: {kont_path}\n"
            f"SQLite: {db_path}\n\n"
            f"Samodejni prenos IR/PR: {'DA' if self.auto_irpr_var.get() else 'NE'}\n\n"
            "Enako kot Call UrejanjeKisanal, brez kisanal.dbf / popa.dbf.\n"
            "Konto: OLDSIFRA → KONTCTRL.",
            parent=self,
        ):
            self.status_var.set("UrejanjeKisanal preklicano.")
            return

        self.status_var.set("UrejanjeKisanal → SQLite…")
        self.update_idletasks()
        try:
            result = urejanje_kisanal_to_sqlite(
                db_path=db_path,
                year=year,
                trops=self.selected_trops,
            )
            summary = kisanal_vrkn_summary(db_path, year)
        except IntegraSqlError as exc:
            self.status_var.set("Napaka pri UrejanjeKisanal.")
            self._append_log(f"NAPAKA UrejanjeKisanal: {exc}")
            messagebox.showerror("UrejanjeKisanal", f"Ni uspešno.\n\n{exc}", parent=self)
            return
        except Exception as exc:
            self.status_var.set("Napaka pri UrejanjeKisanal.")
            self._append_log(f"NAPAKA: {exc}")
            messagebox.showerror("UrejanjeKisanal", f"Ni uspešno.\n\n{exc}", parent=self)
            return

        vk_txt = ", ".join(f"{vk}:{n}" for vk, n in summary[:12]) or "—"
        self._append_log(result.message + f"\n  VRKN: {vk_txt}")
        self.status_var.set(
            f"Uspešno · POPA {result.popa_count} · KISANAL {result.kisanal_count} ({year})"
        )

        transfer_message = "Prenos v IR/PR ni izveden."
        transfer_done = False
        transfer_ir = 0
        transfer_pr = 0
        transfer_skipped = 0
        period_txt = f"{result.date_from.isoformat()} – {result.date_to.isoformat()}"
        if not self.auto_irpr_var.get():
            transfer_message = "Samodejni prenos IR/PR je izklopljen (stikalo)."
            self._append_log("AUTO Prenos v IR/PR: izklopljen (stikalo).")
            self.status_var.set("UrejanjeKisanal OK · samodejni prenos izklopljen.")
        else:
            db = None
            # Preveri Trops konti proti Minimax planu in nato samodejno prenesi v IR/PR.
            try:
                from trops_studio.companies import company_org_id, find_company, load_companies
                from trops_studio.db import Database
                from trops_studio.ui.account_map_dialog import ensure_accounts_mapped

                db = Database(db_path)
                _, companies = load_companies()
                company = find_company(companies, "zst-20")
                org_id = company_org_id(company) if company else ""
                can_transfer = ensure_accounts_mapped(
                    self,
                    db,
                    org_id=org_id,
                    title="Konti pred samodejnim prenosom IR / PR",
                    block_if_cancel=True,
                )
                if not can_transfer:
                    transfer_message = (
                        "Prenos v IR/PR preklican: manjkajo potrjene zamenjave kontov."
                    )
                    self._append_log("AUTO Prenos v IR/PR: preklican (konti niso potrjeni).")
                    self.status_var.set("UrejanjeKisanal OK · prenos preklican (konti).")
                else:
                    self.status_var.set("UrejanjeKisanal OK · samodejni prenos v IR/PR…")
                    self.update_idletasks()
                    transfer = import_kisanal_to_ir_pr(
                        db,
                        date_from=result.date_from,
                        date_to=result.date_to,
                        replace_existing=False,
                        groups=("IR", "PR"),
                        org_id=org_id,
                    )
                    transfer_done = True
                    transfer_ir = int(transfer.ir)
                    transfer_pr = int(transfer.pr)
                    transfer_skipped = int(transfer.skipped)
                    transfer_message = transfer.message
                    self._append_log("AUTO Prenos v IR/PR:\n" + transfer.message)
                    self.status_var.set(
                        f"Uspešno · KISANAL {result.kisanal_count} · IR {transfer_ir} · PR {transfer_pr}"
                    )
            except Exception as exc:
                transfer_message = f"Prenos v IR/PR napaka: {exc}"
                self._append_log(f"AUTO Prenos v IR/PR: {exc}")
                self.status_var.set("UrejanjeKisanal OK · napaka pri prenosu IR/PR.")
            finally:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass

        if transfer_done and self.on_open_vse_knjizbe:
            try:
                self.on_open_vse_knjizbe()
            except Exception:
                pass

        messagebox.showinfo(
            "UrejanjeKisanal — uspešno",
            "Uspešno!\n\n"
            f"{result.message}\n\n"
            f"Vrste knjižb (VRKN):\n{vk_txt}\n\n"
            "Samodejni prenos v IR/PR:\n"
            f"Obdobje: {period_txt}\n"
            f"{transfer_message}\n\n"
            f"Povzetek: IR {transfer_ir} · PR {transfer_pr} · preskočeno {transfer_skipped}",
            parent=self,
        )
