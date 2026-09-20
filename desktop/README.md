# Aerchain · Kill-the-Quote MVP (Groq-only build)

Prototype that replaces the quote spreadsheet with a traceable, decision-ready
procurement evaluation flow: **ingest messy artifacts → normalize → compare →
award → explain**, with a AerBot over real computed data.

This build answers **only through Groq cloud** — there is no local model,
no Ollama, no keyless fallback. You need a free Groq key
(console.groq.com/keys).

## Client quickstart (the only two commands that matter)

```bash
./setup.sh     # once: python env, OCR, Groq key, database (no model download)
./run.sh       # daily: starts everything, opens http://localhost:8136/ (./run.sh [PORT] to override)
./share.sh     # share with someone far away: public HTTPS link (Ctrl-C closes)
./package.sh   # hand to another computer: clean tarball, no secrets (they run setup+run)
```
`./run.sh [PORT]` (default 8000). Ctrl-C stops the app. Re-running either
script is safe — both detect existing state instead of redoing work.
Every dashboard table drills down: click any offer for its calculation
waterfall + evidence, any line for its ranked offers (Esc closes).

## Same-network access (demo on other devices)
The server already listens on all interfaces; `run.sh` prints a LAN URL like
`http://192.168.29.232:8136/ (or your port)` — open it from any device on the same Wi-Fi/LAN.
The model server stays localhost-only by design (browsers never touch it).
If it doesn't connect: allow the port (`sudo ufw allow 8000/tcp`) and check
the Wi-Fi has no client isolation. **Warning: there is no login** — anyone on
the network can view, upload, promote, and factory-reset. Trusted networks
(office LAN, hotspot you control) only; never expose this port to the internet.
Answers need a Groq key: give one to `setup.sh` when asked (or
`GROQ_API_KEY=… ./setup.sh`, or paste more anytime in Settings → Groq cloud).
Saved keys form a pool — on rate limits the next key takes over automatically.

## Access password (shared gate)

`setup.sh` offers one (or set it anytime in Settings → Access password).
One password for everyone opening the app; empty = open. Signed-cookie
sessions (30 days); restarts log everyone out. Applies to the dashboard,
API, docs, and both servers at once — only `/api/health` stays open.

## Share with someone far away

```bash
./share.sh     # needs ./run.sh already going; prints a public https://… link
```
Free Cloudflare tunnel, no router changes, no account. Ctrl-C closes the link
(verified: tunnel process dies, link goes dark). Same no-login warning as
above, stronger: the link is guess-proof but **anyone holding it has full
access** — send it privately, close it when the demo ends. For anything
longer-lived, use a named Cloudflare Tunnel + Access policy (email OTP).

## Deploy off this machine (not Vercel)

Vercel-style serverless **cannot** run this app: the filesystem is read-only
(kills SQLite/uploads), Tesseract isn't installed, and 10–60s function
timeouts decapitate model answers. Use any container host instead (Fly.io /
Render / Railway / VPS with Docker):

```bash
docker build -t aerchain-ktq .
docker run -p 8000:8000 -v aerchain-data:/app/data \
  -e GROQ_API_KEY=gsk-... aerchain-ktq
```
A volume persists the database, uploads, and `.env` across restarts. For
public links put Cloudflare Tunnel in front (see previous section's warning:
no login — add Cloudflare Access before sharing).

## Manual run

```bash
# 1. environment
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. seed + build the SQLite decision layer (deterministic)
.venv/bin/python -m app.pipeline

# 3. optional: generate the 7 messy supplier artifacts in data/raw/
.venv/bin/python -m scripts.generate_artifacts

# 4. connect the AerBot to Groq (required — this build has no local model):
#    Get a free key at console.groq.com/keys, then either export it or save it
#    in .env (cp .env.example .env):
#    GROQ_API_KEY=gsk-...  (first run saves it into the KTQ_GROQ_KEYS pool)
#    Or paste keys anytime in the dashboard: Settings → Groq cloud.
#    Multiple keys form a pool — on rate limits the next key takes over.

# 5. start API + dashboard
.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000/  (redirects to the /ui dashboard; FastAPI docs at /docs)
```

Without a Groq key saved the AerBot API returns `503` with setup guidance —
it never falls back to canned answers (and there is no local model to fall
back to). Answers are grounded in the engines: every `₹` figure must match a
tool result exactly, engine `summary` strings are prepended verbatim, and an
answer that used no tool is rejected and retried.

Groq = fast + stronger NL, but quote data leaves the machine — keep dummy
data there unless you've cleared it. Every answer records that Groq served
it, shown under the answer and in the AerBot status banner. Each key gets 3
tries with backoff before the next pool key takes over; when the whole pool
is rate-limited the answer says so plainly instead of failing cryptically.

## Groq key pool (Settings tab — switchable at runtime, no restart)

Paste keys in Settings → Groq cloud (each key is validated live before it is
saved, and never shown back — only `gsk-…last4` hints). Drag to reorder:
the top key serves first. `GET/POST /api/settings/provider` (+ `/test` for
a live one-call proof). Keys live only in server-side `.env`.

## Settings tab

