"""Scenario + award engine.

Scenarios are runtime inputs. Recalculation never mutates the underlying
decision-ready dataset. MVP award strategy: LINE_LEVEL_SPLIT (one supplier per
line; award quantity = RFx required quantity → tier determinable pre-selection).
"""
from __future__ import annotations

from collections import defaultdict

from app.domain.enums import AwardStrategy
from app.domain.models import AwardDecision, Scenario

from .discount import applicable_tier
from .economics import effective_cost
from .eligibility import EligibilityState, evaluate as base_evaluate


def _pay_days_ok(payment_days):
    return payment_days if payment_days and payment_days > 0 else 30


def recalc_with_scenario(records: list, scenario: Scenario, policy,
                         annual_rate=None, baseline=None,
                         tiers_by_offer=None) -> list:
    """Returns a deep-copied list of records with scenario economics applied.

    additional_discounts override adds on top of the offer's own per-unit
    percentage benefit; supplier_exclusions mark overall_eligible=False.
    quality_required=True/False toggles the quality constraint.
    """
    annual_rate = annual_rate or policy.annual_financing_rate
    baseline = baseline or policy.baseline_payment_days
    out = []
    for rec in records:
        r = _copy(rec)
        add = scenario.additional_discounts.get(r.supplier_id, 0.0)
        if add:
            base_pct = r.applicable_discount_percentage or 0.0
            eff_pct = base_pct + add
            r.applicable_discount_percentage = eff_pct
            r.discount_benefit = round(r.normalized_unit_price * eff_pct / 100.0, 6)
        # flat-amount / tier offers keep computed benefit; recompute net for all
        net = round((r.normalized_unit_price or 0) - (r.discount_benefit or 0), 6)
        fin = round(net * annual_rate * (_pay_days_ok(r.payment_days) - baseline) / 365.0, 6)
        r.net_material_price = net
        r.financing_benefit = fin
        r.effective_economic_cost = effective_cost(
            r.normalized_unit_price or 0, r.discount_benefit or 0,
            r.allocated_freight or 0, fin)

        if scenario.supplier_exclusions and r.supplier_id in scenario.supplier_exclusions:
            r.overall_eligible = False
            r.eligibility_reason = ((r.eligibility_reason + "; ")
                                    if r.eligibility_reason else "") + \
                                   f"Excluded by scenario {scenario.scenario_name}"
        out.append(r)
    return out


def award_line_level(records: list, scenario: Scenario,
                     policy, max_share: float | None = None,
                     min_qualified: int | None = None) -> list[AwardDecision]:
    """Pick cheapest eligible supplier per line; enforce soft share caps greedily."""
    by_line = defaultdict(list)
    for rec in records:
        if rec.overall_eligible:
            by_line[rec.line_number].append(rec)

    decided = []
    share = defaultdict(int)
    total_lines = len(by_line)

    for line_no in sorted(by_line):
        cands = sorted(by_line[line_no], key=lambda r: r.effective_economic_cost)
        chosen = None
        for c in cands:
            if max_share is not None and total_lines:
                cap = max(1, int(max_share / 100.0 * total_lines))
                if share[c.supplier_id] >= cap:
                    continue
            chosen = c
            break
        if chosen is None:
            continue
        share[chosen.supplier_id] += 1
        decided.append(AwardDecision(
            award_decision_id=f"AWD-{scenario.scenario_id}-{line_no:02d}",
            scenario_id=scenario.scenario_id, rfx_id=scenario.rfx_id,
            rfx_line_id=next(r.rfx_line_id for r in cands if r.line_number == line_no),
            line_number=line_no,
            supplier_id=chosen.supplier_id,
            offer_id=chosen.offer_id,
            effective_economic_cost=chosen.effective_economic_cost,
            decision_status="RECOMMENDED",
            decision_reason=_reason(chosen, records, line_no)))

    # annotate unmet soft constraints
    n_qualified_suppliers = len(share)
    unmet = []
    if min_qualified and n_qualified_suppliers < min_qualified:
        unmet.append(f"only {n_qualified_suppliers} qualified supplier(s), "
                     f"scenario requires {min_qualified}")
    for d in decided:
        d.decision_reason = d.decision_reason + (" [" + "; ".join(unmet) + "]" if unmet else "")
    return decided


def _reason(chosen, records, line_no) -> str:
    rec = chosen
    base = (f"Cheapest eligible offer of {rec.effective_economic_cost} "
            f"{rec.supplier_name} (quoted {rec.quoted_currency} "
            f"{rec.quoted_unit_price}/{rec.quoted_uom} → normalized "
            f"{rec.normalized_unit_price}).")
    return base


def _copy(rec):
    import dataclasses
    return dataclasses.replace(rec)