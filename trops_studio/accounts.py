from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from trops_studio.config import (
    DEFAULT_IR_REVENUE_ACCOUNT,
    DEFAULT_PR_EXCLUDED_ACCOUNT,
    DEFAULT_PR_EXPENSE_ACCOUNT,
)
from trops_studio.db import Database
from trops_studio.excel_bridge import read_account_history
from trops_studio.money import (
    decimal_value,
    ensure_eu_vat_id,
    is_nonzero,
    national_tax_id,
    normalize_text,
    normalize_vat_id,
    tax_digits,
)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _valid_account(code: str) -> str:
    code = normalize_text(code)
    if not code or code in {"0", "0000"}:
        return ""
    return code


def resolve_pr_placilo(row: Mapping[str, Any]) -> str:
    """Konto plačila po opredelitvi stranke (Minimax: SI 2200 / EU 2211 / tujec 2210).

    Generični 2200/2210/2211 (ali prazno/0000) se vedno uskladijo z EU/tujcem —
    uvoz iz Excela pogosto pusti 2200 tudi za Meta/OpenAI/Foshan.
    """
    from trops_studio.vat_accounts import infer_supplier_kind, payable_account

    code = _valid_account(str(row.get("placilo") or ""))
    expected = payable_account(infer_supplier_kind(row))
    if not code or code in ("0000", "2200", "2210", "2211"):
        return expected
    return code


def allocate_pr_accounts(row: Mapping[str, Any]) -> dict[str, str]:
    """
    Neodvisni konti po vrsticah odhodka (08 / 14·9a / 10 / 11 / ne gre v DDV).

    »Ne gre v knjigo« = znesek NI v DDV sistemu (KIR/KPR/DDV-O),
    knjiži se samo temeljnica (odhodek + plačilo), brez 160xx/260xx.

    Zgodovina: če je bil samo ta znesek in konto v odhodek01,
    prestavi ga na odhodek_excluded — odhodek01 ostane prazen (ni osnove 08).

    EU nabave: konto iz odhodek01 → odhodek10 (P10) / odhodek11 (P11);
    če ni osnove 08, odhodek01 ostane prazen.
    """
    od01 = _valid_account(str(row.get("odhodek01") or ""))
    od07 = _valid_account(str(row.get("odhodek07") or ""))
    od10 = _valid_account(str(row.get("odhodek10") or ""))
    od11 = _valid_account(str(row.get("odhodek11") or ""))
    od_ex = _valid_account(str(row.get("odhodek_excluded") or ""))

    net = decimal_value(row.get("net_taxable"))
    f76a = decimal_value(row.get("f76a"))
    exempt = (
        decimal_value(row.get("exempt_on"))
        + decimal_value(row.get("exempt_non"))
        + decimal_value(row.get("exempt_os"))
    )
    eu_g = decimal_value(row.get("eu_goods"))
    eu_s = decimal_value(row.get("eu_services"))
    excluded = decimal_value(row.get("excluded"))
    # <> 0 (tudi storno / negativni zneski)
    has_net = is_nonzero(net)
    has_f76a = is_nonzero(f76a)
    has_exempt = is_nonzero(exempt)
    has_eu_g = is_nonzero(eu_g)
    has_eu_s = is_nonzero(eu_s)
    has_excl = is_nonzero(excluded)
    only_excluded = bool(
        has_excl and not (has_net or has_f76a or has_exempt or has_eu_g or has_eu_s)
    )

    if only_excluded and not od_ex and od01:
        od_ex, od01 = od01, ""

    # EU 10/11: prestavi konto z 01 → 10 oz. 11 (P10/P11 <> 0)
    if has_eu_g or has_eu_s:
        seed = od01 or od10 or od11 or DEFAULT_PR_EXPENSE_ACCOUNT
        if has_eu_g and not od10:
            od10 = seed
        if has_eu_s and not od11:
            od11 = seed
        if not has_net and od01 and (od10 or od11):
            # samo EU nabava — konto ne ostane na 08
            od01 = ""

    if has_excl and not od_ex:
        # privzeto isti odhodek kot 08 (4190 …), ne 9729 — razen če je eksplicitno
        od_ex = od01 or DEFAULT_PR_EXCLUDED_ACCOUNT or DEFAULT_PR_EXPENSE_ACCOUNT

    # Oproščeno (P14→33): če ni posebnega konta, isti odhodek kot 08.
    if (has_exempt or has_f76a) and not od07:
        od07 = od01 or DEFAULT_PR_EXPENSE_ACCOUNT

    # Znesek = 0 → ni konta (ne kaži 4190 na prazni 14/08/10/11)
    if not has_net:
        od01 = ""
    if not (has_exempt or has_f76a):
        od07 = ""
    if not has_eu_g:
        od10 = ""
    if not has_eu_s:
        od11 = ""
    if not has_excl:
        od_ex = ""

    return {
        "odhodek01": od01,
        "odhodek07": od07,
        "odhodek10": od10,
        "odhodek11": od11,
        "odhodek_excluded": od_ex,
        "placilo": resolve_pr_placilo(row),
    }


