"""Unit tests for the FanInAggregator module."""

import asyncio
from typing import List

import pytest

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.models import AggregatedResult, StepResult, StepStatus


# ============================================================
# Helpers
# ============================================================


def _make_result(
    step_id: str,
    status: StepStatus = StepStatus.COMPLETED,
    result: str = "ok",
    error: str | None = None,
) -> StepResult:
    return StepResult(
        step_id=step_id,
        status=status,
        result=result,
        error=error,
        duration_ms=100.0,
    )


# ============================================================
# Basic aggregation tests
# ============================================================


class TestFanInAggregatorBasic:
    """Basic aggregation behavior tests."""

    async def test_all_steps_present_returns_complete(self) -> None:
        """When all expected steps have results, is_partial=False."""
        aggregator = FanInAggregator()
        results = [_make_result("s1"), _make_result("s2"), _make_result("s3")]
        expected = ["s1", "s2", "s3"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is False
        assert aggregated.missing_steps == []
        assert len(aggregated.results) == 3

    async def test_missing_steps_returns_partial(self) -> None:
        """When some expected steps are missing, is_partial=True."""
        aggregator = FanInAggregator()
        results = [_make_result("s1")]
        expected = ["s1", "s2", "s3"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is True
        assert set(aggregated.missing_steps) == {"s2", "s3"}
        assert len(aggregated.results) == 1

    async def test_no_results_all_missing(self) -> None:
        """When no results are provided, all expected steps are missing."""
        aggregator = FanInAggregator()
        results: List[StepResult] = []
        expected = ["s1", "s2"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is True
        assert set(aggregated.missing_steps) == {"s1", "s2"}
        assert len(aggregated.results) == 0

    async def test_empty_expected_steps_returns_complete(self) -> None:
        """When no steps are expected, result is complete even with no results."""
        aggregator = FanInAggregator()
        results: List[StepResult] = []
        expected: List[str] = []

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is False
        assert aggregated.missing_steps == []
        assert len(aggregated.results) == 0

    async def test_extra_results_are_filtered(self) -> None:
        """Results for steps not in expected_steps are filtered out."""
        aggregator = FanInAggregator()
        results = [_make_result("s1"), _make_result("s2"), _make_result("extra")]
        expected = ["s1", "s2"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is False
        assert aggregated.missing_steps == []
        assert len(aggregated.results) == 2
        result_ids = {r.step_id for r in aggregated.results}
        assert result_ids == {"s1", "s2"}


# ============================================================
# Step status handling
# ============================================================


class TestFanInAggregatorStepStatuses:
    """Tests for handling various step statuses."""

    async def test_failed_steps_still_count_as_present(self) -> None:
        """Failed steps are included in results and not listed as missing."""
        aggregator = FanInAggregator()
        results = [
            _make_result("s1", StepStatus.COMPLETED),
            _make_result("s2", StepStatus.FAILED, error="something broke"),
        ]
        expected = ["s1", "s2"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is False
        assert aggregated.missing_steps == []
        assert len(aggregated.results) == 2

    async def test_timeout_steps_still_count_as_present(self) -> None:
        """Timeout steps are included in results and not listed as missing."""
        aggregator = FanInAggregator()
        results = [
            _make_result("s1", StepStatus.COMPLETED),
            _make_result("s2", StepStatus.TIMEOUT),
        ]
        expected = ["s1", "s2"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.is_partial is False
        assert aggregated.missing_steps == []


# ============================================================
# Timeout-based aggregation
# ============================================================


class TestFanInAggregatorTimeout:
    """Tests for timeout-based aggregation with async tasks."""

    async def test_all_tasks_complete_before_timeout(self) -> None:
        """When all tasks complete before timeout, result is complete."""
        aggregator = FanInAggregator()

        async def fast_task(step_id: str) -> StepResult:
            return _make_result(step_id)

        tasks = [
            asyncio.create_task(fast_task("s1")),
            asyncio.create_task(fast_task("s2")),
        ]
        expected = ["s1", "s2"]

        aggregated = await aggregator.aggregate_with_timeout(
            tasks, expected, wait_timeout_seconds=5.0
        )

        assert aggregated.is_partial is False
        assert aggregated.missing_steps == []
        assert len(aggregated.results) == 2

    async def test_some_tasks_timeout(self) -> None:
        """When some tasks don't complete before timeout, result is partial."""
        aggregator = FanInAggregator()

        async def fast_task(step_id: str) -> StepResult:
            return _make_result(step_id)

        async def slow_task(step_id: str) -> StepResult:
            await asyncio.sleep(10)
            return _make_result(step_id)

        tasks = [
            asyncio.create_task(fast_task("s1")),
            asyncio.create_task(slow_task("s2")),
        ]
        expected = ["s1", "s2"]

        aggregated = await aggregator.aggregate_with_timeout(
            tasks, expected, wait_timeout_seconds=0.1
        )

        assert aggregated.is_partial is True
        assert "s2" in aggregated.missing_steps
        # s1 should be in results
        result_ids = {r.step_id for r in aggregated.results}
        assert "s1" in result_ids

    async def test_missing_steps_order_preserved(self) -> None:
        """Missing steps are listed in the same order as expected_steps."""
        aggregator = FanInAggregator()
        results = [_make_result("s2")]
        expected = ["s1", "s2", "s3", "s4"]

        aggregated = await aggregator.aggregate(results, expected)

        assert aggregated.missing_steps == ["s1", "s3", "s4"]
