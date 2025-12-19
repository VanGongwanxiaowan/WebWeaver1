"""Tools used by agents."""

from __future__ import annotations

from webweaver.tools.executor import ToolCall, ToolCallResult, ToolExecutor
from webweaver.tools.extended_tools import register_extended_tools
from webweaver.tools.registry import (
    FunctionTool,
    Tool,
    ToolRegistry,
    ToolResult,
    get_registry,
    register_function_tool,
    register_tool,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "FunctionTool",
    "ToolExecutor",
    "ToolCall",
    "ToolCallResult",
    "get_registry",
    "register_tool",
    "register_function_tool",
    "register_extended_tools",
]
