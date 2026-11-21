"""DDV-O kontrola iz Projest SQLite vrstic (preko KirKpr ddvo_summary).

Prevalitev / samoobdavčitev — Minimax 160xx/260xx + knjigi IR/PR:

  EU blago (KPR P10)     → KIR P17 → DDV-O 23  + odbitni KPR P18 → 41
  EU storitve (KPR P11)  → KIR P18 → DDV-O 23a + odbitni → 41
  tujci / tretje (ne-EU) → KIR P23 → DDV-O 25  + nabava KPR P8 → 31 + odbitni → 41
  nabava OS (0470, KPR 08+13) → DDV-O 31 in 35
  MRN uvoz (carina)      → KIR P26 → DDV-O 26  + odbitni → 41

Polje 41 = odbitek od nabav blaga/storitev, pridobitev EU in uvoza
(vključno s tujci SA) — ni samo »EU«.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio.ir_list_view import apply_ir_eu_sale, ir_customer_country
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path
from trops_studio.money import decimal_value, iso_date, normalize_vat_id

ZERO = Decimal("0.00")


def ir_row_to_kir(row: Mapping[str, Any]) -> dict[str, Any]:
    classified = apply_ir_eu_sale(row)
    vat = normalize_vat_id(classified.get("vat_id"))
    country = ir_customer_country(classified) or (
        vat[:2] if len(vat) >= 2 and vat[:2].isalpha() else "SI"
    )
    return {
        "ZAPST": classified.get("seq") or "",
        "P2": iso_date(classified.get("booking_date")) or "",
        "P3": classified.get("document_no") or "",
        "P4": iso_date(classified.get("document_date")) or "",
        "P5": classified.get("party_name") or "",
        "P6": country,
        "P6DS": vat,
        "P7": decimal_value(classified.get("net")),
        "P8": decimal_value(classified.get("reverse_charge")),
        "P9": decimal_value(classified.get("exempt")),
        "P10": decimal_value(classified.get("eu_goods")),
        "P11": decimal_value(classified.get("eu_services")),
        "P12": Decimal("0.00"),
        "P13": Decimal("0.00"),
        "P14": decimal_value(classified.get("vat_22")),
        "P15": decimal_value(classified.get("vat_95")),
        "P16": Decimal("0.00"),
        "P17": Decimal("0.00"),
        "P18": Decimal("0.00"),
        "P19": Decimal("0.00"),
        "P20": Decimal("0.00"),
        "P21": Decimal("0.00"),
        "P22": Decimal("0.00"),
        "P23": Decimal("0.00"),
        "P24": Decimal("0.00"),
        "P25": Decimal("0.00"),
        "P26": Decimal("0.00"),
        "P27": decimal_value(classified.get("excluded")),
        "OBDOBJE": _obdobje(classified.get("document_date") or classified.get("booking_date")),
    }


def pr_row_to_kpr(row: Mapping[str, Any]) -> dict[str, Any]:
    from trops_studio.pr_vat_flags import resolve_pr_vat_flags

    vat = normalize_vat_id(row.get("vat_id"))
    country = vat[:2] if len(vat) >= 2 and vat[:2].isalpha() else "SI"
    self_assessment, vat_deductible, _offer = resolve_pr_vat_flags(row)
    from trops_studio.os_accounts import add_os_amount_to_kpr
    from trops_studio.pr_list_view import pr_supplier_country
    from trops_studio.vat_accounts import third_country_kpr_bases

    bases = third_country_kpr_bases(row)
    geo = pr_supplier_country(row)
    if geo:
        country = geo

    kpr = {
        "ZAPST": row.get("seq") or "",
        "P2": iso_date(row.get("booking_date")) or "",
        "P3": row.get("document_no") or "",
        "P4": iso_date(row.get("received_date")) or "",
        "P5": iso_date(row.get("document_date")) or "",
        "P6": row.get("supplier_name") or "",
        "P7": country,
        "P7DS": vat,
        "OPOMBE": str(row.get("internal_no") or row.get("notes") or "").strip(),
        "P8": bases["P8"],
        "P9": bases["P9"],
        "P10": bases["P10"],
        "P11": bases["P11"],
        "P12": decimal_value(row.get("exempt_non")),
        "P13": decimal_value(row.get("exempt_os")),
        "P14": decimal_value(row.get("exempt_on")),
        "P15": Decimal("0.00"),
        "P16": Decimal("0.00"),
        "P17": decimal_value(row.get("nondeduct_22")) + decimal_value(row.get("nondeduct_95")),
        "P18": decimal_value(row.get("vat_22")),
        "P19": decimal_value(row.get("vat_95")),
        "P20": decimal_value(row.get("vat_5")),
        "P21": Decimal("0.00"),
        "__ddv_se_odbija__": vat_deductible,
        "__samoobdavcitev__": self_assessment,
        "OBDOBJE": _obdobje(row.get("received_date") or row.get("document_date")),
    }
    add_os_amount_to_kpr(kpr, row)
    return kpr


def pr_row_to_synthetic_kir(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Sintetična KIR vrstica samoobdavčitve iz PR (kot Access 2600-x / eDavki 23–25).

    Pravilo:
    - SA + DDV se odbija → obračunani (IR) = odbitni (PR), prevalitev se pobota
    - SA + DDV se ne odbija → DDV samo v obračunanem (IR) — za plačilo; ni odbitka

    Access: DDV_spOut = 2600-8 (EU blago) pred 2600-4 (EU storitve); 76.a / tretja → 25.
    """
    from trops_studio.pr_vat_flags import resolve_pr_vat_flags

    self_assessment, vat_deductible, _ = resolve_pr_vat_flags(row)
    if not self_assessment:
        return None
    f76a = decimal_value(row.get("f76a"))
    eu_goods = decimal_value(row.get("eu_goods"))
    eu_services = decimal_value(row.get("eu_services"))
    net_taxable = decimal_value(row.get("net_taxable"))
    vat_22 = decimal_value(row.get("vat_22"))
    vat_95 = decimal_value(row.get("vat_95"))
    vat_5 = decimal_value(row.get("vat_5"))
    if not (vat_22 or vat_95 or vat_5):
        return None
    # Osnova: P9–P11 ali 08 (tretja država s samoobdavčitvijo na net_taxable)
    if not (f76a or eu_goods or eu_services or net_taxable):
        return None

    vat = normalize_vat_id(row.get("vat_id"))
    country = vat[:2] if len(vat) >= 2 and vat[:2].isalpha() else "SI"
    day = (
        iso_date(row.get("document_date"))
        or iso_date(row.get("received_date"))
        or iso_date(row.get("booking_date"))
        or ""
    )
    kir = {
        "ZAPST": f"S{row.get('seq') or ''}",
        "P2": iso_date(row.get("booking_date")) or day,
        "P3": row.get("document_no") or "",
        "P4": day,
        "P5": row.get("supplier_name") or "",
        "P6": country,
        "P6DS": vat,
        "P7": ZERO,
        "P8": ZERO,
        "P9": ZERO,
        "P10": ZERO,
        "P11": ZERO,
        "P12": ZERO,
        "P13": ZERO,
        "P14": ZERO,
        "P15": ZERO,
        "P16": ZERO,
        "P17": ZERO,
        "P18": ZERO,
        "P19": ZERO,
        "P20": ZERO,
        "P21": ZERO,
        "P22": ZERO,
        "P23": ZERO,
        "P24": ZERO,
        "P25": ZERO,
        "P26": ZERO,
        "P27": ZERO,
        "OBDOBJE": _obdobje(row.get("received_date") or row.get("document_date")),
        "__source__": "projest-prevalitev",
        "__samoobdavcitev__": True,
        "__ddv_se_odbija__": bool(vat_deductible),
    }

    from trops_studio.vat_accounts import is_mrn_row

    # MRN = samoobdavčitev od uvoza → DDV-O polje 26 (KIR P26).
    # Navadni uvoz (UVOZ) nima SA → sem ne pride.
    if is_mrn_row(row):
        kir["P26"] = vat_22 + vat_95 + vat_5
        kir["__source__"] = "projest-mrn-26"
        return kir

    from trops_studio.vat_accounts import is_third_country_supplier

    # Tretje države (US/CN …): blago in storitve → AOP 25 (KIR P23), ne 23/23a.
    if is_third_country_supplier(row) or (f76a and not eu_goods and not eu_services):
        kir["P23"] = vat_22  # DDV-O 25
        kir["P24"] = vat_95  # DDV-O 25a
        kir["P25"] = vat_5   # DDV-O 25b
        return kir

    # EU: blago → 23; storitve → 23a.
    if eu_goods:
        kir["P17"] = vat_22  # DDV-O 23
        kir["P19"] = vat_95  # DDV-O 24
        kir["P21"] = vat_5   # DDV-O 24b
    elif eu_services:
        kir["P18"] = vat_22  # DDV-O 23a
        kir["P20"] = vat_95  # DDV-O 24a
        kir["P22"] = vat_5   # DDV-O 24c
    else:
        # 76.a / SA na osnovi 08
        kir["P23"] = vat_22  # DDV-O 25
        kir["P24"] = vat_95  # DDV-O 25a
        kir["P25"] = vat_5   # DDV-O 25b
    return kir


