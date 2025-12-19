"""Protocol definitions for pluggable backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

FileOperationError = Literal[
    "file_not_found",
    "permission_denied",
    "is_directory",
    "invalid_path",
]


@dataclass
class FileInfo:
    """File information structure."""

    path: str
    is_dir: bool = False
    size: int | None = None
    modified_at: str | None = None


@dataclass
class GrepMatch:
    """Grep match structure."""

    path: str
    line: int
    text: str


@dataclass
class WriteResult:
    """Result from write operations."""

    error: str | None = None
    path: str | None = None
    files_update: dict[str, Any] | None = None


@dataclass
class EditResult:
    """Result from edit operations."""

    error: str | None = None
    path: str | None = None
    files_update: dict[str, Any] | None = None
    occurrences: int | None = None


@dataclass
class ExecuteResponse:
    """Result of code execution."""

    output: str
    exit_code: int | None = None
    truncated: bool = False


class BackendProtocol(ABC):
    """Protocol for pluggable file storage backends."""

    @abstractmethod
    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories."""

    @abstractmethod
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with pagination."""

    @abstractmethod
    def write(self, file_path: str, content: str) -> WriteResult:
        """Write content to a file."""

    @abstractmethod
    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by string replacement."""

    @abstractmethod
    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""

    @abstractmethod
    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for text patterns in files."""


class SandboxBackendProtocol(BackendProtocol):
    """Protocol for sandboxed backends with execution support."""

    @abstractmethod
    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for the sandbox."""

