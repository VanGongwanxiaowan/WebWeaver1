"""File management enhancements: version control, metadata, permissions, locking, snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from webweaver.backends.extended_protocol import (
    FileLock,
    FileMetadata,
    FilePermission,
    FileSnapshot,
    FileVersion,
    LockBackendProtocol,
    MetadataBackendProtocol,
    PermissionBackendProtocol,
    SnapshotBackendProtocol,
    VersionControlBackendProtocol,
)
from webweaver.backends.protocol import BackendProtocol


class FileVersionManager:
    """文件版本管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化版本管理器。

        Args:
            backend: 底层后端用于存储版本数据。
        """
        self.backend = backend
        self._versions: dict[str, list[FileVersion]] = {}

    def _get_version_path(self, file_path: str, version: int) -> str:
        """获取版本文件的存储路径。"""
        return f"/.versions{file_path}/v{version}"

    def _get_metadata_path(self, file_path: str) -> str:
        """获取版本元数据文件的路径。"""
        return f"/.versions{file_path}/metadata.json"

    def create_version(self, path: str, message: str | None = None, created_by: str | None = None) -> FileVersion:
        """创建文件版本。

        Args:
            path: 文件路径。
            message: 版本消息。
            created_by: 创建者。

        Returns:
            创建的版本对象。
        """
        # 读取当前文件内容
        content = self.backend.read(path, offset=0, limit=1000000)  # 读取完整文件
        if content.startswith("Error:"):
            raise ValueError(f"Cannot create version: {content}")

        # 计算校验和
        checksum = hashlib.sha256(content.encode()).hexdigest()

        # 获取现有版本
        versions = self.list_versions(path)
        next_version = len(versions) + 1

        # 创建版本对象
        version = FileVersion(
            version=next_version,
            path=path,
            content=content,
            created_at=datetime.now(UTC).isoformat(),
            created_by=created_by,
            message=message,
            checksum=checksum,
        )

        # 存储版本
        version_path = self._get_version_path(path, next_version)
        self.backend.write(version_path, json.dumps({
            "version": version.version,
            "path": version.path,
            "content": version.content,
            "created_at": version.created_at,
            "created_by": version.created_by,
            "message": version.message,
            "checksum": version.checksum,
        }))

        # 更新版本列表
        if path not in self._versions:
            self._versions[path] = []
        self._versions[path].append(version)

        return version

    def list_versions(self, path: str) -> list[FileVersion]:
        """列出文件的所有版本。

        Args:
            path: 文件路径。

        Returns:
            版本列表。
        """
        if path in self._versions:
            return self._versions[path]

        # 从后端加载版本
        versions: list[FileVersion] = []
        metadata_path = self._get_metadata_path(path)
        try:
            metadata_content = self.backend.read(metadata_path, offset=0, limit=10000)
            if not metadata_content.startswith("Error:"):
                metadata = json.loads(metadata_content)
                for v_data in metadata.get("versions", []):
                    versions.append(FileVersion(**v_data))
        except Exception:
            pass

        self._versions[path] = versions
        return versions

    def get_version(self, path: str, version: int) -> FileVersion | None:
        """获取特定版本的文件。

        Args:
            path: 文件路径。
            version: 版本号。

        Returns:
            版本对象，如果不存在则返回 None。
        """
        versions = self.list_versions(path)
        for v in versions:
            if v.version == version:
                return v
        return None

    def restore_version(self, path: str, version: int) -> bool:
        """恢复文件到特定版本。

        Args:
            path: 文件路径。
            version: 版本号。

        Returns:
            是否成功恢复。
        """
        version_obj = self.get_version(path, version)
        if version_obj is None:
            return False

        # 创建当前版本的备份
        self.create_version(path, message=f"Backup before restoring to v{version}")

        # 恢复内容
        result = self.backend.write(path, version_obj.content)
        return result.error is None


class FileMetadataManager:
    """文件元数据管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化元数据管理器。

        Args:
            backend: 底层后端用于存储元数据。
        """
        self.backend = backend
        self._metadata: dict[str, FileMetadata] = {}

    def _get_metadata_path(self, file_path: str) -> str:
        """获取元数据文件的路径。"""
        return f"/.metadata{file_path}.json"

    def get_metadata(self, path: str) -> FileMetadata | None:
        """获取文件元数据。

        Args:
            path: 文件路径。

        Returns:
            元数据对象，如果不存在则返回 None。
        """
        if path in self._metadata:
            return self._metadata[path]

        # 从后端加载
        metadata_path = self._get_metadata_path(path)
        try:
            content = self.backend.read(metadata_path, offset=0, limit=10000)
            if not content.startswith("Error:"):
                data = json.loads(content)
                metadata = FileMetadata(**data)
                self._metadata[path] = metadata
                return metadata
        except Exception:
            pass

        return None

    def set_metadata(self, path: str, metadata: FileMetadata) -> bool:
        """设置文件元数据。

        Args:
            path: 文件路径。
            metadata: 元数据对象。

        Returns:
            是否成功设置。
        """
        metadata_path = self._get_metadata_path(path)
        try:
            content = json.dumps({
                "path": metadata.path,
                "tags": metadata.tags,
                "category": metadata.category,
                "custom_attributes": metadata.custom_attributes,
                "created_by": metadata.created_by,
                "description": metadata.description,
            }, indent=2)
            result = self.backend.write(metadata_path, content)
            if result.error is None:
                self._metadata[path] = metadata
                return True
        except Exception:
            pass
        return False

    def search_by_metadata(self, filters: dict[str, Any]) -> list[str]:
        """根据元数据搜索文件。

        Args:
            filters: 过滤条件字典。

        Returns:
            匹配的文件路径列表。
        """
        matching_paths: list[str] = []
        # 这里简化实现，实际应该索引元数据以提高性能
        for path, metadata in self._metadata.items():
            match = True
            for key, value in filters.items():
                if key == "tags" and metadata.tags:
                    tag_list = value if isinstance(value, list) else [value]
                    if not any(tag in metadata.tags for tag in tag_list):
                        match = False
                        break
                elif key == "category" and metadata.category != value:
                    match = False
                    break
                elif key in metadata.custom_attributes or {}:
                    if metadata.custom_attributes.get(key) != value:
                        match = False
                        break
            if match:
                matching_paths.append(path)
        return matching_paths


class FileLockManager:
    """文件锁定管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化锁定管理器。

        Args:
            backend: 底层后端用于存储锁定信息。
        """
        self.backend = backend
        self._locks: dict[str, FileLock] = {}

    def _get_lock_path(self, file_path: str) -> str:
        """获取锁定文件的路径。"""
        return f"/.locks{file_path}.json"

    def lock_file(self, path: str, locked_by: str, expires_at: str | None = None) -> FileLock | None:
        """锁定文件。

        Args:
            path: 文件路径。
            locked_by: 锁定者。
            expires_at: 过期时间（ISO 格式）。

        Returns:
            锁定对象，如果已被锁定则返回 None。
        """
        existing_lock = self.get_lock(path)
        if existing_lock is not None:
            # 检查是否过期
            if existing_lock.expires_at:
                try:
                    expires = datetime.fromisoformat(existing_lock.expires_at.replace("Z", "+00:00"))
                    if datetime.now(UTC).replace(tzinfo=UTC) > expires:
                        # 已过期，移除
                        self.unlock_file(path, locked_by)
                    else:
                        return None  # 仍被锁定
                except Exception:
                    pass
            else:
                return None  # 仍被锁定

        lock = FileLock(
            path=path,
            locked_by=locked_by,
            locked_at=datetime.now(UTC).isoformat(),
            expires_at=expires_at,
        )

        lock_path = self._get_lock_path(path)
        content = json.dumps({
            "path": lock.path,
            "locked_by": lock.locked_by,
            "locked_at": lock.locked_at,
            "expires_at": lock.expires_at,
            "reason": lock.reason,
        })
        result = self.backend.write(lock_path, content)
        if result.error is None:
            self._locks[path] = lock
            return lock
        return None

    def unlock_file(self, path: str, locked_by: str) -> bool:
        """解锁文件。

        Args:
            path: 文件路径。
            locked_by: 解锁者（必须是锁定者）。

        Returns:
            是否成功解锁。
        """
        lock = self.get_lock(path)
        if lock is None:
            return False
        if lock.locked_by != locked_by:
            return False

        lock_path = self._get_lock_path(path)
        # 删除锁定文件（简化实现，实际应该用 delete 操作）
        self._locks.pop(path, None)
        return True

    def get_lock(self, path: str) -> FileLock | None:
        """获取文件锁定信息。

        Args:
            path: 文件路径。

        Returns:
            锁定对象，如果未锁定则返回 None。
        """
        if path in self._locks:
            return self._locks[path]

        # 从后端加载
        lock_path = self._get_lock_path(path)
        try:
            content = self.backend.read(lock_path, offset=0, limit=1000)
            if not content.startswith("Error:"):
                data = json.loads(content)
                lock = FileLock(**data)
                self._locks[path] = lock
                return lock
        except Exception:
            pass

        return None


class FileSnapshotManager:
    """文件快照管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化快照管理器。

        Args:
            backend: 底层后端用于存储快照。
        """
        self.backend = backend
        self._snapshots: dict[str, list[FileSnapshot]] = {}

    def _get_snapshot_path(self, snapshot_id: str) -> str:
        """获取快照文件的路径。"""
        return f"/.snapshots/{snapshot_id}.json"

    def create_snapshot(self, path: str, metadata: dict[str, Any] | None = None) -> FileSnapshot:
        """创建文件快照。

        Args:
            path: 文件路径。
            metadata: 可选的元数据。

        Returns:
            快照对象。
        """
        # 读取文件内容
        content = self.backend.read(path, offset=0, limit=1000000)
        if content.startswith("Error:"):
            raise ValueError(f"Cannot create snapshot: {content}")

        snapshot_id = f"{path}_{datetime.now(UTC).isoformat()}".replace("/", "_").replace(":", "-")
        snapshot = FileSnapshot(
            snapshot_id=snapshot_id,
            path=path,
            content=content,
            created_at=datetime.now(UTC).isoformat(),
            metadata=metadata,
        )

        # 存储快照
        snapshot_path = self._get_snapshot_path(snapshot_id)
        snapshot_data = {
            "snapshot_id": snapshot.snapshot_id,
            "path": snapshot.path,
            "content": snapshot.content,
            "created_at": snapshot.created_at,
            "metadata": snapshot.metadata,
        }
        self.backend.write(snapshot_path, json.dumps(snapshot_data))

        # 更新快照列表
        if path not in self._snapshots:
            self._snapshots[path] = []
        self._snapshots[path].append(snapshot)

        return snapshot

    def list_snapshots(self, path: str) -> list[FileSnapshot]:
        """列出文件的所有快照。

        Args:
            path: 文件路径。

        Returns:
            快照列表。
        """
        if path in self._snapshots:
            return self._snapshots[path]

        # 从后端加载（简化实现）
        snapshots: list[FileSnapshot] = []
        # 实际应该扫描快照目录
        return snapshots

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """从快照恢复文件。

        Args:
            snapshot_id: 快照 ID。

        Returns:
            是否成功恢复。
        """
        snapshot_path = self._get_snapshot_path(snapshot_id)
        try:
            content = self.backend.read(snapshot_path, offset=0, limit=1000000)
            if content.startswith("Error:"):
                return False
            snapshot_data = json.loads(content)
            snapshot = FileSnapshot(**snapshot_data)

            # 恢复文件
            result = self.backend.write(snapshot.path, snapshot.content)
            return result.error is None
        except Exception:
            return False


class FilePermissionManager:
    """文件权限管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化权限管理器。

        Args:
            backend: 底层后端用于存储权限信息。
        """
        self.backend = backend
        self._permissions: dict[str, FilePermission] = {}

    def _get_permission_path(self, file_path: str) -> str:
        """获取权限文件的路径。"""
        return f"/.permissions{file_path}.json"

    def get_permission(self, path: str) -> FilePermission:
        """获取文件权限。

        Args:
            path: 文件路径。

        Returns:
            权限对象（默认允许读写）。
        """
        if path in self._permissions:
            return self._permissions[path]

        # 从后端加载
        permission_path = self._get_permission_path(path)
        try:
            content = self.backend.read(permission_path, offset=0, limit=1000)
            if not content.startswith("Error:"):
                data = json.loads(content)
                permission = FilePermission(**data)
                self._permissions[path] = permission
                return permission
        except Exception:
            pass

        # 默认权限
        return FilePermission(path=path, read=True, write=True)

    def set_permission(self, path: str, permission: FilePermission) -> bool:
        """设置文件权限。

        Args:
            path: 文件路径。
            permission: 权限对象。

        Returns:
            是否成功设置。
        """
        permission_path = self._get_permission_path(path)
        try:
            content = json.dumps({
                "path": permission.path,
                "read": permission.read,
                "write": permission.write,
                "owner": permission.owner,
                "groups": permission.groups,
            }, indent=2)
            result = self.backend.write(permission_path, content)
            if result.error is None:
                self._permissions[path] = permission
                return True
        except Exception:
            pass
        return False

    def check_permission(self, path: str, action: Literal["read", "write"]) -> bool:
        """检查是否有权限执行操作。

        Args:
            path: 文件路径。
            action: 操作类型（read 或 write）。

        Returns:
            是否有权限。
        """
        permission = self.get_permission(path)
        if action == "read":
            return permission.read
        elif action == "write":
            return permission.write
        return False

