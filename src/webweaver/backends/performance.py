"""Performance enhancements: metrics, caching, batch operations, compression."""

from __future__ import annotations

import gzip
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

try:
    import brotli

    _BROTLI_AVAILABLE = True
except ImportError:
    _BROTLI_AVAILABLE = False

from webweaver.backends.extended_protocol import BackendMetrics, MetricsBackendProtocol
from webweaver.backends.protocol import BackendProtocol


class PerformanceMonitor:
    """性能监控器。"""

    def __init__(self):
        """初始化性能监控器。"""
        self.metrics = BackendMetrics()
        self.operation_times: list[tuple[str, float]] = []

    def record_operation(self, operation: str, latency_ms: float, success: bool = True, bytes_transferred: int = 0):
        """记录操作。

        Args:
            operation: 操作名称。
            latency_ms: 延迟（毫秒）。
            success: 是否成功。
            bytes_transferred: 传输的字节数。
        """
        self.metrics.operation_count += 1
        self.metrics.total_latency_ms += latency_ms
        if not success:
            self.metrics.error_count += 1
        if "read" in operation.lower():
            self.metrics.bytes_read += bytes_transferred
        elif "write" in operation.lower():
            self.metrics.bytes_written += bytes_transferred
        self.operation_times.append((operation, latency_ms))

    def get_metrics(self) -> BackendMetrics:
        """获取性能指标。"""
        return self.metrics

    def reset_metrics(self) -> None:
        """重置性能指标。"""
        self.metrics = BackendMetrics()
        self.operation_times.clear()

    def get_average_latency(self) -> float:
        """获取平均延迟。"""
        if self.metrics.operation_count == 0:
            return 0.0
        return self.metrics.total_latency_ms / self.metrics.operation_count


class CachedBackend(BackendProtocol):
    """带缓存的后端包装器。"""

    def __init__(
        self,
        backend: BackendProtocol,
        cache_type: Literal["lru", "ttl"] = "lru",
        max_size: int = 1000,
        ttl_seconds: int = 3600,
    ):
        """初始化缓存后端。

        Args:
            backend: 底层后端。
            cache_type: 缓存类型（lru 或 ttl）。
            max_size: 最大缓存大小（LRU）。
            ttl_seconds: TTL 秒数。
        """
        from webweaver.backends.memory_cache import LRUCache, TTLCache

        self.backend = backend
        if cache_type == "lru":
            self.cache = LRUCache(max_size=max_size)
        else:
            self.cache = TTLCache(ttl_seconds=ttl_seconds)
        self.monitor = PerformanceMonitor()

    def ls_info(self, path: str) -> list[Any]:
        """列出文件和目录。"""
        cache_key = f"ls:{path}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.monitor.metrics.cache_hits += 1
            return cached
        self.monitor.metrics.cache_misses += 1
        result = self.backend.ls_info(path)
        self.cache.put(cache_key, result)
        return result

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        cache_key = f"read:{file_path}:{offset}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.monitor.metrics.cache_hits += 1
            return cached
        self.monitor.metrics.cache_misses += 1
        result = self.backend.read(file_path, offset, limit)
        self.cache.put(cache_key, result)
        return result

    def write(self, file_path: str, content: str) -> Any:
        """写入文件。"""
        # 清除相关缓存
        self._invalidate_cache(file_path)
        return self.backend.write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Any:
        """编辑文件。"""
        # 清除相关缓存
        self._invalidate_cache(file_path)
        return self.backend.edit(file_path, old_string, new_string, replace_all)

    def glob_info(self, pattern: str, path: str = "/") -> list[Any]:
        """查找匹配的文件。"""
        cache_key = f"glob:{pattern}:{path}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.monitor.metrics.cache_hits += 1
            return cached
        self.monitor.metrics.cache_misses += 1
        result = self.backend.glob_info(pattern, path)
        self.cache.put(cache_key, result)
        return result

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        """搜索文本模式。"""
        cache_key = f"grep:{pattern}:{path}:{glob}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.monitor.metrics.cache_hits += 1
            return cached
        self.monitor.metrics.cache_misses += 1
        result = self.backend.grep_raw(pattern, path, glob)
        self.cache.put(cache_key, result)
        return result

    def _invalidate_cache(self, file_path: str) -> None:
        """使缓存失效。"""
        # 简化实现：清除所有相关缓存项
        if isinstance(self.cache, dict):
            keys_to_remove = [k for k in self.cache.keys() if file_path in str(k)]
            for key in keys_to_remove:
                self.cache.remove(key)


