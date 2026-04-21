"""Session context management for the Agentic BFF SDK.

Provides session lifecycle management including creation, persistence,
expiration cleanup, topic management, and dialog history compression.
Uses a pluggable StorageBackend for session state persistence.
"""

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agentic_bff_sdk.models import SessionState, Topic


# ============================================================
# Storage Backend Abstraction
# ============================================================


class StorageBackend(ABC):
    """会话状态存储后端抽象基类。

    定义了会话状态持久化的标准接口，支持自定义存储实现
    （如 Redis、数据库等）。
    """

    @abstractmethod
    async def save(self, session_id: str, state: SessionState) -> None:
        """持久化会话状态。

        Args:
            session_id: 会话标识。
            state: 要持久化的会话状态。
        """
        ...

    @abstractmethod
    async def load(self, session_id: str) -> Optional[SessionState]:
        """加载会话状态。

        Args:
            session_id: 会话标识。

        Returns:
            会话状态实例，若不存在则返回 None。
        """
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """删除会话状态。

        Args:
            session_id: 会话标识。
        """
        ...


class InMemoryStorageBackend(StorageBackend):
    """基于内存字典的默认存储后端。

    适用于开发和测试场景。生产环境建议使用 Redis 或数据库后端。
    """

    def __init__(self) -> None:
        self._store: Dict[str, SessionState] = {}

    async def save(self, session_id: str, state: SessionState) -> None:
        """持久化会话状态到内存。"""
        self._store[session_id] = state

    async def load(self, session_id: str) -> Optional[SessionState]:
        """从内存加载会话状态。"""
        return self._store.get(session_id)

    async def delete(self, session_id: str) -> None:
        """从内存删除会话状态。"""
        self._store.pop(session_id, None)

    def list_all(self) -> Dict[str, SessionState]:
        """返回所有存储的会话状态（用于清理等内部操作）。"""
        return dict(self._store)


# ============================================================
# Session Context
# ============================================================


class SessionContext:
    """会话上下文管理器。

    负责会话的创建、恢复、持久化、过期清理，以及话题管理
    和对话历史压缩。通过可插拔的 StorageBackend 实现持久化。
    """

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        max_dialog_history_turns: int = 50,
    ) -> None:
        """初始化 SessionContext。

        Args:
            storage: 存储后端实例，默认使用 InMemoryStorageBackend。
            max_dialog_history_turns: 对话历史最大轮次，超过时触发压缩。
        """
        self._storage = storage or InMemoryStorageBackend()
        self._max_dialog_history_turns = max_dialog_history_turns

    @property
    def storage(self) -> StorageBackend:
        """获取存储后端实例。"""
        return self._storage

    async def get_or_create(self, session_id: str) -> SessionState:
        """获取或创建会话状态。

        若存储后端中存在对应的会话状态则加载并返回，
        否则创建一个新的会话状态。

        Args:
            session_id: 会话标识。

        Returns:
            会话状态实例。
        """
        state = await self._storage.load(session_id)
        if state is not None:
            return state

        now = time.time()
        state = SessionState(
            session_id=session_id,
            dialog_history=[],
            user_profile_summary=None,
            active_topics=[],
            created_at=now,
            last_active_at=now,
        )
        await self._storage.save(session_id, state)
        return state

    async def save(self, session_id: str, state: SessionState) -> None:
        """持久化会话状态。

        Args:
            session_id: 会话标识。
            state: 要持久化的会话状态。
        """
        await self._storage.save(session_id, state)

    async def cleanup_expired(self, idle_timeout_seconds: int) -> List[str]:
        """清理过期会话。

        移除所有 last_active_at 距当前时间超过 idle_timeout_seconds 的会话。

        Args:
            idle_timeout_seconds: 空闲超时时间（秒）。

        Returns:
            被清理的 session_id 列表。
        """
        now = time.time()
        expired_ids: List[str] = []

        if isinstance(self._storage, InMemoryStorageBackend):
            all_sessions = self._storage.list_all()
            for sid, state in all_sessions.items():
                if now - state.last_active_at > idle_timeout_seconds:
                    expired_ids.append(sid)
            for sid in expired_ids:
                await self._storage.delete(sid)

        return expired_ids

    # --------------------------------------------------------
    # Topic Management
    # --------------------------------------------------------

    def create_topic(
        self,
        state: SessionState,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Topic:
        """创建新话题并添加到会话状态。

        新话题的状态为 "active"，其余非 "closed" 话题设为 "suspended"，
        确保任何时刻最多只有一个活跃话题。

        Args:
            state: 当前会话状态。
            name: 话题名称。
            metadata: 话题元数据。

        Returns:
            新创建的 Topic 实例。
        """
        # Suspend existing non-closed topics to maintain the invariant
        # that at most one topic is active at any time.
        for existing in state.active_topics:
            if existing.status != "closed":
                existing.status = "suspended"

        topic = Topic(
            topic_id=str(uuid.uuid4()),
            name=name,
            status="active",
            created_at=time.time(),
            metadata=metadata or {},
        )
        state.active_topics.append(topic)
        return topic

    def switch_topic(self, state: SessionState, topic_id: str) -> bool:
        """切换活跃话题。

        将指定话题设为 "active"，其余非 "closed" 话题设为 "suspended"。

        Args:
            state: 当前会话状态。
            topic_id: 要切换到的话题 ID。

        Returns:
            若找到目标话题并成功切换返回 True，否则返回 False。
        """
        target_found = False
        for topic in state.active_topics:
            if topic.topic_id == topic_id:
                if topic.status == "closed":
                    return False
                target_found = True
                break

        if not target_found:
            return False

        for topic in state.active_topics:
            if topic.status == "closed":
                continue
            if topic.topic_id == topic_id:
                topic.status = "active"
            else:
                topic.status = "suspended"

        return True

    def close_topic(self, state: SessionState, topic_id: str) -> bool:
        """关闭话题。

        将指定话题状态设为 "closed"。

        Args:
            state: 当前会话状态。
            topic_id: 要关闭的话题 ID。

        Returns:
            若找到目标话题并成功关闭返回 True，否则返回 False。
        """
        for topic in state.active_topics:
            if topic.topic_id == topic_id:
                topic.status = "closed"
                return True
        return False

    # --------------------------------------------------------
    # Dialog History Compression
    # --------------------------------------------------------

    def compress_dialog_history(self, state: SessionState) -> None:
        """压缩对话历史。

        当对话历史轮次超过 max_dialog_history_turns 时，将较早的轮次
        摘要为一条摘要记录，保留最近的轮次。压缩后的对话历史长度
        不超过 max_dialog_history_turns。

        Args:
            state: 当前会话状态。
        """
        max_turns = self._max_dialog_history_turns
        history = state.dialog_history

        if len(history) <= max_turns:
            return

        # Keep the most recent turns (reserve 1 slot for the summary entry)
        keep_count = max_turns - 1 if max_turns > 0 else 0
        older_entries = history[: len(history) - keep_count] if keep_count > 0 else history
        recent_entries = history[len(history) - keep_count :] if keep_count > 0 else []

        # Build a summary of the older entries
        summary_parts: List[str] = []
        for entry in older_entries:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            summary_parts.append(f"{role}: {content}")

        summary_text = "[Summary of earlier conversation] " + " | ".join(summary_parts)

        summary_entry: Dict[str, Any] = {
            "role": "system",
            "content": summary_text,
        }

        state.dialog_history = [summary_entry] + recent_entries
