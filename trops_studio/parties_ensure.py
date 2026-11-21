"""Manjkajoče stranke iz IR/PR: SI → Minimax povezava, EU/tretja → AI+SQL+API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

from trops_studio.ajpes_client import lookup_si_company
from trops_studio.config import KONCNI_KUPCI_CODE
from trops_studio.db import Database
from trops_studio.money import (
    ensure_eu_vat_id,
    has_eu_vat_id,
    has_country_prefixed_vat_id,
    has_taxpayer_vat,
    name_needs_repair,
    national_tax_id,
    normalize_text,
    normalize_vat_id,
    sanitize_display_text,
    si_tax8,
    tax_digits,
    vats_compatible,
)
import logging as _logging

_log = _logging.getLogger(__name__)

# Ukrep v dialogu Nove firme → Minimax
ACTION_SI_AJPES = "si_ajpes"       # SI+davčna: dodaj v Minimax, Trops samo poveže
ACTION_TUJEC = "tujec"             # EU/tretja: Minimax → AI+SQL → API
ACTION_KONCNI = "koncni_kupci"     # brez davčne → šifra 01345

ACTION_LABELS = {
    ACTION_SI_AJPES: "SI — Minimax API (davčna)",
    ACTION_TUJEC: "EU/tretja — AI → SQL → API",
    ACTION_KONCNI: f"Končni kupci {KONCNI_KUPCI_CODE}",
}


@dataclass
class EnsureResult:
    matched: int = 0
    from_ajpes: int = 0
    placeholders: int = 0
    failed: list[str] = field(default_factory=list)
    needs_login: bool = False
    message: str = ""


def _country_from_vat(vat_id: str) -> str:
    text = normalize_vat_id(vat_id)
    if len(text) >= 2 and text[:2].isalpha():
        return text[:2]
    return "SI"


def collect_missing_parties(db: Database) -> list[dict[str, Any]]:
    """Unikatni partnerji iz IR/PR, ki še niso v parties (po davčni)."""
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()

    def consider(vat: str, name: str, kind: str) -> None:
        tax = tax_digits(vat)
        key = tax or normalize_vat_id(vat) or name.casefold()
        if not key or key in seen:
            return
        seen.add(key)
        if (tax or vat) and db.find_party_by_tax(vat or tax):
            return
        try:
            from trops_studio.accounts import _known_vat_from_name

            known = _known_vat_from_name(name)
            if known and db.find_party_by_tax(known):
                return
            if name and find_party_for_journal_name(db, name):
                return
        except Exception:
            _log.warning("Iskanje obstoječe stranke ni uspelo", exc_info=True)
        missing.append(
            {
                "kind": kind,
                "vat_id": normalize_vat_id(vat),
                "tax_number": tax,
                "name": name,
            }
        )

    for row in db.list_ir():
        consider(str(row.get("vat_id") or ""), normalize_text(row.get("party_name")), "customer")
    for row in db.list_pr():
        consider(
            str(row.get("vat_id") or row.get("tax_number") or ""),
            normalize_text(row.get("supplier_name")),
            "supplier",
        )
    return missing


def _si_tax8(value: Any) -> str:
    return si_tax8(value)


def classify_firm_action(item: dict[str, Any], *, book: str = "") -> str:
    """
    IR: SI/DE/CH/US… predpona → nujno preveri; brez predpone → Končni.
    PR: predpona SI/DE/US… → zavezanec; brez predpone → podjetje, ni zavezanec DDV.
    """
    from trops_studio.money import has_country_prefixed_vat_id
    from trops_studio.pr_list_view import infer_party_kind

    book_u = str(item.get("book") or book or "").upper()
    kind = infer_party_kind(
        vat_id=item.get("vat_id"),
        tax_number=item.get("tax_number"),
        country=item.get("country"),
        is_foreign=bool(item.get("is_foreign")),
        name=item.get("name"),
        book=book_u,
    )
    vat = normalize_vat_id(item.get("vat_id") or item.get("tax_number"))
    if kind == "SI":
        return ACTION_SI_AJPES
    if kind in {"EU", "THIRD"}:
        return ACTION_TUJEC
    if book_u == "PR" and not has_country_prefixed_vat_id(vat):
        return ACTION_TUJEC
    return ACTION_KONCNI


def _annotate_firm_item(item: dict[str, Any], *, book: str = "") -> dict[str, Any]:
    row = dict(item)
    book_u = str(row.get("book") or book or "").upper()
    action = classify_firm_action(row, book=book_u)
    row["action"] = action
    row["book"] = book_u or row.get("book") or ""
    row["action_label"] = ACTION_LABELS.get(action, action)
    vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
    from trops_studio.money import has_country_prefixed_vat_id

    if action == ACTION_SI_AJPES:
        row["status"] = row.get("status") or "SI — Minimax API po davčni"
    elif action == ACTION_TUJEC:
        if has_country_prefixed_vat_id(vat):
            row["status"] = "ID za DDV — preveri"
        else:
            row["status"] = "podjetje — ni zavezanec DDV"
    else:
        row["status"] = f"Končni {KONCNI_KUPCI_CODE}"
    return row


def _party_tax_keys(party: dict[str, Any]) -> tuple[str, str]:
    country = normalize_text(party.get("country") or "")[:2].upper()
    raw = party.get("tax_number") or party.get("vat_id") or ""
    return tax_digits(raw), national_tax_id(raw, country=country)


def party_covered_by_minimax(
    party: dict[str, Any],
    *,
    covered_tax: set[str],
    covered_alnum: set[str],
    covered_names: list[str],
    overlaps_covered: Callable[[str], bool] | None = None,
) -> bool:
    """True, če je ista firma že v SQL z Minimax šifro (davčna; naziv samo brez DDV)."""
    if normalize_text(party.get("minimax_code")):
        return True
    if has_taxpayer_vat(_party_vat_blob(party)):
        tax, alnum = _party_tax_keys(party)
        if tax and tax in covered_tax:
            return True
        if alnum and len(alnum) >= 5 and alnum in covered_alnum:
            return True
        return False
    tax, alnum = _party_tax_keys(party)
    if tax and tax in covered_tax:
        return True
    if alnum and len(alnum) >= 5 and alnum in covered_alnum:
        return True
    name = sanitize_display_text(party.get("name"))
    if overlaps_covered is not None:
        return bool(name and overlaps_covered(name))
    return bool(name and any(names_overlap(name, other) for other in covered_names))


def absorb_all_minimax_duplicates(db: Database) -> int:
    """
    Hitro: orphani brez MM šifre, ki se ujemajo z že sinhronizirano firmo → izbris.
    Kliči ob Osveži manjkajočih / po ročni povezavi.
    """
    parties = list(db.list_parties())
    keepers = [p for p in parties if normalize_text(p.get("minimax_code"))]
    orphans = [p for p in parties if not normalize_text(p.get("minimax_code"))]
    if not keepers or not orphans:
        return 0

    removed = 0
    for orphan in orphans:
        oid = int(orphan["id"])
        o_name = sanitize_display_text(orphan.get("name"))
        o_tax, o_alnum = _party_tax_keys(orphan)
        best: dict[str, Any] | None = None
        for keeper in keepers:
            k_tax, k_alnum = _party_tax_keys(keeper)
            k_name = sanitize_display_text(keeper.get("name"))
            tax_ok = bool(
                (k_tax and o_tax and k_tax == o_tax and len(k_tax) >= 5)
                or (k_alnum and o_alnum and k_alnum == o_alnum and len(k_alnum) >= 5)
            )
            name_ok = bool(o_name and k_name and names_overlap(o_name, k_name))
            if name_ok or tax_ok:
                best = keeper
                break
        if not best:
            continue
        kid = int(best["id"])
        with db.session() as conn:
            conn.execute(
                "UPDATE ir_rows SET party_id=? WHERE party_id=?",
                (kid, oid),
            )
            conn.execute(
                "UPDATE pr_rows SET party_id=? WHERE party_id=?",
                (kid, oid),
            )
        db.delete_party(oid)
        removed += 1
    return removed


def merge_parties(
    db: Database,
    party_ids: list[int],
    *,
    keeper_id: int | None = None,
) -> tuple[int, int, list[str]]:
    """
    Ročno združi več SQL strank (različna tipkarska imena) v eno.
    Vrne (keeper_id, št. odstranjenih, alias nazivi).
    Keeper: prednost ima MM šifra, nato DDV/naslov; sicer najnižji id.
    """
    ids = sorted({int(x) for x in party_ids if x})
    if len(ids) < 2:
        return (ids[0] if ids else 0, 0, [])

    parties: list[dict[str, Any]] = []
    for pid in ids:
        party = db.get_party(pid)
        if party:
            parties.append(party)
    if len(parties) < 2:
        return (int(parties[0]["id"]) if parties else 0, 0, [])

    def _score(p: dict[str, Any]) -> tuple[int, int, int, int]:
        mm = 1 if normalize_text(p.get("minimax_code")) else 0
        vat = 1 if normalize_text(p.get("vat_id") or p.get("tax_number")) else 0
        addr = 1 if normalize_text(p.get("address")) else 0
        return (mm, vat, addr, -int(p["id"]))

    if keeper_id and any(int(p["id"]) == int(keeper_id) for p in parties):
        keeper = next(p for p in parties if int(p["id"]) == int(keeper_id))
    else:
        keeper = max(parties, key=_score)
    kid = int(keeper["id"])

    # Dopolni prazna polja iz dvojnikov (najbogatejši podatki)
    enrich: dict[str, Any] = dict(keeper)
    for p in parties:
        if int(p["id"]) == kid:
            continue
        for key in (
            "vat_id", "tax_number", "country", "address", "postal_code", "city",
            "registration_no", "ajpes_code", "email", "phone", "iban",
            "minimax_code", "notes",
        ):
            if normalize_text(enrich.get(key)):
                continue
            if normalize_text(p.get(key)):
                enrich[key] = p.get(key)
        if not enrich.get("is_foreign") and p.get("is_foreign"):
            enrich["is_foreign"] = p.get("is_foreign")
    # Preferiraj daljši/čistejši naziv z MM keeperja, sicer najdaljši
    best_name = sanitize_display_text(keeper.get("name"))
    for p in parties:
        name = sanitize_display_text(p.get("name"))
        if not name:
            continue
        if normalize_text(p.get("minimax_code")) and names_overlap(name, best_name or name):
            best_name = name
            break
        if len(name) > len(best_name or ""):
            best_name = name
    if best_name:
        enrich["name"] = best_name
    db.upsert_party(enrich, party_id=kid)

    aliases: list[str] = []
    for p in parties:
        name = sanitize_display_text(p.get("name"))
        if name and name not in aliases:
            aliases.append(name)

    removed = 0
    for p in parties:
        pid = int(p["id"])
        if pid == kid:
            continue
        with db.session() as conn:
            conn.execute("UPDATE ir_rows SET party_id=? WHERE party_id=?", (kid, pid))
            conn.execute("UPDATE pr_rows SET party_id=? WHERE party_id=?", (kid, pid))
        db.delete_party(pid)
        removed += 1

    if aliases:
        link_journal_rows_to_party(db, kid, names=aliases)
    return kid, removed, aliases


def absorb_duplicate_parties(db: Database, keeper_id: int) -> int:
    """
    Po povezavi z Minimax: odstrani dvojnike brez (ali z isto) MM šifro,
    prenesi IR/PR na keeper. Manjkajoči seznam jih takoj izpusti.
    """
    keeper = db.get_party(int(keeper_id))
    if not keeper:
        return 0
    code = normalize_text(keeper.get("minimax_code"))
    if not code:
        return 0
    keeper_name = sanitize_display_text(keeper.get("name"))
    k_tax, k_alnum = _party_tax_keys(keeper)
    aliases = [keeper_name] if keeper_name else []
    removed = 0

    for party in list(db.list_parties()):
        pid = int(party["id"])
        if pid == int(keeper_id):
            continue
        other_code = normalize_text(party.get("minimax_code"))
        if other_code and other_code != code:
            continue
        tax, alnum = _party_tax_keys(party)
        name = sanitize_display_text(party.get("name"))
        name_ok = bool(name and keeper_name and names_overlap(name, keeper_name))
        tax_ok = bool(
            (k_tax and tax and k_tax == tax and len(k_tax) >= 5)
            or (k_alnum and alnum and k_alnum == alnum and len(k_alnum) >= 5)
        )
        same_code = bool(other_code and other_code == code)
        if not (name_ok or tax_ok or same_code):
            continue
        if name and name not in aliases:
            aliases.append(name)
        with db.session() as conn:
            conn.execute(
                "UPDATE ir_rows SET party_id=?, updated_at=datetime('now') WHERE party_id=?",
                (int(keeper_id), pid),
            )
            conn.execute(
                "UPDATE pr_rows SET party_id=?, updated_at=datetime('now') WHERE party_id=?",
                (int(keeper_id), pid),
            )
        db.delete_party(pid)
        removed += 1

    if aliases:
        link_journal_rows_to_party(db, int(keeper_id), names=aliases)
    return removed


def collect_firms_needing_minimax(db: Database) -> list[dict[str, Any]]:
    """
    Nove firme (ni v SQLite ali brez MM šifre), z ukrepom:
    SI+davčna / tujec / Končni kupci 01345.
    Dvojniki Adobe/OpenAI… z že obstajajočo MM šifro niso na seznamu.
    """
    items: list[dict[str, Any]] = []
    seen_tax: set[str] = set()
    seen_name: set[str] = set()
    covered_tax: set[str] = set()
    covered_alnum: set[str] = set()
    covered_names: list[str] = []

    def _mark_seen(tax: str, name: str) -> None:
        if tax:
            seen_tax.add(tax)
        if name:
            seen_name.add(name.casefold())

    # covered_names se po prvi zanki ne spreminja → isti naziv preveri enkrat
    overlap_memo: dict[str, bool] = {}

    def _overlaps_covered(name: str) -> bool:
        hit = overlap_memo.get(name)
        if hit is None:
            hit = any(names_overlap(name, other) for other in covered_names)
            overlap_memo[name] = hit
        return hit

    def _already_seen(tax: str, name: str) -> bool:
        if tax and tax in seen_tax:
            return True
        if name and name.casefold() in seen_name:
            return True
        if name and _overlaps_covered(name):
            return True
        return False

    # Najprej stranke z MM šifro — pokrijejo tipkarske dvojnike (Adobe Stfware…).
    for party in db.list_parties():
        if not normalize_text(party.get("minimax_code")):
            continue
        tax, alnum = _party_tax_keys(party)
        name = sanitize_display_text(party.get("name"))
        if tax:
            covered_tax.add(tax)
        if alnum and len(alnum) >= 5:
            covered_alnum.add(alnum)
        if name:
            covered_names.append(name)
        _mark_seen(tax, name)

    for party in db.list_parties():
        tax = tax_digits(party.get("tax_number") or party.get("vat_id"))
        vat = normalize_vat_id(party.get("vat_id"))
        name = sanitize_display_text(party.get("name"))
        code = normalize_text(party.get("minimax_code"))
        if code:
            continue
        if party_covered_by_minimax(
            party,
            covered_tax=covered_tax,
            covered_alnum=covered_alnum,
            covered_names=covered_names,
            overlaps_covered=_overlaps_covered,
        ):
            continue
        if _already_seen(tax, name):
            continue
        _mark_seen(tax, name)
        party_id = int(party["id"])
        country = normalize_text(party.get("country") or "SI")[:2].upper() or "SI"
        items.append(
            _annotate_firm_item(
                {
                    "party_id": party_id,
                    "kind": "party",
                    "status": "brez MM šifre",
                    "in_sqlite": True,
                    "vat_id": vat,
                    "tax_number": tax,
                    "name": name,
                    "address": sanitize_display_text(party.get("address")),
                    "postal_code": normalize_text(party.get("postal_code")),
                    "city": sanitize_display_text(party.get("city")),
                    "country": country,
                    "registration_no": normalize_text(party.get("registration_no")),
                    "ajpes_code": normalize_text(party.get("ajpes_code")),
                    "email": normalize_text(party.get("email")),
                    "phone": normalize_text(party.get("phone")),
                    "is_foreign": 1 if party.get("is_foreign") or country != "SI" else 0,
                    "source": normalize_text(party.get("source")),
                }
            )
        )

    for item in collect_missing_parties(db):
        tax = tax_digits(item.get("tax_number") or item.get("vat_id"))
        vat = normalize_vat_id(item.get("vat_id"))
        name = sanitize_display_text(item.get("name"))
        if _already_seen(tax, name):
            continue
        # Če obstaja po davčni (tudi z MM šifro) — ni „nova“.
        if (tax or vat) and db.find_party_by_tax(vat or tax):
            continue
        if name and _overlaps_covered(name):
            continue
        _mark_seen(tax, name)
        country = _country_from_vat(vat)
        items.append(
            _annotate_firm_item(
                {
                    "party_id": None,
                    "kind": item.get("kind") or "partner",
                    "status": "ni v SQLite",
                    "in_sqlite": False,
                    "vat_id": vat,
                    "tax_number": tax,
                    "name": name,
                    "address": "",
                    "postal_code": "",
                    "city": "",
                    "country": country,
                    "registration_no": "",
                    "ajpes_code": "",
                    "email": "",
                    "phone": "",
                    "is_foreign": 0 if country == "SI" else 1,
                    "source": "ir_pr",
                }
            )
        )

    order = {ACTION_SI_AJPES: 0, ACTION_KONCNI: 1, ACTION_TUJEC: 2}
    items.sort(
        key=lambda row: (
            order.get(str(row.get("action")), 9),
            str(row.get("name") or "").casefold(),
            str(row.get("tax_number") or ""),
        )
    )
    return items


_NAME_STOPWORDS = frozenset({
    "market", "street", "limited", "ltd", "llc", "inc", "gmbh", "company",
    "doo", "pmb", "suite", "floor", "road", "avenue", "drive", "place",
    "the", "and", "for", "com", "www", "http", "https", "mail", "info",
    "dejavnost", "svetovanje", "izobrazevanje", "storitve",
    # države / kraji — prešibki za ujemanje (GOOGLE Ireland ≠ Adobe Ireland)
    "ireland", "irish", "slovenia", "slovenija", "germany", "deutschland",
    "austria", "france", "italy", "italia", "china", "chinese", "usa",
    "america", "europe", "european", "netherlands", "nederland", "belgium",
    "systems", "software", "electronic", "electronics", "elektronik",
    "house", "gordon",  # pogosti naslovni šumi
})


@lru_cache(maxsize=16384)
def _strip_name_markers_cached(name: str) -> str:
    text = sanitize_display_text(name)
    return re.sub(r"\s*\[(?:MM|DS):[^\]]+\]\s*$", "", text).strip()


def _strip_name_markers(name: str) -> str:
    try:
        return _strip_name_markers_cached(name)
    except TypeError:  # nehashable vrednost
        return _strip_name_markers_cached.__wrapped__(name)


@lru_cache(maxsize=16384)
def _name_tokens_frozen(name: str) -> frozenset[str]:
    out: set[str] = set()
    for t in re.split(r"[^a-z0-9]+", _strip_name_markers(name).casefold()):
        if len(t) < 3 or t.isdigit() or t in _NAME_STOPWORDS:
            continue
        out.add(t)
    return frozenset(out)


def _name_tokens(name: str) -> set[str]:
    return set(_name_tokens_frozen(name))


@lru_cache(maxsize=16384)
def _overlap_keys(name: str) -> tuple[str, str]:
    """(očiščen naziv casefold, kompaktno samo a-z0-9) — enkrat na naziv."""
    folded = _strip_name_markers(name).casefold()
    return folded, re.sub(r"[^a-z0-9]+", "", folded)


def names_overlap(a: str, b: str) -> bool:
    """Ali se naziva dovolj ujemata (za povezavo PR/IR ↔ SQL stranka z MM)."""
    try:
        na, ca = _overlap_keys(a)
        nb, cb = _overlap_keys(b)
    except TypeError:  # nehashable vrednost
        na, ca = _overlap_keys.__wrapped__(a)
        nb, cb = _overlap_keys.__wrapped__(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    # Kompaktno: "Open AI, llc …" → openai… ≈ "OPENAI LLC" (ne pa OPENL)
    if ca and cb and len(ca) >= 5 and len(cb) >= 5:
        if ca.startswith(cb) or cb.startswith(ca):
            return True
        common = 0
        for x, y in zip(ca, cb):
            if x != y:
                break
            common += 1
        if common >= 6:
            return True
    ta, tb = _name_tokens_frozen(na), _name_tokens_frozen(nb)
    if not ta or not tb:
        return False

    def related(t: str, others: set[str]) -> bool:
        if t in others:
            return True
        for o in others:
            shorter, longer = (t, o) if len(t) <= len(o) else (o, t)
            # predpona/vsebovanje samo za ≥5 (open≠openl; foshan⊂foshan…)
            if len(shorter) >= 5 and (longer.startswith(shorter) or shorter in longer):
                return True
        return False

    # Samo ime (DARKO) nikoli ne veže Krajnik ↔ OSOVNIKAR S.P.
    hits = sum(1 for t in ta if related(t, tb))
    return hits >= 2


def find_party_for_journal_name(db: Database, journal_name: str) -> dict[str, Any] | None:
    """Najdi SQL stranko z Minimax šifro, ki pokrije naziv iz IR/PR."""
    name = _strip_name_markers(journal_name)
    if not name:
        return None
    tokens = sorted(_name_tokens(name), key=len, reverse=True)[:4]
    probes = [name[:40]] + tokens
    seen: set[int] = set()
    for probe in probes:
        if len(probe) < 2:
            continue
        for party in db.search_parties(probe, limit=25):
            pid = int(party["id"])
            if pid in seen:
                continue
            seen.add(pid)
            if not normalize_text(party.get("minimax_code")):
                continue
            if names_overlap(name, str(party.get("name") or "")):
                return party
    return None


def _party_vat_blob(party: Mapping[str, Any] | None) -> str:
    if not party:
        return ""
    return str(party.get("vat_id") or party.get("tax_number") or "")


def _find_party_by_taxpayer_vat(db: Database, vat: str, tax_number: str = "") -> dict[str, Any] | None:
    """Samo po SI/EU davčni — nikoli po nazivu."""
    blob = normalize_vat_id(vat or tax_number)
    if not blob:
        return None
    candidates = [blob]
    digits = tax_digits(blob)
    prefix = blob[:2] if len(blob) >= 2 and blob[:2].isalpha() else ""
    if prefix == "SI" and digits:
        candidates.extend([digits, f"SI{digits}"])
    elif not prefix and len(digits) == 8:
        candidates.extend([digits, f"SI{digits}"])
    elif prefix and digits:
        candidates.append(f"{prefix}{digits}")
    seen: set[int] = set()
    for key in candidates:
        if not key:
            continue
        hit = db.find_party_by_tax(key)
        if not hit:
            continue
        pid = int(hit.get("id") or 0)
        if pid in seen:
            continue
        seen.add(pid)
        if vats_compatible(blob, _party_vat_blob(hit), right_country=str(hit.get("country") or "")):
            return hit
    return None


def party_fits_journal(
    party: Mapping[str, Any] | None,
    *,
    name: str = "",
    vat_id: str = "",
    tax_number: str = "",
) -> tuple[bool, str]:
    """Listina (naziv + davčna) sme iti samo na isto firmo.

    Najprej naziv, nato davčna. ERSTE CARD ≠ FREKVENCA — tudi če je party_id napačen.
    """
    if not party:
        return False, "ni stranke"
    jname = sanitize_display_text(name)
    pname = sanitize_display_text(party.get("name"))
    jvat = normalize_vat_id(vat_id or tax_number)
    pvat = _party_vat_blob(party)
    if jname and pname and not names_overlap(jname, pname):
        return False, f"naziv: {jname} ≠ {pname}"
    if has_taxpayer_vat(jvat) and has_taxpayer_vat(pvat):
        if not vats_compatible(jvat, pvat, right_country=str(party.get("country") or "")):
            return False, f"davčna: {jvat} ≠ {pvat or '—'}"
    elif has_taxpayer_vat(jvat) and pvat and not vats_compatible(
        jvat, pvat, right_country=str(party.get("country") or "")
    ):
        return False, f"davčna: {jvat} ≠ {pvat}"
    if jname or has_taxpayer_vat(jvat):
        return True, ""
    return False, "nejasno (brez naziva in davčne)"


def collect_journal_party_conflicts(
    db: Database,
    *,
    ir_rows: Sequence[Mapping[str, Any]] | None = None,
    pr_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Listine, kjer Trops naziv/davčna nista ista firma kot povezana stranka / MM."""
    out: list[dict[str, Any]] = []
    jobs: list[tuple[str, Mapping[str, Any], str]] = []
    for row in ir_rows or ():
        jobs.append(("IR", row, "party_name"))
    for row in pr_rows or ():
        jobs.append(("PR", row, "supplier_name"))
    for book, row, name_key in jobs:
        name = sanitize_display_text(row.get(name_key))
        vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        current = None
        if row.get("party_id"):
            try:
                current = db.get_party(int(row["party_id"]))
            except (TypeError, ValueError):
                current = None
        resolved = resolve_party_for_journal_row(
            db,
            party_id=row.get("party_id"),
            vat_id=vat,
            tax_number=str(row.get("tax_number") or ""),
            name=name,
        )
        reasons: list[str] = []
        if current:
            ok, reason = party_fits_journal(current, name=name, vat_id=vat)
            if not ok:
                reasons.append(reason)
        if resolved and current and int(resolved.get("id") or 0) != int(current.get("id") or 0):
            reasons.append(
                f"vez kaže {sanitize_display_text(current.get('name'))}, "
                f"davčna/naziv pa {sanitize_display_text(resolved.get('name'))}"
            )
        if resolved:
            ok, reason = party_fits_journal(resolved, name=name, vat_id=vat)
            if not ok:
                reasons.append(reason)
        elif current and reasons:
            pass
        elif has_taxpayer_vat(vat) and current is None:
            # ni konflikta vezi — manjka stranka (drug dialog)
            continue
        if not reasons:
            continue
        shown = current or resolved
        out.append(
            {
                "book": book,
                "row_id": int(row.get("id") or 0),
                "document_no": str(row.get("document_no") or ""),
                "trops_name": name,
                "trops_vat": vat or str(row.get("tax_number") or ""),
                "party_id": int(shown["id"]) if shown and shown.get("id") else None,
                "party_name": sanitize_display_text((shown or {}).get("name")),
                "party_vat": _party_vat_blob(shown) if shown else "",
                "minimax_code": normalize_text((shown or {}).get("minimax_code")),
                "reason": " · ".join(dict.fromkeys(reasons)),
            }
        )
    return out


