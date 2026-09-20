"""RFx drafting — talk an RFx into existence without touching the live
decision layer. Drafts are explicitly NOT live: no offers, no award, no
coverage. A draft is scope + lines + questionnaire + terms + deadline,
exportable as JSON, and clearly labeled DRAFT everywhere it appears."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.database import get_conn


def init_tables():
    conn = get_conn()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rfx_draft (
            draft_id TEXT PRIMARY KEY, name TEXT, category TEXT,
            terms TEXT, deadline TEXT, created_at TEXT, source TEXT
        )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rfx_draft_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id TEXT,
            line_no INTEGER, sku_id TEXT, quantity REAL, uom TEXT,
            lead_days INTEGER, note TEXT
        )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rfx_draft_sku (
            draft_id TEXT, sku_id TEXT, sku_name TEXT, buyer_uom TEXT,
            specification TEXT, created_at TEXT,
            PRIMARY KEY (draft_id, sku_id)
        )""")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rfx_draft_line)")]
    if "sku_origin" not in cols:
        conn.execute("ALTER TABLE rfx_draft_line ADD COLUMN sku_origin TEXT DEFAULT 'master'")
    conn.commit()
    conn.close()


class NeedConfirm(Exception):
    """Unknown SKUs need explicit buyer confirmation (with name + UOM)."""
    def __init__(self, unknown, parsed_ok):
        self.unknown = unknown
        self.parsed_ok = parsed_ok
        super().__init__(
            f"{len(unknown)} unknown SKU(s): "
            + ", ".join(u["sku"] or f'"{u.get("name")}"' for u in unknown)
            + ". Confirm creation with a name and buyer UOM for each.")


def next_free_item_code(exclude=None):
    """Next unused Item-NNN code from the master catalogue (suggestion only —
    nothing is created until the buyer confirms)."""
    exclude = set(exclude or [])
    conn = get_conn()
    nums = set()
    for (sid,) in conn.execute("SELECT sku_id FROM sku"):
        m = re.fullmatch(r"Item-(\d{3})", sid or "")
        if m:
            nums.add(int(m.group(1)))
    conn.close()
    n = 1
    while n in nums or f"Item-{n:03d}" in exclude:
        n += 1
    return f"Item-{n:03d}"


def parse_draft_lines(text: str) -> tuple[list[dict], list[str], list[dict]]:
    """Returns (parsed, hard_errors, unknown_skus). Unknown SKUs are proposals,
    never invented: each is {sku, line_no, raw} awaiting buyer confirmation."""
    conn = get_conn()
    valid = {r[0].upper(): r[0] for r in conn.execute("SELECT sku_id FROM sku")}
    conn.close()
    parsed, errors, unknown = [], [], []
    seen_unknown = set()
    for i, raw in enumerate((text or "").splitlines(), 1):
        ln = raw.strip()
        if not ln:
            continue
        m = re.search(r"Item[\s\-–_]*0*(\d{1,3})", ln, re.I)
        sku = f"Item-{int(m.group(1)):03d}" if m else None
        if not sku:
            # free-text item ("Bla x 2000"): propose the leading text as a
            # name; the confirm step assigns a real code, never invented here
            g = re.search(r"^(.+?)\s*[x×:]\s*([\d,]+(?:\.\d+)?)", ln, re.I)
            if g and len(g.group(1).strip()) >= 2:
                um2 = re.search(r"\b(BOX|CARTON|REEL|ROLL|BAG|EA|UNIT|KG)\b", ln, re.I)
                ld2 = re.search(r"(\d+)\s*d(?:ays?)?", ln, re.I)
                q2 = g.group(2)
                unknown.append({"sku": None, "name": g.group(1).strip()[:60],
                                "line_no": i, "raw": raw.strip()[:80]})
                parsed.append({"sku_id": None, "line_no": i,
                               "quantity": float(q2.replace(",", "")),
                               "uom": um2.group(1).upper() if um2 else None,
                               "lead_days": int(ld2.group(1)) if ld2 else None,
                               "note": raw.strip()[:200], "sku_missing": True,
                               "_unknown": unknown[-1]})
                continue
            errors.append(f"line {i}: no SKU (want Item-NNN): {raw.strip()[:60]}")
            continue
        q = re.search(r"[x×:]\s*([\d,]+(?:\.\d+)?)|\bqty\s*([\d,]+(?:\.\d+)?)|\b(\d[\d,]*)\s*(?:units|pcs|nos)\b", ln, re.I)
        qty = None
        if q:
            qty = next((g for g in q.groups() if g), None)
        um = re.search(r"\b(BOX|CARTON|REEL|ROLL|BAG|EA|UNIT|KG)\b", ln, re.I)
        ld = re.search(r"(\d+)\s*d(?:ays?)?", ln, re.I)
        entry = {"sku_id": valid.get(sku.upper(), sku), "line_no": i,
                 "quantity": float(qty.replace(",", "")) if qty else None,
                 "uom": um.group(1).upper() if um else None,
                 "lead_days": int(ld.group(1)) if ld else None,
                 "note": raw.strip()[:200]}
        if sku.upper() not in valid:
            entry["sku_missing"] = True
            if sku.upper() not in seen_unknown:
                seen_unknown.add(sku.upper())
                unknown.append({"sku": sku, "line_no": i,
                                "raw": raw.strip()[:80]})
            entry["_unknown"] = unknown[-1]
        parsed.append(entry)
    return parsed, errors, unknown


KNOWN_UOMS = {"BOX", "CARTON", "REEL", "ROLL", "BAG", "EA", "UNIT", "KG"}


