"""FastAPI app for the Aerchain Kill-the-Quote MVP.

Endpoints:
  GET  /api/health
  GET  /api/rfx                          RFx overview + KPIs
  GET  /api/lines                        all RFx lines
  GET  /api/offers?line=&eligible=1      decision-ready offers
  GET  /api/offers/{offer_id}            single offer + calculation
  GET  /api/offers/{offer_id}/calculation  step-by-step economics
  GET  /api/offers/{offer_id}/evidence   evidence chain
  GET  /api/suppliers                    supplier list + offer/eligible counts
  GET  /api/suppliers/{supplier_id}/offers
  GET  /api/comparison                   per-line ranking
  GET  /api/coverage                     coverage table
  GET  /api/uncertainties                review/uncertain rows
  POST /api/award                        run an award scenario
  POST /api/scenarios/run                cost what-if scenario
  POST /api/aerbot/ask                  aerbot question -> structured answer
  GET  /api/aerbot/suggestions          canned demo questions
  GET  /api/export/{table}               CSV export (offers, award, coverage, raw)
  POST /api/system/reset                re-seed and rebuild the DB
"""
from __future__ import annotations

import dataclasses
import io
import csv
import os

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                                StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import pipeline
from app.aerbot import answer as aerbot_answer
from app.domain.models import AwardDecision, Scenario

app = FastAPI(title="Aerchain Kill-the-Quote", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:8000", "http://127.0.0.1:8000",
                                   "http://localhost:8611", "http://127.0.0.1:8611"],
    allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------- access gate
import base64 as _b64
import hashlib as _hl
import hmac as _hmac
import secrets as _secrets
import time as _time

_SERVER_SECRET = _secrets.token_hex(32)  # per boot: restarts log everyone out
AUTH_COOKIE = "ktq_auth"
AUTH_TTL = 30 * 24 * 3600
_AUTH_OPEN = ("/api/health", "/login", "/favicon.ico",
              "/api/auth/login", "/api/auth/logout")


def _gate_password() -> str:
    from app.aerbot.llm import _maybe_reload_env
    _maybe_reload_env()
    return os.environ.get("KTQ_APP_PASSWORD", "")


def _sign(ts: str) -> str:
    return _hmac.new(_SERVER_SECRET.encode(), ts.encode(),
                     _hl.sha256).hexdigest()


def _session_valid(cookie: str | None) -> bool:
    if not cookie or "." not in cookie:
        return False
    ts, _, sig = cookie.partition(".")
    if not ts.isdigit() or not _hmac.compare_digest(_sign(ts), sig):
        return False
    return int(_time.time()) - int(ts) < AUTH_TTL


@app.middleware("http")
async def _access_gate(request, call_next):
    if not _gate_password() or request.url.path in _AUTH_OPEN:
        return await call_next(request)
    if _session_valid(request.cookies.get(AUTH_COOKIE)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "login required"}, status_code=401)
    return RedirectResponse(f"/login?next={request.url.path}", status_code=302)


def audit(event: str, payload: dict):
    """Append-only audit trail: model Q&A, promotions, awards. §67."""
    import json
    from datetime import datetime, timezone
    try:
        with open("data/audit.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "event": event, **payload},
                                ensure_ascii=False) + "\n")
    except OSError:
        pass


@app.on_event("startup")
def startup_validation():
    """§51 gates run on every boot; failures are logged, never silent."""
    import logging
    try:
        bad = [c for c in pipeline.validate() if not c["ok"]]
        if bad:
            logging.getLogger("uvicorn").warning("data-quality gates failing: %s", bad)
    except Exception as e:  # noqa: BLE001 — boot must survive a broken DB
        logging.getLogger("uvicorn").warning("validation skipped: %s", e)


# ------------------------------------------------------------------ schemas
class Question(BaseModel):
    question: str = Field(min_length=2, max_length=400)
    session_id: str = Field(default="default", max_length=64)


class ResetRequest(BaseModel):
    seed: int | None = None


class SessionOnly(BaseModel):
    session_id: str = Field(default="default", max_length=64)


# conversation memory: session_id -> [{role, content}] (text only, capped).
# In-process and prototype-simple: resets on server restart.
SESSIONS: dict[str, list] = {}


