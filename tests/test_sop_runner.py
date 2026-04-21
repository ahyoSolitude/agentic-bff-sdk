"""Unit tests for the BatchSOPRunner module."""

import time
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.config import InteractionScene, SOPDefinition
from agentic_bff_sdk.models import ExecutionPlan, IntentResult, PlanStep
from agentic_bff_sdk.sop_runner import (
    BatchSOPRunner,
    DefaultBatchSOPRunner,
    MAX_RETRY_ATTEMPTS,
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


def _make_sop(
    sop_id: str = "sop-1",
    steps: list[Dict[str, Any]] | None = None,
    exception_policies: Dict[str, str] | None = None,
    dialog_templates: Dict[InteractionScene, str] | None = None,
) -> SOPDefinition:
    return SOPDefinition(
        sop_id=sop_id,
        name="Test SOP",
        steps=steps or [],
        exception_policies=exception_policies or {},
        dialog_templates=dialog_templates or {},
    )


async def _success_executor(
    domain: str,
    action: str,
    parameters: Dict[str, Any],
    blackboard: Blackboard,
) -> Dict[str, Any]:
    return {
        "domain": domain,
        "action": action,
        "status": "completed",
        "data": {"result": f"{domain}.{action} done"},
    }


def _make_failing_executor(
    error_cls: type = ValueError,
    message: str = "step failed",
    fail_count: int | None = None,
):
    """Create an executor that fails a given number of times then succeeds.

    If fail_count is None, it always fails.
    """
    call_count = {"n": 0}

    async def executor(
        domain: str,
        action: str,
        parameters: Dict[str, Any],
        blackboard: Blackboard,
    ) -> Dict[str, Any]:
        call_count["n"] += 1
        if fail_count is None or call_count["n"] <= fail_count:
            raise error_cls(message)
        return {
            "domain": domain,
            "action": action,
            "status": "completed",
            "data": "recovered",
        }

    return executor, call_count


# ============================================================
# BatchSOPRunner ABC Tests
# ============================================================


class TestBatchSOPRunnerABC:
    """Tests verifying BatchSOPRunner is a proper ABC."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            BatchSOPRunner()  # type: ignore[abstract]


# ============================================================
# DefaultBatchSOPRunner Initialization Tests
# ============================================================


class TestDefaultBatchSOPRunnerInit:
    """Tests for DefaultBatchSOPRunner initialization."""

    def test_default_step_executor(self) -> None:
        runner = DefaultBatchSOPRunner()
        assert runner._step_executor is not None

    def test_custom_step_executor(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        assert runner._step_executor is _success_executor


# ============================================================
# Dialog Template Selection Tests
# ============================================================


class TestDialogTemplateSelection:
    """Tests for interaction scene dialog template selection."""

    def test_select_phone_template(self) -> None:
        sop = _make_sop(
            dialog_templates={
                InteractionScene.PHONE: "Hello, this is a phone call.",
                InteractionScene.ONLINE: "Welcome online.",
            }
        )
        runner = DefaultBatchSOPRunner()
        template = runner.select_dialog_template(sop, InteractionScene.PHONE)
        assert template == "Hello, this is a phone call."

    def test_select_online_template(self) -> None:
        sop = _make_sop(
            dialog_templates={
                InteractionScene.PHONE: "Phone template",
                InteractionScene.ONLINE: "Online template",
            }
        )
        runner = DefaultBatchSOPRunner()
        template = runner.select_dialog_template(sop, InteractionScene.ONLINE)
        assert template == "Online template"

    def test_select_face_to_face_template(self) -> None:
        sop = _make_sop(
            dialog_templates={
                InteractionScene.FACE_TO_FACE: "Face to face template",
            }
        )
        runner = DefaultBatchSOPRunner()
        template = runner.select_dialog_template(sop, InteractionScene.FACE_TO_FACE)
        assert template == "Face to face template"

    def test_missing_template_returns_none(self) -> None:
        sop = _make_sop(dialog_templates={InteractionScene.PHONE: "Phone only"})
        runner = DefaultBatchSOPRunner()
        template = runner.select_dialog_template(sop, InteractionScene.ONLINE)
        assert template is None

    def test_empty_templates_returns_none(self) -> None:
        sop = _make_sop(dialog_templates={})
        runner = DefaultBatchSOPRunner()
        template = runner.select_dialog_template(sop, InteractionScene.PHONE)
        assert template is None


# ============================================================
# Execute — Basic Flow Tests
# ============================================================


class TestExecuteBasicFlow:
    """Tests for the basic execute flow."""

    async def test_empty_sop_returns_empty_results(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(steps=[])
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)
        assert results == []

    async def test_single_step_execution(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(
            steps=[{"domain": "finance", "action": "query", "parameters": {"x": 1}}]
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        assert results[0]["domain"] == "finance"
        assert results[0]["action"] == "query"
        assert results[0]["status"] == "completed"

    async def test_multiple_steps_execution(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(
            steps=[
                {"domain": "d1", "action": "a1", "parameters": {}},
                {"domain": "d2", "action": "a2", "parameters": {}},
                {"domain": "d3", "action": "a3", "parameters": {}},
            ]
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.PHONE, bb)

        assert len(results) == 3
        for i, r in enumerate(results):
            assert r["domain"] == f"d{i + 1}"
            assert r["action"] == f"a{i + 1}"

    async def test_step_missing_fields_uses_defaults(self) -> None:
        """Steps with missing domain/action/parameters should use defaults."""
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(steps=[{}])
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        assert results[0]["domain"] == ""
        assert results[0]["action"] == ""


# ============================================================
# Blackboard Write Tests
# ============================================================


class TestBlackboardWrite:
    """Tests for step results being written to Blackboard."""

    async def test_step_results_written_to_blackboard(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(
            sop_id="my-sop",
            steps=[
                {"domain": "d1", "action": "a1"},
                {"domain": "d2", "action": "a2"},
            ],
        )
        bb = Blackboard()

        await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        result_0 = await bb.get("sop_my-sop_step_0")
        result_1 = await bb.get("sop_my-sop_step_1")

        assert result_0 is not None
        assert result_0["domain"] == "d1"
        assert result_1 is not None
        assert result_1["domain"] == "d2"

    async def test_dialog_template_written_to_blackboard(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(
            sop_id="sop-tmpl",
            steps=[{"domain": "d1", "action": "a1"}],
            dialog_templates={InteractionScene.PHONE: "Phone greeting"},
        )
        bb = Blackboard()

        await runner.execute(plan, sop, InteractionScene.PHONE, bb)

        template = await bb.get("sop_sop-tmpl_dialog_template")
        assert template == "Phone greeting"

    async def test_no_dialog_template_when_scene_not_configured(self) -> None:
        runner = DefaultBatchSOPRunner(step_executor=_success_executor)
        plan = _make_plan()
        sop = _make_sop(
            sop_id="sop-no-tmpl",
            steps=[{"domain": "d1", "action": "a1"}],
            dialog_templates={InteractionScene.PHONE: "Phone only"},
        )
        bb = Blackboard()

        await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        template = await bb.get("sop_sop-no-tmpl_dialog_template")
        assert template is None


# ============================================================
# Exception Policy — Skip Tests
# ============================================================


class TestExceptionPolicySkip:
    """Tests for the skip exception handling policy."""

    async def test_skip_policy_continues_execution(self) -> None:
        failing_exec, _ = _make_failing_executor(ValueError, "bad value")
        runner = DefaultBatchSOPRunner(step_executor=failing_exec)
        plan = _make_plan()
        sop = _make_sop(
            steps=[
                {"domain": "d1", "action": "a1"},
                {"domain": "d2", "action": "a2"},
            ],
            exception_policies={"ValueError": "skip"},
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 2
        assert results[0]["status"] == "skipped"
        assert results[0]["policy_applied"] == "skip"
        assert "bad value" in results[0]["error"]
        # Second step also fails with skip
        assert results[1]["status"] == "skipped"

    async def test_default_policy_is_skip(self) -> None:
        """When no policy is configured for the error type, default to skip."""
        failing_exec, _ = _make_failing_executor(RuntimeError, "unknown error")
        runner = DefaultBatchSOPRunner(step_executor=failing_exec)
        plan = _make_plan()
        sop = _make_sop(
            steps=[{"domain": "d1", "action": "a1"}],
            exception_policies={},  # No policies configured
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert results[0]["policy_applied"] == "skip"


# ============================================================
# Exception Policy — Retry Tests
# ============================================================


class TestExceptionPolicyRetry:
    """Tests for the retry exception handling policy."""

    async def test_retry_succeeds_on_second_attempt(self) -> None:
        """Retry should succeed if the executor recovers within MAX_RETRY_ATTEMPTS."""
        # First call (original) fails, then first retry (call #2) also fails,
        # but the executor succeeds on call #3 (second retry).
        # fail_count=2 means calls 1 and 2 fail, call 3 succeeds.
        failing_exec, call_count = _make_failing_executor(
            ValueError, "transient", fail_count=2
        )
        runner = DefaultBatchSOPRunner(step_executor=failing_exec)
        plan = _make_plan()
        sop = _make_sop(
            steps=[{"domain": "d1", "action": "a1"}],
            exception_policies={"ValueError": "retry"},
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        assert results[0]["status"] == "completed"
        assert results[0]["data"] == "recovered"
        # Original call (1) + retry attempts (2) = 3 total calls
        assert call_count["n"] == 3

    async def test_retry_exhausted_returns_failed(self) -> None:
        """When all retries are exhausted, the step should be marked as failed."""
        failing_exec, call_count = _make_failing_executor(ValueError, "persistent")
        runner = DefaultBatchSOPRunner(step_executor=failing_exec)
        plan = _make_plan()
        sop = _make_sop(
            steps=[{"domain": "d1", "action": "a1"}],
            exception_policies={"ValueError": "retry"},
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        assert results[0]["status"] == "failed"
        assert results[0]["policy_applied"] == "retry_exhausted"
        # Original call (1) + MAX_RETRY_ATTEMPTS retries
        assert call_count["n"] == 1 + MAX_RETRY_ATTEMPTS

    async def test_retry_max_attempts_is_three(self) -> None:
        assert MAX_RETRY_ATTEMPTS == 3


# ============================================================
# Exception Policy — Rollback Tests
# ============================================================


class TestExceptionPolicyRollback:
    """Tests for the rollback exception handling policy."""

    async def test_rollback_raises_runtime_error(self) -> None:
        failing_exec, _ = _make_failing_executor(TypeError, "type mismatch")
        runner = DefaultBatchSOPRunner(step_executor=failing_exec)
        plan = _make_plan()
        sop = _make_sop(
            steps=[{"domain": "d1", "action": "a1"}],
            exception_policies={"TypeError": "rollback"},
        )
        bb = Blackboard()

        with pytest.raises(RuntimeError, match="Rollback triggered at step 0"):
            await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

    async def test_rollback_stops_subsequent_steps(self) -> None:
        """Rollback on first step should prevent second step from executing."""
        call_log: list[str] = []

        async def tracking_executor(
            domain: str,
            action: str,
            parameters: Dict[str, Any],
            blackboard: Blackboard,
        ) -> Dict[str, Any]:
            call_log.append(f"{domain}.{action}")
            if domain == "d1":
                raise TypeError("fail on d1")
            return {"domain": domain, "action": action, "status": "completed"}

        runner = DefaultBatchSOPRunner(step_executor=tracking_executor)
        plan = _make_plan()
        sop = _make_sop(
            steps=[
                {"domain": "d1", "action": "a1"},
                {"domain": "d2", "action": "a2"},
            ],
            exception_policies={"TypeError": "rollback"},
        )
        bb = Blackboard()

        with pytest.raises(RuntimeError):
            await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        # Only the first step should have been called
        assert call_log == ["d1.a1"]


# ============================================================
# Default Step Executor Tests
# ============================================================


class TestDefaultStepExecutor:
    """Tests for the default placeholder step executor."""

    async def test_default_executor_returns_completed(self) -> None:
        runner = DefaultBatchSOPRunner()
        plan = _make_plan()
        sop = _make_sop(steps=[{"domain": "test", "action": "ping"}])
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        assert results[0]["status"] == "completed"
        assert results[0]["domain"] == "test"
        assert results[0]["action"] == "ping"


# ============================================================
# Mixed Policy Tests
# ============================================================


class TestMixedPolicies:
    """Tests for scenarios with multiple exception types and policies."""

    async def test_different_policies_for_different_errors(self) -> None:
        """Different error types should trigger different policies."""
        call_index = {"n": 0}

        async def mixed_executor(
            domain: str,
            action: str,
            parameters: Dict[str, Any],
            blackboard: Blackboard,
        ) -> Dict[str, Any]:
            call_index["n"] += 1
            if action == "a1":
                raise ValueError("val error")
            if action == "a2":
                raise KeyError("key error")
            return {"domain": domain, "action": action, "status": "completed"}

        runner = DefaultBatchSOPRunner(step_executor=mixed_executor)
        plan = _make_plan()
        sop = _make_sop(
            steps=[
                {"domain": "d1", "action": "a1"},
                {"domain": "d2", "action": "a2"},
                {"domain": "d3", "action": "a3"},
            ],
            exception_policies={
                "ValueError": "skip",
                "KeyError": "skip",
            },
        )
        bb = Blackboard()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 3
        assert results[0]["status"] == "skipped"
        assert results[1]["status"] == "skipped"
        assert results[2]["status"] == "completed"
