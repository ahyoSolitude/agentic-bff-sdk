"""Property-based tests for the FanInAggregator module.

Uses Hypothesis to verify correctness properties of result aggregation
completeness across randomized inputs.
"""

import asyncio
from typing import List, Set

import pytest
from hypothesis import given, settings, strategies as st, assume

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.models import AggregatedResult, StepResult, StepStatus


# ============================================================
# Hypothesis Strategies
# ============================================================

# Strategy for generating step IDs
step_id_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=1,
    max_size=12,
)

# Strategy for generating a StepResult
step_result_strategy = st.builds(
    StepResult,
    step_id=step_id_strategy,
    status=st.sampled_from([StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.TIMEOUT]),
    result=st.one_of(st.none(), st.text(max_size=50)),
    error=st.one_of(st.none(), st.text(max_size=50)),
    duration_ms=st.floats(min_value=0, max_value=10000),
)


@st.composite
def complete_aggregation_scenario(draw: st.DrawFn):
    """Generate a scenario where all expected steps have results.

    Returns (step_results, expected_steps) where every expected step
    has a corresponding StepResult.
    """
    # Generate unique expected step IDs
    expected_steps = draw(
        st.lists(step_id_strategy, min_size=0, max_size=10, unique=True)
    )

    # Create a StepResult for each expected step
    step_results = []
    for step_id in expected_steps:
        status = draw(st.sampled_from([StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.TIMEOUT]))
        result = StepResult(
            step_id=step_id,
            status=status,
            result="data",
            duration_ms=draw(st.floats(min_value=0, max_value=10000)),
        )
        step_results.append(result)

    return step_results, expected_steps


@st.composite
def partial_aggregation_scenario(draw: st.DrawFn):
    """Generate a scenario where some expected steps are missing results.

    Returns (step_results, expected_steps) where at least one expected
    step does NOT have a corresponding StepResult.
    """
    # Generate unique expected step IDs (at least 1)
    expected_steps = draw(
        st.lists(step_id_strategy, min_size=1, max_size=10, unique=True)
    )

    # Pick a non-empty strict subset of expected steps to have results
    num_present = draw(st.integers(min_value=0, max_value=len(expected_steps) - 1))
    present_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(expected_steps) - 1),
            min_size=num_present,
            max_size=num_present,
            unique=True,
        )
    )
    present_step_ids = {expected_steps[i] for i in present_indices}

    # Create StepResults only for present steps
    step_results = []
    for step_id in present_step_ids:
        status = draw(st.sampled_from([StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.TIMEOUT]))
        result = StepResult(
            step_id=step_id,
            status=status,
            result="data",
            duration_ms=draw(st.floats(min_value=0, max_value=10000)),
        )
        step_results.append(result)

    return step_results, expected_steps


@st.composite
def mixed_aggregation_scenario(draw: st.DrawFn):
    """Generate a scenario with random expected steps and random results.

    Some results may be for expected steps, some may be extra.
    Returns (step_results, expected_steps).
    """
    expected_steps = draw(
        st.lists(step_id_strategy, min_size=0, max_size=10, unique=True)
    )

    # Generate some results: a subset of expected + possibly some extra
    extra_ids = draw(
        st.lists(step_id_strategy, min_size=0, max_size=5, unique=True)
    )

    all_possible_ids = list(set(expected_steps) | set(extra_ids))
    if not all_possible_ids:
        return [], expected_steps

    # Pick a random subset to have results
    result_ids = draw(
        st.lists(
            st.sampled_from(all_possible_ids),
            min_size=0,
            max_size=len(all_possible_ids),
            unique=True,
        )
    )

    step_results = []
    for step_id in result_ids:
        status = draw(st.sampled_from([StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.TIMEOUT]))
        result = StepResult(
            step_id=step_id,
            status=status,
            result="data",
            duration_ms=draw(st.floats(min_value=0, max_value=10000)),
        )
        step_results.append(result)

    return step_results, expected_steps


# ============================================================
# Property 23: 结果聚合完整性
# ============================================================


@pytest.mark.property
class TestProperty23ResultAggregationCompleteness:
    """Property 23: 结果聚合完整性

    **Validates: Requirements 9.1, 9.2, 9.3**

    For any set of step results:
    - If all expected steps have results: is_partial=False, missing_steps=[]
    - If some expected steps are missing: is_partial=True, missing_steps lists the missing step_ids
    """

    @given(scenario=complete_aggregation_scenario())
    @settings(max_examples=100)
    def test_complete_results_yield_non_partial(
        self, scenario
    ) -> None:
        """When all expected steps have results, is_partial=False and missing_steps=[]."""
        step_results, expected_steps = scenario

        async def _run() -> None:
            aggregator = FanInAggregator()
            aggregated = await aggregator.aggregate(step_results, expected_steps)

            assert aggregated.is_partial is False, (
                f"Expected is_partial=False when all steps present. "
                f"Expected: {expected_steps}, "
                f"Got results for: {[r.step_id for r in step_results]}"
            )
            assert aggregated.missing_steps == [], (
                f"Expected no missing steps, got: {aggregated.missing_steps}"
            )
            # All expected steps should be in results
            result_ids = {r.step_id for r in aggregated.results}
            for step_id in expected_steps:
                assert step_id in result_ids, (
                    f"Expected step {step_id} in results"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(scenario=partial_aggregation_scenario())
    @settings(max_examples=100)
    def test_missing_results_yield_partial(
        self, scenario
    ) -> None:
        """When some expected steps are missing, is_partial=True and missing_steps is correct."""
        step_results, expected_steps = scenario

        received_ids = {r.step_id for r in step_results}
        expected_missing = {
            sid for sid in expected_steps if sid not in received_ids
        }

        # Only run if there are actually missing steps
        assume(len(expected_missing) > 0)

        async def _run() -> None:
            aggregator = FanInAggregator()
            aggregated = await aggregator.aggregate(step_results, expected_steps)

            assert aggregated.is_partial is True, (
                f"Expected is_partial=True when steps are missing. "
                f"Expected: {expected_steps}, "
                f"Got results for: {[r.step_id for r in step_results]}"
            )
            assert set(aggregated.missing_steps) == expected_missing, (
                f"Expected missing steps {expected_missing}, "
                f"got {set(aggregated.missing_steps)}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(scenario=mixed_aggregation_scenario())
    @settings(max_examples=100)
    def test_is_partial_iff_missing_steps_nonempty(
        self, scenario
    ) -> None:
        """is_partial is True if and only if missing_steps is non-empty."""
        step_results, expected_steps = scenario

        async def _run() -> None:
            aggregator = FanInAggregator()
            aggregated = await aggregator.aggregate(step_results, expected_steps)

            if aggregated.missing_steps:
                assert aggregated.is_partial is True, (
                    "is_partial should be True when missing_steps is non-empty"
                )
            else:
                assert aggregated.is_partial is False, (
                    "is_partial should be False when missing_steps is empty"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(scenario=mixed_aggregation_scenario())
    @settings(max_examples=100)
    def test_missing_steps_are_exactly_expected_minus_received(
        self, scenario
    ) -> None:
        """missing_steps = expected_steps - received step_ids."""
        step_results, expected_steps = scenario

        async def _run() -> None:
            aggregator = FanInAggregator()
            aggregated = await aggregator.aggregate(step_results, expected_steps)

            received_ids = {r.step_id for r in step_results}
            expected_missing = {
                sid for sid in expected_steps if sid not in received_ids
            }

            assert set(aggregated.missing_steps) == expected_missing, (
                f"missing_steps should be expected - received. "
                f"Expected missing: {expected_missing}, "
                f"Got: {set(aggregated.missing_steps)}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(scenario=mixed_aggregation_scenario())
    @settings(max_examples=100)
    def test_results_only_contain_expected_steps(
        self, scenario
    ) -> None:
        """Aggregated results should only contain results for expected steps."""
        step_results, expected_steps = scenario

        async def _run() -> None:
            aggregator = FanInAggregator()
            aggregated = await aggregator.aggregate(step_results, expected_steps)

            expected_set = set(expected_steps)
            for r in aggregated.results:
                assert r.step_id in expected_set, (
                    f"Result for step {r.step_id} should not be in aggregated "
                    f"results since it's not in expected_steps: {expected_steps}"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(scenario=mixed_aggregation_scenario())
    @settings(max_examples=100)
    def test_result_count_plus_missing_equals_expected(
        self, scenario
    ) -> None:
        """Number of results + number of missing steps = number of expected steps."""
        step_results, expected_steps = scenario

        async def _run() -> None:
            aggregator = FanInAggregator()
            aggregated = await aggregator.aggregate(step_results, expected_steps)

            total = len(aggregated.results) + len(aggregated.missing_steps)
            assert total == len(expected_steps), (
                f"results ({len(aggregated.results)}) + "
                f"missing ({len(aggregated.missing_steps)}) = {total}, "
                f"expected {len(expected_steps)}"
            )

        asyncio.get_event_loop().run_until_complete(_run())
