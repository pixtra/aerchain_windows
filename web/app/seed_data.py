"""Deterministic golden seed-data generator.

Builds the canonical 16-entity dataset exactly on the spec's contract:
  50 SKUs · 8 suppliers · 249 supplier products · RFx-001 with 30 lines ·
  5 questionnaire items · 40 questionnaire responses · 131 supplier offers ·
  discount tiers · 131 offer evidence rows · policy · FX · coverage.

L29 and L30 are mapped to supplier products (8 suppliers each) yet receive
zero quotes — the NO_QUOTE coverage case, never a zero price.
SUP-008 is invited but returns no offers (NO_RESPONSE coverage case).
No value is random-drawn per call: a fixed seed keeps the golden contract stable.
"""
from __future__ import annotations

import csv
import os
import random
from datetime import date, timedelta

from app.domain.enums import DEFAULT_DECISION_DATE
from app.domain.models import (
    DiscountTier, FxRate, OfferEvidence, Policy, QuestionnaireResponse, Rfx,
    RfxLine, RfxQuestion, RfxSupplier, Sku, Supplier, SupplierOffer,
    SupplierProduct,
)

SEED = 73
rng = random.Random(SEED)

DECISION_DATE = date.fromisoformat(DEFAULT_DECISION_DATE)
RFX = "RFX-001"
ORG = "ORG-001"


# ---------------------------------------------------------------- SKU master (50)
_CATEGORIES = [
    "Corrugated Boxes", "Foam & Padding", "Strapping & Tapes",
    "Films & Wraps", "Labels & Print", "Shipping Supplies",
]
_PREFIX = ["CB", "FP", "ST", "FW", "LP", "SS"]

# canonical buyer uom per category index
_CAT_UOM = {0: "EA", 1: "EA", 2: "EA", 3: "ROLL", 4: "EA", 5: "BAG"}
_CAT_PRICE = {0: 34, 1: 26, 2: 18, 3: 410, 4: 6, 5: 12}


def _make_skus() -> list[Sku]:
    skus = []
    spec_templates = ["EK-31", "S-PLY-3", "S-PLY-5", "FB-38", "UV-RES", "HS-WRAP"]
    for i in range(1, 51):
        ci = (i - 1) % len(_CATEGORIES)
        skus.append(
            Sku(
                sku_id=f"Item-{i:03d}",
                sku_name=f"{_PREFIX[ci]} Item {i:03d}",
                category=_CATEGORIES[ci],
                buyer_uom=_CAT_UOM[ci],
                specification=(f"{spec_templates[(i * 7) % len(spec_templates)]}-"
                               f"{_PREFIX[ci]}-{i:03d}"),
                typical_supplier_uoms="BOX,CARTON,EA,ROLL" if _CAT_UOM[ci] != "ROLL" else "REEL,ROLL",
            )
        )
    return skus


# ---------------------------------------------------------------- Suppliers (8)
_SUPPLIERS = [
    ("SUP-001", "SUP-A", "PackRight Industries", "INR", "Net 30", 30, "INCLUDED", 10, 45, "Pune, IN"),
    ("SUP-002", "SUP-B", "CorruCore Packaging Ltd", "INR", "Net 60", 60, "EXTRA_PER_SHIPMENT", 12, 60, "Chennai, IN"),
    ("SUP-003", "SUP-C", "GlobalBox Trading Co", "USD", "Net 30", 30, "INCLUDED", 14, 30, "Singapore"),
    ("SUP-004", "SUP-D", "SwiftBox Crafts", "INR", "Net 15", 15, "EXTRA_PER_SHIPMENT", 18, 45, "Delhi, IN"),
    ("SUP-005", "SUP-E", "EcoPack Solutions", "INR", "Net 30", 45, "INCLUDED", 9, 30, "Ahmedabad, IN"),
    ("SUP-006", "SUP-F", "PrimeBox Industries", "INR", "Net 30", 30, "INCLUDED", 11, 45, "Hyderabad, IN"),
    ("SUP-007", "SUP-G", "NovaPaper Mills", "INR", "Net 30", 30, "INCLUDED", 15, 30, "Kolkata, IN"),
    ("SUP-008", "SUP-H", "Unicarton Exports", "USD", "Net 45", 45, "EXTRA_PER_SHIPMENT", 20, 60, "Vietnam"),
]

