"""Backend system for WebWeaver.

Provides pluggable backends for file storage and execution.
"""

from __future__ import annotations

from webweaver.backends.automation import (
    AutoCleanupManager,
    BackupManager,
    CleanupPolicy,
    LifecycleManager,
    MigrationManager,
    NotificationManager,
)
from webweaver.backends.collaboration import (
    CommentManager,
    ConflictResolver,
    FileComment,
    FileConflict,
    FileShare,
    FileSharingManager,
)
from webweaver.backends.composite import CompositeBackend
from webweaver.backends.extended_protocol import (
    AuditBackendProtocol,
    AsyncBackendProtocol,
    CompressionBackendProtocol,
    LockBackendProtocol,
    MetadataBackendProtocol,
    MetricsBackendProtocol,
    PermissionBackendProtocol,
    QuotaBackendProtocol,
    SnapshotBackendProtocol,
    VersionControlBackendProtocol,
)
from webweaver.backends.file_management import (
    FileLockManager,
    FileMetadataManager,
    FilePermissionManager,
    FileSnapshotManager,
    FileVersionManager,
)
from webweaver.backends.filesystem import FilesystemBackend
from webweaver.backends.memory_cache import LRUCache, MemoryCacheBackend, TTLCache
from webweaver.backends.monitoring import (
    ErrorReport,
    ErrorTracker,
    HealthChecker,
    HealthStatus,
    MonitoringBackend,
    PerformanceAnalyzer,
    PerformanceStats,
    StorageAnalyzer,
    StorageStats,
)
from webweaver.backends.performance import (
    BatchOperationsBackend,
    CachedBackend,
    CompressionBackend,
    PerformanceMonitor,
)
from webweaver.backends.protocol import BackendProtocol, SandboxBackendProtocol
from webweaver.backends.search_index import (
    ContentIndexer,
    DependencyTracker,
    SearchResult,
    SmartRecommendationEngine,
    TagManager,
)
from webweaver.backends.security import (
    AuditLogger,
    IntegrityChecker,
    QuotaManager,
    RateLimiter,
)
from webweaver.backends.async_base import (
    AsyncBackendMixin,
    AsyncFilesystemBackend,
    AsyncMemoryCacheBackend,
    AsyncStateBackend,
)
from webweaver.backends.cloud_storage import (
    AzureBlobBackend,
    GoogleCloudStorageBackend,
    S3Backend,
)
from webweaver.backends.encryption import EncryptionBackend
from webweaver.backends.search_integration import (
    ElasticsearchBackend,
    MeilisearchBackend,
)
from webweaver.backends.state import StateBackend
from webweaver.backends.store import StoreBackend

__all__ = [
    # Core backends
    "BackendProtocol",
    "SandboxBackendProtocol",
    "FilesystemBackend",
    "StateBackend",
    "CompositeBackend",
    "StoreBackend",
    "MemoryCacheBackend",
    # Extended protocols
    "AsyncBackendProtocol",
    "MetadataBackendProtocol",
    "VersionControlBackendProtocol",
    "PermissionBackendProtocol",
    "LockBackendProtocol",
    "SnapshotBackendProtocol",
    "AuditBackendProtocol",
    "MetricsBackendProtocol",
    "CompressionBackendProtocol",
    "QuotaBackendProtocol",
    # File management
    "FileVersionManager",
    "FileMetadataManager",
    "FilePermissionManager",
    "FileLockManager",
    "FileSnapshotManager",
    # Performance
    "PerformanceMonitor",
    "CachedBackend",
    "BatchOperationsBackend",
    "CompressionBackend",
    "LRUCache",
    "TTLCache",
    # Security
    "AuditLogger",
    "IntegrityChecker",
    "QuotaManager",
    "RateLimiter",
    # Monitoring
    "HealthChecker",
    "HealthStatus",
    "PerformanceAnalyzer",
    "PerformanceStats",
    "StorageAnalyzer",
    "StorageStats",
    "ErrorTracker",
    "ErrorReport",
    "MonitoringBackend",
    # Search and indexing
    "ContentIndexer",
    "SearchResult",
    "DependencyTracker",
    "TagManager",
    "SmartRecommendationEngine",
    # Automation
    "CleanupPolicy",
    "AutoCleanupManager",
    "BackupManager",
    "MigrationManager",
    "NotificationManager",
    "LifecycleManager",
    # Collaboration
    "FileSharingManager",
    "FileShare",
    "CommentManager",
    "FileComment",
    "ConflictResolver",
    "FileConflict",
    # Async backends
    "AsyncBackendMixin",
    "AsyncFilesystemBackend",
    "AsyncStateBackend",
    "AsyncMemoryCacheBackend",
    # Cloud storage
    "S3Backend",
    "AzureBlobBackend",
    "GoogleCloudStorageBackend",
    # Search integration
    "ElasticsearchBackend",
    "MeilisearchBackend",
    # Encryption
    "EncryptionBackend",
]

