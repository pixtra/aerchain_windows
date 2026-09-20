"""Effective economic cost engine — core deterministic formula.

effective_economic_cost =
    normalized_unit_price
    − discount_benefit
    + allocated_freight
    − financing_benefit
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EconomicCostResult:
    normalized_unit_price: float
    discount_benefit: float
    net_material_price: float
    allocated_freight: float
    financing_benefit: float
    effective_economic_cost: float
    inputs: dict


def effective_cost(normalized_unit_price: float, discount_benefit: float,
                   allocated_freight: float, financing_benefit: float) -> float:
    return round(normalized_unit_price - discount_benefit
                 + allocated_freight - financing_benefit, 6)


def compute_full(normalized_unit_price: float, discount_benefit: float,
                 allocated_freight: float, payment_days: int,
                 annual_rate: float, baseline_days: int,
                 required_quantity: float) -> EconomicCostResult:
    net_material = round(normalized_unit_price - discount_benefit, 6)
    fin_benefit = round(net_material * annual_rate * (payment_days - baseline_days) / 365.0, 6)
    eec = effective_cost(normalized_unit_price, discount_benefit,
                         allocated_freight, fin_benefit)
    return EconomicCostResult(
        normalized_unit_price=normalized_unit_price,
        discount_benefit=discount_benefit,
        net_material_price=net_material,
        allocated_freight=allocated_freight,
        financing_benefit=fin_benefit,
        effective_economic_cost=eec,
        inputs=dict(required_quantity=required_quantity, payment_days=payment_days,
                    annual_rate=annual_rate, baseline_days=baseline_days),
    )