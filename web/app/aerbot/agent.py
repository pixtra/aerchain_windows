"""AerBot agent — real model, real tools, grounded answers.

The model decides which tools to call and writes the final narrative. Tool
results are serialized with exact currency strings so the DL can only quote
numbers the engines actually produced. Arithmetic lives in the engines, never
in the model.

Flow:  user question → [model → tool calls → execute → results]×n → final JSON
envelope {intent, title, narrative, table, assumptions, exclusions,
uncertainties, evidence} → validate + ground → answer dict.
"""
from __future__ import annotations

import json
import os
import re

from . import tools
from .domain_serialize import serialize_tool_result

MAX_STEPS = 8

SYSTEM = """You are AerBot, Aerchain's procurement assistant for a "Kill-the-Spreadsheet" RFx evaluation
prototype. If asked who you are, say you are AerBot. You work on ONE deterministic dataset: RFx-001, decision date 2026-09-18,
all money computed to base currency INR by deterministic engines (FX, UOM, discount,
freight, financing, eligibility, award).

GROUND RULES — do not violate these, ever:
1. You cannot do arithmetic. You have TOOLS that return real computed numbers.
   Call them, read their output, and copy numbers verbatim. Never compute, estimate,
   round, or invent a number yourself.
2. Tool results are serialized with exact values (e.g. "₹ 419.2956"). Quote them
   exactly; do not reformat or "clean up" digits.
3. Never invent offers, suppliers, lines, prices, evidence files, or reasons.
   Everything you cite must appear in tool outputs.
4. Distinguish ELIGIBLE vs INELIGIBLE by reading overall_eligible from the tool output.
   Explain the reason from eligibility_reason — do not guess a reason.
5. When you are uncertain or a row is flagged (UOM_UNRESOLVED, requires_review,
   LOW/MEDIUM confidence), say so explicitly under uncertainties. Never silently assume.
6. For comparison/cost questions prefer calling get_line_comparison (optionally a
   specific line) so the answer is ranked by effective economic cost (₹/buyer unit).
7. For award/what-if calls, use run_award_scenario / run_cost_scenario with exact
   supplier IDs (SUP-001..SUP-008) and percentages from the user's question.
8. Quote every money figure EXACTLY as the tool serialised it, symbol and spacing
   included (e.g. "₹ 393.6464"). Never round to fewer decimals, never drop the
   symbol, never convert units.
9. When the tool output lists items (lines, awards, suppliers), copy the actual
   identifiers and full range from that output. Never approximate a range or count
   from your own truncated reading of it.
10. Never raise "discrepancy", "requires verification", or "looks wrong" unless you
   quote BOTH conflicting values verbatim from tool output. If you are unsure, say
   so under uncertainties with the exact numbers you have.
11. run_award_scenario: awards_by_supplier and supplier_share are the same map —
   each value is the INTEGER number of lines awarded to that supplier, so e.g.
   SUP-001:4 means "SUP-001 won 4 lines". It is NOT a percentage. Present it as a
   count; never label it "share %" or infer award criteria from it.
12. If a tool result contains a "summary" string, you MUST reproduce that string
   VERBATIM as the opening sentence of your narrative, then add brief analysis.
   Never contradict it or recompute it.
13. Tool selection is mandatory, not optional:
   - recommended award / "who wins" / "lines won per supplier" → run_award_scenario
   - add a discount or exclude a supplier → run_cost_scenario
   - coverage / "which lines lack quotes" → get_coverage
   - flagged / low-confidence / "needs review" → get_uncertainties
   Never answer one of these from memory or from a different tool's output.
14. Any per-supplier count you print (e.g. "SUP-001 won N lines") MUST equal the
   INTEGER in awards_by_supplier from run_award_scenario. If you cannot match it,
   omit the count rather than guess.
15. Buyer award conditions accept flexible plain English ("exclude suppliers
   outside Asia", "only quantity-matching suppliers for Item-036", "only INR
   quotes"): set with set_buyer_condition, listed with get_buyer_conditions.
   run_award_scenario enforces them automatically and reports
   conditions_applied — always mention applied conditions in award answers.
   If set_buyer_condition returns ok:false, quote its error instead of
   pretending the condition was set.
16. Write for a human buyer: use supplier NAMES (not just SUP-xxx) and item
   descriptions with line numbers ("Line 7 — CB Item 006"); keep raw IDs in
   parentheses on first mention. Never show a bare code as the only label.
17. Bulk questions ("all lines", "every line", "whole RFx", "full analysis",
   "summarize everything") MUST be answered with ONE get_full_brief call —
   never one tool call per line. Its summary string opens your narrative.
   Totals, averages and counts: copy award_total_value, award_value_by_supplier,
   expired_by_supplier and ineligible_by_reason VERBATIM from the brief.
   You cannot add, average, or count — any arithmetic of your own is a
   grounding violation. If no tool holds the answer, say so under exclusions
   instead of estimating.
18. RFx drafting (create_rfx_draft) only ever produces DRAFTS. Never say
   created/saved/finalized unless the tool returned ok:true WITH a draft_id —
   then cite it ("saved as draft DF-00x, not live"). Never claim a draft has
   offers, coverage, or an award. If it returns needs_confirm, ask the buyer
   to confirm each unknown item with a code, name and buyer UOM (a suggested
   code is provided — the buyer may keep or change it), then call again
   with the FULL lines_text plus new_skus [{sku_id, name, uom, line_no}].
   If ok:false, quote the error.
19. If the question has no discernible procurement intent — gibberish, jokes,
   small talk beyond greeting, or anything unrelated to RFX-001 — do NOT call
   tools and do NOT invent an answer. Return the envelope with intent "query",
   title "Out of scope", and this narrative: "I didn't understand that as a
   question about this RFx." Put what was missing under exclusions and suggest
   asking about costs, suppliers, lines, eligibility, coverage, the award, or
   what-ifs instead.

Return your FINAL answer as a single JSON object (no prose outside it) shaped:
{
  "intent": one of [summary, comparison, economic, explain, coverage, uncertainty,
                    scenario, award],
  "title": "<short headline>",
  "narrative": "<markdown text; base every figure on tool output; cite offer ids
                and supplier names>",
  "table": [{"Column Label": "value", ...}, ...]   // optional; values from tool output
  "assumptions": ["..."],
  "exclusions": ["..."],                            // what could not be determined
  "uncertainties": ["..."],                          // flags surfaced by tools
  "evidence": [{"offer_id": "...", "source_file": "...", "location": "...",
                "confidence": "HIGH|MEDIUM|LOW"}]
}
Evidence must come verbatim from get_offer_evidence / get_offer_calculation output.
If you cannot fulfil the request, still return the JSON with an honest explanation
under exclusions rather than inventing data.
"""


