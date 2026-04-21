"""Property-based tests for Session state persistence.

Uses Hypothesis to generate random SessionState instances and verify
that saving to InMemoryStorageBackend and loading back produces an
equivalent state (round-trip correctness).
"""

import pytest
from hypothesis import given, settings, strategies as st

from agentic_bff_sdk.models import SessionState, Topic
from agentic_bff_sdk.session import InMemoryStorageBackend

# ============================================================
# Hypothesis Strategies
# ============================================================

# Safe text: printable strings that survive serialization round-trips
safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
)

# Non-empty identifier strings for IDs
safe_id = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=30,
)

# JSON-safe primitive values for Dict[str, Any] fields
json_primitive = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(
        min_value=-1e6,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
    ),
    safe_text,
)

# Simple JSON-safe dict (one level deep)
json_safe_dict = st.dictionaries(
    keys=safe_id,
    values=json_primitive,
    max_size=5,
)

# Positive finite timestamps
safe_timestamp = st.floats(
    min_value=0.0,
    max_value=1e12,
    allow_nan=False,
    allow_infinity=False,
)

# Topic strategy
topic_st = st.builds(
    Topic,
    topic_id=safe_id,
    name=safe_text,
    status=st.sampled_from(["active", "suspended", "closed"]),
    created_at=safe_timestamp,
    metadata=json_safe_dict,
)

# Dialog history entry strategy
dialog_entry_st = st.fixed_dictionaries(
    {"role": st.sampled_from(["user", "assistant", "system"]),
     "content": safe_text},
)

# SessionState strategy
session_state_st = st.builds(
    SessionState,
    session_id=safe_id,
    dialog_history=st.lists(dialog_entry_st, max_size=20),
    user_profile_summary=st.one_of(st.none(), safe_text),
    active_topics=st.lists(topic_st, max_size=10),
    created_at=safe_timestamp,
    last_active_at=safe_timestamp,
)


# ============================================================
# Property 1: Session 状态持久化 Round-Trip
# ============================================================


@pytest.mark.property
class TestSessionStateRoundTrip:
    """Property 1: Session 状态持久化 Round-Trip

    For any valid SessionState (with arbitrary dialog history, user profile
    summary, and active topics), saving it to a storage backend and loading
    it back should produce a SessionState instance equivalent to the original.

    **Validates: Requirements 1.2, 2.1, 2.4**
    """

    @given(state=session_state_st)
    @settings(max_examples=100)
    async def test_save_then_load_returns_equivalent_state(
        self, state: SessionState
    ):
        """Saving a SessionState and loading it back produces an equivalent instance.

        **Validates: Requirements 1.2, 2.1, 2.4**
        """
        storage = InMemoryStorageBackend()
        await storage.save(state.session_id, state)
        loaded = await storage.load(state.session_id)

        assert loaded is not None
        assert loaded == state

    @given(
        state1=session_state_st,
        state2=session_state_st,
    )
    @settings(max_examples=100)
    async def test_save_overwrites_previous_state(
        self, state1: SessionState, state2: SessionState
    ):
        """Saving a new state for the same session_id overwrites the previous one.

        **Validates: Requirements 1.2, 2.1, 2.4**
        """
        storage = InMemoryStorageBackend()
        # Use the same session_id for both states
        sid = state1.session_id
        state2_same_id = state2.model_copy(update={"session_id": sid})

        await storage.save(sid, state1)
        await storage.save(sid, state2_same_id)
        loaded = await storage.load(sid)

        assert loaded is not None
        assert loaded == state2_same_id

    @given(
        states=st.lists(
            session_state_st,
            min_size=1,
            max_size=10,
            unique_by=lambda s: s.session_id,
        )
    )
    @settings(max_examples=100)
    async def test_multiple_sessions_round_trip(
        self, states: list
    ):
        """Multiple distinct sessions saved and loaded back all match their originals.

        **Validates: Requirements 1.2, 2.1, 2.4**
        """
        storage = InMemoryStorageBackend()

        for state in states:
            await storage.save(state.session_id, state)

        for state in states:
            loaded = await storage.load(state.session_id)
            assert loaded is not None
            assert loaded == state