# re-seed name pools: supplier names are always "word + word"; the golden
# seed (73) keeps the canonical table verbatim so checked-in expectations hold
_NAME_A = ["Nova", "Prime", "Swift", "Eco", "Global", "Pack", "Corru", "Uni",
           "Bright", "Apex", "Blue", "Rapid"]
_NAME_B = ["Packaging", "Industries", "Trading", "Crafts", "Solutions",
           "Mills", "Exports", "Works", "Systems", "Goods", "Supply", "Lines"]

_RFX_NAMES = [
    "Industrial Foam & Cushioning FY26",
    "Shipping Labels & Tapes FY26",
    "MRO Corrugated Supplies FY26",
    "Corrugated Packaging & Shipping Materials FY26",
    "Freight Lanes & Cartons FY26",
]
assert _RFX_NAMES[SEED % len(_RFX_NAMES)] == \
    "Corrugated Packaging & Shipping Materials FY26"


def _make_suppliers(seed: int = SEED) -> list[Supplier]:
    rows = _SUPPLIERS
    if seed != SEED:
        # same IDs, currencies, terms, locations (structural) — fresh names
        used, rows = set(), []
        for s in _SUPPLIERS:
            name = f"{rng.choice(_NAME_A)} {rng.choice(_NAME_B)}"
            while name in used:
                name = f"{rng.choice(_NAME_A)} {rng.choice(_NAME_B)}"
            used.add(name)
            rows.append((s[0], s[1], name) + s[3:])
    out = []
    for s in rows:
        out.append(Supplier(
            supplier_id=s[0], supplier_code=s[1], supplier_name=s[2],
            default_currency=s[3], default_payment_terms=s[4],
            default_payment_days=s[5], default_freight_terms=s[6],
            default_lead_time_days=s[7], default_quote_validity_days=s[8],
            location=s[9],
        ))
    return out


# ---------------------------------------------------------------- Supplier product (249)
def _pack_size(cat_idx: int, i: int) -> tuple[str, float, float]:
    """Return (supplier_base_uom, pack_size_buyer_units, conversion_factor)."""
    cat_uom = _CAT_UOM[cat_idx]
    if cat_uom == "ROLL":
        return "REEL", 12.0, 12.0
    if cat_uom == "BAG":
        return "BAG", 1.0, 1.0
    # EA items quoted in BOX/CARTON with a pack of 25 / 50 / 100 / 200 / 500
    packs = [25, 50, 100, 200, 500]
    n = packs[(i * 3) % len(packs)]
    base_uom = "CARTON" if i % 3 == 0 else ("BOX" if i % 2 else "BOX")
    return base_uom, float(n), float(n)


def _make_supplier_products(skus: list[Sku], line_sku_ids: set[str],
                            suppliers: list[Supplier] | None = None) -> list[SupplierProduct]:
    """249 rows; every supplier maps every RFx-line SKU, plus extras for the remainder.

    Item-049/050 (L29/L30) are mapped across all suppliers but receive no quotes.
    """
    products = []
    idx = 1
    master = suppliers or _make_suppliers()
    by_id = {s.supplier_id: s for s in master}
    eligible = [s for s in skus if s.sku_id not in ("Item-049", "Item-050")]
    line_order = [s for s in eligible if s.sku_id in line_sku_ids]
    rest_order = [s for s in eligible if s.sku_id not in line_sku_ids]
    target = 249
    made = 0
    for si, sup in enumerate(_SUPPLIERS):
        name = by_id.get(sup[0]).supplier_name if by_id.get(sup[0]) else sup[2]
        used = set()
        # guarantee a mapping for every line SKU
        bucket = list(line_order)
        # extras to reach the 249 total (240 base + 9 extras)
        extras = [rest_order[(si * 5 + i) % len(rest_order)] for i in range(2)]
        bucket = bucket + extras
        for sku in bucket:
            if made >= target:
                break
            if sku.sku_id in used:
                continue
            used.add(sku.sku_id)
            ci = _CATEGORIES.index(sku.category)
            base_uom, pack, conv = _pack_size(ci, idx)
            products.append(SupplierProduct(
                supplier_product_id=f"SP-{idx:03d}",
                supplier_id=sup[0],
                sku_id=sku.sku_id,
                supplier_product_code=f"{sup[1][-1]}-{sku.sku_id.split('-')[1]}",
                supplier_product_name=sku.sku_name,
                supplier_description=f"{sku.specification} – {name} grade",
                supplier_base_uom=base_uom,
                pack_size=pack,
                pack_size_uom="buyer units" if base_uom != sku.buyer_uom else sku.buyer_uom,
                conversion_factor=conv,
                conversion_source="MASTER",
                mapping_status="CONFIRMED" if idx % 11 else ("AI_SUGGESTED" if idx % 5 else "UNRESOLVED"),
                mapping_confidence=round(rng.uniform(0.62, 1.0), 2),
            ))
            idx += 1
            made += 1
            if made >= target:
                break
    return products