def _obdobje(value: Any) -> str:
    text = iso_date(value) or ""
    if len(text) >= 7:
        return f"{text[5:7]}{text[2:4]}"
    return ""


def _reverse_vat_sum(kir_row: Mapping[str, Any]) -> Decimal:
    return sum((decimal_value(kir_row.get(f"P{i}")) for i in range(17, 27)), ZERO)


def build_dataset(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
    *,
    period_from: date | None = None,
    period_to: date | None = None,
) -> Any:
    ensure_kirkpr_on_path()
    from kirkpr_minimax_core import KirkprDataset  # type: ignore
    from trops_studio.kirkpr_import import raw_furs_kirkpr_row

    header = {
        "OBDOBJE_OD": period_from.isoformat() if period_from else "",
        "OBDOBJE_DO": period_to.isoformat() if period_to else "",
    }
    # FURS uvoz: ohrani izvirna P-polja (SA P17–P26); sicer SQLite → KIR/KPR.
    kir = []
    for row in ir_rows:
        raw = raw_furs_kirkpr_row(row, book="KIR")
        kir.append(raw if raw else ir_row_to_kir(row))
    kpr = []
    for row in pr_rows:
        raw = raw_furs_kirkpr_row(row, book="KPR")
        kpr.append(raw if raw else pr_row_to_kpr(row))

    # Če IR že ima P17–P26 za isto listino, sintetične ne podvajamo.
    existing_reverse = {
        str(row.get("P3") or "").strip()
        for row in kir
        if str(row.get("P3") or "").strip() and _reverse_vat_sum(row)
    }
    for row in pr_rows:
        invoice = str(row.get("document_no") or "").strip()
        if invoice and invoice in existing_reverse:
            continue
        synthetic = pr_row_to_synthetic_kir(row)
        if synthetic is not None:
            kir.append(synthetic)

    return KirkprDataset(
        header=header,
        kir=kir,
        kpr=kpr,
        source_path=Path("projest.sqlite3"),
        source_format="projest-sqlite",
        source_members=["ir_rows", "pr_rows", "prevalitev-kir"],
    )


