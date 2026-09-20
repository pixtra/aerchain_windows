"""Extraction harness — parses raw supplier artifacts into offer rows.

Artifacts live in data/raw/ and mirror the golden offers (see
scripts/generate_artifacts.py). Each extractor returns a list of rows:

    {sku_code, description, quantity, unit_uom, unit_price, currency,
     uc_on_uom, moq, lead_days, valid_until, discount_tiers, n_best_price,
     unresolved: [fields that could not be keyed]}

Parsers are intentionally messy-tolerant: headers are located by keyword,
numbers are regex-spotted from cell text, units are normalized loosely.
"""
from __future__ import annotations

import json
import os
import re

RAW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/raw"))

_NUM = r"-?\d[\d,]*(?:\.\d+)?"
_QTY_UNIT = re.compile(r"(?P<qty>%s)\s*(?P<unit>[a-zA-Z]+)" % _NUM, re.I)
_PRICE = re.compile(r"(?P<cur>USD|INR|EUR|GBP|฿|₹|€|£)?\s*%s" % _NUM)
_UOM_ALIAS = {"UNIT": "UNIT", "UN": "UNIT", "PCS": "UNIT", "PC": "UNIT",
               "PIECE": "UNIT", "PIECES": "UNIT", "NOS": "UNIT", "NO": "UNIT",
               "PK": "PACK", "PACK": "PACK", "CTN": "CARTON", "CARTON": "CARTON",
               "KG": "KG", "ROLL": "ROLL", "RL": "ROLL", "REEL": "REEL",
               "BAG": "BAG", "BOX": "BOX", "EA": "EA", "SQM": "SQM", "M2": "SQM"}


# Canonicalization: different suppliers write the same fact different ways
# ("Quantity->12 inr" vs "Qty: 12 rupees"). Spelling variants are folded to one
# canonical form BEFORE positional parsing, so every artifact type normalizes
# identically. Only delimiters/labels/words are folded — never digits.
_CUR_WORDS = [
    ("INR", r"₹|\bINR\b|\bRUPEES?\b|\bRS\.?(?!\w)|\bRE\.?(?!\w)"),
    ("USD", r"\$|\bUSD\b|\bDOLLARS?\b"),
    ("EUR", r"€|\bEUR\b|\bEUROS?\b"),
    ("GBP", r"£|\bGBP\b|\bPOUNDS?\b"),
]
_QTY_PRICE_LABELS = r"\b(QUANTITY|QTY|QUANT|QNTY|PRICE|RATE|AMOUNT|COST)\.?\s*[:=\-–—]?"


def _canon_line(ln: str) -> str:
    s = _canon_common(ln)
    s = re.sub(_QTY_PRICE_LABELS, " ", s, flags=re.I)  # drop qty/price labels
    return re.sub(r"\s+", " ", s).strip()


