"""DAG dispatch runtime."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import defaultdict

from agentic_bff_sdk.domain import DomainGateway
from agentic_bff_sdk.events import EventPublisher, EventType, ExecutionEvent
from agentic_bff_sdk.models import (
    DomainCommand,
    ExecutionContext,
    ExecutionPlan,
    StepKind,
    StepResult,
    StepStatus,
)


class Dispatcher(ABC):
    @abstractmethod
    async def dispatch(self, plan: ExecutionPlan, context: ExecutionContext) -> list[StepResult]:
        ...


class DefaultDispatcher(Dispatcher):
    def __init__(
        self,
        domain_gateway: DomainGateway,
        *,
        event_publisher: EventPublisher | None = None,
        default_timeout_seconds: float = 60.0,
    ) -> None:
        self._domain_gateway = domain_gateway
        self._events = event_publisher
        self._default_timeout = default_timeout_seconds

    async def dispatch(self, plan: ExecutionPlan, context: ExecutionContext) -> list[StepResult]:
        cycle = find_cycle(plan)
        if cycle:
            return [
                StepResult(
                    step_id="plan",
                    status=StepStatus.FAILED,
                    error_message=f"Cycle detected: {' -> '.join(cycle)}",
                )
            ]

        step_map = {step.step_id: step for step in plan.steps}
        statuses = {step.step_id: StepStatus.PENDING for step in plan.steps}
        results: dict[str, StepResult] = {}
        pending = set(step_map)

        while pending:
            ready = [
                step
                for step_id, step in step_map.items()
                if step_id in pending
                and all(statuses.get(dep) == StepStatus.COMPLETED for dep in step.dependencies)
            ]
            blocked = [
                step
                for step_id, step in step_map.items()
                if step_id in pending
                and any(statuses.get(dep) in (StepStatus.FAILED, StepStatus.TIMEOUT, StepStatus.SKIPPED) for dep in step.dependencies)
            ]
            for step in blocked:
                pending.remove(step.step_id)
                statuses[step.step_id] = StepStatus.SKIPPED
                results[step.step_id] = StepResult(
                    step_id=step.step_id,
                    status=StepStatus.SKIPPED,
                    error_message="Dependency failed or timed out.",
                )
            if not ready:
                for step_id in list(pending):
                    pending.remove(step_id)
                    statuses[step_id] = StepStatus.SKIPPED
                    results[step_id] = StepResult(step_id=step_id, status=StepStatus.SKIPPED, error_message="No runnable dependencies.")
                break

            executed = await asyncio.gather(*(self._execute_step(step, context) for step in ready))
            for result in executed:
                pending.remove(result.step_id)
                statuses[result.step_id] = result.status
                results[result.step_id] = result

        return [results[step.step_id] for step in plan.steps if step.step_id in results]

    async def _execute_step(self, step, context: ExecutionContext) -> StepResult:  # type: ignore[no-untyped-def]
        start = time.monotonic()
        await self._publish(EventType.STEP_STARTED, context, step.step_id)
        try:
            if step.kind not in (StepKind.DOMAIN_CALL, StepKind.REACT_AGENT, StepKind.RULE_EVAL):
                return StepResult(step_id=step.step_id, status=StepStatus.COMPLETED, output={})
            command = DomainCommand(
                request_id=context.request.request_id,
                session_id=context.request.session_id,
                step_id=step.step_id,
                domain=step.domain or "default",
                action=step.action or step.kind.value,
                payload=step.parameters,
            )
            timeout = step.timeout_seconds or self._default_timeout
            domain_result = await asyncio.wait_for(
                self._domain_gateway.invoke(command, context),
                timeout=timeout,
            )
            duration = (time.monotonic() - start) * 1000
            if domain_result.success:
                await self._publish(EventType.STEP_COMPLETED, context, step.step_id, domain_result.output)
                return StepResult(step_id=step.step_id, status=StepStatus.COMPLETED, output=domain_result.output, duration_ms=duration)
            await self._publish(EventType.STEP_FAILED, context, step.step_id, {"error": domain_result.error_message})
            return StepResult(step_id=step.step_id, status=StepStatus.FAILED, error_message=domain_result.error_message, duration_ms=duration)
        except asyncio.TimeoutError:
            return StepResult(step_id=step.step_id, status=StepStatus.TIMEOUT, error_message="Step timed out.")
        except Exception as exc:
            return StepResult(step_id=step.step_id, status=StepStatus.FAILED, error_message=str(exc))

    async def _publish(
        self,
        event_type: EventType,
        context: ExecutionContext,
        step_id: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        if self._events is None:
            return
        await self._events.publish(
            ExecutionEvent.create(
                event_type,
                request_id=context.request.request_id,
                session_id=context.request.session_id,
                step_id=step_id,
                payload=payload,
            )
        )


def find_cycle(plan: ExecutionPlan) -> list[str] | None:
    step_ids = {step.step_id for step in plan.steps}
    graph: dict[str, list[str]] = defaultdict(list)
    for step in plan.steps:
        for dep in step.dependencies:
            if dep in step_ids:
                graph[dep].append(step.step_id)

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visiting.add(node)
        stack.append(node)
        for neighbour in graph[node]:
            if neighbour in visiting:
                return stack[stack.index(neighbour):] + [neighbour]
            if neighbour not in visited:
                cycle = dfs(neighbour)
                if cycle:
                    return cycle
        visiting.remove(node)
        visited.add(node)
        stack.pop()
        return None

    for step_id in step_ids:
        if step_id not in visited:
            cycle = dfs(step_id)
            if cycle:
                return cycle
    return None
