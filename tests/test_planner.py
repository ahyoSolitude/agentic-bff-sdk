"""Unit tests for the IMCPlanner module."""

import asyncio
import time
from typing import Any, List
from unittest.mock import AsyncMock

import pytest

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    ExecutionPlan,
    IntentResult,
    PlanStep,
    SessionState,
)
from agentic_bff_sdk.planner import DefaultIMCPlanner, IMCPlanner


# ============================================================
# Helpers
# ============================================================


def _make_session_state(session_id: str = "test-session") -> SessionState:
    now = time.time()
    return SessionState(
        session_id=session_id,
        dialog_history=[],
        created_at=now,
        last_active_at=now,
    )


def _make_intent(
    intent_type: str = "test_intent",
    confidence: float = 0.9,
    parameters: dict | None = None,
) -> IntentResult:
    return IntentResult(
        intent_type=intent_type,
        confidence=confidence,
        parameters=parameters or {},
    )


def _make_mock_llm() -> AsyncMock:
    """Create a mock LLM that satisfies BaseLanguageModel interface."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value="[]")
    return mock


def _make_plan_steps(count: int = 2) -> List[PlanStep]:
    """Create a list of PlanStep objects with sequential dependencies."""
    steps = []
    for i in range(count):
        deps = [f"step_{i - 1}"] if i > 0 else []
        steps.append(
            PlanStep(
                step_id=f"step_{i}",
                domain=f"domain_{i}",
                action=f"action_{i}",
                parameters={"key": f"value_{i}"},
                dependencies=deps,
                is_react_node=(i % 2 == 1),
            )
        )
    return steps


async def _fixed_plan_generator(
    llm: Any,
    intent: IntentResult,
    session_state: SessionState,
) -> List[PlanStep]:
    """A plan generator that returns fixed steps."""
    return [
        PlanStep(
            step_id="step_0",
            domain="finance",
            action="query_balance",
            parameters={"account": "main"},
            dependencies=[],
            is_react_node=False,
        ),
        PlanStep(
            step_id="step_1",
            domain="finance",
            action="calculate_risk",
            parameters={"level": "medium"},
            dependencies=["step_0"],
            is_react_node=True,
        ),
    ]


async def _slow_plan_generator(
    llm: Any,
    intent: IntentResult,
    session_state: SessionState,
) -> List[PlanStep]:
    """A plan generator that takes a long time (for timeout testing)."""
    await asyncio.sleep(10)
    return []


# ============================================================
# IMCPlanner ABC Tests
# ============================================================


class TestIMCPlannerABC:
    """Tests verifying IMCPlanner is a proper ABC."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            IMCPlanner()  # type: ignore[abstract]


# ============================================================
# DefaultIMCPlanner Initialization Tests
# ============================================================


class TestDefaultIMCPlannerInit:
    """Tests for DefaultIMCPlanner initialization."""

    def test_default_config(self) -> None:
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm)
        assert planner.config == SDKConfig()
        assert planner.llm is llm
        assert planner.persisted_plans == {}

    def test_custom_config(self) -> None:
        llm = _make_mock_llm()
        config = SDKConfig(plan_generation_timeout_seconds=10.0)
        planner = DefaultIMCPlanner(llm=llm, config=config)
        assert planner.config.plan_generation_timeout_seconds == 10.0

    def test_custom_plan_generator(self) -> None:
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)
        assert planner.llm is llm


# ============================================================
# Plan Generation Tests
# ============================================================


