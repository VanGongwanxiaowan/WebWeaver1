"""Monitoring and diagnostics: health checks, performance analysis, statistics, error tracking."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from webweaver.backends.protocol import BackendProtocol


@dataclass
class HealthStatus:
    """健康状态。"""

    healthy: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceStats:
    """性能统计。"""

    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    average_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    total_bytes_read: int = 0
    total_bytes_written: int = 0
    cache_hit_rate: float = 0.0


@dataclass
class StorageStats:
    """存储统计。"""

    total_files: int = 0
    total_size_bytes: int = 0
    average_file_size_bytes: float = 0.0
    largest_file_bytes: int = 0
    smallest_file_bytes: int = 0


@dataclass
class ErrorReport:
    """错误报告。"""

    error_type: str
    message: str
    path: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    count: int = 1


class HealthChecker:
    """健康检查器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化健康检查器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend

    def check_health(self) -> HealthStatus:
        """检查后端健康状态。

        Returns:
            健康状态对象。
        """
        try:
            # 测试基本操作
            start_time = time.time()
            files = self.backend.ls_info("/")
            latency_ms = (time.time() - start_time) * 1000

            # 检查响应时间
            if latency_ms > 1000:
                return HealthStatus(
                    healthy=False,
                    message=f"High latency: {latency_ms:.2f}ms",
                    details={"latency_ms": latency_ms, "file_count": len(files)},
                )

            return HealthStatus(
                healthy=True,
                message="Backend is healthy",
                details={"latency_ms": latency_ms, "file_count": len(files)},
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                message=f"Health check failed: {str(e)}",
                details={"error": str(e)},
            )


class PerformanceAnalyzer:
    """性能分析器。"""

    def __init__(self):
        """初始化性能分析器。"""
        self.operation_times: list[tuple[str, float]] = []
        self.operation_results: list[tuple[str, bool]] = []
        self.bytes_transferred: list[tuple[str, int]] = []

    def record_operation(self, operation: str, latency_ms: float, success: bool, bytes_transferred: int = 0):
        """记录操作。

        Args:
            operation: 操作名称。
            latency_ms: 延迟（毫秒）。
            success: 是否成功。
            bytes_transferred: 传输的字节数。
        """
        self.operation_times.append((operation, latency_ms))
        self.operation_results.append((operation, success))
        if bytes_transferred > 0:
            self.bytes_transferred.append((operation, bytes_transferred))

    def get_stats(self) -> PerformanceStats:
        """获取性能统计。

        Returns:
            性能统计对象。
        """
        if not self.operation_times:
            return PerformanceStats()

        latencies = [lat for _, lat in self.operation_times]
        latencies.sort()

        total_ops = len(self.operation_times)
        successful_ops = sum(1 for _, success in self.operation_results if success)
        failed_ops = total_ops - successful_ops

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
        p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0.0

        total_read = sum(bytes for op, bytes in self.bytes_transferred if "read" in op.lower())
        total_written = sum(bytes for op, bytes in self.bytes_transferred if "write" in op.lower())

        return PerformanceStats(
            total_operations=total_ops,
            successful_operations=successful_ops,
            failed_operations=failed_ops,
            average_latency_ms=avg_latency,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            p99_latency_ms=p99,
            total_bytes_read=total_read,
            total_bytes_written=total_written,
        )

    def identify_bottlenecks(self) -> list[dict[str, Any]]:
        """识别性能瓶颈。

        Returns:
            瓶颈列表，每个包含 operation, average_latency, count。
        """
        operation_stats: dict[str, list[float]] = defaultdict(list)
        for operation, latency in self.operation_times:
            operation_stats[operation].append(latency)

        bottlenecks = []
        for operation, latencies in operation_stats.items():
            avg_latency = sum(latencies) / len(latencies)
            if avg_latency > 100:  # 超过 100ms 认为是瓶颈
                bottlenecks.append({
                    "operation": operation,
                    "average_latency_ms": avg_latency,
                    "count": len(latencies),
                })

        return sorted(bottlenecks, key=lambda x: x["average_latency_ms"], reverse=True)


