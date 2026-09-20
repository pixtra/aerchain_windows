# Analyst walkthrough — questions worth asking (with verified answers)

All answers below were produced live by AerBot against the golden dataset
(SEED=73, decision date 2026-09-18, base INR) and cross-checked against SQLite.

## 1. "Give me a summary of the RFx"
131 offers, 80 eligible (61%), 2 flagged, 30 lines, 7 suppliers responded,
SUP-008 silent. *Why ask it: proves the whole funnel in one breath.*

## 2. "Who is the cheapest supplier on line 3?"
SUP-001 at the engine-computed effective cost, ranked by ₹/buyer-unit — not by
quoted price. *Why: quoted price lies (packs, currencies); effective cost doesn't.*

## 3. "Show me the recommended award split"
28 of 30 lines: SUP-001 10, SUP-005 9, SUP-003 8, SUP-004 1. Total ≈ ₹2.98 Cr,
≈ ₹12.3 L below the eligible-average baseline. L29/L30: no quotes, honestly
unawarded. *Why: the money slide.*

## 4. "Why wasn't the cheapest supplier awarded on several lines?"
Because cheapest ≠ eligible: MOQ fails (12), lead fails (56), SUP-006's
CONDITIONAL quality, SUP-007's expired quotes. Each exclusion carries its
reason string. *Why: this is the VP's fourth-day question from the brief.*

## 5. "How did you calculate SUP-002's effective cost on line 12?"
Waterfall: quoted → FX (86.50) → UOM ÷ pack → tier discount → freight/shipment
÷ qty → financing (Net 60 vs 30 baseline) → ₹ effective. Every step cites
source evidence. *Why: earns the ₹4-crore trust.*

## 6. "What if SUP-002 offered 5% additional discount?"
Deterministic recalc across all its lines, delta vs baseline, reranked winners.
*Why: proves scenarios are computed, not narrated.*

## 7. "What are we uncertain about?"
2 UOM-unresolved OCR rows, MEDIUM-confidence photo extractions, mapping
suggestions — each with a buyer action. *Why: the system says what it doesn't
know, the brief's core grading lens.*

## 8. "Which lines have poor coverage?"
6 non-competitive lines incl. L29/L30 NO_QUOTE. *Why: shows missingness as a
first-class answer, never a zero price.*

## 9. "Exclude SUP-007 from the award" / "no supplier more than 30%"
Conditions stored in plain English, enforced at award time, reported back
verbatim. 30% cap pulls SUP-002 into the split. *Why: buyer control without
a spreadsheet.*

## 10. "Give me a full bulk analysis of all lines"
One brief call → 28 winners, gaps, uncertainties. *Why: proves bulk analysis
costs one model turn, not thirty.*