class ScenarioRequest(BaseModel):
    scenario_name: str = "Ad-hoc scenario"
    additional_discounts: dict[str, float] = {}
    supplier_exclusions: list[str] = []
    award_strategy: str = "LINE_LEVEL_SPLIT"
    max_supplier_share: float | None = None
    min_qualified_suppliers: int | None = None


class AwardRequest(BaseModel):
    scenario_id: str = "SCN-ADHOC"
    scenario_name: str = "Recommended line-level split"
    award_strategy: str = "LINE_LEVEL_SPLIT"
    max_supplier_share: float | None = None
    min_qualified_suppliers: int | None = None
    supplier_exclusions: list[str] = []


# ------------------------------------------------------------------- health
@app.get("/api/health")
def health():
    return {"status": "ok", "app": "aerchain-ktq", "build": "groq-only"}


@app.post("/api/system/reset")
def system_reset(req: ResetRequest | None = None):
    import random as _random
    seed = (req.seed if req and req.seed is not None
            else _random.SystemRandom().randint(0, 999999))
    pipeline.reset_and_refresh(seed)
    audit("system.reset", {"seed": seed})
    return {"status": "rebuilt", "seed": seed}


# ---------------------------------------------------------------------- rfx
@app.get("/api/rfx")
def rfx_summary():
    from app.aerbot.tools import get_rfx_summary
    return get_rfx_summary()


@app.get("/api/lines")
def lines():
    from app.database import get_conn
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM rfx_line ORDER BY line_number")]
    conn.close()
    return rows


@app.get("/api/suppliers")
def suppliers():
    from app.database import get_conn
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("""
        SELECT s.supplier_id, s.supplier_name, s.default_currency AS currency, s.location AS country,
               COUNT(d.offer_id) AS offers,
               SUM(CASE WHEN d.overall_eligible=1 THEN 1 ELSE 0 END) AS eligible,
               s.default_lead_time_days
        FROM supplier s
        LEFT JOIN decision_ready d ON d.supplier_id = s.supplier_id
        GROUP BY s.supplier_id ORDER BY s.supplier_id""")]
    conn.close()
    return rows


@app.get("/api/suppliers/{supplier_id}/offers")
def supplier_offers(supplier_id: str):
    from app.aerbot.tools import get_supplier_offers
    rows = get_supplier_offers(supplier_id)
    if not rows:
        raise HTTPException(404, f"no offers for {supplier_id}")
    return rows


# -------------------------------------------------------------------- offers
@app.get("/api/offers")
def offers(line: int | None = None, eligible: int = Query(0, ge=0, le=1),
           supplier: str | None = None, limit: int = Query(500, ge=1, le=5000)):
    from app.aerbot.tools import get_line_comparison
    rows = get_line_comparison(line_number=line,
                               eligible_only=bool(eligible), limit=limit)
    if supplier:
        rows = [r for r in rows if r["supplier_id"] == supplier]
    return rows


@app.get("/api/offers/{offer_id}")
def offer_detail(offer_id: str):
    from app.aerbot.tools import evidence_chain, get_offer_calculation
    calc = get_offer_calculation(offer_id)
    if not calc:
        raise HTTPException(404, f"unknown offer {offer_id}")
    chain = evidence_chain(offer_id)
    return {"calculation": chain["calculation"], "evidence": chain["evidence"]}


@app.get("/api/offers/{offer_id}/calculation")
def offer_calculation(offer_id: str):
    from app.aerbot.tools import get_offer_calculation
    calc = get_offer_calculation(offer_id)
    if not calc:
        raise HTTPException(404, f"unknown offer {offer_id}")
    steps = [
        ("Quoted price", f"{calc['quoted_currency']} {calc['quoted_unit_price']} / {calc['quoted_uom']}"),
        ("FX rate", calc["fx_rate_applied"]),
        ("UOM conversion", calc["uom_conversion_factor"]),
        ("Normalized unit price", calc["normalized_unit_price"]),
        ("Discount benefit", calc["discount_benefit"]),
        ("Net material price", calc["net_material_price"]),
        ("Allocated freight", calc["allocated_freight"]),
        ("Financing benefit", calc["financing_benefit"]),
        ("Effective economic cost", calc["effective_economic_cost"]),
    ]
    return {"offer_id": offer_id, "supplier": calc["supplier"],
            "line_number": calc["line_number"], "steps": steps,
            "eligibility": calc["eligibility_reason"] or "ELIGIBLE"}


