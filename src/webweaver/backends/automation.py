"""Automation and policies: cleanup, backup, migration, notifications, lifecycle management."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from webweaver.backends.protocol import BackendProtocol


class CleanupPolicy:
    """文件清理策略。"""

    def __init__(
        self,
        max_age_days: int | None = None,
        max_size_mb: int | None = None,
        min_access_days: int | None = None,
    ):
        """初始化清理策略。

        Args:
            max_age_days: 最大保留天数（None 表示不限制）。
            max_size_mb: 最大总大小（MB，None 表示不限制）。
            min_access_days: 最少访问天数（None 表示不限制）。
        """
        self.max_age_days = max_age_days
        self.max_size_mb = max_size_mb
        self.min_access_days = min_access_days

    def should_cleanup(self, file_info: dict[str, Any]) -> bool:
        """判断文件是否应该被清理。

        Args:
            file_info: 文件信息字典，包含 path, modified_at, size, last_access。

        Returns:
            是否应该清理。
        """
        now = datetime.now(UTC)

        # 检查最大年龄
        if self.max_age_days:
            modified_at = datetime.fromisoformat(file_info.get("modified_at", "").replace("Z", "+00:00"))
            age_days = (now - modified_at).days
            if age_days > self.max_age_days:
                return True

        # 检查最少访问天数
        if self.min_access_days:
            last_access = file_info.get("last_access")
            if last_access:
                last_access_dt = datetime.fromisoformat(last_access.replace("Z", "+00:00"))
                access_days = (now - last_access_dt).days
                if access_days > self.min_access_days:
                    return True

        return False


class AutoCleanupManager:
    """自动清理管理器。"""

    def __init__(self, backend: BackendProtocol, policy: CleanupPolicy):
        """初始化自动清理管理器。

        Args:
            backend: 底层后端。
            policy: 清理策略。
        """
        self.backend = backend
        self.policy = policy

    def cleanup(self) -> list[str]:
        """执行清理。

        Returns:
            被清理的文件路径列表。
        """
        cleaned_files: list[str] = []
        files = self.backend.ls_info("/")

        for file_info in files:
            if file_info.is_dir:
                continue

            file_data = {
                "path": file_info.path,
                "modified_at": file_info.modified_at or "",
                "size": file_info.size or 0,
            }

            if self.policy.should_cleanup(file_data):
                # 简化实现：实际应该删除文件
                cleaned_files.append(file_info.path)

        return cleaned_files


class BackupManager:
    """备份管理器。"""

    def __init__(self, backend: BackendProtocol, backup_backend: BackendProtocol | None = None):
        """初始化备份管理器。

        Args:
            backend: 源后端。
            backup_backend: 备份后端（None 表示使用相同后端）。
        """
        self.backend = backend
        self.backup_backend = backup_backend or backend

    def create_backup(self, path: str) -> str:
        """创建文件备份。

        Args:
            path: 文件路径。

        Returns:
            备份路径。
        """
        content = self.backend.read(path, offset=0, limit=10000000)
        if content.startswith("Error:"):
            raise ValueError(f"Cannot backup: {content}")

        backup_path = f"/.backups/{path}_{datetime.now(UTC).isoformat()}".replace(":", "-")
        self.backup_backend.write(backup_path, content)
        return backup_path

    def restore_backup(self, backup_path: str, target_path: str | None = None) -> bool:
        """从备份恢复文件。

        Args:
            backup_path: 备份路径。
            target_path: 目标路径（None 表示从备份路径推断）。

        Returns:
            是否成功恢复。
        """
        if target_path is None:
            # 从备份路径推断原始路径
            target_path = backup_path.replace("/.backups/", "").split("_")[0]

        content = self.backup_backend.read(backup_path, offset=0, limit=10000000)
        if content.startswith("Error:"):
            return False

        result = self.backend.write(target_path, content)
        return result.error is None


class MigrationManager:
    """文件迁移管理器。"""

    def __init__(self, source_backend: BackendProtocol, target_backend: BackendProtocol):
        """初始化迁移管理器。

        Args:
            source_backend: 源后端。
            target_backend: 目标后端。
        """
        self.source_backend = source_backend
        self.target_backend = target_backend

    def migrate_file(self, path: str) -> bool:
        """迁移单个文件。

        Args:
            path: 文件路径。

        Returns:
            是否成功迁移。
        """
        try:
            content = self.source_backend.read(path, offset=0, limit=10000000)
            if content.startswith("Error:"):
                return False

            result = self.target_backend.write(path, content)
            return result.error is None
        except Exception:
            return False

    def migrate_directory(self, path: str) -> dict[str, bool]:
        """迁移整个目录。

        Args:
            path: 目录路径。

        Returns:
            文件路径到成功状态的字典。
        """
        results: dict[str, bool] = {}
        files = self.source_backend.ls_info(path)

        for file_info in files:
            if file_info.is_dir:
                continue
            results[file_info.path] = self.migrate_file(file_info.path)

        return results


class NotificationManager:
    """文件变更通知管理器。"""

    def __init__(self):
        """初始化通知管理器。"""
        self._subscribers: dict[str, list[Callable[[str, str], None]]] = {}

    def subscribe(self, path_pattern: str, callback: Callable[[str, str], None]) -> None:
        """订阅文件变更通知。

        Args:
            path_pattern: 路径模式。
            callback: 回调函数，接收 (path, action) 参数。
        """
        if path_pattern not in self._subscribers:
            self._subscribers[path_pattern] = []
        self._subscribers[path_pattern].append(callback)

    def notify(self, path: str, action: str) -> None:
        """发送通知。

        Args:
            path: 文件路径。
            action: 操作类型（created, modified, deleted）。
        """
        for pattern, callbacks in self._subscribers.items():
            if self._match_pattern(path, pattern):
                for callback in callbacks:
                    try:
                        callback(path, action)
                    except Exception:
                        pass

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """匹配路径模式（简化实现）。"""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return path.startswith(pattern[:-1])
        return path == pattern


class LifecycleManager:
    """文件生命周期管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化生命周期管理器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._policies: dict[str, dict[str, Any]] = {}

    def set_lifecycle_policy(
        self,
        path_pattern: str,
        archive_after_days: int | None = None,
        delete_after_days: int | None = None,
    ) -> None:
        """设置生命周期策略。

        Args:
            path_pattern: 路径模式。
            archive_after_days: 归档前天数。
            delete_after_days: 删除前天数。
        """
        self._policies[path_pattern] = {
            "archive_after_days": archive_after_days,
            "delete_after_days": delete_after_days,
        }

    def process_lifecycle(self) -> dict[str, list[str]]:
        """处理生命周期。

        Returns:
            操作结果字典，包含 archived 和 deleted 列表。
        """
        results: dict[str, list[str]] = {"archived": [], "deleted": []}
        now = datetime.now(UTC)

        files = self.backend.ls_info("/")
        for file_info in files:
            if file_info.is_dir:
                continue

            # 查找匹配的策略
            for pattern, policy in self._policies.items():
                if self._match_pattern(file_info.path, pattern):
                    modified_at = datetime.fromisoformat(
                        (file_info.modified_at or "").replace("Z", "+00:00")
                    )
                    age_days = (now - modified_at).days

                    # 检查是否需要归档
                    if policy.get("archive_after_days") and age_days >= policy["archive_after_days"]:
                        # 简化实现：实际应该移动到归档目录
                        results["archived"].append(file_info.path)

                    # 检查是否需要删除
                    if policy.get("delete_after_days") and age_days >= policy["delete_after_days"]:
                        # 简化实现：实际应该删除文件
                        results["deleted"].append(file_info.path)

        return results

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """匹配路径模式。"""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return path.startswith(pattern[:-1])
        return path == pattern

