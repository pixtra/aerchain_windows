"""Generate the 7 messy supplier artifacts in data/raw/ from the golden dataset.

Artifacts mirror the golden offers exactly (values, product codes, UOMs), so the
extraction harness in app.services.extraction can be regression-tested 1:1.

  SUP-001 Supplier_A_Quote.xlsx   (grid + header noise)
  SUP-002 Supplier_B_Quote.pdf    (reportlab table text)
  SUP-003 Supplier_C_Quote.xlsx
  SUP-004 Supplier_D_Rate_Card.jpg  + .ocr.txt sidecar (missing UOM on 2 rows)
  SUP-005 Supplier_E_Email.txt
  SUP-006 Supplier_F_Quote.pdf
  SUP-007 Supplier_G_Quote.xlsx

Run:  python -m scripts.generate_artifacts
"""
from __future__ import annotations

import os
import random

from app.seed_data import build

RAW = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/raw"))


def main() -> None:
    ds = build()
    os.makedirs(RAW, exist_ok=True)
    by_sup: dict[str, list] = {}
    for o in ds["offers"]:
        by_sup.setdefault(o.supplier_id, []).append(o)
    for fn in ("Supplier_A_Quote.xlsx", "Supplier_C_Quote.xlsx",
               "Supplier_G_Quote.xlsx"):
        pass  # created below
    _xlsx(by_sup["SUP-001"], "Supplier_A_Quote.xlsx")
    _xlsx(by_sup["SUP-003"], "Supplier_C_Quote.xlsx")
    _xlsx(by_sup["SUP-007"], "Supplier_G_Quote.xlsx")
    _pdf(by_sup["SUP-002"], "Supplier_B_Quote.pdf", "SwiftBox Crafts · Quote Sheet")
    _pdf(by_sup["SUP-006"], "Supplier_F_Quote.pdf", "PrimeCartons 9.6 · Quotation")
    _email(by_sup["SUP-005"], "Supplier_E_Email.txt")
    _image(by_sup["SUP-004"], "Supplier_D_Rate_Card.jpg")
    n = sum(len(v) for v in by_sup.values())
    print(f"artifacts -> {RAW}")
    print(f"offers mirrored: {n}")


def _code_line(o) -> str:
    lead = o.lead_time_days or 0
    moq = int(o.moq) if o.moq else "-"
    cur = o.quoted_currency or "INR"
    uom = o.quoted_uom or "UNIT"
    qty = o.quoted_quantity or 0
    return f"{o.supplier_product_code:>8} {qty:>9.1f} {uom:>6} {cur} {o.quoted_unit_price:>12.4f}   MOQ {moq:>9}   {lead}d   valid {o.quote_valid_until}"