# ---------------------------------------------------------------- FX + policy
def _make_fx_and_policy():
    fx = [
        FxRate("FX-INR-1", "INR", "INR", 1.0),
        FxRate("FX-USD-1", "USD", "INR", 86.50),
        FxRate("FX-EUR-1", "EUR", "INR", 93.20),
        FxRate("FX-GBP-1", "GBP", "INR", 108.60),
    ]
    pol = Policy(
        policy_id="POL-001", organization_id=ORG,
        policy_name="Global Procurement Policy",
        base_currency="INR", annual_financing_rate=0.12,
        baseline_payment_days=30, tax_treatment="EXCLUSIVE",
        hard_moq_constraint=True, hard_lead_time_constraint=True,
        quality_required_for_award=True, expired_quote_ineligible=True,
        default_award_strategy="LINE_LEVEL_SPLIT",
    )
    return fx, pol


# ---------------------------------------------------------------- RFx + 30 lines
def _make_rfx_and_lines(skus: list[Sku], seed: int = SEED) -> tuple[Rfx, list[RfxLine]]:
    rfx = Rfx(
        rfx_id=RFX,
        rfx_name=_RFX_NAMES[seed % len(_RFX_NAMES)],
        category=skus[0].category,
        organization_id=ORG,
        base_currency="INR",
        response_deadline="2026-09-05",
        required_delivery_date="2026-10-15",
        award_strategy="LINE_LEVEL_SPLIT",
        quality_required=True,
        status="OPEN",
    )
    lines = []
    used_sku = set()
    # Lines L01..L28 map to SKU-001..SKU-048 (skip 049/050), L29/L30 also unmapped
    pool = [s for s in skus if s.sku_id not in ("Item-049", "Item-050")]
    for ln in range(1, 31):
        sku = pool[(ln * 5) % len(pool)]
        if sku.sku_id in used_sku:
            sku = pool[(ln * 7 + 2) % len(pool)]
        used_sku.add(sku.sku_id)
        qty = [20000, 12000, 15000, 8000, 30000, 6000, 1000, 7500, 4500, 9000,
               18000, 5000, 27000, 7000, 11000, 14000, 3500, 22000, 9500, 16000,
               13000, 4000, 200000, 8500, 6500, 61000, 10000, 3, 25000, 2][ln - 1]
        lead = [10, 12, 14, 10, 8, 15, 12, 10, 10, 12, 9, 14, 11, 12, 10,
                13, 10, 11, 10, 12, 10, 10, 12, 14, 10, 15, 12, 13, 12, 12][ln - 1]
        lines.append(RfxLine(
            rfx_line_id=f"LF-{ln:02d}",
            rfx_id=RFX,
            line_number=ln,
            sku_id=sku.sku_id,
            buyer_description=sku.sku_name,
            specification=sku.specification,
            required_quantity=float(qty),
            buyer_uom=sku.buyer_uom,
            required_delivery_date=rfx.required_delivery_date,
            required_lead_time_days=lead,
            quality_requirement="PASS_REQUIRED",
            line_status="ACTIVE",
            category=sku.category,
        ))
    return rfx, lines


