"""CompositeBackend: Route operations to different backends based on path prefix."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from webweaver.backends.async_base import AsyncBackendMixin
from webweaver.backends.protocol import (
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileInfo,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)
from webweaver.backends.state import StateBackend


class CompositeBackend(AsyncBackendMixin):
    """Composite backend that routes operations to different backends based on path prefix.

    This allows combining multiple backends (e.g., ephemeral state storage and
    persistent storage) with different path prefixes.

    Example:
        ```python
        from webweaver.backends import StateBackend, FilesystemBackend, CompositeBackend

        # Create a composite backend with state storage as default
        # and filesystem storage for /memories/ prefix
        state_backend = StateBackend(runtime)
        fs_backend = FilesystemBackend(root_dir="/data/memories")
        composite = CompositeBackend(
            default=state_backend,
            routes={"/memories/": fs_backend}
        )
        ```
    """

    def __init__(
        self,
        default: BackendProtocol | StateBackend,
        routes: dict[str, BackendProtocol],
    ) -> None:
        """Initialize CompositeBackend.

        Args:
            default: Default backend for paths that don't match any route.
            routes: Dictionary mapping path prefixes to backends.
                   Prefixes should end with '/' (e.g., "/memories/").
        """
        # Default backend
        self.default = default

        # Virtual routes
        self.routes = routes

        # Sort routes by length (longest first) for correct prefix matching
        self.sorted_routes = sorted(routes.items(), key=lambda x: len(x[0]), reverse=True)

    def _get_backend_and_key(self, key: str) -> tuple[BackendProtocol, str]:
        """Determine which backend handles this key and strip prefix.

        Args:
            key: Original file path

        Returns:
            Tuple of (backend, stripped_key) where stripped_key has the route
            prefix removed (but keeps leading slash).
        """
        # Check routes in order of length (longest first)
        for prefix, backend in self.sorted_routes:
            if key.startswith(prefix):
                # Strip full prefix and ensure a leading slash remains
                # e.g., "/memories/notes.txt" → "/notes.txt"; "/memories/" → "/"
                suffix = key[len(prefix) :]
                stripped_key = f"/{suffix}" if suffix else "/"
                return backend, stripped_key

        return self.default, key

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories in the specified directory (non-recursive).

        Args:
            path: Absolute path to directory.

        Returns:
            List of FileInfo-like dicts with route prefixes added, for files and directories directly in the directory.
            Directories have a trailing / in their path and is_dir=True.
        """
        # Check if path matches a specific route
        for route_prefix, backend in self.sorted_routes:
            if path.startswith(route_prefix.rstrip("/")):
                # Query only the matching routed backend
                suffix = path[len(route_prefix) :]
                search_path = f"/{suffix}" if suffix else "/"
                infos = backend.ls_info(search_path)
                prefixed: list[FileInfo] = []
                for fi in infos:
                    prefixed.append(
                        FileInfo(
                            path=f"{route_prefix[:-1]}{fi.path}",
                            is_dir=fi.is_dir,
                            size=fi.size,
                            modified_at=fi.modified_at,
                        )
                    )
                return prefixed

        # At root, aggregate default and all routed backends
        if path == "/":
            results: list[FileInfo] = []
            results.extend(self.default.ls_info(path))
            for route_prefix, backend in self.sorted_routes:
                # Add the route itself as a directory (e.g., /memories/)
                results.append(
                    FileInfo(
                        path=route_prefix,
                        is_dir=True,
                        size=0,
                        modified_at="",
                    )
                )

            results.sort(key=lambda x: x.path)
            return results

        # Path doesn't match a route: query only default backend
        return self.default.ls_info(path)

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content, routing to appropriate backend.

        Args:
            file_path: Absolute file path.
            offset: Line offset to start reading from (0-indexed).
            limit: Maximum number of lines to read.

        Returns:
            Formatted file content with line numbers, or error message.
        """
        backend, stripped_key = self._get_backend_and_key(file_path)
        return backend.read(stripped_key, offset=offset, limit=limit)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for text patterns in files, routing to appropriate backend(s)."""
        # If path targets a specific route, search only that backend
        if path is not None:
            for route_prefix, backend in self.sorted_routes:
                if path.startswith(route_prefix.rstrip("/")):
                    search_path = path[len(route_prefix) - 1 :]
                    raw = backend.grep_raw(pattern, search_path if search_path else "/", glob)
                    if isinstance(raw, str):
                        return raw
                    return [
                        GrepMatch(
                            path=f"{route_prefix[:-1]}{m.path}",
                            line=m.line,
                            text=m.text,
                        )
                        for m in raw
                    ]

        # Otherwise, search default and all routed backends and merge
        all_matches: list[GrepMatch] = []
        raw_default = self.default.grep_raw(pattern, path, glob)
        if isinstance(raw_default, str):
            # This happens if error occurs
            return raw_default
        all_matches.extend(raw_default)

        for route_prefix, backend in self.routes.items():
            raw = backend.grep_raw(pattern, "/", glob)
            if isinstance(raw, str):
                # This happens if error occurs
                return raw
            all_matches.extend(
                GrepMatch(
                    path=f"{route_prefix[:-1]}{m.path}",
                    line=m.line,
                    text=m.text,
                )
                for m in raw
            )

        return all_matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""
        results: list[FileInfo] = []

        # Route based on path, not pattern
        for route_prefix, backend in self.sorted_routes:
            if path.startswith(route_prefix.rstrip("/")):
                search_path = path[len(route_prefix) - 1 :]
                infos = backend.glob_info(pattern, search_path if search_path else "/")
                return [
                    FileInfo(
                        path=f"{route_prefix[:-1]}{fi.path}",
                        is_dir=fi.is_dir,
                        size=fi.size,
                        modified_at=fi.modified_at,
                    )
                    for fi in infos
                ]

        # Path doesn't match any specific route - search default backend AND all routed backends
        results.extend(self.default.glob_info(pattern, path))

        for route_prefix, backend in self.routes.items():
            infos = backend.glob_info(pattern, "/")
            results.extend(
                FileInfo(
                    path=f"{route_prefix[:-1]}{fi.path}",
                    is_dir=fi.is_dir,
                    size=fi.size,
                    modified_at=fi.modified_at,
                )
                for fi in infos
            )

        # Deterministic ordering
        results.sort(key=lambda x: x.path)
        return results

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file, routing to appropriate backend.

        Args:
            file_path: Absolute file path.
            content: File content as a string.

        Returns:
            WriteResult with success status or error message.
        """
        backend, stripped_key = self._get_backend_and_key(file_path)
        res = backend.write(stripped_key, content)
        # If this is a state-backed update and default has state, merge so listings reflect changes
        if res.files_update:
            try:
                runtime = getattr(self.default, "runtime", None)
                if runtime is not None:
                    state = runtime.state
                    files = state.get("files", {})
                    files.update(res.files_update)
                    state["files"] = files
            except Exception:
                pass
        return res

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file, routing to appropriate backend.

        Args:
            file_path: Absolute file path.
            old_string: String to find and replace.
            new_string: Replacement string.
            replace_all: If True, replace all occurrences.

        Returns:
            EditResult with success status or error message on failure.
        """
        backend, stripped_key = self._get_backend_and_key(file_path)
        res = backend.edit(stripped_key, old_string, new_string, replace_all=replace_all)
        if res.files_update:
            try:
                runtime = getattr(self.default, "runtime", None)
                if runtime is not None:
                    state = runtime.state
                    files = state.get("files", {})
                    files.update(res.files_update)
                    state["files"] = files
            except Exception:
                pass
        return res

    def execute(
        self,
        command: str,
    ) -> ExecuteResponse:
        """Execute a command via the default backend.

        Execution is not path-specific, so it always delegates to the default backend.
        The default backend must implement SandboxBackendProtocol for this to work.

        Args:
            command: Full shell command string to execute.

        Returns:
            ExecuteResponse with combined output, exit code, and truncation flag.

        Raises:
            NotImplementedError: If default backend doesn't support execution.
        """
        if isinstance(self.default, SandboxBackendProtocol):
            return self.default.execute(command)

        # This shouldn't be reached if the runtime check in the execute tool works correctly,
        # but we include it as a safety fallback.
        raise NotImplementedError(
            "Default backend doesn't support command execution (SandboxBackendProtocol). "
            "To enable execution, provide a default backend that implements SandboxBackendProtocol."
        )

    async def aexecute(self, command: str) -> ExecuteResponse:
        """异步执行命令。"""
        if isinstance(self.default, SandboxBackendProtocol):
            if hasattr(self.default, "aexecute"):
                return await self.default.aexecute(command)
            return await asyncio.to_thread(self.default.execute, command)
        raise NotImplementedError(
            "Default backend doesn't support command execution (SandboxBackendProtocol)."
        )

