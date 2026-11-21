"""PR samoobdavčitev / DDV se odbija — enaka semantika kot KIR/KPR."""

from __future__ import annotations

from typing import Any, Mapping

from trops_studio.money import is_nonzero, normalize_text


def as_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value).strip().casefold()
    if text in {"1", "true", "da", "d", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "ne", "n", "no", "off"}:
        return False
    return default


def source_self_assessment_pr(row: Mapping[str, Any]) -> bool:
    """True, če KPR P9–P11 (76.a / EU blago / EU storitve) <> 0."""
    return (
        is_nonzero(row.get("f76a"))
        or is_nonzero(row.get("eu_goods"))
        or is_nonzero(row.get("eu_services"))
    )


def resolve_pr_vat_flags(
    row: Mapping[str, Any],
    *,
    rule: Mapping[str, Any] | None = None,
) -> tuple[bool, bool, str]:
    """
    Vrne (samoobdavčitev, DDV se odbija, vir_ponudbe).
    Prednost: vrednost na listini → pravilo dobavitelja → P9–P11 / privzeto DA.
    """
    offer: list[str] = []
    sa = as_bool(row.get("self_assessment"), None)
    vd = as_bool(row.get("vat_deductible"), None)
    # tudi kir-style ključi (XML / DDV-O)
    if sa is None:
        sa = as_bool(row.get("__samoobdavcitev__"), None)
    if vd is None:
        vd = as_bool(row.get("__ddv_se_odbija__"), None)

    if rule:
        if sa is None:
            sa = as_bool(rule.get("self_assessment"), None)
            if sa is not None:
                offer.append("dobavitelj")
        if vd is None:
            vd = as_bool(rule.get("vat_deductible"), None)
            if vd is not None and "dobavitelj" not in offer:
                offer.append("dobavitelj")

    source_sa = source_self_assessment_pr(row)
    if sa is None:
        sa = source_sa
        if source_sa:
            offer.append("KPR P9–P11")
    if vd is None:
        vd = True
        if source_sa and not offer:
            offer.append("KPR P9–P11")

    return bool(sa), bool(vd), " · ".join(offer)


def flags_offer_text(self_assessment: bool, vat_deductible: bool, offer_from: str = "") -> str:
    text = (
        f"Ponujeno v tem PR: Samoobdavčitev={'DA' if self_assessment else 'NE'}, "
        f"DDV se odbija={'DA' if vat_deductible else 'NE'}"
    )
    if normalize_text(offer_from):
        text += f" (vir: {offer_from})."
    else:
        text += "."
    return text
