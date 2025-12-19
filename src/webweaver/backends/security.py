"""Security enhancements: audit logging, encryption, integrity checks, quota management."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from webweaver.backends.extended_protocol import AuditLogEntry, QuotaBackendProtocol
from webweaver.backends.protocol import BackendProtocol


class AuditLogger:
    """审计日志记录器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化审计日志记录器。

        Args:
            backend: 底层后端用于存储日志。
        """
        self.backend = backend
        self._logs: list[AuditLogEntry] = []

    def _get_log_path(self, timestamp: str | None = None) -> str:
        """获取日志文件路径。"""
        if timestamp is None:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%d")
        return f"/.audit/logs/{timestamp}.jsonl"

    def log_action(
        self,
        action: str,
        path: str,
        user: str | None = None,
        success: bool = True,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录操作日志。

        Args:
            action: 操作类型。
            path: 文件路径。
            user: 用户标识。
            success: 是否成功。
            error: 错误信息。
            metadata: 额外元数据。
        """
        entry = AuditLogEntry(
            timestamp=datetime.now(UTC).isoformat(),
            action=action,
            path=path,
            user=user,
            success=success,
            error=error,
            metadata=metadata,
        )
        self._logs.append(entry)

        # 持久化到后端（简化实现）
        log_path = self._get_log_path()
        log_line = json.dumps({
            "timestamp": entry.timestamp,
            "action": entry.action,
            "path": entry.path,
            "user": entry.user,
            "success": entry.success,
            "error": entry.error,
            "metadata": entry.metadata,
        }) + "\n"
        try:
            # 追加到日志文件
            existing = self.backend.read(log_path, offset=0, limit=100000)
            if existing.startswith("Error:"):
                self.backend.write(log_path, log_line)
            else:
                self.backend.edit(log_path, "", existing + log_line, replace_all=True)
        except Exception:
            pass

    def get_audit_logs(
        self,
        path: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[AuditLogEntry]:
        """获取审计日志。

        Args:
            path: 过滤路径。
            start_time: 开始时间（ISO 格式）。
            end_time: 结束时间（ISO 格式）。

        Returns:
            日志条目列表。
        """
        logs = self._logs.copy()

        # 过滤
        if path:
            logs = [log for log in logs if log.path == path]
        if start_time:
            logs = [log for log in logs if log.timestamp >= start_time]
        if end_time:
            logs = [log for log in logs if log.timestamp <= end_time]

        return logs


class IntegrityChecker:
    """文件完整性检查器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化完整性检查器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._checksums: dict[str, str] = {}

    def _get_checksum_path(self, file_path: str) -> str:
        """获取校验和文件的路径。"""
        return f"/.checksums{file_path}.sha256"

    def calculate_checksum(self, content: str) -> str:
        """计算内容的校验和。

        Args:
            content: 文件内容。

        Returns:
            SHA256 校验和。
        """
        return hashlib.sha256(content.encode()).hexdigest()

    def store_checksum(self, path: str, content: str) -> None:
        """存储文件的校验和。

        Args:
            path: 文件路径。
            content: 文件内容。
        """
        checksum = self.calculate_checksum(content)
        checksum_path = self._get_checksum_path(path)
        self.backend.write(checksum_path, checksum)
        self._checksums[path] = checksum

    def verify_checksum(self, path: str, content: str) -> bool:
        """验证文件的校验和。

        Args:
            path: 文件路径。
            content: 文件内容。

        Returns:
            是否匹配。
        """
        current_checksum = self.calculate_checksum(content)
        stored_checksum = self._checksums.get(path)
        if stored_checksum is None:
            # 从后端加载
            checksum_path = self._get_checksum_path(path)
            try:
                stored_checksum = self.backend.read(checksum_path, offset=0, limit=100).strip()
                self._checksums[path] = stored_checksum
            except Exception:
                return False
        return current_checksum == stored_checksum


class QuotaManager:
    """配额管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化配额管理器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._quotas: dict[str, dict[str, Any]] = {}

    def _get_quota_path(self, path: str | None = None) -> str:
        """获取配额文件的路径。"""
        if path is None:
            return "/.quotas/default.json"
        return f"/.quotas{path}.json"

    def get_quota(self, path: str | None = None) -> dict[str, Any]:
        """获取配额信息。

        Args:
            path: 路径（None 表示默认配额）。

        Returns:
            配额信息字典，包含 max_size, max_files, current_size, current_files。
        """
        if path in self._quotas:
            return self._quotas[path]

        # 从后端加载
        quota_path = self._get_quota_path(path)
        try:
            content = self.backend.read(quota_path, offset=0, limit=1000)
            if not content.startswith("Error:"):
                quota = json.loads(content)
                self._quotas[path or ""] = quota
                return quota
        except Exception:
            pass

        # 默认配额（无限制）
        return {
            "max_size": -1,  # -1 表示无限制
            "max_files": -1,
            "current_size": 0,
            "current_files": 0,
        }

    def set_quota(self, path: str, max_size: int, max_files: int | None = None) -> bool:
        """设置配额限制。

        Args:
            path: 路径。
            max_size: 最大大小（字节）。
            max_files: 最大文件数（None 表示无限制）。

        Returns:
            是否成功设置。
        """
        quota = {
            "max_size": max_size,
            "max_files": max_files if max_files is not None else -1,
            "current_size": 0,
            "current_files": 0,
        }
        quota_path = self._get_quota_path(path)
        try:
            content = json.dumps(quota, indent=2)
            result = self.backend.write(quota_path, content)
            if result.error is None:
                self._quotas[path] = quota
                return True
        except Exception:
            pass
        return False

    def check_quota(self, path: str, size: int) -> tuple[bool, str | None]:
        """检查是否超出配额。

        Args:
            path: 文件路径。
            size: 文件大小（字节）。

        Returns:
            (是否允许, 错误消息)。
        """
        quota = self.get_quota(path)
        current_size = quota.get("current_size", 0)
        max_size = quota.get("max_size", -1)

        if max_size > 0 and current_size + size > max_size:
            return False, f"Quota exceeded: {current_size + size} > {max_size} bytes"

        max_files = quota.get("max_files", -1)
        current_files = quota.get("current_files", 0)
        if max_files > 0 and current_files + 1 > max_files:
            return False, f"File count quota exceeded: {current_files + 1} > {max_files}"

        return True, None

    def update_usage(self, path: str, size_delta: int, file_delta: int = 0) -> None:
        """更新使用量。

        Args:
            path: 路径。
            size_delta: 大小变化（字节）。
            file_delta: 文件数变化。
        """
        quota = self.get_quota(path)
        quota["current_size"] = quota.get("current_size", 0) + size_delta
        quota["current_files"] = quota.get("current_files", 0) + file_delta
        self._quotas[path or ""] = quota


class RateLimiter:
    """访问频率限制器。"""

    def __init__(self, max_requests_per_minute: int = 60):
        """初始化频率限制器。

        Args:
            max_requests_per_minute: 每分钟最大请求数。
        """
        self.max_requests_per_minute = max_requests_per_minute
        self._requests: dict[str, list[float]] = {}

    def check_rate_limit(self, identifier: str) -> tuple[bool, str | None]:
        """检查是否超出频率限制。

        Args:
            identifier: 标识符（如用户 ID 或 IP）。

        Returns:
            (是否允许, 错误消息)。
        """
        import time

        now = time.time()
        if identifier not in self._requests:
            self._requests[identifier] = []

        # 清理一分钟前的记录
        self._requests[identifier] = [
            req_time for req_time in self._requests[identifier] if now - req_time < 60
        ]

        if len(self._requests[identifier]) >= self.max_requests_per_minute:
            return False, f"Rate limit exceeded: {len(self._requests[identifier])} requests in the last minute"

        self._requests[identifier].append(now)
        return True, None

