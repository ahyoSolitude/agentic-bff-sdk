"""Request/task scoped shared state store."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod

from agentic_bff_sdk.models import BlackboardEntry


class Blackboard(ABC):
    @abstractmethod
    async def get(self, key: str) -> BlackboardEntry | None:
        ...

    @abstractmethod
    async def set(self, entry: BlackboardEntry) -> None:
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        ...

    @abstractmethod
    async def cleanup_expired(self) -> list[str]:
        ...


class InMemoryBlackboard(Blackboard):
    def __init__(self) -> None:
        self._store: dict[str, BlackboardEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> BlackboardEntry | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry and entry.expires_at is not None and entry.expires_at <= time.time():
                self._store.pop(key, None)
                return None
            return entry

    async def set(self, entry: BlackboardEntry) -> None:
        async with self._lock:
            self._store[entry.key] = entry

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._store.pop(key, None) is not None

    async def cleanup_expired(self) -> list[str]:
        async with self._lock:
            now = time.time()
            expired = [
                key for key, entry in self._store.items()
                if entry.expires_at is not None and entry.expires_at <= now
            ]
            for key in expired:
                self._store.pop(key, None)
            return expired