GATE_SYSTEM = """You are the relevance gate for AerBot, a procurement copilot
whose ONLY objectives are: RFx-001 costs, prices, suppliers, offers, lines,
SKUs, eligibility, coverage, discounts, awards, scenarios, evidence,
calculations, RFx drafts, buyer conditions, and summaries — plus plain
greetings and thanks.

Classify the last user message in its conversational context. Reply with ONLY
one JSON object, no prose: {"verdict": "greeting"|"relevant"|"irrelevant"}.
- "greeting": hello, hi, thanks, bye, who are you, what can you do — chit-chat
  needing no data.
- "relevant": anything plausibly about the objectives above, including vague,
  misspelled, or fragmentary attempts ("winnr?", "line 7 cheap?", "Item-036??",
  "and the second one?", "make it cheaper").
- "irrelevant": jokes, insults, keyboard mashing, other topics, or messages
  empty of procurement meaning ("poop", "asdfgh", "tell me a joke").
  A message that merely MENTIONS rfx/rfq/quote/supplier words but asks NO
  actual question about costs, suppliers, lines, awards, eligibility,
  coverage, evidence, drafts, conditions, or summaries is also irrelevant
  ("babaji ka rfx", "rfx lol", "supplier babaji").
When torn between relevant and irrelevant, choose relevant — but a mention
with no question is not a torn case, it is irrelevant."""


