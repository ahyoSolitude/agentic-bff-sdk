"""Property-based tests for the AgentExecutor module.

Uses Hypothesis to verify:
- Property 21: Tool input parameter validation
- Property 22: Agent reasoning step limit
- Property 30: Rule engine degradation strategy
"""

import asyncio
from typing import Any, Dict, List

import pytest
from hypothesis import given, settings, strategies as st

from agentic_bff_sdk.agent_executor import (
    DefaultAgentExecutor,
    handle_rule_engine_call,
    validate_tool_input,
)
from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.config import AgentExecutorConfig


# ============================================================
# Hypothesis Strategies
# ============================================================

# Strategy for JSON Schema property types we support in tool schemas
json_schema_type = st.sampled_from(["string", "integer", "number", "boolean"])

# Strategy for generating a simple JSON Schema with required fields
@st.composite
def json_object_schema(draw):
    """Generate a random JSON Schema of type 'object' with required fields."""
    num_props = draw(st.integers(min_value=1, max_value=5))
    prop_names = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L",)),
                min_size=1,
                max_size=10,
            ),
            min_size=num_props,
            max_size=num_props,
            unique=True,
        )
    )
    properties = {}
    for name in prop_names:
        prop_type = draw(json_schema_type)
        properties[name] = {"type": prop_type}

    # Pick a non-empty subset as required fields
    num_required = draw(st.integers(min_value=1, max_value=len(prop_names)))
    required = draw(
        st.lists(
            st.sampled_from(prop_names),
            min_size=num_required,
            max_size=num_required,
            unique=True,
        )
    )

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def value_for_type(schema_type: str):
    """Return a Hypothesis strategy that generates a valid value for the given JSON Schema type."""
    if schema_type == "string":
        return st.text(max_size=50)
    elif schema_type == "integer":
        return st.integers(min_value=-10000, max_value=10000)
    elif schema_type == "number":
        return st.floats(
            min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
        )
    elif schema_type == "boolean":
        return st.booleans()
    return st.text(max_size=20)


def wrong_value_for_type(schema_type: str):
    """Return a Hypothesis strategy that generates an INVALID value for the given JSON Schema type."""
    if schema_type == "string":
        return st.integers(min_value=0, max_value=100)
    elif schema_type == "integer":
        return st.text(min_size=1, max_size=10)
    elif schema_type == "number":
        return st.text(min_size=1, max_size=10)
    elif schema_type == "boolean":
        return st.text(min_size=1, max_size=10)
    return st.integers()


@st.composite
def valid_input_for_schema(draw, schema):
    """Generate a valid input dict that conforms to the given JSON Schema."""
    properties = schema["properties"]
    required = schema.get("required", [])
    result = {}
    for name in required:
        prop_type = properties[name]["type"]
        result[name] = draw(value_for_type(prop_type))
    # Optionally include some non-required fields
    for name in properties:
        if name not in required and draw(st.booleans()):
            prop_type = properties[name]["type"]
            result[name] = draw(value_for_type(prop_type))
    return result


@st.composite
def invalid_input_missing_required(draw, schema):
    """Generate an input dict that is missing at least one required field."""
    required = schema.get("required", [])
    if not required:
        # If no required fields, we can't generate a missing-required violation
        # Return empty dict (which is valid for no-required schemas)
        return {}
    # Remove at least one required field
    num_to_keep = draw(st.integers(min_value=0, max_value=max(0, len(required) - 1)))
    kept = draw(
        st.lists(
            st.sampled_from(required),
            min_size=num_to_keep,
            max_size=num_to_keep,
            unique=True,
        )
    )
    properties = schema["properties"]
    result = {}
    for name in kept:
        prop_type = properties[name]["type"]
        result[name] = draw(value_for_type(prop_type))
    return result


