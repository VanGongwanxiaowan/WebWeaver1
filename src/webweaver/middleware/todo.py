"""TodoList middleware for WebWeaver agents.

Provides task planning and progress tracking capabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from webweaver.logging import get_logger
from webweaver.tools.registry import FunctionTool, ToolResult, register_function_tool

logger = get_logger(__name__)


class TodoItem(BaseModel):
    """A single todo item."""

    id: str
    content: str
    status: str = Field(default="pending")  # pending, in_progress, completed, cancelled


class TodoList(BaseModel):
    """Todo list structure."""

    items: list[TodoItem] = Field(default_factory=list)


TODO_SYSTEM_PROMPT = """
## Todo List Management

You have access to tools for creating and managing structured task lists (`write_todos` and `read_todos`).

**When to use todos:**
- For complex, multi-step tasks that need tracking
- When breaking down a large objective into smaller, actionable items
- To track progress through workflows with dependencies

**When NOT to use todos:**
- For simple tasks (1-2 steps) - just do them directly
- For trivial operations that don't need tracking

**Best practices:**
- Keep todo lists MINIMAL - aim for 3-6 items maximum
- Break down work into clear, actionable items without over-fragmenting
- Update todo status promptly as you complete each item
- Mark items as `in_progress` when you start working on them
- Mark items as `completed` when finished
- Use `cancelled` for items that are no longer needed

**Todo status values:**
- `pending`: Not yet started
- `in_progress`: Currently working on
- `completed`: Finished successfully
- `cancelled`: No longer needed
"""


class TodoListMiddleware:
    """Middleware for managing todo lists in agent state."""

    def __init__(self) -> None:
        """Initialize todo list middleware."""
        self._register_tools()

    def _register_tools(self) -> None:
        """Register todo management tools."""

        def write_todos(todos: list[dict[str, Any]]) -> ToolResult:
            """Create or update a todo list.

            Args:
                todos: List of todo items, each with:
                    - id: Unique identifier
                    - content: Task description
                    - status: pending|in_progress|completed|cancelled

            Returns:
                ToolResult with success status.
            """
            try:
                validated_items = [TodoItem.model_validate(item) for item in todos]
                todo_list = TodoList(items=validated_items)
                # In a real implementation, this would update agent state
                # For now, we just validate and return success
                logger.info("Todo list updated", extra={"count": len(validated_items)})
                return ToolResult(
                    success=True,
                    content=f"Todo list updated with {len(validated_items)} items",
                )
            except Exception as e:
                logger.exception("Failed to update todos")
                return ToolResult(success=False, error=str(e))

        def read_todos() -> ToolResult:
            """Read the current todo list.

            Returns:
                ToolResult with todo list data.
            """
            # In a real implementation, this would read from agent state
            # For now, return empty list
            return ToolResult(
                success=True,
                content={"items": []},
            )

        register_function_tool(
            name="write_todos",
            func=write_todos,
            description=(
                "Create or update a structured todo list for tracking progress through complex workflows. "
                "Use this for multi-step tasks that need tracking. Keep lists minimal (3-6 items). "
                "Each todo item should have: id (string), content (string), status (pending|in_progress|completed|cancelled)."
            ),
        )

        register_function_tool(
            name="read_todos",
            func=read_todos,
            description="Read the current todo list state to see what tasks are pending, in progress, or completed.",
        )

    def get_system_prompt(self) -> str:
        """Get the todo list system prompt section."""
        return TODO_SYSTEM_PROMPT

