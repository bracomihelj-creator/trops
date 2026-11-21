"""Šifrant kontov: Minimax (SQL minimax_accounts) — samo knjižljivi (AllowedPosting ≠ N)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from trops_studio.config import (
    DEFAULT_IR_EU_REVENUE_ACCOUNT,
    DEFAULT_IR_REVENUE_ACCOUNT,
    DEFAULT_PR_EXCLUDED_ACCOUNT,
    DEFAULT_PR_EXPENSE_ACCOUNT,
)
from trops_studio.db import Database
from trops_studio.money import normalize_text

COMMON_ACCOUNTS: tuple[tuple[str, str], ...] = (
    (DEFAULT_PR_EXPENSE_ACCOUNT, "Odhodek (privzeto)"),
    ("2200", "Obveznosti do dobaviteljev"),
    ("1200", "Terjatve do kupcev"),
    (DEFAULT_IR_REVENUE_ACCOUNT, "Prihodek (privzeto)"),
    (DEFAULT_IR_EU_REVENUE_ACCOUNT, "Prihodek blaga EU"),
    (DEFAULT_PR_EXCLUDED_ACCOUNT, "Ne gre v knjigo"),
    ("16000", "Vhodni DDV 22% (domači)"),
    ("16001", "Vhodni DDV 9,5% (domači)"),
    ("16002", "Vhodni DDV 5% (domači)"),
    ("16040", "Vhodni DDV 22% EU blago"),
    ("16044", "Vhodni DDV 22% EU storitve"),
    ("16042", "Vhodni DDV 22% tujci storitve"),
    ("26000", "Izhodni DDV 22% (domači)"),
    ("26001", "Izhodni DDV 9,5% (domači)"),
    ("26004", "Izhodni DDV 5% (domači)"),
    ("26040", "Izhodni DDV 22% EU blago"),
    ("26044", "Izhodni DDV 22% EU storitve"),
    ("26042", "Izhodni DDV 22% tujci storitve"),
    ("4000", "Stroški blaga"),
    ("2850", "Obveznosti — plačilo"),
    ("1000", "Zaloge"),
)

# org_id -> list[str]; "" = lokalno
_ACCOUNT_CACHE: dict[str, list[str]] = {}
_LOCAL_CACHE: list[str] | None = None
# org_id -> set of bookable codes
_CODE_SET_CACHE: dict[str, frozenset[str]] = {}


def _label(code: str, name: str = "") -> str:
    code = normalize_text(code)
    name = normalize_text(name)
    if code and name and name != code:
        return f"{code} — {name}"
    return code or name


def account_is_bookable(record: Mapping[str, Any] | None) -> bool:
    """
    Minimax Account.AllowedPosting:
      V = breme in dobro, B = samo breme, D = samo dobro → knjiženje OK
      N = knjiženje ni dovoljeno (sintetični 4, 40, 400 …)

    Application v API pri PROJEST pride vedno N — zato ga NE uporabljamo za filter.
    """
    if not record:
        return False
    code = normalize_text(record.get("code") or record.get("Code") or "")
    if not code:
        return False
    posting = normalize_text(
        record.get("allowed_posting") or record.get("AllowedPosting") or ""
    ).upper()
    if posting == "N":
        return False
    if posting in {"V", "B", "D"}:
        return True
    # Brez AllowedPosting (stari pull): polne šifre ≥ 4
    return len(code) >= 4


def clear_account_cache() -> None:
    global _LOCAL_CACHE
    _ACCOUNT_CACHE.clear()
    _CODE_SET_CACHE.clear()
    _MAP_CACHE.clear()
    _LOCAL_CACHE = None


def account_cache_has_minimax(org_id: str | int | None, db: Database | None = None) -> bool:
    """True, če so konti že v SQL (ali svež memory cache)."""
    key = str(org_id or "").strip()
    if not key:
        return False
    if key in _ACCOUNT_CACHE and len(_ACCOUNT_CACHE[key]) > len(COMMON_ACCOUNTS) + 5:
        return True
    if db is not None:
        try:
            return db.count_minimax_accounts(key) > 0
        except Exception:
            return False
    return False


def account_choices_from_db(db: Database) -> list[str]:
    """Lokalni fallback (brez Minimax SQL) — rules + pogosti."""
    global _LOCAL_CACHE
    if _LOCAL_CACHE is not None:
        return list(_LOCAL_CACHE)
    seen: dict[str, str] = {}
    for code, name in COMMON_ACCOUNTS:
        if code:
            seen[code] = _label(code, name)
    try:
        for code in db.list_account_codes():
            if not code or code in seen:
                continue
            if len(normalize_text(code)) < 4:
                continue
            seen[code] = _label(code)
    except Exception:
        pass
    _LOCAL_CACHE = sorted(seen.values(), key=lambda s: s.casefold())
    return list(_LOCAL_CACHE)


def account_choices_from_sql(db: Database, org_id: str | int | None) -> list[str]:
    """Kontni plan iz SQL — samo knjižljivi (AllowedPosting ≠ N)."""
    if not org_id:
        return []
    try:
        rows = db.list_minimax_accounts(org_id)
    except Exception:
        return []
    out: list[str] = []
    for r in rows:
        if not r.get("code") or not account_is_bookable(r):
            continue
        out.append(_label(str(r.get("code") or ""), str(r.get("name") or "")))
    return out


def fetch_and_store_minimax_accounts(db: Database, org_id: str | int) -> list[str]:
    """Minimax API → SQL (vsi konti + zastavice) → seznam samo knjižljivih."""
    key = str(org_id or "").strip()
    if not key:
        return []
    try:
        from trops_studio.minimax_parties import open_minimax_client

        client = open_minimax_client(key)
        catalog = client.account_catalog(bookable_only=False)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    labels: list[str] = []
    for item in catalog or []:
        code = normalize_text(item.get("code"))
        if not code:
            continue
        name = normalize_text(item.get("name") or "")
        row = {
            "code": code,
            "name": name,
            "id": item.get("id") or "",
            "allowed_posting": item.get("allowed_posting") or "",
            "application": item.get("application") or "",
        }
        items.append(row)
        if account_is_bookable(row):
            labels.append(_label(code, name))
    try:
        db.replace_minimax_accounts(key, items)
    except Exception:
        pass
    clear_account_cache()
    return labels


def load_account_choices(
    db: Database,
    org_id: str | int | None = None,
    *,
    fetch_minimax: bool = False,
) -> list[str]:
    """
    Šifrant za combobox:
    - če obstaja Minimax SQL za org → SAMO knjižljivi Minimax konti
      (ne mešaj lokalnih 4179 iz zgodovine, če jih v MM ni)
    - sicer lokalni fallback
    """
    cache_key = str(org_id or "").strip() or "local"
    if cache_key in _ACCOUNT_CACHE:
        return list(_ACCOUNT_CACHE[cache_key])

    if fetch_minimax and org_id:
        labels = fetch_and_store_minimax_accounts(db, org_id)
        if labels:
            result = sorted(labels, key=lambda s: s.casefold())
            _ACCOUNT_CACHE[cache_key] = result
            _CODE_SET_CACHE[cache_key] = frozenset(account_code_from_choice(x) for x in result)
            return list(result)

    if org_id:
        mm = account_choices_from_sql(db, org_id)
        if mm:
            result = sorted(mm, key=lambda s: s.casefold())
            _ACCOUNT_CACHE[cache_key] = result
            _CODE_SET_CACHE[cache_key] = frozenset(account_code_from_choice(x) for x in result)
            return list(result)

    result = account_choices_from_db(db)
    _ACCOUNT_CACHE[cache_key] = result
    _CODE_SET_CACHE[cache_key] = frozenset(account_code_from_choice(x) for x in result)
    return list(result)


def warm_account_cache_minimax(
    db: Database,
    org_id: str | int | None,
    *,
    force: bool = False,
) -> list[str]:
    """Naloži kontni plan: SQL; API če prazen / force / manjkajo AllowedPosting zastavice."""
    if not org_id:
        return load_account_choices(db, None, fetch_minimax=False)
    key = str(org_id).strip()
    sql_n = 0
    need_meta = False
    try:
        sql_n = db.count_minimax_accounts(key)
        need_meta = db.minimax_accounts_need_refresh(key)
    except Exception:
        sql_n = 0
        need_meta = True

    if not force and sql_n > 0 and not need_meta:
        _ACCOUNT_CACHE.pop(key, None)
        _CODE_SET_CACHE.pop(key, None)
        return load_account_choices(db, org_id, fetch_minimax=False)

    _ACCOUNT_CACHE.pop(key, None)
    _CODE_SET_CACHE.pop(key, None)
    return load_account_choices(db, org_id, fetch_minimax=True)


def account_code_from_choice(value: str) -> str:
    """Iz '4190 — Odhodek' vzami '4190'."""
    text = normalize_text(value)
    if "—" in text:
        return text.split("—", 1)[0].strip()
    return text.split()[0] if text else ""


def is_complete_account_code(value: str, *, min_len: int = 4) -> bool:
    """Polna šifra (ne filter '4' / '41' med tipkanjem)."""
    code = account_code_from_choice(value)
    if not code or code in {"0", "0000"}:
        return False
    if code.isdigit():
        return len(code) >= min_len
    return len(code) >= min_len


def resolve_committed_account(value: str, *, fallback: str = "") -> str:
    """Za predogled/shranjevanje: samo popolna šifra, sicer fallback."""
    code = account_code_from_choice(value)
    if is_complete_account_code(code):
        return code
    fb = account_code_from_choice(fallback)
    return fb if is_complete_account_code(fb) else ""


def minimax_account_codes(db: Database, org_id: str | int | None) -> frozenset[str]:
    """Množica knjižljivih Minimax šifer za org."""
    key = str(org_id or "").strip() or "local"
    if key in _CODE_SET_CACHE:
        return _CODE_SET_CACHE[key]
    choices = load_account_choices(db, org_id, fetch_minimax=False)
    codes = frozenset(account_code_from_choice(x) for x in choices if account_code_from_choice(x))
    _CODE_SET_CACHE[key] = codes
    return codes


def is_known_account_code(
    db: Database,
    org_id: str | int | None,
    code: str,
) -> bool:
    """True, če je šifra v (Minimax) šifrantu za izbiro."""
    code = account_code_from_choice(code)
    if not code:
        return False
    return code in minimax_account_codes(db, org_id)


# Privzeta Trops → Minimax mapiranja (seed v SQL account_code_map).
TROPS_TO_MINIMAX_DEFAULTS: dict[str, str] = {
    # IR prihodki
    "7622": "7620",  # Trops prihodek blaga — v MM ni 7622
    "7409": "7400",
    # PR odhodki (Trops analitika …1 → MM …0 / 4190)
    "4061": "4060",
    "4071": "4070",
    "4111": "4190",
    "4119": "4110",
    "4151": "4150",
    "4191": "4190",
    "4199": "4190",
    "4735": "4730",
    "4896": "4890",
    # EU / zaloge blaga (Trops → MM obračun nabave)
    "6526": "6500",  # pridobitve blaga EU
    "6527": "6500",
    "660": "6500",  # sintetični 660 (AllowedPosting N)
    "66": "6500",
    # DDV (Trops 1600/2600 + sufiks → MM 5-mestni)
    "1600-0": "16000",
    "1600-1": "16001",
    "1600-8": "16040",
    "1600": "16000",
    "1619": "1610",
    "2600-0": "26000",
    "2600-2": "26000",
    "2600-8": "26040",
    "2600": "26000",
    "260-80": "26040",
    "2629": "2620",
    # Ostalo (pogoste Trops šifre → najbližji MM)
    "1006": "1650",  # Integra: kartice občanov → MM 1650 (ne blagajna 1000)
    "1762": "1760",
    "2555": "2550",
}
# Združljivost
_TROPS_TO_MINIMAX = TROPS_TO_MINIMAX_DEFAULTS

# org_id -> trops→minimax (vključno defaults + SQL)
_MAP_CACHE: dict[str, dict[str, str]] = {}


def _account_base(code: str) -> str:
    text = account_code_from_choice(code)
    if not text:
        return ""
    return text.split("-", 1)[0].split(".", 1)[0]


def _sibling_zero_account(code: str) -> str:
    """4061 → 4060, 4151 → 4150 (pogosta Trops → MM zamenjava)."""
    if len(code) >= 4 and code.isdigit() and code.endswith("1"):
        return code[:-1] + "0"
    return ""


def _nearest_zero_account(code: str) -> str:
    """4119 → 4110, 4735 → 4730 (zadnja cifra → 0), če še ni …0."""
    if len(code) >= 4 and code.isdigit() and not code.endswith("0"):
        return code[:-1] + "0"
    return ""


def load_account_code_maps(db: Database, org_id: str | int | None = None) -> dict[str, str]:
    """Defaults + SQL account_code_map (SQL prepiše default)."""
    key = str(org_id or "").strip() or default_minimax_org_id(db) or "local"
    if key in _MAP_CACHE:
        return dict(_MAP_CACHE[key])
    merged = dict(TROPS_TO_MINIMAX_DEFAULTS)
    try:
        db.seed_default_account_code_maps(key if key != "local" else "")
        merged.update(db.get_account_code_map_dict(key if key != "local" else None))
    except Exception:
        pass
    _MAP_CACHE[key] = dict(merged)
    return dict(merged)


def suggest_minimax_account(
    db: Database,
    org_id: str | int | None,
    trops_code: str,
) -> str:
    """Predlagaj Minimax konto za Trops šifro (mapa / sibling / nearest / prazen)."""
    raw = account_code_from_choice(trops_code)
    base = _account_base(raw)
    maps = load_account_code_maps(db, org_id)
    codes = minimax_account_codes(db, org_id)
    sibling = _sibling_zero_account(base)
    nearest = _nearest_zero_account(base)
    for candidate in (
        maps.get(raw, ""),
        maps.get(base, ""),
        sibling,
        nearest,
        base,
        raw,
    ):
        if not candidate:
            continue
        if not codes or candidate in codes:
            return candidate
    return ""


def account_is_resolved(
    db: Database,
    org_id: str | int | None,
    code: str,
) -> bool:
    """True, če je konto knjižljiv v MM ali ima veljavno mapiranje nanj."""
    raw = account_code_from_choice(code)
    if not raw:
        return True
    base = _account_base(raw)
    codes = minimax_account_codes(db, org_id)
    if not codes:
        return True  # ni plana — ne blokiraj
    if raw in codes or base in codes:
        return True
    maps = load_account_code_maps(db, org_id)
    for key in (raw, base):
        target = maps.get(key, "")
        if target and target in codes:
            return True
    sibling = _sibling_zero_account(base)
    return bool(sibling and sibling in codes)


def coerce_minimax_bookable_account(
    db: Database,
    org_id: str | int | None,
    code: str,
    *,
    fallback: str = "",
) -> str:
    """Vrni knjižljiv Minimax konto (mapa SQL/default → sibling → fallback)."""
    raw = account_code_from_choice(code)
    base = _account_base(raw)
    fb = account_code_from_choice(fallback)
    if not raw and not fb:
        return ""
    if not fb:
        fb = DEFAULT_IR_REVENUE_ACCOUNT
    maps = load_account_code_maps(db, org_id)
    alias = maps.get(raw) or maps.get(base) or ""
    sibling = _sibling_zero_account(base)
    nearest = _nearest_zero_account(base)
    codes = minimax_account_codes(db, org_id)
    if not codes:
        return alias or sibling or nearest or base or fb
    for candidate in (alias, raw, base, sibling, nearest, fb):
        if candidate and candidate in codes:
            return candidate
    return fb


def default_minimax_org_id(db: Database) -> str:
    """Če je v SQL samo en org kontnega plana — uporabi ga."""
    try:
        rows = db.list_minimax_accounts()
    except Exception:
        return ""
    orgs = sorted({normalize_text(r.get("org_id")) for r in rows if r.get("org_id")})
    return orgs[0] if len(orgs) == 1 else ""


def collect_used_account_codes(
    db: Database,
    *,
    include_kisanal: bool = True,
    include_ir_pr: bool = True,
    include_journal: bool = True,
) -> dict[str, int]:
    """Števci uporabljenih kontov (kisanal + IR/PR + journal_lines)."""
    counts: dict[str, int] = {}
    with db.session() as conn:
        tables = {
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if include_kisanal and "kisanal" in tables:
            for code, n in conn.execute(
                """
                SELECT TRIM(anal_akon), COUNT(*)
                FROM kisanal
                WHERE TRIM(COALESCE(anal_akon, '')) <> ''
                GROUP BY 1
                """
            ):
                key = account_code_from_choice(code) or _account_base(str(code or ""))
                if key:
                    counts[key] = counts.get(key, 0) + int(n or 0)
        if include_ir_pr:
            for code, n in conn.execute(
                """
                SELECT TRIM(account), COUNT(*) FROM ir_rows
                WHERE TRIM(COALESCE(account, '')) <> ''
                GROUP BY 1
                """
            ):
                key = account_code_from_choice(code)
                if key:
                    counts[key] = counts.get(key, 0) + int(n or 0)
            for col in (
                "odhodek01",
                "odhodek07",
                "odhodek10",
                "odhodek11",
                "odhodek_excluded",
                "placilo",
            ):
                for code, n in conn.execute(
                    f"""
                    SELECT TRIM({col}), COUNT(*) FROM pr_rows
                    WHERE TRIM(COALESCE({col}, '')) <> ''
                    GROUP BY 1
                    """
                ):
                    key = account_code_from_choice(code)
                    if key:
                        counts[key] = counts.get(key, 0) + int(n or 0)
        if include_journal and "journal_lines" in tables:
            for code, n in conn.execute(
                """
                SELECT TRIM(account), COUNT(*) FROM journal_lines
                WHERE TRIM(COALESCE(account, '')) <> ''
                GROUP BY 1
                """
            ):
                key = account_code_from_choice(code)
                if key:
                    counts[key] = counts.get(key, 0) + int(n or 0)
    return counts


def find_unmapped_accounts(
    db: Database,
    org_id: str | int | None = None,
    *,
    codes: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Konti, ki niso knjižljivi v Minimax in še nimajo veljavne mape."""
    org = str(org_id or "").strip() or default_minimax_org_id(db)
    used = collect_used_account_codes(db) if codes is None else {}
    if codes is not None:
        for c in codes:
            key = account_code_from_choice(c) or _account_base(str(c or ""))
            if key:
                used[key] = used.get(key, 0) + 1
    mm_codes = minimax_account_codes(db, org)
    if not mm_codes:
        return []
    out: list[dict[str, Any]] = []
    for trops, count in sorted(used.items(), key=lambda x: x[0]):
        if account_is_resolved(db, org, trops):
            continue
        out.append(
            {
                "trops_code": trops,
                "count": count,
                "suggested": suggest_minimax_account(db, org, trops),
            }
        )
    return out