@app.get("/api/offers/{offer_id}/evidence")
def offer_evidence(offer_id: str):
    from app.aerbot.tools import get_offer_evidence
    rows = get_offer_evidence(offer_id)
    if not rows:
        raise HTTPException(404, f"no evidence for {offer_id}")
    return rows


# ---------------------------------------------------------------- comparison
@app.get("/api/comparison")
def comparison(line: int | None = None, eligible_only: int = 0,
               limit: int = Query(500, ge=1, le=5000)):
    from app.aerbot.tools import get_line_comparison
    return get_line_comparison(line_number=line, eligible_only=bool(eligible_only),
                               limit=limit)


@app.get("/api/coverage")
def coverage():
    from app.aerbot.tools import get_coverage
    return get_coverage()


@app.get("/api/uncertainties")
def uncertainties():
    from app.aerbot.tools import get_uncertainties
    return get_uncertainties()


# --------------------------------------------------------------------- ingest
@app.post("/api/ingest/upload")
async def ingest_upload(file: UploadFile = File(...),
                        supplier_id: str | None = Form(None),
                        ocr_lang: str | None = Form(None)):
    """Accept a real supplier file, extract it with the real engines
    (Tesseract OCR for images) and store parsed rows with honest match flags.
    supplier_id optionally scopes matching to that supplier's catalogue."""
    import os
    from app.services import ingest
    source_type = ingest.classify(file.filename or "")
    if not source_type:
        raise HTTPException(400, "unsupported file type; use xlsx, pdf, docx, jpg, png, txt or eml")
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "file too large (25 MB max)")
    if ocr_lang:
        os.environ["KTQ_OCR_LANG"] = "+".join(
            c for c in ocr_lang.replace(",", "+").split("+") if c.strip()) or "eng"
    path = ingest.save_upload(file.filename, content)
    try:
        rows, engine = ingest.extract_upload(path, source_type)
    except Exception as e:
        raise HTTPException(502, f"extraction failed: {e}")
    rows = ingest.match_rows(rows, supplier_id=supplier_id)
    try:
        summary = ingest.store_upload(file.filename, path, source_type, rows,
                                      engine, content)
    except ValueError as e:
        raise HTTPException(409, detail=str(e))
    summary["rows_preview"] = rows[:20]
    return summary


class PromoteRequest(BaseModel):
    payment_days: int = 30
    freight_basis: str = "INCLUDED"
    freight_amount: float = 0.0
    default_valid_until: str | None = None
    default_lead_days: int | None = None


@app.post("/api/ingest/uploads/{file_id}/promote")
def ingest_promote(file_id: int, req: PromoteRequest):
    """Promote buyer-confirmed upload rows into the live decision layer with
    real engine economics; award + coverage are recomputed over everything."""
    from app.services import ingest
    try:
        res = ingest.promote_upload(
            file_id, payment_days=req.payment_days,
            freight_basis=req.freight_basis, freight_amount=req.freight_amount,
            default_valid_until=req.default_valid_until,
            default_lead_days=req.default_lead_days)
        audit("ingest.promote", {"file_id": file_id,
                                 "promoted": res.get("promoted"),
                                 "eligible": res.get("eligible"),
                                 "assumptions": res.get("assumptions")})
        return res
    except ValueError as e:
        raise HTTPException(404, detail=str(e))


@app.get("/api/policy")
def policy():
    """Decision policy + FX assumptions behind every computed figure."""
    from app.database import get_conn
    conn = get_conn()
    pol = dict(conn.execute("SELECT * FROM policy LIMIT 1").fetchone())
    fx = [dict(r) for r in conn.execute("SELECT * FROM fx_rate")]
    conn.close()
    return {"policy": pol, "fx_rates": fx}


# ------------------------------------------------------------------- drafts
class DraftRequest(BaseModel):
    name: str = ""
    category: str = ""
    lines_text: str = ""
    terms: str = ""
    deadline: str = ""
    new_skus: list[dict] | None = None


