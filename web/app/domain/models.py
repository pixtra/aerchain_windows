"""Domain dataclasses mirroring the 16-entity canonical logical model.

Physical storage is SQLite; these dataclasses are the typed in-memory contract.
Derived values (normalized economics / eligibility) are computed by the
deterministic engines and carried on the decision-ready projection.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Sku:
    sku_id: str
    sku_name: str
    category: str
    buyer_uom: str
    specification: str
    status: str = "ACTIVE"
    typical_supplier_uoms: str = ""


@dataclass
class Supplier:
    supplier_id: str
    supplier_code: str
    supplier_name: str
    supplier_status: str = "ACTIVE"
    default_currency: str = "INR"
    default_payment_terms: str = "Net 30"
    default_payment_days: int = 30
    default_freight_terms: str = "INCLUDED"
    default_lead_time_days: int = 10
    default_quote_validity_days: int = 30
    location: str = ""


@dataclass
class SupplierProduct:
    supplier_product_id: str
    supplier_id: str
    sku_id: str
    supplier_product_code: str
    supplier_product_name: str
    supplier_description: str = ""
    supplier_base_uom: str = "EA"
    pack_size: float = 1.0
    pack_size_uom: str = "EA"
    conversion_factor: float = 1.0  # buyer units per supplied unit
    conversion_source: str = "MANUAL"
    mapping_status: str = "CONFIRMED"
    mapping_type: str = "DIRECT"
    mapping_confidence: float = 1.0


@dataclass
class FxRate:
    fx_rate_id: str
    from_currency: str
    to_currency: str
    fx_rate: float
    status: str = "ACTIVE"


@dataclass
class Policy:
    policy_id: str
    organization_id: str
    policy_name: str
    base_currency: str = "INR"
    annual_financing_rate: float = 0.12
    baseline_payment_days: int = 30
    tax_treatment: str = "EXCLUSIVE"
    hard_moq_constraint: bool = True
    hard_lead_time_constraint: bool = True
    quality_required_for_award: bool = True
    expired_quote_ineligible: bool = True
    default_award_strategy: str = "LINE_LEVEL_SPLIT"
    status: str = "ACTIVE"


@dataclass
class Rfx:
    rfx_id: str
    rfx_name: str
    category: str
    organization_id: str
    base_currency: str = "INR"
    response_deadline: str = ""
    required_delivery_date: str = ""
    award_strategy: str = "LINE_LEVEL_SPLIT"
    quality_required: bool = True
    status: str = "OPEN"


@dataclass
class RfxLine:
    rfx_line_id: str
    rfx_id: str
    line_number: int
    sku_id: str
    buyer_description: str
    specification: str = ""
    required_quantity: float = 1000
    buyer_uom: str = "EA"
    required_delivery_date: str = ""
    required_lead_time_days: int = 15
    quality_requirement: str = "PASS_REQUIRED"
    max_moq: float = 0
    line_status: str = "ACTIVE"
    category: str = ""


@dataclass
class RfxSupplier:
    rfx_supplier_id: str
    rfx_id: str
    supplier_id: str
    invitation_status: str = "INVITED"
    response_status: str = "NO_RESPONSE"
    invited_at: str = ""
    response_received_at: str = ""
    source_document_count: int = 0
    mapped_rfx_line_count: int = 0
    quoted_rfx_line_count: int = 0
    unquoted_mapped_line_count: int = 0


@dataclass
class RfxQuestion:
    question_id: str
    rfx_id: str
    question_sequence: int
    question_text: str
    response_type: str
    mandatory: bool = True


@dataclass
class QuestionnaireResponse:
    question_response_id: str
    rfx_id: str
    supplier_id: str
    question_id: str
    response_value: str
    response_status: str = "VERIFIED"


@dataclass
class SupplierOffer:
    offer_id: str
    rfx_id: str
    rfx_line_id: str
    line_number: int
    supplier_id: str
    supplier_product_id: str
    sku_id: str
    supplier_product_code: str = ""
    quoted_description: str = ""
    specification: str = ""
    required_quantity: float = 0
    buyer_uom: str = "EA"
    quoted_quantity: float = 0
    quoted_uom: str = "EA"
    quoted_unit_price: float = 0
    quoted_currency: str = "INR"
    quote_received_date: str = ""
    quote_valid_until: str = ""
    payment_terms: str = "Net 30"
    payment_days: int = 30
    freight_amount: float = 0
    freight_basis: str = "INCLUDED"
    moq: float = 0
    lead_time_days: int = 10
    quality_requirement: str = "PASS_REQUIRED"
    discount_rule_type: Optional[str] = None
    discount_rule_id: Optional[str] = None
    discount_percentage: Optional[float] = None
    discount_amount: Optional[float] = None
    discount_currency: Optional[str] = None
    mapping_status: str = "CONFIRMED"
    mapping_confidence: float = 1.0
    extraction_confidence: float = 1.0


@dataclass
class DiscountTier:
    discount_tier_id: str
    offer_id: str
    tier_sequence: int
    supplier_min_qty: float
    supplier_max_qty: Optional[float]
    supplier_tier_uom: str
    min_inclusive: bool = True
    max_inclusive: bool = False
    discount_percentage: float = 0
    source_text: str = ""
    normalized_min_qty: Optional[float] = None
    normalized_max_qty: Optional[float] = None
    buyer_uom: str = "EA"
    conversion_factor: float = 1.0
    normalization_status: str = "NORMALIZED"


@dataclass
class OfferEvidence:
    evidence_id: str
    offer_id: str
    source_type: str = "EXCEL"
    source_file: str = ""
    page_number: Optional[int] = None
    source_location: str = ""
    source_text: str = ""
    extracted_value: str = ""
    extraction_confidence: str = "HIGH"
    normalization_confidence: str = "HIGH"
    verification_status: str = "EXTRACTED"
    requires_review: bool = False


@dataclass
class DecisionReadyRecord:
    decision_record_id: str
    rfx_id: str
    rfx_line_id: str
    line_number: int
    sku_id: str
    supplier_id: str
    supplier_name: str
    offer_id: str
    supplier_product_id: str
    supplier_product_code: str
    quoted_description: str
    buyer_uom: str
    required_quantity: float
    required_lead_time_days: int
    quality_requirement: str
    quoted_unit_price: float
    quoted_currency: str
    quoted_uom: str
    quoted_quantity: float
    fx_rate_id: str = ""
    fx_rate_applied: float = 1.0
    uom_conversion_factor: float = 1.0
    uom_conversion_source: str = "MASTER"
    normalized_unit_price: Optional[float] = None
    discount_rule_type: Optional[str] = None
    applicable_discount_percentage: Optional[float] = None
    discount_benefit: Optional[float] = None
    net_material_price: Optional[float] = None
    freight_basis: str = "INCLUDED"
    allocated_freight: Optional[float] = None
    payment_days: int = 30
    financing_benefit: Optional[float] = None
    effective_economic_cost: Optional[float] = None

    moq: float = 0
    lead_time_days: int = 10
    quote_valid_until: str = ""
    moq_eligible: Optional[bool] = None
    lead_time_eligible: Optional[bool] = None
    quality_eligible: Optional[bool] = None
    quote_validity_eligible: Optional[bool] = None
    mapping_eligible: Optional[bool] = None
    overall_eligible: Optional[bool] = None
    eligibility_reason: str = ""

    evidence_id: str = ""
    source_file: str = ""
    source_type: str = ""
    source_location: str = ""
    source_text: str = ""
    extraction_confidence: str = "HIGH"
    normalization_confidence: str = "HIGH"
    verification_status: str = "EXTRACTED"
    requires_review: bool = False

    error_state: Optional[str] = None
    error_detail: str = ""


@dataclass
class CoverageRecord:
    coverage_record_id: str
    rfx_id: str
    rfx_line_id: str
    line_number: int
    sku_id: str
    supplier_id: str
    supplier_name: str
    supplier_product_mapping_exists: bool
    offer_received: bool


@dataclass
class Scenario:
    scenario_id: str
    rfx_id: str
    scenario_name: str = ""
    additional_discounts: dict = field(default_factory=dict)  # supplier_id -> pct
    supplier_exclusions: list = field(default_factory=list)
    max_supplier_share: Optional[float] = None
    min_qualified_suppliers: Optional[int] = None
    quality_required: Optional[bool] = None
    award_strategy: str = "LINE_LEVEL_SPLIT"
    notes: str = ""


@dataclass
class AwardDecision:
    award_decision_id: str
    scenario_id: str
    rfx_id: str
    rfx_line_id: str
    line_number: int
    supplier_id: str
    offer_id: str
    effective_economic_cost: float
    decision_status: str = "RECOMMENDED"
    decision_reason: str = ""


def model_to_dict(m) -> dict:
    return asdict(m)