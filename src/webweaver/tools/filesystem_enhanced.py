"""Enhanced filesystem tools with glob and grep support."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Literal

from webweaver.logging import get_logger
from webweaver.tools.registry import ToolResult, register_function_tool

logger = get_logger(__name__)


def glob_files(pattern: str, root_dir: str = ".") -> ToolResult:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "*.txt")
        root_dir: Root directory to search from

    Returns:
        ToolResult with list of matching file paths
    """
    try:
        root = Path(root_dir).resolve()
        if not root.exists():
            return ToolResult(success=False, error=f"Root directory not found: {root_dir}")

        matches: list[str] = []
        for path in root.rglob(pattern):
            if path.is_file():
                matches.append(str(path.relative_to(root)))

        logger.info("Glob search completed", extra={"pattern": pattern, "matches": len(matches)})
        return ToolResult(success=True, content={"files": matches, "count": len(matches)})
    except Exception as e:
        logger.exception("Glob search failed", extra={"pattern": pattern})
        return ToolResult(success=False, error=f"Glob search error: {e}")


def grep_files(
    pattern: str,
    root_dir: str = ".",
    file_pattern: str | None = None,
    output_mode: Literal["files_with_matches", "content", "count"] = "files_with_matches",
) -> ToolResult:
    """Search for text patterns within files.

    Args:
        pattern: Text pattern to search for (literal string, not regex)
        root_dir: Root directory to search in
        file_pattern: Optional glob pattern to filter files (e.g., "*.py")
        output_mode: Output format:
            - files_with_matches: List only file paths
            - content: Show matching lines with file path and line numbers
            - count: Show count of matches per file

    Returns:
        ToolResult with search results
    """
    try:
        root = Path(root_dir).resolve()
        if not root.exists():
            return ToolResult(success=False, error=f"Root directory not found: {root_dir}")

        results: dict[str, list[tuple[int, str]]] = {}

        # Find files to search
        files_to_search: list[Path] = []
        if file_pattern:
            files_to_search.extend(root.rglob(file_pattern))
        else:
            files_to_search.extend(root.rglob("*"))

        # Search each file
        for file_path in files_to_search:
            if not file_path.is_file():
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                matches: list[tuple[int, str]] = []

                for line_num, line in enumerate(lines, start=1):
                    if pattern in line:
                        matches.append((line_num, line))

                if matches:
                    rel_path = str(file_path.relative_to(root))
                    results[rel_path] = matches
            except Exception:
                continue

        # Format output based on mode
        if output_mode == "files_with_matches":
            output = {"files": list(results.keys()), "count": len(results)}
        elif output_mode == "content":
            formatted: list[dict[str, Any]] = []
            for file_path, matches in results.items():
                for line_num, line_text in matches:
                    formatted.append(
                        {
                            "file": file_path,
                            "line": line_num,
                            "content": line_text.strip(),
                        }
                    )
            output = {"matches": formatted, "total_matches": sum(len(m) for m in results.values())}
        else:  # count
            output = {
                "files": {file_path: len(matches) for file_path, matches in results.items()},
                "total_files": len(results),
            }

        logger.info(
            "Grep search completed",
            extra={"pattern": pattern, "files_found": len(results), "mode": output_mode},
        )
        return ToolResult(success=True, content=output)
    except Exception as e:
        logger.exception("Grep search failed", extra={"pattern": pattern})
        return ToolResult(success=False, error=f"Grep search error: {e}")


def register_filesystem_enhanced_tools() -> None:
    """Register enhanced filesystem tools."""
    register_function_tool(
        name="glob",
        func=glob_files,
        description=(
            "Find files matching a glob pattern. "
            "Supports standard glob syntax: * (any characters), ** (any directories), "
            "? (single character). Examples: '**/*.py', '*.txt', 'src/**/*.md'"
        ),
    )

    register_function_tool(
        name="grep",
        func=grep_files,
        description=(
            "Search for text patterns within files. "
            "Supports literal string matching (not regex). "
            "Can filter files by glob pattern. "
            "Output modes: files_with_matches (list paths), content (show lines), count (show counts)."
        ),
    )

    logger.info("Enhanced filesystem tools registered")