def _gate_relevance(question: str, chat_fn, history=None) -> str:
    """One cheap model call triages every input. Never raises: any failure,
    ambiguity, or unparseable reply fails OPEN to a full answer attempt."""
    try:
        msgs = [m for m in (history or [])
                if m.get("role") in ("user", "assistant") and m.get("content")]
        msgs = msgs[-6:] + [{"role": "user", "content": question}]
        resp = chat_fn(GATE_SYSTEM, msgs, [])
    except Exception as e:
        from .llm import ModelNotConfigured
        if isinstance(e, ModelNotConfigured):
            raise  # no provider configured — main.py turns this into a 503
        return "relevant"
    if getattr(resp, "tool_calls", None):
        return "relevant"
    text = (resp.content or "").strip()
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        obj = None
    if isinstance(obj, dict) and obj.get("verdict") in (
            "greeting", "relevant", "irrelevant"):
        return obj["verdict"]
    m = re.search(r'"verdict"\s*:\s*"(greeting|relevant|irrelevant)"', text)
    return m.group(1) if m else "relevant"


_CHITCHAT_SUFFIX = (
    "\nThe user is only greeting, thanking, or asking who you are — not "
    "asking for data. Reply briefly and warmly as AerBot in one or two "
    "sentences. Do NOT call tools. Return ONLY the final answer JSON "
    "envelope (intent, title, narrative, table, assumptions, exclusions, "
    "uncertainties, evidence).")


def _decline(question: str) -> dict:
    envelope = {
        "intent": "query", "title": "Out of scope",
        "narrative": ("That doesn't look like a question about this RFx, so "
                      "I won't guess. I answer questions about costs, suppliers, "
                      "lines, eligibility, coverage, the award, evidence, and "
                      "what-ifs on RFX-001 — try one of the suggestions, or "
                      "rephrase with a supplier, line, or item in it."),
        "table": [], "assumptions": [], "exclusions": ["no tools consulted"],
        "uncertainties": [], "evidence": [],
    }
    return _ground(envelope, question, [], set(), [])


def _chitchat(question: str, chat_fn) -> dict:
    """Greetings bypass tools entirely, so no engine summary can leak in."""
    try:
        resp = chat_fn(SYSTEM + _CHITCHAT_SUFFIX,
                       [{"role": "user", "content": question}], [])
        text = (resp.content or "").strip()
    except Exception:
        text = ""
    envelope = _parse_envelope(text) if text else None
    if envelope is None:
        envelope = {
            "intent": "query", "title": "AerBot",
            "narrative": text or "Hi there! I'm AerBot — ask me about costs, "
            "coverage, eligibility, the award, or what-ifs.",
            "table": [], "assumptions": [], "exclusions": [],
            "uncertainties": [], "evidence": [],
        }
    return _ground(envelope, question, [], set(), [])


def _tool(name, description, parameters):
    return {"name": name, "description": description, "parameters": parameters}


