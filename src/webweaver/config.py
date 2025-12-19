"""Application configuration.

Configuration is loaded from environment variables. For local development, you can provide a
`.env` file and set `WEBWEAVER_ENV_FILE` to point to it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """WebWeaver settings.

    All fields are environment-configurable. Prefix is `WEBWEAVER_`.
    """

    model_config = SettingsConfigDict(
        env_prefix="WEBWEAVER_",
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    app_env: Literal["dev", "prod"] = Field(default="dev")
    log_level: str = Field(default="INFO")

    # LLM
    openai_api_key: str | None = Field(default=None)
    openai_base_url: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o-mini")
    openai_timeout_s: float = Field(default=120.0)

    # Search
    search_provider: Literal["tavily", "duckduckgo"] = Field(default="tavily")
    # 适度提高每次搜索返回结果数量，利于收集更多可写证据
    search_max_results: int = Field(default=10, ge=1, le=50)

    tavily_api_key: str | None = Field(default=None)
    tavily_api_base_url: str = Field(default="https://api.tavily.com")
    tavily_search_depth: Literal["basic", "advanced"] = Field(default="basic")
    tavily_timeout_s: float = Field(default=30.0, ge=1.0, le=300.0)
    tavily_max_retries: int = Field(default=3, ge=0, le=10)
    tavily_retry_backoff_s: float = Field(default=0.75, ge=0.0, le=30.0)
    tavily_retry_max_backoff_s: float = Field(default=8.0, ge=0.0, le=120.0)

    # Redis (optional)
    redis_enabled: bool = Field(default=False)
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_key_prefix: str = Field(default="webweaver")

    # Planner loop
    # 增大规划循环的最大步数和每步查询规模，以便进行更多轮基于 Tavily 的检索与大纲优化
    planner_max_steps: int = Field(default=12, ge=1, le=50)
    planner_max_queries_per_step: int = Field(default=4, ge=1, le=10)
    planner_max_urls_per_query: int = Field(default=4, ge=1, le=10)

    # Writer
    # 进一步放宽写作长度和步数上限，以支持“越长越好”的长篇中文学术报告
    writer_section_max_evidences: int = Field(default=12, ge=1, le=50)
    writer_max_steps: int = Field(default=40, ge=1, le=100)
    writer_retrieve_top_k: int = Field(default=12, ge=1, le=50)
    writer_max_draft_chars: int = Field(default=80000, ge=1000, le=200000)
    writer_max_steps_per_section: int = Field(default=18, ge=1, le=50)
    writer_section_max_chars: int = Field(default=20000, ge=500, le=100000)
    writer_tool_response_max_chars: int = Field(default=25000, ge=1000, le=200000)
    writer_evidence_items_per_evidence: int = Field(default=8, ge=1, le=50)

    # Networking
    http_timeout_s: float = Field(default=30.0)
    http_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )

    # Artifacts
    artifacts_dir: Path = Field(default=Path("artifacts"))


def load_settings() -> Settings:
    """Load settings from env.

    Returns:
        Settings: Parsed settings.
    """

    env_file_override = os.getenv("WEBWEAVER_ENV_FILE")
    if env_file_override:
        env_path = Path(env_file_override)
        return Settings(_env_file=env_path)

    default_env = Path.cwd() / ".env"
    if default_env.exists():
        return Settings(_env_file=default_env)

    return Settings()
