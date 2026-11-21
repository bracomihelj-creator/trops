"""Predogled + izvor knjižb iz IR/PR zneskov/kontov (shranjeno tudi v journal_lines)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Mapping, Sequence

from trops_studio.accounts import allocate_pr_accounts
from trops_studio.os_accounts import resolve_os_book
from trops_studio.config import (
    DEFAULT_IR_REVENUE_ACCOUNT,
    DEFAULT_PR_EXCLUDED_ACCOUNT,
    DEFAULT_PR_EXPENSE_ACCOUNT,
)
from trops_studio.ir_list_view import apply_ir_eu_sale
from trops_studio.money import decimal_value, is_nonzero, money_text, normalize_text
from trops_studio.pr_vat_flags import resolve_pr_vat_flags
from trops_studio.vat_accounts import (
    VAT_IN,
    VAT_OUT,
    ir_vat_kind,
    kind_label,
    pr_vat_kind,
    vat_in_account,
    vat_out_account,
)

ZERO = Decimal("0.00")

# Združljivost (domači) — raje uporabi vat_in_account / vat_out_account
__all__ = [
    "VAT_IN",
    "VAT_OUT",
    "extra_journal_lines",
    "extra_lines_net",
    "journal_imbalance",
    "normalize_extra_journal_line",
    "serialize_extra_journal_lines",
    "preview_pr_journals",
    "preview_ir_journals",
]


def _raw_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_json")
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def normalize_extra_journal_line(item: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Konto + debet/kredit (negativni znesek = nasprotna stran)."""
    if not isinstance(item, Mapping):
        return None
    konto = normalize_text(item.get("konto") or item.get("account"))
    if not konto:
        return None
    debit = decimal_value(item.get("debet") or item.get("debit"))
    credit = decimal_value(item.get("kredit") or item.get("credit"))
    if debit < 0 and credit == ZERO:
        credit = -debit
        debit = ZERO
    if credit < 0 and debit == ZERO:
        debit = -credit
        credit = ZERO
    if debit > 0 and credit > 0:
        # Ena stran — večji znesek ostane
        if debit >= credit:
            debit -= credit
            credit = ZERO
        else:
            credit -= debit
            debit = ZERO
    if debit == ZERO and credit == ZERO:
        return None
    opis = normalize_text(item.get("opis") or item.get("description"))
    return {
        "konto": konto,
        "debet": debit,
        "kredit": credit,
        "opis": opis,
        "extra": True,
        "kpr_diff": bool(item.get("kpr_diff")),
    }


def extra_journal_lines(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = _raw_dict(row)
    source = row.get("extra_journal_lines")
    if source is None:
        source = raw.get("extra_journal_lines")
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes)):
        return []
    lines: list[dict[str, Any]] = []
    desc = normalize_text(row.get("document_no") or row.get("internal_no") or row.get("notes")) or "PR"
    for item in source:
        line = normalize_extra_journal_line(item if isinstance(item, Mapping) else {})
        if not line:
            continue
        if not line["opis"]:
            line["opis"] = f"{desc} — dodatna knjižba"
        lines.append(line)
    return lines