def _xlsx(offers: list, filename: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    ws = Workbook().active
    ws.title = "Quotation"
    ws.append(["CONFIDENTIAL — QUOTATION", "", "", "", "", "", "", "", ""])
    ws.append([f"Supplier {filename[9]} · valid subject to acceptance", "", "", "", "", "", "", "", ""])
    ws.append([])
    ws.append(["Item No.", "SKU CODE", "DESCRIPTION", "PACK UNIT", "PRICE",
               "CURRENCY", "QTY", "MOQ", "LEAD (DAYS)", "VALID UNTIL"])
    for i, o in enumerate(sorted(offers, key=lambda x: x.supplier_product_code), start=1):
        ws.append([i, o.supplier_product_code, o.supplier_product_code,
                   o.quoted_uom or "UNIT", o.quoted_unit_price,
                   o.quoted_currency or "INR", o.quoted_quantity or 0,
                   int(o.moq) if o.moq else 0, o.lead_time_days or 0,
                   o.quote_valid_until])
    ws.append([])
    ws.append(["Notes: prices exclude taxes; MOQ 0 = no minimum;", "", "", "", "", "", "", "", ""])
    for row in ws.iter_rows(min_row=4):
        for c in row:
            c.font = Font(size=11)
    ws.parent.save(os.path.join(RAW, filename))


def _pdf(offers: list, filename: str, title: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    w, h = A4
    c = canvas.Canvas(os.path.join(RAW, filename), pagesize=A4)
    c.setFont("Courier", 8)
    c.drawString(40, h - 50, title)
    c.drawString(40, h - 62, "Item | Code    Qty       UOM   Currency         Price        MOQ     Lead  Valid")
    y = h - 82
    for o in sorted(offers, key=lambda x: x.supplier_product_code):
        c.drawString(40, y, _code_line(o))
        y -= 12
        if y < 40:
            c.showPage()
            c.setFont("Courier", 8)
            y = h - 50
    c.showPage()
    c.save()


def _email(offers: list, filename: str) -> None:
    lines = [
        "From: quotes@corrugatedco.example",
        "To: procurement@aerchain.example",
        "Subject: RFx 001 — corrugated & shipping materials — quotation",
        "",
        "Dear Buyer,",
        "PFA our best price list for the above RFx. Standard payment Net 45 days.",
        "Amt in INR, ex works. MOQ listed per line.",
        "",
        "SKU  QTY        UOM       CUR         PRICE       MOQ     LEAD  VALID",
    ]
    for o in sorted(offers, key=lambda x: x.supplier_product_code):
        moq = int(o.moq) if o.moq else 0
        lines.append(f"{o.supplier_product_code} {o.quoted_quantity or 0:>9.1f} {o.quoted_uom or 'UNIT':>6} {o.quoted_currency or 'INR'} {o.quoted_unit_price:>12.4f} {moq:>9} {o.lead_time_days or 0}d {o.quote_valid_until}")
    lines += ["", "Regards,", "Corrugated Co. India", "Sales Team"]
    with open(os.path.join(RAW, filename), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _image(offers: list, filename: str) -> None:
    from PIL import Image, ImageDraw, ImageFont
    cur = (offers[0].quoted_currency or "INR") if offers else "INR"
    img = Image.new("RGB", (760, 360), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 12)
    except Exception:
        font = ImageFont.load_default()
    d.text((20, 14), f"D N Packaging — RATE CARD ({cur})", fill="black", font=font)
    d.text((20, 30), "Prices ex works; no tax included. Prices firm until 2026-11-30.",
           fill="black", font=font)
    d.rectangle([16, 46, 744, 318], outline="gray")
    side = ["Each line: CODE QTY UNIT CURRENCY PRICE", ""]
    for o in sorted(offers, key=lambda x: x.supplier_product_code):
        uom = str(o.quoted_uom or "UNIT")
        price = o.quoted_unit_price
        if o.quoted_uom == "UNKNOWN":
            uom = ""  # defective scan → extractor must flag unresolved uom
        qty = o.quoted_quantity or 0
        if o.quoted_uom == "UNKNOWN":
            qty = o.required_quantity  # OCR shows required qty when unit missing
        side.append(f"{o.supplier_product_code} {qty:>9.1f} {uom:>6} {cur} {price:>12.4f}")
    y = 56
    for ln in side:
        d.text((26, y), ln, fill="black", font=font)
        y += 15
    img.save(os.path.join(RAW, filename), "JPEG", quality=88)
    # OCR sidecar — what the OCR model would emit after scanning the image
    ocr = []
    for o in sorted(offers, key=lambda x: x.supplier_product_code):
        price = o.quoted_unit_price
        if o.quoted_uom == "UNKNOWN":
            ocr.append(f"{o.supplier_product_code} {o.required_quantity:>9.1f}      {cur} {price:>12.4f} {o.lead_time_days or 0}d valid {o.quote_valid_until}".rstrip())
            ocr.append(f"  ~ row manual review flagged: unit of measure not detected")
        else:
            ocr.append(f"{o.supplier_product_code} {o.quoted_quantity or 0:>9.1f} {o.quoted_uom:>6} {cur} {price:>12.4f} {o.lead_time_days or 0}d valid {o.quote_valid_until}")
    with open(os.path.join(RAW, filename).rsplit(".", 1)[0] + ".ocr.txt", "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(ocr) + "\n")


if __name__ == "__main__":
    main()