def resolve_pr_excluded_account(row: Mapping[str, Any]) -> str:
    """Konto odhodka za znesek izven DDV (temeljnica brez DDV bloka)."""
    allocated = allocate_pr_accounts(row)
    return (
        allocated.get("odhodek_excluded")
        or DEFAULT_PR_EXCLUDED_ACCOUNT
        or DEFAULT_PR_EXPENSE_ACCOUNT
    )


# Znani EU DDV (ko je v SQL/listini brez predpone ali okrajšan)
_KNOWN_EU_VAT_BY_NAME: tuple[tuple[str, str], ...] = (
    ("google ireland", "IE6388047V"),
    ("adobe systems", "IE6364992H"),
    ("meta platforms", "IE9692928F"),
    ("facebook", "IE9692928F"),
    ("stripe payments", "IE3206488LH"),
    ("mailerlite", "IE3748416JH"),
    ("mailer lite", "IE3748416JH"),
    ("deepl", "DE349242045"),
    ("worldline", "ATU73496102"),
    ("tunturi", "NL854088969B01"),
    ("coma-sport", "PL6521723282"),
    ("coma sport", "PL6521723282"),
    ("t-shirt makers", "IT07569750636"),
    ("t-shirt markes", "IT07569750636"),
)


def _name_compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(name).casefold())


def _known_vat_from_name(name: str) -> str:
    """EU DDV iz naziva — tudi 'Mailer lite … Vilnius' → MailerLite."""
    blob = normalize_text(name).casefold()
    compact = _name_compact(name)
    for key, vat in _KNOWN_EU_VAT_BY_NAME:
        if key in blob:
            return vat
        needle = _name_compact(key)
        if needle and len(needle) >= 6 and needle in compact:
            return vat
    return ""


def _resolve_pr_vat_for_row(db: Database, row: Mapping[str, Any]) -> tuple[str, int | None]:
    """Najboljši EU ID za DDV + party_id za PR vrstico."""
    from trops_studio.parties_ensure import resolve_party_for_journal_row

    name = normalize_text(row.get("supplier_name"))
    vat = normalize_vat_id(row.get("vat_id") or row.get("tax_number"))
    known = _known_vat_from_name(name)
    party = resolve_party_for_journal_row(
        db,
        party_id=row.get("party_id"),
        vat_id=vat or known,
        name=name,
    )
    party_id = int(party["id"]) if party and party.get("id") else None
    if known and (not vat or len(vat) < 4 or not vat[:2].isalpha() or vat[:2] == "SI"):
        return known, party_id
    if vat and len(vat) >= 4 and vat[:2].isalpha() and vat[:2] != "SI":
        return ensure_eu_vat_id(vat, country=vat[:2], name=name), party_id
    if party:
        country = normalize_text(party.get("country"))[:2].upper()
        party_vat = normalize_vat_id(party.get("vat_id") or "")
        party_tax = national_tax_id(party.get("tax_number") or party.get("vat_id"), country=country)
        if party_vat and len(party_vat) >= 4 and party_vat[:2].isalpha() and party_vat[:2] != "SI":
            return ensure_eu_vat_id(party_vat, country=country or party_vat[:2], name=name), party_id
        seed = vat or party_vat or party_tax
        if known:
            return known, party_id
        return ensure_eu_vat_id(seed, country=country, name=name or str(party.get("name") or "")), party_id
    if known:
        return known, party_id
    if vat:
        return ensure_eu_vat_id(vat, country="", name=name), party_id
    return "", party_id