def iter_pr_vat_split_invoices(
    pr_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """PR listine v odbitnem DDV, razdeljene na domači SLO vs. prevalitev."""
    ensure_kirkpr_on_path()
    from kirkpr_minimax_core import pr_metrics  # type: ignore

    domestic: list[dict[str, Any]] = []
    prevalitev: list[dict[str, Any]] = []
    for row in pr_rows:
        metrics = pr_metrics(pr_row_to_kpr(row))
        if not metrics["vat_deductible"]:
            continue
        amount = metrics["reported_vat"]
        if not amount:
            continue
        item = {
            "id": row.get("id"),
            "seq": row.get("seq") or "",
            "date": row.get("received_date") or row.get("document_date") or row.get("booking_date") or "",
            "document_no": row.get("document_no") or "",
            "supplier_name": row.get("supplier_name") or "",
            "vat_id": normalize_vat_id(row.get("vat_id") or row.get("tax_number")),
            "net_taxable": decimal_value(row.get("net_taxable")),
            "eu_goods": decimal_value(row.get("eu_goods")),
            "eu_services": decimal_value(row.get("eu_services")),
            "f76a": decimal_value(row.get("f76a")),
            "vat_22": metrics["vat_22"],
            "vat_95": metrics["vat_95"],
            "vat_5": metrics["vat_5"],
            "vat_total": amount,
            "self_assessment": bool(metrics["self_assessment"]),
            "vat_deductible": bool(metrics["vat_deductible"]),
        }
        if metrics["self_assessment"]:
            prevalitev.append(item)
        else:
            domestic.append(item)
    return {"domestic": domestic, "prevalitev": prevalitev}


def _pr_vat_split(pr_rows: Sequence[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Domači SLO DDV vs. prevalitev (kot Access: prevalitev | SLO DDV pri 18/41, 19/42).

    Prevalitev = SA (160xx+260xx): EU + tujci(ne-EU) + uvoz/MRN → odbitni 41.
    SLO DDV = domači odbitni DDV brez prevalitve.
    """
    split_rows = iter_pr_vat_split_invoices(pr_rows)
    domestic_22 = sum((item["vat_22"] for item in split_rows["domestic"]), ZERO)
    domestic_95 = sum((item["vat_95"] for item in split_rows["domestic"]), ZERO)
    domestic_5 = sum((item["vat_5"] for item in split_rows["domestic"]), ZERO)
    prevalitev_22 = sum((item["vat_22"] for item in split_rows["prevalitev"]), ZERO)
    prevalitev_95 = sum((item["vat_95"] for item in split_rows["prevalitev"]), ZERO)
    prevalitev_5 = sum((item["vat_5"] for item in split_rows["prevalitev"]), ZERO)
    domestic = domestic_22 + domestic_95 + domestic_5
    prevalitev = prevalitev_22 + prevalitev_95 + prevalitev_5
    return {
        "domestic_input_vat": domestic,
        "prevalitev_input_vat": prevalitev,
        "domestic_vat_22": domestic_22,
        "domestic_vat_95": domestic_95,
        "domestic_vat_5": domestic_5,
        "prevalitev_vat_22": prevalitev_22,
        "prevalitev_vat_95": prevalitev_95,
        "prevalitev_vat_5": prevalitev_5,
        "prevalitev_count": Decimal(len(split_rows["prevalitev"])),
        # Access vrstice: skupaj = prevalitev + SLO
        "access_18_41_total": prevalitev_22 + domestic_22,
        "access_19_42_total": prevalitev_95 + domestic_95,
        "access_20_42a_total": prevalitev_5 + domestic_5,
    }


def _field_exact_sum(fields: Sequence[Mapping[str, Any]], codes: set[str]) -> Decimal:
    return sum(
        (decimal_value(field.get("exact")) for field in fields if str(field.get("code")) in codes),
        ZERO,
    )


def _pr_raw(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row.get("raw_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _raw_money(raw: Mapping[str, Any], *names: str) -> Decimal:
    wanted = {name.casefold() for name in names}
    for key, value in raw.items():
        if str(key).strip().casefold() in wanted:
            return decimal_value(value)
    return ZERO


def _raw_text(raw: Mapping[str, Any], *names: str) -> str:
    wanted = {name.casefold() for name in names}
    for key, value in raw.items():
        if str(key).strip().casefold() in wanted:
            text = str(value or "").strip()
            if text:
                return text
    return ""


def pr_access_info(pr_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """INFO polja kot v Access knjigi PR.

    - 21 (22) uvoz … Vasco F21/F22 + PR z opredelitvijo Uvoz (odbitni, brez SA)
    - 26 MRN … samoobdavčitev uvoza (eDavki deklaracije) → DDV-O polje 26
    - Ne gre v knjigo / neodbitni / OPR OS …
    """
    from trops_studio.vat_accounts import (
        extract_mrn_codes,
        is_mrn_row,
        is_uvoz_row,
        row_supplier_kind,
    )

    excluded = ZERO
    neodbitni = ZERO
    opr_os = ZERO
    uvoz_f21 = ZERO
    uvoz_f22 = ZERO
    uvoz_pr_vat = ZERO
    mrn_vat = ZERO
    pavsal = ZERO
    mrns: list[str] = []
    seen: set[str] = set()

    for row in pr_rows:
        excluded += decimal_value(row.get("excluded"))
        neodbitni += decimal_value(row.get("nondeduct_22")) + decimal_value(row.get("nondeduct_95"))
        raw = _pr_raw(row)
        opr_os += _raw_money(raw, "F18")
        uvoz_f21 += _raw_money(raw, "F21")
        uvoz_f22 += _raw_money(raw, "F22")
        pavsal += _raw_money(raw, "Pavšal 8%", "Pavsal 8%")

        row_vat = (
            decimal_value(row.get("vat_22"))
            + decimal_value(row.get("vat_95"))
            + decimal_value(row.get("vat_5"))
        )
        if is_mrn_row(row) or row_supplier_kind(row) == "MRN":
            mrn_vat += row_vat
        elif is_uvoz_row(row):
            uvoz_pr_vat += row_vat

        for code in extract_mrn_codes(
            _raw_text(raw, "MRN", "26 uvoz - MRN", "Uvoz MRN", "MRN št"),
            row.get("notes"),
            row.get("internal_no"),
            raw.get("Opombe"),
            row.get("document_no"),
        ):
            if code not in seen:
                seen.add(code)
                mrns.append(code)

    uvoz_total = uvoz_f21 + uvoz_f22 + uvoz_pr_vat
    return {
        "info_uvoz_21_22": uvoz_total,
        "info_uvoz_f21": uvoz_f21,
        "info_uvoz_f22": uvoz_f22,
        "info_excluded": excluded,
        "info_mrn_codes": mrns,
        "info_mrn_text": ", ".join(mrns) if mrns else "—",
        "info_mrn_amount": mrn_vat,
        "info_neodbitni": neodbitni,
        "info_opr_os": opr_os,
        "info_pavsal": pavsal,
    }


def compute_ddvo(
    ir_rows: Sequence[Mapping[str, Any]],
    pr_rows: Sequence[Mapping[str, Any]],
    *,
    period_from: date | None = None,
    period_to: date | None = None,
) -> dict[str, Any]:
    ensure_kirkpr_on_path()
    from kirkpr_minimax_core import ddvo_summary  # type: ignore

    dataset = build_dataset(ir_rows, pr_rows, period_from=period_from, period_to=period_to)
    summary = dict(ddvo_summary(dataset))
    split = _pr_vat_split(pr_rows)
    fields = list(summary.get("fields") or [])

    from trops_studio.pr_vat_flags import resolve_pr_vat_flags
    from trops_studio.vat_accounts import is_mrn_row

    domestic_output = _field_exact_sum(fields, {"21", "22", "22a"})
    reverse_output = _field_exact_sum(
        fields, {"23", "23a", "24", "24a", "24b", "24c", "25", "25a", "25b", "26"}
    )
    # Access: DDV za plačilo ≈ DDV IR − domači odbitni PR (prevalitev se pobota).
    access_payable = max(domestic_output - split["domestic_input_vat"], ZERO)
    access_excess = max(split["domestic_input_vat"] - domestic_output, ZERO)

    # Access «DDV skupaj PR» pogosto prišteje še SA tujih storitev na osnovi 08
    # (OpenAI/Fiverr), čeprav grejo tudi v prevalitev — zato nižje «za plačilo».
    access_extra_pr = ZERO
    for row in pr_rows:
        sa, vd, _ = resolve_pr_vat_flags(row)
        if not sa or not vd or is_mrn_row(row):
            continue
        if (
            decimal_value(row.get("eu_goods"))
            or decimal_value(row.get("eu_services"))
            or decimal_value(row.get("f76a"))
        ):
            continue
        if not decimal_value(row.get("net_taxable")):
            continue
        access_extra_pr += (
            decimal_value(row.get("vat_22"))
            + decimal_value(row.get("vat_95"))
            + decimal_value(row.get("vat_5"))
        )
    access_pr_like = split["domestic_input_vat"] + access_extra_pr
    access_pay_like = max(domestic_output - access_pr_like, ZERO)

    summary.update(split)
    summary.update(pr_access_info(pr_rows))
    summary["info_ddvo_26"] = _field_exact_sum(fields, {"26"})
    summary["domestic_output_vat"] = domestic_output
    summary["prevalitev_output_vat"] = reverse_output
    summary["access_payable"] = access_payable
    summary["access_excess"] = access_excess
    summary["access_extra_pr_vat"] = access_extra_pr
    summary["access_pr_like"] = access_pr_like
    summary["access_pay_like"] = access_pay_like
    summary["synthetic_kir_count"] = sum(
        1
        for row in dataset.kir
        if str(row.get("__source__") or "").startswith("projest-")
    )
    return summary