def filter_account_choices(choices: Sequence[str], needle: str) -> list[str]:
    """Živi filter: šifra (41 → 4100…) ali besedilo v nazivu."""
    n = normalize_text(needle).casefold().strip()
    if "—" in n:
        left, right = n.split("—", 1)
        left, right = left.strip(), right.strip()
        n = left if (left and left[0].isdigit()) else (right or left)
    if n and n[0].isdigit():
        n = n.split()[0]
    if not n:
        return list(choices)
    digit_mode = n[0].isdigit()
    prefix: list[str] = []
    contains: list[str] = []
    for label in choices:
        code = account_code_from_choice(label).casefold()
        full = label.casefold()
        name = full.split("—", 1)[1].strip() if "—" in full else ""
        if digit_mode:
            hit_prefix = code.startswith(n)
            hit_contains = False
        else:
            hit_prefix = name.startswith(n) or code.startswith(n) or full.startswith(n)
            hit_contains = (not hit_prefix) and (n in name or n in code or n in full)
        if hit_prefix:
            prefix.append(label)
        elif hit_contains:
            contains.append(label)
    return prefix + contains


def ensure_choice(choices: Sequence[str], code: str) -> list[str]:
    """
    Dodaj trenutni konto v seznam samo za prikaz (če manjka).
    Ne pomeni, da je veljaven Minimax konto — validacija ob shrani.
    """
    code = normalize_text(code)
    if not code or code in {"0", "0000"}:
        return list(choices)
    out = list(choices)
    codes = {account_code_from_choice(c) for c in out}
    if code not in codes:
        out.insert(0, f"{code} — ⚠ ni v Minimax")
    return out


def party_choices(parties: Sequence[dict[str, Any]]) -> list[str]:
    """Naziv [davčna] · MM — za Combobox / SQL filter."""
    result: list[str] = []
    for party in parties:
        name = normalize_text(party.get("name"))
        vat = normalize_text(party.get("vat_id") or party.get("tax_number"))
        mm = normalize_text(party.get("minimax_code"))
        if not name:
            continue
        if vat and mm:
            result.append(f"{name} [{vat}] · {mm}")
        elif vat:
            result.append(f"{name} [{vat}]")
        elif mm:
            result.append(f"{name} · {mm}")
        else:
            result.append(name)
    return result


def parse_party_choice(label: str) -> tuple[str, str]:
    """Vrne (name, vat) iz 'Naziv [SI…]' ali 'Naziv [SI…] · MM'."""
    text = normalize_text(label)
    if " · " in text:
        text = text.split(" · ", 1)[0].strip()
    if "]" in text and "[" in text:
        name, rest = text.rsplit("[", 1)
        vat = rest.split("]", 1)[0].strip()
        return name.strip(), vat
    return text, ""