TOOLS = [
    _tool("get_rfx_summary",
          "Broad RFx overview: line count, responding suppliers, offers received, "
          "eligible offers, review count, base currency, decision date.",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("get_line_comparison",
          "Offers for a line or the whole RFx, ranked by effective economic cost "
          "(₹/buyer unit). Use line_number for a specific line. eligible_only filters "
          "to overall_eligible=1. Returns full decision-ready fields including "
          "eligibility_reason and confidence flags.",
          {"type": "object",
           "properties": {"line_number": {"type": "integer", "description": "1..30"},
                          "eligible_only": {"type": "boolean", "default": False},
                          "limit": {"type": "integer", "default": 60}},
           "additionalProperties": False}),
    _tool("get_offer_calculation",
          "Step-by-step economics waterfall for one offer id (e.g. OFF-0001): FX, UOM "
          "conversion, discount, freight, financing, effective cost. Also eligibility.",
          {"type": "object",
           "properties": {"offer_id": {"type": "string"}},
           "required": ["offer_id"], "additionalProperties": False}),
    _tool("get_offer_evidence",
          "Source evidence rows for one offer id: file, location, extracted text, "
          "confidence, verification status. Use verbatim for the evidence field.",
          {"type": "object",
           "properties": {"offer_id": {"type": "string"}},
           "required": ["offer_id"], "additionalProperties": False}),
    _tool("get_supplier_offers",
          "All decision-ready offers belonging to one supplier (SUP-001..SUP-008).",
          {"type": "object",
           "properties": {"supplier_id": {"type": "string"}},
           "required": ["supplier_id"], "additionalProperties": False}),
    _tool("get_coverage",
          "Per-line supplier coverage: mapped suppliers, offers received, qualified "
          "offers, coverage status (COMPETITIVE/PARTIAL/NO_QUOTE/NO_COVERAGE) and a "
          "buyer action.",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("get_uncertainties",
          "Records flagged for review: LOW/MEDIUM extraction confidence, unresolved "
          "UOM/mapping, requires_review rows. Never ignore these.",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("run_cost_scenario",
          "What-if: add X% discount to one or more suppliers (dict of SUP-xxx → %) or "
          "exclude suppliers; meaningful economics are recomputed deterministically.",
          {"type": "object",
           "properties": {"scenario_name": {"type": "string"},
                          "additional_discounts": {"type": "object",
                                                   "additionalProperties": {"type": "number"}},
                          "supplier_exclusions": {"type": "array", "items": {"type": "string"}}},
           "additionalProperties": False}),
    _tool("run_award_scenario",
          "Run a LINE_LEVEL_SPLIT award: cheapest eligible offer per line, optional "
          "max_supplier_share (%) and min_qualified_suppliers. Active buyer "
          "conditions (exclusions, share caps, lead/quality/validity/cost rules) "
          "are enforced automatically; the output lists conditions_applied. Returns awards (one per "
          "awarded line), awards_by_supplier / supplier_share = SUP-xxx -> INTEGER count "
          "of lines awarded to that supplier (NOT a percentage), and line_count. Lines "
          "with no eligible offer are simply absent from awards.",
          {"type": "object",
           "properties": {"scenario_id": {"type": "string", "default": "SCN-ADHOC"},
                          "scenario_name": {"type": "string"},
                          "max_supplier_share": {"type": "number", "default": None},
                          "min_qualified_suppliers": {"type": "integer", "default": None}},
           "additionalProperties": False}),
    _tool("get_buyer_conditions",
          "List the buyer's active award conditions (exclusions, share caps, "
          "lead/quality/validity/cost rules).",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("get_full_brief",
          "Whole-RFx brief in ONE call: cheapest eligible offer per line, "
          "offer/eligible counts, coverage gaps, uncertainty count, active "
          "conditions, plus precomputed AGGREGATES: award_total_value and "
          "award_value_by_supplier (already summed — never add costs "
          "yourself), expired_by_supplier counts, ineligible_by_reason "
          "counts. MANDATORY for any question about all lines, every "
          "line, the full RFx, bulk analysis, totals, counts, or expired "
          "offers — never call per-line tools in a loop and never compute "
          "sums, averages, or counts yourself.",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("create_rfx_draft",
          "Draft a NEW RFx from conversation (scope, lines, terms, deadline). "
          "lines_text is one 'Item-NNN x QTY' entry per line. Drafts are NOT "
          "live: no offers, no award. Unknown SKUs return needs_confirm "
          "instead of inventing them — ask the buyer for code, name and buyer "
          "UOM per item (suggested codes provided), then call again with new_skus "
          "[{sku_id, name, uom, line_no}].",
          {"type": "object",
           "properties": {"name": {"type": "string"},
                          "category": {"type": "string"},
                          "lines_text": {"type": "string"},
                          "terms": {"type": "string"},
                          "deadline": {"type": "string", "description": "YYYY-MM-DD"},
                          "new_skus": {"type": "array",
                                       "description": "buyer-confirmed new SKUs",
                                       "items": {"type": "object"}}},
           "required": ["name", "lines_text"], "additionalProperties": False}),
    _tool("list_rfx_drafts",
          "List saved RFx drafts (explicitly not live).",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("set_buyer_condition",
          "Set a buyer award condition from plain English, e.g. 'exclude SUP-004', "
          "'no supplier more than 40%', 'lead time max 10 days'. Rejected with "
          "guidance if not understood.",
          {"type": "object",
           "properties": {"text": {"type": "string"}},
           "required": ["text"], "additionalProperties": False}),
]

_HANDLERS = {
    "get_rfx_summary": lambda a: tools.get_rfx_summary(),
    "get_line_comparison": lambda a: tools.get_line_comparison(
        line_number=a.get("line_number"), eligible_only=bool(a.get("eligible_only", False)),
        limit=a.get("limit", 60)),
    "get_offer_calculation": lambda a: tools.get_offer_calculation(a["offer_id"]),
    "get_offer_evidence": lambda a: tools.get_offer_evidence(a["offer_id"]),
    "get_supplier_offers": lambda a: tools.get_supplier_offers(a["supplier_id"]),
    "get_coverage": lambda a: tools.get_coverage(),
    "get_uncertainties": lambda a: tools.get_uncertainties(),
    "run_cost_scenario": lambda a: tools.run_cost_scenario(
        tools.make_cost_scenario(a.get("scenario_name", "Ad-hoc what-if"),
                                 a.get("additional_discounts", {}),
                                 a.get("supplier_exclusions", []))),
    "run_award_scenario": lambda a: tools.run_award_scenario(
        tools.make_award_scenario(a.get("scenario_id", "SCN-ADHOC"),
                                  a.get("scenario_name", "Recommended split"),
                                  a.get("max_supplier_share"),
                                  a.get("min_qualified_suppliers"))),
    "get_buyer_conditions": lambda a: tools.get_buyer_conditions(),
    "get_full_brief": lambda a: tools.get_full_brief(),
    "create_rfx_draft": lambda a: tools.create_rfx_draft(a),
    "list_rfx_drafts": lambda a: tools.list_rfx_drafts(),
    "set_buyer_condition": lambda a: tools.set_buyer_condition(
        a.get("text", "")),
}


def run(question: str, chat_fn=None, steps: int = MAX_STEPS,
        history: list[dict] | None = None, budget_s: float | None = None) -> dict:
    """Execute the tool-calling loop; returns the grounded answer envelope.
    chat_fn defaults to the real provider client; tests inject a scripted one.
    history holds prior {role, content} turns (no tool payloads) so follow-up
    questions resolve against the conversation.
    budget_s caps total wall-clock time (default KTQ_AGENT_BUDGET_S, 240s):
    a question that cannot converge — junk that slipped the gate, or dead
    providers — fails fast with guidance instead of grinding for minutes.
    Three consecutive provider errors abort the same way; intermittent
    errors do not trip the breaker."""
    import time as _time
    if budget_s is None:
        try:
            budget_s = float(os.environ.get("KTQ_AGENT_BUDGET_S", "240"))
        except ValueError:
            budget_s = 240.0
    deadline = _time.monotonic() + budget_s
    def _over_budget() -> bool:
        return _time.monotonic() >= deadline
    from .llm import ModelNotConfigured, client_chat
    chat_fn = chat_fn or client_chat
    hist = [{"role": m["role"], "content": m["content"]} for m in (history or [])
            if m.get("role") in ("user", "assistant") and m.get("content")]
    verdict = _gate_relevance(question, chat_fn, hist)
    if verdict == "greeting":
        return _chitchat(question, chat_fn)
    if verdict == "irrelevant":
        return _decline(question)
    messages = [m for m in (history or [])
                if m.get("role") in ("user", "assistant") and m.get("content")]
    messages = messages[-12:]
    messages.append({"role": "user", "content": question})
    seen_evidence: list[dict] = []
    seen_offers: set[str] = set()
    payload_blob: list[str] = []
    straight_errors = 0

    for _ in range(steps):
        if _over_budget():
            raise RuntimeError(
                "this question is taking too long to answer — try a more "
                "specific question about one line, supplier, or the award")
        try:
            resp = chat_fn(SYSTEM, messages, TOOLS)
        except ModelNotConfigured:
            raise  # no provider configured — main.py turns this into a 503
        except Exception as e:
            straight_errors += 1
            if straight_errors >= 3:
                raise RuntimeError(
                    f"the model is unreachable right now ({type(e).__name__}) "
                    "— retry in a bit") from e
            continue
        straight_errors = 0
        if resp.tool_calls:
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.name,
                                             "arguments": json.dumps(tc.arguments)}}
                               for tc in resp.tool_calls]})
            for tc in resp.tool_calls:
                if tc.name not in _HANDLERS:
                    payload = json.dumps({"error": f"unknown tool {tc.name}"})
                else:
                    handler = _HANDLERS[tc.name]
                    try:
                        result = handler(tc.arguments)
                        payload = serialize_tool_result(result)
                    except Exception as e:  # surface tool errors to the model honestly
                        payload = json.dumps({"error": f"{type(e).__name__}: {e}"})
                    _collect_provenance(tc.name, payload, seen_evidence, seen_offers)
                payload_blob.append(payload)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "name": tc.name, "content": payload})
            continue

        if not resp.content:
            # reasoning models occasionally emit an empty turn; nudge and retry
            messages.append({"role": "user",
                             "content": "You returned nothing. Either call a tool, or "
                             "return ONLY the final answer JSON object now."})
            continue
        envelope = _parse_envelope(resp.content)
        if envelope is not None:
            if not payload_blob:
                # an answer with no tool call can cite unchecked numbers; require
                # the model to consult the engines before answering
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user",
                                 "content": "You answered without calling any tool, so no "
                                 "number can be trusted. Call the appropriate tool now, read "
                                 "its output, then return the final answer JSON using only "
                                 "those values."})
                continue
            offenders = _ungrounded_numbers(envelope, payload_blob)
            wrong_counts = _wrong_award_counts(envelope, payload_blob)
            if not offenders and not wrong_counts:
                return _ground(envelope, question, seen_evidence, seen_offers, payload_blob)
            # every ₹ figure must be an exact engine value, and per-supplier
            # award counts must match awards_by_supplier — ask the model to fix
            messages.append({"role": "assistant", "content": resp.content})
            problems = []
            if offenders:
                problems.append("it cites figures that are NOT in the tool output: "
                                + ", ".join(offenders[:6]))
            if wrong_counts:
                problems.append("its per-supplier line counts contradict the engine: "
                                + "; ".join(wrong_counts[:4]))
            messages.append({"role": "user",
                             "content": "Rewrite the entire answer JSON as instructed: "
                             + " ".join(problems) +
                             ". Quote money values exactly as they appear, only those values."})
            continue
        # the model answered without a valid envelope — feed it back and retry
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user",
                         "content": "That was not a valid final answer. Reply with ONLY the "
                         "JSON envelope object (intent, title, narrative, table, "
                         "assumptions, exclusions, uncertainties, evidence)."})

    raise RuntimeError(
        "I could not build a grounded answer for that — try a more specific "
        "question about one line, supplier, or the award")