def resolve_party_for_journal_row(
    db: Database,
    *,
    party_id: Any = None,
    vat_id: str = "",
    tax_number: str = "",
    name: str = "",
) -> dict[str, Any] | None:
    """
    Stranka za IR/PR vrstico.
    Najprej naziv listine, nato davčna. Če se naziv ali davčna ne ujemata — None.
    """
    vat = normalize_vat_id(vat_id or tax_number)
    name_s = sanitize_display_text(name)
    taxpayer = has_taxpayer_vat(vat)

    def _ok(party: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not party:
            return None
        fits, _reason = party_fits_journal(party, name=name_s, vat_id=vat, tax_number=tax_number)
        return dict(party) if fits else None

    if taxpayer:
        by_tax = _find_party_by_taxpayer_vat(db, vat, tax_number)
        hit = _ok(by_tax)
        if hit:
            return hit
        if party_id:
            try:
                linked = db.get_party(int(party_id))
            except (TypeError, ValueError):
                linked = None
            return _ok(linked)
        return None

    linked: dict[str, Any] | None = None
    if party_id:
        try:
            linked = db.get_party(int(party_id))
        except (TypeError, ValueError):
            linked = None
    # Listina brez ID za DDV = FO — ne veži zavezanca (Krajnik ≠ OSOVNIKAR S.P.).
    # Nezavezanec z davčno (SubjectToVAT=N, npr. najemodajalec) ostane povezan.
    if linked and has_taxpayer_vat(normalize_vat_id(linked.get("vat_id"))):
        linked = None
    hit = _ok(linked)
    if hit:
        return hit

    if name_s:
        found = find_party_for_journal_name(db, name_s)
        if found and tax_digits(_party_vat_blob(found)):
            return None
        return _ok(found)
    return None


def resolve_party_for_missing(
    db: Database,
    *,
    party_id: Any = None,
    vat_id: str = "",
    tax_number: str = "",
    name: str = "",
) -> dict[str, Any] | None:
    """
    Stranka za IR/PR vrstico; če ima MM šifro, manjkajoči seznam jo izpusti.

    Če je listina že eksplicitno povezana (party_id) na stranko z MM šifro,
    zaupamo povezavi samo, če davčna zavezanca ne nasprotuje (ERSTE ≠ FREKVENCA).
    """
    vat = normalize_vat_id(vat_id or tax_number)
    party = resolve_party_for_journal_row(
        db,
        party_id=party_id,
        vat_id=vat_id,
        tax_number=tax_number,
        name=name,
    )
    if party and normalize_text(party.get("minimax_code")):
        return party
    if party_id:
        try:
            linked = db.get_party(int(party_id))
        except (TypeError, ValueError):
            linked = None
        if linked and normalize_text(linked.get("minimax_code")):
            if has_taxpayer_vat(vat) and not vats_compatible(
                vat, _party_vat_blob(linked), right_country=str(linked.get("country") or "")
            ):
                return party
            return linked
    return party


def link_journal_rows_to_party(
    db: Database,
    party_id: int,
    *,
    names: list[str] | None = None,
) -> int:
    """
    Poveži IR/PR vrstice na stranko (party_id), če se naziv ujema z enim od aliasov
    ali z nazivom stranke. Tudi če party_id že obstaja a je drug — posodobi, če alias.
    """
    party = db.get_party(int(party_id))
    if not party:
        return 0
    aliases = [_strip_name_markers(n) for n in (names or []) if sanitize_display_text(n)]
    aliases.append(_strip_name_markers(str(party.get("name") or "")))
    aliases = [a for a in aliases if a]
    if not aliases:
        return 0
    linked = 0
    for row in db.list_ir():
        row_name = sanitize_display_text(row.get("party_name"))
        if not row_name:
            continue
        if not any(names_overlap(row_name, alias) for alias in aliases):
            continue
        if int(row.get("party_id") or 0) == int(party_id):
            continue
        row_vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        if has_taxpayer_vat(row_vat) and has_taxpayer_vat(_party_vat_blob(party)):
            if not vats_compatible(row_vat, _party_vat_blob(party), right_country=str(party.get("country") or "")):
                continue
        payload = dict(row)
        payload["party_id"] = int(party_id)
        db.upsert_ir(payload, row_id=int(row["id"]))
        linked += 1
    for row in db.list_pr():
        row_name = sanitize_display_text(row.get("supplier_name"))
        if not row_name:
            continue
        if not any(names_overlap(row_name, alias) for alias in aliases):
            continue
        if int(row.get("party_id") or 0) == int(party_id):
            continue
        row_vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        if has_taxpayer_vat(row_vat) and has_taxpayer_vat(_party_vat_blob(party)):
            if not vats_compatible(row_vat, _party_vat_blob(party), right_country=str(party.get("country") or "")):
                continue
        payload = dict(row)
        payload["party_id"] = int(party_id)
        db.upsert_pr(payload, row_id=int(row["id"]))
        linked += 1
    return linked


def relink_journal_parties_by_vat(db: Database) -> int:
    """Popravi napačen party_id na IR/PR, kjer davčna zavezanca ne ustreza (ERSTE ≠ FREKVENCA)."""
    fixed = 0
    for kind, rows, name_key in (
        ("IR", db.list_ir(), "party_name"),
        ("PR", db.list_pr(), "supplier_name"),
    ):
        for row in rows:
            vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
            current_id = int(row.get("party_id") or 0)
            if not has_taxpayer_vat(vat):
                if not current_id:
                    continue
                current = db.get_party(current_id)
                if current and tax_digits(_party_vat_blob(current)):
                    payload = dict(row)
                    payload["party_id"] = None
                    if kind == "IR":
                        db.upsert_ir(payload, row_id=int(row["id"]))
                    else:
                        db.upsert_pr(payload, row_id=int(row["id"]))
                    fixed += 1
                continue
            right = resolve_party_for_journal_row(
                db,
                party_id=row.get("party_id"),
                vat_id=vat,
                tax_number=str(row.get("tax_number") or ""),
                name=sanitize_display_text(row.get(name_key)),
            )
            current_id = int(row.get("party_id") or 0)
            right_id = int(right["id"]) if right and right.get("id") else 0
            if right_id and right_id == current_id:
                continue
            if not right_id and not current_id:
                continue
            if current_id:
                current = db.get_party(current_id)
                if current and vats_compatible(
                    vat, _party_vat_blob(current), right_country=str(current.get("country") or "")
                ):
                    continue
            payload = dict(row)
            payload["party_id"] = right_id or None
            if kind == "IR":
                db.upsert_ir(payload, row_id=int(row["id"]))
            else:
                db.upsert_pr(payload, row_id=int(row["id"]))
            fixed += 1
    return fixed


def link_rows_to_parties(db: Database) -> int:
    """Nastavi party_id na IR/PR, kjer manjka, a stranka obstaja (davčna ali MM po nazivu)."""
    linked = relink_journal_parties_by_vat(db)
    for row in db.list_ir():
        if row.get("party_id"):
            continue
        party = resolve_party_for_missing(
            db,
            vat_id=normalize_vat_id(row.get("vat_id")),
            name=sanitize_display_text(row.get("party_name")),
        )
        if not party:
            continue
        payload = dict(row)
        payload["party_id"] = int(party["id"])
        db.upsert_ir(payload, row_id=int(row["id"]))
        linked += 1
    for row in db.list_pr():
        if row.get("party_id"):
            continue
        party = resolve_party_for_missing(
            db,
            vat_id=normalize_vat_id(row.get("vat_id") or row.get("tax_number")),
            tax_number=tax_digits(row.get("tax_number") or row.get("vat_id")),
            name=sanitize_display_text(row.get("supplier_name")),
        )
        if not party:
            continue
        payload = dict(row)
        payload["party_id"] = int(party["id"])
        db.upsert_pr(payload, row_id=int(row["id"]))
        linked += 1
    return linked


def ensure_missing_via_ajpes(db: Database, *, use_ajpes: bool = False) -> EnsureResult:
    """
    Za partnerje iz IR/PR, ki jih ni v SQLite:
    1) če že obstaja po davčni → link
    2) SI+davčna: placeholder (dodaj v Minimax, nato pull) — brez AJPES-uvoza
    3) sicer placeholder (EU/tretja: AI → SQL)
    """
    result = EnsureResult()
    result.matched = link_rows_to_parties(db)

    for item in collect_missing_parties(db):
        tax = tax_digits(item.get("tax_number") or item.get("vat_id"))
        vat = normalize_vat_id(item.get("vat_id"))
        name = normalize_text(item.get("name"))
        country = _country_from_vat(vat)

        if (vat or tax) and db.find_party_by_tax(vat or tax):
            result.matched += 1
            continue

        if country == "SI" and tax:
            db.upsert_party(
                {
                    "vat_id": ensure_eu_vat_id(vat or tax, country="SI") or f"SI{tax}",
                    "tax_number": tax,
                    "country": "SI",
                    "name": name or f"Neznana {tax}",
                    "is_foreign": 0,
                    "source": "placeholder",
                    "notes": "Čaka Minimax — dodaj SI+davčno tam, nato Minimax↓ stranke",
                }
            )
            result.placeholders += 1
            continue

        # Tretja država: ohrani ID za DDV (npr. IL001) — FURS ga zahteva
        keep_vat = normalize_vat_id(vat)
        if country in {"", "SI"} and tax and len(tax) == 8:
            keep_vat = ensure_eu_vat_id(keep_vat or tax, country="SI") or f"SI{tax}"
        elif keep_vat and not has_eu_vat_id(keep_vat) and country in {"", "SI"}:
            keep_vat = ""
        db.upsert_party(
            {
                "vat_id": keep_vat if (has_eu_vat_id(keep_vat) or (keep_vat and country not in {"", "SI"})) else "",
                "tax_number": tax,
                "country": country,
                "name": name or f"Neznana {tax or vat or 'stranka'}",
                "is_foreign": 0 if country == "SI" else 1,
                "source": "placeholder",
                "notes": "Samodejno — preveri z AI, shrani v SQL, nato Minimax API",
            }
        )
        result.placeholders += 1

    result.matched += link_rows_to_parties(db)
    result.message = (
        f"Povezanih: {result.matched}, "
        f"začasnih (Minimax/AI): {result.placeholders}"
        + (f", napak: {len(result.failed)}" if result.failed else "")
    )
    return result


def repair_party_names(db: Database, *, use_ajpes: bool = True) -> dict[str, Any]:
    """Počisti hieroglife v nazivih; SI z luknjami dopolni iz AJPES (EvidencaFirm)."""
    sanitized = 0
    refreshed = 0
    failed: list[str] = []
    for party in db.list_parties():
        party_id = int(party["id"])
        old_name = str(party.get("name") or "")
        new_name = sanitize_display_text(old_name)
        dirty = name_needs_repair(old_name)
        payload = dict(party)
        changed = False
        if new_name and new_name != old_name:
            payload["name"] = new_name
            sanitized += 1
            changed = True
        country = str(party.get("country") or "SI").upper()
        tax = tax_digits(party.get("vat_id") or party.get("tax_number"))
        needs_ajpes = bool(
            dirty and use_ajpes and country == "SI" and tax and not party.get("is_foreign")
        )
        if needs_ajpes:
            lookup = lookup_si_company(
                tax,
                new_name or old_name,
                entity_id=str(party.get("ajpes_code") or ""),
            )
            if lookup.ok:
                payload.update(
                    {
                        "name": lookup.name or new_name or old_name,
                        "vat_id": lookup.vat_id or payload.get("vat_id"),
                        "tax_number": lookup.tax_number or tax,
                        "address": lookup.address or payload.get("address"),
                        "postal_code": lookup.postal_code or payload.get("postal_code"),
                        "city": lookup.city or payload.get("city"),
                        "registration_no": lookup.registration_no or payload.get("registration_no"),
                        "ajpes_code": lookup.ajpes_code or payload.get("ajpes_code"),
                        "email": lookup.email or payload.get("email"),
                        "phone": lookup.phone or payload.get("phone"),
                        "iban": lookup.iban or payload.get("iban"),
                        "country": "SI",
                        "source": "ajpes",
                    }
                )
                refreshed += 1
                changed = True
            elif lookup.needs_login:
                failed.append(f"{tax}: AJPES prijava")
            elif dirty:
                failed.append(f"{tax}: {lookup.message}")
        if changed:
            try:
                db.upsert_party(payload, party_id=party_id)
            except Exception as exc:
                failed.append(f"id={party_id}: {exc}")
    return {
        "sanitized": sanitized,
        "refreshed": refreshed,
        "failed": failed,
        "message": (
            f"Popravljenih nazivov: {sanitized}, AJPES osvežitev: {refreshed}"
            + (f", napak: {len(failed)}" if failed else "")
            + "."
        ),
    }


def collect_missing_ir_parties(
    db: Database,
    ir_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Kupci iz IR z ID za DDV (SI…/DE…/IT…), ki jih še ni v Minimaxu (brez MM šifre).
    SI → AJPES, tujci (DE/IT/AT…) → ročno.
    Brez DDV → Končni kupci 01345 (ni v tem seznamu).
    """
    rows = list(ir_rows) if ir_rows is not None else list(db.list_ir())
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        # Integra Paragoni (1000/1650): brez stranke / Končnih kupcev
        try:
            from trops_studio.journal_preview import _ir_payment_account

            if _ir_payment_account(row) in {"1000", "1650"}:
                continue
        except Exception:
            _log.warning("Plačilni konto IR ni določljiv", exc_info=True)
        vat = normalize_vat_id(row.get("vat_id"))
        # Brez EU ID za DDV → Projest: sync gre na 01345, ni treba listview
        if not has_eu_vat_id(vat):
            continue
        name = sanitize_display_text(row.get("party_name"))
        tax = tax_digits(vat)
        raw_pid = row.get("party_id")
        if raw_pid:
            try:
                linked_now = db.get_party(int(raw_pid))
            except (TypeError, ValueError):
                linked_now = None
            if linked_now and normalize_text(linked_now.get("minimax_code")):
                continue
        party = resolve_party_for_missing(
            db,
            party_id=row.get("party_id"),
            vat_id=vat,
            tax_number=tax,
            name=name,
        )
        if party and normalize_text(party.get("minimax_code")):
            # Poveži vrstico, če še ni — da naslednjič ne pade na seznam
            if not row.get("party_id") or int(row.get("party_id") or 0) != int(party["id"]):
                payload = dict(row)
                payload["party_id"] = int(party["id"])
                db.upsert_ir(payload, row_id=int(row["id"]))
            continue
        key = tax or vat or name.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        country = normalize_text((party or {}).get("country") or "")[:2].upper()
        if not country:
            country = _country_from_vat(vat) or "SI"
        base = {
            "party_id": int(party["id"]) if party and party.get("id") else None,
            "kind": "customer",
            "name": name or sanitize_display_text((party or {}).get("name")) or "Neznan kupec",
            "vat_id": vat or normalize_vat_id((party or {}).get("vat_id") or ""),
            "tax_number": tax or tax_digits((party or {}).get("tax_number") or ""),
            "country": country,
            "address": sanitize_display_text((party or {}).get("address")),
            "postal_code": normalize_text((party or {}).get("postal_code")),
            "city": sanitize_display_text((party or {}).get("city")),
            "is_foreign": (party or {}).get("is_foreign") or (0 if country == "SI" else 1),
            "source": "IR",
            "document": normalize_text(row.get("document_no") or row.get("internal_no")),
            "in_sqlite": bool(party),
        }
        items.append(_annotate_firm_item(base, book="IR"))

    order = {ACTION_SI_AJPES: 0, ACTION_TUJEC: 1, ACTION_KONCNI: 2}
    items.sort(key=lambda i: (order.get(str(i.get("action")), 9), str(i.get("name") or "").casefold()))
    return items


def collect_missing_pr_parties(
    db: Database,
    pr_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Dobavitelji iz PR, ki jih še ni v Minimaxu (brez MM šifre).
    SI → AJPES, tujec / brez davčne → ročno.
    """
    rows = list(pr_rows) if pr_rows is not None else list(db.list_pr())
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        name = sanitize_display_text(row.get("supplier_name"))
        vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
        tax = tax_digits(row.get("tax_number") or row.get("vat_id"))
        # Že povezana listina na SQL stranko z MM šifro → ni manjkajoča
        raw_pid = row.get("party_id")
        if raw_pid:
            try:
                linked_now = db.get_party(int(raw_pid))
            except (TypeError, ValueError):
                linked_now = None
            if linked_now and normalize_text(linked_now.get("minimax_code")):
                continue
        party = resolve_party_for_missing(
            db,
            party_id=row.get("party_id"),
            vat_id=vat,
            tax_number=tax,
            name=name,
        )
        if party and normalize_text(party.get("minimax_code")):
            if not row.get("party_id") or int(row.get("party_id") or 0) != int(party["id"]):
                payload = dict(row)
                payload["party_id"] = int(party["id"])
                db.upsert_pr(payload, row_id=int(row["id"]))
            continue
        key = tax or vat or name.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        country = normalize_text((party or {}).get("country") or "")[:2].upper()
        if not country or country in {"XX", "??"}:
            country = _country_from_vat(vat) if vat else "SI"
        if country == "GR":
            country = "EL"
        foreign = 1 if country != "SI" else int((party or {}).get("is_foreign") or 0)
        base = {
            "party_id": int(party["id"]) if party and party.get("id") else None,
            "kind": "supplier",
            "name": name or sanitize_display_text((party or {}).get("name")) or "Neznan dobavitelj",
            "vat_id": vat or normalize_vat_id((party or {}).get("vat_id") or ""),
            "tax_number": tax or tax_digits((party or {}).get("tax_number") or ""),
            "country": country or "SI",
            "address": sanitize_display_text((party or {}).get("address")),
            "postal_code": normalize_text((party or {}).get("postal_code")),
            "city": sanitize_display_text((party or {}).get("city")),
            "is_foreign": foreign,
            "source": "PR",
            "document": normalize_text(row.get("document_no") or row.get("internal_no")),
            "pr_document": normalize_text(row.get("document_no") or row.get("internal_no")),
            "in_sqlite": bool(party),
        }
        if not has_country_prefixed_vat_id(base["vat_id"] or base["tax_number"]):
            annotated = _annotate_firm_item(base, book="PR")
            items.append(annotated)
        else:
            annotated = _annotate_firm_item(base, book="PR")
            if base["in_sqlite"] and not normalize_text((party or {}).get("minimax_code")):
                annotated["status"] = "v SQL — brez MM"
            items.append(annotated)

    order = {ACTION_SI_AJPES: 0, ACTION_TUJEC: 1, ACTION_KONCNI: 2}
    items.sort(key=lambda i: (order.get(str(i.get("action")), 9), str(i.get("name") or "").casefold()))
    return items


def stage_journal_parties_to_sql(
    db: Database,
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Manjkajoče IR/PR firme → SQLite Stranke (brez Minimax).
    Poveže party_id na listine. sync_status=ready za kasnejši push.
    """
    from trops_studio.sync_state import SYNC_READY
    from trops_studio.vies_client import EU_VAT_COUNTRIES, is_eu_vat_id

    staged = 0
    linked = 0
    for raw in items:
        item = dict(raw)
        name = sanitize_display_text(item.get("name")) or "Neznana stranka"
        vat = normalize_vat_id(item.get("vat_id") or "")
        tax = tax_digits(item.get("tax_number") or vat)
        country = normalize_text(item.get("country") or "")[:2].upper()
        if not country or country in {"XX", "??"}:
            country = _country_from_vat(vat) if vat else "SI"
        if country == "GR":
            country = "EL"
        foreign = 1 if country != "SI" else 0
        eu = bool(vat and is_eu_vat_id(vat) and vat[:2] in EU_VAT_COUNTRIES)
        third = foreign and not eu
        payload: dict[str, Any] = {
            "vat_id": vat,
            "tax_number": "" if third else tax,
            "country": country,
            "name": name,
            "address": sanitize_display_text(item.get("address")),
            "postal_code": normalize_text(item.get("postal_code")),
            "city": sanitize_display_text(item.get("city")),
            "is_foreign": foreign,
            "source": "sql_stage",
            "sync_status": SYNC_READY,
            "notes": normalize_text(item.get("notes"))
            or "Iz PR/IR manjkajočih — v Strankah, čaka Minimax",
        }
        party_id = item.get("party_id")
        if party_id:
            existing = db.get_party(int(party_id))
            if existing and normalize_text(existing.get("minimax_code")):
                linked += link_journal_rows_to_party(db, int(party_id), names=[name])
                continue
            db.upsert_party(payload, party_id=int(party_id))
            try:
                db.set_party_sync(int(party_id), SYNC_READY)
            except Exception:
                _log.warning("Stranka: status »pripravljeno« ni nastavljen", exc_info=True)
            pid = int(party_id)
        else:
            found = None
            if vat or tax:
                found = db.find_party_by_tax(vat or tax)
            if found is None and name:
                found = find_party_for_journal_name(db, name)
            if found:
                pid = int(found["id"])
                if not normalize_text(found.get("minimax_code")):
                    db.upsert_party(payload, party_id=pid)
                    try:
                        db.set_party_sync(pid, SYNC_READY)
                    except Exception:
                        _log.warning("Stranka: status »pripravljeno« ni nastavljen", exc_info=True)
            else:
                pid = db.upsert_party(payload)
                try:
                    db.set_party_sync(pid, SYNC_READY)
                except Exception:
                    _log.warning("Stranka: status »pripravljeno« ni nastavljen", exc_info=True)
        staged += 1
        linked += link_journal_rows_to_party(db, pid, names=[name])
    linked += link_rows_to_parties(db)
    return {"staged": staged, "linked": linked}