# ---------------------------------------------------------------- Questionnaire
_QUESTIONS = [
    ("Q1", 1, "Can you confirm firm delivery by the required delivery date?",
     "DATE / COMMITMENT", True),
    ("Q2", 2, "Do you meet the required specification/quality standard?",
     "YES / NO / CONDITIONAL", True),
    ("Q3", 3, "What lead time and monthly capacity can you guarantee?",
     "TEXT", True),
    ("Q4", 4, "What payment terms do you offer?", "TEXT", True),
    ("Q5", 5, "Are freight charges included or extra?", "TEXT", True),
]


def _make_questionnaire() -> list[RfxQuestion]:
    return [RfxQuestion(question_id=q[0], rfx_id=RFX, question_sequence=q[1],
                        question_text=q[2], response_type=q[3], mandatory=q[4])
            for q in _QUESTIONS]


# ---------------------------------------------------------------- Rfx suppliers
def _make_rfx_suppliers() -> list[RfxSupplier]:
    rows = []
    for s in _SUPPLIERS:
        sid = s[0]
        responded = sid != "SUP-008"
        rows.append(RfxSupplier(
            rfx_supplier_id=f"RS-{sid.split('-')[1]}",
            rfx_id=RFX, supplier_id=sid,
            invitation_status="INVITED",
            response_status="RESPONDED" if responded else "NO_RESPONSE",
            invited_at="2026-08-20",
            response_received_at="2026-09-04" if responded else "",
            source_document_count=1 if responded else 0,
        ))
    return rows


# ---------------------------------------------------------------- Offers profile
# per-supplier behavior: currency, payment, freight, discount, lead, quality, validity
_OFFER_PROFILE = {
    "SUP-001": dict(currency="INR", pay_days=30, freight="INCLUDED", freight_amt=0,
                    discount=("FLAT_PERCENT", 5.0), lead_delta=0,
                    quality="PASS", valid_days=90, count=28, mood="neutral"),
    "SUP-002": dict(currency="INR", pay_days=60, freight="EXTRA_PER_SHIPMENT", freight_amt=15000.0,
                    discount=("QUANTITY_TIER_PERCENT", None), lead_delta=1,
                    quality="PASS", valid_days=60, count=26, mood="neutral"),
    "SUP-003": dict(currency="USD", pay_days=30, freight="INCLUDED", freight_amt=0,
                    discount=(None, None), lead_delta=2,
                    quality="PASS", valid_days=30, count=22, mood="discount_cheap"),
    "SUP-004": dict(currency="INR", pay_days=15, freight="EXTRA_PER_SHIPMENT", freight_amt=8000.0,
                    discount=(None, None), lead_delta=5,
                    quality="PASS", valid_days=45, count=18, mood="photo"),
    "SUP-005": dict(currency="INR", pay_days=45, freight="INCLUDED", freight_amt=0,
                    discount=("QUANTITY_TIER_PERCENT", None), lead_delta=4,
                    quality="PASS", valid_days=45, count=16, mood="email"),
    "SUP-006": dict(currency="INR", pay_days=30, freight="INCLUDED", freight_amt=0,
                    discount=("FLAT_PERCENT", 3.0), lead_delta=0,
                    quality="CONDITIONAL", valid_days=30, count=13, mood="neutral"),
    "SUP-007": dict(currency="INR", pay_days=30, freight="INCLUDED", freight_amt=0,
                    discount=(None, None), lead_delta=0,
                    quality="PASS", valid_days=21, count=8, mood="expiring"),
    "SUP-008": dict(currency="USD", pay_days=45, freight="EXTRA_PER_SHIPMENT", freight_amt=0,
                    discount=(None, None), lead_delta=0,
                    quality="NO_RESPONSE", valid_days=30, count=0, mood="absent"),
}

_BASE_LEAD = {
    "SUP-001": 10, "SUP-002": 11, "SUP-003": 10, "SUP-004": 10,
    "SUP-005": 9, "SUP-006": 11, "SUP-007": 15, "SUP-008": 20,
}

_PRICE_MULT = {
    "SUP-001": 1.00, "SUP-002": 0.985, "SUP-003": 0.92,
    "SUP-004": 1.09, "SUP-005": 0.95, "SUP-006": 1.03, "SUP-007": 1.12,
}