@st.composite
def invalid_input_wrong_type(draw, schema):
    """Generate an input dict where at least one field has the wrong type."""
    properties = schema["properties"]
    required = schema.get("required", [])
    if not required:
        return {}

    result = {}
    # Pick one required field to give a wrong type
    bad_field = draw(st.sampled_from(required))
    for name in required:
        prop_type = properties[name]["type"]
        if name == bad_field:
            result[name] = draw(wrong_value_for_type(prop_type))
        else:
            result[name] = draw(value_for_type(prop_type))
    return result


# Strategy for tool names
tool_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)

# Strategy for max_reasoning_steps (positive integers)
max_steps_st = st.integers(min_value=1, max_value=500)

# Strategy for fallback values (non-None)
fallback_value_st = st.one_of(
    st.integers(min_value=-10000, max_value=10000),
    st.text(max_size=50),
    st.booleans(),
    st.lists(st.integers(min_value=-100, max_value=100), max_size=5),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.integers(min_value=-100, max_value=100),
        max_size=5,
    ),
)

# Strategy for exception types to simulate rule engine failures
error_type_st = st.sampled_from([
    TimeoutError,
    ConnectionError,
    RuntimeError,
    OSError,
    ValueError,
])

# Strategy for rule_set_id
rule_set_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)


# ============================================================
# Property 21: 工具输入参数验证
# ============================================================


