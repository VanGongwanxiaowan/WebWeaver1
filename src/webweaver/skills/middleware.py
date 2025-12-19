"""Skills middleware for WebWeaver agents.

Provides progressive disclosure of skills to agents.
"""

from __future__ import annotations

from pathlib import Path

from webweaver.logging import get_logger
from webweaver.skills.loader import SkillMetadata, list_skills

logger = get_logger(__name__)

SKILLS_SYSTEM_PROMPT = """
## Skills System

You have access to a skills library that provides specialized capabilities and domain knowledge.

{skills_locations}

**Available Skills:**

{skills_list}

**How to Use Skills (Progressive Disclosure):**

Skills follow a **progressive disclosure** pattern - you know they exist (name + description above), but you only read the full instructions when needed:

1. **Recognize when a skill applies**: Check if the user's task matches any skill's description
2. **Read the skill's full instructions**: The skill list above shows the exact path to use with read_file
3. **Follow the skill's instructions**: SKILL.md contains step-by-step workflows, best practices, and examples
4. **Access supporting files**: Skills may include Python scripts, configs, or reference docs - use absolute paths

**When to Use Skills:**
- When the user's request matches a skill's domain (e.g., "research X" → web-research skill)
- When you need specialized knowledge or structured workflows
- When a skill provides proven patterns for complex tasks

**Skills are Self-Documenting:**
- Each SKILL.md tells you exactly what the skill does and how to use it
- The skill list above shows the full path for each skill's SKILL.md file

**Executing Skill Scripts:**
Skills may contain Python scripts or other executable files. Always use absolute paths from the skill list.
"""


class SkillsMiddleware:
    """Middleware for loading and exposing agent skills.

    This middleware implements progressive disclosure pattern:
    - Loads skills metadata (name, description) from YAML frontmatter
    - Injects skills list into system prompt for discoverability
    - Agent reads full SKILL.md content when a skill is relevant
    """

    def __init__(
        self,
        *,
        skills_dir: str | Path,
        project_skills_dir: str | Path | None = None,
    ) -> None:
        """Initialize skills middleware.

        Args:
            skills_dir: Path to the user-level skills directory.
            project_skills_dir: Optional path to project-level skills directory.
        """
        self.skills_dir = Path(skills_dir).expanduser()
        self.project_skills_dir = (
            Path(project_skills_dir).expanduser() if project_skills_dir else None
        )
        self.system_prompt_template = SKILLS_SYSTEM_PROMPT

    def _format_skills_locations(self) -> str:
        """Format skills locations for display in system prompt."""
        locations = [f"**User Skills**: `{self.skills_dir}`"]
        if self.project_skills_dir:
            locations.append(
                f"**Project Skills**: `{self.project_skills_dir}` (overrides user skills)"
            )
        return "\n".join(locations)

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skills metadata for display in system prompt."""
        if not skills:
            locations = [f"{self.skills_dir}/"]
            if self.project_skills_dir:
                locations.append(f"{self.project_skills_dir}/")
            return f"(No skills available yet. You can create skills in {' or '.join(locations)})"

        user_skills = [s for s in skills if s["source"] == "user"]
        project_skills = [s for s in skills if s["source"] == "project"]

        lines = []

        if user_skills:
            lines.append("**User Skills:**")
            for skill in user_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")
            lines.append("")

        if project_skills:
            lines.append("**Project Skills:**")
            for skill in project_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")

        return "\n".join(lines)

    def get_skills_prompt(self) -> str:
        """Get the skills section for system prompt.

        Returns:
            Formatted skills documentation string.
        """
        skills = list_skills(
            user_skills_dir=self.skills_dir,
            project_skills_dir=self.project_skills_dir,
        )

        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills)

        return self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

    def list_available_skills(self) -> list[SkillMetadata]:
        """List all available skills.

        Returns:
            List of skill metadata.
        """
        return list_skills(
            user_skills_dir=self.skills_dir,
            project_skills_dir=self.project_skills_dir,
        )

