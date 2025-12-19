"""Middleware wrapper for Anthropic Prompt Caching."""

from __future__ import annotations

from typing import Literal

from webweaver.logging import get_logger

logger = get_logger(__name__)

try:
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    _PROMPT_CACHING_AVAILABLE = True
except ImportError:
    _PROMPT_CACHING_AVAILABLE = False
    AnthropicPromptCachingMiddleware = None  # type: ignore


def create_prompt_caching_middleware(
    unsupported_model_behavior: Literal["ignore", "warn", "raise"] = "ignore",
) -> AnthropicPromptCachingMiddleware | None:
    """Create Anthropic Prompt Caching middleware if available.

    This middleware caches system prompts to reduce costs when using Anthropic models.
    It's only effective with Anthropic models that support prompt caching.

    Args:
        unsupported_model_behavior: What to do if model doesn't support caching.
                                   Options: "ignore", "warn", "raise"

    Returns:
        AnthropicPromptCachingMiddleware instance if available, None otherwise.

    Example:
        ```python
        from webweaver.middleware.prompt_caching import create_prompt_caching_middleware

        middleware = create_prompt_caching_middleware()
        if middleware:
            # Use middleware with agent
            pass
        ```
    """
    if not _PROMPT_CACHING_AVAILABLE:
        logger.debug(
            "Anthropic Prompt Caching not available (langchain-anthropic not installed)"
        )
        return None

    if AnthropicPromptCachingMiddleware is None:
        return None

    try:
        return AnthropicPromptCachingMiddleware(unsupported_model_behavior=unsupported_model_behavior)
    except Exception as e:
        logger.warning("Failed to create prompt caching middleware", extra={"error": str(e)})
        return None


# Export availability flag
PROMPT_CACHING_AVAILABLE = _PROMPT_CACHING_AVAILABLE

