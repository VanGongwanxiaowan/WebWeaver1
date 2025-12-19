"""Redis-based event recorder.

This is optional and complements the file recorder. It enables multi-instance deployments where
events are accessible without reading local disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import redis

from webweaver.events import RunEvent


@dataclass
class RedisEventRecorder:
    """Append-only recorder storing events in a Redis list."""

    redis_url: str
    key_prefix: str
    run_id: str
    ttl_seconds: int = 60 * 60 * 24 * 7

    def __post_init__(self) -> None:
        self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        self._events_key = f"{self.key_prefix}:run:{self.run_id}:events"
        self._meta_key = f"{self.key_prefix}:run:{self.run_id}:meta"

    def append(self, event: RunEvent) -> None:
        """Append an event to Redis and refresh TTL."""

        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        pipe = self._client.pipeline()
        pipe.rpush(self._events_key, line)
        pipe.expire(self._events_key, self.ttl_seconds)
        pipe.execute()

    def set_meta(self, meta: dict[str, str]) -> None:
        """Store run metadata."""

        if not meta:
            return
        pipe = self._client.pipeline()
        pipe.hset(self._meta_key, mapping=meta)
        pipe.expire(self._meta_key, self.ttl_seconds)
        pipe.execute()

    def iter_events(self) -> list[RunEvent]:
        """Load all events from Redis."""

        lines = self._client.lrange(self._events_key, 0, -1)
        events: list[RunEvent] = []
        for line in lines:
            events.append(RunEvent.model_validate_json(line))
        return events
