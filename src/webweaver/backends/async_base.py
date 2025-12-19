"""Async base implementations for backends."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from webweaver.backends.extended_protocol import AsyncBackendProtocol
from webweaver.backends.protocol import BackendProtocol, EditResult, FileInfo, GrepMatch, WriteResult


class AsyncBackendMixin:
    """异步后端混入类，为同步后端提供异步方法。"""

    async def als_info(self, path: str) -> list[FileInfo]:
        """异步列出文件和目录。"""
        return await asyncio.to_thread(self.ls_info, path)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """异步读取文件内容。"""
        return await asyncio.to_thread(self.read, file_path, offset, limit)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """异步写入文件。"""
        return await asyncio.to_thread(self.write, file_path, content)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """异步编辑文件。"""
        return await asyncio.to_thread(self.edit, file_path, old_string, new_string, replace_all)

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """异步查找匹配的文件。"""
        return await asyncio.to_thread(self.glob_info, pattern, path)

    async def agrep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """异步搜索文本模式。"""
        return await asyncio.to_thread(self.grep_raw, pattern, path, glob)


class AsyncFilesystemBackend(AsyncBackendMixin, BackendProtocol):
    """异步文件系统后端。"""

    def __init__(
        self,
        root_dir: str | None = None,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        """初始化异步文件系统后端。

        Args:
            root_dir: 根目录。
            virtual_mode: 虚拟模式。
            max_file_size_mb: 最大文件大小（MB）。
        """
        from webweaver.backends.filesystem import FilesystemBackend

        self._sync_backend = FilesystemBackend(root_dir, virtual_mode, max_file_size_mb)

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        return self._sync_backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        return self._sync_backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入文件。"""
        return self._sync_backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件。"""
        return self._sync_backend.edit(file_path, old_string, new_string, replace_all)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        return self._sync_backend.glob_info(pattern, path)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式。"""
        return self._sync_backend.grep_raw(pattern, path, glob)


class AsyncStateBackend(AsyncBackendMixin, BackendProtocol):
    """异步状态后端。"""

    def __init__(self, runtime: Any):
        """初始化异步状态后端。

        Args:
            runtime: ToolRuntime 实例。
        """
        from webweaver.backends.state import StateBackend

        self._sync_backend = StateBackend(runtime)

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        return self._sync_backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        return self._sync_backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入文件。"""
        return self._sync_backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件。"""
        return self._sync_backend.edit(file_path, old_string, new_string, replace_all)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        return self._sync_backend.glob_info(pattern, path)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式。"""
        return self._sync_backend.grep_raw(pattern, path, glob)


class AsyncMemoryCacheBackend(AsyncBackendMixin, BackendProtocol):
    """异步内存缓存后端。"""

    def __init__(
        self,
        max_size: int = 1000,
        cache_type: Literal["lru", "ttl"] = "lru",
        ttl_seconds: int = 3600,
    ) -> None:
        """初始化异步内存缓存后端。

        Args:
            max_size: 最大缓存大小。
            cache_type: 缓存类型。
            ttl_seconds: TTL 秒数。
        """
        from webweaver.backends.memory_cache import MemoryCacheBackend

        self._sync_backend = MemoryCacheBackend(max_size, cache_type, ttl_seconds)

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        return self._sync_backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        return self._sync_backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入文件。"""
        return self._sync_backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件。"""
        return self._sync_backend.edit(file_path, old_string, new_string, replace_all)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        return self._sync_backend.glob_info(pattern, path)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式。"""
        return self._sync_backend.grep_raw(pattern, path, glob)

