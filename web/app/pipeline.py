"""Pipeline: seed → SQLite → decision-ready → coverage → baseline award."""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
from datetime import date

from app import seed_data
from app.database import get_conn, init_schema
from app.domain.enums import BASE_CURRENCY, DEFAULT_DECISION_DATE
from app.domain.models import CoverageRecord, Scenario
from app.engines.scenario import award_line_level
from app.services.decision_ready import build_decision_ready

DATA_DIR = os.path.dirname(os.path.abspath(__file__)) + "/../data"


def _bool(v):
    return 1 if v else 0


def _to_row(obj) -> dict:
    return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}


def _insert(conn, table: str, row: dict, conjoin: bool = False):
    """conjoin=True converts bool fields to int (for tables whose schema uses INTEGER)."""
    data = dict(row)
    if conjoin:
        data = {k: (_bool(v) if isinstance(v, bool) else v) for k, v in data.items()}
    cols = list(data.keys())
    qs = ",".join("?" * len(cols))
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({qs})"
    conn.execute(sql, list(data.values()))


_BOOL_SCHEMA = {
    "sku": (), "supplier": (), "supplier_product": (),
    "fx_rate": (), "policy": (), "rfx": (), "rfx_line": (),
    "rfx_supplier": (), "rfx_question": "mandatory",
    "questionnaire_response": (), "supplier_offer": (),
    "discount_tier": ("min_inclusive", "max_inclusive"),
    "offer_evidence": "requires_review",
    "decision_ready": ("moq_eligible", "lead_time_eligible", "quality_eligible",
                       "quote_validity_eligible", "mapping_eligible",
                       "overall_eligible", "requires_review"),
    "coverage": ("supplier_product_mapping_exists", "offer_received"),
    "award_decision": (),
}


def _bool_cols(table) -> tuple:
    v = _BOOL_SCHEMA.get(table, ())
    return v if isinstance(v, tuple) else (v,)


def reset_db(dataset=None) -> dict:
    dataset = dataset or seed_data.build()
    init_schema()
    conn = get_conn()
    try:
        for table in _BOOL_SCHEMA:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

        def put(table, rows, conjoin=True):
            if not isinstance(rows, (list, tuple)):
                rows = [rows]
            for r in rows:
                _insert(conn, table, _to_row(r), conjoin=conjoin)

        put("sku", dataset["skus"])
        put("supplier", dataset["suppliers"])
        put("supplier_product", dataset["products"])
        put("fx_rate", dataset["fx"])
        put("policy", dataset["policy"])
        put("rfx", dataset["rfx"])
        put("rfx_line", dataset["lines"])
        put("rfx_supplier", dataset["rfx_suppliers"])
        put("rfx_question", dataset["questions"])
        put("questionnaire_response", dataset["q_responses"])
        put("supplier_offer", dataset["offers"])
        put("discount_tier", dataset["tiers"])
        put("offer_evidence", dataset["evidence"])
        conn.commit()

        # ---- decision-ready ----
        products_by_id = {p.supplier_product_id: p for p in dataset["products"]}
        suppliers_by_id = {s.supplier_id: s for s in dataset["suppliers"]}
        skus_by_id = dataset["sku_by_id"]
        lines_by_id = {l.rfx_line_id: l for l in dataset["lines"]}
        tiers_by_offer = {}
        for t in dataset["tiers"]:
            tiers_by_offer.setdefault(t.offer_id, []).append(t)
        evidence_by_offer = {e.offer_id: e for e in dataset["evidence"]}
        q_by_supplier = {}
        for r in dataset["q_responses"]:
            if r.question_id == "Q2":
                q_by_supplier[r.supplier_id] = r.response_value.replace(
                    "Qualified", "PASS")

        records = build_decision_ready(
            dataset["offers"], products_by_id, suppliers_by_id, skus_by_id,
            lines_by_id, tiers_by_offer, evidence_by_offer,
            q_by_supplier, dataset["policy"], dataset["fx"])
        conn.execute("DELETE FROM decision_ready")
        for r in records:
            _insert(conn, "decision_ready", _to_row(r), conjoin=True)
        conn.commit()

        # ---- coverage ----
        conn.execute("DELETE FROM coverage")
        for c in dataset["coverage"]:
            _insert(conn, "coverage", _to_row(c), conjoin=True)
        conn.commit()

        # ---- baseline award ----
        conn.execute("DELETE FROM award_decision")
        base = Scenario(scenario_id="BASE", rfx_id="RFX-001",
                        scenario_name="Baseline award · cheapest eligible per line",
                        award_strategy="LINE_LEVEL_SPLIT")
        awards = award_line_level(records, base, dataset["policy"])
        for a in awards:
            _insert(conn, "award_decision", _to_row(a), conjoin=True)
        conn.commit()
    finally:
        conn.close()
    return dataset


