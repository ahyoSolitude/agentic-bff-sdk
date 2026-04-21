"""Property-based tests for the IMC Planner module.

Uses Hypothesis to generate random ExecutionPlan instances and verify:
- Property 12: Structural validity of execution plans
- Property 13: Persistence round-trip correctness
"""

import pytest
from hypothesis import given, settings, strategies as st
from unittest.mock import AsyncMock

from agentic_bff_sdk.models import (
    ExecutionPlan,
    IntentResult,
    PlanStep,
)
from agentic_bff_sdk.planner import DefaultIMCPlanner


# ============================================================
# Hypothesis Strategies
# ============================================================

# Safe identifier strings for IDs, domains, actions
safe_id = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)

# Non-empty domain/action strings
non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
)

# JSON-safe primitive values
json_primitive = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(
        min_value=-1e6, max_value=1e6,
        allow_nan=False, allow_infinity=False,
    ),
    safe_id,
)

# Simple JSON-safe dict
json_safe_dict = st.dictionaries(
    keys=safe_id,
    values=json_primitive,
    max_size=5,
)

# Positive finite timestamps
safe_timestamp = st.floats(
    min_value=0.0,
    max_value=1e12,
    allow_nan=False,
    allow_infinity=False,
)

# IntentResult strategy
intent_result_st = st.builds(
    IntentResult,
    intent_type=non_empty_text,
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    parameters=json_safe_dict,
)


@st.composite
def execution_plan_st(draw):
    """Generate a structurally valid ExecutionPlan.

    Each PlanStep has non-empty domain and action, unique step_id,
    and dependencies that only reference step_ids earlier in the list.
    """
    num_steps = draw(st.integers(min_value=1, max_value=10))

    steps = []
    step_ids = []
    for i in range(num_steps):
        step_id = f"step_{i}_{draw(safe_id)}"
        domain = draw(non_empty_text)
        action = draw(non_empty_text)
        parameters = draw(json_safe_dict)
        is_react_node = draw(st.booleans())

        # Dependencies can only reference previously created step_ids
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
                step_id=step_id,
                domain=domain,
                action=action,
                parameters=parameters,
                dependencies=deps,
                is_react_node=is_react_node,
            )
        )
        step_ids.append(step_id)

    plan_id = draw(safe_id)
    intent = draw(intent_result_st)
    created_at = draw(safe_timestamp)
    timeout_seconds = draw(
        st.one_of(
            st.none(),
            st.floats(min_value=0.1, max_value=3600.0, allow_nan=False, allow_infinity=False),
        )
    )

    return ExecutionPlan(
        plan_id=plan_id,
        intent=intent,
        steps=steps,
        created_at=created_at,
        timeout_seconds=timeout_seconds,
    )


# ============================================================
# Helpers
# ============================================================


def _make_mock_llm() -> AsyncMock:
    """Create a mock LLM that satisfies BaseLanguageModel interface."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value="[]")
    return mock


# ============================================================
# Property 12: 执行计划结构有效性
# ============================================================


@pytest.mark.property
class TestExecutionPlanStructuralValidity:
    """Property 12: 执行计划结构有效性

    For any ExecutionPlan, each PlanStep should have non-empty domain
    and action, and all dependency step_ids should reference existing
    steps within the same plan.

    **Validates: Requirements 4.2, 4.6**
    """

    @given(plan=execution_plan_st())
    @settings(max_examples=100)
    def test_all_steps_have_non_empty_domain_and_action(
        self, plan: ExecutionPlan
    ):
        """Every PlanStep in the plan has a non-empty domain and action.

        **Validates: Requirements 4.2**
        """
        for step in plan.steps:
            assert step.domain, (
                f"Step {step.step_id!r} has empty domain"
            )
            assert step.action, (
                f"Step {step.step_id!r} has empty action"
            )

    @given(plan=execution_plan_st())
    @settings(max_examples=100)
    def test_all_dependency_references_are_valid(
        self, plan: ExecutionPlan
    ):
        """All dependency step_ids in each PlanStep reference existing
        steps within the same plan.

        **Validates: Requirements 4.6**
        """
        valid_step_ids = {step.step_id for step in plan.steps}

        for step in plan.steps:
            for dep_id in step.dependencies:
                assert dep_id in valid_step_ids, (
                    f"Step {step.step_id!r} references dependency "
                    f"{dep_id!r} which does not exist in the plan. "
                    f"Valid step_ids: {valid_step_ids}"
                )

    @given(plan=execution_plan_st())
    @settings(max_examples=100)
    def test_no_self_dependencies(
        self, plan: ExecutionPlan
    ):
        """No PlanStep depends on itself.

        **Validates: Requirements 4.2, 4.6**
        """
        for step in plan.steps:
            assert step.step_id not in step.dependencies, (
                f"Step {step.step_id!r} has a self-dependency"
            )


# ============================================================
# Property 13: 执行计划持久化 Round-Trip
# ============================================================


@pytest.mark.property
class TestExecutionPlanPersistenceRoundTrip:
    """Property 13: 执行计划持久化 Round-Trip

    For any valid ExecutionPlan, persisting it via DefaultIMCPlanner.persist_plan
    and loading it via load_plan should produce an instance equivalent to the
    original plan.

    **Validates: Requirements 4.5**
    """

    @given(plan=execution_plan_st())
    @settings(max_examples=100)
    async def test_persist_then_load_returns_equivalent_plan(
        self, plan: ExecutionPlan
    ):
        """Persisting an ExecutionPlan and loading it back produces an
        equivalent instance.

        **Validates: Requirements 4.5**
        """
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm)

        plan_id = await planner.persist_plan(plan)
        loaded = await planner.load_plan(plan_id)

        assert loaded is not None, (
            f"load_plan returned None for plan_id={plan_id!r}"
        )
        assert loaded == plan, (
            f"Loaded plan does not match original.\n"
            f"Original: {plan}\n"
            f"Loaded:   {loaded}"
        )

    @given(plan=execution_plan_st())
    @settings(max_examples=100)
    async def test_persist_returns_correct_plan_id(
        self, plan: ExecutionPlan
    ):
        """persist_plan returns the plan's plan_id.

        **Validates: Requirements 4.5**
        """
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm)

        returned_id = await planner.persist_plan(plan)
        assert returned_id == plan.plan_id, (
            f"persist_plan returned {returned_id!r}, expected {plan.plan_id!r}"
        )

    @given(
        plans=st.lists(
            execution_plan_st(),
            min_size=1,
            max_size=5,
            unique_by=lambda p: p.plan_id,
        )
    )
    @settings(max_examples=100)
    async def test_multiple_plans_round_trip(
        self, plans: list
    ):
        """Multiple distinct plans persisted and loaded back all match
        their originals.

        **Validates: Requirements 4.5**
        """
        llm = _make_mock_llm()
        planner = DefaultIMCPlanner(llm=llm)

        for plan in plans:
            await planner.persist_plan(plan)

        for plan in plans:
            loaded = await planner.load_plan(plan.plan_id)
            assert loaded is not None, (
                f"load_plan returned None for plan_id={plan.plan_id!r}"
            )
            assert loaded == plan, (
                f"Loaded plan does not match original for "
                f"plan_id={plan.plan_id!r}"
            )
