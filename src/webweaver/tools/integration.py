"""Integration helpers for using tools with WebWeaver agents."""

from __future__ import annotations

from webweaver.config import Settings
from webweaver.llm.client import LLMClient
from webweaver.logging import get_logger
from webweaver.skills.middleware import SkillsMiddleware
from webweaver.tools.extended_tools import register_extended_tools
from webweaver.tools.registry import ToolRegistry, get_registry

logger = get_logger(__name__)


def setup_tools_for_agent(
    settings: Settings,
    registry: ToolRegistry | None = None,
    enable_extended_tools: bool = True,
) -> ToolRegistry:
    """Setup tool registry for an agent.

    Args:
        settings: WebWeaver settings.
        registry: Optional existing registry. If None, uses global registry.
        enable_extended_tools: Whether to register extended tools.

    Returns:
        Configured ToolRegistry.
    """
    if registry is None:
        registry = get_registry()

    if enable_extended_tools:
        register_extended_tools()
        logger.info("Extended tools registered")

    return registry


def setup_skills_middleware(
    skills_dir: str | None = None,
    project_skills_dir: str | None = None,
) -> SkillsMiddleware | None:
    """Setup skills middleware for an agent.

    Args:
        skills_dir: Path to user skills directory.
        project_skills_dir: Optional path to project skills directory.

    Returns:
        SkillsMiddleware instance or None if no skills directories provided.
    """
    if not skills_dir and not project_skills_dir:
        return None

    middleware = SkillsMiddleware(
        skills_dir=skills_dir or "~/.webweaver/skills",
        project_skills_dir=project_skills_dir,
    )
    logger.info("Skills middleware initialized")
    return middleware

