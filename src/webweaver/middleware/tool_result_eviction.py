"""Middleware for automatically evicting large tool results to filesystem."""

from __future__ import annotations

from typing import Any, Callable

from webweaver.backends.protocol import BackendProtocol
from webweaver.backends.utils import (
    TOOL_RESULT_TOKEN_LIMIT,
    format_content_with_line_numbers,
    sanitize_tool_call_id,
)
from webweaver.logging import get_logger

logger = get_logger(__name__)

TOO_LARGE_TOOL_MSG = """Tool result too large, the result of this tool call {tool_call_id} was saved in the filesystem at this path: {file_path}
You can read the result from the filesystem by using the read_file tool, but make sure to only read part of the result at a time.
You can do this by specifying an offset and limit in the read_file tool call.
For example, to read the first 100 lines, you can use the read_file tool with offset=0 and limit=100.

Here are the first 10 lines of the result:
{content_sample}
"""


class ToolResultEvictionMiddleware:
    """Middleware that automatically saves large tool results to filesystem.

    When a tool result exceeds a token limit (default 20k tokens, roughly 80k chars),
    this middleware automatically saves it to the filesystem and replaces the result
    with a message indicating where it was saved.

    This helps manage LLM context windows by offloading large results that don't
    need to be in the immediate context.
    """

    def __init__(
        self,
        backend: BackendProtocol | Callable[[], BackendProtocol] | None = None,
        tool_token_limit_before_evict: int = TOOL_RESULT_TOKEN_LIMIT,
    ) -> None:
        """Initialize tool result eviction middleware.

        Args:
            backend: Backend for file storage. Can be a BackendProtocol instance
                    or a callable that returns one (for lazy initialization).
            tool_token_limit_before_evict: Token limit before evicting results.
                                          Default is 20k tokens (roughly 80k chars).
        """
        self.backend = backend
        self.tool_token_limit_before_evict = tool_token_limit_before_evict

    def _get_backend(self) -> BackendProtocol | None:
        """Get the backend instance, resolving callable if needed."""
        if self.backend is None:
            return None
        if callable(self.backend):
            return self.backend()
        return self.backend

    def process_tool_result(
        self,
        tool_call_id: str,
        result_content: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Process a tool result, evicting if too large.

        Args:
            tool_call_id: ID of the tool call.
            result_content: Content of the tool result.

        Returns:
            Tuple of (processed_content, files_update) where:
            - processed_content: The content to use (either original or eviction message)
            - files_update: Dict of file updates for state backends, or None
        """
        # Rough token estimate: ~4 chars per token
        char_limit = self.tool_token_limit_before_evict * 4

        if not isinstance(result_content, str) or len(result_content) <= char_limit:
            return result_content, None

        backend = self._get_backend()
        if backend is None:
            logger.warning(
                "Tool result too large but no backend configured for eviction",
                extra={"tool_call_id": tool_call_id, "size": len(result_content)},
            )
            return result_content, None

        # Sanitize tool call ID for use as filename
        sanitized_id = sanitize_tool_call_id(tool_call_id)
        file_path = f"/large_tool_results/{sanitized_id}"

        # Write to backend
        write_result = backend.write(file_path, result_content)
        if write_result.error:
            logger.warning(
                "Failed to evict large tool result",
                extra={"tool_call_id": tool_call_id, "error": write_result.error},
            )
            return result_content, None

        # Create eviction message with sample
        content_lines = result_content.splitlines()
        sample_lines = [line[:1000] for line in content_lines[:10]]
        content_sample = format_content_with_line_numbers(sample_lines, start_line=1)

        eviction_message = TOO_LARGE_TOOL_MSG.format(
            tool_call_id=tool_call_id,
            file_path=file_path,
            content_sample=content_sample,
        )

        logger.info(
            "Evicted large tool result to filesystem",
            extra={
                "tool_call_id": tool_call_id,
                "file_path": file_path,
                "original_size": len(result_content),
            },
        )

        return eviction_message, write_result.files_update

    def intercept_tool_result(
        self,
        tool_name: str,
        tool_call_id: str,
        result: Any,
    ) -> Any:
        """Intercept and process tool results before they're added to context.

        This method can be called by tool executors or agents to process results.

        Args:
            tool_name: Name of the tool.
            tool_call_id: ID of the tool call.
            result: Tool result (ToolResult or raw content).

        Returns:
            Processed result (may be modified if evicted).
        """
        from webweaver.tools.registry import ToolResult

        # Handle ToolResult objects
        if isinstance(result, ToolResult):
            if result.success and isinstance(result.content, str):
                processed_content, files_update = self.process_tool_result(
                    tool_call_id, result.content
                )
                if files_update is not None:
                    # Result was evicted
                    return ToolResult(
                        success=True,
                        content=processed_content,
                        metadata={**result.metadata, "evicted": True, "files_update": files_update},
                    )
            return result

        # Handle raw string results
        if isinstance(result, str):
            processed_content, files_update = self.process_tool_result(tool_call_id, result)
            if files_update is not None:
                return ToolResult(
                    success=True,
                    content=processed_content,
                    metadata={"evicted": True, "files_update": files_update},
                )
            return result

        return result

