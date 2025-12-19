"""Extended tools for WebWeaver agents.

These tools extend the basic functionality with HTTP requests, code execution, etc.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import httpx

from webweaver.config import Settings
from webweaver.logging import get_logger
from webweaver.tools.registry import FunctionTool, ToolResult, register_function_tool

logger = get_logger(__name__)


def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: str | dict | None = None,
    params: dict[str, str] | None = None,
    timeout: int = 30,
) -> ToolResult:
    """Make HTTP requests to APIs and web services.

    Args:
        url: Target URL
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: HTTP headers to include
        data: Request body data (string or dict)
        params: URL query parameters
        timeout: Request timeout in seconds

    Returns:
        ToolResult with response data including status, headers, and content
    """
    try:
        kwargs: dict[str, Any] = {"url": url, "method": method.upper(), "timeout": timeout}

        if headers:
            kwargs["headers"] = headers
        if params:
            kwargs["params"] = params
        if data:
            if isinstance(data, dict):
                kwargs["json"] = data
            else:
                kwargs["data"] = data

        with httpx.Client(follow_redirects=True) as client:
            response = client.request(**kwargs)

            try:
                content = response.json()
            except Exception:
                content = response.text

            return ToolResult(
                success=response.status_code < 400,
                content={
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "content": content,
                    "url": str(response.url),
                },
            )
    except httpx.TimeoutException:
        return ToolResult(
            success=False,
            error=f"Request timed out after {timeout} seconds",
        )
    except httpx.RequestError as e:
        return ToolResult(
            success=False,
            error=f"Request error: {e}",
        )
    except Exception as e:
        logger.exception("HTTP request failed", extra={"url": url})
        return ToolResult(
            success=False,
            error=f"Error making request: {e}",
        )


def execute_code(
    code: str,
    language: str = "python",
    timeout: int = 30,
    working_dir: str | None = None,
) -> ToolResult:
    """Execute code in a specified language.

    Args:
        code: Code to execute
        language: Programming language (python, bash, etc.)
        timeout: Execution timeout in seconds
        working_dir: Working directory for execution

    Returns:
        ToolResult with execution output
    """
    try:
        if language == "python":
            result = subprocess.run(
                ["python", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
            )
        elif language == "bash" or language == "shell":
            result = subprocess.run(
                code,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
            )
        else:
            return ToolResult(
                success=False,
                error=f"Unsupported language: {language}",
            )

        return ToolResult(
            success=result.returncode == 0,
            content={
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            },
            error=result.stderr if result.returncode != 0 else None,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            error=f"Code execution timed out after {timeout} seconds",
        )
    except Exception as e:
        logger.exception("Code execution failed", extra={"language": language})
        return ToolResult(
            success=False,
            error=f"Execution error: {e}",
        )


def read_file(file_path: str) -> ToolResult:
    """Read content from a file.

    Args:
        file_path: Path to the file

    Returns:
        ToolResult with file content
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return ToolResult(
                success=False,
                error=f"File not found: {file_path}",
            )
        if not path.is_file():
            return ToolResult(
                success=False,
                error=f"Path is not a file: {file_path}",
            )
        content = path.read_text(encoding="utf-8")
        return ToolResult(
            success=True,
            content=content,
            metadata={"file_path": str(path), "size": len(content)},
        )
    except Exception as e:
        logger.exception("File read failed", extra={"file_path": file_path})
        return ToolResult(
            success=False,
            error=f"Error reading file: {e}",
        )


def write_file(file_path: str, content: str, append: bool = False) -> ToolResult:
    """Write content to a file.

    Args:
        file_path: Path to the file
        content: Content to write
        append: Whether to append to existing file

    Returns:
        ToolResult indicating success
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            content = existing + content

        path.write_text(content, encoding="utf-8")
        return ToolResult(
            success=True,
            content=f"File written: {file_path}",
            metadata={"file_path": str(path), "size": len(content)},
        )
    except Exception as e:
        logger.exception("File write failed", extra={"file_path": file_path})
        return ToolResult(
            success=False,
            error=f"Error writing file: {e}",
        )


def list_directory(dir_path: str = ".", pattern: str | None = None) -> ToolResult:
    """List files and directories.

    Args:
        dir_path: Directory path
        pattern: Optional glob pattern to filter files

    Returns:
        ToolResult with directory listing
    """
    try:
        path = Path(dir_path)
        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Directory not found: {dir_path}",
            )
        if not path.is_dir():
            return ToolResult(
                success=False,
                error=f"Path is not a directory: {dir_path}",
            )

        items: list[dict[str, Any]] = []
        for item in path.iterdir():
            if pattern and not item.match(pattern):
                continue
            items.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )

        return ToolResult(
            success=True,
            content={"items": items, "path": str(path)},
        )
    except Exception as e:
        logger.exception("Directory listing failed", extra={"dir_path": dir_path})
        return ToolResult(
            success=False,
            error=f"Error listing directory: {e}",
        )


def register_extended_tools() -> None:
    """Register all extended tools in the global registry."""
    register_function_tool(
        name="http_request",
        func=http_request,
        description=(
            "Make HTTP requests to APIs and web services. "
            "Supports GET, POST, PUT, DELETE and other HTTP methods. "
            "Returns response status, headers, and content."
        ),
    )

    register_function_tool(
        name="execute_code",
        func=execute_code,
        description=(
            "Execute code in Python, bash, or other languages. "
            "Returns stdout, stderr, and return code. "
            "Use with caution - code execution can be dangerous."
        ),
    )

    register_function_tool(
        name="read_file",
        func=read_file,
        description=(
            "Read content from a file. "
            "Returns the file content as text. "
            "Use absolute paths when possible."
        ),
    )

    register_function_tool(
        name="write_file",
        func=write_file,
        description=(
            "Write content to a file. "
            "Creates parent directories if needed. "
            "Can append to existing files. "
            "Use absolute paths when possible."
        ),
    )

    register_function_tool(
        name="list_directory",
        func=list_directory,
        description=(
            "List files and directories in a given path. "
            "Supports optional glob pattern filtering. "
            "Returns list of items with names, types, and sizes."
        ),
    )

    # Register enhanced filesystem tools
    from webweaver.tools.filesystem_enhanced import register_filesystem_enhanced_tools

    register_filesystem_enhanced_tools()

    logger.info("Extended tools registered")

