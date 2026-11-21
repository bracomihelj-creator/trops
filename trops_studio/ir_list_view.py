"""IR seznam: regija kupca + EU prodaja (76301, splošna osnova blago brez DDV)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from trops_studio.config import DEFAULT_IR_EU_REVENUE_ACCOUNT, DEFAULT_IR_REVENUE_ACCOUNT
from trops_studio.money import decimal_value, is_nonzero, normalize_text
from trops_studio.pr_list_view import (
    EU_COUNTRY_CODES,
    pr_supplier_country,
    pr_supplier_region,
    region_label,
)

ZERO = Decimal("0.00")

__all__ = (
    "EU_COUNTRY_CODES",
    "apply_ir_eu_sale",
    "default_ir_account_for_region",
    "ir_customer_country",
    "ir_customer_region",
    "ir_display_osnova",
    "ir_party_row",
    "is_ir_eu_sale",
    "region_label",
)


def ir_party_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """PR helperji berejo supplier_name — IR ima party_name."""
    data = dict(row)
    if not data.get("supplier_name"):
        data["supplier_name"] = data.get("party_name") or ""
    return data


def ir_customer_country(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> str:
    """ISO država kupca (SI / HR / DE / US …)."""
    return pr_supplier_country(ir_party_row(row), party)


def ir_customer_region(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> str:
    """SI | EU | FOREIGN."""
    return pr_supplier_region(ir_party_row(row), party)


def is_ir_eu_sale(row: Mapping[str, Any], party: Mapping[str, Any] | None = None) -> bool:
    return ir_customer_region(row, party) == "EU"


def default_ir_account_for_region(region: str, current: str = "") -> str:
    """Domači 7620; EU 7620/prazno → 76301. Drugi konto ostane."""
    code = normalize_text(current)
    if region == "EU" and (not code or code == DEFAULT_IR_REVENUE_ACCOUNT):
        return DEFAULT_IR_EU_REVENUE_ACCOUNT
    return code or DEFAULT_IR_REVENUE_ACCOUNT


def ir_display_osnova(row: Mapping[str, Any]) -> Decimal:
    """Osnova za prikaz: domači P7 + EU blago P10 + storitve P11 + oproščeno."""
    return (
        decimal_value(row.get("net"))
        + decimal_value(row.get("eu_goods"))
        + decimal_value(row.get("eu_services"))
        + decimal_value(row.get("exempt"))
    )


def apply_ir_eu_sale(
    row: Mapping[str, Any],
    party: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """EU kupec: 7620→76301; znesek brez DDV → eu_goods (KIR P10 / DDV-O AOP 12).

    Minimax: P10 = splošna osnova BLAGO brez DDV (ne oproščeno, ne storitev).
    """
    data = dict(row)
    region = ir_customer_region(data, party)
    data["account"] = default_ir_account_for_region(region, str(data.get("account") or ""))
    if region != "EU":
        return data

    net = decimal_value(data.get("net"))
    exempt = decimal_value(data.get("exempt"))
    eu_g = decimal_value(data.get("eu_goods"))
    eu_s = decimal_value(data.get("eu_services"))
    has_vat = is_nonzero(data.get("vat_22")) or is_nonzero(data.get("vat_95"))

    pool = eu_g + eu_s + exempt
    if not has_vat:
        pool += net
        data["net"] = ZERO
        data["base_22"] = ZERO
    data["exempt"] = ZERO
    data["eu_services"] = ZERO
    data["eu_goods"] = pool
    return data
