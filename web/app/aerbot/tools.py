"""Aerbot tools — deterministic executors over the Decision-Ready layer.

The LLM (or rule planner) selects tool + params; these functions compute the
answers. Arithmetic, ranking, filtering live here, never in the LLM.
"""
from __future__ import annotations

import dataclasses
import sqlite3

from app.database import get_conn
from app.domain.enums import BASE_CURRENCY, DEFAULT_DECISION_DATE
from app.domain.models import Scenario
from app.engines.scenario import award_line_level, recalc_with_scenario

_FIELDS = ("decision_record_id, rfx_id, rfx_line_id, line_number, sku_id, "
           "supplier_id, supplier_name, offer_id, supplier_product_id, "
           "supplier_product_code, quoted_description, buyer_uom, "
           "required_quantity, required_lead_time_days, "
           "quality_requirement, quoted_unit_price, quoted_currency, quoted_uom, "
           "quoted_quantity, fx_rate_id, fx_rate_applied, uom_conversion_factor, "
           "uom_conversion_source, normalized_unit_price, discount_rule_type, "
           "applicable_discount_percentage, discount_benefit, net_material_price, "
           "freight_basis, allocated_freight, payment_days, financing_benefit, "
           "effective_economic_cost, moq, lead_time_days, quote_valid_until, "
           "moq_eligible, lead_time_eligible, quality_eligible, "
           "quote_validity_eligible, mapping_eligible, overall_eligible, "
           "eligibility_reason, evidence_id, source_file, source_type, "
           "source_location, source_text, extraction_confidence, "
           "normalization_confidence, verification_status, requires_review, "
           "error_state, error_detail")


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _dr_rows(conn, where="", args=(), order="line_number, effective_economic_cost"):
    sql = f"SELECT {_FIELDS} FROM decision_ready r"
    if where:
        sql += f" WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    return _rows(conn, sql, args)


def get_rfx_summary() -> dict:
    conn = get_conn()
    rfx = dict(conn.execute("SELECT * FROM rfx WHERE rfx_id='RFX-001'").fetchone())
    rfx["line_count"] = conn.execute("SELECT COUNT(*) FROM rfx_line").fetchone()[0]
    rfx["supplier_count"] = conn.execute(
        "SELECT COUNT(*) FROM rfx_supplier WHERE response_status='RESPONDED'").fetchone()[0]
    rfx["offer_count"] = conn.execute("SELECT COUNT(*) FROM decision_ready").fetchone()[0]
    rfx["eligible_count"] = conn.execute(
        "SELECT COUNT(*) FROM decision_ready WHERE overall_eligible=1").fetchone()[0]
    rfx["review_count"] = conn.execute(
        "SELECT COUNT(*) FROM decision_ready WHERE requires_review=1").fetchone()[0]
    rfx["base_currency"] = str(BASE_CURRENCY.value)
    rfx["decision_date"] = DEFAULT_DECISION_DATE
    conn.close()
    return rfx


def get_line_comparison(line_number: int | None = None, eligible_only: bool = False,
                        limit: int = 50) -> list[dict]:
    conn = get_conn()
    where, args = "", ()
    if line_number:
        where = "r.line_number = ?"
        args = (line_number,)
    if eligible_only:
        where = f"{where + ' AND ' if where else ''}r.overall_eligible = 1"
    rows = _dr_rows(conn, where, args)
    conn.close()
    ranked = rank_rows(rows)
    return ranked[:limit]


def rank_rows(rows: list[dict]) -> list[dict]:
    """Attach rank per line (ascending effective economic cost)."""
    per_line: dict[int, list] = {}
    for r in rows:
        per_line.setdefault(r["line_number"], []).append(r)
    out = []
    for ln in sorted(per_line):
        cands = sorted(per_line[ln],
                       key=lambda r: (r["effective_economic_cost"] is None,
                                      r["effective_economic_cost"] or 1e18))
        for i, c in enumerate(cands, 1):
            c["line_rank"] = i
            c["line_count"] = len(cands)
        out += cands
    return out


