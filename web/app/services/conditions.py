"""Buyer conditions — procurement rules set in plain English (or structured
form) and enforced for real at award time.

Kinds: EXCLUDE_SUPPLIER | MAX_SUPPLIER_SHARE | MIN_SUPPLIERS |
MAX_LEAD_DAYS | REQUIRE_QUALITY_PASS | REQUIRE_VALID_UNTIL | MAX_EFFECTIVE_COST

The NL parser is deterministic pattern matching, not a model: anything it
cannot understand is rejected with guidance, never silently misapplied.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.database import get_conn

KINDS = ("EXCLUDE_SUPPLIER", "MAX_SUPPLIER_SHARE", "MIN_SUPPLIERS",
         "MAX_LEAD_DAYS", "REQUIRE_QUALITY_PASS", "REQUIRE_VALID_UNTIL",
         "MAX_EFFECTIVE_COST")

HINT = ("Try one per line, e.g. 'exclude SUP-004' · 'no supplier more than 40%'"
        " · 'at least 3 suppliers' · 'lead time max 10 days' · "
        "'require quality pass' · 'quotes valid until 2026-12-31' · "
        "'nothing above ₹500 per unit' · 'exclude suppliers outside Asia' · "
        "'only suppliers from India' · 'only quantity-matching suppliers for "
        "Item-036' · 'only INR quotes' · 'payment under Net 45'")


# ------------------------------------------------------- flexible predicates
SPEC_ATTRS = {
    "supplier": ("supplier_id", "supplier_name", "region", "country",
                 "currency", "payment_days", "default_lead_time"),
    "offer": ("lead_time_days", "moq", "quantity_match", "quality_eligible",
              "quote_valid_until", "effective_economic_cost",
              "quoted_currency", "supplier_id", "line_number", "sku_id"),
}
SPEC_OPS = ("==", "!=", "<", "<=", ">", ">=", "in", "not_in")


def _cmp(op: str, a, b) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "in":
        return a in (b or [])
    if op == "not_in":
        return a not in (b or [])
    try:
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
    except TypeError:
        return False
    return False


def eval_spec(spec: dict, ctx: dict) -> bool:
    """True when the context satisfies the predicate (all AND, any OR)."""
    for clause in spec.get("all", []):
        if clause.get("attr") not in SPEC_ATTRS.get(spec.get("entity", ""), ()):
            return False
        if clause.get("op") not in SPEC_OPS:
            return False
        if not _cmp(clause["op"], ctx.get(clause["attr"]), clause.get("value")):
            return False
    anys = spec.get("any", [])
    if anys and not any(
            c.get("op") in SPEC_OPS
            and c.get("attr") in SPEC_ATTRS.get(spec.get("entity", ""), ())
            and _cmp(c["op"], ctx.get(c["attr"]), c.get("value")) for c in anys):
        return False
    return True


def _quantity_match(rec) -> bool:
    try:
        q = float(getattr(rec, "quoted_quantity", 0) or 0)
        conv = float(getattr(rec, "uom_conversion_factor", 0) or 0) or 1.0
        req = float(getattr(rec, "required_quantity", 0) or 0)
    except (TypeError, ValueError):
        return False
    if req <= 0:
        return False
    import math
    return math.isclose(q * conv, req, rel_tol=1e-3, abs_tol=1e-6)


def record_context(rec, suppliers: dict) -> dict:
    s = suppliers.get(getattr(rec, "supplier_id", ""), {}) or {}
    loc = s.get("location", "")
    return {
        "supplier_id": getattr(rec, "supplier_id", None),
        "supplier_name": s.get("supplier_name"),
        "region": supplier_region(loc),
        "country": supplier_country(loc),
        "currency": s.get("default_currency"),
        "payment_days": getattr(rec, "payment_days", None),
        "default_lead_time": s.get("default_lead_time_days"),
        "lead_time_days": getattr(rec, "lead_time_days", None),
        "moq": getattr(rec, "moq", None),
        "quantity_match": _quantity_match(rec),
        "quality_eligible": bool(getattr(rec, "quality_eligible", False)),
        "quote_valid_until": getattr(rec, "quote_valid_until", "") or "",
        "effective_economic_cost": getattr(rec, "effective_economic_cost", None),
        "quoted_currency": getattr(rec, "quoted_currency", None),
        "line_number": getattr(rec, "line_number", None),
        "sku_id": getattr(rec, "sku_id", None),
    }


def _scope_from_text(t: str) -> dict | None:
    m = re.search(r"(?:for|on|of)\s+(?:SKU\s*)?(Item[\s\-–_]*0*\d{1,3}\b)", t, re.I)
    if m:
        return {"sku": _norm_sku_ref(m.group(1))}
    m = re.search(r"\bline\s*(\d{1,2})\b", t, re.I)
    if m:
        return {"line": int(m.group(1))}
    m = re.search(r"(SUP-\d{3})", t, re.I)
    if m and re.search(r"\bfor\b", t, re.I):
        return {"supplier": m.group(1).upper()}
    return None


def parse_v2(text: str) -> tuple[dict, str]:
    """Deterministic flexible patterns. Returns (spec, description) or raises."""
    t = (text or "").strip()
    scope = _scope_from_text(t)
    for region in REGIONS:
        if re.search(r"excluding|outside(?:\s+of)?\s+" + region
                     + r"|not\s+from\s+" + region, t, re.I):
            return ({"effect": "exclude", "entity": "supplier", "scope": scope,
                     "all": [{"attr": "region", "op": "!=", "value": region}]},
                    f"exclude suppliers outside {region}"
                    + (f" ({_scope_desc(scope)})" if scope else ""))
        if re.search(r"only\s+(?:suppliers?\s+)?(?:from|in)\s+" + region
                     + r"|limit(?:ed)?\s+to\s+" + region, t, re.I):
            return ({"effect": "require", "entity": "supplier", "scope": scope,
                     "all": [{"attr": "region", "op": "==", "value": region}]},
                    f"only suppliers from {region}"
                    + (f" ({_scope_desc(scope)})" if scope else ""))
    m = re.search(r"exclud(?:e|ing)\s+(?:suppliers?\s+)?from\s+([A-Za-z ]+?)(?:\s+for\b|$)",
                  t, re.I)
    if m:
        code = COUNTRY_NAMES.get(m.group(1).strip().upper())
        if code:
            return ({"effect": "exclude", "entity": "supplier", "scope": scope,
                     "all": [{"attr": "country", "op": "==", "value": code}]},
                    f"exclude suppliers from {m.group(1).strip()}")
    m = re.search(r"only\s+(?:suppliers?\s+)?from\s+([A-Za-z ]+?)(?:\s+for\b|$)", t, re.I)
    if m and not any(r in m.group(1) for r in REGIONS):
        code = COUNTRY_NAMES.get(m.group(1).strip().upper())
        if code:
            return ({"effect": "require", "entity": "supplier", "scope": scope,
                     "all": [{"attr": "country", "op": "==", "value": code}]},
                    f"only suppliers from {m.group(1).strip()}")
    if re.search(r"quantity[\-\s]?matching", t, re.I):
        return ({"effect": "require", "entity": "offer", "scope": scope,
                 "all": [{"attr": "quantity_match", "op": "==", "value": True}]},
                "only quantity-matching offers (quoted amount = required amount)"
                + (f" ({_scope_desc(scope)})" if scope else ""))
    m = re.search(r"only\s+(INR|USD|EUR|GBP|rupees?)\b", t, re.I)
    if m:
        cur = {"RUPEES": "INR", "RUPEE": "INR"}.get(m.group(1).upper(), m.group(1).upper())
        return ({"effect": "require", "entity": "offer", "scope": scope,
                 "all": [{"attr": "quoted_currency", "op": "==", "value": cur}]},
                f"only {cur} quotes")
    m = re.search(r"no\s+(INR|USD|EUR|GBP)\b", t, re.I)
    if m:
        return ({"effect": "exclude", "entity": "offer", "scope": scope,
                 "all": [{"attr": "quoted_currency", "op": "==",
                          "value": m.group(1).upper()}]},
                f"exclude {m.group(1).upper()} quotes")
    m = re.search(r"(?:payment|pay)(?:\s*terms?)?\s*(?:under|within|max|<=?)\s*"
                  r"net\s*(\d+)", t, re.I)
    if m:
        return ({"effect": "require", "entity": "offer", "scope": scope,
                 "all": [{"attr": "payment_days", "op": "<=",
                          "value": int(m.group(1))}]},
                f"only payment Net {m.group(1)} or better")
    raise ValueError(f"no flexible pattern matched {text!r}")


def _scope_desc(scope: dict | None) -> str:
    if not scope:
        return ""
    if "sku" in scope:
        return f"for {scope['sku']}"
    if "line" in scope:
        return f"for line {scope['line']}"
    return f"for {scope.get('supplier')}"


def scope_applies(spec: dict, rec) -> bool:
    scope = spec.get("scope") or {}
    if "sku" in scope and (getattr(rec, "sku_id", "") or "").upper() != scope["sku"].upper():
        return False
    if "line" in scope and getattr(rec, "line_number", None) != scope["line"]:
        return False
    if "supplier" in scope and getattr(rec, "supplier_id", "") != scope["supplier"]:
        return False
    return True


def init_table():
    conn = get_conn()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS buyer_condition (
            condition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT, target TEXT, value_num REAL, value_text TEXT,
            active INTEGER DEFAULT 1, source TEXT, created_at TEXT
        )""")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(buyer_condition)")]
    if "spec" not in cols:  # flexible predicate rules (v2)
        conn.execute("ALTER TABLE buyer_condition ADD COLUMN spec TEXT")
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ geography
COUNTRY_TO_REGION = {
    "IN": "Asia", "SG": "Asia", "VN": "Asia", "CN": "Asia", "JP": "Asia",
    "KR": "Asia", "TH": "Asia", "MY": "Asia", "ID": "Asia", "PH": "Asia",
    "AE": "Asia", "SA": "Asia", "LK": "Asia", "BD": "Asia",
    "US": "North America", "CA": "North America", "MX": "North America",
    "DE": "Europe", "FR": "Europe", "IT": "Europe", "ES": "Europe",
    "NL": "Europe", "BE": "Europe", "GB": "Europe", "UK": "Europe",
    "PL": "Europe", "SE": "Europe", "IE": "Europe", "PT": "Europe",
    "BR": "South America", "CL": "South America", "AR": "South America",
    "ZA": "Africa", "EG": "Africa", "NG": "Africa", "KE": "Africa",
    "AU": "Oceania", "NZ": "Oceania",
}
COUNTRY_NAMES = {
    "INDIA": "IN", "SINGAPORE": "SG", "VIETNAM": "VN", "CHINA": "CN",
    "JAPAN": "JP", "KOREA": "KR", "THAILAND": "TH", "MALAYSIA": "MY",
    "INDONESIA": "ID", "USA": "US", "UNITED STATES": "US", "AMERICA": "US",
    "GERMANY": "DE", "FRANCE": "FR", "ITALY": "IT", "SPAIN": "ES",
    "UK": "GB", "BRITAIN": "GB", "ENGLAND": "GB", "BRAZIL": "BR",
    "AUSTRALIA": "AU", "UAE": "AE", "DUBAI": "AE",
}
REGIONS = ("Asia", "Europe", "North America", "South America", "Africa", "Oceania")


