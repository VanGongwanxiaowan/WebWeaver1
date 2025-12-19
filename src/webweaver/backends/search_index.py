"""Search and indexing: full-text search, content indexing, smart recommendations, dependency tracking, tagging."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from webweaver.backends.protocol import BackendProtocol


@dataclass
class SearchResult:
    """搜索结果。"""

    path: str
    score: float
    snippet: str | None = None
    highlights: list[str] | None = None


class ContentIndexer:
    """内容索引器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化内容索引器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._index: dict[str, dict[str, Any]] = {}

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

            # 提取关键词（简化实现）
            words = re.findall(r"\b\w+\b", content.lower())
            word_freq: dict[str, int] = defaultdict(int)
            for word in words:
                if len(word) > 2:  # 忽略短词
                    word_freq[word] += 1

            self._index[path] = {
                "path": path,
                "word_freq": dict(word_freq),
                "content_length": len(content),
                "word_count": len(words),
            }
            return True
        except Exception:
            return False

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """搜索文件。

        Args:
            query: 搜索查询。
            limit: 结果数量限制。

        Returns:
            搜索结果列表。
        """
        query_words = set(re.findall(r"\b\w+\b", query.lower()))
        results: list[tuple[str, float]] = []

        for path, index_data in self._index.items():
            score = 0.0
            word_freq = index_data.get("word_freq", {})
            for word in query_words:
                if word in word_freq:
                    score += word_freq[word]

            if score > 0:
                results.append((path, score))

        # 按分数排序
        results.sort(key=lambda x: x[1], reverse=True)

        # 转换为 SearchResult
        search_results: list[SearchResult] = []
        for path, score in results[:limit]:
            content = self.backend.read(path, offset=0, limit=500)
            snippet = content[:200] + "..." if len(content) > 200 else content
            search_results.append(
                SearchResult(
                    path=path,
                    score=score,
                    snippet=snippet,
                )
            )

        return search_results


class DependencyTracker:
    """依赖关系追踪器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化依赖追踪器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._dependencies: dict[str, list[str]] = {}
        self._dependents: dict[str, list[str]] = {}

    def track_dependency(self, file_path: str, dependency_path: str) -> None:
        """追踪依赖关系。

        Args:
            file_path: 文件路径。
            dependency_path: 依赖的文件路径。
        """
        if file_path not in self._dependencies:
            self._dependencies[file_path] = []
        if dependency_path not in self._dependencies[file_path]:
            self._dependencies[file_path].append(dependency_path)

        if dependency_path not in self._dependents:
            self._dependents[dependency_path] = []
        if file_path not in self._dependents[dependency_path]:
            self._dependents[dependency_path].append(file_path)

    def get_dependencies(self, file_path: str) -> list[str]:
        """获取文件的依赖。

        Args:
            file_path: 文件路径。

        Returns:
            依赖文件路径列表。
        """
        return self._dependencies.get(file_path, [])

    def get_dependents(self, file_path: str) -> list[str]:
        """获取依赖此文件的文件。

        Args:
            file_path: 文件路径。

        Returns:
            依赖此文件的文件路径列表。
        """
        return self._dependents.get(file_path, [])

    def analyze_imports(self, file_path: str) -> list[str]:
        """分析文件中的导入语句（简化实现）。

        Args:
            file_path: 文件路径。

        Returns:
            导入的文件路径列表。
        """
        try:
            content = self.backend.read(file_path, offset=0, limit=10000)
            imports: list[str] = []

            # 匹配 Python import 语句
            import_pattern = r"^(?:from\s+(\S+)\s+)?import\s+(\S+)"
            for line in content.split("\n"):
                match = re.match(import_pattern, line.strip())
                if match:
                    module = match.group(1) or match.group(2)
                    if module:
                        imports.append(module)

            return imports
        except Exception:
            return []


class TagManager:
    """标签管理器。"""

    def __init__(self, backend: BackendProtocol):
        """初始化标签管理器。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._file_tags: dict[str, list[str]] = {}
        self._tag_files: dict[str, list[str]] = defaultdict(list)

    def add_tag(self, file_path: str, tag: str) -> bool:
        """添加标签。

        Args:
            file_path: 文件路径。
            tag: 标签。

        Returns:
            是否成功添加。
        """
        if file_path not in self._file_tags:
            self._file_tags[file_path] = []
        if tag not in self._file_tags[file_path]:
            self._file_tags[file_path].append(tag)
            self._tag_files[tag].append(file_path)
            return True
        return False

    def remove_tag(self, file_path: str, tag: str) -> bool:
        """移除标签。

        Args:
            file_path: 文件路径。
            tag: 标签。

        Returns:
            是否成功移除。
        """
        if file_path in self._file_tags and tag in self._file_tags[file_path]:
            self._file_tags[file_path].remove(tag)
            if tag in self._tag_files and file_path in self._tag_files[tag]:
                self._tag_files[tag].remove(file_path)
            return True
        return False

    def get_tags(self, file_path: str) -> list[str]:
        """获取文件的标签。

        Args:
            file_path: 文件路径。

        Returns:
            标签列表。
        """
        return self._file_tags.get(file_path, [])

    def get_files_by_tag(self, tag: str) -> list[str]:
        """根据标签获取文件。

        Args:
            tag: 标签。

        Returns:
            文件路径列表。
        """
        return self._tag_files.get(tag, [])

    def search_by_tags(self, tags: list[str]) -> list[str]:
        """根据多个标签搜索文件。

        Args:
            tags: 标签列表。

        Returns:
            包含所有标签的文件路径列表。
        """
        if not tags:
            return []

        matching_files: set[str] | None = None
        for tag in tags:
            files_with_tag = set(self.get_files_by_tag(tag))
            if matching_files is None:
                matching_files = files_with_tag
            else:
                matching_files &= files_with_tag

        return list(matching_files) if matching_files else []


class SmartRecommendationEngine:
    """智能推荐引擎。"""

    def __init__(self, backend: BackendProtocol):
        """初始化推荐引擎。

        Args:
            backend: 底层后端。
        """
        self.backend = backend
        self._access_patterns: dict[str, list[str]] = defaultdict(list)
        self._file_similarity: dict[tuple[str, str], float] = {}

    def record_access(self, user_id: str, file_path: str) -> None:
        """记录文件访问。

        Args:
            user_id: 用户标识。
            file_path: 文件路径。
        """
        self._access_patterns[user_id].append(file_path)

    def recommend_files(self, file_path: str, limit: int = 5) -> list[str]:
        """推荐相关文件。

        Args:
            file_path: 参考文件路径。
            limit: 推荐数量限制。

        Returns:
            推荐的文件路径列表。
        """
        # 简化实现：基于访问模式推荐
        recommendations: dict[str, int] = defaultdict(int)

        # 查找访问过此文件的其他用户
        for user_id, accessed_files in self._access_patterns.items():
            if file_path in accessed_files:
                # 推荐这些用户访问的其他文件
                for other_file in accessed_files:
                    if other_file != file_path:
                        recommendations[other_file] += 1

        # 按推荐分数排序
        sorted_recommendations = sorted(recommendations.items(), key=lambda x: x[1], reverse=True)
        return [path for path, _ in sorted_recommendations[:limit]]

