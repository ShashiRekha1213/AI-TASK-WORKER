"""Generate sample invoice PDFs (3 different layouts, some messy)."""

import sys
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import INVOICE_DIR


def money(x):
    return f"{x:,.2f}"


def template_a(path, vendor, no, date, due, items):
    """Clean layout with explicit labels."""
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, vendor)
    y -= 30
    c.setFont("Helvetica", 11)
    for line in [
        f"Invoice No: {no}",
        f"Invoice Date: {date}",
        f"Due Date: {due}",
        "Bill To: Northwind Traders Pvt Ltd",
    ]:
        c.drawString(50, y, line)
        y -= 18
    y -= 10
    sub = 0
    for desc, qty, price in items:
        c.drawString(50, y, f"{desc}   x{qty}   @ {money(price)}   = {money(qty*price)}")
        y -= 16
        sub += qty * price
    tax = round(sub * 0.05, 2)
    y -= 10
    c.drawString(50, y, f"Subtotal: {money(sub)}")
    y -= 16
    c.drawString(50, y, f"Tax (5%): {money(tax)}")
    y -= 16
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Amount Due: ${money(sub+tax)}")
    c.save()
    return round(sub + tax, 2)


def template_b(path, vendor, no, date_long, due_long, total):
    """Different labels and long-form dates."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 800, vendor)
    c.setFont("Helvetica", 11)
    for i, line in enumerate(
        [
            f"INVOICE # {no}",
            f"Date: {date_long}",
            f"Payment due by: {due_long}",
            "Freight & handling services",
            f"Total Amount: USD {money(total)}",
        ]
    ):
        c.drawString(50, 770 - i * 18, line)
    c.save()


def template_c_messy(path, vendor, ref, dated, subtotal, tax, total, prev):
    """Messy: no due date (only 'Net 30'), noisy numbers, bare TOTAL label."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Courier", 10)
    c.drawString(40, 810, vendor.upper() + "  -- TAX INVOICE --  pg 1/1")
    lines = [
        f"Ref: {ref}      Dated {dated}      Terms: Net 30",
        "",
        "Consulting hrs ........ 120 @ 35.00",
        "Cloud mgmt retainer ...  0",
        f"Previous balance carried fwd:   {money(prev)}",
        f"Subtotal    {money(subtotal)}",
        f"GST 18%     {money(tax)}",
        f"TOTAL       {money(total)}",
        "",
        "Thank you for your business. Bank: HDFC 0012345 IFSC HDFC0001",
    ]
    for i, l in enumerate(lines):
        c.drawString(40, 780 - i * 15, l)
    c.save()


def main():
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    for f in INVOICE_DIR.glob("*.pdf"):
        f.unlink()
    d = INVOICE_DIR
    # Acme Supplies: 3 clean invoices, one clear latest (ACM-1003)
    template_a(
        d / "acme_1001.pdf",
        "Acme Supplies",
        "ACM-1001",
        "2026-01-10",
        "2026-02-09",
        [("Widgets", 100, 10.0), ("Bolts", 50, 4.0)],
    )
    template_a(
        d / "acme_1002.pdf",
        "Acme Supplies",
        "ACM-1002",
        "2026-02-12",
        "2026-03-14",
        [("Widgets", 80, 10.0), ("Gaskets", 30, 4.0)],
    )
    template_a(
        d / "acme_1003.pdf",
        "Acme Supplies",
        "ACM-1003",
        "2026-03-15",
        "2026-04-14",
        [("Widgets", 150, 10.0), ("Brackets", 85, 8.5)],
    )
    # Globex Logistics: two invoices with the SAME latest date -> ambiguous
    template_b(
        d / "globex_0398.pdf", "Globex Logistics", "GLX-0398", "February 20, 2026", "March 22, 2026", 1420.00
    )
    template_b(
        d / "globex_0411.pdf", "Globex Logistics", "GLX-0411", "March 20, 2026", "April 19, 2026", 1800.00
    )
    template_b(
        d / "globex_0412.pdf", "Globex Logistics", "GLX-0412", "March 20, 2026", "April 19, 2026", 2150.00
    )
    # Initech Services: messy latest invoice
    template_c_messy(
        d / "initech_old.pdf", "Initech Services", "IN-2025-112", "01 Dec 2025", 3000.00, 540.00, 3540.00, 0.0
    )
    template_c_messy(
        d / "initech_latest.pdf",
        "Initech Services",
        "IN-2026-031",
        "15 Mar 2026",
        4200.00,
        756.00,
        4956.00,
        1200.00,
    )
    # Umbrella Corp: latest is a large amount (needs approval)
    template_a(
        d / "umbrella_4990.pdf",
        "Umbrella Corp",
        "UMB-4990",
        "2026-02-02",
        "2026-03-04",
        [("Lab consumables", 10, 100.0)],
    )
    template_a(
        d / "umbrella_5001.pdf",
        "Umbrella Corp",
        "UMB-5001",
        "2026-03-28",
        "2026-04-27",
        [("Industrial reactors", 5, 3400.0), ("Install", 1, 800.0)],
    )
    # Hooli Cloud: will be pre-seeded in the system (duplicate scenario)
    template_b(d / "hooli_2201.pdf", "Hooli Cloud", "HOO-2201", "March 5, 2026", "April 4, 2026", 3200.00)
    print(f"Generated {len(list(d.glob('*.pdf')))} invoices in {d}")


if __name__ == "__main__":
    main()