def _collect_provenance(name, payload, seen_evidence, seen_offers):
    """Track evidence and offer ids the model actually touched, so the final
    answer can never cite data the tools never produced."""
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return
    if name == "get_offer_evidence":
        for row in data if isinstance(data, list) else []:
            seen_evidence.append({k: row.get(k) for k in
                                  ("source_file", "source_location", "confidence")})
    if isinstance(data, dict):
        if data.get("offer_id"):
            seen_offers.add(data["offer_id"])
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and row.get("offer_id"):
                seen_offers.add(row["offer_id"])


def _parse_envelope(text: str):
    cleaned = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    if m:
        cleaned = m.group(1)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        obj = None
        if start != -1 and end > start:
            try:
                obj = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                obj = None
        if obj is None:
            # small local models sometimes emit a truncated/invalid envelope;
            # salvage the human-readable fields rather than looping forever
            return _salvage_envelope(cleaned)
    if not isinstance(obj, dict) or not obj.get("narrative"):
        return _salvage_envelope(cleaned)
    return obj


def _salvage_envelope(text: str):
    """Best-effort extraction of the answer fields from malformed JSON."""
    def field(name: str):
        m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % name, text, re.S)
        if not m:
            return None
        try:
            return json.loads('"' + m.group(1) + '"')
        except json.JSONDecodeError:
            return m.group(1)
    narrative = field("narrative")
    if not narrative:
        return None
    return {"intent": field("intent") or "query", "title": field("title"),
            "narrative": narrative, "table": _salvage_table(text),
            "assumptions": [], "exclusions": [], "uncertainties": [],
            "evidence": []}


