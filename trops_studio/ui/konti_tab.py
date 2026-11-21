"""Zavihek KONTI — DDV-O (levo) + pivot kontov (desno), chk filter, 2× klik → IR/PR."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from tkinter import ttk
from typing import Any, Callable, Mapping, Sequence

from trops_studio.ddvo_calc import compute_ddvo
from trops_studio.konti_pivot import (
    PivotLine,
    PivotNode,
    build_pivot_tree,
    collect_pivot_lines,
    filter_pivot_lines,
)
from trops_studio.money import is_nonzero, money_text
from trops_studio.ui.collapsible import CollapsibleSection
from trops_studio.ui.search import haystack_matches, search_tokens
from trops_studio.ui.tooltip import ToolTip

ZERO = Decimal("0.00")


class KontiTab:
    def __init__(
        self,
        parent: ttk.Frame,
        *,
        colors: Mapping[str, str],
        pack_search: Callable[..., None],
        on_open_document: Callable[[str, int], None] | None = None,
    ) -> None:
        self.colors = dict(colors)
        self.on_open_document = on_open_document
        self.search_var = tk.StringVar(value="")
        self.period_var = tk.StringVar(value="Obdobje: —")
        self.meta_var = tk.StringVar(value="IR/PR knjižbe → pivot kontov")
        self.total_var = tk.StringVar(value="Skupaj DEBET 0,00  ·  KREDIT 0,00")
        self.filter_info_var = tk.StringVar(value="DDV-O filter: vsa polja")
        self.amount_filter = tk.StringVar(value="NONZERO")
        self._lines: list[PivotLine] = []
        self._ddvo_fields: list[dict[str, Any]] = []
        self._ddvo_chk: dict[str, bool] = {}
        self._pivot_chk: dict[str, bool] = {}
        self._pivot_meta: dict[str, tuple[str, int | None]] = {}
        self._iid = 0

        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 6))
        title_box = ttk.Frame(top, style="Panel.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="KONTI — analitika knjižb", style="SectionTitle.TLabel").pack(
            anchor="w"
        )
        meta = ttk.Frame(title_box, style="Panel.TFrame")
        meta.pack(fill="x", pady=(3, 0))
        ttk.Label(meta, textvariable=self.period_var, style="Muted.TLabel").pack(
            side="left", padx=(0, 18)
        )
        ttk.Label(meta, textvariable=self.meta_var, style="Muted.TLabel").pack(side="left")
        pack_search(
            top,
            self.search_var,
            on_change=self._populate_both,
            clear_command=self.clear_search,
            tip="Išči v pivotu in DDV-O: konto, stranka, listina, znesek, polje …",
        )

        actions = ttk.Frame(parent, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 6))
        ttk.Label(actions, text="Znesek:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        for label, value in (("Vse", "VSE"), ("<> 0", "NONZERO")):
            ttk.Radiobutton(
                actions,
                text=label,
                value=value,
                variable=self.amount_filter,
                command=self._populate_both,
            ).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Vse označi", command=self.check_all).pack(side="left", padx=(12, 4))
        ttk.Button(actions, text="Vse odznači", command=self.uncheck_all).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Razširi vse", command=self.expand_all).pack(side="left", padx=(8, 4))
        ttk.Button(actions, text="Strni vse", command=self.collapse_all).pack(side="left", padx=(0, 8))
        ttk.Label(actions, textvariable=self.filter_info_var, style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        ToolTip(
            actions,
            "Chk v DDV-O filtrira pivot (npr. samo polje 11 → IR osnove).\n"
            "Vse označeno = vsi konti. 2× klik = odpri IR/PR obrazec.\n"
            "Space / klik na Chk preklopi.",
        )

        paned = ttk.Panedwindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True)

        ddvo_frame = ttk.Frame(paned, style="Panel.TFrame")
        pivot_frame = ttk.Frame(paned, style="Panel.TFrame")
        paned.add(ddvo_frame, weight=2)
        paned.add(pivot_frame, weight=3)

        self._build_ddvo_panel(ddvo_frame)
        self._build_pivot_panel(pivot_frame)

    def _build_ddvo_panel(self, parent: ttk.Frame) -> None:
        sec = CollapsibleSection(
            parent,
            "DDV-O — polja (chk = filter kontov)",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True,
            padx=4,
            pady=4,
            accent=self.colors.get("purple", "#6b4cff"),
        )
        sec.pack(fill="both", expand=True)
        sec.set_expand_body(True)
        wrap = ttk.Frame(sec.body, style="Panel.TFrame")
        wrap.pack(fill="both", expand=True)
        cols = ("chk", "code", "description", "exact", "rounded")
        self.ddvo_tree = ttk.Treeview(
            wrap, columns=cols, show="headings", selectmode="browse", height=12
        )
        headings = {
            "chk": ("Chk", 42),
            "code": ("Polje", 55),
            "description": ("Opis", 220),
            "exact": ("Točno", 90),
            "rounded": ("Zaok.", 90),
        }
        for key, (title, width) in headings.items():
            self.ddvo_tree.heading(key, text=title)
            anchor = "center" if key == "chk" else ("e" if key in {"exact", "rounded"} else "w")
            self.ddvo_tree.column(
                key, width=width, anchor=anchor, stretch=key == "description", minwidth=36
            )
        ybar = ttk.Scrollbar(wrap, orient="vertical", command=self.ddvo_tree.yview)
        self.ddvo_tree.configure(yscrollcommand=ybar.set)
        self.ddvo_tree.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        self.ddvo_tree.tag_configure("odd", background="#15213a")
        self.ddvo_tree.tag_configure("checked", background="#1d3a2a")
        self.ddvo_tree.bind("<Button-1>", self._on_ddvo_click, add="+")
        self.ddvo_tree.bind("<space>", self._toggle_ddvo_selected, add="+")
        self.ddvo_tree.bind("<Double-1>", self._on_ddvo_double, add="+")

    def _build_pivot_panel(self, parent: ttk.Frame) -> None:
        sec = CollapsibleSection(
            parent,
            "Pivot kontov (IR + PR)",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors.get("muted", "#a5b0c8"),
            initially_open=True,
            padx=4,
            pady=4,
            accent=self.colors.get("accent", "#4f7cff"),
        )
        sec.pack(fill="both", expand=True)
        sec.set_expand_body(True)
        ttk.Label(sec.body, textvariable=self.total_var, style="Muted.TLabel").pack(
            anchor="e", pady=(0, 4)
        )
        wrap = ttk.Frame(sec.body, style="Panel.TFrame")
        wrap.pack(fill="both", expand=True)
        self.pivot_tree = ttk.Treeview(
            wrap,
            columns=("chk", "debet", "kredit"),
            show="tree headings",
            selectmode="browse",
        )
        self.pivot_tree.heading("#0", text="Oznake vrstic")
        self.pivot_tree.heading("chk", text="Chk")
        self.pivot_tree.heading("debet", text="Vsota DEBET")
        self.pivot_tree.heading("kredit", text="Vsota KREDIT")
        self.pivot_tree.column("#0", width=280, minwidth=160, stretch=True)
        self.pivot_tree.column("chk", width=42, anchor="center", stretch=False)
        self.pivot_tree.column("debet", width=110, anchor="e")
        self.pivot_tree.column("kredit", width=110, anchor="e")
        ybar = ttk.Scrollbar(wrap, orient="vertical", command=self.pivot_tree.yview)
        xbar = ttk.Scrollbar(wrap, orient="horizontal", command=self.pivot_tree.xview)
        self.pivot_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.pivot_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.pivot_tree.tag_configure("group", foreground="#ffe08a")
        self.pivot_tree.tag_configure("konto", foreground="#9ecbff")
        self.pivot_tree.tag_configure("party", foreground="#f3f6ff")
        self.pivot_tree.tag_configure("neg", foreground="#ff7b7b")
        self.pivot_tree.tag_configure("total", foreground="#34c77b", font=("Segoe UI Semibold", 9))
        self.pivot_tree.bind("<Button-1>", self._on_pivot_click, add="+")
        self.pivot_tree.bind("<space>", self._toggle_pivot_selected, add="+")
        self.pivot_tree.bind("<Double-1>", self._on_pivot_double, add="+")

    def clear_search(self) -> None:
        self.search_var.set("")
        self._populate_both()

    def tab_title(self, *, lines: int | None = None) -> str:
        n = len(self._lines) if lines is None else lines
        return f"  KONTI  {n}  "

    def set_open_handler(self, handler: Callable[[str, int], None]) -> None:
        self.on_open_document = handler

    def refresh(
        self,
        ir_rows: Sequence[Mapping[str, Any]],
        pr_rows: Sequence[Mapping[str, Any]],
        *,
        period_from: date | None = None,
        period_to: date | None = None,
    ) -> None:
        if period_from and period_to:
            self.period_var.set(
                f"Obdobje: {period_from.strftime('%d.%m.%Y')} – {period_to.strftime('%d.%m.%Y')}"
            )
        else:
            self.period_var.set("Obdobje: —")

        self._lines = collect_pivot_lines(ir_rows, pr_rows)
        try:
            summary = compute_ddvo(
                ir_rows, pr_rows, period_from=period_from, period_to=period_to
            )
            self._ddvo_fields = list(summary.get("fields") or [])
        except Exception:
            self._ddvo_fields = []

        # ohrani chk; nova polja privzeto označena
        codes = [str(f.get("code") or "") for f in self._ddvo_fields if f.get("code")]
        prev = dict(self._ddvo_chk)
        self._ddvo_chk = {c: prev.get(c, True) for c in codes if c}

        self.meta_var.set(
            f"IR {len(ir_rows)} · PR {len(pr_rows)} · knjižb {len(self._lines)} · "
            f"DDV-O polj {len(self._ddvo_fields)}"
        )
        self._populate_both()

    def check_all(self) -> None:
        for code in self._ddvo_chk:
            self._ddvo_chk[code] = True
        for key in list(self._pivot_chk):
            self._pivot_chk[key] = True
        self._populate_both()

    def uncheck_all(self) -> None:
        for code in self._ddvo_chk:
            self._ddvo_chk[code] = False
        for key in list(self._pivot_chk):
            self._pivot_chk[key] = False
        self._populate_both()

    def _active_ddvo_codes(self) -> set[str] | None:
        """None = brez filtra (vsa polja ali nobeno); sicer množica označenih."""
        if not self._ddvo_chk:
            return None
        checked = {c for c, on in self._ddvo_chk.items() if on}
        if not checked:
            return set()  # vse odznačeno → prazen pivot
        if len(checked) >= len(self._ddvo_chk):
            return None
        return checked

    def _update_filter_info(self) -> None:
        active = self._active_ddvo_codes()
        if active is None:
            self.filter_info_var.set("DDV-O filter: vsa polja")
        elif not active:
            self.filter_info_var.set("DDV-O filter: nič (prazen pivot)")
        else:
            shown = ", ".join(sorted(active, key=lambda x: (len(x), x))[:12])
            more = f" +{len(active) - 12}" if len(active) > 12 else ""
            self.filter_info_var.set(f"DDV-O filter: {shown}{more}")

    def _populate_both(self) -> None:
        self._populate_ddvo()
        self._populate_pivot()
        self._update_filter_info()

    def _populate_ddvo(self) -> None:
        tree = self.ddvo_tree
        tree.delete(*tree.get_children())
        tokens = search_tokens(self.search_var.get())
        nonzero = self.amount_filter.get() == "NONZERO"
        visible = 0
        for field in self._ddvo_fields:
            code = str(field.get("code") or "")
            if not code:
                continue
            exact = field.get("exact")
            # ddvo_summary: zaokroženo je v "value" (cela EUR, ROUND_HALF_UP)
            rounded = field.get("rounded", field.get("value"))
            label = field.get("description") or field.get("label") or ""
            if nonzero and code not in {"51", "52"} and not (
                is_nonzero(exact) or is_nonzero(rounded)
            ):
                continue
            chunks = (
                code,
                label,
                field.get("section"),
                field.get("source"),
                money_text(exact),
                money_text(rounded),
            )
            if tokens and not haystack_matches(tokens, chunks):
                continue
            checked = bool(self._ddvo_chk.get(code, True))
            tags = ("checked",) if checked else (("odd",) if visible % 2 else ())
            # Zaok. = cela EUR (npr. 2.193), Točno ostane z decimalami
            try:
                r_amt = Decimal(str(rounded or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                rounded_txt = f"{int(r_amt):,}".replace(",", ".")
            except Exception:
                rounded_txt = money_text(rounded)
            tree.insert(
                "",
                "end",
                iid=f"ddvo:{code}",
                tags=tags,
                values=(
                    "☑" if checked else "☐",
                    code,
                    label,
                    money_text(exact),
                    rounded_txt,
                ),
            )
            visible += 1

    def _money_cell(self, amount: Decimal) -> str:
        if not is_nonzero(amount):
            return "0,00"
        return money_text(amount)

    def _chk_mark(self, key: str, *, default: bool = True) -> str:
        on = self._pivot_chk.get(key, default)
        self._pivot_chk[key] = on
        return "☑" if on else "☐"

    def _insert_node(self, parent: str, node: PivotNode) -> str:
        self._iid += 1
        iid = f"n{self._iid}"
        tags = [node.level]
        if node.debet < ZERO or node.kredit < ZERO:
            tags.append("neg")
        self.pivot_tree.insert(
            parent,
            "end",
            iid=iid,
            text=node.label,
            open=bool(node.open),
            tags=tuple(tags),
            values=(
                self._chk_mark(iid, default=True),
                self._money_cell(node.debet),
                self._money_cell(node.kredit),
            ),
        )
        self._pivot_meta[iid] = (node.kind, node.doc_id)
        for child in node.children:
            self._insert_node(iid, child)
        return iid

    def _populate_pivot(self) -> None:
        tree = self.pivot_tree
        tree.delete(*tree.get_children())
        self._iid = 0
        self._pivot_meta.clear()
        # ohrani chk po (kind, doc_id); iids se spremenijo
        prev_doc_chk = {
            key: on
            for key, on in self._pivot_chk.items()
            if isinstance(key, str) and key.startswith("doc:")
        }
        self._pivot_chk = dict(prev_doc_chk)

        tokens = search_tokens(self.search_var.get())
        nonzero = self.amount_filter.get() == "NONZERO"
        ddvo = self._active_ddvo_codes()
        filtered = filter_pivot_lines(
            self._lines,
            tokens=tokens,
            nonzero_only=nonzero,
            ddvo_codes=ddvo,
        )
        roots, total_d, total_k = build_pivot_tree(filtered)
        for node in roots:
            node.open = True
            self._insert_node("", node)
        # privzeti chk na document nivoju iz prev_doc_chk
        for iid, (kind, doc_id) in list(self._pivot_meta.items()):
            if doc_id is None:
                continue
            dkey = f"doc:{kind}:{doc_id}"
            if dkey in prev_doc_chk:
                self._pivot_chk[iid] = prev_doc_chk[dkey]
                vals = list(tree.item(iid, "values"))
                if vals:
                    vals[0] = "☑" if prev_doc_chk[dkey] else "☐"
                    tree.item(iid, values=vals)

        tree.insert(
            "",
            "end",
            iid="total",
            text="Skupna vsota",
            open=False,
            tags=("total",),
            values=("", self._money_cell(total_d), self._money_cell(total_k)),
        )
        self._pivot_meta["total"] = ("", None)
        self.total_var.set(
            f"Skupaj DEBET {money_text(total_d)}  ·  KREDIT {money_text(total_k)}"
            f"  ·  listov {len(filtered)}"
        )

    def _on_ddvo_click(self, event: tk.Event) -> str | None:
        region = self.ddvo_tree.identify_region(event.x, event.y)
        if region != "cell":
            return None
        col = self.ddvo_tree.identify_column(event.x)
        if col != "#1":  # chk
            return None
        iid = self.ddvo_tree.identify_row(event.y)
        if not iid:
            return None
        self._toggle_ddvo_iid(iid)
        return "break"

    def _toggle_ddvo_selected(self, _event: tk.Event | None = None) -> str | None:
        sel = self.ddvo_tree.selection()
        if not sel:
            return None
        self._toggle_ddvo_iid(sel[0])
        return "break"

    def _toggle_ddvo_iid(self, iid: str) -> None:
        code = iid.split(":", 1)[-1] if iid.startswith("ddvo:") else ""
        if not code:
            return
        self._ddvo_chk[code] = not bool(self._ddvo_chk.get(code, True))
        self._populate_both()

    def _on_ddvo_double(self, _event: tk.Event | None = None) -> None:
        """2× klik na DDV-O polje → odpri prvo listino, ki prispeva v polje."""
        sel = self.ddvo_tree.selection()
        if not sel:
            return
        code = sel[0].split(":", 1)[-1]
        if code in {"51", "52"}:
            return
        for line in self._lines:
            if code in line.ddvo_codes and line.doc_id:
                self._open(line.kind, line.doc_id)
                return

    def _on_pivot_click(self, event: tk.Event) -> str | None:
        region = self.pivot_tree.identify_region(event.x, event.y)
        if region not in {"cell", "tree"}:
            return None
        col = self.pivot_tree.identify_column(event.x)
        # #1 = tree, #2 = chk
        if col != "#2":
            return None
        iid = self.pivot_tree.identify_row(event.y)
        if not iid or iid == "total":
            return None
        self._toggle_pivot_iid(iid)
        return "break"

    def _toggle_pivot_selected(self, _event: tk.Event | None = None) -> str | None:
        sel = self.pivot_tree.selection()
        if not sel or sel[0] == "total":
            return None
        self._toggle_pivot_iid(sel[0])
        return "break"

    def _toggle_pivot_iid(self, iid: str) -> None:
        on = not bool(self._pivot_chk.get(iid, True))
        self._set_pivot_subtree_chk(iid, on)
        kind, doc_id = self._pivot_meta.get(iid, ("", None))
        if doc_id is not None and kind:
            self._pivot_chk[f"doc:{kind}:{doc_id}"] = on

    def _set_pivot_subtree_chk(self, iid: str, on: bool) -> None:
        self._pivot_chk[iid] = on
        vals = list(self.pivot_tree.item(iid, "values") or ())
        if vals:
            vals = list(vals)
            vals[0] = "☑" if on else "☐"
            self.pivot_tree.item(iid, values=vals)
        for child in self.pivot_tree.get_children(iid):
            self._set_pivot_subtree_chk(child, on)

    def _on_pivot_double(self, _event: tk.Event | None = None) -> None:
        sel = self.pivot_tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == "total":
            return
        kind, doc_id = self._pivot_meta.get(iid, ("", None))
        if kind and doc_id:
            self._open(kind, int(doc_id))
            return
        # poišči prvega potomca z listino
        for child in self._walk_iids(iid):
            k, d = self._pivot_meta.get(child, ("", None))
            if k and d:
                self._open(k, int(d))
                return

    def _walk_iids(self, iid: str) -> list[str]:
        out: list[str] = []
        for child in self.pivot_tree.get_children(iid):
            out.append(child)
            out.extend(self._walk_iids(child))
        return out

    def _open(self, kind: str, doc_id: int) -> None:
        if self.on_open_document and kind in {"IR", "PR"} and doc_id:
            self.on_open_document(kind, int(doc_id))

    def expand_all(self) -> None:
        def _walk(iid: str) -> None:
            self.pivot_tree.item(iid, open=True)
            for child in self.pivot_tree.get_children(iid):
                _walk(child)

        for root in self.pivot_tree.get_children(""):
            if root == "total":
                continue
            _walk(root)

    def collapse_all(self) -> None:
        def _walk(iid: str) -> None:
            for child in self.pivot_tree.get_children(iid):
                _walk(child)
            if self.pivot_tree.get_children(iid):
                self.pivot_tree.item(iid, open=False)

        for root in self.pivot_tree.get_children(""):
            if root == "total":
                continue
            _walk(root)
            self.pivot_tree.item(root, open=True)
