"""Decision-ready procurement data construction.

Assembly: RFx Line + Supplier Offer + Supplier Product + Supplier Master +
Questionnaire Results + Procurement Policy + FX + Discount Tiers + Evidence
→ deterministic normalization, economics, eligibility → DecisionReadyRecord.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.domain.enums import (
    BASE_CURRENCY, Confidence, DEFAULT_DECISION_DATE, EligibilityState,
    VerificationStatus,
)
from app.domain.models import DecisionReadyRecord
from app.engines import discount as discount_engine
from app.engines import economics as economics_engine
from app.engines import eligibility as eligibility_engine
from app.engines import freight as freight_engine
from app.engines.financing import financing_benefit as _financing_benefit
from app.engines.fx import apply_fx
from app.engines.uom import normalize_uom

DECISION_DATE = date.fromisoformat(DEFAULT_DECISION_DATE)


def build_fx_table(fx_rows) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for f in fx_rows:
        table.setdefault(f.from_currency, {})[f.to_currency] = f.fx_rate
    return table


def quality_state(pol_quality_required: bool,
                  value: str) -> Optional[bool]:
    """Return True (pass), False (fail), or None (needs review)."""
    v = (value or "").strip().upper()
    if v in ("PASS", "YES", "YES,", "CONFIRMED", "PASS_REQUIRED", "OK", "0"):
        return True
    if v in ("NO", "FAIL", "FALSE", "NO_RESPONSE"):
        return False
    return None if pol_quality_required else True


def build_decision_ready(offers, products_by_id, suppliers_by_id, skus_by_id,
                         lines_by_id, tiers_by_offer, evidence_by_offer,
                         q_by_supplier, policy, fx_rows, decision_date=None) -> list[DecisionReadyRecord]:
    decision_date = decision_date or DECISION_DATE
    fx_table = build_fx_table(fx_rows)
    records: list[DecisionReadyRecord] = []
    idx = 1

    for o in offers:
        sp = products_by_id[o.supplier_product_id]
        sup = suppliers_by_id[o.supplier_id]
        sku = skus_by_id[o.sku_id]
        line = lines_by_id[o.rfx_line_id]
        ev = evidence_by_offer.get(o.offer_id)
        rec = DecisionReadyRecord(
            decision_record_id=f"DRR-{idx:04d}",
            rfx_id=o.rfx_id, rfx_line_id=o.rfx_line_id,
            line_number=o.line_number, sku_id=o.sku_id,
            supplier_id=o.supplier_id, supplier_name=sup.supplier_name,
            offer_id=o.offer_id,
            supplier_product_id=o.supplier_product_id,
            supplier_product_code=o.supplier_product_code,
            quoted_description=o.quoted_description,
            buyer_uom=line.buyer_uom,
            required_quantity=line.required_quantity,
            required_lead_time_days=line.required_lead_time_days,
            quality_requirement=line.quality_requirement,
            quoted_unit_price=o.quoted_unit_price,
            quoted_currency=o.quoted_currency,
            quoted_uom=o.quoted_uom,
            quoted_quantity=o.quoted_quantity,
            discount_rule_type=o.discount_rule_type,
            freight_basis=o.freight_basis,
            payment_days=o.payment_days,
            moq=o.moq,
            lead_time_days=o.lead_time_days,
            quote_valid_until=o.quote_valid_until,
            evidence_id=ev.evidence_id if ev else "",
            source_file=ev.source_file if ev else "",
            source_type=ev.source_type if ev else "",
            source_location=ev.source_location if ev else "",
            source_text=ev.source_text if ev else "",
            extraction_confidence=ev.extraction_confidence if ev else Confidence.HIGH.value,
            normalization_confidence=ev.normalization_confidence if ev else Confidence.HIGH.value,
            verification_status=ev.verification_status if ev else VerificationStatus.EXTRACTED.value,
            requires_review=(ev.requires_review if ev else False) or o.quoted_uom == "UNKNOWN",
        )

        # --- FX -----------------------------------------------------------
        try:
            fx = apply_fx(o.quoted_unit_price, o.quoted_currency,
                          policy.base_currency, fx_table)
            rec.fx_rate_id = fx.fx_rate_id
            rec.fx_rate_applied = fx.fx_rate_applied
            price_in_base = fx.normalized
        except ValueError:
            rec.error_state = "FX_UNRESOLVED"
            rec.error_detail = f"no rate for {o.quoted_currency}"
            rec.overall_eligible = False
            records.append(rec)
            idx += 1
            continue

        # --- UOM ----------------------------------------------------------
        unresolved = o.quoted_uom == "UNKNOWN"
        try:
            uom = normalize_uom(
                price_in_base,
                conversion_factor=sp.conversion_factor if not unresolved else None,
                source="SUPPLIER_PRODUCT_MASTER",
                quoted_qty=o.quoted_quantity,
            )
            rec.uom_conversion_factor = uom.conversion_factor
            rec.uom_conversion_source = uom.conversion_source
            rec.normalized_unit_price = uom.normalized_unit_price
            rec.normalization_confidence = Confidence.LOW.value if unresolved else Confidence.HIGH.value
        except ValueError:
            rec.error_state = "UOM_UNRESOLVED"
            rec.error_detail = "cannot establish buyer-UOM conversion"
            rec.quoted_uom_detail = o.quoted_uom
            rec.overall_eligible = False
            rec.requires_review = True
            records.append(rec)
            idx += 1
            continue

        # --- Discount -----------------------------------------------------
        dr = discount_engine.calculate_discount(
            normalized_unit_price=rec.normalized_unit_price,
            required_qty=line.required_quantity,
            discount_type=o.discount_rule_type,
            discount_percentage=o.discount_percentage,
            discount_amount=o.discount_amount,
            discount_currency=None,
            normalized_to_inr=1.0,
            tiers=tiers_by_offer.get(o.offer_id, []),
        )
        rec.applicable_discount_percentage = dr.applied_percentage
        rec.discount_benefit = dr.benefit

        # --- Freight ------------------------------------------------------
        fr = freight_engine.allocate_freight(
            o.freight_basis, o.freight_amount, line.required_quantity)
        rec.allocated_freight = fr.allocated_per_unit
        if fr.status != "OK":
            rec.error_state = "FREIGHT_REVIEW_REQUIRED"

        # --- Financing ----------------------------------------------------
        net = round(rec.normalized_unit_price - rec.discount_benefit, 6)
        rec.net_material_price = net
        rec.financing_benefit = _financing_benefit(
            net, o.payment_days, policy.annual_financing_rate,
            policy.baseline_payment_days)

        # --- Effective cost ----------------------------------------------
        rec.effective_economic_cost = economics_engine.effective_cost(
            rec.normalized_unit_price, rec.discount_benefit,
            rec.allocated_freight, rec.financing_benefit)

        # --- Eligibility --------------------------------------------------
        moq_ok = (o.moq or 0) <= line.required_quantity
        lead_ok = (o.lead_time_days or 0) <= line.required_lead_time_days
        qval = q_by_supplier.get(o.supplier_id)
        qok = quality_state(policy.quality_required_for_award, qval) \
            if policy.quality_required_for_award else None
        valid_until = date.fromisoformat(o.quote_valid_until) \
            if o.quote_valid_until else None
        validity_ok = valid_until is not None and valid_until >= decision_date

        elig = eligibility_engine.evaluate(
            mapping_status=o.mapping_status,
            mapping_confidence=o.mapping_confidence,
            moq_ok=moq_ok, lead_time_ok=lead_ok, quality_ok=qok,
            validity_ok=validity_ok,
            hard_moq=policy.hard_moq_constraint,
            hard_lead_time=policy.hard_lead_time_constraint,
            quality_required=policy.quality_required_for_award,
            expired_ineligible=policy.expired_quote_ineligible,
            moq_val=o.moq, moq_req=line.required_quantity,
            lead_val=o.lead_time_days, lead_req=line.required_lead_time_days,
            quality_source=qval, validity_detail=f"expired {o.quote_valid_until}",
            unresolved_uom=unresolved,
        )
        rec.moq_eligible = elig.moq == EligibilityState.PASS
        rec.lead_time_eligible = elig.lead_time == EligibilityState.PASS
        rec.quality_eligible = elig.quality == EligibilityState.PASS
        rec.quote_validity_eligible = elig.validity == EligibilityState.PASS
        rec.mapping_eligible = elig.mapping == EligibilityState.PASS
        rec.overall_eligible = elig.overall_eligible
        rec.eligibility_reason = elig.reason_str()
        rec.verification_status = VerificationStatus.CALCULATED.value
        records.append(rec)
        idx += 1

    return records