def repair_pr_eu_rows(db: Database) -> dict[str, int]:
    """
    Samodejno: EU 10/11 → konti na odhodek10/11; dopolni ID za DDV s predpono;
    uskladi party_id / šifrant.
    """
    fixed_acc = 0
    fixed_vat = 0
    fixed_party = 0
    for row in db.list_pr():
        if not (is_nonzero(row.get("eu_goods")) or is_nonzero(row.get("eu_services"))):
            continue
        payload = dict(row)
        changed = False
        acc_changed = False

        allocated = allocate_pr_accounts(row)
        for key in ("odhodek01", "odhodek10", "odhodek11", "placilo"):
            new_v = allocated.get(key) or ""
            if str(row.get(key) or "") != new_v:
                payload[key] = new_v
                changed = True
                if key in {"odhodek01", "odhodek10", "odhodek11"}:
                    acc_changed = True
        if acc_changed:
            fixed_acc += 1

        new_vat, party_id = _resolve_pr_vat_for_row(db, row)
        old_vat = normalize_vat_id(row.get("vat_id"))
        if new_vat and new_vat != old_vat:
            payload["vat_id"] = new_vat
            payload["tax_number"] = national_tax_id(new_vat)
            changed = True
            fixed_vat += 1
            if party_id:
                party = db.get_party(party_id)
                if party:
                    p = dict(party)
                    p["vat_id"] = new_vat
                    p["tax_number"] = national_tax_id(new_vat)
                    cc = new_vat[:2]
                    if new_vat.startswith("ATU"):
                        p["country"] = "AT"
                    elif cc.isalpha():
                        p["country"] = cc
                    p["is_foreign"] = 0 if p.get("country") == "SI" else 1
                    db.upsert_party(p, party_id)

        if party_id and int(row.get("party_id") or 0) != int(party_id):
            payload["party_id"] = party_id
            changed = True
            fixed_party += 1

        if changed:
            db.upsert_pr(payload, row_id=int(row["id"]))

    return {"accounts": fixed_acc, "vat": fixed_vat, "party": fixed_party}


def _pr_rule_accounts(src: Mapping[str, Any]) -> dict[str, Any]:
    """Izvleček kontov + zastavic iz pravila / zgodovine."""
    out: dict[str, Any] = {
        "odhodek01": normalize_text(src.get("odhodek01")),
        "odhodek07": normalize_text(src.get("odhodek07")),
        "odhodek10": normalize_text(src.get("odhodek10")),
        "odhodek11": normalize_text(src.get("odhodek11")),
        "odhodek_excluded": normalize_text(src.get("odhodek_excluded")),
        "placilo": normalize_text(src.get("placilo")) or "2200",
    }
    if src.get("self_assessment") is not None:
        out["self_assessment"] = int(bool(src.get("self_assessment")))
    if src.get("vat_deductible") is not None:
        out["vat_deductible"] = int(bool(src.get("vat_deductible")))
    return out


