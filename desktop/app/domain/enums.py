"""Domain enums and constants — the vocabulary of the Aerchain decision model."""
from enum import Enum


class Currency(str, Enum):
    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class MappingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    AI_SUGGESTED = "AI_SUGGESTED"
    BUYER_VERIFIED = "BUYER_VERIFIED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"


class DiscountRuleType(str, Enum):
    FLAT_PERCENT = "FLAT_PERCENT"
    QUANTITY_TIER_PERCENT = "QUANTITY_TIER_PERCENT"
    FLAT_AMOUNT = "FLAT_AMOUNT"


class FreightBasis(str, Enum):
    INCLUDED = "INCLUDED"
    EXTRA_PER_SHIPMENT = "EXTRA_PER_SHIPMENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VerificationStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    NORMALIZED = "NORMALIZED"
    CALCULATED = "CALCULATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BUYER_VERIFIED = "BUYER_VERIFIED"


class CoverageStatus(str, Enum):
    COMPETITIVE = "COMPETITIVE"
    PARTIAL = "PARTIAL"
    NO_COVERAGE = "NO_COVERAGE"
    NO_QUOTE = "NO_QUOTE"


class EligibilityState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"
    NA = "NA"


class AwardStrategy(str, Enum):
    LINE_LEVEL_SPLIT = "LINE_LEVEL_SPLIT"


class ResponseStatus(str, Enum):
    INVITED = "INVITED"
    RESPONDED = "RESPONDED"
    NO_RESPONSE = "NO_RESPONSE"


BASE_CURRENCY = Currency.INR
DEFAULT_DECISION_DATE = "2026-09-18"