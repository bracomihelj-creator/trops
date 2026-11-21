"""Zavihek Vse knjižbe — kisanal iz SQLite (filter datum + BD/IR/PR).

Skupine kot Minimax: BD / IR / PR / Ostalo (ne 110/100/120 …).
Prenos IR/PR (100/120 → IR, 220 → PR) gre v knjige.
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from trops_studio.db import Database
from trops_studio.integra_irpr import (
    SKIP_IMPORT_GROUPS,
    import_kisanal_to_ir_pr,
    knjiga_group,
    knjiga_series,
    transferred_ctrls_from_rows,
)
from trops_studio.ui.account_map_dialog import ensure_accounts_mapped
from trops_studio.money import decimal_value, money_text, normalize_text
from trops_studio.ui.search import haystack_matches, row_search_chunks, search_tokens
from trops_studio.ui.tooltip import ToolTip

_MONEY_SORT_COLS = frozenset({"debt", "krdt"})
_NUMERIC_SORT_COLS = frozenset({"ctrl", "pozi", "part", "debt", "krdt"})

# Minimax skupine (filter + stolpec Skup.) — BD ≠ BOD/OP
_MM_GROUPS: tuple[tuple[str, str], ...] = (
    ("BD", "110* bančni izpiski → Minimax BD"),
    ("IR", "100* Paragoni + 120* Fakture"),
    ("PR", "220* prejeti računi"),
    ("OP", "BOD* plače → Minimax OP (že knjiženo, ne uvažamo)"),
    ("DOP", "DOP* dohodki → Minimax DOP (ne uvažamo)"),
    ("OST", "Druge knjižbe"),
)
# Privzeto vklopljene (brez plač/dohodkov)
_DEFAULT_ON = frozenset({"BD", "IR", "PR"})


class VseKnjizbeTab:
    """Prikaz vseh knjižb iz tabele kisanal (Integra SQLite)."""

    def __init__(
        self,
        parent: ttk.Frame,
        *,
        colors: dict[str, str],
        pack_search: Callable[..., None] | None = None,
        get_db_path: Callable[[], Path | None] | None = None,
        get_period: Callable[[], tuple[date, date]] | None = None,
        get_database: Callable[[], Database | None] | None = None,
        get_org_id: Callable[[], str] | None = None,
        get_master: Callable[[], Any] | None = None,
        on_after_transfer: Callable[[], None] | None = None,
    ) -> None:
        self.parent = parent
        self.colors = colors
        self._pack_search = pack_search
        self._get_db_path = get_db_path
        self._get_period = get_period
        self._get_database = get_database
        self._get_org_id = get_org_id
        self._get_master = get_master
        self._on_after_transfer = on_after_transfer
        self.search_var = tk.StringVar(value="")
        self.filter_groups: dict[str, tk.BooleanVar] = {
            code: tk.BooleanVar(value=(code in _DEFAULT_ON)) for code, _tip in _MM_GROUPS
        }
        self.only_pending = tk.BooleanVar(value=True)
        self.info_var = tk.StringVar(value="Ni podatkov — najprej UrejanjeKisanal → SQLite.")
        self.selection_var = tk.StringVar(value="Označenih: 0")
        self._rows: list[dict[str, Any]] = []
        self._transferred: set[str] = set()
        self._heading_titles: dict[str, str] = {}
        self._sort_col: str | None = None
        self._sort_reverse = False
        self._chk: dict[int, bool] = {}
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self.parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Vse knjižbe (kisanal)", style="SectionTitle.TLabel").pack(side="left")
        if self._pack_search:
            self._pack_search(
                top,
                self.search_var,
                on_change=self.refresh,
                clear_command=lambda: (self.search_var.set(""), self.refresh()),
                tip="Išči po vseh poljih: skupina, knjižba, datum, konto, znesek, partner, veza …",
            )

        filters = ttk.Frame(self.parent, style="Panel.TFrame")
        filters.pack(fill="x", pady=(0, 6))
        ttk.Label(filters, text="Skupine (Minimax):", style="Muted.TLabel").pack(
            side="left", padx=(0, 8)
        )
        for code, tip in _MM_GROUPS:
            label = "Ostalo" if code == "OST" else code
            var = self.filter_groups[code]
            chk = ttk.Checkbutton(filters, text=label, variable=var, command=self.refresh)
            chk.pack(side="left", padx=(0, 8))
            ToolTip(chk, f"{tip}\nDvojni klik = samo ta skupina.")
            chk.bind("<Double-Button-1>", lambda _e, c=code: self._only_group(c))
        ttk.Checkbutton(
            filters,
            text="Samo še ne v IR/PR",
            variable=self.only_pending,
            command=self.refresh,
        ).pack(side="left", padx=(8, 0))
        ToolTip(
            filters.winfo_children()[-1],
            "Skrij dokumente, ki so že preneseni v zavihka IR / PR (Knjige).",
        )
        btn_all = ttk.Button(filters, text="Vse", command=self._only_main_groups)
        btn_all.pack(side="left", padx=(12, 0))
        ToolTip(
            btn_all,
            "Vklopi BD + IR + PR.\n"
            "OP (plače BOD*) in DOP ostanejo izklopljeni — že v Minimaxu, ne uvažamo.",
        )
        ttk.Button(filters, text="Samo BD", command=self._only_bd).pack(side="left", padx=(4, 0))
        ttk.Button(filters, text="Samo IR", command=self._only_ir).pack(side="left", padx=(4, 0))
        ttk.Button(filters, text="Samo PR", command=self._only_pr).pack(side="left", padx=(4, 0))

        actions = ttk.Frame(self.parent, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 6))
        btn_tr = ttk.Button(
            actions,
            text="Prenos v IR / PR",
            style="Accent.TButton",
            command=self.transfer_to_ir_pr,
        )
        btn_tr.pack(side="left")
        ToolTip(
            btn_tr,
            "Kot Uvozi Vasco pri Projetu:\n"
            "IR (100/120) → Izdani računi\n"
            "PR (220) → Prejeti računi\n"
            "po filtru obdobja. Najprej preveri konti ↔ Minimax.",
        )
        btn_map = ttk.Button(actions, text="Konti ↔ Minimax", command=self.open_account_map)
        btn_map.pack(side="left", padx=(8, 0))
        ToolTip(
            btn_map,
            "Preveri Trops konti proti Minimax planu.\n"
            "Zamenjave shrani za IR / PR / vse knjižbe.",
        )
        ttk.Button(actions, text="Osveži", command=self.refresh).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Vse označi", command=lambda: self._set_chk_all(True)).pack(
            side="left", padx=(16, 0)
        )
        ttk.Button(actions, text="Vse odznači", command=lambda: self._set_chk_all(False)).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(actions, text="Uredi", command=self.edit_selected).pack(side="left", padx=(16, 0))
        ttk.Button(
            actions, text="Izbriši", style="Danger.TButton", command=self.delete_checked
        ).pack(side="left", padx=(4, 0))
        ttk.Label(actions, textvariable=self.selection_var, style="Muted.TLabel").pack(
            side="left", padx=(12, 0)
        )
        ttk.Label(actions, textvariable=self.info_var, style="Muted.TLabel").pack(side="right")

        cols = (
            "chk",
            "grp",
            "xfer",
            "ctrl",
            "pozi",
            "datum",
            "ddv",
            "konto",
            "konto_old",
            "debt",
            "krdt",
            "part",
            "pime",
            "doku",
            "anal",
            "vrkn",
            "veza",
        )
        self.tree = ttk.Treeview(self.parent, columns=cols, show="headings", selectmode="extended")
        headings = {
            "chk": ("Chk", 42),
            "grp": ("Skup.", 55),
            "xfer": ("IR/PR", 50),
            "ctrl": ("Knjižba", 80),
            "pozi": ("Poz", 45),
            "datum": ("Datum", 85),
            "ddv": ("DDV dat.", 85),
            "konto": ("Konto", 70),
            "konto_old": ("Stari", 70),
            "debt": ("Debet", 85),
            "krdt": ("Kredit", 85),
            "part": ("Part.", 60),
            "pime": ("Partner", 160),
            "doku": ("Dokument", 110),
            "anal": ("Tekst", 140),
            "vrkn": ("VRKN", 50),
            "veza": ("Veza", 80),
        }
        self._heading_titles = {cid: title for cid, (title, _) in headings.items()}
        for cid, (title, width) in headings.items():
            self.tree.heading(
                cid,
                text=title,
                command=lambda c=cid: self._sort_by(c),
            )
            anchor = (
                "center"
                if cid in {"chk", "grp", "xfer"}
                else "e"
                if cid in {"debt", "krdt"}
                else "w"
            )
            self.tree.column(cid, width=width, anchor=anchor, stretch=cid in {"pime", "anal"})
        yscroll = ttk.Scrollbar(self.parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self.tree.bind("<space>", lambda _e: self._toggle_chk())
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.tree.bind("<Delete>", lambda _e: self.delete_checked())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_selection_label())
        self.tree.tag_configure("checked", background="#1d3a2a", foreground="#c8f7d4")
        ToolTip(
            self.tree,
            "Minimax: BD=banka(110) · IR · PR · OP=plače(BOD, ne uvoz) · DOP.\n"
            "Chk / Space = označi · dvojni klik = uredi · Delete = briši označene.\n"
            "Klik na naslov stolpca = sortiranje (↑/↓).",
        )

    def _sort_key(self, item: str, column: str) -> tuple[int, Any]:
        value = self.tree.set(item, column)
        if column == "chk":
            return (0, 0 if value == "☑" else 1)
        if column in _MONEY_SORT_COLS:
            try:
                return (0, decimal_value(value))
            except Exception:
                return (1, str(value).casefold())
        if column in _NUMERIC_SORT_COLS:
            text = str(value).strip()
            if text.isdigit():
                return (0, int(text))
            try:
                return (0, decimal_value(text))
            except Exception:
                pass
        return (1, str(value).casefold())

    def _update_heading_labels(self) -> None:
        for cid, title in self._heading_titles.items():
            mark = ""
            if cid == self._sort_col:
                mark = " ↓" if self._sort_reverse else " ↑"
            self.tree.heading(
                cid,
                text=f"{title}{mark}",
                command=lambda c=cid: self._sort_by(c),
            )

    def _sort_by(self, column: str, *, toggle: bool = True) -> None:
        if column == "chk":
            return
        if toggle and self._sort_col == column:
            self._sort_reverse = not self._sort_reverse
        else:
            if self._sort_col != column:
                self._sort_reverse = False
            self._sort_col = column
        if not self._sort_col:
            return
        items = sorted(
            self.tree.get_children(""),
            key=lambda item: self._sort_key(item, self._sort_col or column),
            reverse=self._sort_reverse,
        )
        for position, item in enumerate(items):
            self.tree.move(item, "", position)
        self._update_heading_labels()

    def _set_groups(self, enabled: set[str], *, pending: bool | None = None) -> None:
        for code, var in self.filter_groups.items():
            var.set(code in enabled)
        if pending is not None:
            self.only_pending.set(pending)
        self.refresh()

    def _only_group(self, code: str) -> None:
        self._set_groups({code})

    def _only_main_groups(self) -> None:
        # Brez OP/DOP — plače/dohodki že v Minimaxu
        self._set_groups(set(_DEFAULT_ON) - set(SKIP_IMPORT_GROUPS))

    def _only_bd(self) -> None:
        """Samo bančni izpiski (110), ne BOD/plače."""
        self._set_groups({"BD"}, pending=True)

    def _only_ir(self) -> None:
        self._set_groups({"IR"})

    def _only_pr(self) -> None:
        self._set_groups({"PR"})

    def _allowed_groups(self) -> set[str]:
        return {code for code, var in self.filter_groups.items() if var.get()}

    def _load_transferred(self) -> set[str]:
        db = self._get_database() if self._get_database else None
        if db is None:
            return set()
        try:
            return transferred_ctrls_from_rows([*db.list_ir(), *db.list_pr()])
        except Exception:
            return set()

    def _org_id(self) -> str:
        if self._get_org_id:
            try:
                return self._get_org_id() or ""
            except Exception:
                return ""
        return ""

    def _master(self) -> Any:
        if self._get_master:
            try:
                return self._get_master()
            except Exception:
                pass
        return self.parent.winfo_toplevel()

    def _row_id(self, iid: str) -> int | None:
        try:
            return int(str(iid).split(":")[0])
        except (TypeError, ValueError):
            return None

    def _checked_ids(self) -> list[int]:
        return [rid for rid, on in self._chk.items() if on]

    def _update_selection_label(self) -> None:
        n = len(self._checked_ids())
        sel = len(self.tree.selection())
        self.selection_var.set(f"Označenih: {n}" + (f" · izbranih: {sel}" if sel else ""))

    def _toggle_chk(self) -> str:
        targets = list(self.tree.selection()) or []
        if not targets:
            return "break"
        for iid in targets:
            rid = self._row_id(iid)
            if rid is None:
                continue
            self._chk[rid] = not bool(self._chk.get(rid))
            self._paint_chk(iid, rid)
        self._update_selection_label()
        return "break"

    def _paint_chk(self, iid: str, rid: int) -> None:
        on = bool(self._chk.get(rid))
        self.tree.set(iid, "chk", "☑" if on else "☐")
        tags = ("checked",) if on else ()
        self.tree.item(iid, tags=tags)

    def _set_chk_all(self, value: bool) -> None:
        for iid in self.tree.get_children(""):
            rid = self._row_id(iid)
            if rid is None:
                continue
            self._chk[rid] = value
            self._paint_chk(iid, rid)
        self._update_selection_label()

    def _on_tree_click(self, event: tk.Event) -> None:
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        # #1 = chk
        if col != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        rid = self._row_id(iid)
        if rid is None:
            return
        self._chk[rid] = not bool(self._chk.get(rid))
        self._paint_chk(iid, rid)
        self._update_selection_label()

    def open_account_map(self) -> None:
        db = self._get_database() if self._get_database else None
        if db is None:
            messagebox.showwarning("Konti ↔ Minimax", "Ni odprte baze podjetja.")
            return
        from trops_studio.ui.account_map_dialog import AccountMapDialog

        AccountMapDialog(
            self._master(),
            db,
            org_id=self._org_id(),
            force_open=True,
            on_saved=lambda _m: self.refresh(),
        )

    def transfer_to_ir_pr(self) -> None:
        db = self._get_database() if self._get_database else None
        if db is None:
            messagebox.showwarning("Prenos v IR / PR", "Ni odprte baze podjetja.")
            return
        d0, d1 = (self._get_period() if self._get_period else (None, None))
        if d0 is None or d1 is None:
            messagebox.showwarning("Prenos v IR / PR", "Najprej nastavi obdobje.")
            return
        org_id = self._org_id()
        if not ensure_accounts_mapped(
            self._master(),
            db,
            org_id=org_id,
            title="Konti pred prenosom IR / PR",
            block_if_cancel=True,
        ):
            return
        replace = messagebox.askyesnocancel(
            "Prenos v IR / PR",
            f"Prenesem IR (BD ne) in PR iz kisanal\n"
            f"za obdobje {d0.isoformat()} – {d1.isoformat()}?\n\n"
            f"DA = zamenjaj že prenesene Integra dokumente\n"
            f"NE = dodaj samo nove (preskoči že v knjigi)\n"
            f"Prekliči = ne naredi nič",
        )
        if replace is None:
            return
        try:
            result = import_kisanal_to_ir_pr(
                db,
                date_from=d0,
                date_to=d1,
                replace_existing=bool(replace),
                groups=("IR", "PR"),
                org_id=org_id,
            )
        except Exception as exc:
            messagebox.showerror("Prenos v IR / PR", str(exc))
            return
        messagebox.showinfo("Prenos v IR / PR", result.message)
        self.refresh()
        if self._on_after_transfer:
            try:
                self._on_after_transfer()
            except Exception:
                pass

    def _db_path(self) -> Path | None:
        path = self._get_db_path() if self._get_db_path else None
        if path is None or not Path(path).is_file():
            return None
        return Path(path)

    def _fetch_row(self, row_id: int) -> dict[str, Any] | None:
        path = self._db_path()
        if path is None:
            return None
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute("SELECT * FROM kisanal WHERE id=?", (row_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def edit_selected(self) -> None:
        iid = ""
        if self.tree.selection():
            iid = self.tree.selection()[0]
        else:
            checked = self._checked_ids()
            if len(checked) == 1:
                iid = str(checked[0])
        rid = self._row_id(iid) if iid else None
        if rid is None:
            messagebox.showinfo("Uredi", "Izberi ali označi eno vrstico.", parent=self._master())
            return
        row = self._fetch_row(rid)
        if row is None:
            messagebox.showwarning("Uredi", f"Vrstica id={rid} ne obstaja več.", parent=self._master())
            self.refresh()
            return
        KisanalEditDialog(
            self._master(),
            row,
            db_path=self._db_path(),
            on_saved=self.refresh,
        )

    def delete_checked(self) -> None:
        ids = self._checked_ids()
        if not ids and self.tree.selection():
            ids = [rid for iid in self.tree.selection() if (rid := self._row_id(iid)) is not None]
        if not ids:
            messagebox.showinfo(
                "Izbriši",
                "Označi vrstice (Chk / Space) ali jih izberi, nato Izbriši.",
                parent=self._master(),
            )
            return
        path = self._db_path()
        if path is None:
            messagebox.showwarning("Izbriši", "Ni SQLite baze.", parent=self._master())
            return
        if not messagebox.askyesno(
            "Izbriši knjižbe",
            f"Izbrišem {len(ids)} označenih vrstic iz kisanal?\n"
            "To vpliva na Vse knjižbe / prenose IR·PR.",
            parent=self._master(),
        ):
            return
        try:
            conn = sqlite3.connect(str(path))
            try:
                conn.executemany("DELETE FROM kisanal WHERE id=?", [(i,) for i in ids])
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            messagebox.showerror("Izbriši", str(exc), parent=self._master())
            return
        for rid in ids:
            self._chk.pop(rid, None)
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        path = self._db_path()
        if path is None:
            self.info_var.set("Ni SQLite baze podjetja.")
            self._rows = []
            self._update_selection_label()
            return

        d0, d1 = (self._get_period() if self._get_period else (None, None))
        if d0 is None or d1 is None:
            self.info_var.set("Ni obdobja.")
            self._update_selection_label()
            return
        iso0, iso1 = d0.isoformat(), d1.isoformat()
        self._transferred = self._load_transferred()
        try:
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kisanal'"
                ).fetchone()
                if not exists:
                    self.info_var.set("Tabela kisanal še ne obstaja — UrejanjeKisanal → SQLite.")
                    self._rows = []
                    self._update_selection_label()
                    return
                cur = conn.execute(
                    """
                    SELECT id, anal_ctrl, anal_pozi, anal_akon, anal_akon_old, anal_ddok, anal_ddur,
                           anal_debt, anal_krdt, anal_part, anal_pime, anal_doku, anal_anal,
                           anal_vrkn, anal_veza
                    FROM kisanal
                    WHERE (anal_ddok BETWEEN ? AND ?)
                       OR (anal_ddur BETWEEN ? AND ?)
                    ORDER BY COALESCE(anal_ddok, anal_ddur), anal_ctrl, anal_pozi
                    """,
                    (iso0, iso1, iso0, iso1),
                )
                raw = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            self.info_var.set(f"SQL napaka: {exc}")
            self._rows = []
            self._update_selection_label()
            return

        allowed = self._allowed_groups()
        tokens = search_tokens(self.search_var.get())
        rows: list[dict[str, Any]] = []
        pending_docs = 0
        seen_ctrl: set[str] = set()
        for row in raw:
            ctrl = str(row.get("anal_ctrl") or "")
            vrkn = str(row.get("anal_vrkn") or "")
            series = knjiga_series(ctrl, vrkn)
            grp = knjiga_group(ctrl, vrkn)
            row["series"] = series
            row["grp"] = grp
            transferred = ctrl in self._transferred
            row["xfer"] = "da" if transferred else ""
            if grp not in allowed:
                continue
            if self.only_pending.get() and transferred:
                continue
            if tokens and not haystack_matches(
                tokens,
                row_search_chunks(
                    row,
                    extra=(
                        grp,
                        series,
                        row.get("xfer", ""),
                        money_text(row.get("anal_debt")),
                        money_text(row.get("anal_krdt")),
                        (row.get("anal_ddok") or "")[:10],
                        (row.get("anal_ddur") or "")[:10],
                    ),
                ),
            ):
                continue
            rows.append(row)
            if ctrl and ctrl not in seen_ctrl:
                seen_ctrl.add(ctrl)
                if not transferred:
                    pending_docs += 1

        self._rows = rows
        debt = sum(float(r.get("anal_debt") or 0) for r in rows)
        krdt = sum(float(r.get("anal_krdt") or 0) for r in rows)
        mode = "nepreneseno" if self.only_pending.get() else "vse"
        self.info_var.set(
            f"{len(rows)} vrstic · {pending_docs} dok. · {mode} · "
            f"{iso0}–{iso1} · D {money_text(debt)} / K {money_text(krdt)}"
        )
        visible_ids: set[int] = set()
        for row in rows:
            rid = int(row.get("id") or 0)
            if not rid:
                continue
            visible_ids.add(rid)
            on = bool(self._chk.get(rid))
            self.tree.insert(
                "",
                "end",
                iid=str(rid),
                values=(
                    "☑" if on else "☐",
                    row.get("grp", ""),
                    row.get("xfer", ""),
                    row.get("anal_ctrl", ""),
                    row.get("anal_pozi", ""),
                    (row.get("anal_ddok") or "")[:10],
                    (row.get("anal_ddur") or "")[:10],
                    row.get("anal_akon", ""),
                    row.get("anal_akon_old", ""),
                    money_text(row.get("anal_debt")),
                    money_text(row.get("anal_krdt")),
                    row.get("anal_part", ""),
                    row.get("anal_pime", ""),
                    row.get("anal_doku", ""),
                    row.get("anal_anal", ""),
                    row.get("anal_vrkn", ""),
                    row.get("anal_veza", ""),
                ),
                tags=("checked",) if on else (),
            )
        # počisti chk za vrstice, ki niso več vidne / obstajajo
        for rid in list(self._chk):
            if rid not in visible_ids and not self._chk.get(rid):
                self._chk.pop(rid, None)
        if self._sort_col:
            self._sort_by(self._sort_col, toggle=False)
        else:
            self._update_heading_labels()
        self._update_selection_label()


class KisanalEditDialog(tk.Toplevel):
    """Urejanje ene vrstice kisanal."""

    _FIELDS: tuple[tuple[str, str, int], ...] = (
        ("anal_ctrl", "Knjižba", 16),
        ("anal_pozi", "Pozicija", 8),
        ("anal_ddok", "Datum", 12),
        ("anal_ddur", "DDV datum", 12),
        ("anal_akon", "Konto", 14),
        ("anal_akon_old", "Stari konto", 14),
        ("anal_debt", "Debet", 14),
        ("anal_krdt", "Kredit", 14),
        ("anal_part", "Partner šifra", 12),
        ("anal_pime", "Partner", 40),
        ("anal_doku", "Dokument", 24),
        ("anal_anal", "Tekst", 48),
        ("anal_vrkn", "VRKN", 8),
        ("anal_veza", "Veza", 20),
    )

    def __init__(
        self,
        master: tk.Misc,
        row: dict[str, Any],
        *,
        db_path: Path | None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.row = row
        self.db_path = db_path
        self.on_saved = on_saved
        self.vars: dict[str, tk.StringVar] = {}
        rid = row.get("id")
        self.title(f"Uredi knjižbo · id {rid}")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.geometry("560x520")
        self.minsize(480, 400)

        pad = ttk.Frame(self, padding=12)
        pad.pack(fill="both", expand=True)
        grp = knjiga_group(str(row.get("anal_ctrl") or ""), str(row.get("anal_vrkn") or ""))
        series = knjiga_series(str(row.get("anal_ctrl") or ""), str(row.get("anal_vrkn") or ""))
        ttk.Label(
            pad,
            text=f"Minimax skupina: {grp}  ·  serija {series}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        form = ttk.Frame(pad)
        form.pack(fill="both", expand=True)
        for i, (key, label, width) in enumerate(self._FIELDS):
            ttk.Label(form, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=3, padx=(0, 8)
            )
            var = tk.StringVar(value=str(row.get(key) or ""))
            self.vars[key] = var
            ent = ttk.Entry(form, textvariable=var, width=width)
            ent.grid(row=i, column=1, sticky="ew", pady=3)
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(pad)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Prekliči", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Shrani", style="Accent.TButton", command=self._save).pack(
            side="right", padx=(0, 8)
        )
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._save())

    def _save(self) -> None:
        if self.db_path is None:
            messagebox.showwarning(self.title(), "Ni baze.", parent=self)
            return
        rid = int(self.row.get("id") or 0)
        if not rid:
            return
        values = {k: normalize_text(v.get()) for k, v in self.vars.items()}
        try:
            debt = float(decimal_value(values.get("anal_debt")))
            krdt = float(decimal_value(values.get("anal_krdt")))
        except Exception:
            messagebox.showwarning(self.title(), "Debet / kredit ni veljaven znesek.", parent=self)
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute(
                    """
                    UPDATE kisanal SET
                        anal_ctrl=?, anal_pozi=?, anal_ddok=?, anal_ddur=?,
                        anal_akon=?, anal_akon_old=?, anal_debt=?, anal_krdt=?,
                        anal_part=?, anal_pime=?, anal_doku=?, anal_anal=?,
                        anal_vrkn=?, anal_veza=?
                    WHERE id=?
                    """,
                    (
                        values.get("anal_ctrl", ""),
                        values.get("anal_pozi", ""),
                        values.get("anal_ddok", "") or None,
                        values.get("anal_ddur", "") or None,
                        values.get("anal_akon", ""),
                        values.get("anal_akon_old", ""),
                        debt,
                        krdt,
                        values.get("anal_part", ""),
                        values.get("anal_pime", ""),
                        values.get("anal_doku", ""),
                        values.get("anal_anal", ""),
                        values.get("anal_vrkn", ""),
                        values.get("anal_veza", ""),
                        rid,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            messagebox.showerror(self.title(), str(exc), parent=self)
            return
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass
        self.destroy()
