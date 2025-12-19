"""SubAgent system for WebWeaver.

Inspired by deepagents, this allows agents to spawn subagents for complex tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger
from webweaver.tools.executor import ToolExecutor
from webweaver.tools.registry import ToolRegistry, ToolResult, register_function_tool

logger = get_logger(__name__)


@dataclass
class SubAgentConfig:
    """Configuration for a subagent."""

    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None  # List of tool names this subagent can use
    model: str | None = None  # Optional model override


class SubAgent:
    """A subagent that can handle delegated tasks."""

    def __init__(
        self,
        config: SubAgentConfig,
        llm: LLMClient,
        tool_registry: ToolRegistry,
    ) -> None:
        """Initialize subagent.

        Args:
            config: SubAgent configuration.
            llm: LLM client for the subagent.
            tool_registry: Tool registry with available tools.
        """
        self.config = config
        self._llm = llm
        self._tool_registry = tool_registry
        self._executor = ToolExecutor(registry=tool_registry)

    def execute(self, task_description: str, max_iterations: int = 10) -> ToolResult:
        """Execute a task using the subagent.

        Args:
            task_description: Description of the task to perform.
            max_iterations: Maximum number of iterations.

        Returns:
            ToolResult with the final result.
        """
        messages = [
            {
                "role": "system",
                "content": self.config.system_prompt,
            },
            {
                "role": "user",
                "content": task_description,
            },
        ]

        for iteration in range(max_iterations):
            # Get LLM response
            response = self._llm.complete(
                [ChatMessage(role=m["role"], content=m["content"]) for m in messages],
                temperature=0.2,
            )

            # Check for termination
            if "<terminate>" in response.lower():
                # Extract final result
                result_text = response.split("<terminate>")[-1].strip()
                return ToolResult(success=True, content=result_text)

            # Parse and execute tool calls
            tool_results = self._executor.execute_tool_calls(response)
            if tool_results:
                # Add tool responses to conversation
                for tr in tool_results:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": tr.formatted_response})
            else:
                # No tool calls, add response as assistant message
                messages.append({"role": "assistant", "content": response})

        return ToolResult(
            success=False,
            error=f"SubAgent reached maximum iterations ({max_iterations})",
        )


class SubAgentManager:
    """Manager for subagents."""

    def __init__(
        self,
        llm: LLMClient,
        tool_registry: ToolRegistry,
    ) -> None:
        """Initialize subagent manager.

        Args:
            llm: LLM client for subagents.
            tool_registry: Tool registry.
        """
        self._llm = llm
        self._tool_registry = tool_registry
        self._subagents: dict[str, SubAgent] = {}

    def register_subagent(self, config: SubAgentConfig) -> None:
        """Register a subagent.

        Args:
            config: SubAgent configuration.
        """
        subagent = SubAgent(config, self._llm, self._tool_registry)
        self._subagents[config.name] = subagent
        logger.info("SubAgent registered", extra={"name": config.name})

    def get_subagent(self, name: str) -> SubAgent | None:
        """Get a subagent by name.

        Args:
            name: SubAgent name.

        Returns:
            SubAgent instance or None.
        """
        return self._subagents.get(name)

    def list_subagents(self) -> list[dict[str, str]]:
        """List all registered subagents.

        Returns:
            List of subagent metadata.
        """
        return [
            {
                "name": config.name,
                "description": config.description,
            }
            for config in [s.config for s in self._subagents.values()]
        ]


def create_task_tool(
    subagent_manager: SubAgentManager,
) -> None:
    """Create and register the 'task' tool for invoking subagents.

    Args:
        subagent_manager: SubAgentManager instance.
    """

    def task(description: str, subagent_type: str) -> ToolResult:
        """Launch a subagent to handle a task.

        Args:
            description: Task description for the subagent.
            subagent_type: Type/name of subagent to use.

        Returns:
            ToolResult with subagent execution result.
        """
        subagent = subagent_manager.get_subagent(subagent_type)
        if subagent is None:
            available = ", ".join(subagent_manager.list_subagents())
            return ToolResult(
                success=False,
                error=f"SubAgent '{subagent_type}' not found. Available: {available}",
            )

        logger.info("SubAgent task started", extra={"type": subagent_type})
        result = subagent.execute(description)
        logger.info("SubAgent task completed", extra={"type": subagent_type, "success": result.success})
        return result

    register_function_tool(
        name="task",
        func=task,
        description=(
            "Launch a subagent to handle complex, multi-step tasks with isolated context. "
            "Subagents are useful for tasks that require focused reasoning or heavy token usage. "
            "Each subagent completes its task autonomously and returns a single result."
        ),
    )

