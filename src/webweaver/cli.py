"""CLI entrypoints for WebWeaver."""

from __future__ import annotations

from pathlib import Path

import typer

from webweaver.config import load_settings
from webweaver.logging import configure_logging, get_logger
from webweaver.orchestrator.runner import run_research

app = typer.Typer(add_completion=False, help="WebWeaver dual-agent deep research CLI")
logger = get_logger(__name__)


@app.command()
def run(
    query: str = typer.Argument(
        "",
        help="Open-ended research query. "
        "If omitted, you must provide --query-file pointing to a UTF-8 text file.",
        show_default=False,
    ),
    output: Path = typer.Option(Path("report.md"), "--output", "-o", help="Output markdown file"),
    artifacts_dir: Path | None = typer.Option(
        None,
        "--artifacts-dir",
        help="Artifacts directory (overrides WEBWEAVER_ARTIFACTS_DIR)",
    ),
    query_file: Path | None = typer.Option(
        None,
        "--query-file",
        help="Path to a UTF-8 text file containing the open-ended research query "
        "(useful for超长或包含特殊字符/全角符号的中文问题)。",
    ),
) -> None:
    """Run a full WebWeaver research workflow and write a markdown report."""

    # Allow passing very long / complex Chinese queries via file to avoid shell解析问题
    if not query:
        if query_file is None:
            raise typer.BadParameter(
                "You must provide either a positional QUERY or --query-file pointing to a text file."
            )
        query = query_file.read_text(encoding="utf-8").strip()
        if not query:
            raise typer.BadParameter("The query file is empty.")

    settings = load_settings()
    if artifacts_dir is not None:
        settings.artifacts_dir = artifacts_dir

    configure_logging(settings.log_level)

    logger.info("CLI run requested")

    report_path = run_research(query=query, settings=settings)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    typer.echo(str(output))


if __name__ == "__main__":
    app()
