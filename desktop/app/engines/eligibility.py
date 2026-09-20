"""Eligibility engine — economics and constraints are separate.

overall_eligible = mapping AND moq AND lead_time AND quality AND validity
An ineligible offer is preserved and explained, never deleted or zeroed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import EligibilityState


@dataclass
class EligibilityResult:
    mapping: EligibilityState = EligibilityState.NA
    moq: EligibilityState = EligibilityState.NA
    lead_time: EligibilityState = EligibilityState.NA
    quality: EligibilityState = EligibilityState.NA
    validity: EligibilityState = EligibilityState.NA
    overall_eligible: bool = False
    reasons: list = field(default_factory=list)

    def reason_str(self) -> str:
        return "; ".join(self.reasons)

    def pass_flags(self) -> dict:
        return {
            "moq_eligible": self.moq == EligibilityState.PASS,
            "lead_time_eligible": self.lead_time == EligibilityState.PASS,
            "quality_eligible": self.quality == EligibilityState.PASS,
            "quote_validity_eligible": self.validity == EligibilityState.PASS,
            "mapping_eligible": self.mapping == EligibilityState.PASS,
        }


def evaluate(mapping_status: str, mapping_confidence: float,
             moq_ok: bool, lead_time_ok: bool, quality_ok: bool,
             validity_ok: bool, hard_moq: bool, hard_lead_time: bool,
             quality_required: bool, expired_ineligible: bool,
             moq_val=None, moq_req=None, lead_val=None, lead_req=None,
             quality_source=None, validity_detail=None,
             unresolved_uom: bool = False) -> EligibilityResult:
    res = EligibilityResult()
    rs = res.reasons

    if unresolved_uom or mapping_status == "UNRESOLVED":
        res.mapping = EligibilityState.FAIL
        rs.append(f"Mapping unresolved (status={mapping_status})" +
                  (", UOM unresolved" if unresolved_uom else ""))
    elif mapping_status in ("CONFIRMED", "AI_SUGGESTED", "BUYER_VERIFIED"):
        res.mapping = EligibilityState.PASS
    else:
        res.mapping = EligibilityState.REVIEW
        rs.append(f"Mapping status needs review: {mapping_status}")

    if hard_moq:
        res.moq = EligibilityState.PASS if moq_ok else EligibilityState.FAIL
        if not moq_ok:
            rs.append(f"MOQ fail: required {moq_req} < supplier MOQ {moq_val}")
    else:
        res.moq = EligibilityState.NA

    if hard_lead_time:
        res.lead_time = EligibilityState.PASS if lead_time_ok else EligibilityState.FAIL
        if not lead_time_ok:
            rs.append(f"Lead-time fail: supplier {lead_val}d > required {lead_req}d")
    else:
        res.lead_time = EligibilityState.NA

    if quality_required:
        if quality_ok is None:
            res.quality = EligibilityState.REVIEW
            rs.append(f"Quality response needs review: {quality_source}")
        elif quality_ok:
            res.quality = EligibilityState.PASS
        else:
            res.quality = EligibilityState.FAIL
            rs.append(f"Quality fail: {quality_source}")
    else:
        res.quality = EligibilityState.NA

    if expired_ineligible:
        res.validity = EligibilityState.PASS if validity_ok else EligibilityState.FAIL
        if not validity_ok:
            rs.append(f"Quote validity fail: {validity_detail}")
    else:
        res.validity = EligibilityState.NA

    states = [res.mapping, res.moq, res.lead_time, res.quality, res.validity]
    res.overall_eligible = all(s in (EligibilityState.PASS, EligibilityState.NA)
                               for s in states)
    return res