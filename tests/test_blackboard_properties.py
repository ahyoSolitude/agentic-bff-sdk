"""Property-based tests for Blackboard shared state storage.

Uses Hypothesis to generate random key-value pairs and verify
the Blackboard set/get round-trip correctness.
"""

import pytest
from hypothesis import given, settings, strategies as st

from agentic_bff_sdk.blackboard import Blackboard

# ============================================================
# Hypothesis Strategies
# ============================================================

# Non-empty key strings (Blackboard keys are plain strings)
blackboard_key = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
)

# JSON-serializable leaf values
json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(
        min_value=-1e6,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            blacklist_characters="\x00",
        ),
        max_size=100,
    ),
)

# Recursive JSON-serializable values: primitives, lists, and dicts
json_value = st.recursive(
    json_leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(
            keys=st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    blacklist_characters="\x00",
                ),
                min_size=1,
                max_size=20,
            ),
            values=children,
            max_size=5,
        ),
    ),
    max_leaves=15,
)


# ============================================================
# Property 5: Blackboard 键值 Round-Trip
# ============================================================


@pytest.mark.property
class TestBlackboardKeyValueRoundTrip:
    """Property 5: Blackboard 键值 Round-Trip

    For any key-value pair (key, value), after executing set(key, value)
    on a Blackboard, immediately executing get(key) should return a value
    equivalent to the original value.

    **Validates: Requirements 2.2, 5.6, 13.3**
    """

    @given(key=blackboard_key, value=json_value)
    @settings(max_examples=100)
    async def test_set_then_get_returns_equivalent_value(self, key: str, value):
        """set(key, value) followed by get(key) returns the equivalent value.

        **Validates: Requirements 2.2, 5.6, 13.3**
        """
        bb = Blackboard()
        await bb.set(key, value)
        result = await bb.get(key)
        assert result == value

    @given(
        key=blackboard_key,
        value1=json_value,
        value2=json_value,
    )
    @settings(max_examples=100)
    async def test_set_overwrites_previous_value(self, key: str, value1, value2):
        """Setting the same key twice should return the latest value on get.

        **Validates: Requirements 2.2, 5.6, 13.3**
        """
        bb = Blackboard()
        await bb.set(key, value1)
        await bb.set(key, value2)
        result = await bb.get(key)
        assert result == value2

    @given(
        data=st.lists(
            st.tuples(blackboard_key, json_value),
            min_size=1,
            max_size=20,
            unique_by=lambda pair: pair[0],
        )
    )
    @settings(max_examples=100)
    async def test_multiple_keys_round_trip(self, data):
        """Multiple distinct keys set and retrieved should all return their values.

        **Validates: Requirements 2.2, 5.6, 13.3**
        """
        bb = Blackboard()
        for key, value in data:
            await bb.set(key, value)

        for key, value in data:
            result = await bb.get(key)
            assert result == value


# ============================================================
# Property 6: Blackboard 过期清理
# ============================================================


@pytest.mark.property
class TestBlackboardExpiredCleanup:
    """Property 6: Blackboard 过期清理

    For any set of keys in the Blackboard, after calling cleanup_expired(ttl),
    all keys whose last access time exceeds the TTL should be removed,
    while keys that have not exceeded the TTL should be preserved.

    **Validates: Requirements 2.5**
    """

    @given(
        data=st.lists(
            st.tuples(blackboard_key, json_value),
            min_size=1,
            max_size=20,
            unique_by=lambda pair: pair[0],
        ),
        ttl=st.integers(min_value=1, max_value=3600),
        ages=st.lists(
            st.floats(min_value=0.0, max_value=7200.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100)
    async def test_expired_keys_removed_unexpired_preserved(
        self, data, ttl, ages,
    ):
        """Keys older than TTL are removed; keys within TTL are preserved.

        **Validates: Requirements 2.5**
        """
        from unittest.mock import patch

        bb = Blackboard()

        # Use a fixed reference time to avoid timing drift between
        # setting _access_times and calling cleanup_expired.
        now = 1_000_000_000.0

        # Set all keys
        for key, value in data:
            await bb.set(key, value)

        # Directly manipulate _access_times to simulate different ages
        expected_expired = set()
        expected_preserved = set()

        for i, (key, _value) in enumerate(data):
            age = ages[i % len(ages)]
            bb._access_times[key] = now - age
            if age > ttl:
                expected_expired.add(key)
            else:
                expected_preserved.add(key)

        # Freeze time so cleanup_expired sees the same 'now'
        with patch("agentic_bff_sdk.blackboard.time") as mock_time:
            mock_time.time.return_value = now
            removed = await bb.cleanup_expired(ttl)

        # Verify expired keys were removed
        assert set(removed) == expected_expired

        # Verify preserved keys are still in the store
        for key in expected_preserved:
            assert key in bb._store

        # Verify expired keys are no longer accessible
        # (Need to read without triggering access time update via internal store)
        for key in expected_expired:
            assert key not in bb._store

    @given(
        data=st.lists(
            st.tuples(blackboard_key, json_value),
            min_size=1,
            max_size=15,
            unique_by=lambda pair: pair[0],
        ),
        ttl=st.integers(min_value=1, max_value=3600),
    )
    @settings(max_examples=100)
    async def test_no_keys_removed_when_all_fresh(self, data, ttl):
        """When all keys are freshly set (age=0), none should be removed.

        **Validates: Requirements 2.5**
        """
        bb = Blackboard()

        for key, value in data:
            await bb.set(key, value)

        # All keys were just set, so their age is ~0 which is < any positive ttl
        removed = await bb.cleanup_expired(ttl)

        assert removed == []

        # All keys should still be present
        for key, value in data:
            result = await bb.get(key)
            assert result == value

    @given(
        data=st.lists(
            st.tuples(blackboard_key, json_value),
            min_size=1,
            max_size=15,
            unique_by=lambda pair: pair[0],
        ),
        ttl=st.integers(min_value=1, max_value=3600),
    )
    @settings(max_examples=100)
    async def test_all_keys_removed_when_all_expired(self, data, ttl):
        """When all keys have age > TTL, all should be removed.

        **Validates: Requirements 2.5**
        """
        import time

        bb = Blackboard()

        for key, value in data:
            await bb.set(key, value)

        # Set all access times to well beyond the TTL
        now = time.time()
        for key, _ in data:
            bb._access_times[key] = now - ttl - 1

        removed = await bb.cleanup_expired(ttl)

        assert set(removed) == {key for key, _ in data}
        assert len(bb._store) == 0
        assert len(bb._access_times) == 0
