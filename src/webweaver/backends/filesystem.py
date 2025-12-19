"""FilesystemBackend: Read and write files directly from the filesystem."""

from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime
from pathlib import Path

from webweaver.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileInfo,
    GrepMatch,
    WriteResult,
)
from webweaver.logging import get_logger

logger = get_logger(__name__)


class FilesystemBackend(BackendProtocol):
    """Backend that reads and writes files directly from the filesystem."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize filesystem backend.

        Args:
            root_dir: Optional root directory for file operations.
            virtual_mode: If True, treat paths as virtual (relative to root_dir).
            max_file_size_mb: Maximum file size to process (MB).
        """
        self.cwd = Path(root_dir).resolve() if root_dir else Path.cwd()
        self.virtual_mode = virtual_mode
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    def _resolve_path(self, key: str) -> Path:
        """Resolve a file path with security checks."""
        if self.virtual_mode:
            vpath = key if key.startswith("/") else "/" + key
            if ".." in vpath or vpath.startswith("~"):
                raise ValueError("Path traversal not allowed")
            full = (self.cwd / vpath.lstrip("/")).resolve()
            try:
                full.relative_to(self.cwd)
            except ValueError:
                raise ValueError(f"Path {full} outside root directory {self.cwd}") from None
            return full

        path = Path(key)
        if path.is_absolute():
            return path
        return (self.cwd / path).resolve()

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories."""
        dir_path = self._resolve_path(path)
        if not dir_path.exists() or not dir_path.is_dir():
            return []

        results: list[FileInfo] = []
        try:
            for child_path in dir_path.iterdir():
                try:
                    is_file = child_path.is_file()
                    is_dir = child_path.is_dir()
                except OSError:
                    continue

                abs_path = str(child_path)
                if not self.virtual_mode:
                    virt_path = abs_path
                else:
                    try:
                        virt_path = "/" + str(child_path.resolve().relative_to(self.cwd))
                    except Exception:
                        continue

                if is_file:
                    try:
                        st = child_path.stat()
                        results.append(
                            FileInfo(
                                path=virt_path,
                                is_dir=False,
                                size=int(st.st_size),
                                modified_at=datetime.fromtimestamp(st.st_mtime).isoformat(),
                            )
                        )
                    except OSError:
                        results.append(FileInfo(path=virt_path, is_dir=False))
                elif is_dir:
                    results.append(FileInfo(path=virt_path + "/", is_dir=True))
        except (OSError, PermissionError):
            pass

        results.sort(key=lambda x: x.path)
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with pagination."""
        resolved_path = self._resolve_path(file_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return f"Error: File '{file_path}' not found"

        try:
            fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                content = f.read()

            lines = content.splitlines()
            start_idx = offset
            end_idx = min(start_idx + limit, len(lines))

            if start_idx >= len(lines):
                return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

            selected_lines = lines[start_idx:end_idx]
            # Format with line numbers
            formatted = "\n".join(
                f"{i + start_idx + 1:6d}\t{line}" for i, line in enumerate(selected_lines)
            )
            return formatted
        except (OSError, UnicodeDecodeError) as e:
            return f"Error reading file '{file_path}': {e}"

    def write(self, file_path: str, content: str) -> WriteResult:
        """Create a new file with content."""
        resolved_path = self._resolve_path(file_path)

        if resolved_path.exists():
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. Read and then make an edit, or write to a new path."
            )

        try:
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved_path, flags, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            return WriteResult(path=file_path, files_update=None)
        except (OSError, UnicodeEncodeError) as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences."""
        resolved_path = self._resolve_path(file_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return EditResult(error=f"Error: File '{file_path}' not found")

        try:
            fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                content = f.read()

            if replace_all:
                occurrences = content.count(old_string)
                new_content = content.replace(old_string, new_string)
            else:
                if content.count(old_string) != 1:
                    return EditResult(
                        error=f"String not unique in file. Found {content.count(old_string)} occurrences. Use replace_all=True to replace all."
                    )
                occurrences = 1
                new_content = content.replace(old_string, new_string, 1)

            flags = os.O_WRONLY | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved_path, flags)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)

            return EditResult(path=file_path, files_update=None, occurrences=occurrences)
        except (OSError, UnicodeDecodeError, UnicodeEncodeError) as e:
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")

        search_path = self.cwd if path == "/" else self._resolve_path(path)
        if not search_path.exists() or not search_path.is_dir():
            return []

        results: list[FileInfo] = []
        try:
            for matched_path in search_path.rglob(pattern):
                try:
                    if not matched_path.is_file():
                        continue
                    abs_path = str(matched_path)
                    if not self.virtual_mode:
                        virt_path = abs_path
                    else:
                        try:
                            virt_path = "/" + str(matched_path.resolve().relative_to(self.cwd))
                        except Exception:
                            continue

                    try:
                        st = matched_path.stat()
                        results.append(
                            FileInfo(
                                path=virt_path,
                                is_dir=False,
                                size=int(st.st_size),
                                modified_at=datetime.fromtimestamp(st.st_mtime).isoformat(),
                            )
                        )
                    except OSError:
                        results.append(FileInfo(path=virt_path, is_dir=False))
                except OSError:
                    continue
        except (OSError, ValueError):
            pass

        results.sort(key=lambda x: x.path)
        return results

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for text patterns in files."""
        base_path = self._resolve_path(path or ".")
        if not base_path.exists():
            return []

        matches: list[GrepMatch] = []
        root = base_path if base_path.is_dir() else base_path.parent

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue

            if glob and not fnmatch.fnmatch(file_path.name, glob):
                continue

            try:
                if file_path.stat().st_size > self.max_file_size_bytes:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for line_num, line in enumerate(content.splitlines(), start=1):
                if pattern in line:
                    virt_path = (
                        str(file_path)
                        if not self.virtual_mode
                        else "/" + str(file_path.resolve().relative_to(self.cwd))
                    )
                    matches.append(GrepMatch(path=virt_path, line=line_num, text=line))

        return matches