@app.get("/api/rfx/drafts")
def drafts_list():
    from app.services import drafts
    return drafts.list_drafts()


@app.post("/api/rfx/drafts", status_code=201)
def drafts_add(req: DraftRequest):
    from app.services import drafts
    try:
        return drafts.create_draft(req.name, req.category, req.lines_text,
                                   req.terms, req.deadline, source="ui",
                                   new_skus=req.new_skus)
    except drafts.NeedConfirm as e:
        raise HTTPException(409, detail={"error": str(e),
                                         "unknown_skus": e.unknown,
                                         "parsed_ok": e.parsed_ok})
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.get("/api/rfx/drafts/{draft_id}")
def drafts_get(draft_id: str):
    from app.services import drafts
    d = drafts.get_draft(draft_id)
    if not d:
        raise HTTPException(404, f"no draft {draft_id}")
    return d


@app.delete("/api/rfx/drafts/{draft_id}")
def drafts_delete(draft_id: str):
    from app.services import drafts
    if not drafts.delete_draft(draft_id):
        raise HTTPException(404, f"no draft {draft_id}")
    return {"deleted": draft_id}


@app.get("/api/brief")
def full_brief():
    """Deterministic whole-RFx brief (no model, zero tokens): per-line
    cheapest eligible offers, coverage gaps, uncertainties, conditions."""
    from app.aerbot.tools import get_full_brief
    return get_full_brief()


# ------------------------------------------------------------------ settings
class ProviderSettingsRequest(BaseModel):
    groq_keys_add: str | None = None
    groq_keys_remove: int | None = None
    groq_keys_order: list[int] | None = None
    ocr_lang: str | None = None


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse("static/login.html")


class LoginRequest(BaseModel):
    password: str = ""
    next: str = "/"


@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    expected = _gate_password()
    if not expected:
        raise HTTPException(400, "no access password is set")
    if not _hmac.compare_digest(req.password, expected):
        raise HTTPException(401, "wrong password")
    ts = str(int(_time.time()))
    resp = JSONResponse({"ok": True, "next": req.next or "/"})
    resp.set_cookie(AUTH_COOKIE, f"{ts}.{_sign(ts)}", max_age=AUTH_TTL,
                    httponly=True, samesite="lax")
    return resp


@app.post("/api/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE)
    return resp


class AccessPasswordRequest(BaseModel):
    password: str = ""


@app.post("/api/settings/access-password")
def settings_access_password(req: AccessPasswordRequest):
    """Set/change the gate password (authed callers only, by construction).
    Empty disables the gate. Persists to .env and propagates like other keys."""
    from app.aerbot.llm import save_env_values
    value = (req.password or "").strip()
    if value and len(value) < 4:
        raise HTTPException(422, "password must be at least 4 characters")
    if value:
        os.environ["KTQ_APP_PASSWORD"] = value
        save_env_values({"KTQ_APP_PASSWORD": value})
    else:
        os.environ.pop("KTQ_APP_PASSWORD", None)
        save_env_values({"KTQ_APP_PASSWORD": ""})
    return {"gate": bool(value)}


@app.get("/api/settings/access")
def settings_access():
    return {"gate": bool(_gate_password())}


@app.get("/api/settings/provider")
def settings_provider_get():
    from app.aerbot.llm import provider_settings
    return provider_settings()


@app.post("/api/settings/provider")
def settings_provider_set(req: ProviderSettingsRequest):
    from app.aerbot.llm import set_provider_settings
    try:
        return set_provider_settings(groq_keys_add=req.groq_keys_add,
                                     groq_keys_remove=req.groq_keys_remove,
                                     groq_keys_order=req.groq_keys_order,
                                     ocr_lang=req.ocr_lang)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.post("/api/settings/provider/test")
def settings_provider_test():
    """One tiny live call through the active chain: proves the mode works."""
    import time
    from app.aerbot.llm import LAST_PROVIDER, client_chat
    t0 = time.time()
    try:
        r = client_chat("Reply with exactly: PROVIDER-OK",
                        [{"role": "user", "content": "Reply with exactly: PROVIDER-OK"}],
                        [])
    except Exception as e:
        raise HTTPException(502, detail=f"provider test failed: {e}")
    return {"ok": (r.content or "").strip() == "PROVIDER-OK",
            "serving": LAST_PROVIDER["name"],
            "fell_back": LAST_PROVIDER["fell_back"],
            "ms": int((time.time() - t0) * 1000)}


@app.get("/api/settings/stats")
def settings_stats():
    """Dataset + usage counts for the Settings page."""
    import os
    from app.database import get_conn
    conn = get_conn()
    try:
        q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        uploads_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "../data/uploads"))
        files = len([f for f in os.listdir(uploads_dir)
                     if not f.startswith(".")]) if os.path.isdir(uploads_dir) else 0
        return {
            "offers": q("SELECT COUNT(*) FROM decision_ready"),
            "eligible": q("SELECT COUNT(*) FROM decision_ready WHERE overall_eligible=1"),
            "lines_awarded": q("SELECT COUNT(*) FROM award_decision"),
            "uploads": q("SELECT COUNT(*) FROM uploaded_file"),
            "upload_files_on_disk": files,
            "conditions": q("SELECT COUNT(*) FROM buyer_condition WHERE active=1"),
        }
    finally:
        conn.close()