def _salvage_table(text: str) -> list:
    """Recover the table array from truncated JSON via balanced-bracket scan."""
    i = text.find('"table"')
    if i == -1:
        return []
    j = text.find("[", i)
    if j == -1:
        return []
    depth, instr, esc = 0, False, False
    for k in range(j, len(text)):
        c = text[k]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    arr = json.loads(text[j:k + 1])
                    return arr if isinstance(arr, list) else []
                except json.JSONDecodeError:
                    return []
    return []


def _award_counts(payload_blob: list[str]) -> dict:
    for blob in payload_blob:
        try:
            data = json.loads(blob)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("awards_by_supplier"), dict):
            return data["awards_by_supplier"]
    return {}


def _wrong_award_counts(envelope: dict, payload_blob: list[str]) -> list[str]:
    """Per-supplier line counts stated as `SUP-001 10` / `SUP-001: 10` must
    equal the engine's awards_by_supplier — catches contradicted counts."""
    counts = _award_counts(payload_blob)
    if not counts:
        return []
    text = (envelope.get("narrative") or "") + " " + json.dumps(envelope.get("table") or [])
    bad = []
    for sup, n in counts.items():
        for m in re.finditer(re.escape(sup) + r"\s*[:\-]?\s*(\d+)", text):
            if int(m.group(1)) != int(n):
                bad.append(f"{sup} stated as {m.group(1)} lines but engine says {n}")
    return bad


