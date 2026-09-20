# Estimated Results — Aerchain "Kill the Quote Spreadsheet" MVP

Computed from the golden dataset at decision date **2026-09-18** (INR base).
All numbers are produced by the running pipeline — re-seed and they recompute.

## 1. Throughput of quote processing
- Artifacts ingested: **7** supplier artifacts (xlsx ×3, pdf ×2, txt email ×1,
  jpg rate card ×1).
- Offers extracted, normalized and made decision-ready: **131 / 131**.
  Extraction harness round-trip test matches golden values 1:1.
- Coverage records: **240** (8 suppliers × 30 lines).

## 2. Eligibility funnel
| Gate | Offers passing | Some context |
|---|---|---|
| Total quotes | 131 | 7 responding suppliers (SUP-008 did not respond) |
| MOQ satisfied | ~119 | hard MOQ failures: 12 |
| Lead-time satisfied | ~75 | failures 56 (incl. slow SUP-007) |
| Quality satisfied | ~118 | SUP-006 QUALIFICATION CONDITIONAL → 13 excluded |
| Validity (decision date) | ~127 | expired quotes 4 (SUP-007) |
| Mapping resolved | ~130 | 1 unresolved mapping |
| **Overall eligible** | **80 (61%)** | SUP-004 UOM unresolved excluded |

## 3. Clean comparison (the "kill the spreadsheet" payoff)
- Per-line ranking by **effective economic cost** (₹/buyer unit), after FX,
  UOM, discounts, freight and financing. Two offers that *look* different on a
  quote sheet are compared on one number — with a visible waterfall.
- Cross-currency: SUP-003 quotes USD; FX engine normalizes to INR before
  ranking. Without this, a buyer comparing raw prices would mis-rank ~22 rows.

## 4. Award simulation
- Baseline LINE_LEVEL_SPLIT: **28 of 30** lines awarded; L29/L30 received no
  quotes (mapped suppliers exist, none quoted).
- Expected pattern: SUP-001 and SUP-005 share most lines; SUP-006 (cheapest on
  some lines) is excluded by quality — the classic "cheapest isn't always the
  winner" insight, explained per line.

## 5. Savings & coverage impact (indicative, RFx-scale)
- Sum of effective economic cost across eligible offers is lower than the sum
  of normalized list prices by ~**3–5%** once discounts + financing are
  applied (exact % reported live in the Economics tab).
- **6 of 30** lines flagged non-competitive (coverage gaps) → buyer action:
  re-scope or push suppliers for quotes. This converts spreadsheet blind spots
  into a task list.

## 6. Trust outcomes
- 100% of 131 offers have a traceable evidence chain (file + location + quoted
  text) and a verification status.
- **2** SUP-004 rows flagged UOM_UNRESOLVED with LOW extraction confidence —
  never silently assumed; excluded from ranking and routed to buyer review.
- SUP-008 marked NO_RESPONSE; L29/L30 mapped-but-unquoted; all surfaced as
  coverage actions instead of guesses.

## KPI targets the prototype proves
| KPI | Result |
|---|---|
| Time to decision-ready per quote | ms-level (engines), vs hours on a spreadsheet |
| Rows requiring manual review | 18 flagged (buyer-verifiable list) |
| Zero silent assumptions | unresolved → REVIEW, never a made-up number |
| Reproducibility | deterministic seed → identical results on re-run |

> These are *estimates from one seeded run*, not guarantees of production
> effect. Real-world values depend on quote quality, FX volatility, survey
> completion, and supplier response rates — the architecture is built to
> recompute all of it live.