def get_offer_calculation(offer_id: str) -> dict | None:
    conn = get_conn()
    rows = _dr_rows(conn, "r.offer_id = ?", (offer_id,))
    conn.close()
    if not rows:
        return None
    r = rows[0]
    return {
        "offer_id": r["offer_id"], "supplier": r["supplier_name"],
        "line_number": r["line_number"], "sku_id": r["sku_id"],
        "quoted_unit_price": r["quoted_unit_price"],
        "quoted_currency": r["quoted_currency"], "quoted_uom": r["quoted_uom"],
        "quoted_quantity": r["quoted_quantity"],
        "fx_rate_applied": r["fx_rate_applied"],
        "uom_conversion_factor": r["uom_conversion_factor"],
        "uom_conversion_source": r["uom_conversion_source"],
        "normalized_unit_price": r["normalized_unit_price"],
        "discount_rule_type": r["discount_rule_type"],
        "applicable_discount_percentage": r["applicable_discount_percentage"],
        "discount_benefit": r["discount_benefit"],
        "net_material_price": r["net_material_price"],
        "allocated_freight": r["allocated_freight"],
        "freight_basis": r["freight_basis"],
        "payment_days": r["payment_days"],
        "financing_benefit": r["financing_benefit"],
        "effective_economic_cost": r["effective_economic_cost"],
        "overall_eligible": r["overall_eligible"],
        "eligibility_reason": r["eligibility_reason"],
        "base_currency": str(BASE_CURRENCY),
    }


def get_offer_evidence(offer_id: str) -> list[dict]:
    conn = get_conn()
    rows = _rows(conn,
                 "SELECT * FROM offer_evidence WHERE offer_id=? ORDER BY evidence_id",
                 (offer_id,))
    conn.close()
    return rows


def get_supplier_offers(supplier_id: str) -> list[dict]:
    conn = get_conn()
    rows = _dr_rows(conn, "r.supplier_id=?", (supplier_id,))
    conn.close()
    return rows


def get_coverage() -> list[dict]:
    conn = get_conn()
    rows = []
    for r in _rows(conn,
                   "SELECT line_number, sku_id, "
                   "SUM(supplier_product_mapping_exists) mapped, "
                   "SUM(offer_received) offers "
                   "FROM coverage GROUP BY rfx_line_id ORDER BY line_number"):
        mapped, offers = r["mapped"], r["offers"]
        qualified = conn.execute(
            "SELECT COUNT(*) FROM decision_ready d WHERE d.line_number=? AND d.overall_eligible=1",
            (r["line_number"],)).fetchone()[0]
        status, action = _coverage_label(mapped, offers, qualified)
        rows.append({"line_number": r["line_number"], "sku_id": r["sku_id"],
                     "mapped_supplier_count": mapped, "offer_count": offers,
                     "qualified_offer_count": qualified,
                     "coverage_status": status, "buyer_action": action})
    conn.close()
    return rows


def _coverage_label(mapped, offers, qualified):
    from app.domain.enums import CoverageStatus
    if mapped == 0 and offers == 0:
        return CoverageStatus.NO_COVERAGE.value, "No mapped supplier — re-scope the line"
    if offers == 0:
        return CoverageStatus.NO_QUOTE.value, "Invited suppliers did not quote"
    if qualified < 1:
        return CoverageStatus.PARTIAL.value, "Offers exist but none qualified — review"
    if offers == 1 or qualified == 1:
        return CoverageStatus.PARTIAL.value, "Single qualified supplier — confirm competition"
    return CoverageStatus.COMPETITIVE.value, "Competitive"


def get_uncertainties() -> list[dict]:
    conn = get_conn()
    rows = _dr_rows(
        conn,
        "r.requires_review=1 OR r.error_state IS NOT NULL OR "
        "r.extraction_confidence IN ('LOW','MEDIUM')",
        order="r.line_number",
    )
    conn.close()
    return rows


def get_cheapest_per_line(eligible_only: bool = True, constraint=None) -> list[dict]:
    conn = get_conn()
    where, args = "", ()
    if eligible_only:
        where = "r.overall_eligible=1"
    rows = _dr_rows(conn, where, args)
    conn.close()
    rows = rank_rows(rows)
    best = {}
    for r in rows:
        if constraint and not _meets_constraint(r, constraint):
            continue
        cur = best.get(r["line_number"])
        if cur is None or (r["line_rank"] and r["line_rank"] < cur["line_rank"]):
            best[r["line_number"]] = r
    return sorted(best.values(), key=lambda r: r["line_number"])


def _meets_constraint(r: dict, constraint: str) -> bool:
    c = (constraint or "").lower()
    if "quality" in c:
        return bool(r["quality_eligible"])
    if "moq" in c:
        return bool(r["moq_eligible"])
    if "lead" in c or "delivery" in c:
        return bool(r["lead_time_eligible"])
    return True


