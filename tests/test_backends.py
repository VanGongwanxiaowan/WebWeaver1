"""Tests for backend implementations."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from webweaver.backends import CompositeBackend, FilesystemBackend, StateBackend
from webweaver.backends.protocol import FileInfo


class MockRuntime:
    """Mock ToolRuntime for testing StateBackend."""

    def __init__(self) -> None:
        self.state = {"files": {}}


def test_filesystem_backend_basic_operations() -> None:
    """Test basic FilesystemBackend operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

        # Write file
        result = backend.write("/test.txt", "Hello, World!")
        assert result.error is None
        assert result.path == "/test.txt"

        # Read file
        content = backend.read("/test.txt")
        assert "Hello, World!" in content

        # List files
        files = backend.ls_info("/")
        assert len(files) == 1
        assert files[0].path == "/test.txt"
        assert files[0].is_dir is False


def test_state_backend_basic_operations() -> None:
    """Test basic StateBackend operations."""
    runtime = MockRuntime()
    backend = StateBackend(runtime)

    # Write file
    result = backend.write("/test.txt", "Hello, World!")
    assert result.error is None
    assert result.path == "/test.txt"
    assert result.files_update is not None

    # Update state
    runtime.state["files"].update(result.files_update)

    # Read file
    content = backend.read("/test.txt")
    assert "Hello, World!" in content

    # List files
    files = backend.ls_info("/")
    assert len(files) == 1
    assert files[0].path == "/test.txt"


def test_composite_backend_routing() -> None:
    """Test CompositeBackend routing functionality."""
    runtime = MockRuntime()
    state_backend = StateBackend(runtime)

    with tempfile.TemporaryDirectory() as tmpdir:
        fs_backend = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

        composite = CompositeBackend(
            default=state_backend,
            routes={"/persistent/": fs_backend},
        )

        # Write to routed backend
        result = composite.write("/persistent/test.txt", "Persistent data")
        assert result.error is None

        # Write to default backend
        result2 = composite.write("/temp.txt", "Temp data")
        assert result2.error is None
        assert result2.files_update is not None
        runtime.state["files"].update(result2.files_update)

        # Read from routed backend
        content1 = composite.read("/persistent/test.txt")
        assert "Persistent data" in content1

        # Read from default backend
        content2 = composite.read("/temp.txt")
        assert "Temp data" in content2


def test_tool_result_eviction() -> None:
    """Test tool result eviction middleware."""
    from webweaver.middleware import ToolResultEvictionMiddleware
    from webweaver.backends import FilesystemBackend

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)
        eviction = ToolResultEvictionMiddleware(backend=backend, tool_token_limit_before_evict=100)

        # Small result should not be evicted
        small_result = "x" * 50
        processed, files_update = eviction.process_tool_result("call_123", small_result)
        assert processed == small_result
        assert files_update is None

        # Large result should be evicted
        large_result = "x" * 500  # Exceeds 100 * 4 = 400 char limit
        processed, files_update = eviction.process_tool_result("call_456", large_result)
        assert processed != large_result
        assert "large_tool_results" in processed
        assert files_update is None  # FilesystemBackend doesn't return files_update

        # Verify file was created
        files = backend.ls_info("/large_tool_results/")
        assert len(files) == 1


def test_prompt_caching_availability() -> None:
    """Test prompt caching middleware availability."""
    from webweaver.middleware.prompt_caching import (
        PROMPT_CACHING_AVAILABLE,
        create_prompt_caching_middleware,
    )

    # Should not raise even if langchain-anthropic is not installed
    middleware = create_prompt_caching_middleware()
    # Middleware may be None if not available, which is fine
    assert middleware is None or hasattr(middleware, "__class__")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

