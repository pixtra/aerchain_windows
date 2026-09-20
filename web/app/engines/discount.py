"""Discount normalization + benefit engine.

Types: FLAT_PERCENT · QUANTITY_TIER_PERCENT · FLAT_AMOUNT
Tier boundaries are converted to buyer UOM BEFORE lookup; the RFx required
quantity is compared in buyer units only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.domain.enums import DiscountRuleType


@dataclass
class DiscountResult:
    rule_type: Optional[str]
    applied_percentage: Optional[float]
    benefit: float
    benefit_per_unit: float
    tier_selected: Optional[dict] = None
    status: str = "OK"
    detail: str = ""


def get_discount_percentage(discount: Optional[float], discount_type: Optional[str]) -> Optional[float]:
    if discount_type == DiscountRuleType.FLAT_PERCENT.value or \
            (discount_type == DiscountRuleType.QUANTITY_TIER_PERCENT.value and discount is not None):
        return discount
    return None


def applicable_tier(required_qty: float, tiers, buyer_uom: str) -> Optional[dict]:
    """Pick the tier whose normalized boundaries contain required_qty."""
    if not tiers:
        return None
    selected = None
    for t in tiers:
        if t.normalization_status == "UNRESOLVED":
            continue
        mn = t.normalized_min_qty if t.normalized_min_qty is not None else float("-inf")
        mx = t.normalized_max_qty if t.normalized_max_qty is not None else float("inf")
        min_ok = required_qty >= mn if t.min_inclusive else required_qty > mn
        max_ok = required_qty <= mx if t.max_inclusive else required_qty < mx
        if min_ok and max_ok:
            selected = {
                "tier_id": t.discount_tier_id,
                "min": t.normalized_min_qty,
                "max": t.normalized_max_qty,
                "pct": t.discount_percentage,
                "source": t.source_text,
            }
    return selected


def normalize_tier_boundary(supplier_qty: float, conversion_factor: float) -> float:
    return supplier_qty * conversion_factor


def calculate_discount(normalized_unit_price: float, required_qty: float,
                       discount_type: Optional[str], discount_percentage: Optional[float],
                       discount_amount: Optional[float], discount_currency: float | None,
                       normalized_to_inr: float = 1.0,
                       tiers=None) -> DiscountResult:
    """benefit expressed per buyer unit in base currency."""
    if discount_type is None:
        return DiscountResult(None, None, 0.0, 0.0, status="NONE")

    if discount_type == DiscountRuleType.FLAT_PERCENT.value:
        pct = discount_percentage or 0
        benefit = normalized_unit_price * pct / 100.0
        return DiscountResult(discount_type, pct, round(benefit, 6),
                              round(benefit, 6),
                              status="OK")

    if discount_type == DiscountRuleType.QUANTITY_TIER_PERCENT.value:
        selected = applicable_tier(required_qty, tiers or [], "EA")
        if selected is None:
            return DiscountResult(discount_type, None, 0.0, 0.0,
                                  status="NO_MATCHING_TIER",
                                  detail=("no normalized tier contains "
                                          f"required qty {required_qty}"))
        pct = selected["pct"]
        benefit = normalized_unit_price * pct / 100.0
        return DiscountResult(discount_type, pct, round(benefit, 6),
                              round(benefit, 6), tier_selected=selected)

    if discount_type == DiscountRuleType.FLAT_AMOUNT.value:
        amt_inr = (discount_amount or 0) * normalized_to_inr
        return DiscountResult(discount_type, None, round(amt_inr, 6),
                              round(amt_inr, 6), status="OK")

    return DiscountResult(discount_type, None, 0.0, 0.0, status="UNSUPPORTED")