def supplier_country(location: str) -> str:
    loc = (location or "").strip()
    if "," in loc:
        return loc.rsplit(",", 1)[1].strip().upper()
    return loc.strip().upper()


def supplier_region(location: str) -> str:
    c = supplier_country(location)
    code = COUNTRY_NAMES.get(c, c)
    return COUNTRY_TO_REGION.get(code, "Unknown")


def _suppliers() -> dict:
    conn = get_conn()
    rows = {r[0]: dict(r) for r in conn.execute("SELECT * FROM supplier")}
    conn.close()
    return rows


def list_conditions(active_only: bool = False) -> list[dict]:
    init_table()
    conn = get_conn()
    q = "SELECT * FROM buyer_condition"
    if active_only:
        q += " WHERE active=1"
    rows = [dict(r) for r in conn.execute(q + " ORDER BY condition_id")]
    conn.close()
    return rows


def _num(tok: str) -> float | None:
    try:
        return float(tok.replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_condition(text: str) -> tuple[dict | None, str | None]:
    """Parse one NL condition. Returns (condition, None) or (None, error)."""
    t = (text or "").strip()
    if not t:
        return None, "empty condition. " + HINT
    m = re.search(r"(?:exclude|drop|remove|ban|blacklist)\s+(SUP-\d{3})", t, re.I)
    if m:
        return ({"kind": "EXCLUDE_SUPPLIER", "target": m.group(1).upper(),
                 "value_num": None,
                 "value_text": f"exclude {m.group(1).upper()}"}, None)
    m = re.search(r"(?:more than|over|above|max(?:imum)?|<=?|up to)\s*"
                  r"(\d+(?:\.\d+)?)\s*%[^.]*?(share|split|supplier|award)", t, re.I)
    pct = m.group(1) if m else None
    if pct is None:
        m = re.search(r"(share|split)[^.]*?(?:max(?:imum)?|<=?|no more than|under)"
                      r"\s*(\d+(?:\.\d+)?)\s*%", t, re.I)
        pct = m.group(2) if m else None
    if pct is not None:
        v = _num(pct)
        if v is not None and 0 < v <= 100:
            return ({"kind": "MAX_SUPPLIER_SHARE", "target": None,
                     "value_num": v, "value_text": f"max {v:g}% share per supplier"},
                    None)
    if re.search(r"shar|split|supplier|award", t, re.I) and re.search(
            r"more than|no more than|max|under|cap", t, re.I):
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
        if m:
            v = _num(m.group(1))
            if v is not None and 0 < v <= 100:
                return ({"kind": "MAX_SUPPLIER_SHARE", "target": None,
                         "value_num": v,
                         "value_text": f"max {v:g}% share per supplier"}, None)
    m = re.search(r"at least\s*(\d+)\s*suppliers?", t, re.I)
    if m and _num(m.group(1)) and int(float(m.group(1))) >= 1:
        v = int(float(m.group(1)))
        return ({"kind": "MIN_SUPPLIERS", "target": None, "value_num": v,
                 "value_text": f"at least {v} suppliers in the split"}, None)
    m = re.search(r"(?:lead(?:\s*time)?|deliver(?:y)?)[^.]*?"
                  r"(?:max(?:imum)?|under|within|<=?|no more than)\s*"
                  r"(\d+)\s*d(?:ays?)?", t, re.I) \
        or re.search(r"(\d+)\s*days?\s*max[^.]*?(?:lead|deliver)", t, re.I)
    if m:
        v = _num(next(g for g in m.groups() if g and g.strip().isdigit()))
        if v is not None and v > 0:
            return ({"kind": "MAX_LEAD_DAYS", "target": None, "value_num": v,
                     "value_text": f"award only offers with lead ≤ {v:g} days"},
                    None)
    if re.search(r"require.{0,20}quality.{0,20}pass|quality.{0,20}must.{0,20}pass|"
                 r"only.{0,20}quality.?pass", t, re.I):
        return ({"kind": "REQUIRE_QUALITY_PASS", "target": None, "value_num": None,
                 "value_text": "award only quality-eligible offers"}, None)
    m = re.search(r"valid[^.]*?(20\d\d-\d\d-\d\d)", t, re.I)
    if m:
        return ({"kind": "REQUIRE_VALID_UNTIL", "target": None, "value_num": None,
                 "value_text": m.group(1)}, None)
    m = re.search(r"(?:under|below|beneath|max(?:imum)?|<=?|up to|nothing above)\s*"
                  r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:per|\/)?\s*"
                  r"(?:unit|buyer unit)?", t, re.I)
    if m and _num(m.group(1)):
        v = _num(m.group(1))
        return ({"kind": "MAX_EFFECTIVE_COST", "target": None, "value_num": v,
                 "value_text": f"award only offers at or under ₹ {v:,.4f}/unit"},
                None)
    return None, f"could not understand {text!r}. " + HINT


