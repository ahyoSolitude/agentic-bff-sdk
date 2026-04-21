"""Unit tests for the SessionContext module."""

import time

import pytest

from agentic_bff_sdk.models import SessionState, Topic
from agentic_bff_sdk.session import (
    InMemoryStorageBackend,
    SessionContext,
    StorageBackend,
)


# ============================================================
# StorageBackend Tests
# ============================================================


class TestInMemoryStorageBackend:
    """Tests for InMemoryStorageBackend."""

    @pytest.fixture
    def storage(self) -> InMemoryStorageBackend:
        return InMemoryStorageBackend()

    @pytest.fixture
    def sample_state(self) -> SessionState:
        now = time.time()
        return SessionState(
            session_id="test-session-1",
            dialog_history=[{"role": "user", "content": "hello"}],
            user_profile_summary="Test user",
            active_topics=[],
            created_at=now,
            last_active_at=now,
        )

    async def test_save_and_load(
        self, storage: InMemoryStorageBackend, sample_state: SessionState
    ) -> None:
        await storage.save(sample_state.session_id, sample_state)
        loaded = await storage.load(sample_state.session_id)
        assert loaded is not None
        assert loaded == sample_state

    async def test_load_nonexistent(self, storage: InMemoryStorageBackend) -> None:
        loaded = await storage.load("nonexistent")
        assert loaded is None

    async def test_delete(
        self, storage: InMemoryStorageBackend, sample_state: SessionState
    ) -> None:
        await storage.save(sample_state.session_id, sample_state)
        await storage.delete(sample_state.session_id)
        loaded = await storage.load(sample_state.session_id)
        assert loaded is None

    async def test_delete_nonexistent(
        self, storage: InMemoryStorageBackend
    ) -> None:
        # Should not raise
        await storage.delete("nonexistent")

    async def test_list_all(
        self, storage: InMemoryStorageBackend, sample_state: SessionState
    ) -> None:
        await storage.save(sample_state.session_id, sample_state)
        all_sessions = storage.list_all()
        assert sample_state.session_id in all_sessions


# ============================================================
# SessionContext.get_or_create Tests
# ============================================================


class TestSessionContextGetOrCreate:
    """Tests for SessionContext.get_or_create."""

    @pytest.fixture
    def ctx(self) -> SessionContext:
        return SessionContext()

    async def test_create_new_session(self, ctx: SessionContext) -> None:
        state = await ctx.get_or_create("new-session")
        assert state.session_id == "new-session"
        assert state.dialog_history == []
        assert state.active_topics == []
        assert state.user_profile_summary is None

    async def test_load_existing_session(self, ctx: SessionContext) -> None:
        state1 = await ctx.get_or_create("session-1")
        state1.dialog_history.append({"role": "user", "content": "hi"})
        await ctx.save("session-1", state1)

        state2 = await ctx.get_or_create("session-1")
        assert len(state2.dialog_history) == 1
        assert state2.dialog_history[0]["content"] == "hi"


# ============================================================
# SessionContext.save Tests
# ============================================================


class TestSessionContextSave:
    """Tests for SessionContext.save."""

    async def test_save_persists_state(self) -> None:
        ctx = SessionContext()
        state = await ctx.get_or_create("s1")
        state.user_profile_summary = "updated"
        await ctx.save("s1", state)

        loaded = await ctx.storage.load("s1")
        assert loaded is not None
        assert loaded.user_profile_summary == "updated"


# ============================================================
# SessionContext.cleanup_expired Tests
# ============================================================


class TestSessionContextCleanupExpired:
    """Tests for SessionContext.cleanup_expired."""

    async def test_cleanup_removes_expired_sessions(self) -> None:
        ctx = SessionContext()
        now = time.time()

        # Create an expired session
        expired_state = SessionState(
            session_id="expired",
            dialog_history=[],
            created_at=now - 7200,
            last_active_at=now - 7200,
        )
        await ctx.save("expired", expired_state)

        # Create a fresh session
        fresh_state = SessionState(
            session_id="fresh",
            dialog_history=[],
            created_at=now,
            last_active_at=now,
        )
        await ctx.save("fresh", fresh_state)

        removed = await ctx.cleanup_expired(idle_timeout_seconds=3600)
        assert "expired" in removed
        assert "fresh" not in removed

        # Verify expired session is gone
        assert await ctx.storage.load("expired") is None
        # Verify fresh session still exists
        assert await ctx.storage.load("fresh") is not None

    async def test_cleanup_returns_empty_when_none_expired(self) -> None:
        ctx = SessionContext()
        state = await ctx.get_or_create("active")
        removed = await ctx.cleanup_expired(idle_timeout_seconds=3600)
        assert removed == []


# ============================================================
# Topic Management Tests
# ============================================================


