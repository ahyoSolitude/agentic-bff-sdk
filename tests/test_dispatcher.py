"""Unit tests for the ConcurrentDispatcher module."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentic_bff_sdk.blackboard import Blackboard
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


def _make_plan(steps: list[PlanStep] | None = None) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-1",
        intent=_make_intent(),
        steps=steps or [],
        created_at=time.time(),
    )


def _make_step(
    step_id: str,
    domain: str = "test",
    action: str = "do",
    dependencies: list[str] | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        domain=domain,
        action=action,
        dependencies=dependencies or [],
    )


async def _success_invoker(request: DomainRequest) -> DomainResponse:
    """A domain invoker that always succeeds."""
    return DomainResponse(
        request_id=request.request_id,
        domain=request.domain,
        success=True,
        data={"action": request.action, "result": "ok"},
    )


async def _failure_invoker(request: DomainRequest) -> DomainResponse:
    """A domain invoker that always returns a failure response."""
    return DomainResponse(
        request_id=request.request_id,
        domain=request.domain,
        success=False,
        error="domain error",
    )


async def _slow_invoker(request: DomainRequest) -> DomainResponse:
    """A domain invoker that sleeps for 5 seconds (for timeout tests)."""
    await asyncio.sleep(5)
    return DomainResponse(
        request_id=request.request_id,
        domain=request.domain,
        success=True,
        data="slow result",
    )


async def _exception_invoker(request: DomainRequest) -> DomainResponse:
    """A domain invoker that raises an exception."""
    raise RuntimeError("unexpected crash")


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


# ============================================================
# validate_dag Tests
# ============================================================


class TestValidateDAG:
    """Tests for ConcurrentDispatcher.validate_dag."""

    def test_empty_plan_is_valid(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[])
        assert dispatcher.validate_dag(plan) is None

    def test_single_step_no_deps_is_valid(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        assert dispatcher.validate_dag(plan) is None

    def test_linear_chain_is_valid(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
                _make_step("s3", dependencies=["s2"]),
            ]
        )
        assert dispatcher.validate_dag(plan) is None

    def test_diamond_dag_is_valid(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
                _make_step("s3", dependencies=["s1"]),
                _make_step("s4", dependencies=["s2", "s3"]),
            ]
        )
        assert dispatcher.validate_dag(plan) is None

    def test_self_loop_detected(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1", dependencies=["s1"])])
        cycle = dispatcher.validate_dag(plan)
        assert cycle is not None
        assert "s1" in cycle

    def test_two_node_cycle_detected(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1", dependencies=["s2"]),
                _make_step("s2", dependencies=["s1"]),
            ]
        )
        cycle = dispatcher.validate_dag(plan)
        assert cycle is not None
        assert "s1" in cycle
        assert "s2" in cycle

    def test_three_node_cycle_detected(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1", dependencies=["s3"]),
                _make_step("s2", dependencies=["s1"]),
                _make_step("s3", dependencies=["s2"]),
            ]
        )
        cycle = dispatcher.validate_dag(plan)
        assert cycle is not None
        assert len(cycle) >= 2

    def test_parallel_steps_no_deps_is_valid(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2"),
                _make_step("s3"),
            ]
        )
        assert dispatcher.validate_dag(plan) is None

    def test_dependency_on_nonexistent_step_is_valid(self) -> None:
        """Dependencies referencing non-existent step_ids are ignored."""
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[_make_step("s1", dependencies=["nonexistent"])]
        )
        assert dispatcher.validate_dag(plan) is None


# ============================================================
# dispatch — Basic Flow Tests
# ============================================================


class TestDispatchBasicFlow:
    """Tests for the basic dispatch flow."""

    async def test_empty_plan_returns_empty(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[])
        results = await dispatcher.dispatch(plan, _success_invoker)
        assert results == []

    async def test_single_step_success(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        results = await dispatcher.dispatch(plan, _success_invoker)

        assert len(results) == 1
        assert results[0].step_id == "s1"
        assert results[0].status == StepStatus.COMPLETED
        assert results[0].result is not None
        assert results[0].duration_ms > 0

    async def test_multiple_independent_steps(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2"),
                _make_step("s3"),
            ]
        )
        results = await dispatcher.dispatch(plan, _success_invoker)

        assert len(results) == 3
        for r in results:
            assert r.status == StepStatus.COMPLETED

    async def test_linear_chain_execution(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
                _make_step("s3", dependencies=["s2"]),
            ]
        )
        results = await dispatcher.dispatch(plan, _success_invoker)

        assert len(results) == 3
        for r in results:
            assert r.status == StepStatus.COMPLETED

    async def test_diamond_dag_execution(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
                _make_step("s3", dependencies=["s1"]),
                _make_step("s4", dependencies=["s2", "s3"]),
            ]
        )
        results = await dispatcher.dispatch(plan, _success_invoker)

        assert len(results) == 4
        result_map = {r.step_id: r for r in results}
        for sid in ["s1", "s2", "s3", "s4"]:
            assert result_map[sid].status == StepStatus.COMPLETED


# ============================================================
# dispatch — Failure Handling Tests
# ============================================================


class TestDispatchFailureHandling:
    """Tests for failure handling in dispatch."""

    async def test_step_failure_propagates(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        results = await dispatcher.dispatch(plan, _failure_invoker)

        assert len(results) == 1
        assert results[0].step_id == "s1"
        assert results[0].status == StepStatus.FAILED
        assert results[0].error == "domain error"

    async def test_exception_in_invoker_marks_failed(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        results = await dispatcher.dispatch(plan, _exception_invoker)

        assert len(results) == 1
        assert results[0].status == StepStatus.FAILED
        assert "unexpected crash" in (results[0].error or "")

    async def test_dependent_step_fails_when_dependency_fails(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
            ]
        )
        results = await dispatcher.dispatch(plan, _failure_invoker)

        result_map = {r.step_id: r for r in results}
        assert result_map["s1"].status == StepStatus.FAILED
        assert result_map["s2"].status == StepStatus.FAILED
        assert "Dependency" in (result_map["s2"].error or "")

    async def test_independent_step_continues_after_failure(self) -> None:
        """Steps not depending on a failed step should still execute."""
        call_log: list[str] = []

        async def selective_invoker(request: DomainRequest) -> DomainResponse:
            call_log.append(request.action)
            if request.action == "fail_action":
                return DomainResponse(
                    request_id=request.request_id,
                    domain=request.domain,
                    success=False,
                    error="intentional failure",
                )
            return DomainResponse(
                request_id=request.request_id,
                domain=request.domain,
                success=True,
                data="ok",
            )

        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1", action="fail_action"),
                _make_step("s2", action="ok_action"),
            ]
        )
        results = await dispatcher.dispatch(plan, selective_invoker)

        result_map = {r.step_id: r for r in results}
        assert result_map["s1"].status == StepStatus.FAILED
        assert result_map["s2"].status == StepStatus.COMPLETED


# ============================================================
# dispatch — Timeout Tests
# ============================================================


class TestDispatchTimeout:
    """Tests for timeout handling in dispatch."""

    async def test_timeout_marks_step_as_timeout(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        results = await dispatcher.dispatch(
            plan, _slow_invoker, step_timeout_seconds=0.05
        )

        assert len(results) == 1
        assert results[0].step_id == "s1"
        assert results[0].status == StepStatus.TIMEOUT
        assert "timed out" in (results[0].error or "").lower()

    async def test_timeout_step_does_not_block_independent_steps(self) -> None:
        """Independent steps should complete even if one times out."""

        async def mixed_invoker(request: DomainRequest) -> DomainResponse:
            if request.action == "slow":
                await asyncio.sleep(5)
            return DomainResponse(
                request_id=request.request_id,
                domain=request.domain,
                success=True,
                data="done",
            )

        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1", action="slow"),
                _make_step("s2", action="fast"),
            ]
        )
        results = await dispatcher.dispatch(
            plan, mixed_invoker, step_timeout_seconds=0.05
        )

        result_map = {r.step_id: r for r in results}
        assert result_map["s1"].status == StepStatus.TIMEOUT
        assert result_map["s2"].status == StepStatus.COMPLETED

    async def test_dependent_step_fails_when_dependency_times_out(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
            ]
        )
        results = await dispatcher.dispatch(
            plan, _slow_invoker, step_timeout_seconds=0.05
        )

        result_map = {r.step_id: r for r in results}
        assert result_map["s1"].status == StepStatus.TIMEOUT
        assert result_map["s2"].status == StepStatus.FAILED


# ============================================================
# dispatch — StatusCallback Tests
# ============================================================


class TestDispatchCallback:
    """Tests for StatusCallback notifications."""

    async def test_callback_receives_transitions(self) -> None:
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        await dispatcher.dispatch(plan, _success_invoker, callback=cb)

        # Expect PENDING→RUNNING, RUNNING→COMPLETED
        assert len(cb.transitions) == 2
        assert cb.transitions[0] == ("s1", StepStatus.PENDING, StepStatus.RUNNING)
        assert cb.transitions[1] == ("s1", StepStatus.RUNNING, StepStatus.COMPLETED)

    async def test_callback_on_failure(self) -> None:
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        await dispatcher.dispatch(plan, _failure_invoker, callback=cb)

        assert len(cb.transitions) == 2
        assert cb.transitions[0] == ("s1", StepStatus.PENDING, StepStatus.RUNNING)
        assert cb.transitions[1] == ("s1", StepStatus.RUNNING, StepStatus.FAILED)

    async def test_callback_on_timeout(self) -> None:
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        await dispatcher.dispatch(
            plan, _slow_invoker, step_timeout_seconds=0.05, callback=cb
        )

        assert len(cb.transitions) == 2
        assert cb.transitions[0] == ("s1", StepStatus.PENDING, StepStatus.RUNNING)
        assert cb.transitions[1] == ("s1", StepStatus.RUNNING, StepStatus.TIMEOUT)

    async def test_callback_for_blocked_dependent(self) -> None:
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
            ]
        )
        await dispatcher.dispatch(plan, _failure_invoker, callback=cb)

        # s1: PENDING→RUNNING, RUNNING→FAILED
        # s2: PENDING→FAILED (blocked by s1)
        s2_transitions = [(s, o, n) for s, o, n in cb.transitions if s == "s2"]
        assert len(s2_transitions) == 1
        assert s2_transitions[0] == ("s2", StepStatus.PENDING, StepStatus.FAILED)


# ============================================================
# dispatch — State Transition Tests
# ============================================================


class TestStateTransitions:
    """Tests verifying valid state transitions."""

    async def test_successful_step_transitions(self) -> None:
        """PENDING → RUNNING → COMPLETED"""
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        await dispatcher.dispatch(plan, _success_invoker, callback=cb)

        statuses = [n for _, _, n in cb.transitions if _ == "s1" or True]
        s1_statuses = [n for s, _, n in cb.transitions if s == "s1"]
        assert s1_statuses == [StepStatus.RUNNING, StepStatus.COMPLETED]

    async def test_failed_step_transitions(self) -> None:
        """PENDING → RUNNING → FAILED"""
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        await dispatcher.dispatch(plan, _failure_invoker, callback=cb)

        s1_statuses = [n for s, _, n in cb.transitions if s == "s1"]
        assert s1_statuses == [StepStatus.RUNNING, StepStatus.FAILED]

    async def test_timeout_step_transitions(self) -> None:
        """PENDING → RUNNING → TIMEOUT"""
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        await dispatcher.dispatch(
            plan, _slow_invoker, step_timeout_seconds=0.05, callback=cb
        )

        s1_statuses = [n for s, _, n in cb.transitions if s == "s1"]
        assert s1_statuses == [StepStatus.RUNNING, StepStatus.TIMEOUT]

    async def test_blocked_step_transitions(self) -> None:
        """PENDING → FAILED (dependency failed)"""
        cb = RecordingCallback()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
            ]
        )
        await dispatcher.dispatch(plan, _failure_invoker, callback=cb)

        s2_statuses = [n for s, _, n in cb.transitions if s == "s2"]
        assert s2_statuses == [StepStatus.FAILED]


# ============================================================
# dispatch — Ordering Tests
# ============================================================


class TestDispatchOrdering:
    """Tests verifying execution order respects dependencies."""

    async def test_results_in_plan_order(self) -> None:
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1"),
                _make_step("s2", dependencies=["s1"]),
                _make_step("s3", dependencies=["s2"]),
            ]
        )
        results = await dispatcher.dispatch(plan, _success_invoker)

        assert [r.step_id for r in results] == ["s1", "s2", "s3"]

    async def test_dependency_completes_before_dependent_starts(self) -> None:
        """Verify that a dependent step only starts after its dependency completes."""
        execution_order: list[str] = []

        async def tracking_invoker(request: DomainRequest) -> DomainResponse:
            execution_order.append(f"start:{request.action}")
            await asyncio.sleep(0.01)
            execution_order.append(f"end:{request.action}")
            return DomainResponse(
                request_id=request.request_id,
                domain=request.domain,
                success=True,
                data="ok",
            )

        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(
            steps=[
                _make_step("s1", action="first"),
                _make_step("s2", action="second", dependencies=["s1"]),
            ]
        )
        await dispatcher.dispatch(plan, tracking_invoker)

        # "end:first" must appear before "start:second"
        end_first = execution_order.index("end:first")
        start_second = execution_order.index("start:second")
        assert end_first < start_second


# ============================================================
# dispatch — Blackboard Passthrough Test
# ============================================================


class TestBlackboardPassthrough:
    """Tests that blackboard parameter is accepted."""

    async def test_dispatch_accepts_blackboard(self) -> None:
        bb = Blackboard()
        dispatcher = ConcurrentDispatcher()
        plan = _make_plan(steps=[_make_step("s1")])
        results = await dispatcher.dispatch(
            plan, _success_invoker, blackboard=bb
        )
        assert len(results) == 1
        assert results[0].status == StepStatus.COMPLETED
