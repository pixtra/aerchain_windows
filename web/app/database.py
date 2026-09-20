"""SQLite storage layer."""
from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get(
    "AERCHAIN_DB",
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "data", "aerchain.db")))
DB_DIR = os.path.dirname(DB_PATH)


def _ensure_dir():
    if DB_DIR:
        os.makedirs(DB_DIR, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_schema():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS sku (
            sku_id TEXT PRIMARY KEY,
            sku_name TEXT, category TEXT, buyer_uom TEXT,
            specification TEXT, status TEXT, typical_supplier_uoms TEXT
        );
        CREATE TABLE IF NOT EXISTS supplier (
            supplier_id TEXT PRIMARY KEY,
            supplier_code TEXT, supplier_name TEXT, supplier_status TEXT,
            default_currency TEXT, default_payment_terms TEXT,
            default_payment_days INTEGER, default_freight_terms TEXT,
            default_lead_time_days INTEGER, default_quote_validity_days INTEGER,
            location TEXT
        );
        CREATE TABLE IF NOT EXISTS supplier_product (
            supplier_product_id TEXT PRIMARY KEY,
            supplier_id TEXT, sku_id TEXT,
            supplier_product_code TEXT, supplier_product_name TEXT,
            supplier_description TEXT, supplier_base_uom TEXT,
            pack_size REAL, pack_size_uom TEXT, conversion_factor REAL,
            conversion_source TEXT, mapping_status TEXT, mapping_type TEXT,
            mapping_confidence REAL
        );
        CREATE TABLE IF NOT EXISTS fx_rate (
            fx_rate_id TEXT PRIMARY KEY,
            from_currency TEXT, to_currency TEXT, fx_rate REAL, status TEXT
        );
        CREATE TABLE IF NOT EXISTS policy (
            policy_id TEXT PRIMARY KEY,
            organization_id TEXT, policy_name TEXT, base_currency TEXT,
            annual_financing_rate REAL, baseline_payment_days INTEGER,
            tax_treatment TEXT, hard_moq_constraint INTEGER,
            hard_lead_time_constraint INTEGER, quality_required_for_award INTEGER,
            expired_quote_ineligible INTEGER, default_award_strategy TEXT,
            status TEXT
        );
        CREATE TABLE IF NOT EXISTS rfx (
            rfx_id TEXT PRIMARY KEY, rfx_name TEXT, category TEXT,
            organization_id TEXT, base_currency TEXT, response_deadline TEXT,
            required_delivery_date TEXT, award_strategy TEXT,
            quality_required INTEGER, status TEXT
        );
        CREATE TABLE IF NOT EXISTS rfx_line (
            rfx_line_id TEXT PRIMARY KEY, rfx_id TEXT, line_number INTEGER,
            sku_id TEXT, buyer_description TEXT, specification TEXT,
            required_quantity REAL, buyer_uom TEXT, required_delivery_date TEXT,
            required_lead_time_days INTEGER, quality_requirement TEXT,
            max_moq REAL, line_status TEXT, category TEXT
        );
        CREATE TABLE IF NOT EXISTS rfx_supplier (
            rfx_supplier_id TEXT PRIMARY KEY, rfx_id TEXT, supplier_id TEXT,
            invitation_status TEXT, response_status TEXT, invited_at TEXT,
            response_received_at TEXT, source_document_count INTEGER,
            mapped_rfx_line_count INTEGER, quoted_rfx_line_count INTEGER,
            unquoted_mapped_line_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS rfx_question (
            question_id TEXT PRIMARY KEY, rfx_id TEXT, question_sequence INTEGER,
            question_text TEXT, response_type TEXT, mandatory INTEGER
        );
        CREATE TABLE IF NOT EXISTS questionnaire_response (
            question_response_id TEXT PRIMARY KEY, rfx_id TEXT, supplier_id TEXT,
            question_id TEXT, response_value TEXT, response_status TEXT
        );
        CREATE TABLE IF NOT EXISTS supplier_offer (
            offer_id TEXT PRIMARY KEY, rfx_id TEXT, rfx_line_id TEXT,
            line_number INTEGER, supplier_id TEXT, supplier_product_id TEXT,
            sku_id TEXT, supplier_product_code TEXT, quoted_description TEXT,
            specification TEXT, required_quantity REAL, buyer_uom TEXT,
            quoted_quantity REAL, quoted_uom TEXT, quoted_unit_price REAL,
            quoted_currency TEXT, quote_received_date TEXT, quote_valid_until TEXT,
            payment_terms TEXT, payment_days INTEGER, freight_amount REAL,
            freight_basis TEXT, moq REAL, lead_time_days INTEGER,
            quality_requirement TEXT, discount_rule_type TEXT,
            discount_rule_id TEXT, discount_percentage REAL,
            discount_amount REAL, discount_currency TEXT,
            mapping_status TEXT, mapping_confidence REAL,
            extraction_confidence REAL
        );
        CREATE TABLE IF NOT EXISTS discount_tier (
            discount_tier_id TEXT PRIMARY KEY, offer_id TEXT,
            tier_sequence INTEGER, supplier_min_qty REAL,
            supplier_max_qty REAL, supplier_tier_uom TEXT,
            min_inclusive INTEGER, max_inclusive INTEGER,
            discount_percentage REAL, source_text TEXT,
            normalized_min_qty REAL, normalized_max_qty REAL,
            buyer_uom TEXT, conversion_factor REAL, normalization_status TEXT
        );
        CREATE TABLE IF NOT EXISTS offer_evidence (
            evidence_id TEXT PRIMARY KEY, offer_id TEXT,
            source_type TEXT, source_file TEXT, page_number INTEGER,
            source_location TEXT, source_text TEXT, extracted_value TEXT,
            extraction_confidence TEXT, normalization_confidence TEXT,
            verification_status TEXT, requires_review INTEGER
        );
        CREATE TABLE IF NOT EXISTS decision_ready (
            decision_record_id TEXT PRIMARY KEY,
            rfx_id TEXT, rfx_line_id TEXT, line_number INTEGER, sku_id TEXT,
            supplier_id TEXT, supplier_name TEXT, offer_id TEXT,
            supplier_product_id TEXT, supplier_product_code TEXT,
            quoted_description TEXT, buyer_uom TEXT, required_quantity REAL,
            required_lead_time_days INTEGER, quality_requirement TEXT,
            quoted_unit_price REAL, quoted_currency TEXT, quoted_uom TEXT,
            quoted_quantity REAL, fx_rate_id TEXT, fx_rate_applied REAL,
            uom_conversion_factor REAL, uom_conversion_source TEXT,
            normalized_unit_price REAL, discount_rule_type TEXT,
            applicable_discount_percentage REAL, discount_benefit REAL,
            net_material_price REAL, freight_basis TEXT, allocated_freight REAL,
            payment_days INTEGER, financing_benefit REAL,
            effective_economic_cost REAL, moq REAL, lead_time_days INTEGER,
            quote_valid_until TEXT, moq_eligible INTEGER,
            lead_time_eligible INTEGER, quality_eligible INTEGER,
            quote_validity_eligible INTEGER, mapping_eligible INTEGER,
            overall_eligible INTEGER, eligibility_reason TEXT,
            evidence_id TEXT, source_file TEXT, source_type TEXT,
            source_location TEXT, source_text TEXT,
            extraction_confidence TEXT, normalization_confidence TEXT,
            verification_status TEXT, requires_review INTEGER,
            error_state TEXT, error_detail TEXT
        );
        CREATE TABLE IF NOT EXISTS coverage (
            coverage_record_id TEXT PRIMARY KEY,
            rfx_id TEXT, rfx_line_id TEXT, line_number INTEGER, sku_id TEXT,
            supplier_id TEXT, supplier_name TEXT,
            supplier_product_mapping_exists INTEGER, offer_received INTEGER
        );
        CREATE TABLE IF NOT EXISTS award_decision (
            award_decision_id TEXT PRIMARY KEY, scenario_id TEXT, rfx_id TEXT,
            rfx_line_id TEXT, line_number INTEGER, supplier_id TEXT,
            offer_id TEXT, effective_economic_cost REAL,
            decision_status TEXT, decision_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS extraction_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfx_id TEXT, supplier_id TEXT, source_document TEXT,
            candidate_json TEXT, rule TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS uploaded_file (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT, stored_path TEXT, source_type TEXT,
            ocr_engine TEXT, row_count INTEGER, unresolved_count INTEGER,
            uploaded_at TEXT
        );
        CREATE TABLE IF NOT EXISTS uploaded_offer (
            upload_offer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER, supplier_code TEXT, quantity REAL,
            unit_uom TEXT, currency TEXT, unit_price REAL,
            moq REAL, lead_days INTEGER, valid_until TEXT,
            matched_supplier_id TEXT, matched_sku_id TEXT,
            unresolved TEXT, raw_text TEXT
        );
        """
    )
    conn.commit()
    conn.close()