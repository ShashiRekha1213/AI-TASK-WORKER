"""Offline test of the local-LLM (MLX Mistral) brain using a scripted fake generator (no model, no GPU).

Checks: JSON tool calls are parsed out of messy model text, a malformed reply is retried,
results flow back as TOOL_RESULT messages, and the verifier still overrules a false success.

    python -m tests.test_mlx_brain
"""

import json
import requests

import config
from agent import loop
from agent.brains import MLXBrain, extract_tool_call
from company_app.app import start_server
from tools.browser_tools import Browser
from tools.human_tools import ScriptedHuman


def call(tool, **args):
    return f"Next step.\n{json.dumps({'tool': tool, 'args': args})}"


def test_extract_tool_call_variants():
    assert extract_tool_call('I will search.\n{"tool": "search_files", "args": {"query": "Acme"}}') == (
        "I will search.", "search_files", {"query": "Acme"})
    t, n, a = extract_tool_call('```json\n{"name": "finish", "arguments": {"status": "failed", "summary": "x"}}\n```')
    assert n == "finish" and a["status"] == "failed"
    assert extract_tool_call("no json here")[1] is None
    assert extract_tool_call('{"unrelated": 1} then {"tool":"read_page","args":{}}')[1] == "read_page"


def make_brain(replies):
    replies, seen = list(replies), []

    def gen(messages):
        seen.append(messages)
        return replies.pop(0)

    return MLXBrain("goal", generate_fn=gen), seen


def run(replies):
    requests.post(f"{config.APP_URL}/admin/reset")
    brain, seen = make_brain(replies)
    browser = Browser()
    try:
        report = loop.run("goal", ScriptedHuman(), browser, brain=brain, run_name="_unit_mlx", verbose=False)
    finally:
        browser.close()
    return seen, report


def test_results_fed_back_retry_on_garbage_and_false_success_caught():
    seen, report = run([
        call("search_files", query="Acme"),
        "Hmm, let me think about that for a moment.",  # malformed -> should be retried
        call("finish", status="success", summary="Done (but I entered nothing)."),
    ])
    assert any("TOOL_RESULT (search_files)" in m["content"] and "acme_1003.pdf" in m["content"] for m in seen[1])
    assert any("no valid tool call" in m["content"] for m in seen[2])
    assert all(m["role"] in ("user", "assistant") for m in seen[0])  # Mistral template needs alternation
    assert [m["role"] for m in seen[0]] == ["user"]
    assert report["status"] == "FAILED_VERIFICATION", report["status"]


if __name__ == "__main__":
    test_extract_tool_call_variants()
    srv = start_server()
    try:
        test_results_fed_back_retry_on_garbage_and_false_success_caught()
    finally:
        srv.stop()
    print("mlx-brain plumbing tests: PASS")
