# One-page note: what we decided, and what we deliberately left out

## Decided
- **Models never do arithmetic.** The LLM selects tools and writes prose; every
  figure is engine-computed and quoted verbatim, with retries on invention.
  A model that can't subtract can't corrupt a ₹3 Cr award.
- **Golden data is a test oracle, not truth.** Artifacts generate backward from
  expected offers; real OCR therefore scores 17/18, not 131/131 — and the test
  asserts that honestly instead of simulating perfection.
- **Missingness is data.** No-quote lines, silent suppliers, and unresolved UOMs
  are first-class states with buyer actions, never zero prices or guesses.
- **Uploads stage before they count.** Your files parse, match, and flag — but
  enter the decision layer only via buyer-confirmed promote (lead/validity the
  file doesn't state are confirmed, not fabricated).
- **Buyer conditions are predicates, not prompts.** Plain English compiles to
  validated attribute rules; the model translates only what deterministic
  patterns can't, and unknown references are rejected with guidance.
- **Two-command handover** (`setup.sh`/`run.sh`) with exact-PID lifecycle —
  because a prototype the client can't start is a prototype that doesn't exist.

## Deliberately left out
- **RFx drafts stay drafts.** Conversational RFx creation produces planning
  records, never live decision state — promoting a draft into the award
  pipeline would silently fork the golden dataset the demo is graded on.
- **No optimizer.** One supplier per line (the brief's grain); share caps and
  minima are greedy constraints, not MILP. Gurobi can come when lines split.
- **No SMTP.** Upload replaces the email channel; transport is stubbed per the
  brief's explicit permission, extraction is not.
- **No auth/multi-tenancy.** Localhost demo; CORS locked down, keys server-side,
  but anyone with the URL is the buyer.
- **Static FX/policy.** Live rates, versioned rules, and tax/duty engines are
  future work — the architecture isolates them behind engine boundaries.
- **Charts are descriptive, not analytical.** Auto-bars visualize returned
  tables; no insight is ever computed in the browser.

## The better problem we found
The brief asks how to read messy quotes. The harder problem is **what to do
with answers you can't fully trust**: every load-bearing choice above is about
keeping uncertainty visible and actionable rather than parsing slightly better.
A buyer with ₹4 crore on the line doesn't need a smarter spreadsheet — they
need a system that says what it doesn't know.
