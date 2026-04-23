"""Step result aggregation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentic_bff_sdk.models import AggregatedResult, ExecutionPlan, StepResult, StepStatus


class Aggregator(ABC):
    @abstractmethod
    async def aggregate(self, plan: ExecutionPlan, results: list[StepResult]) -> AggregatedResult:
        ...


class DefaultAggregator(Aggregator):
    async def aggregate(self, plan: ExecutionPlan, results: list[StepResult]) -> AggregatedResult:
        by_step = {result.step_id: result for result in results}
        expected = [step.step_id for step in plan.steps]
        missing = [step_id for step_id in expected if step_id not in by_step]
        failed = [
            result.step_id
            for result in results
            if result.status in (StepStatus.FAILED, StepStatus.TIMEOUT, StepStatus.SKIPPED)
        ]
        return AggregatedResult(
            results=[by_step[step_id] for step_id in expected if step_id in by_step],
            missing_steps=missing,
            failed_steps=failed,
            is_partial=bool(missing or failed),
        )
