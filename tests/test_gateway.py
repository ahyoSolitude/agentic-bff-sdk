"""Unit tests for the MASGateway module."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Union
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.card_generator import CardGenerator, DefaultCardGenerator
from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher
from agentic_bff_sdk.gateway import DefaultMASGateway, MASGateway
from agentic_bff_sdk.models import (
    AggregatedResult,
    Card,
    CardOutput,
    CardType,
    ClarificationQuestion,
    DomainRequest,
    DomainResponse,
    ErrorResponse,
    ExecutionPlan,
    IntentResult,
    PlanStep,
    RequestMessage,
    ResponseMessage,
    SessionState,
    StepResult,
    StepStatus,
    SynthesisResult,
    TaskStatus,
)
from agentic_bff_sdk.planner import IMCPlanner
from agentic_bff_sdk.router import TopLevelRouter
from agentic_bff_sdk.session import SessionContext
from agentic_bff_sdk.synthesizer import Synthesizer


# ============================================================
# Helpers / Fixtures
# ============================================================


def _make_session_state(session_id: str = "sess1") -> SessionState:
    now = time.time()
    return SessionState(
        session_id=session_id,
        dialog_history=[],
        created_at=now,
        last_active_at=now,
    )


def _make_request(
    session_id: str = "sess1",
    channel_id: str = "ch1",
    user_input: str = "hello",
) -> RequestMessage:
    return RequestMessage(
        user_input=user_input,
        session_id=session_id,
        channel_id=channel_id,
    )


def _make_intent() -> IntentResult:
    return IntentResult(
        intent_type="query",
        confidence=0.95,
        parameters={"domain": "fund"},
    )


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan1",
        intent=_make_intent(),
        steps=[
            PlanStep(
                step_id="s1",
                domain="fund",
                action="query",
                parameters={},
            )
        ],
        created_at=time.time(),
    )


def _make_step_results() -> List[StepResult]:
    return [
        StepResult(
            step_id="s1",
            status=StepStatus.COMPLETED,
            result={"data": "fund_info"},
            duration_ms=100.0,
        )
    ]


def _make_aggregated() -> AggregatedResult:
    return AggregatedResult(
        results=_make_step_results(),
        missing_steps=[],
        is_partial=False,
    )


def _make_synthesis() -> SynthesisResult:
    return SynthesisResult(
        text_response="Here is your fund information.",
        quality_score=0.9,
    )


def _make_card_output() -> CardOutput:
    return CardOutput(
        cards=[
            Card(
                card_type=CardType.TEXT,
                title="Response",
                content={"text": "Here is your fund information."},
            )
        ],
        raw_text="Here is your fund information.",
    )


class MockRouter(TopLevelRouter):
    """Mock router for testing."""

    def __init__(self, result=None):
        self._result = result or _make_intent()

    async def route(self, user_input, session_state, mode=None):
        return self._result

    def register_priority_rule(self, rule):
        pass

    def register_fallback_handler(self, handler):
        pass


class MockPlanner(IMCPlanner):
    """Mock planner for testing."""

    def __init__(self, plan=None):
        self._plan = plan or _make_plan()

    async def generate_plan(self, intent, session_state, timeout_seconds=None):
        return self._plan

    async def persist_plan(self, plan):
        return plan.plan_id


class MockSynthesizer(Synthesizer):
    """Mock synthesizer for testing."""

    def __init__(self, result=None):
        self._result = result or _make_synthesis()

    async def synthesize(self, aggregated, session_state, quality_threshold=0.7):
        return self._result


class MockCardGenerator(CardGenerator):
    """Mock card generator for testing."""

    def __init__(self, result=None):
        self._result = result or _make_card_output()

    async def generate(self, synthesis, channel_capabilities):
        return self._result


def _build_gateway(
    router=None,
    planner=None,
    synthesizer=None,
    card_generator=None,
    config=None,
    domain_invoker=None,
) -> DefaultMASGateway:
    """Build a DefaultMASGateway with mock components."""
    session_ctx = SessionContext()
    return DefaultMASGateway(
        session_context=session_ctx,
        router=router or MockRouter(),
        planner=planner or MockPlanner(),
        dispatcher=ConcurrentDispatcher(),
        aggregator=FanInAggregator(),
        synthesizer=synthesizer or MockSynthesizer(),
        card_generator=card_generator or MockCardGenerator(),
        config=config or SDKConfig(),
        domain_invoker=domain_invoker,
    )


# ============================================================
# Request Validation Tests
# ============================================================


class TestRequestValidation:
    """Tests for request validation logic."""

    async def test_missing_session_id_returns_error(self) -> None:
        """Empty session_id should return ErrorResponse."""
        gw = _build_gateway()
        req = _make_request(session_id="")
        resp = await gw.handle_request(req)

        assert resp.error is not None
        assert resp.error.code == "REQ_MISSING_SESSION_ID"
        assert "session_id" in resp.error.message

    async def test_missing_channel_id_returns_error(self) -> None:
        """Empty channel_id should return ErrorResponse."""
        gw = _build_gateway()
        req = _make_request(channel_id="")
        resp = await gw.handle_request(req)

        assert resp.error is not None
        assert resp.error.code == "REQ_MISSING_CHANNEL_ID"
        assert "channel_id" in resp.error.message

    async def test_valid_request_no_error(self) -> None:
        """Valid request should not return an error."""
        async def mock_invoker(req: DomainRequest) -> DomainResponse:
            return DomainResponse(
                request_id=req.request_id,
                domain=req.domain,
                success=True,
                data={"result": "ok"},
            )

        gw = _build_gateway(domain_invoker=mock_invoker)
        req = _make_request()
        resp = await gw.handle_request(req)

        assert resp.error is None

    async def test_both_missing_returns_session_id_error_first(self) -> None:
        """When both are empty, session_id error takes precedence."""
        gw = _build_gateway()
        req = _make_request(session_id="", channel_id="")
        resp = await gw.handle_request(req)

        assert resp.error is not None
        assert resp.error.code == "REQ_MISSING_SESSION_ID"


# ============================================================
# Synchronous Pipeline Tests
# ============================================================


class TestSyncPipeline:
    """Tests for the synchronous request processing pipeline."""

    async def test_full_pipeline_returns_card_output(self) -> None:
        """Full pipeline should return a ResponseMessage with card content."""
        async def mock_invoker(req: DomainRequest) -> DomainResponse:
            return DomainResponse(
                request_id=req.request_id,
                domain=req.domain,
                success=True,
                data={"result": "ok"},
            )

        gw = _build_gateway(domain_invoker=mock_invoker)
        req = _make_request()
        resp = await gw.handle_request(req)

        assert resp.error is None
        assert resp.session_id == "sess1"
        assert resp.content is not None

    async def test_clarification_returned_when_ambiguous(self) -> None:
        """When router returns ClarificationQuestion, it should be forwarded."""
        clarification = ClarificationQuestion(
            question="Please clarify your intent.",
            candidates=[],
        )
        router = MockRouter(result=clarification)
        gw = _build_gateway(router=router)
        req = _make_request()
        resp = await gw.handle_request(req)

        assert resp.error is None
        assert resp.content is not None
        assert resp.content["question"] == "Please clarify your intent."

    async def test_pipeline_without_domain_invoker(self) -> None:
        """Pipeline without domain_invoker should still work (empty results)."""
        gw = _build_gateway(domain_invoker=None)
        req = _make_request()
        resp = await gw.handle_request(req)

        assert resp.error is None

    async def test_session_state_updated_after_request(self) -> None:
        """Session state should have dialog history updated after request."""
        async def mock_invoker(req: DomainRequest) -> DomainResponse:
            return DomainResponse(
                request_id=req.request_id,
                domain=req.domain,
                success=True,
                data={},
            )

        gw = _build_gateway(domain_invoker=mock_invoker)
        req = _make_request(user_input="test input")
        await gw.handle_request(req)

        # Check session was saved with dialog history
        state = await gw.session_context.get_or_create("sess1")
        assert len(state.dialog_history) >= 2
        assert state.dialog_history[-2]["role"] == "user"
        assert state.dialog_history[-2]["content"] == "test input"

    async def test_internal_error_returns_error_response(self) -> None:
        """Internal errors should be caught and returned as ErrorResponse."""

        class FailingRouter(TopLevelRouter):
            async def route(self, user_input, session_state, mode=None):
                raise RuntimeError("Router exploded")

            def register_priority_rule(self, rule):
                pass

            def register_fallback_handler(self, handler):
                pass

        gw = _build_gateway(router=FailingRouter())
        req = _make_request()
        resp = await gw.handle_request(req)

        assert resp.error is not None
        assert resp.error.code == "SYS_INTERNAL_ERROR"
        assert "Router exploded" in resp.error.message


# ============================================================
# Async Task Management Tests
# ============================================================


class TestAsyncTaskManagement:
    """Tests for async task submission, status, and retry."""

    async def test_submit_returns_task_id(self) -> None:
        """submit_async_task should return a non-empty task_id."""
        gw = _build_gateway()
        req = _make_request()
        task_id = await gw.submit_async_task(req, priority=1)

        assert task_id
        assert isinstance(task_id, str)

    async def test_task_status_after_submit(self) -> None:
        """Task should be PENDING or RUNNING after submission."""
        gw = _build_gateway()
        req = _make_request()
        task_id = await gw.submit_async_task(req, priority=1)

        status = await gw.get_task_status(task_id)
        assert status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETED)

    async def test_unknown_task_returns_failed(self) -> None:
        """Querying unknown task_id should return FAILED."""
        gw = _build_gateway()
        status = await gw.get_task_status("nonexistent")
        assert status == TaskStatus.FAILED

    async def test_task_completes_after_processing(self) -> None:
        """Task should eventually reach COMPLETED status."""
        async def mock_invoker(req: DomainRequest) -> DomainResponse:
            return DomainResponse(
                request_id=req.request_id,
                domain=req.domain,
                success=True,
                data={},
            )

        gw = _build_gateway(domain_invoker=mock_invoker)
        req = _make_request()
        task_id = await gw.submit_async_task(req, priority=0)

        # Wait for processing
        await asyncio.sleep(0.2)

        status = await gw.get_task_status(task_id)
        assert status == TaskStatus.COMPLETED

    async def test_retry_failed_task(self) -> None:
        """Retrying a failed task should re-enqueue it."""
        gw = _build_gateway()
        req = _make_request()
        task_id = await gw.submit_async_task(req, priority=0)

        # Wait for processing
        await asyncio.sleep(0.2)

        # Manually set to failed for testing retry
        entry = gw.tasks[task_id]
        entry.status = TaskStatus.FAILED
        entry.error = "test failure"

        result = await gw.retry_task(task_id)
        assert result is True

        # After retry, status should be PENDING
        assert entry.status == TaskStatus.PENDING

    async def test_retry_non_failed_task_returns_false(self) -> None:
        """Retrying a non-failed task should return False."""
        gw = _build_gateway()
        req = _make_request()
        task_id = await gw.submit_async_task(req, priority=0)

        # Wait for processing
        await asyncio.sleep(0.2)

        result = await gw.retry_task(task_id)
        assert result is False

    async def test_retry_unknown_task_returns_false(self) -> None:
        """Retrying an unknown task should return False."""
        gw = _build_gateway()
        result = await gw.retry_task("nonexistent")
        assert result is False


# ============================================================
# Plugin Registration Tests
# ============================================================


class TestPluginRegistration:
    """Tests for plugin registration."""

    def test_register_plugin(self) -> None:
        """Registering a plugin should store it."""
        gw = _build_gateway()
        mock_plugin = MagicMock()
        gw.register_plugin("router", mock_plugin)

        assert gw.plugins["router"] is mock_plugin

    def test_register_multiple_plugins(self) -> None:
        """Multiple plugins of different types can be registered."""
        gw = _build_gateway()
        gw.register_plugin("router", "router_plugin")
        gw.register_plugin("executor", "executor_plugin")
        gw.register_plugin("generator", "generator_plugin")

        assert len(gw.plugins) == 3

    def test_register_overwrites_same_type(self) -> None:
        """Registering same plugin type overwrites the previous one."""
        gw = _build_gateway()
        gw.register_plugin("router", "first")
        gw.register_plugin("router", "second")

        assert gw.plugins["router"] == "second"


# ============================================================
# Session Cleanup Tests
# ============================================================


class TestSessionCleanup:
    """Tests for session idle timeout cleanup."""

    async def test_cleanup_removes_expired_sessions(self) -> None:
        """Expired sessions should be cleaned up."""
        config = SDKConfig(session_idle_timeout_seconds=1)
        gw = _build_gateway(config=config)

        # Create a session
        state = await gw.session_context.get_or_create("old_session")
        # Manually set last_active_at to the past
        state.last_active_at = time.time() - 100
        await gw.session_context.save("old_session", state)

        cleaned = await gw.cleanup_idle_sessions()
        assert "old_session" in cleaned

    async def test_cleanup_preserves_active_sessions(self) -> None:
        """Active sessions should not be cleaned up."""
        config = SDKConfig(session_idle_timeout_seconds=3600)
        gw = _build_gateway(config=config)

        # Create a session
        await gw.session_context.get_or_create("active_session")

        cleaned = await gw.cleanup_idle_sessions()
        assert "active_session" not in cleaned


# ============================================================
# ABC Tests
# ============================================================


class TestMASGatewayABC:
    """Tests for the MASGateway abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        """MASGateway cannot be instantiated directly."""
        with pytest.raises(TypeError):
            MASGateway()
