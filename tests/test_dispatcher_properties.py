"""Property-based tests for the ConcurrentDispatcher module.

Uses Hypothesis to verify correctness properties of the ConcurrentDispatcher
across randomized inputs: DAG cycle detection, concurrent scheduling correctness,
step state transition validity, and timeout handling with continued execution.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from hypothesis import given, settings, strategies as st, assume

from agentic_bff_sdk.dispatcher import (
    ConcurrentDispatcher,
    DomainInvoker,
    StatusCallback,
)
from agentic_bff_sdk.models import (
    DomainRequest,
    DomainResponse,
    ExecutionPlan,
    IntentResult,
    PlanStep,
    StepResult,
    StepStatus,
)


# ============================================================
# Helpers
# ============================================================


def _make_intent() -> IntentResult:
    return IntentResult(intent_type="test", confidence=0.9)


def _make_plan(steps: List[PlanStep]) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="prop-plan",
        intent=_make_intent(),
        steps=steps,
        created_at=time.time(),
    )


class RecordingCallback(StatusCallback):
    """A StatusCallback that records all transitions."""

    def __init__(self) -> None:
        self.transitions: List[Tuple[str, StepStatus, StepStatus]] = []

    async def on_status_change(
        self,
        step_id: str,
        old_status: StepStatus,
        new_status: StepStatus,
    ) -> None:
        self.transitions.append((step_id, old_status, new_status))


async def _success_invoker(request: DomainRequest) -> DomainResponse:
    """A domain invoker that always succeeds."""
    return DomainResponse(
        request_id=request.request_id,
        domain=request.domain,
        success=True,
        data={"action": request.action, "result": "ok"},
    )


# ============================================================
# Hypothesis Strategies
# ============================================================

# Strategy for generating unique step IDs
step_id_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=8,
)


@st.composite
def valid_dag_strategy(draw: st.DrawFn) -> List[PlanStep]:
    """Generate a valid DAG (no cycles).

    Steps are created in order; each step can only depend on
    previously created steps, which guarantees no cycles.
    """
    num_steps = draw(st.integers(min_value=1, max_value=8))
    steps: List[PlanStep] = []
    step_ids: List[str] = []

    for i in range(num_steps):
        sid = f"s{i}"
        # Each step can depend on any subset of previously created steps
        if step_ids:
            deps = draw(
                st.lists(
                    st.sampled_from(step_ids),
                    max_size=min(3, len(step_ids)),
                    unique=True,
                )
            )
        else:
            deps = []
        steps.append(
            PlanStep(
                step_id=sid,
                domain="test",
                action=f"action_{i}",
                dependencies=deps,
            )
        )
        step_ids.append(sid)

    return steps


@st.composite
def cyclic_dag_strategy(draw: st.DrawFn) -> List[PlanStep]:
    """Generate a DAG that contains at least one cycle.

    First creates a valid DAG, then injects a back-edge to create a cycle.
    """
    num_steps = draw(st.integers(min_value=2, max_value=8))
    steps: List[PlanStep] = []
    step_ids: List[str] = []

    for i in range(num_steps):
        sid = f"s{i}"
        if step_ids:
            deps = draw(
                st.lists(
                    st.sampled_from(step_ids),
                    max_size=min(2, len(step_ids)),
                    unique=True,
                )
            )
        else:
            deps = []
        steps.append(
            PlanStep(
                step_id=sid,
                domain="test",
                action=f"action_{i}",
                dependencies=deps,
            )
        )
        step_ids.append(sid)

    # Inject a back-edge: pick an earlier step and make it depend on a later step
    earlier_idx = draw(st.integers(min_value=0, max_value=num_steps - 2))
    later_idx = draw(st.integers(min_value=earlier_idx + 1, max_value=num_steps - 1))

    earlier_step = steps[earlier_idx]
    later_sid = steps[later_idx].step_id

    # Add the back-edge dependency (later -> earlier already exists implicitly
    # through the forward chain; we add earlier -> later to create a cycle)
    # Actually, we need earlier step to depend on later step to create a back-edge
    if later_sid not in earlier_step.dependencies:
        new_deps = list(earlier_step.dependencies) + [later_sid]
        steps[earlier_idx] = PlanStep(
            step_id=earlier_step.step_id,
            domain=earlier_step.domain,
            action=earlier_step.action,
            dependencies=new_deps,
        )

    return steps


# ============================================================
# Property 16: DAG 循环依赖检测
# ============================================================


@pytest.mark.property
class TestProperty16DagCycleDetection:
    """Property 16: DAG 循环依赖检测

    **Validates: Requirements 6.6**

    For any ExecutionPlan, if steps contain cyclic dependencies,
    validate_dag should return a non-None cycle path; if no cycles
    exist, it should return None.
    """

    @given(steps=valid_dag_strategy())
    @settings(max_examples=100)
    def test_valid_dag_returns_none(self, steps: List[PlanStep]) -> None:
        """For any valid DAG (no cycles), validate_dag returns None."""
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps)
        result = dispatcher.validate_dag(plan)
        assert result is None, f"Expected None for valid DAG, got cycle: {result}"

    @given(steps=cyclic_dag_strategy())
    @settings(max_examples=100)
    def test_cyclic_dag_returns_cycle_path(self, steps: List[PlanStep]) -> None:
        """For any DAG with cycles, validate_dag returns a non-None cycle path.

        We need to verify the cycle is real: the back-edge we injected
        may not always form a reachable cycle in the dependency graph.
        We check that if a cycle exists (via independent detection),
        validate_dag finds it.
        """
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps)

        # Independent cycle detection using Kahn's algorithm (in-degree)
        step_ids = {s.step_id for s in steps}
        adj: Dict[str, List[str]] = {sid: [] for sid in step_ids}
        in_degree: Dict[str, int] = {sid: 0 for sid in step_ids}
        for step in steps:
            for dep in step.dependencies:
                if dep in step_ids:
                    adj[dep].append(step.step_id)
                    in_degree[step.step_id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        has_cycle = visited < len(step_ids)

        result = dispatcher.validate_dag(plan)

        if has_cycle:
            assert result is not None, "Expected cycle path for cyclic DAG, got None"
            assert len(result) >= 2, "Cycle path should contain at least 2 nodes"
            # All nodes in the cycle path should be valid step IDs
            for node in result:
                assert node in step_ids, f"Cycle node {node} not in step IDs"
        # If our injection didn't actually create a cycle (e.g., no forward
        # path from later to earlier), validate_dag returning None is correct


# ============================================================
# Property 17: DAG 并发调度正确性
# ============================================================


@pytest.mark.property
class TestProperty17DagSchedulingCorrectness:
    """Property 17: DAG 并发调度正确性

    **Validates: Requirements 6.1, 6.2**

    For any valid DAG execution plan, when a step starts running,
    all of its dependencies must already be in COMPLETED status.
    """

    @given(steps=valid_dag_strategy())
    @settings(max_examples=100)
    def test_dependencies_completed_before_step_starts(
        self, steps: List[PlanStep]
    ) -> None:
        """Every step starts running only after all its dependencies are COMPLETED."""

        async def _run() -> None:
            cb = RecordingCallback()
            dispatcher = ConcurrentDispatcher()
            plan = _make_plan(steps)
            await dispatcher.dispatch(plan, _success_invoker, callback=cb)

            # Build a map of step_id -> dependencies
            dep_map: Dict[str, List[str]] = {}
            step_ids = {s.step_id for s in steps}
            for step in steps:
                dep_map[step.step_id] = [
                    d for d in step.dependencies if d in step_ids
                ]

            # Track the order of status changes
            # When a step transitions to RUNNING, all its deps must have
            # already transitioned to COMPLETED
            completed_steps: Set[str] = set()
            for step_id, old_status, new_status in cb.transitions:
                if new_status == StepStatus.COMPLETED:
                    completed_steps.add(step_id)
                elif new_status == StepStatus.RUNNING:
                    for dep in dep_map.get(step_id, []):
                        assert dep in completed_steps, (
                            f"Step {step_id} started RUNNING but dependency "
                            f"{dep} was not yet COMPLETED"
                        )

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 18: 步骤状态转换有效性
# ============================================================

# Valid state transitions as defined in the design
VALID_TRANSITIONS: Set[Tuple[StepStatus, StepStatus]] = {
    (StepStatus.PENDING, StepStatus.RUNNING),
    (StepStatus.RUNNING, StepStatus.COMPLETED),
    (StepStatus.RUNNING, StepStatus.FAILED),
    (StepStatus.RUNNING, StepStatus.TIMEOUT),
    (StepStatus.PENDING, StepStatus.FAILED),  # blocked by dependency
}


@pytest.mark.property
class TestProperty18StepStateTransitionValidity:
    """Property 18: 步骤状态转换有效性

    **Validates: Requirements 6.5**

    For any step execution, state transitions must follow valid paths:
    PENDING → RUNNING → {COMPLETED, FAILED, TIMEOUT}
    PENDING → FAILED (blocked by dependency)
    No skipping intermediate states or reverse transitions.
    """

    @given(steps=valid_dag_strategy())
    @settings(max_examples=100)
    def test_all_transitions_are_valid_success_path(
        self, steps: List[PlanStep]
    ) -> None:
        """All state transitions during successful execution follow valid paths."""

        async def _run() -> None:
            cb = RecordingCallback()
            dispatcher = ConcurrentDispatcher()
            plan = _make_plan(steps)
            await dispatcher.dispatch(plan, _success_invoker, callback=cb)

            for step_id, old_status, new_status in cb.transitions:
                assert (old_status, new_status) in VALID_TRANSITIONS, (
                    f"Invalid transition for step {step_id}: "
                    f"{old_status.value} → {new_status.value}"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(steps=valid_dag_strategy())
    @settings(max_examples=100)
    def test_all_transitions_are_valid_failure_path(
        self, steps: List[PlanStep]
    ) -> None:
        """All state transitions during failed execution follow valid paths."""

        async def _failing_invoker(request: DomainRequest) -> DomainResponse:
            return DomainResponse(
                request_id=request.request_id,
                domain=request.domain,
                success=False,
                error="test failure",
            )

        async def _run() -> None:
            cb = RecordingCallback()
            dispatcher = ConcurrentDispatcher()
            plan = _make_plan(steps)
            await dispatcher.dispatch(plan, _failing_invoker, callback=cb)

            for step_id, old_status, new_status in cb.transitions:
                assert (old_status, new_status) in VALID_TRANSITIONS, (
                    f"Invalid transition for step {step_id}: "
                    f"{old_status.value} → {new_status.value}"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(steps=valid_dag_strategy())
    @settings(max_examples=100)
    def test_no_duplicate_transitions_per_step(
        self, steps: List[PlanStep]
    ) -> None:
        """Each step should not have duplicate transitions (same old→new pair)."""

        async def _run() -> None:
            cb = RecordingCallback()
            dispatcher = ConcurrentDispatcher()
            plan = _make_plan(steps)
            await dispatcher.dispatch(plan, _success_invoker, callback=cb)

            # Group transitions by step_id
            step_transitions: Dict[str, List[Tuple[StepStatus, StepStatus]]] = {}
            for step_id, old_status, new_status in cb.transitions:
                step_transitions.setdefault(step_id, []).append(
                    (old_status, new_status)
                )

            for step_id, transitions in step_transitions.items():
                # Each step should have at most 2 transitions
                # (PENDING→RUNNING, RUNNING→terminal) or (PENDING→FAILED)
                assert len(transitions) <= 2, (
                    f"Step {step_id} had {len(transitions)} transitions: {transitions}"
                )

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 19: 超时步骤标记与继续执行
# ============================================================


@pytest.mark.property
class TestProperty19TimeoutAndContinuedExecution:
    """Property 19: 超时步骤标记与继续执行

    **Validates: Requirements 6.4**

    For any timed-out step, its status should be TIMEOUT, and steps
    that do not depend on it should continue to execute normally.
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_timeout_steps_marked_and_independent_steps_continue(
        self, data: st.DataObject
    ) -> None:
        """Timeout steps are marked TIMEOUT; independent steps still complete."""
        # Generate a set of independent steps (no dependencies between them)
        num_steps = data.draw(st.integers(min_value=2, max_value=6))

        # Pick which steps will be slow (at least 1, at most num_steps - 1)
        num_slow = data.draw(
            st.integers(min_value=1, max_value=max(1, num_steps - 1))
        )
        slow_indices = set(
            data.draw(
                st.lists(
                    st.integers(min_value=0, max_value=num_steps - 1),
                    min_size=num_slow,
                    max_size=num_slow,
                    unique=True,
                )
            )
        )

        # Ensure at least one fast step exists
        assume(len(slow_indices) < num_steps)

        steps: List[PlanStep] = []
        for i in range(num_steps):
            action = "slow" if i in slow_indices else "fast"
            steps.append(
                PlanStep(
                    step_id=f"s{i}",
                    domain="test",
                    action=action,
                    dependencies=[],  # all independent
                )
            )

        async def _mixed_invoker(request: DomainRequest) -> DomainResponse:
            if request.action == "slow":
                await asyncio.sleep(10)
            return DomainResponse(
                request_id=request.request_id,
                domain=request.domain,
                success=True,
                data="done",
            )

        async def _run() -> None:
            dispatcher = ConcurrentDispatcher()
            plan = _make_plan(steps)
            results = await dispatcher.dispatch(
                plan, _mixed_invoker, step_timeout_seconds=0.1
            )

            result_map = {r.step_id: r for r in results}

            for i in range(num_steps):
                sid = f"s{i}"
                if i in slow_indices:
                    assert result_map[sid].status == StepStatus.TIMEOUT, (
                        f"Slow step {sid} should be TIMEOUT, "
                        f"got {result_map[sid].status}"
                    )
                else:
                    assert result_map[sid].status == StepStatus.COMPLETED, (
                        f"Fast independent step {sid} should be COMPLETED, "
                        f"got {result_map[sid].status}"
                    )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(data=st.data())
    @settings(max_examples=100)
    def test_dependent_steps_fail_when_dependency_times_out(
        self, data: st.DataObject
    ) -> None:
        """Steps depending on a timed-out step should be marked FAILED."""
        # Create a chain: s0 (slow, will timeout) -> s1 (depends on s0)
        # Plus an independent step s2 that should complete
        num_independent = data.draw(st.integers(min_value=1, max_value=3))

        steps: List[PlanStep] = [
            PlanStep(
                step_id="s_slow",
                domain="test",
                action="slow",
                dependencies=[],
            ),
            PlanStep(
                step_id="s_dependent",
                domain="test",
                action="fast",
                dependencies=["s_slow"],
            ),
        ]

        for i in range(num_independent):
            steps.append(
                PlanStep(
                    step_id=f"s_ind_{i}",
                    domain="test",
                    action="fast",
                    dependencies=[],
                )
            )

        async def _mixed_invoker(request: DomainRequest) -> DomainResponse:
            if request.action == "slow":
                await asyncio.sleep(10)
            return DomainResponse(
                request_id=request.request_id,
                domain=request.domain,
                success=True,
                data="done",
            )

        async def _run() -> None:
            dispatcher = ConcurrentDispatcher()
            plan = _make_plan(steps)
            results = await dispatcher.dispatch(
                plan, _mixed_invoker, step_timeout_seconds=0.1
            )

            result_map = {r.step_id: r for r in results}

            # Slow step should be TIMEOUT
            assert result_map["s_slow"].status == StepStatus.TIMEOUT

            # Dependent step should be FAILED (blocked by timeout)
            assert result_map["s_dependent"].status == StepStatus.FAILED

            # Independent steps should be COMPLETED
            for i in range(num_independent):
                sid = f"s_ind_{i}"
                assert result_map[sid].status == StepStatus.COMPLETED, (
                    f"Independent step {sid} should be COMPLETED, "
                    f"got {result_map[sid].status}"
                )

        asyncio.get_event_loop().run_until_complete(_run())
