"""Blackboard shared state storage for the Agentic BFF SDK.

Provides a thread-safe key-value store using asyncio.Lock,
allowing multiple agents to share intermediate results within a session.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional


class Blackboard:
    """线程安全的黑板共享状态存储。

    使用 asyncio.Lock 保证并发安全，供多个智能体在同一会话中
    读写中间结果。支持 TTL 过期清理机制。
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self._access_times: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """读取键值。

        Args:
            key: 要读取的键。

        Returns:
            键对应的值，若键不存在则返回 None。
        """
        async with self._lock:
            if key in self._store:
                self._access_times[key] = time.time()
                return self._store[key]
            return None

    async def set(self, key: str, value: Any) -> None:
        """写入键值。

        Args:
            key: 要写入的键。
            value: 要写入的值。
        """
        async with self._lock:
            self._store[key] = value
            self._access_times[key] = time.time()

    async def delete(self, key: str) -> bool:
        """删除键值。

        Args:
            key: 要删除的键。

        Returns:
            若键存在并被删除返回 True，否则返回 False。
        """
        async with self._lock:
            if key in self._store:
                del self._store[key]
                del self._access_times[key]
                return True
            return False

    async def cleanup_expired(self, ttl_seconds: int) -> List[str]:
        """清理过期键值。

        比较当前时间与每个键的最后访问时间，若差值超过 ttl_seconds
        则移除该键值。

        Args:
            ttl_seconds: 键值的存活时间（秒）。

        Returns:
            被清理的 key 列表。
        """
        async with self._lock:
            now = time.time()
            expired_keys: List[str] = []
            for key, access_time in list(self._access_times.items()):
                if now - access_time > ttl_seconds:
                    expired_keys.append(key)
            for key in expired_keys:
                del self._store[key]
                del self._access_times[key]
            return expired_keys