def _base_price(line: RfxLine, skus: dict[str, Sku]) -> float:
    sku = skus[line.sku_id]
    ci = _CATEGORIES.index(sku.category)
    wobble = ((line.line_number * 29) % 13) - 6  # −6..+6%
    return round(_CAT_PRICE[ci] * (1 + wobble / 100.0), 2)


def _line_mapped_suppliers(lines: list[RfxLine], products: list[SupplierProduct],
                           skus: dict[str, Sku]) -> dict[str, list[str]]:
    """line -> list of supplier_ids having a product mapping for the line's sku."""
    mapping: dict[str, list[str]] = {l.rfx_line_id: [] for l in lines}
    sp_by_sku: dict[str, list[SupplierProduct]] = {}
    for sp in products:
        sp_by_sku.setdefault(sp.sku_id, []).append(sp)
    for line in lines:
        for sp in sp_by_sku.get(line.sku_id, []):
            if sp.supplier_id not in mapping[line.rfx_line_id]:
                mapping[line.rfx_line_id].append(sp.supplier_id)
    return mapping


def _make_offers(lines, products, skus, suppliers, seed: int = SEED) -> tuple[list[SupplierOffer], list[DiscountTier], list[OfferEvidence]]:
    line_by_id = {l.rfx_line_id: l for l in lines}
    sku_by_id = {s.sku_id: s for s in skus}
    sp_by_sup: dict[str, list[SupplierProduct]] = {}
    for sp in products:
        sp_by_sup.setdefault(sp.supplier_id, []).append(sp)

    offers: list[SupplierOffer] = []
    tiers: list[DiscountTier] = []
    evidence: list[OfferEvidence] = []
    oid = 1
    tide = 1
    evid = 1

    file_for = {
        "SUP-001": ("Supplier_A_Quote.xlsx", "EXCEL"),
        "SUP-002": ("Supplier_B_Quote.pdf", "PDF"),
        "SUP-003": ("Supplier_C_Quote.xlsx", "EXCEL"),
        "SUP-004": ("Supplier_D_Rate_Card.jpg", "IMAGE"),
        "SUP-005": ("Supplier_E_Email.txt", "EMAIL"),
        "SUP-006": ("Supplier_F_Quote.pdf", "PDF"),
        "SUP-007": ("Supplier_G_Quote.xlsx", "EXCEL"),
    }

    # lines eligible for offers: all except L29/L30 (no mappings)
    offerable = [l for l in lines if l.line_number <= 28]

    for sup_id, prof in _OFFER_PROFILE.items():
        if prof["count"] == 0:
            continue
        my_products = sp_by_sup.get(sup_id, [])
        # pick which lines this supplier can quote: those whose sku it has a product for
        cand_lines = [l for l in offerable
                      if any(sp.sku_id == l.sku_id for sp in my_products)]
        rng2 = random.Random(seed + int(sup_id.split("-")[1]))
        chosen = rng2.sample(cand_lines, k=min(prof["count"], len(cand_lines)))
        # for SUP-004 (photo) force 2 unresolved-UOM lines
        forced_unresolved = []
        if sup_id == "SUP-004":
            forced_unresolved = rng2.sample(chosen, k=2)
        for line in chosen:
            sp = next(sp for sp in my_products if sp.sku_id == line.sku_id)
            sku = sku_by_id[line.sku_id]
            base = _base_price(line, sku_by_id)
            mult = rng2.uniform(0.96, 1.06) * _PRICE_MULT[sup_id]
            supplier_currency = prof["currency"]
            fx = 1.0 if supplier_currency == "INR" else 86.50

            # quoted price in supplier's currency for ONE supplier pack unit
            unit_price_inr = round(base * mult, 4)
            conv = sp.conversion_factor if sp.supplier_base_uom != sku.buyer_uom else 1.0
            if conv == 1.0:
                conv = sp.conversion_factor  # use product's canonical factor
            quoted_price = round(unit_price_inr / fx * conv, 4)

            unresolved = line.rfx_line_id in {x.rfx_line_id for x in forced_unresolved}
            quoted_uom = sp.supplier_base_uom if not unresolved else "UNKNOWN"
            conv = sp.conversion_factor if quoted_uom != "UNKNOWN" else None

            lead = _BASE_LEAD[sup_id] + rng2.choice([-1, -1, 0, 0, 0, 1, 1, 2])
            lead_fail = (sup_id == "SUP-005" and line.line_number % 7 == 0) or (
                sup_id == "SUP-004" and line.line_number % 11 == 0)
            if lead_fail:
                lead = line.required_lead_time_days + 7

            moq = 0.0
            if sup_id == "SUP-002" and line.line_number % 5 == 0:
                moq = line.required_quantity * 1.25  # forces MOQ fail
            elif sup_id == "SUP-003":
                moq = 2000.0
            elif sup_id == "SUP-007":
                moq = 10000.0

            valid_days = prof["valid_days"]
            valid_until = DECISION_DATE + timedelta(days=valid_days)
            if sup_id == "SUP-007" and line.line_number % 2 == 0:
                valid_until = DECISION_DATE - timedelta(days=5)  # expired

            discount_type, discount_pct = prof["discount"]

            offer = SupplierOffer(
                offer_id=f"OFF-{oid:04d}",
                rfx_id=RFX, rfx_line_id=line.rfx_line_id, line_number=line.line_number,
                supplier_id=sup_id, supplier_product_id=sp.supplier_product_id,
                sku_id=line.sku_id,
                supplier_product_code=sp.supplier_product_code,
                quoted_description=sp.supplier_product_name,
                specification=line.specification,
                required_quantity=line.required_quantity,
                buyer_uom=line.buyer_uom,
                quoted_quantity=round(line.required_quantity / conv, 2) if conv else None,
                quoted_uom=quoted_uom,
                quoted_unit_price=quoted_price,
                quoted_currency=supplier_currency,
                quote_received_date="2026-09-04",
                quote_valid_until=valid_until.isoformat(),
                payment_terms=f"Net {prof['pay_days']}",
                payment_days=prof["pay_days"],
                freight_amount=prof["freight_amt"],
                freight_basis=prof["freight"],
                moq=moq,
                lead_time_days=lead,
                quality_requirement="PASS_REQUIRED",
                discount_rule_type=discount_type,
                discount_rule_id=f"DR-{sup_id.split('-')[1]}-{line.line_number:02d}",
                discount_percentage=discount_pct,
                mapping_status=sp.mapping_status,
                mapping_confidence=sp.mapping_confidence,
                extraction_confidence=round(rng2.uniform(0.86, 0.99), 2) if not unresolved else 0.52,
            )
            if offer.quoted_quantity is None:
                offer.quoted_quantity = 0.0

            offers.append(offer)
            src_file, src_type = file_for[sup_id]
            loc = _evidence_location(src_type, line.line_number, oid)
            conf = "HIGH"
            if unresolved:
                conf = "LOW"
            elif sup_id == "SUP-004":
                conf = "MEDIUM"
            evidence.append(OfferEvidence(
                evidence_id=f"EVD-{evid:04d}",
                offer_id=offer.offer_id,
                source_type=src_type, source_file=src_file,
                source_location=loc,
                source_text=f"Qty {offer.quoted_quantity} × {offer.quoted_uom} @ "
                            f"{offer.quoted_currency} {offer.quoted_unit_price}",
                extracted_value=str(offer.quoted_unit_price),
                extraction_confidence=conf,
                verification_status="REVIEW_REQUIRED" if unresolved else "NORMALIZED",
                requires_review=unresolved or conf == "LOW",
            ))
            oid += 1
            evid += 1

            if discount_type == "QUANTITY_TIER_PERCENT":
                conv2 = conv or 1.0
                base_tiers = [
                    (0.0, 249.0, 1.5),
                    (250.0, 499.0, 3.0),
                    (500.0, None, 5.0),
                ]
                for ti, (mn, mx, pct) in enumerate(base_tiers, start=1):
                    tiers.append(DiscountTier(
                        discount_tier_id=f"DT-{tide:04d}",
                        offer_id=offer.offer_id,
                        tier_sequence=ti,
                        supplier_min_qty=mn,
                        supplier_max_qty=mx,
                        supplier_tier_uom=offer.quoted_uom,
                        min_inclusive=True,
                        max_inclusive=False,
                        discount_percentage=pct,
                        source_text=(f"{int(mn)}–{int(mx)} {offer.quoted_uom} = {pct}%"
                                     if mx else f">{int(mn)} {offer.quoted_uom} = {pct}%"),
                        normalized_min_qty=round(mn * conv2, 0) if not unresolved else None,
                        normalized_max_qty=round(mx * conv2, 0) if (mx and not unresolved) else None,
                        buyer_uom=line.buyer_uom,
                        conversion_factor=conv2,
                        normalization_status="UNRESOLVED" if unresolved else "NORMALIZED",
                    ))
                    tide += 1

    return offers, tiers, evidence


