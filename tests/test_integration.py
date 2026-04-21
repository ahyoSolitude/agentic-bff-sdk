"""End-to-end integration tests for the Agentic BFF SDK.

Tests the full request processing pipeline from RequestMessage to CardOutput
using mock components, verifying:
- Complete synchronous pipeline flow
- Async task submission and query flow
- Error handling and degradation flow

Requirements: 1.1, 3.1, 4.1, 9.1, 10.1, 11.1
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Union

import pytest

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.card_generator import DefaultCardGenerator
from agentic_bff_sdk.config import OrchestrationConfig, SDKConfig
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher
from agentic_bff_sdk.gateway import DefaultMASGateway
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
from agentic_bff_sdk.sdk import create_sdk
from agentic_bff_sdk.session import SessionContext
from agentic_bff_sdk.synthesizer import Synthesizer


# ============================================================
# Mock Components for Integration Testing
# ============================================================


class MockLLMRouter(TopLevelRouter):
    """Mock router that simulates LLM-based intent recognition."""

    def __init__(
        self,
        intent_map: Optional[Dict[str, IntentResult]] = None,
        default_intent: Optional[IntentResult] = None,
        clarification_keywords: Optional[List[str]] = None,
    ) -> None:
        self._intent_map = intent_map or {}
        self._default_intent = default_intent or IntentResult(
            intent_type="general_query",
            confidence=0.95,
            parameters={},
        )
        self._clarification_keywords = clarification_keywords or []
        self._priority_rules: List[Dict[str, Any]] = []
        self._fallback_handler: Any = None

    async def route(
        self, user_input: str, session_state: SessionState, mode=None
    ) -> Union[IntentResult, ClarificationQuestion]:
        # Check clarification keywords
        for keyword in self._clarification_keywords:
            if keyword in user_input.lower():
                return ClarificationQuestion(
                    question="Could you please clarify your request?",
                    candidates=[
                        IntentResult(intent_type="option_a", confidence=0.5),
                        IntentResult(intent_type="option_b", confidence=0.48),
                    ],
                )

        # Check intent map
        for key, intent in self._intent_map.items():
            if key in user_input.lower():
                return intent

        return self._default_intent

    def register_priority_rule(self, rule: Dict[str, Any]) -> None:
        self._priority_rules.append(rule)

    def register_fallback_handler(self, handler: Any) -> None:
        self._fallback_handler = handler


class MockLLMPlanner(IMCPlanner):
    """Mock planner that generates deterministic execution plans."""

    def __init__(
        self,
        plan_map: Optional[Dict[str, List[PlanStep]]] = None,
        default_steps: Optional[List[PlanStep]] = None,
    ) -> None:
        self._plan_map = plan_map or {}
        self._default_steps = default_steps or [
            PlanStep(
                step_id="step_1",
                domain="general",
                action="process",
                parameters={},
            )
        ]
        self._persisted: Dict[str, ExecutionPlan] = {}

    async def generate_plan(
        self, intent: IntentResult, session_state: SessionState, timeout_seconds=None
    ) -> ExecutionPlan:
        steps = self._plan_map.get(intent.intent_type, self._default_steps)
        return ExecutionPlan(
            plan_id=f"plan_{intent.intent_type}",
            intent=intent,
            steps=steps,
            created_at=time.time(),
        )

    async def persist_plan(self, plan: ExecutionPlan) -> str:
        self._persisted[plan.plan_id] = plan
        return plan.plan_id


class MockLLMSynthesizer(Synthesizer):
    """Mock synthesizer that generates deterministic responses."""

    async def synthesize(
        self,
        aggregated: AggregatedResult,
        session_state: SessionState,
        quality_threshold: float = 0.7,
    ) -> SynthesisResult:
        completed = [
            r for r in aggregated.results if r.status == StepStatus.COMPLETED
        ]
        if not completed:
            return SynthesisResult(
                text_response="No results available.",
                quality_score=0.5,
            )

        parts = []
        for r in completed:
            parts.append(f"Step {r.step_id}: {r.result}")

        text = "Results: " + "; ".join(parts)
        return SynthesisResult(
            text_response=text,
            quality_score=0.9,
            requires_confirmation=False,
        )


# ============================================================
# Mock Domain Invoker
# ============================================================


async def mock_domain_invoker(request: DomainRequest) -> DomainResponse:
    """Simulates domain service calls with deterministic responses."""
    if request.domain == "fund":
        return DomainResponse(
            request_id=request.request_id,
            domain=request.domain,
            success=True,
            data={"fund_name": "Growth Fund", "nav": 1.25},
        )
    elif request.domain == "asset":
        return DomainResponse(
            request_id=request.request_id,
            domain=request.domain,
            success=True,
            data={"total_assets": 1000000, "currency": "CNY"},
        )
    elif request.domain == "failing":
        return DomainResponse(
            request_id=request.request_id,
            domain=request.domain,
            success=False,
            error="Service temporarily unavailable",
        )
    elif request.domain == "slow":
        await asyncio.sleep(10)
        return DomainResponse(
            request_id=request.request_id,
            domain=request.domain,
            success=True,
            data={"result": "slow_response"},
        )
    else:
        return DomainResponse(
            request_id=request.request_id,
            domain=request.domain,
            success=True,
            data={"result": "ok"},
        )


# ============================================================
# Integration Test Fixtures
# ============================================================


def _build_integration_gateway(
    router: Optional[TopLevelRouter] = None,
    planner: Optional[IMCPlanner] = None,
    synthesizer: Optional[Synthesizer] = None,
    config: Optional[SDKConfig] = None,
    domain_invoker=None,
) -> DefaultMASGateway:
    """Build a fully wired gateway with mock components for integration testing."""
    return DefaultMASGateway(
        session_context=SessionContext(),
        router=router or MockLLMRouter(),
        planner=planner or MockLLMPlanner(),
        dispatcher=ConcurrentDispatcher(),
        aggregator=FanInAggregator(),
        synthesizer=synthesizer or MockLLMSynthesizer(),
        card_generator=DefaultCardGenerator(),
        config=config or SDKConfig(),
        domain_invoker=domain_invoker or mock_domain_invoker,
    )


# ============================================================
# Test: Full Synchronous Pipeline (RequestMessage → CardOutput)
# ============================================================


class TestFullPipeline:
    """Integration tests for the complete synchronous request pipeline.

    Validates: Requirements 1.1, 3.1, 4.1, 9.1, 10.1
    """

    async def test_simple_request_produces_card_output(self) -> None:
        """A simple request should flow through the entire pipeline and
        produce a ResponseMessage with card content."""
        gw = _build_integration_gateway()
        request = RequestMessage(
            user_input="查询基金信息",
            session_id="integration_sess_1",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is None
        assert response.session_id == "integration_sess_1"
        assert response.content is not None
        # Content should be a serialized CardOutput
        assert isinstance(response.content, dict)
        assert "cards" in response.content
        assert len(response.content["cards"]) > 0

    async def test_multi_step_plan_with_dependencies(self) -> None:
        """A plan with multiple steps and dependencies should execute
        in the correct order and produce aggregated results."""
        planner = MockLLMPlanner(
            plan_map={
                "general_query": [
                    PlanStep(
                        step_id="s1",
                        domain="fund",
                        action="query_nav",
                        parameters={"fund_id": "001"},
                    ),
                    PlanStep(
                        step_id="s2",
                        domain="asset",
                        action="query_total",
                        parameters={},
                    ),
                    PlanStep(
                        step_id="s3",
                        domain="general",
                        action="combine",
                        parameters={},
                        dependencies=["s1", "s2"],
                    ),
                ]
            }
        )

        gw = _build_integration_gateway(planner=planner)
        request = RequestMessage(
            user_input="查询基金和资产",
            session_id="integration_sess_2",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is None
        assert response.content is not None
        assert "cards" in response.content

    async def test_session_state_persists_across_requests(self) -> None:
        """Dialog history should accumulate across multiple requests
        within the same session."""
        gw = _build_integration_gateway()

        # First request
        req1 = RequestMessage(
            user_input="第一个问题",
            session_id="persist_sess",
            channel_id="web",
        )
        resp1 = await gw.handle_request(req1)
        assert resp1.error is None

        # Second request
        req2 = RequestMessage(
            user_input="第二个问题",
            session_id="persist_sess",
            channel_id="web",
        )
        resp2 = await gw.handle_request(req2)
        assert resp2.error is None

        # Verify session has accumulated dialog history
        state = await gw.session_context.get_or_create("persist_sess")
        # Each request adds 2 entries (user + assistant)
        assert len(state.dialog_history) >= 4

    async def test_clarification_flow(self) -> None:
        """When the router returns a ClarificationQuestion, the response
        should contain the question and candidates."""
        router = MockLLMRouter(clarification_keywords=["不确定"])
        gw = _build_integration_gateway(router=router)

        request = RequestMessage(
            user_input="我不确定要查什么",
            session_id="clarify_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is None
        assert response.content is not None
        assert "question" in response.content
        assert "candidates" in response.content

    async def test_intent_specific_routing(self) -> None:
        """Different user inputs should route to different intents
        and produce different execution plans."""
        router = MockLLMRouter(
            intent_map={
                "基金": IntentResult(
                    intent_type="fund_query",
                    confidence=0.95,
                    parameters={"domain": "fund"},
                ),
                "资产": IntentResult(
                    intent_type="asset_query",
                    confidence=0.92,
                    parameters={"domain": "asset"},
                ),
            }
        )
        planner = MockLLMPlanner(
            plan_map={
                "fund_query": [
                    PlanStep(step_id="f1", domain="fund", action="query", parameters={})
                ],
                "asset_query": [
                    PlanStep(step_id="a1", domain="asset", action="query", parameters={})
                ],
            }
        )

        gw = _build_integration_gateway(router=router, planner=planner)

        # Fund query
        resp_fund = await gw.handle_request(
            RequestMessage(
                user_input="查询基金净值",
                session_id="route_sess_1",
                channel_id="web",
            )
        )
        assert resp_fund.error is None

        # Asset query
        resp_asset = await gw.handle_request(
            RequestMessage(
                user_input="查询资产总额",
                session_id="route_sess_2",
                channel_id="web",
            )
        )
        assert resp_asset.error is None

    async def test_card_output_contains_raw_text(self) -> None:
        """The CardOutput should include raw_text for accessibility."""
        gw = _build_integration_gateway()
        request = RequestMessage(
            user_input="hello",
            session_id="raw_text_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is None
        assert response.content is not None
        assert "raw_text" in response.content


# ============================================================
# Test: Async Task Submission and Query Flow
# ============================================================


class TestAsyncTaskFlow:
    """Integration tests for async task submission and status tracking.

    Validates: Requirements 11.1
    """

    async def test_submit_and_query_task(self) -> None:
        """Submitting an async task should return a task_id, and the task
        should eventually complete."""
        gw = _build_integration_gateway()
        request = RequestMessage(
            user_input="异步查询",
            session_id="async_sess_1",
            channel_id="web",
        )

        task_id = await gw.submit_async_task(request, priority=0)
        assert task_id
        assert isinstance(task_id, str)

        # Initial status should be PENDING or already processing
        initial_status = await gw.get_task_status(task_id)
        assert initial_status in (
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
        )

        # Wait for completion
        await asyncio.sleep(0.5)

        final_status = await gw.get_task_status(task_id)
        assert final_status == TaskStatus.COMPLETED

    async def test_async_task_result_available(self) -> None:
        """After an async task completes, its result should be retrievable."""
        gw = _build_integration_gateway()
        request = RequestMessage(
            user_input="查询基金",
            session_id="async_result_sess",
            channel_id="web",
        )

        task_id = await gw.submit_async_task(request, priority=0)
        await asyncio.sleep(0.5)

        result = await gw.get_task_result(task_id)
        assert result is not None
        assert isinstance(result, ResponseMessage)
        assert result.error is None

    async def test_multiple_async_tasks(self) -> None:
        """Multiple async tasks should all complete independently."""
        gw = _build_integration_gateway()

        task_ids = []
        for i in range(3):
            request = RequestMessage(
                user_input=f"查询 {i}",
                session_id=f"multi_async_{i}",
                channel_id="web",
            )
            tid = await gw.submit_async_task(request, priority=i)
            task_ids.append(tid)

        # Wait for all to complete
        await asyncio.sleep(1.0)

        for tid in task_ids:
            status = await gw.get_task_status(tid)
            assert status == TaskStatus.COMPLETED

    async def test_unknown_task_id_returns_failed(self) -> None:
        """Querying a non-existent task_id should return FAILED."""
        gw = _build_integration_gateway()
        status = await gw.get_task_status("nonexistent_task_id")
        assert status == TaskStatus.FAILED


# ============================================================
# Test: Error Handling and Degradation Flow
# ============================================================


class TestErrorHandlingFlow:
    """Integration tests for error handling and degradation.

    Validates: Requirements 1.1, 9.1
    """

    async def test_missing_session_id_returns_error(self) -> None:
        """Request with empty session_id should return an error response."""
        gw = _build_integration_gateway()
        request = RequestMessage(
            user_input="hello",
            session_id="",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is not None
        assert response.error.code == "REQ_MISSING_SESSION_ID"

    async def test_missing_channel_id_returns_error(self) -> None:
        """Request with empty channel_id should return an error response."""
        gw = _build_integration_gateway()
        request = RequestMessage(
            user_input="hello",
            session_id="err_sess",
            channel_id="",
        )

        response = await gw.handle_request(request)

        assert response.error is not None
        assert response.error.code == "REQ_MISSING_CHANNEL_ID"

    async def test_failing_domain_produces_partial_results(self) -> None:
        """When a domain step fails, the pipeline should still produce
        a response with partial results."""
        planner = MockLLMPlanner(
            default_steps=[
                PlanStep(
                    step_id="ok_step",
                    domain="fund",
                    action="query",
                    parameters={},
                ),
                PlanStep(
                    step_id="fail_step",
                    domain="failing",
                    action="query",
                    parameters={},
                ),
            ]
        )

        gw = _build_integration_gateway(planner=planner)
        request = RequestMessage(
            user_input="查询多个领域",
            session_id="partial_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        # Pipeline should still complete (not crash)
        assert response.error is None
        assert response.content is not None

    async def test_router_exception_returns_system_error(self) -> None:
        """If the router throws an exception, the gateway should catch it
        and return a system error response."""

        class ExplodingRouter(TopLevelRouter):
            async def route(self, user_input, session_state, mode=None):
                raise RuntimeError("Router internal failure")

            def register_priority_rule(self, rule):
                pass

            def register_fallback_handler(self, handler):
                pass

        gw = _build_integration_gateway(router=ExplodingRouter())
        request = RequestMessage(
            user_input="hello",
            session_id="explode_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is not None
        assert response.error.code == "SYS_INTERNAL_ERROR"

    async def test_planner_exception_returns_system_error(self) -> None:
        """If the planner throws an exception, the gateway should catch it
        and return a system error response."""

        class ExplodingPlanner(IMCPlanner):
            async def generate_plan(self, intent, session_state, timeout_seconds=None):
                raise RuntimeError("Planner internal failure")

            async def persist_plan(self, plan):
                return "plan_id"

        gw = _build_integration_gateway(planner=ExplodingPlanner())
        request = RequestMessage(
            user_input="hello",
            session_id="planner_err_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is not None
        assert response.error.code == "SYS_INTERNAL_ERROR"

    async def test_synthesizer_exception_returns_system_error(self) -> None:
        """If the synthesizer throws an exception, the gateway should catch it
        and return a system error response."""

        class ExplodingSynthesizer(Synthesizer):
            async def synthesize(self, aggregated, session_state, quality_threshold=0.7):
                raise RuntimeError("Synthesizer internal failure")

        gw = _build_integration_gateway(synthesizer=ExplodingSynthesizer())
        request = RequestMessage(
            user_input="hello",
            session_id="synth_err_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is not None
        assert response.error.code == "SYS_INTERNAL_ERROR"

    async def test_no_domain_invoker_still_produces_response(self) -> None:
        """When no domain_invoker is configured, the pipeline should still
        produce a response (with empty step results)."""
        gw = _build_integration_gateway(domain_invoker=None)
        request = RequestMessage(
            user_input="hello",
            session_id="no_invoker_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is None
        assert response.content is not None


# ============================================================
# Test: SDK Factory Integration
# ============================================================


class TestSDKFactoryIntegration:
    """Integration tests for the create_sdk factory function.

    Validates: Requirements 12.1, 12.2
    """

    async def test_create_sdk_and_handle_request(self) -> None:
        """A gateway created via create_sdk should handle requests end-to-end."""
        config = OrchestrationConfig()
        gw = create_sdk(
            config,
            router=MockLLMRouter(),
            planner=MockLLMPlanner(),
            synthesizer=MockLLMSynthesizer(),
            domain_invoker=mock_domain_invoker,
        )

        request = RequestMessage(
            user_input="通过工厂创建的SDK查询",
            session_id="factory_sess",
            channel_id="web",
        )

        response = await gw.handle_request(request)

        assert response.error is None
        assert response.session_id == "factory_sess"
        assert response.content is not None

    async def test_create_sdk_with_custom_config(self) -> None:
        """Custom SDK config should be propagated through the factory."""
        custom_config = SDKConfig(
            session_idle_timeout_seconds=600,
            intent_confidence_threshold=0.8,
        )
        config = OrchestrationConfig(sdk=custom_config)
        gw = create_sdk(
            config,
            router=MockLLMRouter(),
            planner=MockLLMPlanner(),
            synthesizer=MockLLMSynthesizer(),
            domain_invoker=mock_domain_invoker,
        )

        assert gw.config.session_idle_timeout_seconds == 600
        assert gw.config.intent_confidence_threshold == 0.8

        # Should still handle requests
        request = RequestMessage(
            user_input="test",
            session_id="custom_config_sess",
            channel_id="web",
        )
        response = await gw.handle_request(request)
        assert response.error is None
