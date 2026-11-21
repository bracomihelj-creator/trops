"""Trops Studio 5.1 — preslikava kontov Trops→Minimax, kontni plan Minimax→SQL in urejanje strank (AJPES/VIES).

Funkcije so bile prej samo v klasičnem Tk urejevalniku. Poslovna logika ostaja v obstoječih modulih
(account_choices, db, ajpes_client, vies_client); tu je samo tanek sloj za spletni UI.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Mapping

from trops_studio.account_choices import (
    account_code_from_choice,
    clear_account_cache,
    default_minimax_org_id,
    find_unmapped_accounts,
    load_account_choices,
    minimax_account_codes,
)
from trops_studio.companies import company_org_id
from trops_studio.money import (
    national_tax_id,
    normalize_text,
    normalize_vat_id,
    sanitize_display_text,
    tax_digits,
)
from trops_studio.sync_state import SYNC_READY, SYNC_SYNCED

log = logging.getLogger("trops_studio_web.accounts_parties")

PARTY_FIELDS = (
    "name", "vat_id", "tax_number", "country", "address", "postal_code", "city",
    "registration_no", "ajpes_code", "email", "phone", "iban", "notes", "minimax_code",
)
PARTY_KINDS = {"SI", "EU", "THIRD", "NONE"}


class InputError(ValueError):
    """Neveljaven vnos (host ga preslika v HTTP 400)."""


class AccountsPartiesMixin:
    """Mešanica za AppService/Motor (uporablja self.db, self.active_company, self._lock, self.refresh_all)."""

    # ------------------------------------------------------------------ konti Trops → Minimax
    def _org_for_accounts(self) -> str:
        org = company_org_id(self.active_company) if self.active_company else ""
        return str(org or "").strip() or default_minimax_org_id(self.db)

    def account_map_info(self) -> dict[str, Any]:
        with self._lock:
            org = self._org_for_accounts()
            choices = load_account_choices(self.db, org, fetch_minimax=False)
            mm_codes = minimax_account_codes(self.db, org)
            labels = {account_code_from_choice(c): c for c in choices}
            rows = []
            for r in find_unmapped_accounts(self.db, org):
                sug = str(r.get("suggested") or "")
                rows.append({
                    "trops_code": r["trops_code"],
                    "count": int(r.get("count") or 0),
                    "suggested": sug,
                    "suggested_label": labels.get(account_code_from_choice(sug), sug),
                })
            saved = [
                {**m, "minimax_label": labels.get(str(m.get("minimax_code") or ""), m.get("minimax_code"))}
                for m in self.db.list_account_code_maps(org)
            ]
            return {
                "ok": True,
                "org": org,
                "rows": rows,
                "choices": choices,
                "mm_count": len(mm_codes),
                "saved": saved,
                "warning": "" if mm_codes else "Ni Minimax kontnega plana v bazi. Najprej: Minimax → Kontni plan iz Minimax.",
            }

    def account_map_save(self, maps: Any, apply_data: bool = False, confirm: bool = False) -> dict[str, Any]:
        if not isinstance(maps, Mapping) or not maps:
            raise InputError("Ni izbranih zamenjav kontov.")
        if apply_data and confirm is not True:
            raise InputError("Prepis kontov v IR/PR/knjižbah zahteva potrditev.")
        with self._lock:
            org = self._org_for_accounts()
            mm_codes = minimax_account_codes(self.db, org)
            clean: dict[str, str] = {}
            bad: list[str] = []
            for trops_raw, mm_raw in maps.items():
                trops = account_code_from_choice(str(trops_raw or ""))
                mm = account_code_from_choice(str(mm_raw or ""))
                if not trops or not mm or (mm_codes and mm not in mm_codes):
                    bad.append(str(trops_raw))
                    continue
                clean[trops] = mm
            if bad:
                raise InputError("Neveljaven ali neknjižljiv Minimax konto za: " + ", ".join(bad))
            n = self.db.upsert_account_code_maps(clean, org_id=org, source="user")
            clear_account_cache()
            applied: dict[str, int] = {}
            if apply_data:
                applied = self.db.apply_account_code_maps_to_data(clean, org_id=org)
            log.info("Preslikava kontov shranjena (org %s): %s, prepis=%s", org, clean, applied)
            self.refresh_all()
            msg = f"Shranjenih {n} preslikav kontov."
            if applied:
                msg += (f" Prepisano: IR {applied.get('ir', 0)}, PR {applied.get('pr', 0)}, "
                        f"knjižbe {applied.get('journal', 0)}, kisanal {applied.get('kisanal', 0)}.")
            return {"ok": True, "saved": n, "applied": applied, "msg": msg}

    def minimax_accounts_sync(self) -> dict[str, Any]:
        """Minimax kontni plan → SQLite (minimax_accounts). Bere iz Minimaxa, v Minimaxu ne spreminja ničesar."""
        from trops_studio.account_choices import warm_account_cache_minimax

        with self._lock:
            org = company_org_id(self.active_company) if self.active_company else ""
            if not org:
                raise InputError("Pri izbranem podjetju manjka Minimax Org_ID.")
            before = self.db.count_minimax_accounts(org)
            choices = warm_account_cache_minimax(self.db, org, force=True)
            n = self.db.count_minimax_accounts(org)
            clear_account_cache()
            return {
                "ok": True, "org": org, "count": n, "before": before, "bookable": len(choices),
                "msg": f"Kontni plan Minimax → baza: {n} kontov (prej {before}), knjižljivih {len(choices)}.",
            }

    # ------------------------------------------------------------------ stranke
    def party_get(self, party_id: Any) -> dict[str, Any]:
        with self._lock:
            row = self.db.get_party(int(party_id))
            if not row:
                return {"ok": False, "error": "Stranka ne obstaja."}
            return {"ok": True, "row": row}

    @staticmethod
    def _party_payload(data: Mapping[str, Any]) -> dict[str, Any]:
        """Enaka pravila kot Tk obrazec Stranke (_payload)."""
        name = sanitize_display_text(data.get("name"))
        if not name:
            raise InputError("Naziv stranke je obvezen.")
        kind = str(data.get("kind") or "SI").upper()
        if kind not in PARTY_KINDS:
            raise InputError("Vrsta stranke mora biti SI, EU, THIRD ali NONE.")
        country = normalize_text(data.get("country"))[:2].upper()
        foreign = kind in {"EU", "THIRD"}
        if not foreign and not country:
            country = "SI"
        if country == "SI":
            foreign = False
        vat = normalize_vat_id(data.get("vat_id"))
        if country == "SI" or not foreign:
            tax = tax_digits(data.get("tax_number") or vat)
        else:
            tax = national_tax_id(data.get("tax_number") or vat, country=country)
        mm = normalize_text(data.get("minimax_code"))
        return {
            "vat_id": vat,
            "tax_number": tax,
            "country": country or ("XX" if foreign else "SI"),
            "name": name,
            "address": sanitize_display_text(data.get("address")),
            "postal_code": normalize_text(data.get("postal_code")),
            "city": sanitize_display_text(data.get("city")),
            "registration_no": normalize_text(data.get("registration_no")),
            "ajpes_code": normalize_text(data.get("ajpes_code")),
            "email": normalize_text(data.get("email")),
            "phone": normalize_text(data.get("phone")),
            "iban": normalize_text(data.get("iban")),
            "notes": normalize_text(data.get("notes")),
            "is_foreign": foreign,
            "source": "ajpes" if not foreign and tax else "manual",
            "minimax_code": mm,
            "sync_status": SYNC_SYNCED if mm else SYNC_READY,
        }

    def party_save(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise InputError("Manjkajo podatki stranke.")
        payload = self._party_payload(data)
        pid_raw = data.get("id")
        with self._lock:
            pid = int(pid_raw) if pid_raw not in (None, "") else None
            if pid is not None and not self.db.get_party(pid):
                return {"ok": False, "error": "Stranka ne obstaja."}
            new_id = self.db.upsert_party(payload, pid)
            fresh = self.db.get_party(new_id) or {}
            self.refresh_all()
            return {"ok": True, "id": new_id, "row": fresh, "msg": f"Stranka shranjena: {fresh.get('name') or payload['name']}"}

    def party_ajpes(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """AJPES poizvedba (EvidencaFirm). Nič ne shrani — UI izpolni obrazec, uporabnik shrani."""
        from trops_studio.ajpes_client import eprs_url_by_tax, lookup_si_company

        tax = str(data.get("vat_id") or data.get("tax_number") or "")
        res = lookup_si_company(tax, sanitize_display_text(data.get("name")), entity_id=str(data.get("ajpes_code") or ""))
        out = asdict(res)
        out["candidates"] = [{k: v for k, v in c.items() if k != "detail"} for c in res.candidates[:20]]
        out["eprs_url"] = eprs_url_by_tax(res.tax_number or tax) if (res.tax_number or tax) else ""
        if not res.ok:
            out["error"] = res.message or "AJPES ni vrnil podatkov."
        else:
            out["msg"] = "AJPES: podatki prebrani. ID za DDV ostane prazen (po potrebi preveri VIES)."
        return out

    def party_vies(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """VIES preverba ID za DDV. Nič ne shrani."""
        from trops_studio.vies_client import EU_VAT_COUNTRIES, check_eu_vat, is_eu_vat_id

        vat = normalize_vat_id(data.get("vat_id"))
        country = normalize_text(data.get("country"))[:2].upper()
        if not vat:
            body = national_tax_id(data.get("tax_number") or "", country=country)
            cc = country if country in EU_VAT_COUNTRIES else ("SI" if body.isdigit() and len(body) == 8 else "")
            if cc and body:
                vat = f"{cc}{body}"
        if not is_eu_vat_id(vat):
            return {"ok": False, "error": "Za VIES vnesi ID za DDV (npr. IE6388047V) ali državo in davčno številko."}
        res = check_eu_vat(vat)
        out = asdict(res)
        out["full_vat"] = f"{res.country}{res.vat_number}" if res.country else vat
        if not res.ok:
            out["error"] = res.message
        else:
            out["msg"] = res.message
        return out
