"""MemoryCacheBackend: In-memory cache backend for high-frequency access."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Literal

from webweaver.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileInfo,
    GrepMatch,
    WriteResult,
)
from webweaver.backends.utils import (
    create_file_data,
    file_data_to_string,
    format_read_response,
    grep_matches_from_files,
    perform_string_replacement,
    update_file_data,
)


class LRUCache:
    """LRU (Least Recently Used) cache implementation."""

    def __init__(self, max_size: int = 1000):
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of items to cache.
        """
        self.max_size = max_size
        self.cache: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str) -> Any | None:
        """Get item from cache."""
        if key not in self.cache:
            return None
        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: Any) -> None:
        """Put item in cache."""
        if key in self.cache:
            # Update existing item
            self.cache.move_to_end(key)
        else:
            # Add new item
            if len(self.cache) >= self.max_size:
                # Remove least recently used
                self.cache.popitem(last=False)
        self.cache[key] = value

    def remove(self, key: str) -> None:
        """Remove item from cache."""
        self.cache.pop(key, None)

    def clear(self) -> None:
        """Clear all items from cache."""
        self.cache.clear()

    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)


class TTLCache:
    """TTL (Time To Live) cache implementation."""

    def __init__(self, ttl_seconds: int = 3600):
        """Initialize TTL cache.

        Args:
            ttl_seconds: Time to live in seconds.
        """
        self.ttl_seconds = ttl_seconds
        self.cache: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        """Get item from cache if not expired."""
        if key not in self.cache:
            return None
        value, expire_time = self.cache[key]
        if time.time() > expire_time:
            # Expired, remove it
            del self.cache[key]
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        """Put item in cache with TTL."""
        expire_time = time.time() + self.ttl_seconds
        self.cache[key] = (value, expire_time)

    def remove(self, key: str) -> None:
        """Remove item from cache."""
        self.cache.pop(key, None)

    def clear(self) -> None:
        """Clear all items from cache."""
        self.cache.clear()

    def cleanup_expired(self) -> int:
        """Remove expired items and return count of removed items."""
        now = time.time()
        expired_keys = [k for k, (_, expire_time) in self.cache.items() if now > expire_time]
        for key in expired_keys:
            del self.cache[key]
        return len(expired_keys)


class MemoryCacheBackend(BackendProtocol):
    """In-memory cache backend for high-frequency temporary data.

    This backend stores files in memory with optional LRU or TTL eviction policies.
    Useful for caching frequently accessed files or temporary working data.
    """

    def __init__(
        self,
        max_size: int = 1000,
        cache_type: Literal["lru", "ttl"] = "lru",
        ttl_seconds: int = 3600,
    ):
        """Initialize memory cache backend.

        Args:
            max_size: Maximum number of files to cache (for LRU).
            cache_type: Cache eviction policy - "lru" or "ttl".
            ttl_seconds: Time to live in seconds (for TTL cache).
        """
        self.files: dict[str, dict[str, Any]] = {}
        if cache_type == "lru":
            self.cache = LRUCache(max_size=max_size)
        else:
            self.cache = TTLCache(ttl_seconds=ttl_seconds)
        self.cache_type = cache_type

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories."""
        infos: list[FileInfo] = []
        subdirs: set[str] = set()

        # Normalize path
        normalized_path = path if path.endswith("/") else path + "/"

        for file_path, file_data in self.files.items():
            if not file_path.startswith(normalized_path):
                continue

            relative = file_path[len(normalized_path) :]
            if "/" in relative:
                subdir_name = relative.split("/")[0]
                subdirs.add(normalized_path + subdir_name + "/")
                continue

            content_lines = file_data.get("content", [])
            if isinstance(content_lines, str):
                content_lines = content_lines.split("\n")
            size = len("\n".join(content_lines))
            infos.append(
                FileInfo(
                    path=file_path,
                    is_dir=False,
                    size=int(size),
                    modified_at=file_data.get("modified_at", ""),
                )
            )

        for subdir in sorted(subdirs):
            infos.append(
                FileInfo(
                    path=subdir,
                    is_dir=True,
                    size=0,
                    modified_at="",
                )
            )

        infos.sort(key=lambda x: x.path)
        return infos

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content with pagination."""
        # Check cache first
        cached = self.cache.get(file_path)
        if cached is not None:
            file_data = cached
        else:
            file_data = self.files.get(file_path)
            if file_data is None:
                return f"Error: File '{file_path}' not found"
            # Cache it
            self.cache.put(file_path, file_data)

        return format_read_response(file_data, offset, limit)

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file with content."""
        if file_path in self.files:
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. Read and then make an edit, or write to a new path."
            )

        file_data = create_file_data(content)
        self.files[file_path] = file_data
        self.cache.put(file_path, file_data)
        return WriteResult(path=file_path, files_update={file_path: file_data})

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences."""
        file_data = self.files.get(file_path)
        if file_data is None:
            return EditResult(error=f"Error: File '{file_path}' not found")

        content = file_data_to_string(file_data)
        result = perform_string_replacement(content, old_string, new_string, replace_all)

        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result
        new_file_data = update_file_data(file_data, new_content)
        self.files[file_path] = new_file_data
        self.cache.put(file_path, new_file_data)
        return EditResult(
            path=file_path, files_update={file_path: new_file_data}, occurrences=int(occurrences)
        )

    def grep_raw(
        self,
        pattern: str,
        path: str = "/",
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for text patterns in files."""
        return grep_matches_from_files(self.files, pattern, path, glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""
        from webweaver.backends.utils import _glob_search_files

        result = _glob_search_files(self.files, pattern, path)
        if result == "No files found":
            return []
        paths = result.split("\n")
        infos: list[FileInfo] = []
        for p in paths:
            fd = self.files.get(p)
            content_lines = fd.get("content", []) if fd else []
            if isinstance(content_lines, str):
                content_lines = content_lines.split("\n")
            size = len("\n".join(content_lines)) if fd else 0
            infos.append(
                FileInfo(
                    path=p,
                    is_dir=False,
                    size=int(size),
                    modified_at=fd.get("modified_at", "") if fd else "",
                )
            )
        return infos

    def clear_cache(self) -> None:
        """Clear the cache."""
        self.cache.clear()

    def cleanup_expired(self) -> int:
        """Clean up expired items (for TTL cache)."""
        if isinstance(self.cache, TTLCache):
            return self.cache.cleanup_expired()
        return 0

