"""Extended protocol definitions for enhanced backend features."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from webweaver.backends.protocol import BackendProtocol


# ==================== 文件元数据 ====================

@dataclass
class FileMetadata:
    """文件元数据结构。"""

    path: str
    tags: list[str] | None = None
    category: str | None = None
    custom_attributes: dict[str, Any] | None = None
    created_by: str | None = None
    description: str | None = None


# ==================== 文件版本控制 ====================

@dataclass
class FileVersion:
    """文件版本信息。"""

    version: int
    path: str
    content: str
    created_at: str
    created_by: str | None = None
    message: str | None = None
    checksum: str | None = None


# ==================== 文件权限 ====================

@dataclass
class FilePermission:
    """文件权限信息。"""

    path: str
    read: bool = True
    write: bool = True
    owner: str | None = None
    groups: list[str] | None = None


# ==================== 文件锁定 ====================

@dataclass
class FileLock:
    """文件锁定信息。"""

    path: str
    locked_by: str
    locked_at: str
    expires_at: str | None = None
    reason: str | None = None


# ==================== 文件快照 ====================

@dataclass
class FileSnapshot:
    """文件快照信息。"""

    snapshot_id: str
    path: str
    content: str
    created_at: str
    metadata: dict[str, Any] | None = None


# ==================== 审计日志 ====================

@dataclass
class AuditLogEntry:
    """审计日志条目。"""

    timestamp: str
    action: str  # read, write, edit, delete, etc.
    path: str
    user: str | None = None
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] | None = None


# ==================== 性能指标 ====================

@dataclass
class BackendMetrics:
    """后端性能指标。"""

    operation_count: int = 0
    total_latency_ms: float = 0.0
    error_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    bytes_read: int = 0
    bytes_written: int = 0


# ==================== 扩展协议接口 ====================


class AsyncBackendProtocol(BackendProtocol):
    """支持异步操作的后端协议。"""

    @abstractmethod
    async def als_info(self, path: str) -> list[Any]:
        """异步列出文件和目录。"""

    @abstractmethod
    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """异步读取文件内容。"""

    @abstractmethod
    async def awrite(self, file_path: str, content: str) -> Any:
        """异步写入文件。"""

    @abstractmethod
    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> Any:
        """异步编辑文件。"""


class MetadataBackendProtocol(BackendProtocol):
    """支持文件元数据的后端协议。"""

    @abstractmethod
    def get_metadata(self, path: str) -> FileMetadata | None:
        """获取文件元数据。"""

    @abstractmethod
    def set_metadata(self, path: str, metadata: FileMetadata) -> bool:
        """设置文件元数据。"""

    @abstractmethod
    def search_by_metadata(self, filters: dict[str, Any]) -> list[str]:
        """根据元数据搜索文件。"""


class VersionControlBackendProtocol(BackendProtocol):
    """支持版本控制的后端协议。"""

    @abstractmethod
    def create_version(self, path: str, message: str | None = None) -> FileVersion:
        """创建文件版本。"""

    @abstractmethod
    def list_versions(self, path: str) -> list[FileVersion]:
        """列出文件的所有版本。"""

    @abstractmethod
    def get_version(self, path: str, version: int) -> FileVersion | None:
        """获取特定版本的文件。"""

    @abstractmethod
    def restore_version(self, path: str, version: int) -> bool:
        """恢复文件到特定版本。"""


class PermissionBackendProtocol(BackendProtocol):
    """支持权限管理的后端协议。"""

    @abstractmethod
    def get_permission(self, path: str) -> FilePermission:
        """获取文件权限。"""

    @abstractmethod
    def set_permission(self, path: str, permission: FilePermission) -> bool:
        """设置文件权限。"""

    @abstractmethod
    def check_permission(self, path: str, action: Literal["read", "write"]) -> bool:
        """检查是否有权限执行操作。"""


class LockBackendProtocol(BackendProtocol):
    """支持文件锁定的后端协议。"""

    @abstractmethod
    def lock_file(self, path: str, locked_by: str, expires_at: str | None = None) -> FileLock | None:
        """锁定文件。"""

    @abstractmethod
    def unlock_file(self, path: str, locked_by: str) -> bool:
        """解锁文件。"""

    @abstractmethod
    def get_lock(self, path: str) -> FileLock | None:
        """获取文件锁定信息。"""


class SnapshotBackendProtocol(BackendProtocol):
    """支持文件快照的后端协议。"""

    @abstractmethod
    def create_snapshot(self, path: str, metadata: dict[str, Any] | None = None) -> FileSnapshot:
        """创建文件快照。"""

    @abstractmethod
    def list_snapshots(self, path: str) -> list[FileSnapshot]:
        """列出文件的所有快照。"""

    @abstractmethod
    def restore_snapshot(self, snapshot_id: str) -> bool:
        """从快照恢复文件。"""


class AuditBackendProtocol(BackendProtocol):
    """支持审计日志的后端协议。"""

    @abstractmethod
    def log_action(self, entry: AuditLogEntry) -> None:
        """记录操作日志。"""

    @abstractmethod
    def get_audit_logs(
        self,
        path: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[AuditLogEntry]:
        """获取审计日志。"""


class MetricsBackendProtocol(BackendProtocol):
    """支持性能指标的后端协议。"""

    @abstractmethod
    def get_metrics(self) -> BackendMetrics:
        """获取性能指标。"""

    @abstractmethod
    def reset_metrics(self) -> None:
        """重置性能指标。"""


class CompressionBackendProtocol(BackendProtocol):
    """支持文件压缩的后端协议。"""

    @abstractmethod
    def compress_file(self, path: str, algorithm: Literal["gzip", "brotli"] = "gzip") -> bool:
        """压缩文件。"""

    @abstractmethod
    def decompress_file(self, path: str) -> bool:
        """解压文件。"""

    @abstractmethod
    def is_compressed(self, path: str) -> bool:
        """检查文件是否已压缩。"""


class QuotaBackendProtocol(BackendProtocol):
    """支持配额管理的后端协议。"""

    @abstractmethod
    def get_quota(self, path: str | None = None) -> dict[str, Any]:
        """获取配额信息。"""

    @abstractmethod
    def set_quota(self, path: str, max_size: int, max_files: int | None = None) -> bool:
        """设置配额限制。"""

    @abstractmethod
    def check_quota(self, path: str, size: int) -> tuple[bool, str | None]:
        """检查是否超出配额。"""