def refresh() -> dict:
    return reset_db()


def validate() -> list[dict]:
    """§51 data-quality gates: fail-fast checks over the live database.
    Returns [{check, ok, detail}] — callers log, never silently proceed."""
    conn = get_conn()
    out = []

    def check(name: str, sql: str, expect_zero: bool = True, detail=""):
        try:
            n = conn.execute(sql).fetchone()[0]
            out.append({"check": name, "ok": bool(n == 0) if expect_zero else True,
                        "detail": detail or str(n)})
        except Exception as e:  # noqa: BLE001 — a missing table is itself a finding
            out.append({"check": name, "ok": False, "detail": f"{type(e).__name__}: {e}"})

    check("lines_have_valid_sku",
          "SELECT COUNT(*) FROM rfx_line l LEFT JOIN sku s ON s.sku_id=l.sku_id"
          " WHERE s.sku_id IS NULL")
    check("products_reference_valid_supplier",
          "SELECT COUNT(*) FROM supplier_product p LEFT JOIN supplier s"
          " ON s.supplier_id=p.supplier_id WHERE s.supplier_id IS NULL")
    check("products_reference_valid_sku",
          "SELECT COUNT(*) FROM supplier_product p LEFT JOIN sku s"
          " ON s.sku_id=p.sku_id WHERE s.sku_id IS NULL")
    check("offers_reference_valid_line",
          "SELECT COUNT(*) FROM supplier_offer o LEFT JOIN rfx_line l"
          " ON l.rfx_line_id=o.rfx_line_id WHERE l.rfx_line_id IS NULL")
    check("no_duplicate_offer_id",
          "SELECT COUNT(*) FROM (SELECT offer_id FROM supplier_offer"
          " GROUP BY offer_id HAVING COUNT(*) > 1)")
    check("fx_currencies_resolvable",
          "SELECT COUNT(DISTINCT quoted_currency) FROM supplier_offer"
          " WHERE quoted_currency NOT IN (SELECT DISTINCT from_currency FROM fx_rate)"
          " AND quoted_currency NOT IN (SELECT DISTINCT to_currency FROM fx_rate)")
    check("tiers_reference_valid_offer",
          "SELECT COUNT(*) FROM discount_tier t LEFT JOIN supplier_offer o"
          " ON o.offer_id=t.offer_id WHERE o.offer_id IS NULL")
    check("evidence_references_valid_offer",
          "SELECT COUNT(*) FROM offer_evidence e LEFT JOIN supplier_offer o"
          " ON o.offer_id=e.offer_id WHERE o.offer_id IS NULL")
    check("unresolved_uom_never_eligible",
          "SELECT COUNT(*) FROM decision_ready WHERE error_state='UOM_UNRESOLVED'"
          " AND overall_eligible=1")
    check("coverage_offer_lte_mapped",
          "SELECT COUNT(*) FROM coverage WHERE offer_received=1"
          " AND supplier_product_mapping_exists=0")
    conn.close()
    return out


def reset_and_refresh(seed: int | None = None) -> dict:
    """Rebuild the database. seed=None keeps the golden dataset; pass an int
    for a fresh deal (names, prices, RFx title vary; IDs and counts hold)."""
    from app import seed_data as _seed
    if seed is None:
        seed = _seed.SEED
    return reset_db(_seed.build(seed))


if __name__ == "__main__":
    ds = refresh()
    conn = get_conn()
    for t in ("supplier_offer", "decision_ready", "coverage", "award_decision"):
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n} rows")
    q = conn.execute("SELECT COUNT(*) FROM decision_ready WHERE overall_eligible=1"
                     ).fetchone()[0]
    print(f"eligible offers: {q}")
    conn.close()