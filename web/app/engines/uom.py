"""UOM / pack normalization engine.

precedence:  quote-specific conversion > supplier product master > item/global master > UNRESOLVED

normalized_unit_price = quoted_unit_price × FX ÷ conversion_factor
conversion_factor = buyer units per one quoted/supplier unit.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UomResult:
    normalized_unit_price: float
    conversion_factor: float
    conversion_source: str
    conflict: bool = False
    normalized_qty: float | None = None


def normalize_uom(quoted_unit_price: float, conversion_factor: float | None,
                  source: str, quoted_qty: float | None = None,
                  quote_factor: float | None = None,
                  quote_source: str | None = None,
                  master_factor: float | None = None) -> UomResult:
    """Applies precedence; when a quote-specific factor conflicts with master it is
    used for the transaction and the conflict is flagged."""
    source = source or "MASTER"
    conflict = False
    if quote_factor is not None and master_factor is not None \
            and abs(quote_factor - master_factor) > 1e-9:
        conversion_factor = quote_factor
        source = quote_source or source
        conflict = True
    elif quote_factor is not None:
        conversion_factor = quote_factor
        source = quote_source or source
        conflict = False
    elif conversion_factor is None:
        raise ValueError("UOM unresolved: no conversion factor available")

    if conversion_factor <= 0:
        raise ValueError(f"invalid conversion factor {conversion_factor}")

    price = quoted_unit_price / conversion_factor
    qty = None
    if quoted_qty is not None:
        qty = quoted_qty * conversion_factor

    return UomResult(
        normalized_unit_price=round(price, 6),
        conversion_factor=conversion_factor,
        conversion_source=source,
        conflict=conflict,
        normalized_qty=round(qty, 4) if qty is not None else None,
    )