@pytest.mark.property
class TestToolInputValidationProperty:
    """Property 21: 工具输入参数验证

    For any tool call request, if the input parameters conform to the tool's
    input_schema, validation should pass; if they do not conform, validation
    should reject and raise ValueError.

    **Validates: Requirements 8.4**
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_valid_input_passes_validation(self, data):
        """Valid inputs conforming to the schema pass validation without error.

        **Validates: Requirements 8.4**
        """
        schema = data.draw(json_object_schema())
        tool_name = data.draw(tool_name_st)
        input_params = data.draw(valid_input_for_schema(schema))

        # Should not raise
        validate_tool_input(tool_name, input_params, schema)

    @given(data=st.data())
    @settings(max_examples=100)
    def test_missing_required_field_raises(self, data):
        """Inputs missing required fields are rejected with ValueError.

        **Validates: Requirements 8.4**
        """
        schema = data.draw(json_object_schema())
        tool_name = data.draw(tool_name_st)
        input_params = data.draw(invalid_input_missing_required(schema))

        required = set(schema.get("required", []))
        provided = set(input_params.keys())

        if not required.issubset(provided):
            with pytest.raises(ValueError, match="input validation failed"):
                validate_tool_input(tool_name, input_params, schema)
        # If all required happen to be present (edge case), it's valid

    @given(data=st.data())
    @settings(max_examples=100)
    def test_wrong_type_field_raises(self, data):
        """Inputs with wrong-typed fields are rejected with ValueError.

        **Validates: Requirements 8.4**
        """
        schema = data.draw(json_object_schema())
        tool_name = data.draw(tool_name_st)
        input_params = data.draw(invalid_input_wrong_type(schema))

        required = set(schema.get("required", []))
        if not required:
            return  # Skip if no required fields to corrupt

        with pytest.raises(ValueError, match="input validation failed"):
            validate_tool_input(tool_name, input_params, schema)


# ============================================================
# Property 22: Agent 推理步数上限
# ============================================================


@pytest.mark.property
class TestAgentReasoningStepLimitProperty:
    """Property 22: Agent 推理步数上限

    For any AgentExecutor execution, the reasoning step count should not
    exceed the configured max_reasoning_steps. The reasoning loop receives
    the correct max_steps parameter matching the config.

    **Validates: Requirements 8.6**
    """

    @given(max_steps=max_steps_st)
    @settings(max_examples=100)
    async def test_reasoning_loop_receives_correct_max_steps(self, max_steps: int):
        """The reasoning loop receives max_steps matching the configured value.

        **Validates: Requirements 8.6**
        """
        received_max_steps = None

        async def recording_loop(
            action: str,
            parameters: Dict[str, Any],
            tools: list,
            blackboard_context: Dict[str, Any],
            loop_max_steps: int,
        ) -> Any:
            nonlocal received_max_steps
            received_max_steps = loop_max_steps
            return "done"

        executor = DefaultAgentExecutor(reasoning_loop=recording_loop)
        blackboard = Blackboard()
        config = AgentExecutorConfig(max_reasoning_steps=max_steps)

        await executor.execute("test_action", {}, blackboard, config)

        assert received_max_steps == max_steps

    @given(
        max_steps=max_steps_st,
        action=st.text(min_size=1, max_size=30),
    )
    @settings(max_examples=100)
    async def test_max_steps_is_upper_bound(self, max_steps: int, action: str):
        """The reasoning loop's max_steps parameter is always <= configured max_reasoning_steps.

        **Validates: Requirements 8.6**
        """
        received_max_steps = None

        async def recording_loop(
            act: str,
            parameters: Dict[str, Any],
            tools: list,
            blackboard_context: Dict[str, Any],
            loop_max_steps: int,
        ) -> Any:
            nonlocal received_max_steps
            received_max_steps = loop_max_steps
            return "result"

        executor = DefaultAgentExecutor(reasoning_loop=recording_loop)
        blackboard = Blackboard()
        config = AgentExecutorConfig(max_reasoning_steps=max_steps)

        await executor.execute(action, {}, blackboard, config)

        assert received_max_steps is not None
        assert received_max_steps <= max_steps
        assert received_max_steps == max_steps


# ============================================================
# Property 30: 规则引擎降级策略
# ============================================================


@pytest.mark.property
class TestRuleEngineDegradationProperty:
    """Property 30: 规则引擎降级策略

    For any rule engine call timeout or error, if a degradation strategy
    (fallback_value) is configured, the AgentExecutor should return the
    configured default value; if no degradation strategy is configured,
    it should raise RuntimeError.

    **Validates: Requirements 13.4**
    """

    @given(
        fallback=fallback_value_st,
        error_cls=error_type_st,
        rule_set_id=rule_set_id_st,
    )
    @settings(max_examples=100)
    async def test_returns_fallback_when_configured(
        self, fallback, error_cls, rule_set_id
    ):
        """When fallback_value is configured and rule engine fails, return fallback.

        **Validates: Requirements 13.4**
        """

        async def failing_engine(rid, params):
            raise error_cls(f"Simulated {error_cls.__name__}")

        result = await handle_rule_engine_call(
            failing_engine,
            rule_set_id,
            {"key": "value"},
            fallback_value=fallback,
        )
        assert result == fallback

    @given(
        error_cls=error_type_st,
        rule_set_id=rule_set_id_st,
    )
    @settings(max_examples=100)
    async def test_raises_when_no_fallback(self, error_cls, rule_set_id):
        """When no fallback_value is configured and rule engine fails, raise RuntimeError.

        **Validates: Requirements 13.4**
        """

        async def failing_engine(rid, params):
            raise error_cls(f"Simulated {error_cls.__name__}")

        with pytest.raises(RuntimeError, match="Rule engine call failed"):
            await handle_rule_engine_call(
                failing_engine,
                rule_set_id,
                {"key": "value"},
                fallback_value=None,
            )

    @given(
        fallback=fallback_value_st,
        rule_set_id=rule_set_id_st,
    )
    @settings(max_examples=100)
    async def test_successful_call_ignores_fallback(self, fallback, rule_set_id):
        """When rule engine succeeds, the actual result is returned regardless of fallback config.

        **Validates: Requirements 13.4**
        """
        expected_result = {"computed": True}

        async def successful_engine(rid, params):
            return expected_result

        result = await handle_rule_engine_call(
            successful_engine,
            rule_set_id,
            {"key": "value"},
            fallback_value=fallback,
        )
        assert result == expected_result
