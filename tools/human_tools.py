"""Human-in-the-loop channel + ask_user / finish tools."""

import re
from .base import Tool, ToolResult

AFFIRM = re.compile(
    r"^\s*(y|yes|yep|approve|approved|ok|okay|confirm|confirmed|go ahead|proceed|correct)\b", re.I
)


class CLIHuman:
    def ask(self, question, kind="clarify", options=None):
        print(f"\n[AGENT ASKS - {kind}] {question}" + (f"\n  options: {options}" if options else ""))
        return input("  your answer> ").strip()


class ScriptedHuman:
    """Deterministic user for tests: answers by question kind, records the transcript."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.transcript = []

    def ask(self, question, kind="clarify", options=None):
        ans = self.answers.get(kind, "no")
        self.transcript.append({"kind": kind, "question": question, "answer": ans})
        return ans


def ask_user(ctx, question: str, kind: str = "clarify", options: list | None = None) -> ToolResult:
    ans = ctx.human.ask(question, kind, options)
    ctx.state.asks.append({"kind": kind, "question": question, "answer": ans})
    if kind == "clarify":
        ctx.state.flags["clarified"] = True
    elif AFFIRM.match(ans):
        ctx.state.flags[f"{kind}_granted"] = True
    return ToolResult(True, {"user_answer": ans})


def finish(ctx, status: str, summary: str) -> ToolResult:
    ctx.state.final = {"status": status, "summary": summary}
    return ToolResult(True, {"finished": True})


TOOLS = [
    Tool(
        "ask_user",
        "Ask the human a question. kind='clarify' (which invoice? missing info), 'approve' (permission for risky action) or 'confirm' (verify uncertain values).",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "kind": {"type": "string", "enum": ["clarify", "approve", "confirm"]},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question", "kind"],
        },
        ask_user,
    ),
    Tool(
        "finish",
        "End the task. status: success | already_done | declined_by_user | failed. Summary must state what was done and the evidence.",
        {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["success", "already_done", "declined_by_user", "failed"],
                },
                "summary": {"type": "string"},
            },
            "required": ["status", "summary"],
        },
        finish,
    ),
]