def add_condition(text: str, source: str = "ui") -> dict:
    cond, err = parse_condition(text)
    if cond:
        return _store_legacy(cond, source)
    try:
        spec, desc = parse_v2(text)
        return _store_custom(spec, desc, source)
    except ValueError:
        pass
    spec, desc = model_parse_condition(text)
    return _store_custom(spec, desc, source + "+model")


def _store_legacy(cond: dict, source: str) -> dict:
    init_table()
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO buyer_condition (kind, target, value_num, value_text,"
        " active, source, created_at) VALUES (?,?,?,?,1,?,?)",
        (cond["kind"], cond.get("target"),
         cond.get("value_num"), cond.get("value_text"),
         source, datetime.now(timezone.utc).isoformat()))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"condition_id": cid, **cond}


def _store_custom(spec: dict, desc: str, source: str) -> dict:
    import json
    init_table()
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO buyer_condition (kind, target, value_num, value_text,"
        " active, source, created_at, spec) VALUES (?,?,?,?,1,?,?,?)",
        ("CUSTOM", None, None, desc, source,
         datetime.now(timezone.utc).isoformat(), json.dumps(spec)))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"condition_id": cid, "kind": "CUSTOM", "value_text": desc,
            "spec": spec}


SPEC_SYSTEM = """You translate buyer procurement conditions into JSON specs.
Output ONLY one JSON object, no prose. Either a spec:
{"effect":"exclude"|"require","entity":"supplier"|"offer",\
"scope":{"sku":"Item-001"|"line":7|"supplier":"SUP-001"}|null,\
"all":[{"attr":...,"op":...,"value":...}],"any":[...]}
or {"error":"<why, with an example that would work>"}.
supplier attrs: supplier_id, supplier_name, region, country, currency,\
payment_days, default_lead_time. Regions: Asia, Europe, North America,\
South America, Africa, Oceania.
offer attrs: lead_time_days, moq, quantity_match, quality_eligible,\
quote_valid_until (YYYY-MM-DD), effective_economic_cost, quoted_currency,\
supplier_id, line_number, sku_id.
ops: ==,!=,<,<=,>,>=,in,not_in. quantity_match is boolean (quoted amount \
equals required amount). "Only X" means require; "exclude/no/ban/outside" \
means exclude; "outside of Asia" means region != Asia. Supplier and SKU \
masters follow after a SUPPLIERS: line. SKU ids look like Item-001..Item-050 \
— normalize bare numbers ("36"→Item-036); if a referenced supplier, SKU, \
region or country is unknown, return error, never invent an id."""


