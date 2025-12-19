"""Skills system for WebWeaver agents."""

from __future__ import annotations

from webweaver.skills.loader import SkillMetadata, list_skills
from webweaver.skills.middleware import SkillsMiddleware

__all__ = [
    "SkillMetadata",
    "SkillsMiddleware",
    "list_skills",
]