@app.post("/api/system/factory-reset")
def factory_reset():
    """Golden rebuild + wipe EVERYTHING the user created: uploads (rows +
    files), buyer conditions, RFx drafts, and chat memory. Pristine demo
    state. Never touches .env — saved Groq keys survive a reset."""
    import os
    import shutil
    from app.database import get_conn
    pipeline.reset_and_refresh()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM uploaded_offer")
        conn.execute("DELETE FROM uploaded_file")
        conn.execute("DELETE FROM rfx_draft_line")
        conn.execute("DELETE FROM rfx_draft_sku")
        cur = conn.execute("DELETE FROM rfx_draft")
        drafts_removed = cur.rowcount
        cur = conn.execute("DELETE FROM buyer_condition")
        conditions_removed = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    SESSIONS.clear()
    uploads = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/uploads"))
    removed = 0
    if os.path.isdir(uploads):
        for fn in os.listdir(uploads):
            p = os.path.join(uploads, fn)
            if os.path.isfile(p):
                os.remove(p)
                removed += 1
    return {"status": "rebuilt", "uploads_removed": removed,
            "conditions_removed": conditions_removed,
            "drafts_removed": drafts_removed}


# ---------------------------------------------------------------- conditions
class ConditionRequest(BaseModel):
    text: str = Field(min_length=2, max_length=300)


class ConditionToggle(BaseModel):
    active: bool


@app.get("/api/conditions")
def conditions():
    from app.services import conditions as cond
    return cond.list_conditions()


@app.post("/api/conditions", status_code=201)
def conditions_add(req: ConditionRequest):
    from app.services import conditions as cond
    try:
        return cond.add_condition(req.text, source="ui")
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.patch("/api/conditions/{cid}")
def conditions_toggle(cid: int, req: ConditionToggle):
    from app.services import conditions as cond
    if not cond.set_active(cid, req.active):
        raise HTTPException(404, f"no condition {cid}")
    return {"condition_id": cid, "active": req.active}


@app.delete("/api/conditions/{cid}")
def conditions_delete(cid: int):
    from app.services import conditions as cond
    if not cond.delete_condition(cid):
        raise HTTPException(404, f"no condition {cid}")
    return {"deleted": cid}


@app.get("/api/ingest/uploads")
def ingest_uploads():
    from app.services import ingest
    return ingest.list_uploads()


@app.get("/api/ingest/uploads/{file_id}")
def ingest_upload_rows(file_id: int):
    from app.services import ingest
    rows = ingest.get_upload_rows(file_id)
    if not rows:
        raise HTTPException(404, f"no upload {file_id}")
    return rows


# ------------------------------------------------------------- scenario/award
@app.post("/api/scenarios/run")
def run_scenario(req: ScenarioRequest):
    scenario = Scenario(
        scenario_id="SCN-ADHOC", rfx_id="RFX-001",
        scenario_name=req.scenario_name,
        additional_discounts=req.additional_discounts,
        supplier_exclusions=req.supplier_exclusions,
        award_strategy=req.award_strategy,
        max_supplier_share=req.max_supplier_share,
        min_qualified_suppliers=req.min_qualified_suppliers)
    from app.aerbot.tools import run_cost_scenario
    return run_cost_scenario(scenario)