_NUM = re.compile(r"₹\s*([\d,]+(?:\.\d+)?)")


def _normalize_amount(tok: str) -> str:
    return tok.replace(",", "").strip()


def _payload_has_ineligible(payload_blob: list[str]) -> bool:
    """True when any tool payload this run contains an ineligible offer."""
    for blob in payload_blob:
        try:
            data = json.loads(blob)
        except (TypeError, json.JSONDecodeError):
            continue
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if isinstance(row, dict) and row.get("overall_eligible") in (0, False):
                return True
            if isinstance(row, dict) and isinstance(row.get("awards"), list):
                return False
    return False


def _engine_summaries(payload_blob: list[str]) -> list[str]:
    """Engine-produced 'summary' strings found in this run's tool outputs."""
    required = []
    for blob in payload_blob:
        try:
            data = json.loads(blob)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("summary"):
            required.append(str(data["summary"]))
        elif isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("summary"):
                    required.append(str(row["summary"]))
    return required


def _missing_summaries(envelope: dict, payload_blob: list[str]) -> list[str]:
    """Engine-produced 'summary' strings that the narrative MUST contain."""
    required = _engine_summaries(payload_blob)
    if not required:
        return []
    text = (envelope.get("narrative") or "") + " " + json.dumps(envelope.get("table") or [])
    return [s for s in required if s not in text]


