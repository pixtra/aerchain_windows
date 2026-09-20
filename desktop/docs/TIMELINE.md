# Build Timeline — Aerchain "Kill the Quote Spreadsheet" MVP

Decision date: **2026-09-18** · Base currency: **INR** · Scope: single RFx,
deterministic engines, trust layer, aerbot, web UI.

## Phase 0 — Foundations (2 days)
- Requirements + dependency pinning (fastapi, uvicorn, pydantic, openpyxl,
  reportlab, pypdf, Pillow, httpx, pytest).
- Golden dataset generator (**50 SKUs, 8 suppliers, 249 supplier products,
  30 RFx lines, 131 offers, 126 discount tiers, 131 evidence rows, 40 survey
  responses**) — deterministic, re-seedable.
- Domain model (16 entities) and SQLite storage schema.

## Phase 1 — Normalization & calculation engines (3 days)
| Engine | Responsibility | Status |
|---|---|---|
| FX | quote currency → INR at active rates (USD 86.50, EUR 93.20, GBP 108.60) | ✅ |
| UOM / pack | buyer units per supplier unit, master→quote precedence, conflict flag | ✅ |
| Discount | flat % / qty-tier % / flat amount, tier-boundary normalization | ✅ |
| Freight | per-unit allocation for EXTRA_PER_SHIPMENT + INCLUDED | ✅ |
| Financing | Net-term benefit at 12% p.a. vs 30-day baseline | ✅ |
| Economics | effective cost = price − discount + freight − financing | ✅ |
| Eligibility | MOQ, lead time, quality, validity, mapping gates | ✅ |

## Phase 2 — Decision-ready & pipeline (2 days)
- `build_decision_ready` assembles 131 records with full provenance
  (source file, location, text, confidence), `verification_status=CALCULATED`.
- Coverage table (240 rows), unresolved UOM/FX states preserved.
- Baseline award: cheapest **eligible** offer per line (28/30 lines; L29/L30
  unquoted). No hardcoding — every figure recomputes from the seed.

## Phase 3 — Trust & evidence (2 days)
- Messy raw artifacts generated (xlsx grids, PDF text, email, rate-card image)
  mirroring the golden offers 1:1.
- Extraction harness parses all artifact types with real engines (openpyxl,
  pypdf, regex, **Tesseract OCR for images — no simulated OCR**). Text
  artifacts re-extract exactly; the image recovers ~17/18 rows with genuine
  misreads surfaced as unresolved, not silently passed.
- Upload path: POST /api/ingest/upload accepts your own xlsx/pdf/image/email,
  runs the same real extractors, matches rows to the product master and stores
  them with honest UNRESOLVED flags (Ingestion tab → "Upload your own file").
- Uncertainties surfaced: LOW/MEDIUM confidence, UOM_UNRESOLVED, review flags.

## Phase 4 — AerBot (3 days)
- Real-model tool-calling agent: a configured LLM (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `OLLAMA_HOST`, or any OpenAI-compatible `KTQ_LLM_URL`)
  plans tool calls over the decision-ready engines and writes the narrative.
- Tool output is serialized to exact figures; the model never performs
  arithmetic, and only evidence the tools returned can appear in an answer
  (invented evidence is dropped). No provider → 503, never canned answers.
- Answers expose assumptions, exclusions, uncertainties, evidence chain.

## Phase 5 — API & UI (2 days)
- FastAPI: rfx, lines, offers, suppliers, comparison, coverage,
  uncertainties, scenarios, award, aerbot, CSV exports, re-seed.
- Dashboard (Overview / RFx / Ingestion / Comparison / AerBot / Scenarios /
  Award / Trust).

## Phase 6 — QA & hardening (2 days)
- 17 golden regression / engine / pipeline / aerbot / extraction tests green.
- Endpoints + UI end-to-end verified.

**Total estimate: ~16 engineering days** for one engineer; 10–11 days with two
(stack: engines in parallel with UI/API).

## What shipped vs. spec
| Requirement | Delivered |
|---|---|
| Extract from multi-format quotes | ✅ harness over xlsx/pdf/image/email |
| Normalize currency & UOM | ✅ deterministic engines + rate table |
| Line-level comparison | ✅ ranked effective-cost table |
| Scenario / what-if | ✅ recalc endpoint + aerbot |
| Award recommendation | ✅ cheapest eligible per line + share caps |
| Traceability & uncertainty | ✅ evidence chain + review flags |
| AerBot with tools | ✅ model agent (function calling) → tools → grounded explanation |