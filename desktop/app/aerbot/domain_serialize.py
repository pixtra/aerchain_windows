"""Serialize tool results into the exact strings the model depends on.

Deterministic engines produce these numbers; the model is forbidden from
recomputing them. Money fields are rendered as exact ₹ values (4 decimals) so
there is no rounding or reformatting the model could drift on. Pass-through
identifiers (offer_id, line_number, supplier codes) stay faithful.
"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal, InvalidOperation

# value keys that are money denominated in base currency (INR) and must be
# rendered as exact ₹ strings. Names come from the decision-ready engines.
_MONEY = {
    "effective_economic_cost", "normalized_unit_price", "net_material_price",
    "discount_benefit", "discount_benefit_per_unit", "allocated_freight",
    "financing_benefit", "quoted_unit_price", "manual_normalized_price",
    "additional_benefit_per_unit", "economic_cost_per_buyer_unit",
}
# keys that carry an original currency string attached to the number
_CURRENCY_KEY = {"currency", "quoted_currency", "base_currency"}


def _fmt_money(v) -> str:
    try:
        return "₹ {:,}".format(Decimal(str(v)).quantize(Decimal("0.0001")))
    except (InvalidOperation, ValueError):
        return f"₹ {v}"


def _row(d: dict) -> dict:
    out = {}
    for key, val in d.items():
        if val is None:
            continue
        if key in _MONEY and isinstance(val, (int, float, str, Decimal)):
            out[key] = _fmt_money(val)
        elif isinstance(val, Decimal):
            out[key] = str(val)
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
            out[key] = int(fv) if fv == int(fv) else round(fv, 6)
        elif isinstance(val, dict):
            out[key] = _row(val)
        elif isinstance(val, (list, tuple)):
            out[key] = [_row(v) if isinstance(v, dict) else v for v in val]
        else:
            out[key] = val
    return out


def serialize_tool_result(result) -> str:
    if isinstance(result, (list, tuple)):
        data = [_row(r.__dict__) if dataclasses.is_dataclass(r) else
                (_row(r) if isinstance(r, dict) else r) for r in result]
    elif dataclasses.is_dataclass(result):
        data = _row(result.__dict__)
    elif isinstance(result, dict):
        data = _row(result)
    else:
        data = result
    return json.dumps(data, ensure_ascii=False, default=str)