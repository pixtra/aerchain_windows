"""FX conversion engine — deterministic, always applies an active rate."""
from __future__ import annotations

from app.domain.enums import Currency


class FxResult:
    def __init__(self, normalized: float, fx_rate_id: str, fx_rate_applied: float):
        self.normalized = round(normalized, 6)
        self.fx_rate_id = fx_rate_id
        self.fx_rate_applied = fx_rate_applied


def apply_fx(amount: float, from_currency: str, to_currency: str,
             rates: dict[str, dict[str, float]]) -> FxResult:
    """Convert amount in `from_currency` to `to_currency`.

    rates: {from_currency: {to_currency: rate}}. IN->IN identity is implicit.
    """
    if from_currency == to_currency:
        return FxResult(amount, "FX-IDENTITY", 1.0)

    if from_currency not in rates or to_currency not in rates[from_currency]:
        raise ValueError(f"no active FX rate for {from_currency} -> {to_currency}")

    rate = rates[from_currency][to_currency]
    rid = f"FX-{from_currency}-{to_currency}"
    return FxResult(amount * rate, rid, rate)