"""Tool call executor for parsing and executing tool calls from agent output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from webweaver.logging import get_logger
from webweaver.tools.registry import ToolRegistry, ToolResult, get_registry

logger = get_logger(__name__)

_TOOL_CALL_OPEN = "<" + "tool_call" + ">"
_TOOL_CALL_CLOSE = "</" + "tool_call" + ">"
_TOOL_CALL_RE = re.compile(
    r"{}\s*(?P<json>\{{.*?\}})\s*{}".format(_TOOL_CALL_OPEN, _TOOL_CALL_CLOSE),
    re.DOTALL,
)


@dataclass
class ToolCall:
    """Represents a tool call request."""

    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        """Create ToolCall from dictionary."""
        return cls(
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
        )


@dataclass
class ToolCallResult:
    """Result of executing a tool call."""

    tool_call: ToolCall
    result: ToolResult
    formatted_response: str


class ToolExecutor:
    """Executor for parsing and executing tool calls."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        """Initialize tool executor.

        Args:
            registry: Tool registry to use. If None, uses global registry.
        """
        self._registry = registry or get_registry()

    def parse_tool_calls(self, text: str) -> list[ToolCall]:
        """Parse tool calls from agent output.

        Args:
            text: Agent output text.

        Returns:
            List of parsed ToolCall objects.
        """
        tool_calls: list[ToolCall] = []
        for match in _TOOL_CALL_RE.finditer(text):
            try:
                json_str = match.group("json")
                data = json.loads(json_str)
                tool_call = ToolCall.from_dict(data)
                if tool_call.name:
                    tool_calls.append(tool_call)
            except Exception as e:
                logger.warning(
                    "Failed to parse tool call",
                    extra={"raw": json_str[:200] if "json_str" in locals() else "", "error": str(e)},
                )
        return tool_calls

    def execute_tool_call(
        self,
        tool_call: ToolCall,
        *,
        require_approval: bool = False,
        approval_callback: Any | None = None,
    ) -> ToolCallResult:
        """Execute a single tool call.

        Args:
            tool_call: Tool call to execute.
            require_approval: Whether approval is required.
            approval_callback: Optional approval callback.

        Returns:
            ToolCallResult with execution result.
        """
        result = self._registry.execute(
            tool_call.name,
            tool_call.arguments,
            require_approval=require_approval,
            approval_callback=approval_callback,
        )
        formatted = self._format_tool_response(tool_call.name, result)
        return ToolCallResult(tool_call=tool_call, result=result, formatted_response=formatted)

    def execute_tool_calls(
        self,
        text: str,
        *,
        require_approval: bool = False,
        approval_callback: Any | None = None,
    ) -> list[ToolCallResult]:
        """Parse and execute all tool calls in text.

        Args:
            text: Agent output containing tool calls.
            require_approval: Whether approval is required for all tools.
            approval_callback: Optional approval callback.

        Returns:
            List of ToolCallResult objects.
        """
        tool_calls = self.parse_tool_calls(text)
        results: list[ToolCallResult] = []
        for tool_call in tool_calls:
            result = self.execute_tool_call(
                tool_call,
                require_approval=require_approval,
                approval_callback=approval_callback,
            )
            results.append(result)
        return results

    @staticmethod
    def _format_tool_response(tool_name: str, result: ToolResult) -> str:
        """Format tool result for agent consumption.

        Args:
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Formatted response string.
        """
        parts: list[str] = []
        parts.append("<tool_response>")
        parts.append(f"<tool>{tool_name}</tool>")
        if result.success:
            if isinstance(result.content, (dict, list)):
                parts.append("<result>")
                parts.append(json.dumps(result.content, ensure_ascii=False, indent=2))
                parts.append("</result>")
            elif result.content:
                parts.append("<result>")
                parts.append(str(result.content))
                parts.append("</result>")
            else:
                parts.append("<result>success</result>")
        else:
            parts.append("<error>")
            parts.append(result.error or "Unknown error")
            parts.append("</error>")
        parts.append("</tool_response>")
        return "\n".join(parts)

