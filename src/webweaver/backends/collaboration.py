"""Collaboration features: file sharing, comments, change notifications, conflict resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from webweaver.backends.protocol import BackendProtocol


@dataclass
class FileComment:
    """文件评论。"""

    comment_id: str
    file_path: str
    user: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    line_number: int | None = None
    resolved: bool = False


@dataclass
class FileShare:
    """文件共享。"""

    share_id: str
    file_path: str
    shared_by: str
    shared_with: list[str]
    permission: Literal["read", "write"] = "read"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None


@dataclass
class FileConflict:
    """文件冲突。"""

    conflict_id: str
    file_path: str
    user1: str
    user2: str
    version1: str
    version2: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FileSharingManager:
    """文件共享管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化文件共享管理器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._shares: dict[str, FileShare] = {}

    def _get_share_path(self, share_id: str) -> str:
        """获取共享文件的路径。"""
        return f"/.shares/{share_id}.json"

    def share_file(
        self,
        file_path: str,
        shared_by: str,
        shared_with: list[str],
        permission: Literal["read", "write"] = "read",
        expires_at: str | None = None,
    ) -> FileShare:
        """共享文件。

        Args:
            file_path: 文件路径。
            shared_by: 共享者。
            shared_with: 共享给的用户列表。
            permission: 权限类型。
            expires_at: 过期时间。

        Returns:
            共享对象。
        """
        share_id = f"{file_path}_{shared_by}_{datetime.now(UTC).isoformat()}".replace("/", "_").replace(":", "-")
        share = FileShare(
            share_id=share_id,
            file_path=file_path,
            shared_by=shared_by,
            shared_with=shared_with,
            permission=permission,
            expires_at=expires_at,
        )

        # 存储共享信息
        share_path = self._get_share_path(share_id)
        share_data = {
            "share_id": share.share_id,
            "file_path": share.file_path,
            "shared_by": share.shared_by,
            "shared_with": share.shared_with,
            "permission": share.permission,
            "created_at": share.created_at,
            "expires_at": share.expires_at,
        }
        self.backend.write(share_path, json.dumps(share_data, indent=2))
        self._shares[share_id] = share

        return share

    def get_shares(self, file_path: str | None = None, user: str | None = None) -> list[FileShare]:
        """获取共享列表。

        Args:
            file_path: 过滤文件路径。
            user: 过滤用户。

        Returns:
            共享列表。
        """
        shares = list(self._shares.values())

        if file_path:
            shares = [s for s in shares if s.file_path == file_path]
        if user:
            shares = [s for s in shares if user in s.shared_with or s.shared_by == user]

        return shares

    def check_permission(self, file_path: str, user: str, action: Literal["read", "write"]) -> bool:
        """检查用户权限。

        Args:
            file_path: 文件路径。
            user: 用户。
            action: 操作类型。

        Returns:
            是否有权限。
        """
        shares = self.get_shares(file_path=file_path, user=user)
        for share in shares:
            if user in share.shared_with:
                if action == "read":
                    return True
                elif action == "write" and share.permission == "write":
                    return True
        return False


class CommentManager:
    """评论管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化评论管理器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._comments: dict[str, FileComment] = {}

    def _get_comments_path(self, file_path: str) -> str:
        """获取评论文件的路径。"""
        return f"/.comments{file_path}.json"

    def add_comment(
        self,
        file_path: str,
        user: str,
        content: str,
        line_number: int | None = None,
    ) -> FileComment:
        """添加评论。

        Args:
            file_path: 文件路径。
            user: 用户。
            content: 评论内容。
            line_number: 行号。

        Returns:
            评论对象。
        """
        comment_id = f"{file_path}_{user}_{datetime.now(UTC).isoformat()}".replace("/", "_").replace(":", "-")
        comment = FileComment(
            comment_id=comment_id,
            file_path=file_path,
            user=user,
            content=content,
            line_number=line_number,
        )

        # 存储评论
        comments = self.get_comments(file_path)
        comments.append(comment)
        self._save_comments(file_path, comments)
        self._comments[comment_id] = comment

        return comment

    def get_comments(self, file_path: str, resolved: bool | None = None) -> list[FileComment]:
        """获取文件的评论。

        Args:
            file_path: 文件路径。
            resolved: 是否已解决（None 表示全部）。

        Returns:
            评论列表。
        """
        comments_path = self._get_comments_path(file_path)
        try:
            content = self.backend.read(comments_path, offset=0, limit=100000)
            if not content.startswith("Error:"):
                comments_data = json.loads(content)
                comments = [FileComment(**c) for c in comments_data]
                if resolved is not None:
                    comments = [c for c in comments if c.resolved == resolved]
                return comments
        except Exception:
            pass

        return []

    def resolve_comment(self, comment_id: str) -> bool:
        """解决评论。

        Args:
            comment_id: 评论 ID。

        Returns:
            是否成功解决。
        """
        if comment_id not in self._comments:
            return False

        comment = self._comments[comment_id]
        comment.resolved = True

        comments = self.get_comments(comment.file_path)
        for c in comments:
            if c.comment_id == comment_id:
                c.resolved = True
                break

        self._save_comments(comment.file_path, comments)
        return True

    def _save_comments(self, file_path: str, comments: list[FileComment]) -> None:
        """保存评论。"""
        comments_path = self._get_comments_path(file_path)
        comments_data = [
            {
                "comment_id": c.comment_id,
                "file_path": c.file_path,
                "user": c.user,
                "content": c.content,
                "created_at": c.created_at,
                "line_number": c.line_number,
                "resolved": c.resolved,
            }
            for c in comments
        ]
        self.backend.write(comments_path, json.dumps(comments_data, indent=2))


class ConflictResolver:
    """冲突解决器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化冲突解决器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._conflicts: dict[str, FileConflict] = {}

    def detect_conflict(self, file_path: str, user1: str, version1: str, user2: str, version2: str) -> FileConflict:
        """检测冲突。

        Args:
            file_path: 文件路径。
            user1: 用户1。
            version1: 版本1。
            user2: 用户2。
            version2: 版本2。

        Returns:
            冲突对象。
        """
        conflict_id = f"{file_path}_{datetime.now(UTC).isoformat()}".replace("/", "_").replace(":", "-")
        conflict = FileConflict(
            conflict_id=conflict_id,
            file_path=file_path,
            user1=user1,
            user2=user2,
            version1=version1,
            version2=version2,
        )

        self._conflicts[conflict_id] = conflict
        return conflict

    def resolve_conflict(
        self,
        conflict_id: str,
        resolution: Literal["keep_version1", "keep_version2", "merge"],
        merged_content: str | None = None,
    ) -> bool:
        """解决冲突。

        Args:
            conflict_id: 冲突 ID。
            resolution: 解决方案。
            merged_content: 合并后的内容（如果 resolution 是 merge）。

        Returns:
            是否成功解决。
        """
        if conflict_id not in self._conflicts:
            return False

        conflict = self._conflicts[conflict_id]

        if resolution == "keep_version1":
            content = conflict.version1
        elif resolution == "keep_version2":
            content = conflict.version2
        elif resolution == "merge" and merged_content:
            content = merged_content
        else:
            return False

        result = self.backend.write(conflict.file_path, content)
        if result.error is None:
            del self._conflicts[conflict_id]
            return True

        return False

    def get_conflicts(self, file_path: str | None = None) -> list[FileConflict]:
        """获取冲突列表。

        Args:
            file_path: 过滤文件路径。

        Returns:
            冲突列表。
        """
        conflicts = list(self._conflicts.values())
        if file_path:
            conflicts = [c for c in conflicts if c.file_path == file_path]
        return conflicts

