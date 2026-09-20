# Aerchain Kill-the-Quote — live demo script (~12 min)

Golden state: 131 offers, 80 eligible, 28 of 30 lines awarded. Mode: offline.
Reset first: Settings → Factory reset (or `POST /api/system/factory-reset`).

## 1. The mess we're killing (1 min) — Ingestion tab
- 7 artifacts: 3 xlsx grids, 2 PDFs, 1 rate-card photo, 1 email. None follows a template.
- Point at SUP-004's photo: real Tesseract OCR, 17/18 rows, 2 genuinely unresolved.
- Upload your own file live (phone photo welcome) → parsed, matched, flagged.

## 2. Talk an RFx into existence (1 min) — RFx tab + AerBot
- RFx tab → draft form (or ask AerBot: "draft an RFx for MRO spares: Item-006 x 20000").
- Stress: drafts are planning records — DRAFT badge, no offers, no award.

## 3. Side-by-side truth (2 min) — Comparison tab
- Filter RF07: SUP-001 ₹11.28 vs the pack. Click a row → full waterfall drawer.
- Toggle "Eligible only": watch ineligible rows vanish with reasons attached.

## 4. Ask AerBot (3 min) — AerBot tab
- "Give me a full bulk analysis of all lines" (one brief call, ~28 lines).
- "Show me the recommended award split" (verbatim engine summary + chart).
- "Why wasn't the cheapest supplier awarded on several lines?"
- "What if SUP-002 offered 5% additional discount?"
- "Exclude SUP-007 from the award" (condition set conversationally).

## 5. Buyer conditions (2 min) — Award tab
- Type: `no supplier more than 30%` → split reshapes live (SUP-002 enters).
- Verdict hero: ₹2.98 Cr total, ₹12.3 L saved vs average, 9 close calls.
- Open a close call (<3% margin) → runner-up breathing down the winner.

## 6. Trust (2 min) — Trust tab + promote
- Every uncertain row + the source file behind every figure.
- Promote the uploaded file (buyer-confirmed lead/validity) → award recomputed.
- Close: "cheapest never wins by itself — eligibility gates, evidence, and your
  conditions decide. The ₹4-crore decision is traceable to pixels."

## Kill lines (if challenged)
- "Is the LLM doing math?" → No: tools compute, model copies verbatim; invented
  ₹ figures are rejected and retried (grounding guards, tested).
- "What if OCR misreads?" → Show the unresolved flags + LOW confidence; nothing
  silently passes.
- "Our data?" → Upload path + promote; golden set untouched.