def _ungrounded_numbers(envelope: dict, payload_blob: list[str]) -> list[str]:
    """Return every ₹ figure the model printed that is NOT an exact engine
    value from the tool payloads. Enforces: no invented numbers."""
    if not payload_blob:
        return []
    corpus = " ".join(payload_blob)
    allowed = {_normalize_amount(t) for t in _NUM.findall(corpus)}
    if not allowed:
        return []
    text = envelope.get("narrative") or ""
    try:
        text += json.dumps(envelope.get("table") or [])
    except (TypeError, ValueError):
        pass
    seen, offenders = [], []
    for tok in _NUM.findall(text):
        norm = _normalize_amount(tok)
        if norm not in seen:
            seen.append(norm)
            if norm not in allowed:
                offenders.append(f"₹ {tok}")
    return offenders


_INTENTS = {"summary", "comparison", "economic", "explain", "coverage",
            "uncertainty", "scenario", "award"}


def _ground(envelope: dict, question, seen_evidence, seen_offers,
            payload_blob=None) -> dict:
    intent = envelope.get("intent")
    if intent not in _INTENTS:
        intent = "query"
    table = envelope.get("table") or []
    if not isinstance(table, list):
        table = []
    evidence = envelope.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = []
    # evidence is only admissible if it matches a source the tools actually
    # returned this run — model-invented rows are dropped, never surfaced
    real_sources = {ev["source_file"] for ev in seen_evidence if ev.get("source_file")}
    valid = [e for e in evidence
             if isinstance(e, dict) and e.get("source_file")
             and e["source_file"] in real_sources]
    # merge in real evidence we actually retrieved, de-duplicated
    for ev in seen_evidence:
        if ev.get("source_file") and not any(e.get("source_file") == ev["source_file"]
                                             for e in valid):
            valid.append(ev)
    narrative = str(envelope.get("narrative") or "Returned no narrative.")
    # the engines' summary strings are authoritative: guarantee they appear
    # verbatim up front rather than trusting the model to reproduce them
    for summary in _engine_summaries(payload_blob or []):
        if summary not in narrative:
            narrative = summary + "\n\n" + narrative
    assumptions = [a for a in (envelope.get("assumptions") or [])]
    if _payload_has_ineligible(payload_blob or []):
        # never let a blanket "everything is eligible/valid" claim survive
        # when the tools returned ineligible offers this run
        assumptions = [a for a in assumptions
                       if not (isinstance(a, str) and re.search(
                           r"\ball\b.{0,30}(eligible|valid|qualif)", a, re.I))]
    return {
        "question": str(question),
        "intent": intent,
        "title": str(envelope.get("title") or "AerBot answer"),
        "narrative": narrative,
        "table": table,
        "assumptions": assumptions,
        "exclusions": envelope.get("exclusions") or [],
        "uncertainties": envelope.get("uncertainties") or [],
        "evidence": valid[:8],
        "provider": _serving_provider(),
        "markdown": "",  # filled by explainer.render_markdown
    }


def _serving_provider() -> str | None:
    try:
        from .llm import _serving_display
        return _serving_display()
    except Exception:
        return None


def status() -> dict:
    """Provider chain + dataset context for the UI to show."""
    from .llm import LAST_PROVIDER, ModelNotConfigured, resolve_chain
    try:
        chain = resolve_chain()
        if not chain:
            from .llm import resolve_provider
            resolve_provider()  # raises ModelNotConfigured with backend guidance
        primary, cfg = chain[0]
        return {"configured": True, "provider": primary, "model": cfg.get("model"),
                "chain": [f"{p}:{c.get('model')}" for p, c in chain],
                "serving": LAST_PROVIDER["name"],
                "fell_back": LAST_PROVIDER["fell_back"]}
    except ModelNotConfigured as e:
        return {"configured": False, "detail": str(e)}