def _evidence_location(src_type: str, line: int, oid: int) -> str:
    if src_type == "EXCEL":
        return f"Quote!B{6 + (oid % 34)}"
    if src_type == "PDF":
        return f"Page 1 · Line {line}"
    if src_type == "IMAGE":
        return f"Grid row {6 + (oid % 20)}"
    if src_type == "EMAIL":
        return f"Paragraph 2 · line item {line}"
    return f"Page 1 · Line {line}"


# ---------------------------------------------------------------- Questionnaire responses
def _make_questionnaire_responses(suppliers: list[Supplier]) -> list[QuestionnaireResponse]:
    rows = []
    for s in suppliers:
        sid = s.supplier_id
        prof = _OFFER_PROFILE[sid]
        if sid == "SUP-008":
            for q in _QUESTIONS:
                qid = q[0]
                rows.append(QuestionnaireResponse(
                    question_response_id=f"QR-8-{qid}",
                    rfx_id=RFX, supplier_id=sid, question_id=qid,
                    response_value="NO_RESPONSE",
                    response_status="MISSING",
                ))
            continue
        quality = prof["quality"]
        freight_text = ("Included" if prof["freight"] == "INCLUDED"
                        else f"Extra, ₹{int(prof['freight_amt'])} per shipment")
        vals = {
            "Q1": "Confirmed by required delivery date",
            "Q2": quality,
            "Q3": f"{30} days lead time; 250k units/month capacity",
            "Q4": f"Net {prof['pay_days']}",
            "Q5": freight_text,
        }
        for qid, v in vals.items():
            rows.append(QuestionnaireResponse(
                question_response_id=f"QR-{sid.split('-')[1]}-{qid}",
                rfx_id=RFX, supplier_id=sid, question_id=qid,
                response_value=v,
                response_status="VERIFIED" if v not in ("CONDITIONAL", "NO_RESPONSE")
                else "REVIEW_REQUIRED",
            ))
    return rows


