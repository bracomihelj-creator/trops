"""Headless AppService — 100 % poslovna orkestracija Trops Studio brez Tkinter UI."""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio import APP_TITLE
from trops_studio.config import DEFAULT_MINIMAX_OUT
from trops_studio_web import __version__
from trops_studio.accounts import allocate_pr_accounts, remember_customer_rule, remember_supplier_rule
from trops_studio.companies import (
    company_ddv_cadence,
    company_key,
    company_name,
    company_org_id,
    company_source_kind,
    company_tax,
    company_zst,
    find_company,
    load_companies,
)
from trops_studio.config import (
    DEFAULT_INTEGRA_SQL,
    DEFAULT_IR_EU_REVENUE_ACCOUNT,
    DEFAULT_IR_REVENUE_ACCOUNT,
    DEFAULT_PR_EXPENSE_ACCOUNT,
    company_db_path,
    migrate_legacy_projest_db,
)
from trops_studio.db import Database
from trops_studio.ddvo_calc import compute_ddvo as run_compute_ddvo, ir_row_to_kir, pr_row_to_kpr
from trops_studio.ir_list_view import apply_ir_eu_sale, ir_customer_region, ir_display_osnova
from trops_studio.konti_pivot import build_pivot_tree, collect_pivot_lines
from trops_studio.money import (
    date_text,
    decimal_value,
    is_nonzero,
    money_text,
    normalize_vat_id,
    parse_date,
)
from trops_studio.minimax_parties import sync_customers_from_minimax
from trops_studio.minimax_runtime import check_minimax_api
from trops_studio.minimax_sync import confirm_documents, sync_ready_to_minimax
from trops_studio.pr_list_view import (
    odhodek_summary,
    pr_corrected_region,
    pr_odhodek_lines,
    pr_p8_amount,
    pr_si_vat_on_non_domestic,
    pr_supplier_region,
    region_label,
)
from trops_studio.row_status import status_filter_matches
from trops_studio.session_prefs import load_session, parse_iso_date, save_session
from trops_studio.ui.period import (
    PERIOD_CHOICES,
    default_period_for_ddv_cadence,
    format_si_date,
    month_bounds,
    parse_si_date,
    period_bounds,
    period_label_for_range,
    previous_month_bounds,
)
from trops_studio.ui.search import haystack_matches, row_search_chunks, search_tokens

