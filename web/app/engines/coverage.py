"""Coverage engine — a missing offer is not a zero price."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import CoverageStatus


@dataclass
class LineCoverage:
    line_number: int
    rfx_line_id: str
    sku_id: str
    mapped_supplier_count: int
    offer_count: int
    qualified_offer_count: int
    coverage_status: str
    buyer_action: str


def coverage_for_line(mapped: int, offered: int, qualified: int) -> LineCoverage:
    if mapped == 0 and offered == 0:
        status = CoverageStatus.NO_COVERAGE.value
        action = "No mapped supplier — re-scope or source the line"
    elif offered == 0:
        status = CoverageStatus.NO_QUOTE.value
        action = "Invited suppliers did not quote — follow up"
    elif qualified < 1:
        status = CoverageStatus.PARTIAL.value
        action = "Offers exist but none qualified — review eligibility"
    elif offered == 1 or qualified == 1:
        status = CoverageStatus.PARTIAL.value
        action = "Only a single qualified supplier — confirm competition"
    else:
        status = CoverageStatus.COMPETITIVE.value
        action = "Competitive — proceed to award analysis"
    return LineCoverage(line_number=0, rfx_line_id="", sku_id="",
                        mapped_supplier_count=mapped, offer_count=offered,
                        qualified_offer_count=qualified,
                        coverage_status=status, buyer_action=action)