# ---------------------------------------------------------------- Coverage
def _make_coverage_records(lines, suppliers, products, offers):
    """RFx line × supplier coverage projection."""
    sp_by_sup_sku = {}
    for sp in products:
        sp_by_sup_sku[(sp.supplier_id, sp.sku_id)] = True
    offered = {(o.rfx_line_id, o.supplier_id) for o in offers}
    records = []
    idx = 1
    from app.domain.models import CoverageRecord
    for line in lines:
        for s in suppliers:
            mapped = (s.supplier_id, line.sku_id) in sp_by_sup_sku
            rec = CoverageRecord(
                coverage_record_id=f"CV-{idx:04d}",
                rfx_id=RFX, rfx_line_id=line.rfx_line_id, line_number=line.line_number,
                sku_id=line.sku_id, supplier_id=s.supplier_id,
                supplier_name=s.supplier_name,
                supplier_product_mapping_exists=mapped,
                offer_received=(line.rfx_line_id, s.supplier_id) in offered,
            )
            records.append(rec)
            idx += 1
    return records


# ---------------------------------------------------------------- Orchestrator
def build(seed: int = SEED) -> dict:
    """Deterministic dataset. Default seed reproduces the golden dataset
    exactly; any other seed deals fresh values (names, prices, RFx title)
    over stable IDs and counts."""
    global rng
    rng = random.Random(seed)
    skus = _make_skus()
    suppliers = _make_suppliers(seed)
    rfx, lines = _make_rfx_and_lines(skus, seed)
    line_sku_ids = {l.sku_id for l in lines}
    products = _make_supplier_products(skus, line_sku_ids, suppliers)
    fx, policy = _make_fx_and_policy()
    questions = _make_questionnaire()
    rfx_suppliers = _make_rfx_suppliers()
    offers, tiers, evidence = _make_offers(lines, products, skus, suppliers, seed)
    q_responses = _make_questionnaire_responses(suppliers)
    coverage = _make_coverage_records(lines, suppliers, products, offers)

    # close mapped/quoted counts on rfx_supplier
    for rs in rfx_suppliers:
        rs.mapped_rfx_line_count = len({r.sku_id for r in coverage
                                        if r.supplier_id == rs.supplier_id
                                        and r.supplier_product_mapping_exists})
        rs.quoted_rfx_line_count = len({o.line_number for o in offers
                                        if o.supplier_id == rs.supplier_id})
        rs.unquoted_mapped_line_count = max(0, rs.mapped_rfx_line_count - rs.quoted_rfx_line_count)

    sku_by_id = {s.sku_id: s for s in skus}
    assert len(skus) == 50, len(skus)
    assert len(suppliers) == 8, len(suppliers)
    assert len(products) == 249, len(products)
    assert len(lines) == 30, len(lines)
    assert len(offers) == 131, len(offers)
    assert len(q_responses) == 40, len(q_responses)
    assert len(evidence) == len(offers)
    assert sum(1 for l in lines if l.line_number in (29, 30)) == 2
    assert all(o.rfx_line_id != "LF-29" and o.rfx_line_id != "LF-30" for o in offers)

    return dict(
        skus=skus, suppliers=suppliers, products=products, fx=fx, policy=policy,
        rfx=rfx, lines=lines, rfx_suppliers=rfx_suppliers, questions=questions,
        offers=offers, tiers=tiers, evidence=evidence, q_responses=q_responses,
        coverage=coverage, sku_by_id=sku_by_id,
    )


