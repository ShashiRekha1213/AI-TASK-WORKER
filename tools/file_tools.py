"""Invoice discovery and PDF reading + field extraction."""

import re
from datetime import datetime, timedelta
from pathlib import Path
import pdfplumber
from config import INVOICE_DIR
from .base import Tool, ToolResult

_DATE_FORMATS = ["%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y"]
_DATE_RE = r"\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]{3,9} \d{4}|[A-Za-z]{3,9} \d{1,2}, \d{4}"
_AMT = r"(?:USD|INR|\$|Rs\.?|€|£)?\s*([\d,]+\.\d{2})"
# ordered by specificity: most specific label wins
_AMOUNT_LABELS = [
    "amount due",
    "balance due",
    "balance payable",
    "total due",
    "total amount",
    "grand total",
    "total",
]


def parse_date(s: str):
    s = s.strip().rstrip(".,")
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _read_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages).strip()


def extract_fields(text: str) -> dict:
    """Rule-based extraction with a confidence flag + reasons (shown to the human when low)."""
    reasons = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    vendor = re.split(r"\s+--|\s{2,}", lines[0])[0].strip().title() if lines else None

    m = re.search(
        r"(?:Invoice\s*(?:No\.?|Number|#)\s*[:#]?\s*|INVOICE\s*#\s*|Ref:\s*)([A-Z]{2,5}-[\w-]+)", text, re.I
    )
    invoice_no = m.group(1).upper() if m else None
    if not invoice_no:
        reasons.append("invoice number not found")

    m = re.search(rf"(?<!Due )(?:Invoice Date|Dated|Date)\s*:?\s*({_DATE_RE})", text)
    inv_date = parse_date(m.group(1)) if m else None
    if not inv_date:
        reasons.append("invoice date not found/parsable")

    due = None
    m = re.search(rf"(?:Due Date|Payment due by|Due)\s*:?\s*({_DATE_RE})", text, re.I)
    if m:
        due = parse_date(m.group(1))
    if not due:
        n = re.search(r"Net\s*(\d+)", text, re.I)
        if n and inv_date:
            due = inv_date + timedelta(days=int(n.group(1)))
            reasons.append(f"no explicit due date; derived from invoice date + Net {n.group(1)} terms")
        else:
            reasons.append("due date not found")

    amount = None
    for label in _AMOUNT_LABELS:
        found = re.findall(rf"(?<![A-Za-z]){label}\s*[:\-]?\s*{_AMT}", text, re.I)
        if found:
            vals = {float(x.replace(",", "")) for x in found}
            amount = max(vals)
            if len(vals) > 1:
                reasons.append(f"multiple conflicting '{label}' values")
            if label == "total":
                nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+\.\d{2}", text)]
                if len(nums) > 4:
                    reasons.append("amount taken from bare 'TOTAL' on a cluttered page")
            break
    if amount is None:
        reasons.append("amount not found")

    return {
        "vendor": vendor,
        "invoice_no": invoice_no,
        "invoice_date": inv_date.isoformat() if inv_date else None,
        "due_date": due.isoformat() if due else None,
        "amount": amount,
        "confidence": "low" if reasons else "high",
        "reasons": reasons,
    }


def search_files(ctx, query: str) -> ToolResult:
    tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
    hits = []
    for p in sorted(Path(INVOICE_DIR).glob("*.pdf")):
        try:
            text = _read_text(p)
        except Exception:
            continue
        header = (p.stem + " " + (text.splitlines()[0] if text else "")).lower()
        if tokens and all(t in header for t in tokens):
            hits.append(p.name)
    return ToolResult(
        True,
        {"query": query, "matches": hits, "count": len(hits)},
        hint=None if hits else "No match. Try a shorter/partial vendor name once, then report not found.",
    )


def read_pdf(ctx, path: str) -> ToolResult:
    p = Path(INVOICE_DIR) / Path(path).name  # sandboxed to the invoice folder
    if not p.exists():
        return ToolResult(False, error=f"File not found: {path}")
    try:
        text = _read_text(p)
    except Exception as e:
        return ToolResult(False, error=f"PDF read failed: {e}")
    if not text:
        return ToolResult(
            False,
            error="PDF has no text layer (scanned image?)",
            hint="OCR needed; ask the user instead of guessing.",
        )
    fields = extract_fields(text)
    ctx.state.seen_invoices[p.name] = fields
    return ToolResult(True, {"file": p.name, "fields": fields, "raw_text": text[:1200]})


TOOLS = [
    Tool(
        "search_files",
        "Find invoice PDFs whose vendor/file name matches the query (e.g. a vendor name).",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        search_files,
    ),
    Tool(
        "read_pdf",
        "Read an invoice PDF and extract vendor, invoice_no, invoice_date, due_date, amount (+ confidence and reasons).",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        read_pdf,
    ),
]
