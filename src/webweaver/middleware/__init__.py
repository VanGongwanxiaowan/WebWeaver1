"""Middleware for WebWeaver agents."""

from __future__ import annotations

from webweaver.middleware.agent_memory import AgentMemoryMiddleware
from webweaver.middleware.patch_tool_calls import PatchToolCallsMiddleware
from webweaver.middleware.summarization import SummarizationConfig, SummarizationMiddleware
from webweaver.middleware.todo import TodoListMiddleware
from webweaver.middleware.tool_result_eviction import ToolResultEvictionMiddleware

__all__ = [
    "TodoListMiddleware",
    "SummarizationMiddleware",
    "SummarizationConfig",
    "PatchToolCallsMiddleware",
    "AgentMemoryMiddleware",
    "ToolResultEvictionMiddleware",
]