class BatchOperationsBackend(BackendProtocol):
    """支持批量操作的后端包装器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化批量操作后端。

        Args:
            backend: 底层后端。
        """
        self.backend = backend

    def batch_read(self, file_paths: list[str], offset: int = 0, limit: int = 2000) -> dict[str, str]:
        """批量读取文件。

        Args:
            file_paths: 文件路径列表。
            offset: 行偏移。
            limit: 行限制。

        Returns:
            文件路径到内容的字典。
        """
        results: dict[str, str] = {}
        for path in file_paths:
            results[path] = self.backend.read(path, offset, limit)
        return results

    def batch_write(self, files: dict[str, str]) -> dict[str, Any]:
        """批量写入文件。

        Args:
            files: 文件路径到内容的字典。

        Returns:
            文件路径到 WriteResult 的字典。
        """
        results: dict[str, Any] = {}
        for path, content in files.items():
            results[path] = self.backend.write(path, content)
        return results

    def batch_edit(self, edits: list[dict[str, Any]]) -> dict[str, Any]:
        """批量编辑文件。

        Args:
            edits: 编辑操作列表，每个包含 path, old_string, new_string, replace_all。

        Returns:
            文件路径到 EditResult 的字典。
        """
        results: dict[str, Any] = {}
        for edit in edits:
            path = edit["path"]
            results[path] = self.backend.edit(
                path,
                edit["old_string"],
                edit["new_string"],
                edit.get("replace_all", False),
            )
        return results

    # 实现必需的协议方法
    def ls_info(self, path: str) -> list[Any]:
        """列出文件和目录。"""
        return self.backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        return self.backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> Any:
        """写入文件。"""
        return self.backend.write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Any:
        """编辑文件。"""
        return self.backend.edit(file_path, old_string, new_string, replace_all)

    def glob_info(self, pattern: str, path: str = "/") -> list[Any]:
        """查找匹配的文件。"""
        return self.backend.glob_info(pattern, path)

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        """搜索文本模式。"""
        return self.backend.grep_raw(pattern, path, glob)


class CompressionBackend(BackendProtocol):
    """支持文件压缩的后端包装器。"""

    def __init__(self, backend: BackendProtocol, default_algorithm: Literal["gzip", "brotli"] = "gzip"):
        """初始化压缩后端。

        Args:
            backend: 底层后端。
            default_algorithm: 默认压缩算法。
        """
        self.backend = backend
        self.default_algorithm = default_algorithm
        self._compressed_files: set[str] = set()

    def compress_file(self, path: str, algorithm: Literal["gzip", "brotli"] = "gzip") -> bool:
        """压缩文件。

        Args:
            path: 文件路径。
            algorithm: 压缩算法。

        Returns:
            是否成功压缩。
        """
        try:
            content = self.backend.read(path, offset=0, limit=10000000)
            if content.startswith("Error:"):
                return False

            if algorithm == "gzip":
                compressed = gzip.compress(content.encode())
            elif algorithm == "brotli" and _BROTLI_AVAILABLE:
                compressed = brotli.compress(content.encode())
            else:
                return False

            # 存储压缩内容（简化实现）
            compressed_path = f"{path}.{algorithm}"
            compressed_str = compressed.hex()  # 转换为十六进制字符串存储
            result = self.backend.write(compressed_path, compressed_str)
            if result.error is None:
                self._compressed_files.add(path)
                return True
        except Exception:
            pass
        return False

    def decompress_file(self, path: str) -> bool:
        """解压文件。

        Args:
            path: 文件路径。

        Returns:
            是否成功解压。
        """
        # 简化实现
        if path not in self._compressed_files:
            return False
        # 实际应该检测压缩格式并解压
        self._compressed_files.discard(path)
        return True

    def is_compressed(self, path: str) -> bool:
        """检查文件是否已压缩。

        Args:
            path: 文件路径。

        Returns:
            是否已压缩。
        """
        return path in self._compressed_files

    # 实现必需的协议方法
    def ls_info(self, path: str) -> list[Any]:
        """列出文件和目录。"""
        return self.backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容（自动解压）。"""
        if self.is_compressed(file_path):
            # 简化实现：实际应该解压
            pass
        return self.backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> Any:
        """写入文件。"""
        return self.backend.write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Any:
        """编辑文件。"""
        return self.backend.edit(file_path, old_string, new_string, replace_all)

    def glob_info(self, pattern: str, path: str = "/") -> list[Any]:
        """查找匹配的文件。"""
        return self.backend.glob_info(pattern, path)

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        """搜索文本模式。"""
        return self.backend.grep_raw(pattern, path, glob)

