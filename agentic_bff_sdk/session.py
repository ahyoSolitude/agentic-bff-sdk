"""Session lifecycle, topic management, and dialog history compression."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod

from agentic_bff_sdk.config import RuntimeConfig
from agentic_bff_sdk.models import SessionMessage, SessionState, Topic, TopicStatus


class SessionStore(ABC):
    @abstractmethod
    async def load(self, session_id: str) -> SessionState | None:
        ...

    @abstractmethod
    async def save(self, state: SessionState) -> None:
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        ...


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    async def load(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    async def save(self, state: SessionState) -> None:
        self._sessions[state.session_id] = state

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_all(self) -> list[SessionState]:
        return list(self._sessions.values())


class SessionManager:
    def __init__(
        self,
        store: SessionStore | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self._store = store or InMemorySessionStore()
        self._runtime = runtime_config or RuntimeConfig()

    async def get_or_create(self, session_id: str) -> SessionState:
        state = await self._store.load(session_id)
        if state is not None:
            state.last_active_at = time.time()
            return state

        now = time.time()
        state = SessionState(session_id=session_id, created_at=now, last_active_at=now)
        await self._store.save(state)
        return state

    async def save(self, state: SessionState) -> None:
        state.last_active_at = time.time()
        await self._store.save(state)

    async def append_message(self, session_id: str, message: SessionMessage) -> SessionState:
        state = await self.get_or_create(session_id)
        state.dialog_history.append(message)
        self.compress_history(state)
        await self.save(state)
        return state

    async def cleanup_expired(self) -> list[str]:
        if not isinstance(self._store, InMemorySessionStore):
            return []
        now = time.time()
        expired = [
            state.session_id
            for state in self._store.list_all()
            if now - state.last_active_at > self._runtime.session_idle_timeout_seconds
        ]
        for session_id in expired:
            await self._store.delete(session_id)
        return expired

    def create_topic(self, state: SessionState, name: str) -> Topic:
        for topic in state.active_topics:
            if topic.status != TopicStatus.CLOSED:
                topic.status = TopicStatus.SUSPENDED
        topic = Topic(
            topic_id=str(uuid.uuid4()),
            name=name,
            status=TopicStatus.ACTIVE,
            created_at=time.time(),
        )
        state.active_topics.append(topic)
        return topic

    def switch_topic(self, state: SessionState, topic_id: str) -> bool:
        target = next((topic for topic in state.active_topics if topic.topic_id == topic_id), None)
        if target is None or target.status == TopicStatus.CLOSED:
            return False
        for topic in state.active_topics:
            if topic.status != TopicStatus.CLOSED:
                topic.status = TopicStatus.ACTIVE if topic.topic_id == topic_id else TopicStatus.SUSPENDED
        return True

    def close_topic(self, state: SessionState, topic_id: str) -> bool:
        for topic in state.active_topics:
            if topic.topic_id == topic_id:
                topic.status = TopicStatus.CLOSED
                return True
        return False

    def compress_history(self, state: SessionState) -> None:
        max_items = self._runtime.max_dialog_history_turns
        if len(state.dialog_history) <= max_items:
            return
        keep = max_items - 1
        older = state.dialog_history[:-keep]
        recent = state.dialog_history[-keep:]
        summary = " | ".join(f"{msg.role}: {msg.content}" for msg in older)
        state.dialog_history = [
            SessionMessage(role="system", content=f"[Summary] {summary}", timestamp=time.time())
        ] + recent
