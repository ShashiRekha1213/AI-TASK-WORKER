"""Independent verification: re-reads the internal system and compares against the SOURCE PDF
(not against the agent's own memory or claims)."""

from collections import Counter
from config import APP_URL
from tools.system_tools import fetch_payables


def run(state, browser=None, shots_dir=None):
    rows = fetch_payables()
    delta = len(rows) - len(state.baseline)
    claim = (state.final or {}).get("status")
    checks, notes = {}, []
    f = state.facts
    src = next((v for v in state.seen_invoices.values() if v.get("invoice_no") == f.get("invoice_no")), None)

    if claim in ("success", "already_done"):
        # A success claim with no remembered invoice cannot be verified, so it must not pass.
        checks["claim_refers_to_a_specific_invoice"] = bool(f.get("invoice_no"))
        mine = [r for r in rows if r["invoice_no"] == f.get("invoice_no")]
        checks["record_exists_in_system"] = bool(mine)
        checks["exactly_one_record"] = len(mine) == 1
        if src and mine:
            checks["amount_matches_source_pdf"] = abs(mine[0]["amount"] - src["amount"]) < 0.005
            checks["due_date_matches_source_pdf"] = mine[0]["due_date"] == src["due_date"]
            checks["vendor_matches_source_pdf"] = (
                mine[0]["vendor"].casefold() == (src["vendor"] or "").casefold()
            )
        checks["new_records_created_this_run"] = (delta == 1) if claim == "success" else (delta == 0)
    else:  # declined / failed / no claim: nothing should have been written
        checks["no_unintended_records_created"] = delta == 0
    # global duplicate scan
    dups = [k for k, v in Counter((r["vendor"].casefold(), r["invoice_no"]) for r in rows).items() if v > 1]
    checks["no_duplicate_records_in_system"] = not dups

    if browser and shots_dir:
        try:
            from pathlib import Path

            Path(shots_dir).mkdir(parents=True, exist_ok=True)
            browser.page.goto(f"{APP_URL}/payables")
            out = Path(shots_dir) / "final_payables_page.png"
            browser.page.screenshot(path=str(out))
            state.evidence.append(str(out))
        except Exception as e:
            notes.append(f"final screenshot failed: {e}")
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "records_now": len(rows),
        "records_before": len(state.baseline),
        "notes": notes,
    }


STATUS_MAP = {
    "success": "COMPLETED",
    "already_done": "ALREADY_DONE",
    "declined_by_user": "DECLINED_BY_USER",
    "failed": "NOT_COMPLETED",
}


def final_status(state, verification):
    claim = (state.final or {}).get("status")
    if claim is None:
        return "INCOMPLETE"
    if not verification["passed"]:
        return "FAILED_VERIFICATION"
    return STATUS_MAP[claim]
