"""Cloud storage backends: S3, Azure Blob, Google Cloud Storage."""

from __future__ import annotations

import json
from typing import Any, Literal

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


class S3Backend(AsyncBackendMixin, BackendProtocol):
    """AWS S3 存储后端。"""

    def __init__(
        self,
        bucket_name: str,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str = "us-east-1",
        prefix: str = "",
    ):
        """初始化 S3 后端。

        Args:
            bucket_name: S3 存储桶名称。
            aws_access_key_id: AWS 访问密钥 ID。
            aws_secret_access_key: AWS 密钥。
            region_name: AWS 区域。
            prefix: 路径前缀。
        """
        try:
            import boto3

            self.boto3 = boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3Backend. Install it with: pip install boto3"
            )

        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip("/")
        self.s3_client = self.boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

    def _get_key(self, path: str) -> str:
        """获取 S3 键。"""
        clean_path = path.lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{clean_path}"
        return clean_path

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        try:
            prefix = self._get_key(path).rstrip("/") + "/"
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix, Delimiter="/")

            infos: list[FileInfo] = []

            # 处理目录
            for prefix_obj in response.get("CommonPrefixes", []):
                dir_path = "/" + prefix_obj["Prefix"][len(self.prefix + "/") :] if self.prefix else prefix_obj["Prefix"]
                infos.append(FileInfo(path=dir_path, is_dir=True))

            # 处理文件
            for obj in response.get("Contents", []):
                file_path = "/" + obj["Key"][len(self.prefix + "/") :] if self.prefix else "/" + obj["Key"]
                infos.append(
                    FileInfo(
                        path=file_path,
                        is_dir=False,
                        size=obj.get("Size", 0),
                        modified_at=obj.get("LastModified", "").isoformat() if obj.get("LastModified") else None,
                    )
                )

            return infos
        except Exception as e:
            logger.exception("Failed to list S3 objects", extra={"path": path})
            return []

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        try:
            key = self._get_key(file_path)
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response["Body"].read().decode("utf-8")

            lines = content.splitlines()
            start_idx = offset
            end_idx = min(start_idx + limit, len(lines))

            if start_idx >= len(lines):
                return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

            selected_lines = lines[start_idx:end_idx]
            formatted = "\n".join(f"{i + start_idx + 1:6d}\t{line}" for i, line in enumerate(selected_lines))
            return formatted
        except Exception as e:
            logger.exception("Failed to read from S3", extra={"path": file_path})
            return f"Error reading file '{file_path}': {e}"

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入文件。"""
        try:
            key = self._get_key(file_path)
            # 检查文件是否存在
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
                return WriteResult(
                    error=f"Cannot write to {file_path} because it already exists. Read and then make an edit, or write to a new path."
                )
            except self.s3_client.exceptions.ClientError:
                pass  # 文件不存在，可以写入

            self.s3_client.put_object(Bucket=self.bucket_name, Key=key, Body=content.encode("utf-8"))
            return WriteResult(path=file_path)
        except Exception as e:
            logger.exception("Failed to write to S3", extra={"path": file_path})
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件。"""
        try:
            key = self._get_key(file_path)
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response["Body"].read().decode("utf-8")

            if replace_all:
                occurrences = content.count(old_string)
                new_content = content.replace(old_string, new_string)
            else:
                if content.count(old_string) != 1:
                    return EditResult(
                        error=f"String not unique in file. Found {content.count(old_string)} occurrences. Use replace_all=True to replace all."
                    )
                occurrences = 1
                new_content = content.replace(old_string, new_string, 1)

            self.s3_client.put_object(Bucket=self.bucket_name, Key=key, Body=new_content.encode("utf-8"))
            return EditResult(path=file_path, occurrences=occurrences)
        except Exception as e:
            logger.exception("Failed to edit S3 object", extra={"path": file_path})
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        # 简化实现
        all_files = self.ls_info(path)
        # 实际应该使用 glob 模式匹配
        return [f for f in all_files if not f.is_dir]

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式。"""
        # 简化实现
        files = self.ls_info(path or "/")
        matches: list[GrepMatch] = []
        for file_info in files:
            if file_info.is_dir:
                continue
            content = self.read(file_info.path, offset=0, limit=10000)
            if pattern in content:
                for line_num, line in enumerate(content.splitlines(), start=1):
                    if pattern in line:
                        matches.append(GrepMatch(path=file_info.path, line=line_num, text=line))
        return matches


class AzureBlobBackend(AsyncBackendMixin, BackendProtocol):
    """Azure Blob Storage 后端。"""

    def __init__(
        self,
        container_name: str,
        account_name: str,
        account_key: str | None = None,
        connection_string: str | None = None,
        prefix: str = "",
    ):
        """初始化 Azure Blob 后端。

        Args:
            container_name: 容器名称。
            account_name: 存储账户名称。
            account_key: 存储账户密钥。
            connection_string: 连接字符串。
            prefix: 路径前缀。
        """
        try:
            from azure.storage.blob import BlobServiceClient

            self.BlobServiceClient = BlobServiceClient
        except ImportError:
            raise ImportError(
                "azure-storage-blob is required for AzureBlobBackend. Install it with: pip install azure-storage-blob"
            )

        if connection_string:
            self.blob_service_client = self.BlobServiceClient.from_connection_string(connection_string)
        elif account_key:
            account_url = f"https://{account_name}.blob.core.windows.net"
            self.blob_service_client = self.BlobServiceClient(account_url, credential=account_key)
        else:
            raise ValueError("Either connection_string or account_key must be provided")

        self.container_name = container_name
        self.prefix = prefix.rstrip("/")
        self.container_client = self.blob_service_client.get_container_client(container_name)

    def _get_blob_name(self, path: str) -> str:
        """获取 Blob 名称。"""
        clean_path = path.lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{clean_path}"
        return clean_path

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        try:
            prefix = self._get_blob_name(path).rstrip("/") + "/"
            blobs = self.container_client.list_blobs(name_starts_with=prefix)

            infos: list[FileInfo] = []
            seen_dirs: set[str] = set()

            for blob in blobs:
                relative_path = blob.name[len(prefix) :] if prefix else blob.name
                if "/" in relative_path:
                    dir_name = relative_path.split("/")[0]
                    dir_path = f"/{dir_name}/"
                    if dir_path not in seen_dirs:
                        seen_dirs.add(dir_path)
                        infos.append(FileInfo(path=dir_path, is_dir=True))
                else:
                    file_path = "/" + relative_path
                    infos.append(
                        FileInfo(
                            path=file_path,
                            is_dir=False,
                            size=blob.size,
                            modified_at=blob.last_modified.isoformat() if blob.last_modified else None,
                        )
                    )

            return infos
        except Exception as e:
            logger.exception("Failed to list Azure Blob objects", extra={"path": path})
            return []

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        try:
            blob_name = self._get_blob_name(file_path)
            blob_client = self.container_client.get_blob_client(blob_name)
            content = blob_client.download_blob().readall().decode("utf-8")

            lines = content.splitlines()
            start_idx = offset
            end_idx = min(start_idx + limit, len(lines))

            if start_idx >= len(lines):
                return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

            selected_lines = lines[start_idx:end_idx]
            formatted = "\n".join(f"{i + start_idx + 1:6d}\t{line}" for i, line in enumerate(selected_lines))
            return formatted
        except Exception as e:
            logger.exception("Failed to read from Azure Blob", extra={"path": file_path})
            return f"Error reading file '{file_path}': {e}"

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入文件。"""
        try:
            blob_name = self._get_blob_name(file_path)
            blob_client = self.container_client.get_blob_client(blob_name)

            # 检查文件是否存在
            try:
                blob_client.get_blob_properties()
                return WriteResult(
                    error=f"Cannot write to {file_path} because it already exists. Read and then make an edit, or write to a new path."
                )
            except Exception:
                pass  # 文件不存在，可以写入

            blob_client.upload_blob(content.encode("utf-8"), overwrite=False)
            return WriteResult(path=file_path)
        except Exception as e:
            logger.exception("Failed to write to Azure Blob", extra={"path": file_path})
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件。"""
        try:
            blob_name = self._get_blob_name(file_path)
            blob_client = self.container_client.get_blob_client(blob_name)
            content = blob_client.download_blob().readall().decode("utf-8")

            if replace_all:
                occurrences = content.count(old_string)
                new_content = content.replace(old_string, new_string)
            else:
                if content.count(old_string) != 1:
                    return EditResult(
                        error=f"String not unique in file. Found {content.count(old_string)} occurrences. Use replace_all=True to replace all."
                    )
                occurrences = 1
                new_content = content.replace(old_string, new_string, 1)

            blob_client.upload_blob(new_content.encode("utf-8"), overwrite=True)
            return EditResult(path=file_path, occurrences=occurrences)
        except Exception as e:
            logger.exception("Failed to edit Azure Blob object", extra={"path": file_path})
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        all_files = self.ls_info(path)
        return [f for f in all_files if not f.is_dir]

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式。"""
        files = self.ls_info(path or "/")
        matches: list[GrepMatch] = []
        for file_info in files:
            if file_info.is_dir:
                continue
            content = self.read(file_info.path, offset=0, limit=10000)
            if pattern in content:
                for line_num, line in enumerate(content.splitlines(), start=1):
                    if pattern in line:
                        matches.append(GrepMatch(path=file_info.path, line=line_num, text=line))
        return matches