log = logging.getLogger("trops_studio_web.service")
IR_BOOKS = ("Darila", "Fitness", "Paragoni", "Fakture", "KIR")


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return money_text(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    return str(value)


class AppService:
    def __init__(self) -> None:
        migrate_legacy_projest_db()
        self._lock = threading.RLock()
        self.progress_callback = None
        self._session = load_session()
        self.company_registry_path, self.companies = load_companies()
        self.active_company: dict[str, Any] | None = None
        self._company_db_key = ""
        self.db = Database()
        self.filter_from_date, self.filter_to_date = previous_month_bounds()
        self.data_span_from: date | None = None
        self.data_span_to: date | None = None
        self.filter_rev = "vse"
        self.integra_sql_dir = str(self._session.get("integra_sql_dir") or DEFAULT_INTEGRA_SQL)
        self.integra_auto_irpr = self._as_bool(self._session.get("integra_auto_irpr"), True)
        self.company_search = str(self._session.get("company_search") or "")
        self.status = f"SQLite: {self.db.path}"
        self.chk_state: dict[str, bool] = {}
        self._ir_cache: list[dict[str, Any]] = []
        self._pr_cache: list[dict[str, Any]] = []
        self._party_cache: list[dict[str, Any]] = []
        self.ir_books = {b: b in {"Darila", "Fitness"} for b in IR_BOOKS}
        self.filters: dict[str, Any] = {
            "ir_search": "",
            "pr_search": "",
            "party_search": "",
            "ir_status": "VSI",
            "pr_status": "VSI",
            "ir_amount": "VSE",
            "pr_amount": "VSE",
            "ir_si": False,
            "ir_eu": False,
            "ir_foreign": False,
            "ir_vat": False,
            "pr_si": False,
            "pr_foreign": False,
            "pr_excluded": False,
            "pr_eu10": False,
            "pr_eu11": False,
            "pr_exempt": False,
            "pr_76a": False,
            "pr_multi": False,
            "pr_si_vat": False,
            "pr_vat": False,
        }
        self._restore_period_from_session()
        key = str(self._session.get("company_key") or "").strip()
        if key:
            company = find_company(self.companies, key)
            if company:
                self._activate_company(company, load_data=True)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _as_bool(value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().casefold()
        if text in {"1", "true", "da", "yes", "on"}:
            return True
        if text in {"0", "false", "ne", "no", "off"}:
            return False
        return default

    def _restore_period_from_session(self) -> None:
        start = parse_iso_date(self._session.get("period_from"))
        end = parse_iso_date(self._session.get("period_to"))
        if start and end and end >= start:
            self.filter_from_date, self.filter_to_date = start, end
            return
        label = str(self._session.get("period_label") or "").strip()
        year_raw = str(self._session.get("period_year") or "").strip()
        if label:
            try:
                year = int(year_raw) if year_raw else previous_month_bounds()[0].year
            except ValueError:
                year = previous_month_bounds()[0].year
            bounds = period_bounds(year, label)
            if bounds:
                self.filter_from_date, self.filter_to_date = bounds

    def _persist_session(self) -> None:
        key = company_key(self.active_company) if self.active_company else ""
        data = {
            "company_key": key,
            "company_search": self.company_search,
            "period_from": self.filter_from_date.isoformat(),
            "period_to": self.filter_to_date.isoformat(),
            "period_label": period_label_for_range(self.filter_from_date, self.filter_to_date),
            "period_year": str(self.filter_from_date.year),
            "integra_sql_dir": self.integra_sql_dir,
            "integra_auto_irpr": bool(self.integra_auto_irpr),
        }
        save_session(data)
        self._session = data

    def _period_payload(self) -> dict[str, Any]:
        return {
            "from": self.filter_from_date.isoformat(),
            "to": self.filter_to_date.isoformat(),
            "from_si": format_si_date(self.filter_from_date),
            "to_si": format_si_date(self.filter_to_date),
            "label": period_label_for_range(self.filter_from_date, self.filter_to_date),
            "year": self.filter_from_date.year,
            "choices": list(PERIOD_CHOICES),
            "rev": self.filter_rev,
        }

    def _company_payload(self, company: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        c = company or self.active_company
        if not c:
            return None
        return {
            "key": company_key(c),
            "zst": company_zst(c),
            "name": company_name(c),
            "org_id": company_org_id(c),
            "tax": company_tax(c),
            "source_kind": company_source_kind(c),
            "ddv_cadence": company_ddv_cadence(c),
            "db_path": str(company_db_path(company_zst(c))),
        }

    def _row_matches_period_rev(self, row: Mapping[str, Any]) -> bool:
        if self.filter_rev in {"", "vse", None}:
            return True
        return str(row.get("period_revision") or "1") == str(self.filter_rev)

    def _row_in_period(self, row: Mapping[str, Any], *, date_keys: tuple[str, ...]) -> bool:
        if not self._row_matches_period_rev(row):
            return False
        for key in date_keys:
            raw = row.get(key)
            if not raw:
                continue
            try:
                parsed = parse_date(raw)
            except Exception:
                parsed = None
            if parsed is None:
                continue
            return self.filter_from_date <= parsed <= self.filter_to_date
        return True

    def _party_by_vat_index(self) -> dict[str, dict[str, Any]]:
        idx: dict[str, dict[str, Any]] = {}
        for party in self._party_cache:
            vat = normalize_vat_id(party.get("vat_id") or party.get("tax_number"))
            if vat and vat not in idx:
                idx[vat] = party
        return idx

    def _party_by_id_index(self) -> dict[int, dict[str, Any]]:
        idx: dict[int, dict[str, Any]] = {}
        for party in self._party_cache:
            try:
                idx[int(party["id"])] = party
            except (KeyError, TypeError, ValueError):
                continue
        return idx

    def _party_for_row(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        by_id = self._party_by_id_index()
        by_vat = self._party_by_vat_index()
        if row.get("party_id"):
            try:
                party = by_id.get(int(row["party_id"]))
            except (TypeError, ValueError):
                party = None
            if party:
                return party
        vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        return by_vat.get(vat) if vat else None

    def _active_ir_books(self) -> set[str]:
        return {b for b, on in self.ir_books.items() if on}

    def _period_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ir_rows = [
            row
            for row in self._ir_cache
            if self._row_in_period(row, date_keys=("document_date", "booking_date"))
        ]
        pr_rows = [
            row
            for row in self._pr_cache
            if self._row_in_period(row, date_keys=("received_date", "document_date", "booking_date"))
        ]
        return ir_rows, pr_rows

    def _update_data_span(self) -> None:
        dates: list[date] = []
        for row in self._ir_cache:
            for key in ("document_date", "booking_date"):
                try:
                    d = parse_date(row.get(key))
                except Exception:
                    d = None
                if d:
                    dates.append(d)
        for row in self._pr_cache:
            for key in ("received_date", "document_date", "booking_date"):
                try:
                    d = parse_date(row.get(key))
                except Exception:
                    d = None
                if d:
                    dates.append(d)
        if dates:
            self.data_span_from, self.data_span_to = min(dates), max(dates)
        else:
            self.data_span_from = self.data_span_to = None

    def _activate_company(self, company: Mapping[str, Any], *, load_data: bool) -> None:
        zst = company_zst(company)
        path = company_db_path(zst)
        self.db = Database(path)
        self.active_company = dict(company)
        self._company_db_key = company_key(company)
        self.status = f"SQLite: {self.db.path}"
        kind = company_source_kind(company)
        if kind == "integra":
            self.ir_books = {b: b in {"Paragoni", "Fakture", "KIR"} for b in IR_BOOKS}
        elif kind in {"kirkpr", "furs"}:
            self.ir_books = {b: b == "KIR" for b in IR_BOOKS}
        else:
            self.ir_books = {b: b in {"Darila", "Fitness"} for b in IR_BOOKS}
        if load_data:
            self.refresh_all()
        self._persist_session()

    # ------------------------------------------------------------------ public
    def bootstrap(self) -> dict[str, Any]:
        with self._lock:
            ir_rows, pr_rows = self._filtered_ir(), self._filtered_pr()
            return _safe(
                {
                    "ok": True,
                    "version": __version__,
                    "title": APP_TITLE,
                    "workflow": "1 Uvoz → 2 Preveri IR/PR → 3 Manjkajoče → 4 Potrdi → 5 Minimax",
                    "company": self._company_payload(),
                    "companies": self.list_companies(self.company_search),
                    "period": self._period_payload(),
                    "status": self.status,
                    "warnings": (["Seznam podjetij ni dosegljiv ali je prazen. Preveri settings.json: evidenca_firm_root in kirkpr_*_root."] if not self.companies else []),
                    "filters": dict(self.filters),
                    "ir_books": dict(self.ir_books),
                    "integra_sql_dir": self.integra_sql_dir,
                    "summary": {
                        "ir_count": len(ir_rows),
                        "pr_count": len(pr_rows),
                        "parties": len(self._party_cache),
                        "ir_value": next(
                            (t["value"] for t in [self._ir_totals(ir_rows)] if True),
                            "0,00",
                        ),
                        "pr_value": next(
                            (t["value"] for t in [self._pr_totals(pr_rows)] if True),
                            "0,00",
                        ),
                    },
                    "nav": [
                        {"id": "ir", "label": "Izdani računi (IR)"},
                        {"id": "pr", "label": "Prejeti računi (PR)"},
                        {"id": "ddvo", "label": "Obrazec DDV-O"},
                        {
                            "id": "knjige",
                            "label": "Knjige IR/PR",
                            "children": [
                                {"id": "knjiga_ir", "label": "Knjiga IR"},
                                {"id": "knjiga_pr", "label": "Knjiga PR"},
                            ],
                        },
                        {"id": "konti", "label": "KONTI (pivot)"},
                        {"id": "parties", "label": "Stranke"},
                        {"id": "analysis", "label": "Analitika"},
                        {"id": "knjizbe", "label": "Vse knjižbe"},
                    ],
                }
            )

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return _safe({"ok": True, "status": self.status, "company": self._company_payload(), "period": self._period_payload()})

    def get_company(self) -> dict[str, Any]:
        with self._lock:
            payload = self._company_payload()
            return _safe({"ok": bool(payload), "company": payload})

    def get_period(self) -> dict[str, Any]:
        with self._lock:
            return _safe({"ok": True, **self._period_payload()})

    def list_companies(self, search: str = "") -> list[dict[str, Any]]:
        self.company_search = str(search or "")
        query = re.sub(r"\s+", " ", self.company_search.strip().casefold())
        terms = query.split() if query else []
        rows: list[dict[str, Any]] = []
        for company in self.companies:
            zst = company_zst(company)
            name = company_name(company)
            org = company_org_id(company)
            tax = company_tax(company)
            haystack = " ".join((zst, name, tax, org)).casefold()
            if terms and any(term not in haystack for term in terms):
                continue
            rows.append(
                {
                    "key": company_key(company),
                    "zst": zst or "—",
                    "name": name,
                    "org": org or "—",
                    "tax": tax or "",
                    "source_kind": company_source_kind(company),
                    "active": bool(self.active_company and company_key(self.active_company) == company_key(company)),
                }
            )
        return rows

    def select_company(self, key: str = "", zst: str = "", name: str = "", org: str = "") -> dict[str, Any]:
        with self._lock:
            company = None
            if key:
                company = find_company(self.companies, key)
            if company is None and zst:
                for c in self.companies:
                    if company_zst(c) == str(zst).strip() or company_key(c) == f"zst-{str(zst).strip()}":
                        company = c
                        break
            if company is None:
                return {"ok": False, "error": "Podjetje ni najdeno."}
            # privzeto obdobje po cadence, razen če že imamo sejo za isto firmo
            same = self.active_company and company_key(self.active_company) == company_key(company)
            if not same:
                start, end = default_period_for_ddv_cadence(company_ddv_cadence(company))
                # ohrani session period if same session company was restored already
                sess_key = str(self._session.get("company_key") or "")
                if sess_key == company_key(company):
                    s = parse_iso_date(self._session.get("period_from"))
                    e = parse_iso_date(self._session.get("period_to"))
                    if s and e and e >= s:
                        start, end = s, e
                self.filter_from_date, self.filter_to_date = start, end
            self._activate_company(company, load_data=True)
            self.status = f"Podjetje: {company_zst(company)} • {company_name(company)}"
            return self.bootstrap()

    def set_period(
        self,
        period_from: str = "",
        period_to: str = "",
        label: str = "",
        year: int | str = "",
        rev: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            if rev:
                self.filter_rev = str(rev)
            if label:
                try:
                    y = int(year) if str(year).strip() else self.filter_from_date.year
                except ValueError:
                    y = self.filter_from_date.year
                bounds = period_bounds(y, label) or month_bounds(y, self.filter_from_date.month)
                self.filter_from_date, self.filter_to_date = bounds
            else:
                start = parse_si_date(period_from) or parse_iso_date(period_from) or self.filter_from_date
                end = parse_si_date(period_to) or parse_iso_date(period_to) or self.filter_to_date
                if end < start:
                    start, end = end, start
                self.filter_from_date, self.filter_to_date = start, end
            self._persist_session()
            self.status = (
                f"Obdobje {format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)}"
            )
            return self.bootstrap()

    def shift_period(self, delta: int = 1) -> dict[str, Any]:
        with self._lock:
            label = period_label_for_range(self.filter_from_date, self.filter_to_date)
            try:
                index = PERIOD_CHOICES.index(label)
            except ValueError:
                index = max(0, self.filter_from_date.month - 1)
            index = (index + int(delta)) % len(PERIOD_CHOICES)
            bounds = period_bounds(self.filter_from_date.year, PERIOD_CHOICES[index]) or month_bounds(
                self.filter_from_date.year, self.filter_from_date.month
            )
            self.filter_from_date, self.filter_to_date = bounds
            self._persist_session()
            return self.bootstrap()

    def reset_period(self) -> dict[str, Any]:
        with self._lock:
            if self.data_span_from and self.data_span_to:
                self.filter_from_date, self.filter_to_date = self.data_span_from, self.data_span_to
            self._persist_session()
            return self.bootstrap()

    def set_filters(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if filters:
                for k, v in dict(filters).items():
                    if k in self.filters:
                        self.filters[k] = v
                    if k == "ir_books" and isinstance(v, dict):
                        for book, on in v.items():
                            if book in self.ir_books:
                                self.ir_books[book] = bool(on)
            return {"ok": True, "filters": dict(self.filters), "ir_books": dict(self.ir_books)}

    def set_chk(self, kind: str, row_id: int | str, checked: bool) -> dict[str, Any]:
        with self._lock:
            key = f"{str(kind).lower()}:{int(row_id)}"
            self.chk_state[key] = bool(checked)
            return {"ok": True, "key": key, "checked": bool(checked)}

    def set_chk_all(self, kind: str, checked: bool, ids: Sequence[Any] | None = None) -> dict[str, Any]:
        with self._lock:
            kind_l = str(kind).lower()
            if ids is None:
                rows = self._filtered_ir() if kind_l == "ir" else self._filtered_pr()
                ids = [r["id"] for r in rows]
            for rid in ids:
                self.chk_state[f"{kind_l}:{int(rid)}"] = bool(checked)
            return {"ok": True, "count": len(list(ids)), "checked": bool(checked)}

    def refresh_all(self) -> dict[str, Any]:
        with self._lock:
            self._ir_cache = self.db.list_ir()
            self._pr_cache = self.db.list_pr()
            self._party_cache = self.db.list_parties()
            self._update_data_span()
            self.status = (
                f"Osveženo · IR {len(self._ir_cache)} · PR {len(self._pr_cache)} · "
                f"stranke {len(self._party_cache)} · {Path(self.db.path).name}"
            )
            return self.bootstrap()

    # ------------------------------------------------------------------ lists
    def _ir_totals(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        net = Decimal("0")
        for row in rows:
            party = self._party_for_row(row)
            classified = apply_ir_eu_sale(row, party)
            net += ir_display_osnova(classified)
        return {"value": money_text(net), "count": len(rows)}

    def _pr_totals(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        net = Decimal("0")
        for row in rows:
            party = self._party_for_row(row)
            region = pr_corrected_region(row, party) if pr_si_vat_on_non_domestic(row, party) else pr_supplier_region(row, party)
            net += pr_p8_amount(row, region) + decimal_value(row.get("eu_goods")) + decimal_value(row.get("eu_services"))
        return {"value": money_text(net), "count": len(rows)}

    def _filtered_ir(self) -> list[dict[str, Any]]:
        tokens = search_tokens(str(self.filters.get("ir_search") or ""))
        books = self._active_ir_books()
        status_filter = str(self.filters.get("ir_status") or "VSI")
        nonzero_only = str(self.filters.get("ir_amount") or "VSE") == "NONZERO"
        only_si = bool(self.filters.get("ir_si"))
        only_eu = bool(self.filters.get("ir_eu"))
        only_third = bool(self.filters.get("ir_foreign"))
        only_vat = bool(self.filters.get("ir_vat"))
        any_region = only_si or only_eu or only_third
        out: list[dict[str, Any]] = []
        for row in self._ir_cache:
            book = str(row.get("book") or "")
            if books and book not in books:
                continue
            if not self._row_in_period(row, date_keys=("document_date", "booking_date")):
                continue
            key = f"ir:{row['id']}"
            checked = bool(self.chk_state.get(key))
            if status_filter == "CHK" and not checked:
                continue
            if status_filter not in {"VSI", "CHK"} and not status_filter_matches(
                row.get("status"), status_filter, has_account=bool(row.get("account"))
            ):
                continue
            party = self._party_for_row(row)
            classified = apply_ir_eu_sale(dict(row), party)
            region = ir_customer_region(classified, party)
            if any_region and not (
                (only_si and region == "SI")
                or (only_eu and region == "EU")
                or (only_third and region == "FOREIGN")
            ):
                continue
            if only_vat and not normalize_vat_id(row.get("vat_id")):
                continue
            vat_22 = decimal_value(classified.get("vat_22"))
            vat_95 = decimal_value(classified.get("vat_95"))
            vat = vat_22 + vat_95
            net = ir_display_osnova(classified)
            gross = decimal_value(classified.get("total"))
            if not is_nonzero(gross):
                gross = net + vat
            if nonzero_only and not (is_nonzero(net) or is_nonzero(vat) or is_nonzero(gross)):
                continue
            chunks = row_search_chunks(
                row,
                extra=("IR", book, region_label(region), money_text(net), money_text(vat)),
            )
            if not haystack_matches(tokens, chunks):
                continue
            item = dict(classified)
            item.update(
                {
                    "id": row["id"],
                    "checked": checked,
                    "region": region,
                    "region_label": region_label(region),
                    "net_display": money_text(net),
                    "vat_22_display": money_text(vat_22),
                    "vat_95_display": money_text(vat_95),
                    "vat_display": money_text(vat),
                    "gross_display": money_text(gross),
                    "document_date_si": date_text(row.get("document_date")),
                }
            )
            out.append(item)
        return out

    def _filtered_pr(self) -> list[dict[str, Any]]:
        tokens = search_tokens(str(self.filters.get("pr_search") or ""))
        status_filter = str(self.filters.get("pr_status") or "VSI")
        nonzero_only = str(self.filters.get("pr_amount") or "VSE") == "NONZERO"
        only_si = bool(self.filters.get("pr_si"))
        only_third = bool(self.filters.get("pr_foreign"))
        only_excluded = bool(self.filters.get("pr_excluded"))
        only_eu10 = bool(self.filters.get("pr_eu10"))
        only_eu11 = bool(self.filters.get("pr_eu11"))
        only_exempt = bool(self.filters.get("pr_exempt"))
        only_76a = bool(self.filters.get("pr_76a"))
        only_multi = bool(self.filters.get("pr_multi"))
        only_si_vat = bool(self.filters.get("pr_si_vat"))
        only_vat = bool(self.filters.get("pr_vat"))
        out: list[dict[str, Any]] = []
        for row in self._pr_cache:
            if not self._row_in_period(row, date_keys=("received_date", "document_date", "booking_date")):
                continue
            key = f"pr:{row['id']}"
            checked = bool(self.chk_state.get(key))
            excluded_amt = decimal_value(row.get("excluded"))
            exempt_amt = (
                decimal_value(row.get("exempt_on"))
                + decimal_value(row.get("exempt_non"))
                + decimal_value(row.get("exempt_os"))
            )
            f76a_amt = decimal_value(row.get("f76a"))
            acc = allocate_pr_accounts(row)
            eu_g = decimal_value(row.get("eu_goods"))
            eu_s = decimal_value(row.get("eu_services"))
            has_eu10 = is_nonzero(eu_g)
            has_eu11 = is_nonzero(eu_s)
            has_eu_purchase = has_eu10 or has_eu11
            has_excl = is_nonzero(excluded_amt)
            has_exempt = is_nonzero(exempt_amt)
            has_76a = is_nonzero(f76a_amt)
            lines = pr_odhodek_lines(row)
            party = self._party_for_row(row)
            geo = pr_supplier_region(row, party)
            si_vat_err = pr_si_vat_on_non_domestic(row, party)
            region = pr_corrected_region(row, party) if si_vat_err else geo
            has_acc = bool(acc.get("odhodek01") or acc.get("odhodek10") or acc.get("odhodek11") or (has_excl and acc.get("odhodek_excluded")))
            if only_vat and not normalize_vat_id(row.get("vat_id")):
                continue
            if status_filter == "CHK" and not checked:
                continue
            if status_filter == "NO_ACCOUNT" and has_acc:
                continue
            if status_filter not in {"VSI", "CHK", "NO_ACCOUNT"} and not status_filter_matches(
                row.get("status"), status_filter, has_account=has_acc
            ):
                continue
            tips = {str(line.get("tip") or "") for line in lines}
            has_book_base = bool(tips & {"08", "14", "9a"})
            any_bucket = (
                only_si
                or only_third
                or only_eu10
                or only_eu11
                or only_exempt
                or only_76a
                or only_excluded
                or only_multi
                or only_si_vat
            )
            if any_bucket:
                bucket_ok = False
                if only_si and region == "SI" and not has_eu_purchase and has_book_base and not si_vat_err:
                    bucket_ok = True
                if only_third and region == "FOREIGN":
                    bucket_ok = True
                if only_eu10 and has_eu10 and region == "EU":
                    bucket_ok = True
                if only_eu11 and has_eu11 and region == "EU":
                    bucket_ok = True
                if only_exempt and has_exempt:
                    bucket_ok = True
                if only_76a and has_76a:
                    bucket_ok = True
                if only_excluded and has_excl:
                    bucket_ok = True
                if only_multi and len(lines) >= 2:
                    bucket_ok = True
                if only_si_vat and si_vat_err:
                    bucket_ok = True
                if not bucket_ok:
                    continue
            vat_22 = decimal_value(row.get("vat_22"))
            vat_95 = decimal_value(row.get("vat_95"))
            vat_5 = decimal_value(row.get("vat_5"))
            vat = vat_22 + vat_95 + vat_5
            p8_amt = pr_p8_amount(row, region)
            f8 = decimal_value(row.get("net_taxable"))
            if not is_nonzero(f8):
                f8 = decimal_value(row.get("base_5"))
            osnova = f8 + eu_g + eu_s
            if nonzero_only and not (
                is_nonzero(p8_amt) or is_nonzero(osnova) or is_nonzero(vat) or has_excl or has_exempt or has_76a
            ):
                continue
            chunks = row_search_chunks(
                row,
                extra=(
                    "PR",
                    region_label(region),
                    money_text(p8_amt),
                    money_text(osnova),
                    money_text(vat),
                    odhodek_summary(lines),
                    "SI+DŠ" if si_vat_err else "",
                ),
            )
            if not haystack_matches(tokens, chunks):
                continue
            item = dict(row)
            item.update(
                {
                    "checked": checked,
                    "region": region,
                    "region_label": region_label(region),
                    "si_vat_err": bool(si_vat_err),
                    "odhodek_display": acc.get("odhodek01") or odhodek_summary(lines),
                    "p8_display": money_text(p8_amt),
                    "osnova_display": money_text(osnova),
                    "vat_display": money_text(vat),
                    "vat_22_display": money_text(vat_22),
                    "vat_95_display": money_text(vat_95),
                    "vat_5_display": money_text(vat_5),
                    "excluded_display": money_text(excluded_amt),
                    "received_date_si": date_text(row.get("received_date")),
                    "has_account": has_acc,
                }
            )
            out.append(item)
        return out

    def list_ir(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if filters:
                self.set_filters(filters)
            rows = self._filtered_ir()
            totals = self._ir_totals(rows)
            return _safe({"ok": True, "rows": rows, "totals": totals, "count": len(rows)})

    def list_pr(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if filters:
                self.set_filters(filters)
            rows = self._filtered_pr()
            totals = self._pr_totals(rows)
            return _safe({"ok": True, "rows": rows, "totals": totals, "count": len(rows)})

    def list_parties(self, search: str = "") -> dict[str, Any]:
        with self._lock:
            if search is not None:
                self.filters["party_search"] = search
            tokens = search_tokens(str(self.filters.get("party_search") or ""))
            rows = []
            for party in self._party_cache:
                chunks = row_search_chunks(party)
                if tokens and not haystack_matches(tokens, chunks):
                    continue
                rows.append(dict(party))
            return _safe({"ok": True, "rows": rows, "count": len(rows)})

    def get_ir(self, row_id: int | str) -> dict[str, Any]:
        with self._lock:
            row = self.db.get_ir(int(row_id))
            if not row:
                return {"ok": False, "error": "IR ni najden."}
            return _safe({"ok": True, "row": row})

    def get_pr(self, row_id: int | str) -> dict[str, Any]:
        with self._lock:
            row = self.db.get_pr(int(row_id))
            if not row:
                return {"ok": False, "error": "PR ni najden."}
            return _safe({"ok": True, "row": row})

    def save_ir(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            rid = self.db.upsert_ir(dict(payload), int(payload["id"]) if payload.get("id") else None)
            self.refresh_all()
            return {"ok": True, "id": rid}

    def save_pr(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            rid = self.db.upsert_pr(dict(payload), int(payload["id"]) if payload.get("id") else None)
            self.refresh_all()
            return {"ok": True, "id": rid}

    def delete_rows(self, kind: str, ids: Sequence[Any]) -> dict[str, Any]:
        with self._lock:
            kind_u = str(kind).upper()
            n = 0
            for rid in ids:
                if kind_u == "IR":
                    self.db.delete_ir(int(rid))
                else:
                    self.db.delete_pr(int(rid))
                n += 1
            self.refresh_all()
            return {"ok": True, "deleted": n}

    def apply_ir_account(self, ids: Sequence[Any], account: str, remember: bool = True) -> dict[str, Any]:
        with self._lock:
            code = str(account or DEFAULT_IR_REVENUE_ACCOUNT).strip()
            for rid in ids:
                row = self.db.get_ir(int(rid))
                if not row:
                    continue
                row = dict(row)
                row["account"] = code
                self.db.upsert_ir(row, int(rid))
                if remember:
                    remember_customer_rule(self.db, row, source="ui")
            self.refresh_all()
            return {"ok": True, "account": code, "count": len(list(ids))}

    def apply_pr_account(self, ids: Sequence[Any], account: str, remember: bool = True) -> dict[str, Any]:
        with self._lock:
            from trops_studio.account_choices import account_code_from_choice

            code = account_code_from_choice(str(account or DEFAULT_PR_EXPENSE_ACCOUNT))
            for rid in ids:
                row = self.db.get_pr(int(rid))
                if not row:
                    continue
                row = dict(row)
                eu_g = decimal_value(row.get("eu_goods"))
                eu_s = decimal_value(row.get("eu_services"))
                net = decimal_value(row.get("net_taxable"))
                has_eu10 = is_nonzero(eu_g)
                has_eu11 = is_nonzero(eu_s)
                has_net = is_nonzero(net)
                if has_eu10:
                    row["odhodek10"] = code
                if has_eu11:
                    row["odhodek11"] = code
                if has_net or not (has_eu10 or has_eu11):
                    row["odhodek01"] = code
                elif not has_net and (has_eu10 or has_eu11):
                    row["odhodek01"] = ""
                row.update(allocate_pr_accounts(row))
                self.db.upsert_pr(row, int(rid))
                if remember:
                    remember_supplier_rule(self.db, row, source="ui")
            self.refresh_all()
            return {"ok": True, "account": code, "count": len(list(ids))}

    def set_selected_ir_account(self, account: str, ids: Sequence[Any]) -> dict[str, Any]:
        return self.apply_ir_account(ids, account, remember=False)

    def set_selected_pr_account(self, account: str, ids: Sequence[Any]) -> dict[str, Any]:
        return self.apply_pr_account(ids, account, remember=False)

    def confirm_selected(self, kind: str, ids: Sequence[Any]) -> dict[str, Any]:
        with self._lock:
            if not self.active_company:
                return {"ok": False, "error": "Najprej izberi podjetje."}
            org = company_org_id(self.active_company)
            if not org:
                return {"ok": False, "error": "Manjka Org_ID."}
            n = confirm_documents(self.db, str(kind).upper(), [int(x) for x in ids])
            self.refresh_all()
            return _safe({"ok": True, "confirmed": n})

    def sync_ready_minimax(self, scope: str = "ALL") -> dict[str, Any]:
        with self._lock:
            if not self.active_company:
                return {"ok": False, "error": "Najprej izberi podjetje."}
            org = company_org_id(self.active_company)
            if not org:
                return {"ok": False, "error": "Manjka Org_ID."}
            scope_u = str(scope or "ALL").upper()
            kinds = None
            if scope_u == "IR":
                kinds = {"IR"}
            elif scope_u == "PR":
                kinds = {"PR"}
            push_parties = scope_u == "ALL"
            result = sync_ready_to_minimax(
                self.db,
                org,
                output_dir=DEFAULT_MINIMAX_OUT,
                company_label=company_name(self.active_company) or "TROPS",
                push_parties=push_parties,
                push_journals_api=True,
                progress=getattr(self, "progress_callback", None),
                kinds=kinds,
                ir_books=self._active_ir_books() or None,
            )
            self.refresh_all()
            msg = getattr(result, "message", None) or str(result)
            failures = list(getattr(result, "parties_failed", []) or []) + list(getattr(result, "journal_failed", []) or [])
            return _safe({"ok": not failures, "message": msg, "msg": msg, "failures": failures})

    def sync_minimax_parties(self) -> dict[str, Any]:
        with self._lock:
            if not self.active_company:
                return {"ok": False, "error": "Najprej izberi podjetje."}
            org = company_org_id(self.active_company)
            if not org:
                return {"ok": False, "error": "Manjka Org_ID."}
            result = sync_customers_from_minimax(self.db, org)
            self.refresh_all()
            return _safe(
                {
                    "ok": True,
                    "message": getattr(result, "message", str(result)),
                    "created": getattr(result, "created", None),
                    "updated": getattr(result, "updated", None),
                }
            )

    def check_minimax_api(self) -> dict[str, Any]:
        with self._lock:
            if not self.active_company:
                return {"ok": False, "error": "Najprej izberi podjetje."}
            org = company_org_id(self.active_company)
            if not org:
                return {"ok": False, "error": "Manjka Org_ID."}
            result = check_minimax_api(org)
            ok = bool(getattr(result, "ok", False))
            return _safe({"ok": ok, "message": getattr(result, "message", str(result))})

    def compute_ddvo(self) -> dict[str, Any]:
        with self._lock:
            ir_rows, pr_rows = self._period_rows()
            summary = run_compute_ddvo(
                ir_rows,
                pr_rows,
                period_from=self.filter_from_date,
                period_to=self.filter_to_date,
            )
            fields = summary.get("fields") if isinstance(summary, dict) else None
            if not isinstance(fields, list):
                fields = []
            return _safe(
                {
                    "ok": True,
                    "summary": summary if isinstance(summary, dict) else {},
                    "fields": fields,
                    "period": self._period_payload(),
                    "company": self._company_payload(),
                }
            )

    def knjige_data(self, book: str = "IR") -> dict[str, Any]:
        with self._lock:
            ir_rows, pr_rows = self._period_rows()
            book_u = str(book or "IR").upper()
            rows_out = []
            if book_u == "IR":
                for row in ir_rows:
                    rows_out.append(ir_row_to_kir(row))
            else:
                for row in pr_rows:
                    rows_out.append(pr_row_to_kpr(row))
            return _safe({"ok": True, "book": book_u, "rows": rows_out, "count": len(rows_out)})

    def konti_data(self) -> dict[str, Any]:
        with self._lock:
            ir_rows, pr_rows = self._period_rows()
            lines = collect_pivot_lines(ir_rows, pr_rows)
            roots, total_d, total_k = build_pivot_tree(lines)
            rows = []
            for line in lines:
                rows.append(
                    {
                        "group": line.group,
                        "konto": line.konto,
                        "party": line.party,
                        "document": line.document,
                        "tip": line.tip,
                        "kind": line.kind,
                        "doc_id": line.doc_id,
                        "debet": money_text(line.debet),
                        "kredit": money_text(line.kredit),
                        "opis": line.opis,
                        "ddvo": ",".join(sorted(line.ddvo_codes)),
                    }
                )
            return _safe(
                {
                    "ok": True,
                    "rows": rows,
                    "count": len(rows),
                    "total_debet": money_text(total_d),
                    "total_kredit": money_text(total_k),
                }
            )

    def analysis_text(self) -> dict[str, Any]:
        with self._lock:
            ir_rows, pr_rows = self._period_rows()
            company = self._company_payload() or {}
            lines = [
                f"Trops Studio {__version__}",
                f"Podjetje: {company.get('zst', '—')} • {company.get('name', '—')}",
                f"Obdobje: {format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)}",
                f"IR v obdobju: {len(ir_rows)}",
                f"PR v obdobju: {len(pr_rows)}",
                f"Stranke v SQL: {len(self._party_cache)}",
                f"Baza: {self.db.path}",
            ]
            try:
                ddvo = run_compute_ddvo(
                    ir_rows, pr_rows, period_from=self.filter_from_date, period_to=self.filter_to_date
                )
                if isinstance(ddvo, dict):
                    lines.append(f"DDV-O 51/52: {money_text(ddvo.get('obligation') or ddvo.get('excess') or 0)}")
                    lines.append(f"Info 26: {money_text(ddvo.get('info_ddvo_26') or 0)}")
            except Exception as exc:
                lines.append(f"DDV-O izračun: {exc}")
            return {"ok": True, "text": "\n".join(lines)}

    def knjizbe_data(self, search: str = "") -> dict[str, Any]:
        """Vse knjižbe — journal_lines iz SQLite (Integra/PR/IR)."""
        with self._lock:
            rows = []
            try:
                for kind, cache in (("IR", self._ir_cache), ("PR", self._pr_cache)):
                    for doc in cache:
                        if not self._row_in_period(
                            doc,
                            date_keys=("document_date", "booking_date", "received_date"),
                        ):
                            continue
                        for line in self.db.list_journal_lines(kind, int(doc["id"])):
                            item = dict(line)
                            item["doc_kind"] = kind
                            item["document_no"] = doc.get("document_no") or doc.get("internal_no")
                            rows.append(item)
            except Exception as exc:
                return {"ok": False, "error": str(exc), "rows": []}
            tokens = search_tokens(search)
            if tokens:
                rows = [r for r in rows if haystack_matches(tokens, row_search_chunks(r))]
            return _safe({"ok": True, "rows": rows, "count": len(rows)})

    def delete_import_for_period(self) -> dict[str, Any]:
        with self._lock:
            n = self.db.delete_ir_pr_for_period(self.filter_from_date, self.filter_to_date)
            self.refresh_all()
            return _safe({"ok": True, "deleted": n})

    def open_path(self, path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            return {"ok": False, "error": f"Ne obstaja: {path}"}
        try:
            os.startfile(str(p))  # type: ignore[attr-defined]
            return {"ok": True, "path": str(p)}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def pick_file(self, title: str = "Izberi datoteko", filetypes: list | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "pick_file — uporabi TropsJsApi.pick_file (sistemski dialog).",
            "path": "",
        }

    def pick_directory(self, title: str = "Izberi mapo") -> dict[str, Any]:
        return {
            "ok": False,
            "error": "pick_directory — uporabi TropsJsApi.pick_directory.",
            "path": "",
        }

    def import_kirkpr_path(self, path: str) -> dict[str, Any]:
        with self._lock:
            from trops_studio.kirkpr_import import import_kirkpr_file_to_db

            if not path or not Path(path).is_file():
                return {"ok": False, "error": "Datoteka ne obstaja."}
            report = import_kirkpr_file_to_db(self.db, Path(path))
            self.refresh_all()
            return _safe({"ok": True, "report": report})

    def import_vasco_paths(self, paths: Mapping[str, str] | None = None) -> dict[str, Any]:
        with self._lock:
            from trops_studio.excel_map import import_vasco_files_to_db

            payload = dict(paths or {})
            ir_files: list[Path] = []
            pr_files: list[Path] = []
            for key in ("darila", "fitnes", "ir"):
                if payload.get(key):
                    ir_files.append(Path(payload[key]))
            if payload.get("pr"):
                pr_files.append(Path(payload["pr"]))
            for extra in payload.get("ir_files") or []:
                ir_files.append(Path(extra))
            for extra in payload.get("pr_files") or []:
                pr_files.append(Path(extra))
            report = import_vasco_files_to_db(
                self.db,
                ir_files=ir_files,
                pr_files=pr_files,
                period_from=self.filter_from_date,
                period_to=self.filter_to_date,
            )
            self.refresh_all()
            return _safe({"ok": True, "report": report})

    def integra_info(self) -> dict[str, Any]:
        with self._lock:
            from trops_studio.integra_sql import (
                list_sql_bak_files,
                list_sql_bck_candidates,
                resolve_integra_sql_dir,
            )

            sql_dir = resolve_integra_sql_dir(self.integra_sql_dir)
            zips = [str(p) for p in list_sql_bck_candidates(sql_dir)]
            baks = [str(p) for p in list_sql_bak_files(sql_dir)]
            return _safe(
                {
                    "ok": True,
                    "sql_dir": str(sql_dir),
                    "candidates": zips,
                    "baks": baks,
                    "auto_irpr": self.integra_auto_irpr,
                }
            )

    def integra_set_sql_dir(self, path: str) -> dict[str, Any]:
        with self._lock:
            self.integra_sql_dir = str(path or self.integra_sql_dir)
            self._persist_session()
            return self.integra_info()

    def integra_restore(self, candidate: str = "") -> dict[str, Any]:
        """Obnovi TROPS iz ZIP/BAK — kliče obstoječo integra_sql logiko."""
        with self._lock:
            from trops_studio.integra_sql import (
                discover_trops_targets,
                razpakiraj_in_restore,
                resolve_integra_sql_dir,
            )

            sql_dir = resolve_integra_sql_dir(self.integra_sql_dir)
            targets = discover_trops_targets()
            if not targets:
                return {"ok": False, "error": "TROPS v SQL ni najden."}
            trops = targets[0]

            if not candidate:
                raise ValueError("Najprej izberi ZIP/BAK datoteko.")
            src = Path(candidate)
            if not src.is_file() or src.suffix.lower() not in {".zip", ".bak"}:
                raise ValueError("Izbrana ZIP/BAK datoteka ne obstaja.")
            try:
                prepared, restored = razpakiraj_in_restore(sql_dir, src, trops)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return _safe(
                {
                    "ok": True,
                    "prepared": str(prepared),
                    "restored": str(restored),
                }
            )

    def integra_kisanal(self, year: str | int = "") -> dict[str, Any]:
        with self._lock:
            from trops_studio.integra_kisanal import urejanje_kisanal_to_sqlite
            from trops_studio.integra_irpr import import_kisanal_to_ir_pr

            y = int(year) if str(year).strip().isdigit() else self.filter_from_date.year
            try:
                result = urejanje_kisanal_to_sqlite(
                    db_path=Path(self.db.path),
                    year=y,
                    date_from=self.filter_from_date,
                    date_to=self.filter_to_date,
                )
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            irpr = None
            if self.integra_auto_irpr:
                try:
                    irpr_res = import_kisanal_to_ir_pr(
                        self.db,
                        date_from=self.filter_from_date,
                        date_to=self.filter_to_date,
                        org_id=company_org_id(self.active_company) if self.active_company else None,
                    )
                    irpr = {
                        "message": getattr(irpr_res, "message", str(irpr_res)),
                        "ir": getattr(irpr_res, "ir_count", None),
                        "pr": getattr(irpr_res, "pr_count", None),
                    }
                except Exception as exc:
                    irpr = {"error": str(exc)}
            self.refresh_all()
            return _safe(
                {
                    "ok": True,
                    "kisanal": {
                        "message": getattr(result, "message", str(result)),
                        "year": getattr(result, "year", y),
                        "db_path": str(getattr(result, "db_path", self.db.path)),
                    },
                    "irpr": irpr,
                }
            )

    def missing_parties(self, book: str = "PR") -> dict[str, Any]:
        with self._lock:
            from trops_studio.parties_ensure import collect_missing_ir_parties, collect_missing_pr_parties

            if str(book).upper() == "IR":
                rows = collect_missing_ir_parties(self.db)
            else:
                rows = collect_missing_pr_parties(self.db)
            return _safe({"ok": True, "rows": rows, "count": len(rows)})

    def default_accounts(self) -> dict[str, Any]:
        return {
            "ok": True,
            "ir": DEFAULT_IR_REVENUE_ACCOUNT,
            "ir_eu": DEFAULT_IR_EU_REVENUE_ACCOUNT,
            "pr": DEFAULT_PR_EXPENSE_ACCOUNT,
        }