def run_cost_scenario(scenario: Scenario) -> dict:
    conn = get_conn()
    recs = _dr_objects(conn)
    policy = _obj(_load_policy(conn))
    conn.close()
    updated = recalc_with_scenario(recs, scenario, policy)
    out = []
    for r in updated:
        d = dataclasses.asdict(r)
        out.append({"supplier_id": d["supplier_id"],
                    "line_number": d["line_number"],
                    "supplier_name": d["supplier_name"],
                    "normalized_unit_price": d["normalized_unit_price"],
                    "discount_benefit": d["discount_benefit"],
                    "net_material_price": d["net_material_price"],
                    "financing_benefit": d["financing_benefit"],
                    "effective_economic_cost": d["effective_economic_cost"],
                    "overall_eligible": d["overall_eligible"]})
    return {"scenario": scenario.scenario_name, "records": out[::-1][:160]}


def _dr_objects(conn) -> list:
    from app.domain.models import DecisionReadyRecord
    objs = []
    for row in _rows(conn, f"SELECT {_FIELDS} FROM decision_ready ORDER BY line_number"):
        objs.append(DecisionReadyRecord(**row))
    return objs


def _load_policy(conn) -> dict:
    d = dict(conn.execute("SELECT * FROM policy LIMIT 1").fetchone())
    return d


def _obj(d: dict):
    from app.domain.models import Policy
    d = dict(d)
    for k in ("hard_moq_constraint", "hard_lead_time_constraint",
              "quality_required_for_award", "expired_quote_ineligible"):
        d[k] = bool(d[k])
    return Policy(**d)


def run_award_scenario(scenario: Scenario) -> dict:
    from app.services.conditions import filter_candidates, list_conditions
    conn = get_conn()
    recs = _dr_objects(conn)
    policy = _obj(_load_policy(conn))
    conds = list_conditions(active_only=True)
    recs, applied = filter_candidates(recs, conds)
    for sup in getattr(scenario, "supplier_exclusions", None) or []:
        if sup not in [c.get("target") for c in conds]:
            recs = [r for r in recs if r.supplier_id != sup]
            applied = applied + [f"exclude {sup}"]
    share_cap = getattr(scenario, "max_supplier_share", None)
    for c in conds:
        if c["kind"] == "MAX_SUPPLIER_SHARE" and c.get("value_num"):
            share_cap = c["value_num"] if share_cap is None else min(share_cap, c["value_num"])
            if f"max {c['value_num']:g}% share per supplier" not in applied:
                applied = applied + [f"max {c['value_num']:g}% share per supplier"]
    min_q = getattr(scenario, "min_qualified_suppliers", None)
    for c in conds:
        if c["kind"] == "MIN_SUPPLIERS" and c.get("value_num"):
            need = int(c["value_num"])
            min_q = need if min_q is None else max(min_q, need)
            if f"at least {need} suppliers in the split" not in applied:
                applied = applied + [f"at least {need} suppliers in the split"]
    awards = award_line_level(recs, scenario, policy,
                              max_share=share_cap, min_qualified=min_q)
    conn.close()
    share = {}
    for a in awards:
        share[a.supplier_id] = share.get(a.supplier_id, 0) + 1
    totals = ",".join(f"{k} {v}" for k, v in sorted(share.items(), key=lambda x: -x[1]))
    total_lines = conn_line_count()
    summary = (f"{len(awards)} of {total_lines} RFx lines awarded. "
               f"Lines awarded per supplier: {totals}.")
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.scenario_name,
        "awards": [dataclasses.asdict(a) for a in awards],
        "supplier_share": {k: v for k, v in sorted(share.items(), key=lambda x: -x[1])},
        "awards_by_supplier": {k: v for k, v in sorted(share.items(), key=lambda x: -x[1])},
        "share_is_count_of_awarded_lines": True,
        "summary": summary,
        "line_count": len(awards),
        "conditions_applied": applied,
    }


def conn_line_count() -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM rfx_line").fetchone()[0]
    conn.close()
    return n


def get_buyer_conditions() -> list[dict]:
    from app.services.conditions import list_conditions
    return list_conditions()


