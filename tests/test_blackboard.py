"""Tests for the Blackboard shared state storage."""

import asyncio
import time
from unittest.mock import patch

import pytest

from agentic_bff_sdk.blackboard import Blackboard


# ============================================================
# Basic CRUD Tests
# ============================================================


class TestBlackboardCRUD:
    async def test_set_and_get(self):
        bb = Blackboard()
        await bb.set("key1", "value1")
        result = await bb.get("key1")
        assert result == "value1"

    async def test_get_nonexistent_key_returns_none(self):
        bb = Blackboard()
        result = await bb.get("missing")
        assert result is None

    async def test_set_overwrites_existing_value(self):
        bb = Blackboard()
        await bb.set("key1", "old")
        await bb.set("key1", "new")
        result = await bb.get("key1")
        assert result == "new"

    async def test_delete_existing_key(self):
        bb = Blackboard()
        await bb.set("key1", "value1")
        deleted = await bb.delete("key1")
        assert deleted is True
        result = await bb.get("key1")
        assert result is None

    async def test_delete_nonexistent_key(self):
        bb = Blackboard()
        deleted = await bb.delete("missing")
        assert deleted is False

    async def test_set_various_value_types(self):
        bb = Blackboard()
        await bb.set("str", "hello")
        await bb.set("int", 42)
        await bb.set("float", 3.14)
        await bb.set("list", [1, 2, 3])
        await bb.set("dict", {"a": 1})
        await bb.set("none", None)

        assert await bb.get("str") == "hello"
        assert await bb.get("int") == 42
        assert await bb.get("float") == 3.14
        assert await bb.get("list") == [1, 2, 3]
        assert await bb.get("dict") == {"a": 1}
        assert await bb.get("none") is None

    async def test_multiple_keys(self):
        bb = Blackboard()
        await bb.set("a", 1)
        await bb.set("b", 2)
        await bb.set("c", 3)
        assert await bb.get("a") == 1
        assert await bb.get("b") == 2
        assert await bb.get("c") == 3


# ============================================================
# Access Time Tracking Tests
# ============================================================


class TestBlackboardAccessTimes:
    async def test_set_records_access_time(self):
        bb = Blackboard()
        before = time.time()
        await bb.set("key1", "value1")
        after = time.time()
        assert "key1" in bb._access_times
        assert before <= bb._access_times["key1"] <= after

    async def test_get_updates_access_time(self):
        bb = Blackboard()
        await bb.set("key1", "value1")
        first_access = bb._access_times["key1"]
        # Small delay to ensure time difference
        await asyncio.sleep(0.01)
        await bb.get("key1")
        assert bb._access_times["key1"] > first_access

    async def test_get_nonexistent_does_not_create_access_time(self):
        bb = Blackboard()
        await bb.get("missing")
        assert "missing" not in bb._access_times

    async def test_delete_removes_access_time(self):
        bb = Blackboard()
        await bb.set("key1", "value1")
        assert "key1" in bb._access_times
        await bb.delete("key1")
        assert "key1" not in bb._access_times


# ============================================================
# Expiration Cleanup Tests
# ============================================================


class TestBlackboardCleanup:
    async def test_cleanup_removes_expired_keys(self):
        bb = Blackboard()
        # Set keys with mocked old access times
        await bb.set("old_key", "old_value")
        bb._access_times["old_key"] = time.time() - 100

        await bb.set("new_key", "new_value")

        expired = await bb.cleanup_expired(ttl_seconds=50)
        assert "old_key" in expired
        assert "new_key" not in expired
        assert await bb.get("old_key") is None
        assert await bb.get("new_key") == "new_value"

    async def test_cleanup_returns_empty_when_nothing_expired(self):
        bb = Blackboard()
        await bb.set("key1", "value1")
        expired = await bb.cleanup_expired(ttl_seconds=3600)
        assert expired == []
        assert await bb.get("key1") == "value1"

    async def test_cleanup_on_empty_blackboard(self):
        bb = Blackboard()
        expired = await bb.cleanup_expired(ttl_seconds=10)
        assert expired == []

    async def test_cleanup_removes_all_expired(self):
        bb = Blackboard()
        old_time = time.time() - 200
        await bb.set("a", 1)
        await bb.set("b", 2)
        await bb.set("c", 3)
        bb._access_times["a"] = old_time
        bb._access_times["b"] = old_time
        bb._access_times["c"] = old_time

        expired = await bb.cleanup_expired(ttl_seconds=100)
        assert sorted(expired) == ["a", "b", "c"]
        assert await bb.get("a") is None
        assert await bb.get("b") is None
        assert await bb.get("c") is None

    async def test_cleanup_preserves_unexpired_keys(self):
        bb = Blackboard()
        await bb.set("keep", "value")
        await bb.set("remove", "value")
        bb._access_times["remove"] = time.time() - 200

        expired = await bb.cleanup_expired(ttl_seconds=100)
        assert "remove" in expired
        assert "keep" not in expired
        assert await bb.get("keep") == "value"


# ============================================================
# Thread Safety Tests
# ============================================================


class TestBlackboardConcurrency:
    async def test_concurrent_writes(self):
        bb = Blackboard()

        async def write(key: str, value: int):
            await bb.set(key, value)

        tasks = [write(f"key_{i}", i) for i in range(100)]
        await asyncio.gather(*tasks)

        for i in range(100):
            result = await bb.get(f"key_{i}")
            assert result == i

    async def test_concurrent_reads_and_writes(self):
        bb = Blackboard()
        await bb.set("shared", 0)

        async def increment():
            val = await bb.get("shared")
            await bb.set("shared", (val or 0) + 1)

        # Run multiple increments concurrently
        tasks = [increment() for _ in range(50)]
        await asyncio.gather(*tasks)

        # The final value should be set (may not be exactly 50 due to race
        # conditions at the application level, but the lock ensures no crashes)
        result = await bb.get("shared")
        assert result is not None
        assert isinstance(result, int)