def serialize_extra_journal_lines(lines: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in lines or []:
        if not isinstance(item, Mapping):
            continue
        line = normalize_extra_journal_line(item)
        if not line:
            continue
        row = {
            "konto": str(line["konto"]),
            "debet": str(line["debet"]),
            "kredit": str(line["kredit"]),
            "opis": str(line["opis"] or ""),
        }
        if line.get("kpr_diff"):
            row["kpr_diff"] = True
        out.append(row)
    return out


def extra_lines_net(row: Mapping[str, Any]) -> Decimal:
    """Predznačena vsota dodatnih vrstic (debet − kredit)."""
    total = ZERO
    for line in extra_journal_lines(row):
        total += decimal_value(line.get("debet")) - decimal_value(line.get("kredit"))
    return total


def journal_imbalance(lines: Sequence[Mapping[str, Any]]) -> Decimal:
    """Debet − kredit; 0 = temeljnica štima."""
    debit = sum((decimal_value(line.get("debet")) for line in lines), ZERO)
    credit = sum((decimal_value(line.get("kredit")) for line in lines), ZERO)
    return debit - credit


def _append_balancing_payment(
    lines: list[dict[str, Any]],
    *,
    placilo: str,
    desc: str,
    self_assessment: bool,
    amount: Any = None,
) -> None:
    pay_tip = " — plačilo (samoobdavčitev)" if self_assessment else " — plačilo"
    if amount is not None and str(amount).strip() != "":
        pay = decimal_value(amount)
        if not is_nonzero(pay):
            return
        if pay > ZERO:
            lines.append(
                {
                    "konto": placilo,
                    "debet": ZERO,
                    "kredit": pay,
                    "opis": f"{desc}{pay_tip}",
                    "payment": True,
                }
            )
        else:
            lines.append(
                {
                    "konto": placilo,
                    "debet": -pay,
                    "kredit": ZERO,
                    "opis": f"{desc}{pay_tip}",
                    "payment": True,
                }
            )
        return
    delta = journal_imbalance(lines)
    if not is_nonzero(delta):
        return
    if delta > ZERO:
        lines.append(
            {
                "konto": placilo,
                "debet": ZERO,
                "kredit": delta,
                "opis": f"{desc}{pay_tip}",
                "payment": True,
            }
        )
    else:
        lines.append(
            {
                "konto": placilo,
                "debet": -delta,
                "kredit": ZERO,
                "opis": f"{desc}{pay_tip}",
                "payment": True,
            }
        )


def preview_pr_journals(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Vrstice: konto, debet, kredit, opis — Minimax 160xx/260xx po tipu prometa."""
    lines: list[dict[str, Any]] = []
    desc = normalize_text(row.get("document_no") or row.get("internal_no") or row.get("notes")) or "PR"
    acc = allocate_pr_accounts(row)
    expense = acc["odhodek01"] or DEFAULT_PR_EXPENSE_ACCOUNT
    expense07 = acc["odhodek07"]
    expense10 = acc["odhodek10"] or expense07 or expense
    expense11 = acc["odhodek11"] or expense07 or expense
    placilo = acc["placilo"]
    excluded_acc = acc["odhodek_excluded"] or DEFAULT_PR_EXCLUDED_ACCOUNT
    extras = extra_journal_lines(row)
    raw_pay = _raw_dict(row)
    placilo_amount = row.get("placilo_amount")
    if placilo_amount is None:
        placilo_amount = raw_pay.get("placilo_amount")
    _os_field, os_amt, os_contra = resolve_os_book(row)
    net = decimal_value(row.get("net_taxable"))
    os_08_lines: list[dict[str, Any]] = []
    if is_nonzero(os_amt):
        extras = [
            line
            for line in extras
            if str(line.get("konto") or "") not in {expense, os_contra}
            and not line.get("kpr_diff")
        ]
        total_08 = net + os_amt
        os_08_lines = [
            {
                "konto": expense,
                "debet": total_08,
                "kredit": ZERO,
                "opis": f"08 > {expense} > {money_text(total_08)}",
                "extra": True,
            },
            {
                "konto": os_contra,
                "debet": ZERO,
                "kredit": os_amt,
                "opis": f"08 > {os_contra} > -{money_text(os_amt)}",
                "extra": True,
                "kpr_diff": True,
            },
        ]
    extra_accounts = {line["konto"] for line in extras} | {line["konto"] for line in os_08_lines}
    f76a = decimal_value(row.get("f76a"))
    eu_g = decimal_value(row.get("eu_goods"))
    eu_s = decimal_value(row.get("eu_services"))
    exempt = (
        decimal_value(row.get("exempt_on"))
        + decimal_value(row.get("exempt_non"))
        + decimal_value(row.get("exempt_os"))
    )
    vat22 = decimal_value(row.get("vat_22"))
    vat95 = decimal_value(row.get("vat_95"))
    vat5 = decimal_value(row.get("vat_5"))
    excluded = decimal_value(row.get("excluded"))
    nondeduct = decimal_value(row.get("nondeduct_22")) + decimal_value(row.get("nondeduct_95"))
    reported_vat = vat22 + vat95 + vat5
    self_assessment, vat_deductible, _offer = resolve_pr_vat_flags(row)
    kind = pr_vat_kind(row)
    tip = kind_label(kind)

    excluded_only = is_nonzero(excluded) and not (
        is_nonzero(net) or is_nonzero(f76a) or is_nonzero(eu_g) or is_nonzero(eu_s)
        or is_nonzero(vat22) or is_nonzero(vat95) or is_nonzero(vat5)
    )
    if excluded_only:
        if excluded_acc not in extra_accounts:
            lines.append({"konto": excluded_acc, "debet": excluded, "kredit": ZERO, "opis": f"{desc} — ni v DDV"})
        lines.extend(extras)
        _append_balancing_payment(
            lines,
            placilo=placilo,
            desc=desc,
            self_assessment=False,
            amount=placilo_amount,
        )
        return lines

    # Strošek (osnova); <> 0 tudi za storno; brez odbitka se DDV prišteje strošku.
    # Če dodatna vrstica že knjiži isti konto (npr. 0470=1000, 1300=-800), avto 08 izpusti.
    if is_nonzero(net) and expense not in extra_accounts:
        lines.append(
            {"konto": expense, "debet": net, "kredit": ZERO, "opis": f"08 > {expense} > {money_text(net)}"}
        )
    lines.extend(os_08_lines)
    if is_nonzero(f76a):
        acc07 = expense07 or expense
        if acc07 not in extra_accounts:
            lines.append({"konto": acc07, "debet": f76a, "kredit": ZERO, "opis": f"{desc} — 9a 76.a člen"})
    if is_nonzero(eu_g) and expense10 not in extra_accounts:
        lines.append({"konto": expense10, "debet": eu_g, "kredit": ZERO, "opis": f"{desc} — 10 pridobitve BL EU"})
    if is_nonzero(eu_s) and expense11 not in extra_accounts:
        lines.append({"konto": expense11, "debet": eu_s, "kredit": ZERO, "opis": f"{desc} — 11 prejete ST EU"})
    if is_nonzero(exempt):
        acc07 = expense07 or expense
        if acc07 not in extra_accounts:
            lines.append({"konto": acc07, "debet": exempt, "kredit": ZERO, "opis": f"{desc} — oproščeno"})
    if is_nonzero(nondeduct) and expense not in extra_accounts:
        lines.append(
            {"konto": expense, "debet": nondeduct, "kredit": ZERO, "opis": f"{desc} — neodbitni DDV"}
        )
    if is_nonzero(reported_vat) and not vat_deductible and expense not in extra_accounts:
        lines.append(
            {
                "konto": expense,
                "debet": reported_vat,
                "kredit": ZERO,
                "opis": f"{desc} — DDV v strošku (brez odbitka)",
            }
        )
    if is_nonzero(excluded) and excluded_acc not in extra_accounts:
        lines.append({"konto": excluded_acc, "debet": excluded, "kredit": ZERO, "opis": f"{desc} — ni v DDV"})

    # Odbitni vhodni DDV → 160xx (domači / EU / tujci)
    if vat_deductible:
        if is_nonzero(vat22):
            lines.append(
                {
                    "konto": vat_in_account(kind, "22"),
                    "debet": vat22,
                    "kredit": ZERO,
                    "opis": f"{desc} — DDV 22% ({tip})",
                }
            )
        if is_nonzero(vat95):
            lines.append(
                {
                    "konto": vat_in_account(kind, "95"),
                    "debet": vat95,
                    "kredit": ZERO,
                    "opis": f"{desc} — DDV 9,5% ({tip})",
                }
            )
        if is_nonzero(vat5):
            lines.append(
                {
                    "konto": vat_in_account(kind, "5"),
                    "debet": vat5,
                    "kredit": ZERO,
                    "opis": f"{desc} — DDV 5% ({tip})",
                }
            )

    # Samoobdavčitev → obračunani DDV v dobro 260xx
    if self_assessment and is_nonzero(reported_vat):
        if is_nonzero(vat22):
            lines.append(
                {
                    "konto": vat_out_account(kind, "22"),
                    "debet": ZERO,
                    "kredit": vat22,
                    "opis": f"{desc} — samoobdavčitev 22% ({tip})",
                }
            )
        if is_nonzero(vat95):
            lines.append(
                {
                    "konto": vat_out_account(kind, "95"),
                    "debet": ZERO,
                    "kredit": vat95,
                    "opis": f"{desc} — samoobdavčitev 9,5% ({tip})",
                }
            )
        if is_nonzero(vat5):
            lines.append(
                {
                    "konto": vat_out_account(kind, "5"),
                    "debet": ZERO,
                    "kredit": vat5,
                    "opis": f"{desc} — samoobdavčitev 5% ({tip})",
                }
            )

    lines.extend(extras)
    _append_balancing_payment(
        lines,
        placilo=placilo,
        desc=desc,
        self_assessment=self_assessment,
        amount=placilo_amount,
    )
    return lines


def _ir_raw_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    import json

    raw = row.get("raw_json")
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _is_integra_paragon(row: Mapping[str, Any]) -> bool:
    """Integra 100* / knjiga Paragoni (ne Fakture DR…)."""
    data = _ir_raw_dict(row)
    if data.get("integra_paragon"):
        return True
    book = normalize_text(row.get("book")).casefold()
    if book == "paragoni":
        return True
    ctrl = normalize_text(data.get("anal_ctrl"))
    doc = normalize_text(row.get("document_no"))
    notes = normalize_text(row.get("notes"))
    if ctrl.startswith("100") or doc.startswith("100") or notes.startswith("kisanal:100"):
        return True
    return False


def _ir_payment_account(row: Mapping[str, Any]) -> str:
    """Integra Paragoni: 1000/1650 iz raw_json; sicer 1200 (Projest / Fakture)."""
    data = _ir_raw_dict(row)
    pay = normalize_text(data.get("payment_account") or row.get("payment_account"))
    if pay:
        return pay
    if _is_integra_paragon(row):
        return "1000"
    return "1200"


def integra_ir_journal_type(row: Mapping[str, Any]) -> str:
    """Minimax vrsta temeljnice: Paragoni 100* → DI, Fakture DR… → IR."""
    if _is_integra_paragon(row):
        return "DI"
    return "IR"


def preview_ir_journals(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    row = apply_ir_eu_sale(row)
    lines: list[dict[str, Any]] = []
    desc = normalize_text(row.get("document_no") or row.get("notes")) or "IR"
    revenue = normalize_text(row.get("account")) or DEFAULT_IR_REVENUE_ACCOUNT
    net = decimal_value(row.get("net"))
    vat22 = decimal_value(row.get("vat_22"))
    vat95 = decimal_value(row.get("vat_95"))
    vat5 = decimal_value(row.get("vat_5"))
    exempt = decimal_value(row.get("exempt"))
    excluded = decimal_value(row.get("excluded"))
    reverse = decimal_value(row.get("reverse_charge"))
    eu_g = decimal_value(row.get("eu_goods"))
    eu_s = decimal_value(row.get("eu_services"))
    gross = decimal_value(row.get("total"))
    kind = ir_vat_kind(row)
    tip = kind_label(kind)
    if not is_nonzero(gross):
        gross = net + vat22 + vat95 + vat5 + exempt + excluded + reverse + eu_g + eu_s

    payment = _ir_payment_account(row)
    if is_nonzero(gross):
        if payment in {"1000", "1650"}:
            label = "gotovina" if payment == "1000" else "kartice"
            lines.append(
                {
                    "konto": payment,
                    "debet": gross,
                    "kredit": ZERO,
                    "opis": f"{desc} — {label}",
                }
            )
        else:
            lines.append(
                {"konto": "1200", "debet": gross, "kredit": ZERO, "opis": f"{desc} — terjatev"}
            )
    credit_net = net + exempt + reverse + eu_g + eu_s + excluded
    if is_nonzero(credit_net):
        lines.append({"konto": revenue, "debet": ZERO, "kredit": credit_net, "opis": f"{desc} — prihodek"})
    if is_nonzero(vat22):
        lines.append(
            {
                "konto": vat_out_account(kind, "22"),
                "debet": ZERO,
                "kredit": vat22,
                "opis": f"{desc} — DDV 22% ({tip})",
            }
        )
    if is_nonzero(vat95):
        lines.append(
            {
                "konto": vat_out_account(kind, "95"),
                "debet": ZERO,
                "kredit": vat95,
                "opis": f"{desc} — DDV 9,5% ({tip})",
            }
        )
    if is_nonzero(vat5):
        lines.append(
            {
                "konto": vat_out_account(kind, "5"),
                "debet": ZERO,
                "kredit": vat5,
                "opis": f"{desc} — DDV 5% ({tip})",
            }
        )
    return lines