class TestTopicManagement:
    """Tests for topic create, switch, and close."""

    @pytest.fixture
    def ctx(self) -> SessionContext:
        return SessionContext()

    @pytest.fixture
    def state(self) -> SessionState:
        now = time.time()
        return SessionState(
            session_id="topic-test",
            dialog_history=[],
            created_at=now,
            last_active_at=now,
        )

    def test_create_topic(self, ctx: SessionContext, state: SessionState) -> None:
        topic = ctx.create_topic(state, "Topic A")
        assert topic.name == "Topic A"
        assert topic.status == "active"
        assert len(state.active_topics) == 1
        assert state.active_topics[0].topic_id == topic.topic_id

    def test_create_topic_with_metadata(
        self, ctx: SessionContext, state: SessionState
    ) -> None:
        topic = ctx.create_topic(state, "Topic B", metadata={"key": "value"})
        assert topic.metadata == {"key": "value"}

    def test_switch_topic(self, ctx: SessionContext, state: SessionState) -> None:
        t1 = ctx.create_topic(state, "Topic 1")
        t2 = ctx.create_topic(state, "Topic 2")

        result = ctx.switch_topic(state, t2.topic_id)
        assert result is True

        for topic in state.active_topics:
            if topic.topic_id == t2.topic_id:
                assert topic.status == "active"
            elif topic.topic_id == t1.topic_id:
                assert topic.status == "suspended"

    def test_switch_topic_nonexistent(
        self, ctx: SessionContext, state: SessionState
    ) -> None:
        result = ctx.switch_topic(state, "nonexistent-id")
        assert result is False

    def test_switch_topic_closed_returns_false(
        self, ctx: SessionContext, state: SessionState
    ) -> None:
        t1 = ctx.create_topic(state, "Topic 1")
        ctx.close_topic(state, t1.topic_id)
        result = ctx.switch_topic(state, t1.topic_id)
        assert result is False

    def test_close_topic(self, ctx: SessionContext, state: SessionState) -> None:
        t1 = ctx.create_topic(state, "Topic 1")
        result = ctx.close_topic(state, t1.topic_id)
        assert result is True
        assert state.active_topics[0].status == "closed"

    def test_close_topic_nonexistent(
        self, ctx: SessionContext, state: SessionState
    ) -> None:
        result = ctx.close_topic(state, "nonexistent-id")
        assert result is False

    def test_at_most_one_active_topic_after_switch(
        self, ctx: SessionContext, state: SessionState
    ) -> None:
        ctx.create_topic(state, "A")
        ctx.create_topic(state, "B")
        ctx.create_topic(state, "C")

        # Switch to the second topic
        t2_id = state.active_topics[1].topic_id
        ctx.switch_topic(state, t2_id)

        active_count = sum(
            1 for t in state.active_topics if t.status == "active"
        )
        assert active_count == 1


# ============================================================
# Dialog History Compression Tests
# ============================================================


class TestDialogHistoryCompression:
    """Tests for dialog history compression."""

    def test_no_compression_when_under_limit(self) -> None:
        ctx = SessionContext(max_dialog_history_turns=10)
        now = time.time()
        state = SessionState(
            session_id="s1",
            dialog_history=[{"role": "user", "content": f"msg {i}"} for i in range(5)],
            created_at=now,
            last_active_at=now,
        )
        ctx.compress_dialog_history(state)
        assert len(state.dialog_history) == 5

    def test_compression_reduces_length(self) -> None:
        ctx = SessionContext(max_dialog_history_turns=10)
        now = time.time()
        state = SessionState(
            session_id="s1",
            dialog_history=[
                {"role": "user", "content": f"msg {i}"} for i in range(20)
            ],
            created_at=now,
            last_active_at=now,
        )
        ctx.compress_dialog_history(state)
        assert len(state.dialog_history) <= 10

    def test_compression_preserves_recent_turns(self) -> None:
        ctx = SessionContext(max_dialog_history_turns=5)
        now = time.time()
        history = [{"role": "user", "content": f"msg {i}"} for i in range(15)]
        state = SessionState(
            session_id="s1",
            dialog_history=history.copy(),
            created_at=now,
            last_active_at=now,
        )
        ctx.compress_dialog_history(state)

        # The last 4 entries should be preserved (5 - 1 for summary)
        assert len(state.dialog_history) == 5
        # First entry is the summary
        assert state.dialog_history[0]["role"] == "system"
        assert "[Summary" in state.dialog_history[0]["content"]
        # Last 4 entries are the most recent from original
        for i in range(1, 5):
            assert state.dialog_history[i]["content"] == f"msg {10 + i}"

    def test_compression_with_max_turns_1(self) -> None:
        ctx = SessionContext(max_dialog_history_turns=1)
        now = time.time()
        state = SessionState(
            session_id="s1",
            dialog_history=[
                {"role": "user", "content": f"msg {i}"} for i in range(5)
            ],
            created_at=now,
            last_active_at=now,
        )
        ctx.compress_dialog_history(state)
        # With max_turns=1, keep_count=0, so all entries become summary
        assert len(state.dialog_history) == 1
        assert state.dialog_history[0]["role"] == "system"

    def test_compression_summary_contains_older_content(self) -> None:
        ctx = SessionContext(max_dialog_history_turns=3)
        now = time.time()
        state = SessionState(
            session_id="s1",
            dialog_history=[
                {"role": "user", "content": "old message"},
                {"role": "assistant", "content": "old reply"},
                {"role": "user", "content": "recent 1"},
                {"role": "assistant", "content": "recent 2"},
            ],
            created_at=now,
            last_active_at=now,
        )
        ctx.compress_dialog_history(state)
        summary = state.dialog_history[0]["content"]
        assert "old message" in summary
        assert "old reply" in summary