class GoogleCloudStorageBackend(AsyncBackendMixin, BackendProtocol):
    """Google Cloud Storage 后端。"""

    def __init__(
        self,
        bucket_name: str,
        credentials_path: str | None = None,
        project: str | None = None,
        prefix: str = "",
    ):
        """初始化 GCS 后端。

        Args:
            bucket_name: 存储桶名称。
            credentials_path: 凭证文件路径。
            project: GCP 项目 ID。
            prefix: 路径前缀。
        """
        try:
            from google.cloud import storage

            self.storage = storage
        except ImportError:
            raise ImportError(
                "google-cloud-storage is required for GoogleCloudStorageBackend. Install it with: pip install google-cloud-storage"
            )

        if credentials_path:
            self.client = self.storage.Client.from_service_account_json(credentials_path, project=project)
        else:
            self.client = self.storage.Client(project=project)

        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip("/")
        self.bucket = self.client.bucket(bucket_name)

    def _get_blob_name(self, path: str) -> str:
        """获取 Blob 名称。"""
        clean_path = path.lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{clean_path}"
        return clean_path

    def ls_info(self, path: str) -> list[FileInfo]:
        """列出文件和目录。"""
        try:
            prefix = self._get_blob_name(path).rstrip("/") + "/"
            blobs = self.bucket.list_blobs(prefix=prefix)

            infos: list[FileInfo] = []
            seen_dirs: set[str] = set()

            for blob in blobs:
                relative_path = blob.name[len(prefix) :] if prefix else blob.name
                if "/" in relative_path:
                    dir_name = relative_path.split("/")[0]
                    dir_path = f"/{dir_name}/"
                    if dir_path not in seen_dirs:
                        seen_dirs.add(dir_path)
                        infos.append(FileInfo(path=dir_path, is_dir=True))
                else:
                    file_path = "/" + relative_path
                    infos.append(
                        FileInfo(
                            path=file_path,
                            is_dir=False,
                            size=blob.size,
                            modified_at=blob.time_created.isoformat() if blob.time_created else None,
                        )
                    )

            return infos
        except Exception as e:
            logger.exception("Failed to list GCS objects", extra={"path": path})
            return []

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        try:
            blob_name = self._get_blob_name(file_path)
            blob = self.bucket.blob(blob_name)
            content = blob.download_as_text()

            lines = content.splitlines()
            start_idx = offset
            end_idx = min(start_idx + limit, len(lines))

            if start_idx >= len(lines):
                return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

            selected_lines = lines[start_idx:end_idx]
            formatted = "\n".join(f"{i + start_idx + 1:6d}\t{line}" for i, line in enumerate(selected_lines))
            return formatted
        except Exception as e:
            logger.exception("Failed to read from GCS", extra={"path": file_path})
            return f"Error reading file '{file_path}': {e}"

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入文件。"""
        try:
            blob_name = self._get_blob_name(file_path)
            blob = self.bucket.blob(blob_name)

            # 检查文件是否存在
            if blob.exists():
                return WriteResult(
                    error=f"Cannot write to {file_path} because it already exists. Read and then make an edit, or write to a new path."
                )

            blob.upload_from_string(content.encode("utf-8"))
            return WriteResult(path=file_path)
        except Exception as e:
            logger.exception("Failed to write to GCS", extra={"path": file_path})
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """编辑文件。"""
        try:
            blob_name = self._get_blob_name(file_path)
            blob = self.bucket.blob(blob_name)
            content = blob.download_as_text()

            if replace_all:
                occurrences = content.count(old_string)
                new_content = content.replace(old_string, new_string)
            else:
                if content.count(old_string) != 1:
                    return EditResult(
                        error=f"String not unique in file. Found {content.count(old_string)} occurrences. Use replace_all=True to replace all."
                    )
                occurrences = 1
                new_content = content.replace(old_string, new_string, 1)

            blob.upload_from_string(new_content.encode("utf-8"))
            return EditResult(path=file_path, occurrences=occurrences)
        except Exception as e:
            logger.exception("Failed to edit GCS object", extra={"path": file_path})
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """查找匹配的文件。"""
        all_files = self.ls_info(path)
        return [f for f in all_files if not f.is_dir]

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """搜索文本模式。"""
        files = self.ls_info(path or "/")
        matches: list[GrepMatch] = []
        for file_info in files:
            if file_info.is_dir:
                continue
            content = self.read(file_info.path, offset=0, limit=10000)
            if pattern in content:
                for line_num, line in enumerate(content.splitlines(), start=1):
                    if pattern in line:
                        matches.append(GrepMatch(path=file_info.path, line=line_num, text=line))
        return matches