def _has_pr_accounts(acc: Mapping[str, Any]) -> bool:
    return bool(
        normalize_text(acc.get("odhodek01"))
        or normalize_text(acc.get("odhodek07"))
        or normalize_text(acc.get("odhodek10"))
        or normalize_text(acc.get("odhodek11"))
        or normalize_text(acc.get("odhodek_excluded"))
    )


def remember_supplier_rule(
    db: Database,
    row: Mapping[str, Any],
    *,
    source: str = "confirm",
) -> bool:
    """
    Shrani konte + samoobdavčitev/DDV odbitek za dobavitelja v account_rules.
    Vrne True, če je bilo kaj za zapomniti.
    """
    vat_id = normalize_vat_id(row.get("vat_id"))
    name = normalize_text(row.get("supplier_name"))
    if not (vat_id or name):
        return False
    allocated = allocate_pr_accounts(row)
    payload: dict[str, Any] = {
        "party_kind": "supplier",
        "match_vat": vat_id,
        "match_tax": tax_digits(row.get("tax_number") or vat_id),
        "match_name": name,
        "odhodek01": allocated.get("odhodek01") or "",
        "odhodek07": allocated.get("odhodek07") or "",
        "odhodek10": allocated.get("odhodek10") or "",
        "odhodek11": allocated.get("odhodek11") or "",
        "odhodek_excluded": allocated.get("odhodek_excluded") or "",
        "placilo": allocated.get("placilo") or row.get("placilo") or "2200",
        "source": source,
    }
    if not _has_pr_accounts(payload):
        return False
    if row.get("self_assessment") is not None:
        payload["self_assessment"] = row.get("self_assessment")
    if row.get("vat_deductible") is not None:
        payload["vat_deductible"] = row.get("vat_deductible")
    db.upsert_account_rule(payload)
    return True


def remember_customer_rule(
    db: Database,
    row: Mapping[str, Any],
    *,
    source: str = "confirm",
) -> bool:
    """Shrani prihodkovni konto za kupca v account_rules."""
    vat_id = normalize_vat_id(row.get("vat_id"))
    name = normalize_text(row.get("party_name"))
    account = normalize_text(row.get("account"))
    if not account or not (vat_id or name):
        return False
    db.upsert_account_rule(
        {
            "party_kind": "customer",
            "match_vat": vat_id,
            "match_tax": tax_digits(vat_id),
            "match_name": name,
            "prihodek": account,
            "source": source,
        }
    )
    return True


