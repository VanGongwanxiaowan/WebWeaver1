"""Tool registry and execution framework.

This module provides a unified tool calling system inspired by deepagents,
allowing agents to register and invoke tools dynamically.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field

from webweaver.logging import get_logger

logger = get_logger(__name__)


class ToolResult(BaseModel):
    """Result from a tool execution."""

    success: bool = True
    content: str | dict | list | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
    """Base class for tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM."""

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool.

        Args:
            **kwargs: Tool arguments.

        Returns:
            ToolResult with execution result.
        """

    def get_schema(self) -> dict[str, Any]:
        """Get JSON schema for tool arguments.

        Returns:
            JSON schema dictionary.
        """
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }


class FunctionTool(Tool):
    """Tool wrapper for a Python function."""

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        description: str,
        schema: dict[str, Any] | None = None,
    ) -> None:
        """Initialize function tool.

        Args:
            name: Tool name.
            func: Python function to wrap.
            description: Tool description.
            schema: Optional JSON schema for arguments.
        """
        self._name = name
        self._func = func
        self._description = description
        self._schema = schema or self._infer_schema(func)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the wrapped function."""
        try:
            result = self._func(**kwargs)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(success=True, content=result)
        except Exception as e:
            logger.exception("Tool execution failed", extra={"tool": self._name})
            return ToolResult(success=False, error=str(e))

    def get_schema(self) -> dict[str, Any]:
        return self._schema

    @staticmethod
    def _infer_schema(func: Callable[..., Any]) -> dict[str, Any]:
        """Infer schema from function signature."""
        import inspect

        sig = inspect.signature(func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            param_type = param.annotation if param.annotation != inspect.Parameter.empty else "string"
            properties[param_name] = {"type": str(param_type)}
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {"type": "object", "properties": properties, "required": required}


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self) -> None:
        """Initialize tool registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register.
        """
        self._tools[tool.name] = tool
        logger.info("Tool registered", extra={"tool": tool.name})

    def register_function(
        self,
        name: str,
        func: Callable[..., Any],
        description: str,
        schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a function as a tool.

        Args:
            name: Tool name.
            func: Function to wrap.
            description: Tool description.
            schema: Optional JSON schema.
        """
        tool = FunctionTool(name=name, func=func, description=description, schema=schema)
        self.register(tool)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            Tool instance or None if not found.
        """
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools with their schemas.

        Returns:
            List of tool metadata dictionaries.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.get_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        require_approval: bool = False,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> ToolResult:
        """Execute a tool.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            require_approval: Whether to require approval before execution.
            approval_callback: Optional callback for approval. Should return True to approve.

        Returns:
            ToolResult with execution result.
        """
        tool = self.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found. Available tools: {', '.join(self._tools.keys())}",
            )

        if require_approval and approval_callback:
            approved = approval_callback(tool_name, arguments)
            if not approved:
                return ToolResult(
                    success=False,
                    error="Tool execution was rejected by user",
                )

        return tool.execute(**arguments)


# Global registry instance
_global_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _global_registry


def register_tool(tool: Tool) -> None:
    """Register a tool in the global registry."""
    _global_registry.register(tool)


def register_function_tool(
    name: str,
    func: Callable[..., Any],
    description: str,
    schema: dict[str, Any] | None = None,
) -> None:
    """Register a function as a tool in the global registry."""
    _global_registry.register_function(name, func, description, schema)