Only two things live here: the **Groq key pool** (above) and the **model-data
factory reset** (golden rebuild + wipes uploads, conditions, drafts, and chat
memory; saved keys are kept; double-click to confirm). Chat
**Clear**/**Export** (.md transcript) lives in the AerBot view.

## Tests

```bash
.venv/bin/pytest -q        # 85 tests: engines, golden dataset, pipeline, aerbot agent, real-OCR extraction, upload ingest + promote, buyer conditions, bulk brief, groq key pool + retry/failover, gate/breaker/budget, access gate
```

## Bring your own data

Ingestion tab → "Upload your own supplier file" (or `POST /api/ingest/upload`):
xlsx, pdf (text layer or scanned — scanned pages are rendered and OCR'd),
jpg/png (real Tesseract OCR — install `tesseract-ocr` plus
`pip install -r requirements.txt`), email/txt. Rows are parsed, matched to the
product master by code (optionally scoped to a declared supplier), and stored
in `uploaded_file`/`uploaded_offer`; identical re-uploads are rejected by
content hash; anything unmatched or unreadable stays flagged UNRESOLVED.
xlsx, pdf (text layer or scanned), docx, jpg/png, email/txt accepted.
`POST /api/ingest/uploads/{id}/promote` runs buyer-confirmed rows through the
real FX/UOM/discount/freight/financing/eligibility engines into the live
`decision_ready` layer and recomputes coverage + award (incomplete rows are
skipped with reasons, never fabricated). Uploads live in `data/uploads/` and
never touch the golden `data/raw/` set.

## Buyer conditions (plain English, enforced at award)

Award tab → "Buyer conditions", or `POST /api/conditions {"text": "..."}` —
or just tell the AerBot ("exclude SUP-004 from the award"). One per line:
`exclude SUP-004` · `no supplier more than 40%` · `at least 3 suppliers` ·
`lead time max 10 days` · `require quality pass` ·
`quotes valid until 2026-12-31` · `nothing above ₹500 per unit`.
The deterministic NL parser stores what it understands and rejects the rest
with guidance (422) — never silently misapplied. Beyond the built-ins, any
attribute predicate works: `exclude suppliers outside Asia`, `only suppliers
from India`, `only quantity-matching suppliers for Item-036`, `only INR
quotes`, `payment under Net 45` — and anything else goes to Groq,
which translates it into a strict JSON predicate that is validated against
the live masters (unknown suppliers/SKUs/regions are rejected, never
invented). `GET /api/award/current`
enforces active conditions (candidate filtering + share caps) and reports
`conditions_applied`; AerBot award answers cite them too.

## Architecture

```
data/raw/            supplier artifacts (xlsx/pdf/jpg/email); the jpg also ships
                     a legacy .ocr.txt sidecar, used only if Tesseract is absent
scripts/             artifact generator (mirrors golden offers 1:1)
app/
  domain/            enums + 16 dataclasses (the golden "master" model)
  database.py        SQLite storage (AERCHAIN_DB env to relocate)
  seed_data.py       deterministic golden dataset (SEED=73)
  engines/           fx · uom · discount · freight · financing · economics · eligibility
  services/          decision_ready assembly, extraction harness
  pipeline.py        seed → SQLite → decision-ready → coverage → baseline award
  aerbot/           model agent (function calling) → tools → grounded synthesis
  main.py            FastAPI app (REST + /ui dashboard)
static/              dashboard (Overview / RFx / Ingestion / Comparison / AerBot / Scenarios / Award / Trust)
data/aerchain.db     built locally, not committed
docs/                TIMELINE.md, ESTIMATED_RESULTS.md
```

## Key properties

- **Deterministic, auditable** — same seed → same numbers. The deterministic
  engines do the math; the AerBot is a **real-model tool-calling agent**
  (  `llm.py`) that plans tool calls and writes the narrative from exact
  serialized engine output. The model can never do arithmetic, invent numbers,
  or cite evidence the tools didn't return — invented ₹ figures are rejected and
  regenerated, engine fact summaries must be reproduced verbatim, and invented
  evidence is dropped.
- **No hardcoded answers** — without an LLM provider the AerBot API returns
  `503` with setup guidance; it never serves canned replies.
- **No silent assumptions** — unresolved UOM / mapping / LOW-confidence rows
  are flagged `REVIEW`/`UNRESOLVED`, excluded from ranking, and surfaced in
  the Trust tab. L29/L30: mapped suppliers present, no quotes → coverage gap,
  never a guessed price.
- **Decision date 2026-09-18**, base currency INR; FX table for USD/EUR/GBP.
- **Approach** — build engines bottom-up against the MD/HTML spec as a build
  contract, green-flag the decision-ready layer, then add aerbot + UI on top.

## API (selected)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/aerbot/ask` | structured aerbot answer |
| GET  | `/api/comparison?line=&eligible_only=` | per-line effective-cost ranking |
| POST | `/api/scenarios/run` | what-if (add discount / exclude supplier) |
| POST | `/api/award` | award scenario (share caps, min suppliers) |
| GET  | `/api/coverage` | line coverage gaps |
| GET  | `/api/uncertainties` | review / unresolved records |
| GET  | `/api/offers/{offer_id}/calculation` | step-by-step economics waterfall |
| GET  | `/api/offers/{offer_id}/evidence` | source evidence chain |
| GET  | `/api/export/offers` (or `award`, `coverage`) | CSV export |
| POST | `/api/system/reset` | re-seed and rebuild |

Full endpoint list in `app/main.py`.