class TestPlanGeneration:
    """Tests for generate_plan method."""

    async def test_generate_plan_with_custom_generator(self) -> None:
        """Custom plan_generator should be used when provided."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent("check_balance")
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert isinstance(plan, ExecutionPlan)
        assert plan.intent == intent
        assert len(plan.steps) == 2
        assert plan.steps[0].step_id == "step_0"
        assert plan.steps[0].domain == "finance"
        assert plan.steps[0].action == "query_balance"
        assert plan.steps[0].dependencies == []
        assert plan.steps[0].is_react_node is False
        assert plan.steps[1].step_id == "step_1"
        assert plan.steps[1].dependencies == ["step_0"]
        assert plan.steps[1].is_react_node is True

    async def test_generate_plan_has_valid_plan_id(self) -> None:
        """Generated plan should have a non-empty plan_id."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert plan.plan_id
        assert len(plan.plan_id) > 0

    async def test_generate_plan_has_created_at(self) -> None:
        """Generated plan should have a created_at timestamp."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        before = time.time()
        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)
        after = time.time()

        assert before <= plan.created_at <= after

    async def test_generate_plan_has_timeout_seconds(self) -> None:
        """Generated plan should record the configured timeout."""
        config = SDKConfig(plan_generation_timeout_seconds=15.0)
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(
            llm=llm, config=config, plan_generator=_fixed_plan_generator
        )

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert plan.timeout_seconds == 15.0

    async def test_generate_plan_unique_plan_ids(self) -> None:
        """Each generated plan should have a unique plan_id."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan1 = await planner.generate_plan(intent, state)
        plan2 = await planner.generate_plan(intent, state)

        assert plan1.plan_id != plan2.plan_id

    async def test_generate_plan_preserves_intent(self) -> None:
        """Generated plan should preserve the original intent."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent("complex_intent", 0.95, {"key": "value"})
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert plan.intent == intent
        assert plan.intent.intent_type == "complex_intent"
        assert plan.intent.confidence == 0.95
        assert plan.intent.parameters == {"key": "value"}


# ============================================================
# Timeout Control Tests
# ============================================================


class TestTimeoutControl:
    """Tests for timeout control in generate_plan."""

    async def test_timeout_raises_timeout_error(self) -> None:
        """When plan generation exceeds timeout, asyncio.TimeoutError is raised."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_slow_plan_generator)

        intent = _make_intent()
        state = _make_session_state()

        with pytest.raises(asyncio.TimeoutError):
            await planner.generate_plan(intent, state, timeout_seconds=0.1)

    async def test_explicit_timeout_overrides_config(self) -> None:
        """Explicit timeout_seconds parameter overrides config default."""
        config = SDKConfig(plan_generation_timeout_seconds=100.0)
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(
            llm=llm, config=config, plan_generator=_slow_plan_generator
        )

        intent = _make_intent()
        state = _make_session_state()

        with pytest.raises(asyncio.TimeoutError):
            await planner.generate_plan(intent, state, timeout_seconds=0.1)

    async def test_config_timeout_used_when_no_explicit_timeout(self) -> None:
        """Config timeout is used when timeout_seconds is None."""
        config = SDKConfig(plan_generation_timeout_seconds=0.1)
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(
            llm=llm, config=config, plan_generator=_slow_plan_generator
        )

        intent = _make_intent()
        state = _make_session_state()

        with pytest.raises(asyncio.TimeoutError):
            await planner.generate_plan(intent, state)

    async def test_fast_generation_completes_within_timeout(self) -> None:
        """Fast plan generation should complete without timeout."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state, timeout_seconds=5.0)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 2


# ============================================================
# Step Dependencies Tests
# ============================================================


class TestStepDependencies:
    """Tests for step dependency annotation."""

    async def test_steps_have_dependencies(self) -> None:
        """Steps should correctly record their dependencies."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        # step_0 has no dependencies
        assert plan.steps[0].dependencies == []
        # step_1 depends on step_0
        assert plan.steps[1].dependencies == ["step_0"]

    async def test_custom_generator_with_complex_dependencies(self) -> None:
        """Custom generator can produce complex dependency graphs."""

        async def complex_generator(llm, intent, session_state):
            return [
                PlanStep(
                    step_id="a",
                    domain="d1",
                    action="act1",
                    dependencies=[],
                ),
                PlanStep(
                    step_id="b",
                    domain="d2",
                    action="act2",
                    dependencies=[],
                ),
                PlanStep(
                    step_id="c",
                    domain="d3",
                    action="act3",
                    dependencies=["a", "b"],
                ),
            ]

        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=complex_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert len(plan.steps) == 3
        assert plan.steps[2].dependencies == ["a", "b"]