def _canon_common(ln: str) -> str:
    """Shared half of canonicalization: arrows and currency words only.
    Card layouts keep their Quantity/Price labels, so they use this."""
    s = re.sub(r"[-–—]*>+|=>|<[-–—]+|@", " ", ln)  # arrows / @ -> space
    for code, pat in _CUR_WORDS:
        s = re.sub(pat, code, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def normalize_uom(token: str) -> str:
    key = token.strip().upper()
    return _UOM_ALIAS.get(key, key)


_CODE_RE = re.compile(r"^[A-Z]{1,2}-\d{3}$")


def extract_xlsx(path: str) -> list[dict]:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    grid = [[c.value for c in row] for row in ws.iter_rows()]
    header_idx = _find_header(grid, ("SKU", "DESCRIPTION", "QTY", "UNIT", "PRICE"))
    if header_idx is None:
        return []
    heads = [_norm_col(c) for c in grid[header_idx]]
    rows = []
    for r in grid[header_idx + 1:]:
        if _row_blank(r):
            continue
        rec = _from_heads(heads, r)
        if rec and _CODE_RE.match(rec["sku_code"]):
            rows.append(rec)
    return rows


def _find_header(grid, keys):
    for i, row in enumerate(grid[:15]):
        norm = [_norm_col(c) for c in row]
        if all(any(k in h for h in norm) for k in keys):
            return i
    return None


def extract_pdf_text(path: str) -> list[dict]:
    from pypdf import PdfReader
    reader = PdfReader(path)
    lines = []
    for page in reader.pages:
        for ln in (page.extract_text() or "").splitlines():
            lines.append(ln.strip())
    if any(lines):
        return _parse_keyvalue_rows(lines)
    # scanned PDF (no text layer): render pages and OCR them for real
    return _parse_ocr_rows(_ocr_pdf_pages(path))


def _ocr_pdf_pages(path: str) -> list[str]:
    """Render PDF pages with pdftoppm and OCR each one. Returns text lines."""
    import subprocess
    import tempfile
    from PIL import Image
    import pytesseract
    out = []
    with tempfile.TemporaryDirectory(prefix="ktq_pdf_") as tmp:
        subprocess.run(["pdftoppm", "-png", "-r", "200", path,
                        os.path.join(tmp, "pg")],
                       check=True, capture_output=True, timeout=300)
        for fn in sorted(os.listdir(tmp)):
            if not fn.endswith(".png"):
                continue
            img = Image.open(os.path.join(tmp, fn)).convert("L")
            text = pytesseract.image_to_string(
                img, config="--psm 6",
                lang=os.environ.get("KTQ_OCR_LANG", "eng"))
            out += [ln.strip() for ln in _ocr_normalize(text).splitlines()
                    if ln.strip()]
    return out


def pdf_source_engine(path: str) -> str:
    """Name the real backend a PDF will take: text layer or scanned OCR."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        if any((p.extract_text() or "").strip() for p in reader.pages):
            return "pypdf-text"
    except Exception:
        pass
    return "tesseract-scanned-pdf"


def extract_email_text(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
    return _parse_keyvalue_rows(lines)


def extract_docx(path: str) -> list[dict]:
    """Word quotes: commercials live in paragraphs AND tables. Both are
    linearized to text lines, then parsed by the same keyvalue grammar —
    plus card-block fallback for prose layouts."""
    from docx import Document
    doc = Document(path)
    lines = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            lines.append(t)
    for tbl in doc.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append("  ".join(cells))
    rows = _parse_keyvalue_rows(lines)
    if not rows:
        rows = parse_card_blocks("\n".join(_canon_common(l) for l in lines))
    return rows


def extract_image_ocr(path: str) -> list[dict]:
    """Rate-card image: read with real OCR (Tesseract). Nothing is simulated —
    misreads surface as unresolved/LOW-confidence rows, exactly what happens
    with real supplier scans. Returns (rows, engine) where engine names the
    OCR backend used, so callers can label results honestly."""
    try:
        text = _ocr_text(path)
    except Exception as e:  # tesseract missing/unreadable: scanner-sidecar fallback
        rows = _sidecar_rows(path)
        for r in rows:
            r["ocr_engine"] = f"sidecar-fallback ({e})"
        return rows
    lines = [ln.strip() for ln in _ocr_normalize(text).splitlines() if ln.strip()]
    rows = _parse_ocr_rows(lines)
    for r in rows:
        r["ocr_engine"] = "tesseract"
    return rows


def _ocr_text(path: str) -> str:
    from PIL import Image
    import pytesseract
    img = Image.open(path).convert("L")
    if max(img.size) < 1600:  # upscale small scans; cheap accuracy win
        img = img.resize((img.width * 2, img.height * 2))
    return pytesseract.image_to_string(
        img, config="--psm 6",
        lang=os.environ.get("KTQ_OCR_LANG", "eng"))


def _ocr_normalize(text: str) -> str:
    """Delimiter/whitespace repair only — never guesses digits. Fixes the two
    systematic Tesseract merges on rate cards: digit→letter (160.0CARTON) and
    UOM→currency (BOXINR), plus dropped dashes in product codes (D003)."""
    text = re.sub(r"(\d)([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"(?i)\b(BOX|CARTON|CTN|REEL|ROLL|BAG|UNIT|KG|PACK|PCS|PC)"
                 r"(INR|USD|EUR|GBP)\b", r"\1 \2", text)
    text = re.sub(r"\b([A-Z]{1,2})[.\-–_]?\s?(\d{3})\b", r"\1-\2", text)
    return text


_KNOWN_UOMS = set(_UOM_ALIAS.values())

_OCR_ROW = re.compile(
    r"(?P<code>[A-Z]{1,2}-\d{2,4})\s+"
    r"(?P<qty>%s)?(?!\d)\s*(?P<unit>[A-Za-z]*?)\s*(?P<cur>USD|INR|EUR|GBP)?\s*(?P<price>%s)(?!\d)"
    r"(?:\s+(?P<lead>%s)\s*d)?(?:\s*valid\s*(?P<valid>[0-9-]+))?"
    % (_NUM, _NUM, _NUM), re.I)


def _parse_ocr_rows(lines: list[str]) -> list[dict]:
    rows = []
    for raw in lines:
        ln = _canon_line(raw)
        m = _OCR_ROW.search(ln)
        if not m:
            continue
        g = m.groupdict()
        unit = normalize_uom(g.get("unit") or "")
        qty, price = _to_float(g.get("qty")), _to_float(g.get("price"))
        unresolved = []
        if unit not in _KNOWN_UOMS:
            unresolved.append("uom")
        if qty is None or price is None:
            unresolved.append("numbers")
        rows.append({
            "sku_code": g["code"].upper(), "description": "",
            "quantity": qty, "unit_price": price,
            "currency": (g.get("cur") or "INR").upper(),
            "unit_uom": unit or "UNKNOWN", "uc_on_uom": unit or "UNKNOWN",
            "moq": None, "lead_days": _to_int(g.get("lead")),
            "valid_until": g.get("valid"),
            "unresolved": unresolved, "ocr_confidence": "LOW",
            "raw_text": raw,
        })
    if not rows:
        rows = parse_card_blocks("\n".join(lines))
    return rows


_CARD_SKU = re.compile(r"(?:SKU\s*)?Item[\s\-–_]*0*(\d{1,3})\b", re.I)
_CARD_QTY = re.compile(r"(?:Quantity|Qty)\s*[:=\-–—]?\s*(%s)(?!\d)" % _NUM, re.I)
_CARD_PRICE = re.compile(
    r"(?:Quoted|Price|Rate)\s*[:=\-–—]?\s*(USD|INR|EUR|GBP|₹|\$|€|£)?\s*(%s)(?!\d)\s*/?\s*([A-Za-z]*)"
    % _NUM, re.I)
_CARD_SUP = re.compile(r"Supplier\s*Name\s*:\s*([A-Za-z0-9 .&'\-]+)", re.I)


def parse_card_blocks(text: str) -> list[dict]:
    """Product-card layout: supplier, price, SKU and quantity on separate
    lines (phone screenshots of quotes). Facts are associated across lines
    into one row; anything missing is flagged, never filled in."""
    canon = _canon_common(text)
    m_sku = _CARD_SKU.search(canon)
    m_qty = _CARD_QTY.search(canon)
    m_price = _CARD_PRICE.search(canon)
    if not (m_sku and m_price):
        return []
    n = int(m_sku.group(1))
    unit = normalize_uom((m_price.group(3) or "").strip())
    qty = _to_float(m_qty.group(1)) if m_qty else None
    price = _to_float(m_price.group(2))
    cur = (m_price.group(1) or "INR").upper()
    cur = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}.get(cur, cur)
    m_sup = _CARD_SUP.search(text)
    unresolved = []
    if unit not in _KNOWN_UOMS:
        unresolved.append("uom")
    if qty is None:
        unresolved.append("quantity")
    if price is None:
        unresolved.append("price")
    return [{
        "sku_code": f"Item-{n:03d}", "description": "",
        "quantity": qty, "unit_price": price, "currency": cur,
        "unit_uom": unit or "UNKNOWN", "uc_on_uom": unit or "UNKNOWN",
        "moq": None, "lead_days": None, "valid_until": None,
        "unresolved": unresolved, "ocr_confidence": "LOW",
        "supplier_name_hint": m_sup.group(1).strip(" |") if m_sup else None,
        "layout": "card",
        "raw_text": " | ".join(t for t in (text.splitlines()) if t.strip())[:400],
    }]


def _sidecar_rows(path: str) -> list[dict]:
    """Legacy scanner-workflow fallback: .ocr.txt next to the image."""
    sidecar = path.rsplit(".", 1)[0] + ".ocr.txt"
    if not os.path.exists(sidecar):
        return []
    with open(sidecar, "r", encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
    rows = []
    for ln in lines:
        m = _ROW_RE.search(ln)
        if not m:
            continue
        g = m.groupdict()
        unit = g.get("unit") or ""
        row = {
            "sku_code": g["code"], "description": "",
            "quantity": _to_float(g["qty"]), "unit_price": _to_float(g["price"]),
            "currency": g.get("cur") or "USD", "unit_uom": unit,
            "uc_on_uom": unit, "moq": _to_float(g.get("moq")),
            "lead_days": _to_int(g.get("lead")), "valid_until": g.get("valid"),
            "unresolved": [] if normalize_uom(unit) else ["uom"],
        }
        rows.append(row)
    return rows


_ROW_RE = re.compile(
    r"(?P<code>[A-Z]{1,2}-\d{3})\s+"
    r"(?P<qty>%s)(?!\d)\s*(?P<unit>[A-Za-z]*?)\s*(?P<cur>USD|INR|EUR|GBP|฿|₹|€|£)?\s*(?P<price>%s)(?!\d)"
    r"\s*(?:\s+(?:MOQ\s+)?(?P<moq>%s|-))?(?!\d)\s*(?P<lead>%s)(?!\d)\s*d"
    r"(?:\s*valid\s*(?P<valid>[0-9-]+))?" % (_NUM, _NUM, _NUM, _NUM), re.I)


_TIER_RES = [
    re.compile(r"(?P<pct>\d+(?:\.\d+)?)\s*%%\s*(?:off\s+)?(?:above|over|for|on|from)\s+"
               r"(?P<qty>%s)(?!\d)" % _NUM, re.I),
    re.compile(r"(?P<qty>%s)(?!\d)\s*\+\s*[:=\-]?\s*(?P<pct>\d+(?:\.\d+)?)\s*%%" % _NUM,
               re.I),
]


def parse_tier_hints(lines: list[str]) -> list[dict]:
    """Extract discount-tier rules from free text, e.g. '5% above 500 units'
    or '500+: 3%'. Returns [{discount_percentage, supplier_min_qty,
    source_text}] — real rules, attached to promoted offers on ingest."""
    out, seen = [], set()
    for raw in lines:
        ln = _canon_line(raw)
        for rx in _TIER_RES:
            m = rx.search(ln)
            if not m:
                continue
            try:
                pct, qty = float(m.group("pct")), float(m.group("qty"))
            except (TypeError, ValueError):
                continue
            if not (0 < pct < 100) or qty < 0 or (pct, qty) in seen:
                continue
            seen.add((pct, qty))
            out.append({"discount_percentage": pct, "supplier_min_qty": qty,
                        "source_text": raw.strip()})
    return sorted(out, key=lambda r: r["supplier_min_qty"])


def _parse_keyvalue_rows(lines: list[str]) -> list[dict]:
    rows = []
    for raw in lines:
        ln = _canon_line(raw)
        m = _ROW_RE.search(ln)
        if not m:
            continue
        g = m.groupdict()
        unit = g.get("unit") or ""
        rows.append({
            "sku_code": g["code"], "description": "",
            "quantity": _to_float(g["qty"]), "unit_price": _to_float(g["price"]),
            "currency": g.get("cur") or "INR", "unit_uom": unit or "UNKNOWN",
            "uc_on_uom": unit or "UNKNOWN", "moq": _to_float(g.get("moq")),
            "lead_days": _to_int(g.get("lead")), "valid_until": g.get("valid"),
            "unresolved": [] if unit else ["uom"], "raw_text": raw,
        })
    return rows


# ----------------------------------------------------------------- helpers
def _find_header_by_keywords(grid, keys=(("CODE",), ("QTY",), ("PRICE",))):
    for ln, row in enumerate(grid[:12]):
        norm = [_norm_col(c) for c in row]
        if all(any(k in h for h in norm) for k in keys):
            return ln
    return None


def _norm_col(v):
    return str(v or "").strip().upper().replace("\n", " ").replace("_", " ")


def _row_blank(row):
    return all(v is None or str(v).strip() == "" for v in row)


def _from_heads(heads, cells):
    def get(*alts):
        for a in alts:
            for idx, h in enumerate(heads):
                if a in h and idx < len(cells) and cells[idx] is not None:
                    return cells[idx]
        return None

    code = str(get("SKU CODE", "CODE", "ITEM") or "").strip()
    if not code:
        return None
    qty = _first_float(str(get("QTY", "QUANTITY") or ""))
    price = _first_float(str(get("PRICE", "UNIT PRICE", "RATE") or ""))
    unit = _norm_col(get("UNIT", "UOM", "PACK UOM"))
    unresolved = []
    if normalize_uom(unit) and unit != "UNKNOWN":
        unresolved.append("normalize")
    return {
        "sku_code": code, "description": "",
        "quantity": qty, "unit_price": price,
        "currency": _norm_col(get("CURRENCY", "CUR") or "") or "INR",
        "unit_uom": unit or "UNKNOWN", "uc_on_uom": unit or "UNKNOWN",
        "moq": _first_float(str(get("MOQ") or "")),
        "lead_days": _first_int(str(get("LEAD", "LEAD TIME", "DELIVERY") or "")),
        "valid_until": str(get("VALID UNTIL", "VALIDITY", "VALID TO") or "") or None,
        "unresolved": unresolved,
    }


def _first_float(s):
    m = re.search(_NUM, s)
    return _to_float(m.group(0)) if m else None


def _first_int(s):
    m = re.search(_NUM, s)
    return _to_int(m.group(0)) if m else None


def _to_float(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(s):
    try:
        return int(float(str(s).replace(",", "")))
    except (TypeError, ValueError):
        return None


def extract_all(raw_dir: str = RAW_DIR) -> dict[str, dict]:
    """Return {filename: {rows, type, parsed}}. Deterministic, self-contained."""
    out = {}
    for fn in sorted(os.listdir(raw_dir)):
        if fn.startswith("."):
            continue
        path = os.path.join(raw_dir, fn)
        try:
            if fn.lower().endswith(".xlsx"):
                out[fn] = {"type": "EXCEL", "engine": "openpyxl",
                           "rows": extract_xlsx(path)}
            elif fn.lower().endswith(".docx"):
                out[fn] = {"type": "WORD", "engine": "python-docx",
                           "rows": extract_docx(path)}
            elif fn.lower().endswith(".pdf"):
                out[fn] = {"type": "PDF", "engine": pdf_source_engine(path),
                           "rows": extract_pdf_text(path)}
            elif fn.lower().endswith((".jpg", ".jpeg", ".png")):
                out[fn] = {"type": "IMAGE", "engine": "tesseract",
                           "rows": extract_image_ocr(path)}
            elif fn.lower().endswith((".eml", ".txt")):
                if fn.lower().endswith(".ocr.txt"):
                    continue
                out[fn] = {"type": "EMAIL", "engine": "regex-text",
                           "rows": extract_email_text(path)}
        except Exception as e:  # don't kill the whole batch on one artifact
            out[fn] = {"type": "?", "rows": [], "error": str(e)}
    return out