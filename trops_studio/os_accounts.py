"""Konti nepremičnin / osnovnih sredstev (razred 01–04).

Konto 0470 (in ostali OS): celotna nabava gre v KPR 08 in 13 → DDV-O 31 in 35.
Nepremičnine (0210/02/03): KPR 08 in 12 → DDV-O 31 in 34.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Mapping

from trops_studio.account_choices import account_code_from_choice
from trops_studio.money import decimal_value, normalize_text

# Obdavčeno OS: 12/13 sta »od tega« v 08 (AOP 31). Oproščeno: 14 → 33, 15 → 34.
OS_KPR_META: dict[str, dict[str, str]] = {
    "12": {"p": "P12", "aop": "34", "label": "12 — nepremičnine (AOP 31+34)"},
    "13": {"p": "P13", "aop": "35", "label": "13 — drugo OS (AOP 31+35)"},
    "14": {"p": "P14", "aop": "33", "label": "14 — oproščene (AOP 33)"},
    "15": {"p": "P15", "aop": "34", "label": "15 — nepr. opros. (AOP 34)"},
}
_OS_ALSO_IN_P8 = frozenset({"12", "13"})
OS_KPR_LABELS = tuple(item["label"] for item in OS_KPR_META.values())
OS_KPR_TAXED_LABELS = tuple(OS_KPR_META[k]["label"] for k in ("12", "13"))
OS_KPR_EXEMPT_LABELS = tuple(OS_KPR_META[k]["label"] for k in ("14", "15"))
DEFAULT_OS_CONTRA = "1300"
ZERO = Decimal("0.00")

# 01 neopredmetena, 02 zgradbe/zemljišča, 03 naložbene nepremičnine, 04 oprema/0470 v gradnji
_OS_PREFIXES = ("01", "02", "03", "04")
_OS_EXACT = frozenset(
    {
        "0210",
        "0470",
        "0200",
        "0211",
        "0400",
        "0410",
        "0420",
        "0430",
        "0440",
        "0450",
        "0460",
    }
)


def account_digits(value: str) -> str:
    return "".join(ch for ch in account_code_from_choice(value) if ch.isdigit())


def is_fixed_asset_account(value: str) -> bool:
    """0470, 0210 in ostali konti OS / nepremičnin (ne 05 popravek, ne 13 predujem)."""
    digits = account_digits(value)
    if not digits:
        return False
    if digits in _OS_EXACT:
        return True
    return len(digits) >= 3 and digits[:2] in _OS_PREFIXES


def first_fixed_asset_account(*values: str) -> str:
    for value in values:
        code = account_code_from_choice(normalize_text(value))
        if is_fixed_asset_account(code):
            return code
    return ""


def os_kpr_code(value: str) -> str:
    text = normalize_text(value)
    if text in OS_KPR_META:
        return text
    digits = "".join(ch for ch in text if ch.isdigit())[:2]
    return digits if digits in OS_KPR_META else ""


def os_kpr_label(value: str) -> str:
    code = os_kpr_code(value)
    return OS_KPR_META[code]["label"] if code else ""


def os_aop_hint(value: str) -> str:
    """Kratek AOP niz za status (13 → 31+35)."""
    code = os_kpr_code(value)
    if code == "12":
        return "31+34"
    if code == "13":
        return "31+35"
    if code == "14":
        return "33"
    if code == "15":
        return "34"
    return OS_KPR_META.get(code, {}).get("aop", "") if code else ""


def default_os_kpr_field(account: str) -> str:
    """0210/02/03 → 12 nepremičnine; 0470/oprema → 13 drugo OS."""
    digits = account_digits(account)
    if digits.startswith(("02", "03")):
        return "12"
    return "13"


def _raw_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_json")
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def resolve_os_allocations(row: Mapping[str, Any]) -> list[tuple[str, Decimal]]:
    """Seznam (KPR 12/13/14/15, znesek) za DDV-O 34/35."""
    raw = _raw_dict(row)
    source = row.get("os_allocations")
    if source is None:
        source = raw.get("os_allocations")
    out: list[tuple[str, Decimal]] = []
    if isinstance(source, list):
        for item in source:
            if not isinstance(item, Mapping):
                continue
            field = os_kpr_code(str(item.get("kpr") or item.get("os_kpr") or ""))
            amount = decimal_value(item.get("amount") or item.get("os_amount"))
            if field and amount != ZERO:
                out.append((field, amount))
    if out:
        return out
    field = os_kpr_code(str(row.get("os_kpr") or raw.get("os_kpr") or ""))
    amount = decimal_value(row.get("os_amount") if row.get("os_amount") is not None else raw.get("os_amount"))
    if field and amount != ZERO:
        return [(field, amount)]
    return []


def resolve_os_book(row: Mapping[str, Any]) -> tuple[str, Decimal, str]:
    """(prvo KPR polje, vsota OS, konto razlike — 1300 v minus)."""
    raw = _raw_dict(row)
    allocs = resolve_os_allocations(row)
    field = allocs[0][0] if allocs else os_kpr_code(str(row.get("os_kpr") or raw.get("os_kpr") or ""))
    amount = sum((item[1] for item in allocs), ZERO)
    if amount == ZERO:
        amount = decimal_value(row.get("os_amount") if row.get("os_amount") is not None else raw.get("os_amount"))
    contra = account_code_from_choice(str(row.get("os_contra") or raw.get("os_contra") or DEFAULT_OS_CONTRA))
    return field, amount, contra or DEFAULT_OS_CONTRA


def add_os_amount_to_kpr(kpr: dict[str, Any], row: Mapping[str, Any]) -> None:
    """Konto OS (0470): nabava v KPR 08 in 13 → DDV-O 31 in 35.

    Prenos v OS (KPR 13) se prišteje tudi k P8; osnova 08 na kontu 0470/0210
    gre tudi v P13/P12 (od tega OS / nepremičnine).
    """
    allocs = resolve_os_allocations(row)
    for field, amount in allocs:
        key = OS_KPR_META[field]["p"]
        kpr[key] = decimal_value(kpr.get(key)) + amount
        if field in _OS_ALSO_IN_P8:
            kpr["P8"] = decimal_value(kpr.get("P8")) + amount

    raw = _raw_dict(row)
    expense = first_fixed_asset_account(
        str(row.get("odhodek01") or ""),
        str(raw.get("odhodek01") or ""),
    )
    net = decimal_value(row.get("net_taxable") if row.get("net_taxable") is not None else raw.get("net_taxable"))
    if not expense or net == ZERO:
        return
    field = next((item[0] for item in allocs if item[0] in _OS_ALSO_IN_P8), "")
    if field not in _OS_ALSO_IN_P8:
        field = os_kpr_code(str(row.get("os_kpr") or raw.get("os_kpr") or ""))
    if field not in _OS_ALSO_IN_P8:
        field = default_os_kpr_field(expense)
    key = OS_KPR_META[field]["p"]
    kpr[key] = decimal_value(kpr.get(key)) + net