# ---------------------------------------------------------------- CSV export helpers
def _dump(rows, name: str, outdir: str, fields=None):
    objs = rows if isinstance(rows, (list, tuple)) else [rows]
    fieldnames = fields or [k for k in asdict_like(objs[0]).keys()]
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, name)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for o in objs:
            w.writerow(asdict_like(o))
    return path


def asdict_like(o):
    from dataclasses import fields
    return {f.name: getattr(o, f.name) for f in fields(o)}


def export_golden(dataset: dict, outdir: str = "data/seed"):
    paths = {}
    sets = [
        ("skus", "Aerchain_Golden_Product_SKU_Master_50.csv"),
        ("suppliers", "Aerchain_Golden_Supplier_Master_8.csv"),
        ("products", "Aerchain_Golden_Supplier_Product_Master_249.csv"),
        ("fx", "Aerchain_Golden_FX_Rate_Master_001.csv"),
        ("policy", "Aerchain_Golden_Procurement_Policy_001.csv"),
        ("rfx", "Aerchain_Golden_RFx_001.csv"),
        ("lines", "Aerchain_Golden_RFx_Lines_001_30.csv"),
        ("rfx_suppliers", "Aerchain_Golden_RFx_Supplier_001.csv"),
        ("questions", "Aerchain_Golden_RFx_Questionnaire_001.csv"),
        ("offers", "Aerchain_Golden_Supplier_Offers_001.csv"),
        ("tiers", "Aerchain_Golden_Discount_Tier_Rules_001.csv"),
        ("evidence", "Aerchain_Golden_Offer_Evidence_001.csv"),
        ("q_responses", "Aerchain_Golden_Supplier_Questionnaire_Responses_001.csv"),
        ("coverage", "Aerchain_Golden_RFx_Coverage_001.csv"),
    ]
    for key, name in sets:
        paths[name] = _dump(dataset[key], name, outdir)
    return paths


def main():
    ds = build()
    export_golden(ds)
    print("golden seed generated:" )
    for k, v in [("skus", len(ds["skus"])), ("suppliers", len(ds["suppliers"])),
                 ("products", len(ds["products"])), ("lines", len(ds["lines"])),
                 ("offers", len(ds["offers"])), ("tiers", len(ds["tiers"])),
                 ("evidence", len(ds["evidence"])), ("q_responses", len(ds["q_responses"]))]:
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()