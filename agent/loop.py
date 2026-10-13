"""The agent loop:  decide -> guardrail -> act -> observe -> (recover) -> ... -> finish -> independent verify."""

import time
from pathlib import Path
import config
from tools import registry
from tools.base import ToolContext
from tools.system_tools import fetch_payables
from . import guardrails, verifier
from .brains import make_brain
from .logger import RunLogger
from .state import AgentState


def _soft_failure(name, result):
    """A tool call that 'succeeded' technically but the page reported an error."""
    if name == "click" and result.ok:
        alerts = (result.data or {}).get("alerts", [])
        return bool(alerts) and not any("saved successfully" in a.lower() for a in alerts)
    return False


def run(goal, human, browser, brain="heuristic", run_name=None, verbose=True, on_event=None):
    run_dir = Path(config.RUNS_DIR) / (run_name or time.strftime("run_%Y%m%d_%H%M%S"))
    state = AgentState(goal)
    state.baseline = fetch_payables()
    ctx = ToolContext(state, browser, human, shots_dir=run_dir / "screenshots")
    log, nudged = RunLogger(run_dir, verbose, on_event), False
    brain_obj = (
        make_brain(brain, goal) if isinstance(brain, str) else brain
    )  # allow injecting a custom brain (tests)
    if verbose:
        print(
            f"\n=== GOAL: {goal}\n    brain={brain if isinstance(brain, str) else type(brain).__name__}  run_dir={run_dir}"
        )

    while state.steps < config.MAX_STEPS and not state.final:
        decision = brain_obj.decide(state)
        log.say(decision.thought)
        if not decision.calls:
            if nudged:
                break
            nudged = True
            brain_obj.nudge()
            continue
        results = []
        for call in decision.calls:
            state.steps += 1
            result = guardrails.enforce(ctx, call.name, call.input) or registry.execute(
                ctx, call.name, call.input
            )
            note = ""
            if not result.ok or _soft_failure(call.name, result):
                state.failures[call.name] = state.failures.get(call.name, 0) + 1
                note = "failure counted"
                if _soft_failure(call.name, result):
                    note = "soft failure: page showed an error"
                if state.failures[call.name] > config.MAX_RETRIES_PER_TOOL:
                    result.hint = "Retry limit reached for this tool. Stop retrying: ask_user or finish(status='failed')."
            elif state.failures.get(call.name):
                state.recoveries.append(
                    f"{call.name}: succeeded after {state.failures[call.name]} failure(s)"
                )
                state.failures[call.name] = 0
                note = "RECOVERED"
            log.log(
                state.steps,
                decision.thought if call is decision.calls[0] else "",
                call.name,
                call.input,
                result,
                note,
            )
            results.append(result)
            if state.final:
                break
        if state.final:
            break
        brain_obj.observe(decision, results)

    verification = verifier.run(state, browser, ctx.shots_dir)
    status = verifier.final_status(state, verification)
    report = {
        "goal": goal,
        "status": status,
        "summary": (state.final or {}).get(
            "summary", "Agent stopped without finishing (step cap or no action)."
        ),
        "agent_claim": (state.final or {}).get("status"),
        "verification": verification,
        "asks": state.asks,
        "failures": {k: v for k, v in state.failures.items() if v},
        "recoveries": state.recoveries,
        "evidence": state.evidence,
        "steps": state.steps,
        "run_dir": str(run_dir),
        "facts": state.facts,
    }
    log.write_markdown(report)
    if verbose:
        print(
            f"\n=== RESULT: {status}\n    {report['summary']}\n    verification passed={verification['passed']} {verification['checks']}"
        )
    return report
