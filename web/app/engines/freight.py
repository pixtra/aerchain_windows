"""Freight allocation engine."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FreightResult:
    basis: str
    allocated_per_unit: float
    status: str = "OK"
    detail: str = ""


def allocate_freight(freight_basis: str, freight_amount_in_base: float,
                     required_quantity: float) -> FreightResult:
    if freight_basis in ("INCLUDED", None, ""):
        return FreightResult("INCLUDED", 0.0, status="OK")

    if freight_basis == "EXTRA_PER_SHIPMENT":
        if required_quantity <= 0:
            return FreightResult(freight_basis, 0.0, status="REVIEW_REQUIRED",
                                 detail="required quantity missing")
        return FreightResult(freight_basis,
                             round(freight_amount_in_base / required_quantity, 6),
                             status="OK")

    return FreightResult(freight_basis, 0.0, status="REVIEW_REQUIRED",
                         detail=f"ambiguous freight basis: {freight_basis}")