def set_buyer_condition(text: str) -> dict:
    from app.services.conditions import add_condition
    try:
        return {"ok": True, **add_condition(text, source="aerbot")}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def create_rfx_draft(args: dict) -> dict:
    from app.services import drafts
    try:
        return {"ok": True, **drafts.create_draft(
            args.get("name", ""), args.get("category", ""),
            args.get("lines_text", ""), args.get("terms", ""),
            args.get("deadline", ""), source="aerbot",
            new_skus=args.get("new_skus"))}
    except drafts.NeedConfirm as e:
        return {"ok": False, "needs_confirm": True,
                "unknown_skus": e.unknown, "parsed_ok": e.parsed_ok,
                "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def list_rfx_drafts() -> list[dict]:
    from app.services import drafts
    return drafts.list_drafts()


def get_full_brief() -> dict:
    """Whole-RFx brief in ONE payload for bulk questions: per-line winners,
    coverage gaps, award summary, uncertainty counts, active conditions.
    Compact by design — one tool call replaces up to 30 per-line calls."""
    comp = get_line_comparison(eligible_only=False, limit=5000)
    elig = {r["line_number"]: r for r in
            get_line_comparison(eligible_only=True, limit=5000)
            if r.get("line_rank") == 1}
    winners = {}
    for ln, r in elig.items():
        winners[ln] = {
            "sku": r.get("sku_id"),
            "winner": r.get("supplier_id"),
            "winner_name": r.get("supplier_name"),
            "cost": r.get("effective_economic_cost"),
            "offer": r.get("offer_id"),
        }
    per_line = {}
    for r in comp:
        ln = r["line_number"]
        d = per_line.setdefault(ln, {"offers": 0, "eligible": 0})
        d["offers"] += 1
        d["eligible"] += 1 if r.get("overall_eligible") else 0
    lines = []
    for ln in sorted(set(list(winners) + list(per_line))):
        w = winners.get(ln, {})
        lines.append({"line": ln, "sku": w.get("sku"),
                      "cheapest": w.get("winner"),
                      "cheapest_name": w.get("winner_name"),
                      "cheapest_cost": w.get("cost"),
                      "offers": per_line.get(ln, {}).get("offers", 0),
                      "eligible": per_line.get(ln, {}).get("eligible", 0)})
    gaps = [c for c in get_coverage() if c.get("coverage_status") != "COMPETITIVE"]
    unc = get_uncertainties()
    summary = get_rfx_summary()
    decision_date = str(summary.get("decision_date") or "2026-09-18")
    expired: dict[str, int] = {}
    ineligible_reasons: dict[str, int] = {}
    for r in comp:
        valid_until = r.get("quote_valid_until") or ""
        if valid_until and valid_until < decision_date:
            expired[r["supplier_id"]] = expired.get(r["supplier_id"], 0) + 1
        if not r.get("overall_eligible"):
            reason = (r.get("eligibility_reason") or "unknown").split(":")[0]
            ineligible_reasons[reason] = ineligible_reasons.get(reason, 0) + 1
    _qty = {r["line_number"]: r.get("required_quantity") or 0 for r in comp}
    per_line_value = {}
    for ln, w in winners.items():
        per_line_value[ln] = (w.get("cost") or 0) * _qty.get(ln, 0)
    award_total = round(sum(per_line_value.values()), 4)
    by_supplier_value: dict[str, float] = {}
    for ln, w in winners.items():
        by_supplier_value[w["winner"]] = round(
            by_supplier_value.get(w["winner"], 0) + per_line_value[ln], 4)
    return {
        "summary": (f"{summary.get('offer_count')} offers, "
                    f"{summary.get('eligible_count')} eligible, "
                    f"{summary.get('review_count')} flagged, "
                    f"{len(gaps)} non-competitive lines. "
                    f"Recommended award totals ₹ {award_total} across "
                    f"{len(winners)} lines."),
        "award_total_value": award_total,
        "award_value_by_supplier": by_supplier_value,
        "expired_by_supplier": expired,
        "ineligible_by_reason": ineligible_reasons,
        "lines": lines,
        "gaps": [{"line": g["line_number"], "sku": g["sku_id"],
                  "status": g["coverage_status"],
                  "action": g["buyer_action"]} for g in gaps],
        "uncertain_count": len(unc),
        "conditions": get_buyer_conditions(),
    }


def evidence_chain(offer_id: str) -> dict | None:
    calc = get_offer_calculation(offer_id)
    if not calc:
        return None
    ev = get_offer_evidence(offer_id)
    return {"calculation": calc, "evidence": ev}


def make_cost_scenario(name: str, additional_discounts: dict | None = None,
                       supplier_exclusions: list | None = None) -> Scenario:
    """Deterministic builder — the agent supplies intent/params; no free math."""
    return Scenario(scenario_id="SCN-ADHOC", rfx_id="RFX-001",
                    scenario_name=name or "Ad-hoc what-if",
                    additional_discounts=additional_discounts or {},
                    supplier_exclusions=supplier_exclusions or [],
                    award_strategy="LINE_LEVEL_SPLIT")


def make_award_scenario(scenario_id: str, name: str, max_supplier_share=None,
                        min_qualified_suppliers=None) -> Scenario:
    return Scenario(scenario_id=scenario_id or "SCN-ADHOC", rfx_id="RFX-001",
                    scenario_name=name or "Recommended line-level split",
                    max_supplier_share=max_supplier_share,
                    min_qualified_suppliers=min_qualified_suppliers,
                    award_strategy="LINE_LEVEL_SPLIT")