def model_parse_condition(text: str, chat_fn=None) -> tuple[dict, str]:
    """Model fallback: strict JSON spec, validated against live masters."""
    import json
    from app.aerbot.llm import ChatResponse
    sups = _suppliers()
    menu = "; ".join(f"{sid} {s.get('supplier_name')} "
                     f"({supplier_country(s.get('location', ''))}/"
                     f"{supplier_region(s.get('location', ''))})"
                     for sid, s in sorted(sups.items()))
    chat_fn = chat_fn or _model_chat
    resp = chat_fn(SPEC_SYSTEM + "\nSUPPLIERS: " + menu,
                   [{"role": "user", "content": text}], [])
    try:
        obj = json.loads((resp.content or "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"model returned unparseable output for {text!r}. " + HINT)
    if not isinstance(obj, dict) or "error" in obj:
        err = str(obj.get("error", f"could not understand {text!r}.")).strip()
        raise ValueError(f"{err} {HINT}")
    spec = _validate_spec(obj, sups)
    return spec, _describe_spec(spec)


def _model_chat(system: str, messages, tools):
    from app.aerbot.llm import client_chat
    return client_chat(system, messages, tools)


def _validate_spec(obj: dict, sups: dict) -> dict:
    import json
    if obj.get("effect") not in ("exclude", "require"):
        raise ValueError("spec needs effect exclude|require. " + HINT)
    if obj.get("entity") not in SPEC_ATTRS:
        raise ValueError("spec needs entity supplier|offer. " + HINT)
    allowed = SPEC_ATTRS[obj["entity"]]
    for key in ("all", "any"):
        for c in obj.get(key, []) or []:
            if c.get("attr") not in allowed or c.get("op") not in SPEC_OPS:
                raise ValueError(f"unknown attr/op in {c}. " + HINT)
            a, v = c["attr"], c.get("value")
            if a == "region" and isinstance(v, str) and v not in REGIONS:
                raise ValueError(f"unknown region {v!r}. " + HINT)
            if a == "supplier_id" and isinstance(v, str) and v not in sups:
                hit = next((sid for sid, s in sups.items()
                            if v.lower() in (s.get("supplier_name") or "").lower()),
                           None)
                if not hit:
                    raise ValueError(f"unknown supplier {v!r}. " + HINT)
                c["value"] = hit
            if a == "sku_id" and isinstance(v, str):
                sku = _norm_sku_ref(v)
                if not sku:
                    raise ValueError(f"unknown SKU {v!r}. " + HINT)
                c["value"] = sku
    scope = obj.get("scope")
    if scope:
        if not isinstance(scope, dict) or len(scope) != 1:
            raise ValueError("scope must be one of sku|line|supplier. " + HINT)
        k, v = next(iter(scope.items()))
        if k == "sku":
            sku = _norm_sku_ref(str(v))
            if not sku:
                raise ValueError(f"unknown SKU {v!r}. " + HINT)
            scope[k] = sku
        elif k == "supplier" and isinstance(v, str) and v not in sups:
            raise ValueError(f"unknown supplier {v!r}. " + HINT)
        elif k not in ("sku", "line", "supplier"):
            raise ValueError("scope must be one of sku|line|supplier. " + HINT)
    return {"effect": obj["effect"], "entity": obj["entity"],
            "scope": scope, "all": obj.get("all") or [],
            "any": obj.get("any") or []}


def _norm_sku_ref(tok: str) -> str | None:
    m = re.search(r"Item[\s\-–_]*0*(\d{1,3})\b", tok, re.I)
    if m:
        return f"Item-{int(m.group(1)):03d}"
    m = re.search(r"\b0*(\d{1,3})\b", tok)
    if m and len(m.group(0)) >= 3:
        return f"Item-{int(m.group(1)):03d}"
    return None


def _describe_spec(spec: dict) -> str:
    bits = []
    for c in spec.get("all", []) + spec.get("any", []):
        bits.append(f"{c['attr']} {c['op']} {c['value']}")
    scope = spec.get("scope")
    extra = ""
    if scope:
        k, v = next(iter(scope.items()))
        extra = f" for {k} {v}"
    verb = "exclude where" if spec.get("effect") == "exclude" else "require"
    return f"{verb} {' AND '.join(bits)}{extra}"


def describe(cond: dict) -> str:
    if cond.get("kind") == "CUSTOM":
        return cond.get("value_text") or "custom rule"
    if cond["kind"] == "REQUIRE_VALID_UNTIL":
        return f"award only quotes valid through {cond.get('value_text')}"
    return cond.get("value_text") or cond["kind"]


def set_active(condition_id: int, active: bool) -> bool:
    init_table()
    conn = get_conn()
    cur = conn.execute("UPDATE buyer_condition SET active=? WHERE condition_id=?",
                       (1 if active else 0, condition_id))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def delete_condition(condition_id: int) -> bool:
    init_table()
    conn = get_conn()
    cur = conn.execute("DELETE FROM buyer_condition WHERE condition_id=?",
                       (condition_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def describe(cond: dict) -> str:
    if cond["kind"] == "REQUIRE_VALID_UNTIL":
        return f"award only quotes valid through {cond.get('value_text')}"
    return cond.get("value_text") or cond["kind"]


def filter_candidates(records: list, conditions: list[dict] | None = None):
    """Drop award candidates violating active buyer conditions. Returns
    (kept, applied_descriptions). Pure function over record attributes."""
    conds = conditions if conditions is not None else list_conditions(True)
    if not conds:
        return list(records), []
    kept, applied = [], []
    excluded = {c["target"] for c in conds if c["kind"] == "EXCLUDE_SUPPLIER"
                and c.get("target")}
    max_lead = min([c["value_num"] for c in conds
                    if c["kind"] == "MAX_LEAD_DAYS" and c.get("value_num")]
                   or [None])
    max_cost = min([c["value_num"] for c in conds
                    if c["kind"] == "MAX_EFFECTIVE_COST" and c.get("value_num")]
                   or [None])
    need_quality = any(c["kind"] == "REQUIRE_QUALITY_PASS" for c in conds)
    valid_dates = [c["value_text"] for c in conds
                   if c["kind"] == "REQUIRE_VALID_UNTIL" and c.get("value_text")]
    need_valid = max(valid_dates) if valid_dates else None
    import json
    customs = []
    sup_master = {}
    for c in conds:
        if c.get("kind") != "CUSTOM" or not c.get("spec"):
            continue
        try:
            customs.append((c, json.loads(c["spec"])))
        except (TypeError, ValueError):
            continue
    if customs:
        sup_master = {sid: s for sid, s in _suppliers().items()}
    for r in records:
        if getattr(r, "supplier_id", None) in excluded:
            continue
        if max_lead is not None and (getattr(r, "lead_time_days", 0) or 0) > max_lead:
            continue
        if need_quality and not getattr(r, "quality_eligible", False):
            continue
        if need_valid and (getattr(r, "quote_valid_until", "") or "") < need_valid:
            continue
        if max_cost is not None and (getattr(r, "effective_economic_cost", 0)
                                     or 0) > max_cost:
            continue
        if customs:
            ctx = record_context(r, sup_master)
            drop = False
            for _, spec in customs:
                if not scope_applies(spec, r):
                    continue
                hit = eval_spec(spec, ctx)
                if (spec.get("effect") == "exclude" and hit) or \
                   (spec.get("effect") == "require" and not hit):
                    drop = True
                    break
            if drop:
                continue
        kept.append(r)
    return kept, [describe(c) for c in conds]
