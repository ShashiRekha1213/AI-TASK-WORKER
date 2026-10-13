"""Offline test of the Claude brain's plumbing using a fake Anthropic client (no API key, no network).

It checks that the loop turns model tool_use blocks into real tool calls, feeds results back as
tool_result blocks, and that the verifier still overrules a false "success" claim.

    python -m tests.test_claude_brain
"""

import requests
from types import SimpleNamespace as NS

import config
from agent import loop
from agent.brains import ClaudeBrain
from company_app.app import start_server
from tools.browser_tools import Browser
from tools.human_tools import ScriptedHuman


def tool_use(i, name, **inp):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input=inp)


class FakeClient:
    """Plays back a fixed list of assistant turns and records what the agent sent back."""

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.seen.append(kw["messages"][-1])
        return NS(content=self.turns.pop(0))


def make_brain(turns):
    brain = ClaudeBrain.__new__(ClaudeBrain)  # skip __init__: no API key needed
    brain.client = FakeClient(turns)
    brain.messages = [{"role": "user", "content": "goal"}]
    return brain


def run(turns):
    requests.post(f"{config.APP_URL}/admin/reset")
    brain = make_brain(turns)
    browser = Browser()
    try:
        report = loop.run(
            "goal", ScriptedHuman(), browser, brain=brain, run_name="_unit_claude", verbose=False
        )
    finally:
        browser.close()
    return brain, report


def test_tool_results_are_fed_back_and_false_success_is_caught():
    turns = [
        [NS(type="text", text="Looking for the vendor."), tool_use(1, "search_files", query="Acme")],
        [tool_use(2, "finish", status="success", summary="Done (but I entered nothing).")],
    ]
    brain, report = run(turns)
    first_result = brain.client.seen[1]["content"][0]
    assert first_result["type"] == "tool_result" and first_result["tool_use_id"] == "tu_1"
    assert "acme_1003.pdf" in first_result["content"]
    assert report["status"] == "FAILED_VERIFICATION", report["status"]


def test_unknown_tool_is_returned_as_error_not_raised():
    turns = [
        [tool_use(1, "delete_everything")],
        [tool_use(2, "finish", status="failed", summary="gave up")],
    ]
    brain, report = run(turns)
    assert brain.client.seen[1]["content"][0]["is_error"] is True
    assert report["status"] == "NOT_COMPLETED"


if __name__ == "__main__":
    srv = start_server()
    try:
        test_tool_results_are_fed_back_and_false_success_is_caught()
        test_unknown_tool_is_returned_as_error_not_raised()
    finally:
        srv.stop()
    print("claude-brain plumbing tests: PASS")
