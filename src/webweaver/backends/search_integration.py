"""Search integration: Elasticsearch, Meilisearch."""

from __future__ import annotations

from typing import Any

from webweaver.backends.protocol import BackendProtocol
from webweaver.backends.search_index import ContentIndexer, SearchResult
from webweaver.logging import get_logger

logger = get_logger(__name__)


class ElasticsearchBackend(BackendProtocol):
    """Elasticsearch 全文搜索后端。"""

    def __init__(
        self,
        backend: BackendProtocol,
        elasticsearch_url: str = "http://localhost:9200",
        index_name: str = "webweaver_files",
    ):
        """初始化 Elasticsearch 后端。

        Args:
            backend: 底层后端。
            elasticsearch_url: Elasticsearch URL。
            index_name: 索引名称。
        """
        try:
            from elasticsearch import Elasticsearch

            self.Elasticsearch = Elasticsearch
        except ImportError:
            raise ImportError(
                "elasticsearch is required for ElasticsearchBackend. Install it with: pip install elasticsearch"
            )

        self.backend = backend
        self.client = self.Elasticsearch([elasticsearch_url])
        self.index_name = index_name
        self._ensure_index()

    def _ensure_index(self) -> None:
        """确保索引存在。"""
        try:
            if not self.client.indices.exists(index=self.index_name):
                self.client.indices.create(
                    index=self.index_name,
                    body={
                        "mappings": {
                            "properties": {
                                "path": {"type": "keyword"},
                                "content": {"type": "text"},
                                "modified_at": {"type": "date"},
                            }
                        }
                    },
                )
        except Exception as e:
            logger.warning("Failed to create Elasticsearch index", extra={"error": str(e)})

    def index_file(self, path: str) -> bool:
        """索引文件。

        Args:
            path: 文件路径。

        Returns:
            是否成功索引。
        """
        try:
            content = self.backend.read(path, offset=0, limit=1000000)
            if content.startswith("Error:"):
                return False

            self.client.index(
                index=self.index_name,
                id=path,
                body={
                    "path": path,
                    "content": content,
                },
            )
            return True
        except Exception as e:
            logger.exception("Failed to index file in Elasticsearch", extra={"path": path})
            return False

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """搜索文件。

        Args:
            query: 搜索查询。
            limit: 结果数量限制。

        Returns:
            搜索结果列表。
        """
        try:
            response = self.client.search(
                index=self.index_name,
                body={
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["content", "path"],
                        }
                    },
                    "size": limit,
                },
            )

            results: list[SearchResult] = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                results.append(
                    SearchResult(
                        path=source["path"],
                        score=hit["_score"],
                        snippet=source["content"][:200] + "..." if len(source["content"]) > 200 else source["content"],
                    )
                )

            return results
        except Exception as e:
            logger.exception("Failed to search in Elasticsearch", extra={"query": query})
            return []

    # 实现必需的协议方法（委托给底层后端）
    def ls_info(self, path: str) -> list[Any]:
        """列出文件和目录。"""
        return self.backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        return self.backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> Any:
        """写入文件。"""
        result = self.backend.write(file_path, content)
        if result.error is None:
            self.index_file(file_path)
        return result

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Any:
        """编辑文件。"""
        result = self.backend.edit(file_path, old_string, new_string, replace_all)
        if result.error is None:
            self.index_file(file_path)
        return result

    def glob_info(self, pattern: str, path: str = "/") -> list[Any]:
        """查找匹配的文件。"""
        return self.backend.glob_info(pattern, path)

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        """搜索文本模式。"""
        return self.backend.grep_raw(pattern, path, glob)


class MeilisearchBackend(BackendProtocol):
    """Meilisearch 全文搜索后端。"""

    def __init__(
        self,
        backend: BackendProtocol,
        meilisearch_url: str = "http://localhost:7700",
        api_key: str | None = None,
        index_name: str = "webweaver_files",
    ):
        """初始化 Meilisearch 后端。

        Args:
            backend: 底层后端。
            meilisearch_url: Meilisearch URL。
            api_key: API 密钥。
            index_name: 索引名称。
        """
        try:
            from meilisearch import Client

            self.Client = Client
        except ImportError:
            raise ImportError(
                "meilisearch is required for MeilisearchBackend. Install it with: pip install meilisearch"
            )

        self.backend = backend
        self.client = self.Client(meilisearch_url, api_key)
        self.index_name = index_name
        self.index = self.client.index(index_name)
        self._ensure_index()

    def _ensure_index(self) -> None:
        """确保索引存在并配置。"""
        try:
            # Meilisearch 会自动创建索引
            # 配置搜索属性
            self.index.update_searchable_attributes(["content", "path"])
        except Exception as e:
            logger.warning("Failed to configure Meilisearch index", extra={"error": str(e)})

    def index_file(self, path: str) -> bool:
        """索引文件。

        Args:
            path: 文件路径。

        Returns:
            是否成功索引。
        """
        try:
            content = self.backend.read(path, offset=0, limit=1000000)
            if content.startswith("Error:"):
                return False

            self.index.add_documents(
                [
                    {
                        "id": path,
                        "path": path,
                        "content": content,
                    }
                ],
                primary_key="id",
            )
            return True
        except Exception as e:
            logger.exception("Failed to index file in Meilisearch", extra={"path": path})
            return False

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """搜索文件。

        Args:
            query: 搜索查询。
            limit: 结果数量限制。

        Returns:
            搜索结果列表。
        """
        try:
            response = self.index.search(query, {"limit": limit})

            results: list[SearchResult] = []
            for hit in response["hits"]:
                results.append(
                    SearchResult(
                        path=hit["path"],
                        score=hit.get("_rankingScore", 0.0),
                        snippet=hit["content"][:200] + "..." if len(hit["content"]) > 200 else hit["content"],
                    )
                )

            return results
        except Exception as e:
            logger.exception("Failed to search in Meilisearch", extra={"query": query})
            return []

    # 实现必需的协议方法（委托给底层后端）
    def ls_info(self, path: str) -> list[Any]:
        """列出文件和目录。"""
        return self.backend.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件内容。"""
        return self.backend.read(file_path, offset, limit)

    def write(self, file_path: str, content: str) -> Any:
        """写入文件。"""
        result = self.backend.write(file_path, content)
        if result.error is None:
            self.index_file(file_path)
        return result

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Any:
        """编辑文件。"""
        result = self.backend.edit(file_path, old_string, new_string, replace_all)
        if result.error is None:
            self.index_file(file_path)
        return result

    def glob_info(self, pattern: str, path: str = "/") -> list[Any]:
        """查找匹配的文件。"""
        return self.backend.glob_info(pattern, path)

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        """搜索文本模式。"""
        return self.backend.grep_raw(pattern, path, glob)