# ============================================================
# Property 3: 会话过期清理
# ============================================================


@pytest.mark.property
class TestSessionExpirationCleanup:
    """Property 3: 会话过期清理

    For any set of SessionState instances and an idle_timeout, calling
    cleanup_expired should remove exactly those sessions whose
    last_active_at is older than (now - idle_timeout) and preserve
    the rest.

    **Validates: Requirements 1.5**
    """

    @given(
        sessions=st.lists(
            session_state_st,
            min_size=0,
            max_size=15,
            unique_by=lambda s: s.session_id,
        ),
        idle_timeout=st.integers(min_value=1, max_value=7200),
    )
    @settings(max_examples=100)
    async def test_expired_sessions_removed_fresh_preserved(
        self, sessions: list, idle_timeout: int
    ):
        """Sessions whose last_active_at exceeds idle_timeout are removed;
        others are preserved.

        We set each session's last_active_at to either clearly expired or
        clearly fresh relative to a fixed 'now', then freeze time so
        cleanup_expired sees the same 'now'.

        **Validates: Requirements 1.5**
        """
        import time
        from unittest.mock import patch

        from agentic_bff_sdk.session import SessionContext, InMemoryStorageBackend

        # Use a fixed reference time
        now = 1_000_000_000.0

        expected_expired: set[str] = set()
        expected_kept: set[str] = set()

        storage = InMemoryStorageBackend()
        ctx = SessionContext(storage=storage)

        for i, session in enumerate(sessions):
            # Alternate: even-index sessions are expired, odd-index are fresh
            if i % 2 == 0:
                # Expired: last_active_at is clearly before the cutoff
                expired_at = now - idle_timeout - 1.0 - i
                updated = session.model_copy(update={"last_active_at": expired_at})
                expected_expired.add(session.session_id)
            else:
                # Fresh: last_active_at is clearly after the cutoff
                fresh_at = now - idle_timeout + 60.0 + i
                updated = session.model_copy(update={"last_active_at": fresh_at})
                expected_kept.add(session.session_id)

            await storage.save(updated.session_id, updated)

        # Freeze time.time() so cleanup_expired uses our fixed 'now'
        with patch("agentic_bff_sdk.session.time") as mock_time:
            mock_time.time.return_value = now
            removed_ids = await ctx.cleanup_expired(idle_timeout)

        removed_set = set(removed_ids)

        # All expired sessions should have been removed
        assert removed_set == expected_expired, (
            f"Expected expired={expected_expired}, got removed={removed_set}"
        )

        # All fresh sessions should still be in storage
        for sid in expected_kept:
            loaded = await storage.load(sid)
            assert loaded is not None, f"Fresh session {sid!r} was incorrectly removed"

        # No expired session should remain in storage
        for sid in expected_expired:
            loaded = await storage.load(sid)
            assert loaded is None, f"Expired session {sid!r} was not removed"

    @given(
        sessions=st.lists(
            session_state_st,
            min_size=1,
            max_size=10,
            unique_by=lambda s: s.session_id,
        ),
        idle_timeout=st.integers(min_value=1, max_value=3600),
    )
    @settings(max_examples=100)
    async def test_all_fresh_sessions_none_removed(
        self, sessions: list, idle_timeout: int
    ):
        """When all sessions are fresh, cleanup_expired removes nothing.

        **Validates: Requirements 1.5**
        """
        import time
        from unittest.mock import patch

        from agentic_bff_sdk.session import SessionContext, InMemoryStorageBackend

        now = 1_000_000_000.0
        storage = InMemoryStorageBackend()
        ctx = SessionContext(storage=storage)

        for session in sessions:
            # All sessions are fresh (last active well within timeout)
            fresh_at = now - idle_timeout + 100.0
            updated = session.model_copy(update={"last_active_at": fresh_at})
            await storage.save(updated.session_id, updated)

        with patch("agentic_bff_sdk.session.time") as mock_time:
            mock_time.time.return_value = now
            removed_ids = await ctx.cleanup_expired(idle_timeout)

        assert removed_ids == [], "No sessions should be removed when all are fresh"

        # Verify all sessions still exist
        for session in sessions:
            loaded = await storage.load(session.session_id)
            assert loaded is not None

    @given(
        sessions=st.lists(
            session_state_st,
            min_size=1,
            max_size=10,
            unique_by=lambda s: s.session_id,
        ),
        idle_timeout=st.integers(min_value=1, max_value=3600),
    )
    @settings(max_examples=100)
    async def test_all_expired_sessions_all_removed(
        self, sessions: list, idle_timeout: int
    ):
        """When all sessions are expired, cleanup_expired removes all of them.

        **Validates: Requirements 1.5**
        """
        import time
        from unittest.mock import patch

        from agentic_bff_sdk.session import SessionContext, InMemoryStorageBackend

        now = 1_000_000_000.0
        storage = InMemoryStorageBackend()
        ctx = SessionContext(storage=storage)

        all_ids: set[str] = set()
        for i, session in enumerate(sessions):
            expired_at = now - idle_timeout - 1.0 - i
            updated = session.model_copy(update={"last_active_at": expired_at})
            await storage.save(updated.session_id, updated)
            all_ids.add(session.session_id)

        with patch("agentic_bff_sdk.session.time") as mock_time:
            mock_time.time.return_value = now
            removed_ids = await ctx.cleanup_expired(idle_timeout)

        assert set(removed_ids) == all_ids, (
            f"All sessions should be removed; expected={all_ids}, got={set(removed_ids)}"
        )

        # Verify storage is empty
        for sid in all_ids:
            loaded = await storage.load(sid)
            assert loaded is None


