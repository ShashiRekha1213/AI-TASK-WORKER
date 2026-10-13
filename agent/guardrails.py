"""Safety checks enforced IN CODE before irreversible actions (the model cannot talk its way past them).

Irreversible action = clicking a form submit button in the internal system.
Checks, in order: facts complete -> form matches facts -> duplicate -> latest/ambiguity
-> low extraction confidence (ask) -> amount over threshold (ask).
"""

from config import APPROVAL_THRESHOLD
from tools.base import ToolResult
from tools.human_tools import AFFIRM
from tools.system_tools import fetch_payables

REQUIRED = ["vendor", "invoice_no", "amount", "due_date"]


def _block(msg, hint=None):
    return ToolResult(False, error=msg, blocked=True, hint=hint)


def _ask(ctx, question, kind):
    ans = ctx.human.ask(question, kind, None)
    ctx.state.asks.append({"kind": kind, "question": question, "answer": ans, "by": "guardrail"})
    if AFFIRM.match(ans):
        ctx.state.flags[f"{kind}_granted"] = True
        return True
    ctx.state.flags["declined"] = True
    return False


def enforce(ctx, name, args):
    """Return None to allow, or a blocked ToolResult."""
    if name != "click" or not ctx.browser.is_submit(args.get("selector", "")):
        return None
    st, f = ctx.state, ctx.state.facts

    missing = [k for k in REQUIRED if k not in f]
    if missing:
        return _block(
            f"Cannot submit: facts not yet remembered: {missing}", "Call remember() for each field first."
        )

    form = ctx.browser.form_values()
    diffs = []
    try:
        if abs(float(form.get("amount", "nan")) - float(f["amount"])) > 0.005:
            diffs.append("amount")
    except ValueError:
        diffs.append("amount")
    for k in ("vendor", "invoice_no", "due_date"):
        if str(form.get(k, "")).strip().casefold() != str(f[k]).strip().casefold():
            diffs.append(k)
    if diffs:
        return _block(
            f"Form values differ from remembered facts for: {diffs}. Form={form}",
            "Re-type the fields from memory, then submit.",
        )

    try:
        rows = fetch_payables()
    except Exception as e:
        return _block(f"Cannot check for duplicates (system unreachable): {e}")
    if any(
        r["invoice_no"].casefold() == str(f["invoice_no"]).casefold()
        and r["vendor"].casefold() == str(f["vendor"]).casefold()
        for r in rows
    ):
        return _block(
            f"Duplicate: {f['invoice_no']} is already in the system.",
            "Do not submit. finish(status='already_done').",
        )

    same_vendor = [
        v
        for v in st.seen_invoices.values()
        if (v.get("vendor") or "").casefold() == str(f["vendor"]).casefold() and v.get("invoice_date")
    ]
    chosen = next((v for v in same_vendor if v["invoice_no"] == f["invoice_no"]), None)
    if chosen and same_vendor and not st.flags.get("clarified"):
        newest = max(v["invoice_date"] for v in same_vendor)
        if chosen["invoice_date"] < newest:
            return _block(
                f"{chosen['invoice_no']} is not the latest invoice (a newer one exists, dated {newest}).",
                "Pick the newest, or ask_user(kind='clarify') if the user wants an older one.",
            )
        tied = [v["invoice_no"] for v in same_vendor if v["invoice_date"] == newest]
        if len(tied) > 1:
            return _block(
                f"Ambiguous: {tied} share the latest date {newest}.",
                "ask_user(kind='clarify') which one to enter.",
            )

    if chosen and chosen.get("confidence") == "low" and not st.flags.get("confirm_granted"):
        q = (
            f"Extraction of {chosen['invoice_no']} is uncertain ({'; '.join(chosen['reasons'])}). "
            f"I read amount={f['amount']:,.2f}, due_date={f['due_date']}. Confirm these values?"
        )
        if not _ask(ctx, q, "confirm"):
            return _block("User declined / did not confirm the extracted values. Not submitting.")

    if float(f["amount"]) > APPROVAL_THRESHOLD and not st.flags.get("approve_granted"):
        q = f"Amount {f['amount']:,.2f} exceeds the auto-approval limit of {APPROVAL_THRESHOLD:,.2f}. Approve entering {f['invoice_no']} for {f['vendor']}?"
        if not _ask(ctx, q, "approve"):
            return _block("User declined approval for the large amount. Not submitting.")
    return None
