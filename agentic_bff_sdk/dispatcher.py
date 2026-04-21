"""Concurrent Dispatcher — DAG-based concurrent scheduling engine.

Parses step dependencies from an ExecutionPlan, validates the DAG for
cycles, and dispatches steps concurrently using asyncio.  Each step is
executed via a pluggable *domain_invoker* callable, with per-step timeout
control and status-change callbacks.

State transitions per step: PENDING → RUNNING → {COMPLETED, FAILED, TIMEOUT}
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agentic_bff_sdk.models import (
    DomainRequest,
    DomainResponse,
    ExecutionPlan,
    PlanStep,
    StepResult,
    StepStatus,
)


# ============================================================
# StatusCallback ABC
# ============================================================


class StatusCallback(ABC):
    """Abstract callback notified on step status changes."""

    @abstractmethod
    async def on_status_change(
        self,
        step_id: str,
        old_status: StepStatus,
        new_status: StepStatus,
    ) -> None:
        """Called whenever a step transitions to a new status."""
        ...


# Type alias for the domain invoker callable used for testability.
# DomainGateway ABC will be created in task 10.1; until then callers
# pass an async callable with the same signature as DomainGateway.invoke.
DomainInvoker = Callable[[DomainRequest], Coroutine[Any, Any, DomainResponse]]


# ============================================================
# ConcurrentDispatcher
# ============================================================


class ConcurrentDispatcher:
    """DAG concurrent scheduling engine.

    Validates an ``ExecutionPlan`` for cyclic dependencies, then dispatches
    steps in topological order — steps whose dependencies have all completed
    are launched concurrently.  Per-step timeout is enforced via
    ``asyncio.wait_for``; timed-out steps are marked ``TIMEOUT`` and
    execution continues for independent steps.
    """

    # ----------------------------------------------------------
    # DAG validation
    # ----------------------------------------------------------

    def validate_dag(self, plan: ExecutionPlan) -> Optional[List[str]]:
        """Check the plan for cyclic dependencies.

        Returns:
            ``None`` if the DAG is valid (no cycles).
            A ``list[str]`` representing one cycle path if a cycle is found.
        """
        step_ids = {s.step_id for s in plan.steps}
        adj: Dict[str, List[str]] = defaultdict(list)
        for step in plan.steps:
            for dep in step.dependencies:
                if dep in step_ids:
                    adj[dep].append(step.step_id)

        # DFS-based cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {sid: WHITE for sid in step_ids}
        parent: Dict[str, Optional[str]] = {sid: None for sid in step_ids}

        def _dfs(node: str) -> Optional[List[str]]:
            color[node] = GRAY
            for neighbour in adj[node]:
                if color[neighbour] == GRAY:
                    # Back-edge found — reconstruct cycle path
                    cycle = [neighbour, node]
                    cur = node
                    while cur != neighbour:
                        cur = parent[cur]  # type: ignore[assignment]
                        if cur is None:
                            break
                        cycle.append(cur)
                    cycle.reverse()
                    return cycle
                if color[neighbour] == WHITE:
                    parent[neighbour] = node
                    result = _dfs(neighbour)
                    if result is not None:
                        return result
            color[node] = BLACK
            return None

        for sid in step_ids:
            if color[sid] == WHITE:
                cycle = _dfs(sid)
                if cycle is not None:
                    return cycle
        return None

    # ----------------------------------------------------------
    # Dispatch
    # ----------------------------------------------------------

    async def dispatch(
        self,
        plan: ExecutionPlan,
        domain_invoker: DomainInvoker,
        blackboard: Any = None,
        step_timeout_seconds: float = 30.0,
        callback: Optional[StatusCallback] = None,
    ) -> List[StepResult]:
        """Execute the plan's steps respecting DAG dependencies.

        Steps with all dependencies satisfied are launched concurrently.
        Each step is wrapped with ``asyncio.wait_for`` for timeout control.

        Args:
            plan: The execution plan containing steps and dependencies.
            domain_invoker: Async callable ``(DomainRequest) -> DomainResponse``.
            blackboard: Optional shared state (passed through but not used
                directly by the dispatcher).
            step_timeout_seconds: Per-step timeout in seconds.
            callback: Optional ``StatusCallback`` for status-change notifications.

        Returns:
            A list of ``StepResult`` for every step in the plan.
        """
        if not plan.steps:
            return []

        # Build lookup structures
        step_map: Dict[str, PlanStep] = {s.step_id: s for s in plan.steps}
        step_ids = set(step_map.keys())

        # Current status for each step
        statuses: Dict[str, StepStatus] = {
            sid: StepStatus.PENDING for sid in step_ids
        }
        results: Dict[str, StepResult] = {}

        # Dependents: step_id -> list of steps that depend on it
        dependents: Dict[str, List[str]] = defaultdict(list)
        for step in plan.steps:
            for dep in step.dependencies:
                if dep in step_ids:
                    dependents[dep].append(step.step_id)

        async def _set_status(step_id: str, new_status: StepStatus) -> None:
            old = statuses[step_id]
            statuses[step_id] = new_status
            if callback is not None:
                await callback.on_status_change(step_id, old, new_status)

        async def _execute_step(step: PlanStep) -> StepResult:
            """Run a single step with timeout control."""
            await _set_status(step.step_id, StepStatus.RUNNING)
            start = time.monotonic()

            request = DomainRequest(
                domain=step.domain,
                action=step.action,
                parameters=step.parameters,
                request_id=str(uuid.uuid4()),
            )

            try:
                response: DomainResponse = await asyncio.wait_for(
                    domain_invoker(request),
                    timeout=step_timeout_seconds,
                )
                elapsed_ms = (time.monotonic() - start) * 1000

                if response.success:
                    await _set_status(step.step_id, StepStatus.COMPLETED)
                    return StepResult(
                        step_id=step.step_id,
                        status=StepStatus.COMPLETED,
                        result=response.data,
                        duration_ms=elapsed_ms,
                    )
                else:
                    await _set_status(step.step_id, StepStatus.FAILED)
                    return StepResult(
                        step_id=step.step_id,
                        status=StepStatus.FAILED,
                        error=response.error or "Domain invocation failed",
                        duration_ms=elapsed_ms,
                    )

            except asyncio.TimeoutError:
                elapsed_ms = (time.monotonic() - start) * 1000
                await _set_status(step.step_id, StepStatus.TIMEOUT)
                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.TIMEOUT,
                    error=f"Step timed out after {step_timeout_seconds}s",
                    duration_ms=elapsed_ms,
                )
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                await _set_status(step.step_id, StepStatus.FAILED)
                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.FAILED,
                    error=str(exc),
                    duration_ms=elapsed_ms,
                )

        def _deps_satisfied(step: PlanStep) -> bool:
            """Check whether all dependencies of *step* are completed."""
            for dep in step.dependencies:
                if dep not in step_ids:
                    continue
                if statuses.get(dep) != StepStatus.COMPLETED:
                    return False
            return True

        def _deps_blocked(step: PlanStep) -> bool:
            """Check whether any dependency has failed or timed out."""
            for dep in step.dependencies:
                if dep not in step_ids:
                    continue
                s = statuses.get(dep)
                if s in (StepStatus.FAILED, StepStatus.TIMEOUT):
                    return True
            return False

        # Iterative batch scheduling
        pending = set(step_ids)

        while pending:
            # Identify steps that are blocked (dependency failed/timed out)
            blocked = set()
            for sid in list(pending):
                step = step_map[sid]
                if _deps_blocked(step):
                    blocked.add(sid)

            # Mark blocked steps as FAILED
            for sid in blocked:
                pending.discard(sid)
                await _set_status(sid, StepStatus.FAILED)
                results[sid] = StepResult(
                    step_id=sid,
                    status=StepStatus.FAILED,
                    error="Dependency failed or timed out",
                    duration_ms=0,
                )

            # Identify ready steps (all deps completed)
            ready = []
            for sid in list(pending):
                step = step_map[sid]
                if _deps_satisfied(step):
                    ready.append(step)

            if not ready:
                # No progress possible — remaining steps are blocked
                for sid in list(pending):
                    pending.discard(sid)
                    await _set_status(sid, StepStatus.FAILED)
                    results[sid] = StepResult(
                        step_id=sid,
                        status=StepStatus.FAILED,
                        error="Dependency failed or timed out",
                        duration_ms=0,
                    )
                break

            # Launch ready steps concurrently
            tasks = {
                asyncio.create_task(_execute_step(step)): step.step_id
                for step in ready
            }
            for sid in [s.step_id for s in ready]:
                pending.discard(sid)

            done, _ = await asyncio.wait(tasks.keys())
            for task in done:
                result = task.result()
                results[result.step_id] = result

        # Return results in the original step order
        return [results[s.step_id] for s in plan.steps if s.step_id in results]
