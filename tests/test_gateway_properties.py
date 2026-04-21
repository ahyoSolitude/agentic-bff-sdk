"""Property-based tests for the MASGateway module.

Uses Hypothesis to verify correctness properties of request validation,
async task round-trip, and task priority scheduling.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, strategies as st, assume

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.card_generator import CardGenerator
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
# Mock Components for Testing
# ============================================================


class _MockRouter(TopLevelRouter):
    async def route(self, user_input, session_state, mode=None):
        return IntentResult(
            intent_type="test", confidence=0.95, parameters={}
        )

    def register_priority_rule(self, rule):
        pass

    def register_fallback_handler(self, handler):
        pass


class _MockPlanner(IMCPlanner):
    async def generate_plan(self, intent, session_state, timeout_seconds=None):
        return ExecutionPlan(
            plan_id="plan1",
            intent=intent,
            steps=[
                PlanStep(
                    step_id="s1",
                    domain="test",
                    action="do",
                    parameters={},
                )
            ],
            created_at=time.time(),
        )

    async def persist_plan(self, plan):
        return plan.plan_id


class _MockSynthesizer(Synthesizer):
    async def synthesize(self, aggregated, session_state, quality_threshold=0.7):
        return SynthesisResult(
            text_response="Test response",
            quality_score=0.9,
        )


class _MockCardGenerator(CardGenerator):
    async def generate(self, synthesis, channel_capabilities):
        return CardOutput(
            cards=[
                Card(
                    card_type=CardType.TEXT,
                    title="Response",
                    content={"text": synthesis.text_response},
                )
            ],
            raw_text=synthesis.text_response,
        )


async def _mock_domain_invoker(req: DomainRequest) -> DomainResponse:
    return DomainResponse(
        request_id=req.request_id,
        domain=req.domain,
        success=True,
        data={"result": "ok"},
    )


def _build_test_gateway(config: Optional[SDKConfig] = None) -> DefaultMASGateway:
    """Build a DefaultMASGateway with mock components for property tests."""
    return DefaultMASGateway(
        session_context=SessionContext(),
        router=_MockRouter(),
        planner=_MockPlanner(),
        dispatcher=ConcurrentDispatcher(),
        aggregator=FanInAggregator(),
        synthesizer=_MockSynthesizer(),
        card_generator=_MockCardGenerator(),
        config=config or SDKConfig(),
        domain_invoker=_mock_domain_invoker,
    )


# ============================================================
# Hypothesis Strategies
# ============================================================

# Strategy for non-empty strings (valid identifiers)
non_empty_text = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=32,
)

# Strategy for user input text
user_input_text = st.text(min_size=1, max_size=100)

# Strategy for generating a RequestMessage with missing session_id
missing_session_id_strategy = st.builds(
    RequestMessage,
    user_input=user_input_text,
    session_id=st.just(""),
    channel_id=non_empty_text,
)

# Strategy for generating a RequestMessage with missing channel_id
missing_channel_id_strategy = st.builds(
    RequestMessage,
    user_input=user_input_text,
    session_id=non_empty_text,
    channel_id=st.just(""),
)

# Strategy for generating a RequestMessage with both missing
both_missing_strategy = st.builds(
    RequestMessage,
    user_input=user_input_text,
    session_id=st.just(""),
    channel_id=st.just(""),
)

# Strategy for generating a valid RequestMessage
valid_request_strategy = st.builds(
    RequestMessage,
    user_input=user_input_text,
    session_id=non_empty_text,
    channel_id=non_empty_text,
)

# Strategy for task priorities
priority_strategy = st.integers(min_value=0, max_value=100)


# ============================================================
# Property 2: 请求验证 — 缺失标识返回错误
# ============================================================


@pytest.mark.property
class TestProperty2RequestValidation:
    """Property 2: 请求验证 — 缺失标识返回错误

    **Validates: Requirements 1.4**

    For any RequestMessage where session_id or channel_id is empty,
    MASGateway should return a ResponseMessage with ErrorResponse
    and not create any SessionContext.
    """

    @given(request=missing_session_id_strategy)
    @settings(max_examples=100)
    def test_missing_session_id_returns_error(self, request: RequestMessage) -> None:
        """Missing session_id should always return ErrorResponse."""

        async def _run() -> None:
            gw = _build_test_gateway()
            resp = await gw.handle_request(request)

            assert resp.error is not None, (
                f"Expected ErrorResponse for empty session_id, got none. "
                f"Request: session_id='{request.session_id}', "
                f"channel_id='{request.channel_id}'"
            )
            assert resp.error.code == "REQ_MISSING_SESSION_ID", (
                f"Expected error code REQ_MISSING_SESSION_ID, "
                f"got {resp.error.code}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(request=missing_channel_id_strategy)
    @settings(max_examples=100)
    def test_missing_channel_id_returns_error(self, request: RequestMessage) -> None:
        """Missing channel_id should always return ErrorResponse."""

        async def _run() -> None:
            gw = _build_test_gateway()
            resp = await gw.handle_request(request)

            assert resp.error is not None, (
                f"Expected ErrorResponse for empty channel_id, got none. "
                f"Request: session_id='{request.session_id}', "
                f"channel_id='{request.channel_id}'"
            )
            assert resp.error.code == "REQ_MISSING_CHANNEL_ID", (
                f"Expected error code REQ_MISSING_CHANNEL_ID, "
                f"got {resp.error.code}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(request=both_missing_strategy)
    @settings(max_examples=100)
    def test_both_missing_returns_error(self, request: RequestMessage) -> None:
        """When both are empty, should return ErrorResponse (session_id first)."""

        async def _run() -> None:
            gw = _build_test_gateway()
            resp = await gw.handle_request(request)

            assert resp.error is not None, (
                "Expected ErrorResponse when both session_id and channel_id are empty"
            )
            # session_id is checked first
            assert resp.error.code == "REQ_MISSING_SESSION_ID"

        asyncio.get_event_loop().run_until_complete(_run())

    @given(request=st.one_of(
        missing_session_id_strategy,
        missing_channel_id_strategy,
        both_missing_strategy,
    ))
    @settings(max_examples=100)
    def test_no_session_created_on_validation_failure(
        self, request: RequestMessage
    ) -> None:
        """No SessionContext should be created when validation fails."""

        async def _run() -> None:
            gw = _build_test_gateway()
            resp = await gw.handle_request(request)

            assert resp.error is not None

            # Verify no session was created — the storage should be empty
            from agentic_bff_sdk.session import InMemoryStorageBackend

            storage = gw.session_context.storage
            if isinstance(storage, InMemoryStorageBackend):
                all_sessions = storage.list_all()
                # If session_id is empty, no session should exist for ""
                if not request.session_id:
                    assert "" not in all_sessions
                # If channel_id is empty but session_id is not,
                # no session should be created either
                if request.session_id and not request.channel_id:
                    assert request.session_id not in all_sessions

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 27: 异步任务提交与查询 Round-Trip
# ============================================================


@pytest.mark.property
class TestProperty27AsyncTaskRoundTrip:
    """Property 27: 异步任务提交与查询 Round-Trip

    **Validates: Requirements 11.1, 11.3**

    For any async task submission, should return a non-empty task_id,
    and querying that task_id should return a valid TaskStatus.
    """

    @given(
        request=valid_request_strategy,
        priority=priority_strategy,
    )
    @settings(max_examples=100)
    def test_submit_returns_non_empty_task_id(
        self, request: RequestMessage, priority: int
    ) -> None:
        """Submitting an async task should return a non-empty task_id."""

        async def _run() -> None:
            gw = _build_test_gateway()
            task_id = await gw.submit_async_task(request, priority=priority)

            assert task_id, (
                f"Expected non-empty task_id, got '{task_id}'"
            )
            assert isinstance(task_id, str)
            assert len(task_id) > 0

        asyncio.get_event_loop().run_until_complete(_run())

    @given(
        request=valid_request_strategy,
        priority=priority_strategy,
    )
    @settings(max_examples=100)
    def test_query_returns_valid_status(
        self, request: RequestMessage, priority: int
    ) -> None:
        """Querying a submitted task should return a valid TaskStatus."""

        async def _run() -> None:
            gw = _build_test_gateway()
            task_id = await gw.submit_async_task(request, priority=priority)

            # Allow some time for processing
            await asyncio.sleep(0.05)

            status = await gw.get_task_status(task_id)

            assert isinstance(status, TaskStatus), (
                f"Expected TaskStatus, got {type(status)}"
            )
            assert status in (
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
            ), f"Unexpected status: {status}"

        asyncio.get_event_loop().run_until_complete(_run())

    @given(
        request=valid_request_strategy,
        priority=priority_strategy,
    )
    @settings(max_examples=100)
    def test_unique_task_ids(
        self, request: RequestMessage, priority: int
    ) -> None:
        """Each submission should produce a unique task_id."""

        async def _run() -> None:
            gw = _build_test_gateway()
            id1 = await gw.submit_async_task(request, priority=priority)
            id2 = await gw.submit_async_task(request, priority=priority)

            assert id1 != id2, (
                f"Expected unique task_ids, got same: {id1}"
            )

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 28: 任务优先级调度顺序
# ============================================================


@pytest.mark.property
class TestProperty28TaskPriorityScheduling:
    """Property 28: 任务优先级调度顺序

    **Validates: Requirements 11.5**

    For any set of tasks with different priorities, higher priority
    tasks (lower priority number) should be executed before lower
    priority tasks.
    """

    @given(
        priorities=st.lists(
            st.integers(min_value=0, max_value=100),
            min_size=2,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_higher_priority_tasks_execute_first(
        self, priorities: List[int]
    ) -> None:
        """Tasks with lower priority numbers should be dequeued first."""
        # Ensure we have at least two distinct priorities
        assume(len(set(priorities)) >= 2)

        async def _run() -> None:
            # Track execution order using a list
            execution_order: List[int] = []

            class _OrderTrackingRouter(TopLevelRouter):
                """Router that records execution order by priority."""

                def __init__(self):
                    self._call_count = 0

                async def route(self, user_input, session_state, mode=None):
                    # Extract priority from user_input metadata
                    priority = int(user_input.split(":")[-1])
                    execution_order.append(priority)
                    return IntentResult(
                        intent_type="test", confidence=0.95, parameters={}
                    )

                def register_priority_rule(self, rule):
                    pass

                def register_fallback_handler(self, handler):
                    pass

            # Build gateway with order-tracking router
            gw = DefaultMASGateway(
                session_context=SessionContext(),
                router=_OrderTrackingRouter(),
                planner=_MockPlanner(),
                dispatcher=ConcurrentDispatcher(),
                aggregator=FanInAggregator(),
                synthesizer=_MockSynthesizer(),
                card_generator=_MockCardGenerator(),
                config=SDKConfig(),
                domain_invoker=_mock_domain_invoker,
            )

            # Submit all tasks without starting the worker yet
            # We do this by directly populating the queue and tasks dict
            task_ids = []
            for i, priority in enumerate(priorities):
                task_id = f"task_{i}"
                from agentic_bff_sdk.gateway import _AsyncTaskEntry

                entry = _AsyncTaskEntry(
                    task_id=task_id,
                    request=RequestMessage(
                        user_input=f"priority:{priority}",
                        session_id=f"sess_{i}",
                        channel_id="ch1",
                    ),
                    priority=priority,
                )
                gw._tasks[task_id] = entry
                await gw._task_queue.put((priority, time.time() + i * 0.001, task_id))
                task_ids.append(task_id)

            # Process the queue
            await gw._process_task_queue()

            # Verify execution order: should be sorted by priority (ascending)
            # For tasks that were actually executed
            if len(execution_order) >= 2:
                for i in range(len(execution_order) - 1):
                    assert execution_order[i] <= execution_order[i + 1], (
                        f"Priority order violated: {execution_order[i]} > "
                        f"{execution_order[i + 1]} in execution order "
                        f"{execution_order}"
                    )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(
        n_high=st.integers(min_value=1, max_value=5),
        n_low=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100)
    def test_all_high_priority_before_low_priority(
        self, n_high: int, n_low: int
    ) -> None:
        """All high-priority tasks should execute before any low-priority task."""

        async def _run() -> None:
            execution_order: List[str] = []

            class _TrackingRouter(TopLevelRouter):
                async def route(self, user_input, session_state, mode=None):
                    execution_order.append(user_input)
                    return IntentResult(
                        intent_type="test", confidence=0.95, parameters={}
                    )

                def register_priority_rule(self, rule):
                    pass

                def register_fallback_handler(self, handler):
                    pass

            gw = DefaultMASGateway(
                session_context=SessionContext(),
                router=_TrackingRouter(),
                planner=_MockPlanner(),
                dispatcher=ConcurrentDispatcher(),
                aggregator=FanInAggregator(),
                synthesizer=_MockSynthesizer(),
                card_generator=_MockCardGenerator(),
                config=SDKConfig(),
                domain_invoker=_mock_domain_invoker,
            )

            from agentic_bff_sdk.gateway import _AsyncTaskEntry

            # Add high priority tasks (priority=0)
            for i in range(n_high):
                task_id = f"high_{i}"
                entry = _AsyncTaskEntry(
                    task_id=task_id,
                    request=RequestMessage(
                        user_input=f"high_{i}",
                        session_id=f"sess_h{i}",
                        channel_id="ch1",
                    ),
                    priority=0,
                )
                gw._tasks[task_id] = entry
                await gw._task_queue.put((0, time.time() + i * 0.001, task_id))

            # Add low priority tasks (priority=10)
            for i in range(n_low):
                task_id = f"low_{i}"
                entry = _AsyncTaskEntry(
                    task_id=task_id,
                    request=RequestMessage(
                        user_input=f"low_{i}",
                        session_id=f"sess_l{i}",
                        channel_id="ch1",
                    ),
                    priority=10,
                )
                gw._tasks[task_id] = entry
                await gw._task_queue.put((10, time.time() + i * 0.001, task_id))

            # Process all tasks
            await gw._process_task_queue()

            # All high-priority tasks should appear before any low-priority task
            high_indices = [
                i for i, name in enumerate(execution_order)
                if name.startswith("high_")
            ]
            low_indices = [
                i for i, name in enumerate(execution_order)
                if name.startswith("low_")
            ]

            if high_indices and low_indices:
                max_high_idx = max(high_indices)
                min_low_idx = min(low_indices)
                assert max_high_idx < min_low_idx, (
                    f"High-priority tasks should all execute before low-priority. "
                    f"Execution order: {execution_order}"
                )

        asyncio.get_event_loop().run_until_complete(_run())
