"""User-upload ingestion — real files, real extraction, honest matching.

Uploaded files land in data/uploads/ (never mixed into the golden data/raw/
set). Each file is run through the same real extractors as the golden
artifacts — including Tesseract OCR for images — then every parsed row is
matched against the supplier-product master by product code. Rows that match
nothing, or that OCR could not read cleanly, are kept with explicit
UNRESOLVED flags instead of being silently dropped or invented.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app.database import get_conn

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/uploads"))

_ALLOWED = {".xlsx": "EXCEL", ".pdf": "PDF", ".jpg": "IMAGE", ".jpeg": "IMAGE",
            ".png": "IMAGE", ".txt": "EMAIL", ".eml": "EMAIL", ".docx": "WORD"}


def classify(filename: str) -> str | None:
    return _ALLOWED.get(os.path.splitext(filename.lower())[1])


def save_upload(filename: str, content: bytes) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in
                   os.path.basename(filename))[:80] or "upload"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = os.path.join(UPLOAD_DIR, f"{stamp}_{safe}")
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def extract_upload(path: str, source_type: str) -> tuple[list[dict], str]:
    """Run the real extractor for this file type. Returns (rows, engine)."""
    from app.services import extraction
    if source_type == "EXCEL":
        return extraction.extract_xlsx(path), "openpyxl"
    if source_type == "PDF":
        return extraction.extract_pdf_text(path), "pypdf"
    if source_type == "WORD":
        return extraction.extract_docx(path), "python-docx"
    if source_type == "IMAGE":
        rows = extraction.extract_image_ocr(path)
        engine = rows[0].get("ocr_engine", "tesseract") if rows else "tesseract"
        return rows, engine
    rows = extraction.extract_email_text(path)
    return rows, "regex-text"


def _norm_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "").replace("_", "-")


def _ensure_schema():
    conn = get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(uploaded_file)")]
    if "content_hash" not in cols:
        conn.execute("ALTER TABLE uploaded_file ADD COLUMN content_hash TEXT")
    conn.commit()
    conn.close()


def match_rows(rows: list[dict], supplier_id: str | None = None) -> list[dict]:
    """Attach matched_supplier_id/matched_sku_id where the row's product code
    exists in the supplier-product master; otherwise flag no_product_match.
    When supplier_id is given (buyer-declared uploader), only that supplier's
    catalogue is eligible — a code belonging to someone else will NOT match."""
    conn = get_conn()
    master = {}
    for r in conn.execute(
            "SELECT supplier_product_code, supplier_id, sku_id FROM supplier_product"):
        if supplier_id and r[1] != supplier_id:
            continue
        master[r[0].upper()] = (r[1], r[2])
    suppliers = {r[0]: r[1] for r in conn.execute(
        "SELECT supplier_id, supplier_name FROM supplier")}
    sku_map = {}
    for r in conn.execute("SELECT sku_id FROM sku"):
        sku_map[r[0].upper()] = r[0]
    pairs = {(r[0], r[1].upper()) for r in conn.execute(
        "SELECT supplier_id, sku_id FROM supplier_product")}
    conn.close()
    out = []
    for r in rows:
        r = dict(r)
        hit = master.get(_norm_code(r.get("sku_code")))
        if hit:
            r["matched_supplier_id"], r["matched_sku_id"] = hit
        else:
            # card layouts carry a buyer SKU + supplier name instead of a
            # product code: resolve both halves, keep what verifies
            r["matched_supplier_id"], r["matched_sku_id"] = None, None
            hint = (r.get("supplier_name_hint") or "").strip().lower()
            sup = next((sid for sid, name in suppliers.items()
                        if hint and (hint == name.lower() or hint in name.lower()
                                     or name.lower() in hint)), None)
            if supplier_id and sup != supplier_id:
                sup = None  # scoped upload: foreign supplier never matches
            sku = _norm_code(r.get("sku_code"))
            if sup and sku in sku_map and (sup, sku) in pairs:
                r["matched_supplier_id"], r["matched_sku_id"] = sup, sku_map[sku]
            elif supplier_id:
                # scoped upload: the code is simply not in this catalogue
                r["unresolved"] = list(r.get("unresolved") or []) + ["no_product_match"]
            else:
                flag = ("unknown_supplier" if not sup
                        else "unknown_sku" if sku not in sku_map
                        else "no_product_match")
                r["unresolved"] = list(r.get("unresolved") or []) + [flag]
        out.append(r)
    return out


def store_upload(filename: str, path: str, source_type: str,
                 rows: list[dict], engine: str, content: bytes | None = None) -> dict:
    import hashlib
    _ensure_schema()
    conn = get_conn()
    digest = hashlib.sha256(content).hexdigest() if content else None
    if digest:
        dup = conn.execute("SELECT file_id, filename FROM uploaded_file"
                           " WHERE content_hash=?", (digest,)).fetchone()
        if dup:
            conn.close()
            raise ValueError(f"duplicate of upload #{dup[0]} ({dup[1]})")
    unresolved = sum(1 for r in rows if r.get("unresolved"))
    cur = conn.execute(
        "INSERT INTO uploaded_file (filename, stored_path, source_type, ocr_engine,"
        " row_count, unresolved_count, uploaded_at, content_hash)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (filename, path, source_type, engine, len(rows), unresolved,
         datetime.now(timezone.utc).isoformat(), digest))
    fid = cur.lastrowid
    for r in rows:
        conn.execute(
            "INSERT INTO uploaded_offer (file_id, supplier_code, quantity, unit_uom,"
            " currency, unit_price, moq, lead_days, valid_until, matched_supplier_id,"
            " matched_sku_id, unresolved, raw_text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, r.get("sku_code"), r.get("quantity"), r.get("unit_uom"),
             r.get("currency"), r.get("unit_price"), r.get("moq"),
             r.get("lead_days"), r.get("valid_until"),
             r.get("matched_supplier_id"), r.get("matched_sku_id"),
             json.dumps(r.get("unresolved") or []), r.get("raw_text")))
    conn.commit()
    matched = sum(1 for r in rows if r.get("matched_supplier_id"))
    conn.close()
    return {"file_id": fid, "rows": len(rows), "unresolved": unresolved,
            "matched": matched, "engine": engine}


def list_uploads() -> list[dict]:
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT file_id, filename, source_type, ocr_engine, row_count,"
        " unresolved_count, uploaded_at FROM uploaded_file ORDER BY file_id DESC")]
    conn.close()
    return rows


def get_upload_rows(file_id: int) -> list[dict]:
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM uploaded_offer WHERE file_id=? ORDER BY upload_offer_id",
        (file_id,))]
    conn.close()
    return rows


def get_upload_rows(file_id: int) -> list[dict]:
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM uploaded_offer WHERE file_id=? ORDER BY upload_offer_id",
        (file_id,))]
    conn.close()
    return rows


def promote_upload(file_id: int, payment_days: int = 30,
                   freight_basis: str = "INCLUDED", freight_amount: float = 0.0,
                   default_valid_until: str | None = None,
                   default_lead_days: int | None = None) -> dict:
    """Promote buyer-confirmed uploaded rows into the live decision layer.

    Only rows matched to the product master with complete price/qty/UOM and a
    known lead time (row or buyer default) are promoted; everything else is
    reported in `skipped` with a reason — never fabricated. New offers run the
    REAL engines (FX/UOM/discount/freight/financing/eligibility) and the award
    + coverage layers are recomputed over the full dataset afterwards.
    """
    from types import SimpleNamespace
    from app.domain.models import (AwardDecision, DiscountTier, OfferEvidence,
                                   Scenario, SupplierOffer)
    from app.engines.scenario import award_line_level
    from app.pipeline import _insert, _to_row
    from app.services.decision_ready import build_decision_ready
    from app.services.extraction import parse_tier_hints

    conn = get_conn()
    f = conn.execute("SELECT * FROM uploaded_file WHERE file_id = ?",
                     (file_id,)).fetchone()
    if not f:
        conn.close()
        raise ValueError(f"no upload {file_id}")
    f = dict(f)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM uploaded_offer WHERE file_id=? ORDER BY upload_offer_id",
        (file_id,))]

    def table(name: str) -> list[dict]:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {name}")]

    products = {(r["supplier_id"], r["sku_id"]): SimpleNamespace(**r)
                for r in table("supplier_product")}
    suppliers = {r["supplier_id"]: SimpleNamespace(**r) for r in table("supplier")}
    skus = {r["sku_id"]: SimpleNamespace(**r) for r in table("sku")}
    lines_by_sku: dict[str, object] = {}
    for r in table("rfx_line"):
        lines_by_sku.setdefault(r["sku_id"], SimpleNamespace(**r))
    policy = SimpleNamespace(**table("policy")[0])
    fx_rows = [SimpleNamespace(**r) for r in table("fx_rate")]
    q_by_supplier = {}
    for r in table("questionnaire_response"):
        if r["question_id"] == "Q2":
            q_by_supplier[r["supplier_id"]] = r["response_value"].replace(
                "Qualified", "PASS")

    assumptions = [
        f"buyer-confirmed payment Net {payment_days}",
        f"buyer-confirmed freight {freight_basis}"
        + (f" {freight_amount}/shipment" if freight_amount else ""),
    ]
    if default_valid_until:
        assumptions.append(f"buyer-confirmed validity {default_valid_until}"
                           " where the file gave none")
    if default_lead_days is not None:
        assumptions.append(f"buyer-confirmed lead {default_lead_days}d"
                           " where the file gave none")

    hints = parse_tier_hints([r["raw_text"] for r in rows if r.get("raw_text")])
    new_offers, new_tiers, new_evs = [], [], []
    skipped, seq = [], 0
    today = datetime.now(timezone.utc).date().isoformat()
    for i, r in enumerate(rows, 1):
        why = None
        if not r["matched_supplier_id"]:
            why = "no product-code match"
        elif r["unit_price"] is None or r["quantity"] is None:
            why = "unreadable price/quantity"
        elif (r["lead_days"] or default_lead_days) is None:
            why = "missing lead time and no buyer default"
        line = lines_by_sku.get(r["matched_sku_id"] or "")
        if why is None and line is None:
            why = "matched SKU is on no RFx line"
        if why:
            skipped.append({"row": i, "code": r["supplier_code"], "reason": why})
            continue
        seq += 1
        oid = f"OFF-U{file_id}-{seq:02d}"
        sp = products[(r["matched_supplier_id"], r["matched_sku_id"])]
        valid = r["valid_until"] or default_valid_until or ""
        offer = SupplierOffer(
            offer_id=oid, rfx_id="RFX-001", rfx_line_id=line.rfx_line_id,
            line_number=line.line_number, supplier_id=r["matched_supplier_id"],
            supplier_product_id=sp.supplier_product_id, sku_id=r["matched_sku_id"],
            supplier_product_code=r["supplier_code"],
            quoted_description=f"upload #{file_id} {f['filename']}",
            specification=getattr(line, "specification", ""),
            required_quantity=line.required_quantity, buyer_uom=line.buyer_uom,
            quoted_quantity=r["quantity"], quoted_uom=r["unit_uom"],
            quoted_unit_price=r["unit_price"], quoted_currency=r["currency"],
            quote_received_date=today, quote_valid_until=valid,
            payment_terms=f"Net {payment_days}", payment_days=payment_days,
            freight_amount=freight_amount, freight_basis=freight_basis,
            moq=r["moq"] or 0.0, lead_time_days=r["lead_days"] or default_lead_days,
            discount_rule_type="QUANTITY_TIER_PERCENT" if hints else None,
            discount_rule_id=f"DR-U{file_id}" if hints else None,
            mapping_status="CONFIRMED", mapping_confidence=1.0,
            extraction_confidence=0.55 if json.loads(r["unresolved"] or "[]") else 0.95,
        )
        new_offers.append(offer)
        conv = sp.conversion_factor or 1.0
        for ti, h in enumerate(hints, 1):
            nxt = hints[ti]["supplier_min_qty"] if ti < len(hints) else None
            new_tiers.append(DiscountTier(
                discount_tier_id=f"DT-U{file_id}-{seq:02d}-{ti}",
                offer_id=oid, tier_sequence=ti,
                supplier_min_qty=h["supplier_min_qty"], supplier_max_qty=nxt,
                supplier_tier_uom=r["unit_uom"],
                discount_percentage=h["discount_percentage"],
                source_text=h["source_text"],
                normalized_min_qty=round(h["supplier_min_qty"] * conv, 0),
                normalized_max_qty=round(nxt * conv, 0) if nxt else None,
                buyer_uom=line.buyer_uom, conversion_factor=conv))
        new_evs.append(OfferEvidence(
            evidence_id=f"EVD-U{file_id}-{seq:02d}", offer_id=oid,
            source_type=f["source_type"], source_file=f["filename"],
            source_location=f"upload row {i}",
            source_text=(r["raw_text"] or f"{r['supplier_code']} {r['quantity']} "
                         f"{r['unit_uom']} {r['currency']} {r['unit_price']}"),
            extracted_value=str(r["unit_price"]),
            extraction_confidence="MEDIUM" if json.loads(r["unresolved"] or "[]")
            else "HIGH",
            verification_status="REVIEW_REQUIRED" if json.loads(r["unresolved"] or "[]")
            else "NORMALIZED",
            requires_review=bool(json.loads(r["unresolved"] or "[]"))))

    for o in new_offers:
        _insert(conn, "supplier_offer", _to_row(o), conjoin=True)
    for t in new_tiers:
        _insert(conn, "discount_tier", _to_row(t), conjoin=True)
    for e in new_evs:
        _insert(conn, "offer_evidence", _to_row(e), conjoin=True)
    conn.commit()

    tiers_by_offer: dict[str, list] = {}
    for t in new_tiers:
        tiers_by_offer.setdefault(t.offer_id, []).append(t)
    ev_by_offer = {e.offer_id: e for e in new_evs}
    records = build_decision_ready(
        new_offers,
        {sp.supplier_product_id: sp for (s, _), sp in products.items()
         if s in {o.supplier_id for o in new_offers}},
        {o.supplier_id: suppliers[o.supplier_id] for o in new_offers},
        {o.sku_id: skus[o.sku_id] for o in new_offers},
        {o.rfx_line_id: lines_by_sku[o.sku_id] for o in new_offers},
        tiers_by_offer, ev_by_offer, q_by_supplier, policy, fx_rows)
    # build_decision_ready numbers DRR-0001.. fresh per call — remint upload
    # records so INSERT OR REPLACE can never clobber golden rows
    for i, rec in enumerate(records, 1):
        rec.decision_record_id = f"DRR-U{file_id}-{i:02d}"
    for rec in records:
        _insert(conn, "decision_ready", _to_row(rec), conjoin=True)
    for o in new_offers:
        conn.execute("UPDATE coverage SET offer_received=1 WHERE rfx_line_id=?"
                     " AND supplier_id=?", (o.rfx_line_id, o.supplier_id))
    conn.commit()

    all_recs = [SimpleNamespace(**dict(r)) for r in
                conn.execute("SELECT * FROM decision_ready")]
    base = Scenario(scenario_id="BASE", rfx_id="RFX-001",
                    scenario_name="Baseline award · cheapest eligible per line",
                    award_strategy="LINE_LEVEL_SPLIT")
    conn.execute("DELETE FROM award_decision")
    for a in award_line_level(all_recs, base, policy):
        _insert(conn, "award_decision", _to_row(a), conjoin=True)
    conn.commit()
    awarded = conn.execute("SELECT COUNT(*) FROM award_decision").fetchone()[0]
    conn.close()
    return {"file_id": file_id, "promoted": len(records),
            "eligible": sum(1 for r in records if r.overall_eligible),
            "skipped": skipped, "assumptions": assumptions,
            "tiers_applied": len(hints), "lines_awarded": awarded}
