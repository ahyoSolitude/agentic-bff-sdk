"""Unit tests for core data models."""

import json

import pytest
from pydantic import ValidationError

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
    RouterMode,
    SessionState,
    StepResult,
    StepStatus,
    SynthesisResult,
    TaskStatus,
    Topic,
)


# ============================================================
# Enum Tests
# ============================================================


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"

    def test_is_str_enum(self):
        assert isinstance(TaskStatus.PENDING, str)


class TestRouterMode:
    def test_values(self):
        assert RouterMode.GENERATE == "generate"
        assert RouterMode.CONFIRM == "confirm"

    def test_is_str_enum(self):
        assert isinstance(RouterMode.GENERATE, str)


class TestStepStatus:
    def test_values(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.RUNNING == "running"
        assert StepStatus.COMPLETED == "completed"
        assert StepStatus.FAILED == "failed"
        assert StepStatus.TIMEOUT == "timeout"

    def test_is_str_enum(self):
        assert isinstance(StepStatus.TIMEOUT, str)


class TestCardType:
    def test_values(self):
        assert CardType.TEXT == "text"
        assert CardType.TABLE == "table"
        assert CardType.CHART == "chart"
        assert CardType.ACTION_BUTTON == "action_button"
        assert CardType.CONFIRMATION == "confirmation"

    def test_is_str_enum(self):
        assert isinstance(CardType.TEXT, str)


# ============================================================
# Request / Response Model Tests
# ============================================================


class TestRequestMessage:
    def test_basic_creation(self):
        msg = RequestMessage(user_input="hello", session_id="s1", channel_id="c1")
        assert msg.user_input == "hello"
        assert msg.session_id == "s1"
        assert msg.channel_id == "c1"
        assert msg.metadata == {}

    def test_with_metadata(self):
        msg = RequestMessage(
            user_input="hi",
            session_id="s1",
            channel_id="c1",
            metadata={"key": "value"},
        )
        assert msg.metadata == {"key": "value"}

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            RequestMessage(user_input="hello", session_id="s1")  # type: ignore

    def test_serialization_round_trip(self):
        msg = RequestMessage(
            user_input="test", session_id="s1", channel_id="c1", metadata={"a": 1}
        )
        data = msg.model_dump_json()
        loaded = RequestMessage.model_validate_json(data)
        assert loaded == msg


class TestErrorResponse:
    def test_basic_creation(self):
        err = ErrorResponse(code="REQ_001", message="Missing field")
        assert err.code == "REQ_001"
        assert err.message == "Missing field"
        assert err.details is None

    def test_with_details(self):
        err = ErrorResponse(
            code="REQ_002", message="Invalid", details={"field": "session_id"}
        )
        assert err.details == {"field": "session_id"}


class TestResponseMessage:
    def test_basic_creation(self):
        resp = ResponseMessage(session_id="s1", content="hello")
        assert resp.session_id == "s1"
        assert resp.content == "hello"
        assert resp.task_id is None
        assert resp.is_async is False
        assert resp.error is None

    def test_async_with_error(self):
        err = ErrorResponse(code="SYS_001", message="Internal error")
        resp = ResponseMessage(
            session_id="s1", content=None, task_id="t1", is_async=True, error=err
        )
        assert resp.is_async is True
        assert resp.task_id == "t1"
        assert resp.error.code == "SYS_001"


# ============================================================
# Session Model Tests
# ============================================================


class TestTopic:
    def test_basic_creation(self):
        topic = Topic(topic_id="t1", name="Fund Query", status="active", created_at=1.0)
        assert topic.topic_id == "t1"
        assert topic.name == "Fund Query"
        assert topic.status == "active"
        assert topic.metadata == {}

    def test_with_metadata(self):
        topic = Topic(
            topic_id="t1",
            name="Test",
            status="closed",
            created_at=1.0,
            metadata={"reason": "done"},
        )
        assert topic.metadata == {"reason": "done"}


class TestSessionState:
    def test_basic_creation(self):
        state = SessionState(
            session_id="s1",
            dialog_history=[],
            created_at=1000.0,
            last_active_at=2000.0,
        )
        assert state.session_id == "s1"
        assert state.dialog_history == []
        assert state.user_profile_summary is None
        assert state.active_topics == []

    def test_with_topics_and_history(self):
        topic = Topic(topic_id="t1", name="Test", status="active", created_at=1.0)
        state = SessionState(
            session_id="s1",
            dialog_history=[{"role": "user", "content": "hi"}],
            user_profile_summary="VIP customer",
            active_topics=[topic],
            created_at=1000.0,
            last_active_at=2000.0,
        )
        assert len(state.active_topics) == 1
        assert state.user_profile_summary == "VIP customer"

    def test_serialization_round_trip(self):
        topic = Topic(topic_id="t1", name="Test", status="active", created_at=1.0)
        state = SessionState(
            session_id="s1",
            dialog_history=[{"role": "user", "content": "hello"}],
            active_topics=[topic],
            created_at=1000.0,
            last_active_at=2000.0,
        )
        data = state.model_dump_json()
        loaded = SessionState.model_validate_json(data)
        assert loaded == state


# ============================================================
# Intent Model Tests
# ============================================================


class TestIntentResult:
    def test_basic_creation(self):
        intent = IntentResult(intent_type="fund_query", confidence=0.95)
        assert intent.intent_type == "fund_query"
        assert intent.confidence == 0.95
        assert intent.parameters == {}

    def test_with_parameters(self):
        intent = IntentResult(
            intent_type="transfer",
            confidence=0.8,
            parameters={"amount": 1000, "target": "account_b"},
        )
        assert intent.parameters["amount"] == 1000


class TestClarificationQuestion:
    def test_basic_creation(self):
        q = ClarificationQuestion(question="Did you mean fund query or transfer?")
        assert q.question == "Did you mean fund query or transfer?"
        assert q.candidates == []

    def test_with_candidates(self):
        candidates = [
            IntentResult(intent_type="fund_query", confidence=0.6),
            IntentResult(intent_type="transfer", confidence=0.55),
        ]
        q = ClarificationQuestion(
            question="Which did you mean?", candidates=candidates
        )
        assert len(q.candidates) == 2


# ============================================================
# Execution Plan Model Tests
# ============================================================


class TestPlanStep:
    def test_basic_creation(self):
        step = PlanStep(step_id="s1", domain="fund", action="query")
        assert step.step_id == "s1"
        assert step.domain == "fund"
        assert step.action == "query"
        assert step.parameters == {}
        assert step.dependencies == []
        assert step.is_react_node is False

    def test_with_dependencies(self):
        step = PlanStep(
            step_id="s2",
            domain="risk",
            action="check",
            dependencies=["s1"],
            is_react_node=True,
        )
        assert step.dependencies == ["s1"]
        assert step.is_react_node is True


class TestExecutionPlan:
    def test_basic_creation(self):
        intent = IntentResult(intent_type="query", confidence=0.9)
        step = PlanStep(step_id="s1", domain="fund", action="query")
        plan = ExecutionPlan(
            plan_id="p1", intent=intent, steps=[step], created_at=1000.0
        )
        assert plan.plan_id == "p1"
        assert plan.timeout_seconds is None
        assert len(plan.steps) == 1

    def test_serialization_round_trip(self):
        intent = IntentResult(intent_type="query", confidence=0.9)
        steps = [
            PlanStep(step_id="s1", domain="fund", action="query"),
            PlanStep(step_id="s2", domain="risk", action="check", dependencies=["s1"]),
        ]
        plan = ExecutionPlan(
            plan_id="p1",
            intent=intent,
            steps=steps,
            created_at=1000.0,
            timeout_seconds=30.0,
        )
        data = plan.model_dump_json()
        loaded = ExecutionPlan.model_validate_json(data)
        assert loaded == plan


# ============================================================
# Step Status Model Tests
# ============================================================


class TestStepResult:
    def test_basic_creation(self):
        result = StepResult(step_id="s1", status=StepStatus.COMPLETED)
        assert result.step_id == "s1"
        assert result.status == StepStatus.COMPLETED
        assert result.result is None
        assert result.error is None
        assert result.duration_ms == 0

    def test_failed_with_error(self):
        result = StepResult(
            step_id="s1",
            status=StepStatus.FAILED,
            error="Connection timeout",
            duration_ms=5000.0,
        )
        assert result.status == StepStatus.FAILED
        assert result.error == "Connection timeout"

    def test_with_result_data(self):
        result = StepResult(
            step_id="s1",
            status=StepStatus.COMPLETED,
            result={"balance": 10000},
            duration_ms=150.5,
        )
        assert result.result == {"balance": 10000}


# ============================================================
# Domain Call Model Tests
# ============================================================


class TestDomainRequest:
    def test_basic_creation(self):
        req = DomainRequest(domain="fund", action="query", request_id="r1")
        assert req.domain == "fund"
        assert req.action == "query"
        assert req.parameters == {}
        assert req.request_id == "r1"

    def test_with_parameters(self):
        req = DomainRequest(
            domain="fund",
            action="buy",
            parameters={"fund_id": "F001", "amount": 5000},
            request_id="r2",
        )
        assert req.parameters["fund_id"] == "F001"


class TestDomainResponse:
    def test_success(self):
        resp = DomainResponse(request_id="r1", domain="fund", success=True, data={"nav": 1.5})
        assert resp.success is True
        assert resp.data == {"nav": 1.5}
        assert resp.error is None

    def test_failure(self):
        resp = DomainResponse(
            request_id="r1", domain="fund", success=False, error="Service unavailable"
        )
        assert resp.success is False
        assert resp.error == "Service unavailable"


# ============================================================
# Aggregation / Synthesis Model Tests
# ============================================================


class TestAggregatedResult:
    def test_complete(self):
        results = [StepResult(step_id="s1", status=StepStatus.COMPLETED)]
        agg = AggregatedResult(results=results)
        assert agg.is_partial is False
        assert agg.missing_steps == []

    def test_partial(self):
        results = [StepResult(step_id="s1", status=StepStatus.COMPLETED)]
        agg = AggregatedResult(
            results=results, missing_steps=["s2"], is_partial=True
        )
        assert agg.is_partial is True
        assert agg.missing_steps == ["s2"]


class TestSynthesisResult:
    def test_basic_creation(self):
        synth = SynthesisResult(text_response="Here is your summary.")
        assert synth.text_response == "Here is your summary."
        assert synth.structured_data is None
        assert synth.requires_confirmation is False
        assert synth.confirmation_actions == []
        assert synth.quality_score == 0.0

    def test_with_confirmation(self):
        synth = SynthesisResult(
            text_response="Please confirm the transfer.",
            requires_confirmation=True,
            confirmation_actions=[{"action": "transfer", "amount": 1000}],
            quality_score=0.85,
        )
        assert synth.requires_confirmation is True
        assert len(synth.confirmation_actions) == 1


# ============================================================
# Card Model Tests
# ============================================================


class TestCard:
    def test_text_card(self):
        card = Card(card_type=CardType.TEXT, content={"text": "Hello"})
        assert card.card_type == CardType.TEXT
        assert card.title is None
        assert card.actions == []

    def test_confirmation_card(self):
        card = Card(
            card_type=CardType.CONFIRMATION,
            title="Confirm Transfer",
            content={"summary": "Transfer $1000"},
            actions=[{"label": "Confirm", "action": "confirm_transfer"}],
        )
        assert card.card_type == CardType.CONFIRMATION
        assert card.title == "Confirm Transfer"
        assert len(card.actions) == 1


class TestCardOutput:
    def test_basic_creation(self):
        card = Card(card_type=CardType.TEXT, content={"text": "Hi"})
        output = CardOutput(cards=[card])
        assert len(output.cards) == 1
        assert output.raw_text is None

    def test_with_raw_text(self):
        output = CardOutput(cards=[], raw_text="Fallback text")
        assert output.raw_text == "Fallback text"

    def test_serialization_round_trip(self):
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "Hello"}),
            Card(
                card_type=CardType.TABLE,
                title="Fund Data",
                content={"rows": [["A", "1"], ["B", "2"]]},
            ),
        ]
        output = CardOutput(cards=cards, raw_text="Summary")
        data = output.model_dump_json()
        loaded = CardOutput.model_validate_json(data)
        assert loaded == output

    def test_json_schema_generation(self):
        """Validates: Requirement 10.4 - CardOutput outputs valid JSON Schema."""
        schema = CardOutput.model_json_schema()
        assert "properties" in schema
        assert "cards" in schema["properties"]