# ============================================================
# Property 4: 话题管理一致性
# ============================================================


@pytest.mark.property
class TestTopicManagementConsistency:
    """Property 4: 话题管理一致性

    For any sequence of topic operations (create, switch, close), the
    resulting topic list should satisfy:
    1. Created topics exist in the topic list
    2. Closed topics have status "closed"
    3. At most one topic has status "active" at any time

    **Validates: Requirements 1.3**
    """

    # Strategy: generate a sequence of topic operations
    # Operations are represented as tagged tuples:
    #   ("create", name)
    #   ("switch", index)  -- index into created topics so far
    #   ("close", index)   -- index into created topics so far

    @given(
        operations=st.lists(
            st.one_of(
                st.tuples(st.just("create"), safe_text),
                st.tuples(st.just("switch"), st.integers(min_value=0, max_value=49)),
                st.tuples(st.just("close"), st.integers(min_value=0, max_value=49)),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @settings(max_examples=100)
    def test_topic_operations_maintain_consistency(self, operations: list):
        """Random sequences of create/switch/close operations maintain
        topic list consistency invariants.

        **Validates: Requirements 1.3**
        """
        from agentic_bff_sdk.session import SessionContext

        ctx = SessionContext()
        state = SessionState(
            session_id="test-session",
            dialog_history=[],
            created_at=1_000_000.0,
            last_active_at=1_000_000.0,
        )

        created_topic_ids: list[str] = []
        closed_topic_ids: set[str] = set()

        for op_type, op_arg in operations:
            if op_type == "create":
                topic = ctx.create_topic(state, name=op_arg)
                created_topic_ids.append(topic.topic_id)
            elif op_type == "switch":
                if created_topic_ids:
                    idx = op_arg % len(created_topic_ids)
                    ctx.switch_topic(state, created_topic_ids[idx])
            elif op_type == "close":
                if created_topic_ids:
                    idx = op_arg % len(created_topic_ids)
                    tid = created_topic_ids[idx]
                    result = ctx.close_topic(state, tid)
                    if result:
                        closed_topic_ids.add(tid)

        # --- Invariant 1: All created topics exist in the topic list ---
        topic_ids_in_state = {t.topic_id for t in state.active_topics}
        for tid in created_topic_ids:
            assert tid in topic_ids_in_state, (
                f"Created topic {tid!r} not found in topic list"
            )

        # --- Invariant 2: Closed topics have status "closed" ---
        for topic in state.active_topics:
            if topic.topic_id in closed_topic_ids:
                assert topic.status == "closed", (
                    f"Topic {topic.topic_id!r} was closed but has status {topic.status!r}"
                )

        # --- Invariant 3: At most one topic has status "active" ---
        active_topics = [t for t in state.active_topics if t.status == "active"]
        assert len(active_topics) <= 1, (
            f"Expected at most 1 active topic, found {len(active_topics)}: "
            f"{[t.topic_id for t in active_topics]}"
        )


# ============================================================
# Property 7: 对话历史压缩后长度不超限
# ============================================================


@pytest.mark.property
class TestDialogHistoryCompression:
    """Property 7: 对话历史压缩后长度不超限

    For any dialog history whose length exceeds max_dialog_history_turns,
    after compression:
    1. len(state.dialog_history) <= max_dialog_history_turns
    2. The most recent turns from the original history are preserved
       intact at the end of the compressed history.

    **Validates: Requirements 2.3**
    """

    @given(
        max_turns=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_compressed_length_within_limit(self, max_turns: int, data):
        """After compression, dialog history length <= max_dialog_history_turns.

        **Validates: Requirements 2.3**
        """
        from agentic_bff_sdk.session import SessionContext

        # Generate a history that exceeds max_turns
        history_len = data.draw(
            st.integers(min_value=max_turns + 1, max_value=max_turns + 100),
            label="history_len",
        )
        history = data.draw(
            st.lists(dialog_entry_st, min_size=history_len, max_size=history_len),
            label="dialog_history",
        )

        ctx = SessionContext(max_dialog_history_turns=max_turns)
        state = SessionState(
            session_id="test-compress",
            dialog_history=history,
            created_at=1_000_000.0,
            last_active_at=1_000_000.0,
        )

        ctx.compress_dialog_history(state)

        assert len(state.dialog_history) <= max_turns, (
            f"Compressed history length {len(state.dialog_history)} "
            f"exceeds max_dialog_history_turns={max_turns}"
        )

    @given(
        max_turns=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_recent_turns_preserved_after_compression(self, max_turns: int, data):
        """The most recent turns from the original history are preserved
        intact at the end of the compressed history.

        **Validates: Requirements 2.3**
        """
        from agentic_bff_sdk.session import SessionContext

        # Generate a history that exceeds max_turns
        history_len = data.draw(
            st.integers(min_value=max_turns + 1, max_value=max_turns + 100),
            label="history_len",
        )
        history = data.draw(
            st.lists(dialog_entry_st, min_size=history_len, max_size=history_len),
            label="dialog_history",
        )

        # The number of recent entries that should be preserved
        keep_count = max_turns - 1
        expected_recent = history[-keep_count:]

        ctx = SessionContext(max_dialog_history_turns=max_turns)
        state = SessionState(
            session_id="test-compress",
            dialog_history=list(history),  # copy to avoid mutation issues
            created_at=1_000_000.0,
            last_active_at=1_000_000.0,
        )

        ctx.compress_dialog_history(state)

        # The compressed history should end with the most recent entries
        actual_recent = state.dialog_history[-keep_count:]
        assert actual_recent == expected_recent, (
            f"Recent turns not preserved. Expected last {keep_count} entries "
            f"to match original, but they differ."
        )

    @given(
        max_turns=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_first_entry_is_system_summary(self, max_turns: int, data):
        """After compression, the first entry is a system summary of older entries.

        **Validates: Requirements 2.3**
        """
        from agentic_bff_sdk.session import SessionContext

        # Generate a history that exceeds max_turns
        history_len = data.draw(
            st.integers(min_value=max_turns + 1, max_value=max_turns + 100),
            label="history_len",
        )
        history = data.draw(
            st.lists(dialog_entry_st, min_size=history_len, max_size=history_len),
            label="dialog_history",
        )

        ctx = SessionContext(max_dialog_history_turns=max_turns)
        state = SessionState(
            session_id="test-compress",
            dialog_history=list(history),
            created_at=1_000_000.0,
            last_active_at=1_000_000.0,
        )

        ctx.compress_dialog_history(state)

        first_entry = state.dialog_history[0]
        assert first_entry["role"] == "system", (
            f"First entry after compression should have role 'system', "
            f"got {first_entry['role']!r}"
        )
        assert first_entry["content"].startswith("[Summary of earlier conversation]"), (
            f"First entry content should start with summary marker, "
            f"got: {first_entry['content'][:80]!r}"
        )