@app.post("/api/award")
def award(req: AwardRequest):
    scenario = Scenario(
        scenario_id=req.scenario_id, rfx_id="RFX-001",
        scenario_name=req.scenario_name,
        award_strategy=req.award_strategy,
        max_supplier_share=req.max_supplier_share,
        min_qualified_suppliers=req.min_qualified_suppliers,
        supplier_exclusions=req.supplier_exclusions)
    from app.aerbot.tools import run_award_scenario
    return run_award_scenario(scenario)


@app.get("/api/award/current")
def award_current():
    scenario = Scenario(
        scenario_id="SCN-AWARD-BASE", rfx_id="RFX-001",
        scenario_name="Recommended line-level split (cheapest eligible per line)",
        award_strategy="LINE_LEVEL_SPLIT")
    from app.aerbot.tools import run_award_scenario
    return run_award_scenario(scenario)


# -------------------------------------------------------------------- aerbot
@app.post("/api/aerbot/ask")
def aerbot(req: Question):
    import time
    from app.aerbot import ModelNotConfigured
    t0 = time.time()
    try:
        hist = SESSIONS.get(req.session_id, [])
        ans = aerbot_answer(req.question, history=hist)
        hist = (hist + [{"role": "user", "content": req.question},
                        {"role": "assistant", "content": ans.get("narrative", "")}])[-12:]
        SESSIONS[req.session_id] = hist
        if len(SESSIONS) > 50:
            SESSIONS.pop(next(iter(SESSIONS)))
        audit("aerbot.ask", {"question": req.question[:200],
                             "intent": ans.get("intent"),
                             "provider": ans.get("provider"),
                             "ms": int((time.time() - t0) * 1000)})
        return ans
    except ModelNotConfigured as e:
        raise HTTPException(503, detail=str(e))
    except Exception as e:
        audit("aerbot.ask.error", {"question": req.question[:200],
                                   "error": str(e)[:200]})
        raise HTTPException(502, detail=f"Aerbot agent failed: {e}")


@app.post("/api/aerbot/forget")
def aerbot_forget(req: SessionOnly):
    """Drop a conversation session (used by Clear chat)."""
    SESSIONS.pop(req.session_id, None)
    return {"forgotten": req.session_id}


@app.get("/api/aerbot/status")
def aerbot_status():
    from app.aerbot import status
    return status()


@app.get("/api/aerbot/suggestions")
def aerbot_suggestions():
    from app.database import get_conn
    conn = get_conn()
    try:
        n_lines = conn.execute("SELECT COUNT(*) FROM rfx_line").fetchone()[0]
        sups = [r[0] for r in conn.execute(
            "SELECT supplier_id FROM supplier ORDER BY supplier_id LIMIT 3")]
    finally:
        conn.close()
    return {"suggestions": [
        "Give me a summary of the RFx",
        f"Who is the cheapest supplier on line 3 of {n_lines}?",
        "Why wasn't the cheapest supplier awarded on several lines?",
        "Which lines have poor coverage?",
        "What are we uncertain about?",
        f"How did you calculate {sups[1]}'s effective cost on line 12?",
        f"What if {sups[1]} offered 5% additional discount?",
        "Show me the recommended award split",
        "Give me a full bulk analysis of all lines",
    ]}


# -------------------------------------------------------------------- export
_EXPORT_TABLES = {"offers": "decision_ready", "award": "award_decision",
                  "coverage": "coverage", "raw": "supplier_offer"}


@app.get("/api/export/{table}")
def export(table: str, format: str = Query("csv", pattern="^(csv|xlsx)$")):
    name = _EXPORT_TABLES.get(table)
    if not name:
        raise HTTPException(404, f"unknown export table: {table}")
    from app.database import get_conn
    conn = get_conn()
    cur = conn.execute(f"SELECT * FROM {name}")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    if format == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = name[:31]
        ws.append(cols)
        for r in rows:
            ws.append(list(r))
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={name}.xlsx"})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={name}.csv"})

# optionally serve the built dashboard
app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)