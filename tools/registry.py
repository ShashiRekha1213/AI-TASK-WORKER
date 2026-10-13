from . import file_tools, browser_tools, system_tools, human_tools
from .base import ToolResult

_ALL = file_tools.TOOLS + browser_tools.TOOLS + system_tools.TOOLS + human_tools.TOOLS
TOOLS = {t.name: t for t in _ALL}


def schemas():
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in _ALL]


def execute(ctx, name, args) -> ToolResult:
    t = TOOLS.get(name)
    if not t:
        return ToolResult(False, error=f"Unknown tool: {name}")
    try:
        return t.fn(ctx, **(args or {}))
    except TypeError as e:
        return ToolResult(False, error=f"Bad arguments for {name}: {e}")
    except Exception as e:
        return ToolResult(False, error=f"{name} crashed: {e}")