def resolve_pr_accounts(
    db: Database,
    *,
    vat_id: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Konto odhodka za dobavitelja: pravilo → zgodovina → 4190 (+ EU / ne gre)."""
    rule = db.find_account_rule(vat_id=vat_id, name=name, party_kind="supplier") or {}
    from_rule = _pr_rule_accounts(rule)
    if _has_pr_accounts(from_rule):
        return from_rule

    hist = db.last_pr_account(vat_id=vat_id, name=name)
    if hist and _has_pr_accounts(hist):
        packed = _pr_rule_accounts(hist)
        learn: dict[str, Any] = {
            "party_kind": "supplier",
            "match_vat": vat_id,
            "match_tax": tax_digits(vat_id),
            "match_name": name,
            **{k: packed[k] for k in (
                "odhodek01", "odhodek07", "odhodek10", "odhodek11",
                "odhodek_excluded", "placilo",
            )},
            "source": "history",
        }
        if "self_assessment" in packed:
            learn["self_assessment"] = packed["self_assessment"]
        if "vat_deductible" in packed:
            learn["vat_deductible"] = packed["vat_deductible"]
        db.upsert_account_rule(learn)
        return packed

    return {
        "odhodek01": DEFAULT_PR_EXPENSE_ACCOUNT,
        "odhodek07": "",
        "odhodek10": "",
        "odhodek11": "",
        "odhodek_excluded": "",
        "placilo": "2200",
    }


def resolve_ir_account(
    db: Database,
    *,
    vat_id: str = "",
    name: str = "",
    org_id: str | int | None = None,
) -> str:
    """Prihodkovni konto za kupca: pravilo → zgodovina → Minimax knjižljiv (ne 7622)."""
    from trops_studio.account_choices import (
        coerce_minimax_bookable_account,
        default_minimax_org_id,
    )

    rule = db.find_account_rule(vat_id=vat_id, name=name, party_kind="customer") or {}
    account = normalize_text(rule.get("prihodek"))
    if not account:
        hist = db.last_ir_account(vat_id=vat_id, name=name)
        if hist:
            db.upsert_account_rule(
                {
                    "party_kind": "customer",
                    "match_vat": vat_id,
                    "match_tax": tax_digits(vat_id),
                    "match_name": name,
                    "prihodek": hist,
                    "source": "history",
                }
            )
            account = hist
    if not account:
        account = DEFAULT_IR_REVENUE_ACCOUNT
    from trops_studio.ir_list_view import default_ir_account_for_region, ir_customer_region

    region = ir_customer_region({"vat_id": vat_id, "party_name": name})
    account = default_ir_account_for_region(region, account)
    org = org_id or default_minimax_org_id(db)
    return coerce_minimax_bookable_account(
        db, org, account, fallback=account or DEFAULT_IR_REVENUE_ACCOUNT
    )


def import_account_templates_from_accdb(db: Database, accdb: Path) -> dict[str, int]:
    """Prenese vzorce kontov iz Access zgodovine / tblPR_KontoPravila v SQLite."""
    if not accdb.is_file():
        raise FileNotFoundError(f"Access baza ni najdena: {accdb}")
    payload = read_account_history(accdb)
    recent_added = 0
    rules_added = 0
    seen_tax: set[str] = set()

    for raw in _as_list(payload.get("recent")):
        tax = tax_digits(raw.get("DS"))
        name = normalize_text(raw.get("6-Dobavitelj"))
        key = tax or name.casefold()
        if not key or key in seen_tax:
            continue
        values = {
            "odhodek01": normalize_text(raw.get("Odhodek01")),
            "odhodek07": normalize_text(raw.get("Odhodek07")),
            "placilo": normalize_text(raw.get("Plačilo")),
        }
        if not any(values.values()):
            continue
        seen_tax.add(key)
        db.upsert_account_rule(
            {
                "party_kind": "supplier",
                "match_tax": tax,
                "match_vat": f"SI{tax}" if tax else "",
                "match_name": name,
                "odhodek01": values["odhodek01"],
                "odhodek07": values["odhodek07"],
                "placilo": values["placilo"] or "2200",
                "source": f"accdb:{accdb.name}",
                "active": True,
            }
        )
        recent_added += 1

    for raw in _as_list(payload.get("rules")):
        tax = tax_digits(raw.get("DS") or raw.get("Davčna") or raw.get("IŠ za DDV"))
        name = normalize_text(raw.get("Dobavitelj") or raw.get("Naziv") or raw.get("match_name"))
        odhodek01 = normalize_text(raw.get("Odhodek01") or raw.get("Konto") or raw.get("KontoOdhodka"))
        if not (tax or name) or not odhodek01:
            continue
        db.upsert_account_rule(
            {
                "party_kind": "supplier",
                "match_tax": tax,
                "match_vat": f"SI{tax}" if tax else "",
                "match_name": name,
                "odhodek01": odhodek01,
                "odhodek07": normalize_text(raw.get("Odhodek07")),
                "placilo": normalize_text(raw.get("Plačilo") or raw.get("KontoPlacila") or "2200"),
                "source": f"pravilo:{accdb.name}",
                "active": True,
                "notes": normalize_text(raw.get("Opomba") or raw.get("Opis")),
            }
        )
        rules_added += 1

    learned = db.learn_account_rules_from_rows()
    return {
        "from_history": recent_added,
        "from_rules": rules_added,
        "from_sqlite_pr": learned.get("pr", 0),
        "from_sqlite_ir": learned.get("ir", 0),
    }
