"""Middleware to patch dangling tool calls in message history."""

from __future__ import annotations

from typing import Any

from webweaver.logging import get_logger

logger = get_logger(__name__)


class PatchToolCallsMiddleware:
    """Middleware to patch dangling tool calls in message history.

    When an agent's tool call is interrupted (e.g., by a new user message),
    this middleware ensures that dangling tool calls are properly handled
    by adding cancellation messages.
    """

    def __init__(self) -> None:
        """Initialize patch tool calls middleware."""

    def patch_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Patch messages to handle dangling tool calls.

        Args:
            messages: List of message dictionaries.

        Returns:
            Patched message list with cancellation messages for dangling tool calls.
        """
        patched: list[dict[str, Any]] = []
        tool_call_ids_seen: set[str] = set()

        for i, msg in enumerate(messages):
            patched.append(msg)

            # Track tool messages we've seen
            if msg.get("type") == "tool" and "tool_call_id" in msg:
                tool_call_ids_seen.add(msg["tool_call_id"])

            # Check for dangling tool calls in AI messages
            if msg.get("type") == "ai" and "tool_calls" in msg:
                tool_calls = msg.get("tool_calls", [])
                for tool_call in tool_calls:
                    tool_call_id = tool_call.get("id") or tool_call.get("tool_call_id")
                    if not tool_call_id:
                        continue

                    # Check if this tool call has a corresponding tool message
                    has_response = False
                    for future_msg in messages[i:]:
                        if (
                            future_msg.get("type") == "tool"
                            and future_msg.get("tool_call_id") == tool_call_id
                        ):
                            has_response = True
                            break

                    # If no response found, add cancellation message
                    if not has_response:
                        tool_name = tool_call.get("name", "unknown")
                        cancellation_msg = {
                            "type": "tool",
                            "content": (
                                f"Tool call {tool_name} with id {tool_call_id} was "
                                "cancelled - another message came in before it could be completed."
                            ),
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                        }
                        patched.append(cancellation_msg)
                        logger.debug(
                            "Patched dangling tool call",
                            extra={"tool_call_id": tool_call_id, "tool_name": tool_name},
                        )

        return patched

