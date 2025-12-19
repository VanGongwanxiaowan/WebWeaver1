"""Concurrency control utilities for async operations."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from webweaver.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class ConcurrencyLimiter:
    """Concurrency limiter with priority support."""

    max_concurrent: int
    _semaphore: asyncio.Semaphore = field(init=False)
    _queue: deque[tuple[float, asyncio.Future]] = field(default_factory=deque)
    _running: int = field(default=0)

    def __post_init__(self):
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def acquire(self, priority: float = 0.0) -> None:
        """Acquire a slot, optionally with priority.

        Args:
            priority: Higher priority values are processed first.
        """
        await self._semaphore.acquire()
        self._running += 1

    def release(self) -> None:
        """Release a slot."""
        self._semaphore.release()
        self._running -= 1

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()

    @property
    def running(self) -> int:
        """Get number of running tasks."""
        return self._running

    @property
    def available(self) -> int:
        """Get number of available slots."""
        return self._semaphore._value


class TaskPool:
    """Task pool for managing concurrent async tasks."""

    def __init__(self, max_concurrent: int = 10):
        """Initialize task pool.

        Args:
            max_concurrent: Maximum concurrent tasks.
        """
        self._limiter = ConcurrencyLimiter(max_concurrent)
        self._tasks: set[asyncio.Task] = set()

    async def submit(self, coro: Callable[..., Any], *args, **kwargs) -> asyncio.Task:
        """Submit a task to the pool.

        Args:
            coro: Coroutine function.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Task object.
        """
        async def _wrapped():
            async with self._limiter:
                return await coro(*args, **kwargs)

        task = asyncio.create_task(_wrapped())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def gather(self, *coros: Callable[..., Any], return_exceptions: bool = False) -> list[Any]:
        """Submit multiple tasks and wait for all to complete.

        Args:
            *coros: Coroutine functions.
            return_exceptions: Whether to return exceptions instead of raising.

        Returns:
            List of results.
        """
        tasks = [self.submit(coro) for coro in coros]
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)

    async def wait_all(self) -> None:
        """Wait for all tasks to complete."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def cancel_all(self) -> None:
        """Cancel all pending tasks."""
        for task in self._tasks:
            if not task.done():
                task.cancel()

    @property
    def active_count(self) -> int:
        """Get number of active tasks."""
        return len([t for t in self._tasks if not t.done()])


class RateLimiter:
    """Rate limiter using token bucket algorithm."""

    def __init__(self, rate: float, burst: int = 1):
        """Initialize rate limiter.

        Args:
            rate: Requests per second.
            burst: Maximum burst size.
        """
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int = 1) -> None:
        """Acquire n tokens, waiting if necessary."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < n:
                wait_time = (n - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= n


class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] = Exception,
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit.
            recovery_timeout: Time to wait before attempting recovery.
            expected_exception: Exception type to catch.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = "closed"  # closed, open, half_open
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Call a function with circuit breaker protection.

        Args:
            func: Function to call.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            CircuitBreakerOpenError: If circuit is open.
        """
        async with self._lock:
            if self.state == "open":
                if self.last_failure_time:
                    elapsed = asyncio.get_event_loop().time() - self.last_failure_time
                    if elapsed >= self.recovery_timeout:
                        self.state = "half_open"
                        logger.info("Circuit breaker transitioning to half-open")
                    else:
                        raise CircuitBreakerOpenError(
                            f"Circuit breaker is open. Retry after {self.recovery_timeout - elapsed:.1f}s"
                        )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            async with self._lock:
                if self.state == "half_open":
                    self.state = "closed"
                    self.failure_count = 0
                    logger.info("Circuit breaker closed after successful call")

            return result

        except self.expected_exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = asyncio.get_event_loop().time()

                if self.failure_count >= self.failure_threshold:
                    self.state = "open"
                    logger.warning(
                        "Circuit breaker opened",
                        extra={
                            "failure_count": self.failure_count,
                            "threshold": self.failure_threshold,
                        },
                    )

            raise


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass

