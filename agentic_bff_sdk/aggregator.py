"""Fan-In Aggregator for collecting concurrent step results.

Implements the Async Fan-In pattern to collect results from multiple
concurrent execution steps, with timeout handling and partial result support.
"""

import asyncio
from typing import List

from agentic_bff_sdk.models import AggregatedResult, StepResult


class FanInAggregator:
    """Async Fan-In result aggregator.

    Collects results from multiple concurrent steps and determines
    completeness. If all expected steps have results, the aggregation
    is complete (is_partial=False). If some steps are missing,
    the aggregation is partial (is_partial=True) with missing step IDs listed.

    Supports a wait timeout: after the timeout expires, already-collected
    partial results are passed downstream with missing parts annotated.
    """

    async def aggregate(
        self,
        step_results: List[StepResult],
        expected_steps: List[str],
        wait_timeout_seconds: float = 60.0,
    ) -> AggregatedResult:
        """Aggregate multi-step execution results.

        Args:
            step_results: List of step results collected so far.
            expected_steps: List of expected step IDs that should be present.
            wait_timeout_seconds: Maximum time to wait for results (seconds).
                After timeout, partial results are returned with missing steps annotated.

        Returns:
            AggregatedResult with all collected results, missing step IDs,
            and a flag indicating whether the result is partial.
        """
        # Build a set of step IDs that have results
        received_step_ids = {r.step_id for r in step_results}

        # Determine which expected steps are missing
        missing_steps = [
            step_id
            for step_id in expected_steps
            if step_id not in received_step_ids
        ]

        # Filter results to only include those for expected steps
        relevant_results = [
            r for r in step_results if r.step_id in set(expected_steps)
        ]

        # Determine completeness
        is_partial = len(missing_steps) > 0

        return AggregatedResult(
            results=relevant_results,
            missing_steps=missing_steps,
            is_partial=is_partial,
        )

    async def aggregate_with_timeout(
        self,
        result_futures: List[asyncio.Task],
        expected_steps: List[str],
        wait_timeout_seconds: float = 60.0,
    ) -> AggregatedResult:
        """Aggregate results with timeout support for async tasks.

        Waits up to wait_timeout_seconds for all futures to complete.
        After timeout, collects whatever results are available and
        marks missing steps.

        Args:
            result_futures: List of asyncio Tasks that produce StepResult.
            expected_steps: List of expected step IDs.
            wait_timeout_seconds: Maximum wait time in seconds.

        Returns:
            AggregatedResult with collected results and missing step annotations.
        """
        collected_results: List[StepResult] = []

        # Wait for tasks with timeout
        done, pending = await asyncio.wait(
            result_futures,
            timeout=wait_timeout_seconds,
            return_when=asyncio.ALL_COMPLETED,
        )

        # Collect results from completed tasks
        for task in done:
            try:
                result = task.result()
                if isinstance(result, StepResult):
                    collected_results.append(result)
            except Exception:
                # Task raised an exception; skip it
                pass

        # Cancel pending tasks
        for task in pending:
            task.cancel()

        # Delegate to the core aggregate method
        return await self.aggregate(
            step_results=collected_results,
            expected_steps=expected_steps,
            wait_timeout_seconds=wait_timeout_seconds,
        )
