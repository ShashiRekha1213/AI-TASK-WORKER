"""Read-back from the internal system + agent memory."""

import requests
from config import APP_URL
from .base import Tool, ToolResult


def fetch_payables():
    r = requests.get(f"{APP_URL}/api/payables", timeout=5)
    r.raise_for_status()
    return r.json()


def get_payables(ctx, vendor: str | None = None) -> ToolResult:
    try:
        rows = fetch_payables()
    except Exception as e:
        return ToolResult(False, error=f"Cannot reach internal system: {e}")
    if vendor:
        rows = [r for r in rows if vendor.lower() in r["vendor"].lower()]
    return ToolResult(True, {"count": len(rows), "payables": rows})


def remember(ctx, key: str, value) -> ToolResult:
    """Remember invoice facts only when they are supported by a PDF read in this run."""
    if key not in {"vendor", "invoice_no", "amount", "due_date", "invoice_date"}:
        return ToolResult(False, error=f"Unsupported fact key: {key!r}")

    if key == "amount":
        try:
            value = float(str(value).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            return ToolResult(False, error=f"amount must be numeric, got {value!r}")

    # Prevent the LLM from inventing a value and then satisfying the submit guardrail.
    # Facts must match at least one invoice extracted by read_pdf during this run.
    if not ctx.state.seen_invoices:
        return ToolResult(
            False,
            error=f"Cannot remember {key!r}: no invoice PDF has been read yet.",
            hint="Call search_files, then read_pdf on the matching PDF before remembering invoice facts.",
        )

    supported = []
    for fields in ctx.state.seen_invoices.values():
        source_value = fields.get(key)
        if source_value is None:
            continue
        if key == "amount":
            try:
                if abs(float(source_value) - float(value)) <= 0.005:
                    supported.append(source_value)
            except (TypeError, ValueError):
                pass
        elif str(source_value).strip().casefold() == str(value).strip().casefold():
            supported.append(source_value)
    if not supported:
        return ToolResult(
            False,
            error=f"Refusing to remember unsupported {key}={value!r}; it does not match any extracted invoice.",
            hint="Use the exact value returned by read_pdf. Do not use placeholders or infer missing fields.",
        )

    ctx.state.facts[key] = value
    return ToolResult(True, {"remembered": {key: value}, "all_facts": ctx.state.facts})


TOOLS = [
    Tool(
        "get_payables",
        "List payables already saved in the internal system (optionally filter by vendor). Use to check duplicates and to verify.",
        {"type": "object", "properties": {"vendor": {"type": "string"}}, "required": []},
        get_payables,
    ),
    Tool(
        "remember",
        "Store a fact in memory. Use keys: vendor, invoice_no, amount, due_date, invoice_date.",
        {
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": ["string", "number"]}},
            "required": ["key", "value"],
        },
        remember,
    ),
]