class StorageAnalyzer:
    """存储分析器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化存储分析器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend

    def get_stats(self) -> StorageStats:
        """获取存储统计。

        Returns:
            存储统计对象。
        """
        files = self.backend.ls_info("/")
        file_sizes = [f.size or 0 for f in files if not f.is_dir and f.size is not None]

        if not file_sizes:
            return StorageStats()

        total_size = sum(file_sizes)
        avg_size = total_size / len(file_sizes) if file_sizes else 0.0
        max_size = max(file_sizes) if file_sizes else 0
        min_size = min(file_sizes) if file_sizes else 0

        return StorageStats(
            total_files=len(file_sizes),
            total_size_bytes=total_size,
            average_file_size_bytes=avg_size,
            largest_file_bytes=max_size,
            smallest_file_bytes=min_size,
        )


class ErrorTracker:
    """错误追踪器。"""

    def __init__(self):
        """初始化错误追踪器。"""
        self.errors: dict[str, ErrorReport] = {}

    def record_error(self, error_type: str, message: str, path: str | None = None):
        """记录错误。

        Args:
            error_type: 错误类型。
            message: 错误消息。
            path: 文件路径。
        """
        key = f"{error_type}:{path or 'global'}"
        if key in self.errors:
            self.errors[key].count += 1
        else:
            self.errors[key] = ErrorReport(
                error_type=error_type,
                message=message,
                path=path,
            )

    def get_error_reports(self) -> list[ErrorReport]:
        """获取错误报告。

        Returns:
            错误报告列表。
        """
        return list(self.errors.values())

    def get_top_errors(self, limit: int = 10) -> list[ErrorReport]:
        """获取最常见的错误。

        Args:
            limit: 返回数量限制。

        Returns:
            错误报告列表。
        """
        return sorted(self.errors.values(), key=lambda x: x.count, reverse=True)[:limit]

    def clear_errors(self):
        """清除所有错误记录。"""
        self.errors.clear()


class MonitoringBackend(BackendProtocol):
    """带监控功能的后端包装器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化监控后端。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self.health_checker = HealthChecker(backend)
        self.performance_analyzer = PerformanceAnalyzer()
        self.storage_analyzer = StorageAnalyzer(backend)
        self.error_tracker = ErrorTracker()

    def check_health(self) -> HealthStatus:
        """检查健康状态。"""
        return self.health_checker.check_health()

    def get_performance_stats(self) -> PerformanceStats:
        """获取性能统计。"""
        return self.performance_analyzer.get_stats()

    def get_storage_stats(self) -> StorageStats:
        """获取存储统计。"""
        return self.storage_analyzer.get_stats()

    def get_error_reports(self) -> list[ErrorReport]:
        """获取错误报告。"""
        return self.error_tracker.get_error_reports()

    def identify_bottlenecks(self) -> list[dict[str, Any]]:
        """识别性能瓶颈。"""
        return self.performance_analyzer.identify_bottlenecks()

    # 实现必需的协议方法（带监控）
    def ls_info(self, path: str) -> list[Any]:
        """列出文件和目录。"""
        start_time = time.time()
        try:
            result = self.backend.ls_info(path)
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("ls_info", latency_ms, True)
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("ls_info", latency_ms, False)
            self.error_tracker.record_error("ls_info_error", str(e), path)
            raise

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        start_time = time.time()
        try:
            result = self.backend.read(file_path, offset, limit)
            latency_ms = (time.time() - start_time) * 1000
            bytes_transferred = len(result.encode())
            self.performance_analyzer.record_operation("read", latency_ms, True, bytes_transferred)
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("read", latency_ms, False)
            self.error_tracker.record_error("read_error", str(e), file_path)
            raise

    def write(self, file_path: str, content: str) -> Any:
        """写入文件。"""
        start_time = time.time()
        try:
            result = self.backend.write(file_path, content)
            latency_ms = (time.time() - start_time) * 1000
            bytes_transferred = len(content.encode())
            self.performance_analyzer.record_operation("write", latency_ms, result.error is None, bytes_transferred)
            if result.error:
                self.error_tracker.record_error("write_error", result.error, file_path)
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("write", latency_ms, False)
            self.error_tracker.record_error("write_error", str(e), file_path)
            raise

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Any:
        """编辑文件。"""
        start_time = time.time()
        try:
            result = self.backend.edit(file_path, old_string, new_string, replace_all)
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("edit", latency_ms, result.error is None)
            if result.error:
                self.error_tracker.record_error("edit_error", result.error, file_path)
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("edit", latency_ms, False)
            self.error_tracker.record_error("edit_error", str(e), file_path)
            raise

    def glob_info(self, pattern: str, path: str = "/") -> list[Any]:
        """查找匹配的文件。"""
        start_time = time.time()
        try:
            result = self.backend.glob_info(pattern, path)
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("glob_info", latency_ms, True)
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("glob_info", latency_ms, False)
            self.error_tracker.record_error("glob_info_error", str(e), path)
            raise

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        """搜索文本模式。"""
        start_time = time.time()
        try:
            result = self.backend.grep_raw(pattern, path, glob)
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("grep_raw", latency_ms, True)
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.performance_analyzer.record_operation("grep_raw", latency_ms, False)
            self.error_tracker.record_error("grep_raw_error", str(e), path)
            raise