# ============================================================
# ReAct Node Embedding Tests
# ============================================================


class TestReActNodeEmbedding:
    """Tests for ReAct loop node embedding support."""

    async def test_react_node_flag(self) -> None:
        """Steps can be marked as ReAct loop nodes."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert plan.steps[0].is_react_node is False
        assert plan.steps[1].is_react_node is True

    async def test_all_react_nodes(self) -> None:
        """All steps can be ReAct nodes."""

        async def all_react_generator(llm, intent, session_state):
            return [
                PlanStep(
                    step_id="s1",
                    domain="d1",
                    action="a1",
                    is_react_node=True,
                ),
                PlanStep(
                    step_id="s2",
                    domain="d2",
                    action="a2",
                    is_react_node=True,
                ),
            ]

        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=all_react_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert all(step.is_react_node for step in plan.steps)


# ============================================================
# Plan Persistence Tests
# ============================================================


class TestPlanPersistence:
    """Tests for persist_plan and load_plan methods."""

    async def test_persist_plan_returns_plan_id(self) -> None:
        """persist_plan should return the plan's plan_id."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        plan_id = await planner.persist_plan(plan)
        assert plan_id == plan.plan_id

    async def test_persist_and_load_plan(self) -> None:
        """Persisted plan should be loadable by plan_id."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        await planner.persist_plan(plan)
        loaded = await planner.load_plan(plan.plan_id)

        assert loaded is not None
        assert loaded == plan

    async def test_load_nonexistent_plan_returns_none(self) -> None:
        """Loading a non-existent plan_id should return None."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm)

        loaded = await planner.load_plan("nonexistent-id")
        assert loaded is None

    async def test_persist_multiple_plans(self) -> None:
        """Multiple plans can be persisted and loaded independently."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()

        plan1 = await planner.generate_plan(intent, state)
        plan2 = await planner.generate_plan(intent, state)

        await planner.persist_plan(plan1)
        await planner.persist_plan(plan2)

        loaded1 = await planner.load_plan(plan1.plan_id)
        loaded2 = await planner.load_plan(plan2.plan_id)

        assert loaded1 == plan1
        assert loaded2 == plan2
        assert loaded1 != loaded2

    async def test_persisted_plans_property(self) -> None:
        """persisted_plans property should return a copy of the internal store."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        await planner.persist_plan(plan)

        plans = planner.persisted_plans
        assert plan.plan_id in plans
        assert plans[plan.plan_id] == plan

        # Modifying the returned dict should not affect internal state
        plans.clear()
        assert len(planner.persisted_plans) == 1

    async def test_persist_plan_round_trip_preserves_all_fields(self) -> None:
        """Persisted plan should preserve all fields including steps, intent, etc."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm, plan_generator=_fixed_plan_generator)

        intent = _make_intent("complex", 0.95, {"param": "value"})
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        await planner.persist_plan(plan)
        loaded = await planner.load_plan(plan.plan_id)

        assert loaded is not None
        assert loaded.plan_id == plan.plan_id
        assert loaded.intent == plan.intent
        assert loaded.steps == plan.steps
        assert loaded.created_at == plan.created_at
        assert loaded.timeout_seconds == plan.timeout_seconds


# ============================================================
# Default LLM Plan Generator Tests
# ============================================================


class TestDefaultLLMPlanGenerator:
    """Tests for the default LLM-based plan generation (no custom generator)."""

    async def test_default_generator_calls_llm(self) -> None:
        """When no custom generator, LLM ainvoke should be called."""
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        llm.ainvoke.assert_called_once()
        assert isinstance(plan, ExecutionPlan)

    async def test_default_generator_parses_llm_json_response(self) -> None:
        """Default generator should parse valid JSON from LLM response."""
        import json

        llm_response = json.dumps(
            [
                {
                    "step_id": "s1",
                    "domain": "trading",
                    "action": "buy",
                    "parameters": {"symbol": "AAPL"},
                    "dependencies": [],
                    "is_react_node": False,
                },
                {
                    "step_id": "s2",
                    "domain": "notification",
                    "action": "notify",
                    "parameters": {},
                    "dependencies": ["s1"],
                    "is_react_node": False,
                },
            ]
        )

        llm = _make_mock_llm()
        llm.ainvoke = AsyncMock(return_value=llm_response)
        planner = DefaultIMCPlanner(llm=llm)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert len(plan.steps) == 2
        assert plan.steps[0].step_id == "s1"
        assert plan.steps[0].domain == "trading"
        assert plan.steps[0].action == "buy"
        assert plan.steps[0].parameters == {"symbol": "AAPL"}
        assert plan.steps[1].dependencies == ["s1"]

    async def test_default_generator_handles_invalid_json(self) -> None:
        """Default generator should return empty steps for invalid JSON."""
        llm = _make_mock_llm()
        llm.ainvoke = AsyncMock(return_value="not valid json at all")
        planner = DefaultIMCPlanner(llm=llm)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert isinstance(plan, ExecutionPlan)
        assert plan.steps == []

    async def test_default_generator_handles_llm_content_attribute(self) -> None:
        """Default generator should handle LLM response with .content attribute."""
        import json

        steps_json = json.dumps(
            [
                {
                    "step_id": "s1",
                    "domain": "d1",
                    "action": "a1",
                    "parameters": {},
                    "dependencies": [],
                    "is_react_node": True,
                }
            ]
        )

        mock_response = AsyncMock()
        mock_response.content = steps_json

        llm = _make_mock_llm()
        llm.ainvoke = AsyncMock(return_value=mock_response)
        planner = DefaultIMCPlanner(llm=llm)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert len(plan.steps) == 1
        assert plan.steps[0].is_react_node is True

    async def test_default_generator_empty_array_response(self) -> None:
        """Default generator should handle empty JSON array from LLM."""
        llm = _make_mock_llm()
        llm.ainvoke = AsyncMock(return_value="[]")
        planner = DefaultIMCPlanner(llm=llm)

        intent = _make_intent()
        state = _make_session_state()
        plan = await planner.generate_plan(intent, state)

        assert isinstance(plan, ExecutionPlan)
        assert plan.steps == []


# ============================================================
# Parse Steps Tests
# ============================================================


class TestParseSteps:
    """Tests for the _parse_steps static method."""

    def test_parse_valid_json_array(self) -> None:
        import json

        text = json.dumps(
            [
                {"step_id": "s1", "domain": "d1", "action": "a1"},
                {"step_id": "s2", "domain": "d2", "action": "a2", "dependencies": ["s1"]},
            ]
        )
        steps = DefaultIMCPlanner._parse_steps(text)
        assert len(steps) == 2
        assert steps[0].step_id == "s1"
        assert steps[1].dependencies == ["s1"]

    def test_parse_invalid_json(self) -> None:
        steps = DefaultIMCPlanner._parse_steps("not json")
        assert steps == []

    def test_parse_json_object_instead_of_array(self) -> None:
        import json

        text = json.dumps({"step_id": "s1", "domain": "d1", "action": "a1"})
        steps = DefaultIMCPlanner._parse_steps(text)
        assert steps == []

    def test_parse_with_missing_fields_uses_defaults(self) -> None:
        import json

        text = json.dumps([{"some_field": "value"}])
        steps = DefaultIMCPlanner._parse_steps(text)
        assert len(steps) == 1
        assert steps[0].step_id == "step_0"
        assert steps[0].domain == ""
        assert steps[0].action == ""
        assert steps[0].parameters == {}
        assert steps[0].dependencies == []
        assert steps[0].is_react_node is False

    def test_parse_skips_non_dict_items(self) -> None:
        import json

        text = json.dumps([{"step_id": "s1", "domain": "d1", "action": "a1"}, "not_a_dict", 42])
        steps = DefaultIMCPlanner._parse_steps(text)
        assert len(steps) == 1
        assert steps[0].step_id == "s1"
