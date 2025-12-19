"""Agent memory middleware for WebWeaver.

Provides long-term memory persistence across conversations.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from webweaver.logging import get_logger

logger = get_logger(__name__)

LONGTERM_MEMORY_SYSTEM_PROMPT = """
## Long-term Memory

Your long-term memory is stored in files on the filesystem and persists across sessions.

**User Memory Location**: `{agent_dir_absolute}` (displays as `{agent_dir_display}`)
**Project Memory Location**: {project_memory_info}

Your system prompt is loaded from TWO sources at startup:
1. **User agent.md**: `{agent_dir_absolute}/agent.md` - Your personal preferences across all projects
2. **Project agent.md**: Loaded from project root if available - Project-specific instructions

**When to CHECK/READ memories:**
- At the start of ANY new session: Check both user and project memories
- BEFORE answering questions: Check project memories FIRST, then user
- When user asks you to do something: Check if you have project-specific guides

**When to update memories:**
- IMMEDIATELY when the user describes your role or how you should behave
- IMMEDIATELY when the user gives feedback on your work
- When the user explicitly asks you to remember something
- When patterns or preferences emerge
"""


class AgentMemoryMiddleware:
    """Middleware for loading agent-specific long-term memory."""

    def __init__(
        self,
        *,
        agent_dir: str | Path,
        project_root: str | Path | None = None,
    ) -> None:
        """Initialize agent memory middleware.

        Args:
            agent_dir: Path to agent directory (e.g., ~/.webweaver/agents/{agent_id}).
            project_root: Optional project root directory.
        """
        self.agent_dir = Path(agent_dir).expanduser()
        self.project_root = Path(project_root).expanduser() if project_root else None
        self.agent_dir_display = f"~/.webweaver/agents/{self.agent_dir.name}"

    def load_user_memory(self) -> str | None:
        """Load user memory from agent.md file.

        Returns:
            Memory content or None if file doesn't exist.
        """
        agent_md = self.agent_dir / "agent.md"
        if agent_md.exists():
            try:
                return agent_md.read_text(encoding="utf-8")
            except Exception:
                logger.exception("Failed to load user memory")
        return None

    def load_project_memory(self) -> str | None:
        """Load project memory from project root.

        Returns:
            Memory content or None if not in a project or file doesn't exist.
        """
        if not self.project_root:
            return None

        # Check both .webweaver/agent.md and agent.md
        for path in [
            self.project_root / ".webweaver" / "agent.md",
            self.project_root / "agent.md",
        ]:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception:
                    logger.exception("Failed to load project memory")
        return None

    def get_memory_prompt(self) -> str:
        """Get the memory system prompt section.

        Returns:
            Formatted memory prompt.
        """
        user_memory = self.load_user_memory()
        project_memory = self.load_project_memory()

        if self.project_root and project_memory:
            project_memory_info = f"`{self.project_root}` (detected)"
        elif self.project_root:
            project_memory_info = f"`{self.project_root}` (no agent.md found)"
        else:
            project_memory_info = "None (not in a project)"

        memory_section = LONGTERM_MEMORY_SYSTEM_PROMPT.format(
            agent_dir_absolute=str(self.agent_dir),
            agent_dir_display=self.agent_dir_display,
            project_memory_info=project_memory_info,
        )

        if user_memory:
            memory_section += f"\n\n<user_memory>\n{user_memory}\n</user_memory>"

        if project_memory:
            memory_section += f"\n\n<project_memory>\n{project_memory}\n</project_memory>"

        return memory_section