def create_draft(name: str, category: str = "", lines_text: str = "",
                 terms: str = "", deadline: str = "",
                 questions: list[str] | None = None,
                 source: str = "ui",
                 new_skus: list[dict] | None = None) -> dict:
    init_tables()
    parsed, errors, unknown = parse_draft_lines(lines_text)
    if errors:
        raise ValueError("draft has bad lines: " + "; ".join(errors[:5]))
    if not parsed:
        raise ValueError("draft needs at least one 'Item-NNN x QTY' line")
    no_qty = [i + 1 for i, l in enumerate(parsed) if not l["quantity"]]
    if no_qty:
        raise ValueError("lines missing quantity (want 'Item-NNN x QTY'): "
                         + ", ".join(f"line {i}" for i in no_qty[:5]))
    if deadline and not re.fullmatch(r"20\d\d-\d\d-\d\d", deadline.strip()):
        raise ValueError(f"bad deadline {deadline!r} (want YYYY-MM-DD)")
    defined = {}
    used_codes = set()
    for s in new_skus or []:
        ln_no = s.get("line_no")
        sid = (s.get("sku_id") or "").strip().upper()
        if not sid:
            # buyer confirmed name+UOM, left the code to us: next free number
            sid = next_free_item_code(exclude=used_codes).upper()
        if not re.fullmatch(r"[A-Z]{1,4}-?\d{1,4}", sid):
            raise ValueError(f"bad SKU code {s.get('sku_id')!r} (want like Item-036)")
        if not (s.get("name") or "").strip():
            raise ValueError(f"new SKU {sid} needs a name")
        if (s.get("uom") or "").strip().upper() not in KNOWN_UOMS:
            raise ValueError(f"new SKU {sid} needs a buyer UOM from "
                             f"{sorted(KNOWN_UOMS)}")
        m = re.fullmatch(r"([A-Z]{1,4})-?(\d{1,4})", sid)
        display = f"{m.group(1).title()}-{int(m.group(2)):03d}" if m else sid
        used_codes.add(display)
        for key in ({sid, ln_no} - {None}):
            defined[key] = {"sku_id": display, "sku_name": s["name"].strip(),
                            "buyer_uom": s["uom"].strip().upper(),
                            "specification": (s.get("spec") or "").strip()[:200]}
    still_missing = []
    for idx, l in enumerate(parsed):
        if not l.get("sku_missing"):
            continue
        hit = defined.get(l.get("line_no")) or defined.get(
            (l.get("sku_id") or "").upper())
        if hit:
            l["_def"] = hit
        else:
            still_missing.append(l["_unknown"])
    if still_missing:
        sugg = set()
        for u in still_missing:
            code = next_free_item_code(exclude=sugg)
            sugg.add(code)
            u["suggested_code"] = code
        raise NeedConfirm(still_missing, len(parsed))
    conn = get_conn()
    row = conn.execute("SELECT MAX(CAST(SUBSTR(draft_id, 4) AS INTEGER))"
                       " FROM rfx_draft").fetchone()[0]
    did = f"DF-{(row or 0) + 1:03d}"
    conn.execute("INSERT INTO rfx_draft VALUES (?,?,?,?,?,?,?)",
                 (did, name or f"Draft RFx {did}", category, terms, deadline,
                  datetime.now(timezone.utc).isoformat(), source))
    seen_defs = set()
    for s in defined.values():
        if s["sku_id"] in seen_defs:
            continue
        seen_defs.add(s["sku_id"])
        conn.execute("INSERT OR IGNORE INTO rfx_draft_sku VALUES (?,?,?,?,?,?)",
                     (did, s["sku_id"], s["sku_name"], s["buyer_uom"],
                      s["specification"],
                      datetime.now(timezone.utc).isoformat()))
    for i, l in enumerate(parsed, 1):
        hit = l.get("_def")
        conn.execute("INSERT INTO rfx_draft_line (draft_id, line_no, sku_id,"
                     " quantity, uom, lead_days, note, sku_origin)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (did, i, (hit["sku_id"] if hit else l["sku_id"]),
                      l["quantity"], l["uom"], l["lead_days"], l["note"],
                      "draft" if hit else "master"))
    conn.commit()
    conn.close()
    return {"draft_id": did, "name": name, "lines": len(parsed),
            "questions": questions or [],
            "skus_created": sorted({v["sku_id"] for v in defined.values()}),
            "status": "DRAFT — not live, no offers, no award"}


def list_drafts() -> list[dict]:
    init_tables()
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT d.*, (SELECT COUNT(*) FROM rfx_draft_line l"
        " WHERE l.draft_id=d.draft_id) AS line_count FROM rfx_draft d"
        " ORDER BY draft_id")]
    conn.close()
    return rows


def get_draft(draft_id: str) -> dict | None:
    init_tables()
    conn = get_conn()
    d = conn.execute("SELECT * FROM rfx_draft WHERE draft_id=?",
                     (draft_id,)).fetchone()
    if not d:
        conn.close()
        return None
    out = dict(d)
    out["lines"] = [dict(r) for r in conn.execute(
        "SELECT line_no, sku_id, quantity, uom, lead_days, note, sku_origin"
        " FROM rfx_draft_line WHERE draft_id=? ORDER BY line_no", (draft_id,))]
    out["new_skus"] = [dict(r) for r in conn.execute(
        "SELECT sku_id, sku_name, buyer_uom, specification FROM rfx_draft_sku"
        " WHERE draft_id=?", (draft_id,))]
    conn.close()
    return out


def delete_draft(draft_id: str) -> bool:
    init_tables()
    conn = get_conn()
    conn.execute("DELETE FROM rfx_draft_line WHERE draft_id=?", (draft_id,))
    conn.execute("DELETE FROM rfx_draft_sku WHERE draft_id=?", (draft_id,))
    cur = conn.execute("DELETE FROM rfx_draft WHERE draft_id=?", (draft_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok
