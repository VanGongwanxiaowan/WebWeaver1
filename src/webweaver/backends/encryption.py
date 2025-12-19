"""File encryption: end-to-end encryption support."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from webweaver.backends.async_base import AsyncBackendMixin
from webweaver.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileInfo,
    GrepMatch,
    WriteResult,
)
from webweaver.logging import get_logger

logger = get_logger(__name__)


class EncryptionBackend(AsyncBackendMixin, BackendProtocol):
    """支持文件加密的后端包装器。"""

    def __init__(
        self,
        backend: BackendProtocol,
        password: str | None = None,
        key: bytes | None = None,
    ):
        """初始化加密后端。

        Args:
            backend: 底层后端。
            password: 加密密码（用于生成密钥）。
            key: 加密密钥（如果提供，将优先使用）。
        """
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            self.Fernet = Fernet
            self.PBKDF2HMAC = PBKDF2HMAC
            self.hashes = hashes
        except ImportError:
            raise ImportError(
                "cryptography is required for EncryptionBackend. Install it with: pip install cryptography"
            )

        self.backend = backend
        self._encrypted_files: set[str] = set()

        if key:
            self.cipher = self.Fernet(key)
        elif password:
            # 从密码生成密钥
            kdf = self.PBKDF2HMAC(
                algorithm=self.hashes.SHA256(),
                length=32,
                salt=b"webweaver_salt",  # 实际应用中应该使用随机 salt
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self.cipher = self.Fernet(key)
        else:
            # 生成随机密钥
            key = self.Fernet.generate_key()
            self.cipher = self.Fernet(key)
            logger.warning("No password or key provided, using randomly generated key")

    def _encrypt(self, content: str) -> str:
        """加密内容。

        Args:
            content: 原始内容。

        Returns:
            加密后的内容（base64 编码）。
        """
        encrypted = self.cipher.encrypt(content.encode())
        return base64.b64encode(encrypted).decode()

    def _decrypt(self, encrypted_content: str) -> str:
        """解密内容。

        Args:
            encrypted_content: 加密的内容（base64 编码）。

        Returns:
            解密后的内容。
        """
        encrypted_bytes = base64.b64decode(encrypted_content.encode())
        decrypted = self.cipher.decrypt(encrypted_bytes)
        return decrypted.decode()

    def _is_encrypted(self, content: str) -> bool:
        """检查内容是否已加密。

        Args:
            content: 内容。

        Returns:
            是否已加密。
        """
        # 简化实现：检查是否以特定前缀开头
        return content.startswith("ENCRYPTED:")

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        return self.backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容（自动解密）。"""
        content = self.backend.read(file_path, offset, limit)
        if content.startswith("Error:"):
            return content

        if file_path in self._encrypted_files or self._is_encrypted(content):
            try:
                # 移除加密标记
                if content.startswith("ENCRYPTED:"):
                    encrypted_content = content[len("ENCRYPTED:") :]
                else:
                    encrypted_content = content

                decrypted = self._decrypt(encrypted_content)
                # 重新应用分页
                lines = decrypted.splitlines()
                start_idx = offset
                end_idx = min(start_idx + limit, len(lines))
                if start_idx >= len(lines):
                    return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"
                selected_lines = lines[start_idx:end_idx]
                formatted = "\n".join(f"{i + start_idx + 1:6d}\t{line}" for i, line in enumerate(selected_lines))
                return formatted
            except Exception as e:
                logger.exception("Failed to decrypt file", extra={"path": file_path})
                return f"Error: Failed to decrypt file '{file_path}': {e}"
        return content

    def write(self, file_path: str, content: str, encrypt: bool = True) -> WriteResult:
        """写入文件（可选加密）。

        Args:
            file_path: 文件路径。
            content: 文件内容。
            encrypt: 是否加密。

        Returns:
            WriteResult。
        """
        if encrypt:
            encrypted_content = self._encrypt(content)
            result = self.backend.write(file_path, f"ENCRYPTED:{encrypted_content}")
            if result.error is None:
                self._encrypted_files.add(file_path)
            return result
        else:
            return self.backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件（自动处理加密）。"""
        # 读取并解密
        content = self.read(file_path, offset=0, limit=1000000)
        if content.startswith("Error:"):
            return EditResult(error=content)

        # 移除行号格式
        lines = content.splitlines()
        actual_content = "\n".join(line.split("\t", 1)[1] if "\t" in line else line for line in lines)

        # 执行替换
        if replace_all:
            occurrences = actual_content.count(old_string)
            new_content = actual_content.replace(old_string, new_string)
        else:
            if actual_content.count(old_string) != 1:
                return EditResult(
                    error=f"String not unique in file. Found {actual_content.count(old_string)} occurrences. Use replace_all=True to replace all."
                )
            occurrences = 1
            new_content = actual_content.replace(old_string, new_string, 1)

        # 重新加密并写入
        is_encrypted = file_path in self._encrypted_files
        write_result = self.write(file_path, new_content, encrypt=is_encrypted)
        if write_result.error:
            return EditResult(error=write_result.error)
        return EditResult(path=file_path, occurrences=occurrences)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        return self.backend.glob_info(pattern, path)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式（自动解密）。"""
        files = self.backend.ls_info(path or "/")
        matches: list[GrepMatch] = []
        for file_info in files:
            if file_info.is_dir:
                continue
            content = self.read(file_info.path, offset=0, limit=10000)
            if content.startswith("Error:"):
                continue
            # 移除行号格式
            lines = content.splitlines()
            for line_num, line in enumerate(lines, start=1):
                actual_line = line.split("\t", 1)[1] if "\t" in line else line
                if pattern in actual_line:
                    matches.append(GrepMatch(path=file_info.path, line=line_num, text=actual_line))
        return matches

    def encrypt_file(self, file_path: str) -> bool:
        """加密现有文件。

        Args:
            file_path: 文件路径。

        Returns:
            是否成功加密。
        """
        if file_path in self._encrypted_files:
            return True  # 已经加密

        content = self.backend.read(file_path, offset=0, limit=10000000)
        if content.startswith("Error:"):
            return False

        # 移除行号格式
        lines = content.splitlines()
        actual_content = "\n".join(line.split("\t", 1)[1] if "\t" in line else line for line in lines)

        encrypted_content = self._encrypt(actual_content)
        result = self.backend.write(file_path, f"ENCRYPTED:{encrypted_content}")
        if result.error is None:
            self._encrypted_files.add(file_path)
            return True
        return False

    def decrypt_file(self, file_path: str) -> bool:
        """解密现有文件。

        Args:
            file_path: 文件路径。

        Returns:
            是否成功解密。
        """
        if file_path not in self._encrypted_files:
            return True  # 未加密

        content = self.backend.read(file_path, offset=0, limit=10000000)
        if content.startswith("Error:"):
            return False

        try:
            if content.startswith("ENCRYPTED:"):
                encrypted_content = content[len("ENCRYPTED:") :]
                decrypted = self._decrypt(encrypted_content)
                result = self.backend.write(file_path, decrypted)
                if result.error is None:
                    self._encrypted_files.discard(file_path)
                    return True
        except Exception as e:
            logger.exception("Failed to decrypt file", extra={"path": file_path})
        return False

