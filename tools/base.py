"""Tool primitives. Tools never raise to the agent: failures are returned as data."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    blocked: bool = False  # True when a guardrail (not the tool itself) refused
    hint: str | None = None  # recovery suggestion shown to the agent

    def to_text(self) -> str:
        import json

        d = {"ok": self.ok}
        if self.data is not None:
            d["data"] = self.data
        if self.error:
            d["error"] = self.error
        if self.hint:
            d["hint"] = self.hint
        if self.blocked:
            d["blocked_by_guardrail"] = True
        return json.dumps(d, default=str, ensure_ascii=False)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., ToolResult]


@dataclass
class ToolContext:
    """Everything a tool may touch. The agent loop owns one per run."""

    state: Any
    browser: Any
    human: Any
    shots_dir: Any = None
