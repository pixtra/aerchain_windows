"""Financing benefit engine.

benefit = net_material_price × annual_rate × (payment_days − baseline) ÷ 365
Financing is computed on net material price only.
"""
from __future__ import annotations


def financing_benefit(net_material_price: float, payment_days: int,
                      annual_rate: float, baseline_days: int) -> float:
    return round(net_material_price * annual_rate * (payment_days - baseline_days) / 365.0, 6)


def net_30(price: float, rate=0.12, baseline=30) -> float:
    return financing_benefit(price, 30, rate, baseline)


def net_60(price: float, rate=0.12, baseline=30) -> float:
    return financing_benefit(price, 60, rate, baseline)


def net_15(price: float, rate=0.12, baseline=30) -> float:
    return financing_benefit(price, 15, rate, baseline)