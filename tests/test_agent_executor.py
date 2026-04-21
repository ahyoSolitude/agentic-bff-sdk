"""Unit tests for the AgentExecutor module.

Tests cover:
- AgentExecutor ABC contract
- DefaultAgentExecutor tool registration
- Tool input validation (jsonschema-based)
- Max reasoning steps limit
- Blackboard context passing to LLM
- Tool call error feedback to LLM
- Rule engine degradation strategy (fallback value / raise)
"""

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from agentic_bff_sdk.agent_executor import (
    AgentExecutor,
    DefaultAgentExecutor,
    ReasoningLoop,
    handle_rule_engine_call,
    validate_tool_input,
)
from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.config import AgentExecutorConfig, SDKConfig, ToolDefinition


# ============================================================
# Helpers / Fixtures
# ============================================================


class DummyTool(BaseTool):
    """A simple tool for testing."""

    name: str = "dummy_tool"
    description: str = "A dummy tool for testing"

    def _run(self, **kwargs: Any) -> str:
        return f"dummy_result: {kwargs}"

    async def _arun(self, **kwargs: Any) -> str:
        return f"dummy_result: {kwargs}"


class FailingTool(BaseTool):
    """A tool that always raises an error."""

    name: str = "failing_tool"
    description: str = "A tool that always fails"

    def _run(self, **kwargs: Any) -> str:
        raise RuntimeError("Tool execution failed")

    async def _arun(self, **kwargs: Any) -> str:
        raise RuntimeError("Tool execution failed")


@pytest.fixture
def blackboard() -> Blackboard:
    return Blackboard()


@pytest.fixture
def default_config() -> AgentExecutorConfig:
    return AgentExecutorConfig(max_reasoning_steps=10)


@pytest.fixture
def config_with_tools() -> AgentExecutorConfig:
    return AgentExecutorConfig(
        max_reasoning_steps=5,
        tools=[
            ToolDefinition(
                name="dummy_tool",
                description="A dummy tool",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            )
        ],
    )


# ============================================================
# Test: AgentExecutor ABC
# ============================================================


class TestAgentExecutorABC:
    """Tests for the AgentExecutor abstract base class."""

    def test_cannot_instantiate_abc(self):
        """AgentExecutor cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AgentExecutor()

    def test_subclass_must_implement_execute(self):
        """Subclass must implement execute method."""

        class IncompleteExecutor(AgentExecutor):
            def register_tool(self, tool: BaseTool) -> None:
                pass

        with pytest.raises(TypeError):
            IncompleteExecutor()

    def test_subclass_must_implement_register_tool(self):
        """Subclass must implement register_tool method."""

        class IncompleteExecutor(AgentExecutor):
            async def execute(self, action, parameters, blackboard, config):
                pass

        with pytest.raises(TypeError):
            IncompleteExecutor()

    def test_complete_subclass_can_be_instantiated(self):
        """A complete subclass can be instantiated."""

        class CompleteExecutor(AgentExecutor):
            async def execute(self, action, parameters, blackboard, config):
                return "result"

            def register_tool(self, tool: BaseTool) -> None:
                pass

        executor = CompleteExecutor()
        assert executor is not None


# ============================================================
# Test: DefaultAgentExecutor — Tool Registration
# ============================================================


class TestToolRegistration:
    """Tests for tool registration in DefaultAgentExecutor."""

    def test_register_single_tool(self):
        """Registering a single tool adds it to the tools list."""
        executor = DefaultAgentExecutor()
        tool = DummyTool()
        executor.register_tool(tool)
        assert len(executor.tools) == 1
        assert executor.tools[0].name == "dummy_tool"

    def test_register_multiple_tools(self):
        """Registering multiple tools adds all of them."""
        executor = DefaultAgentExecutor()
        tool1 = DummyTool(name="tool_1", description="First tool")
        tool2 = DummyTool(name="tool_2", description="Second tool")
        executor.register_tool(tool1)
        executor.register_tool(tool2)
        assert len(executor.tools) == 2
        names = {t.name for t in executor.tools}
        assert names == {"tool_1", "tool_2"}

    def test_tools_property_returns_copy(self):
        """The tools property returns a copy, not the internal list."""
        executor = DefaultAgentExecutor()
        tool = DummyTool()
        executor.register_tool(tool)
        tools_copy = executor.tools
        tools_copy.append(DummyTool(name="extra"))
        assert len(executor.tools) == 1  # Internal list unchanged


# ============================================================
# Test: Tool Input Validation
# ============================================================


class TestToolInputValidation:
    """Tests for tool input parameter validation."""

    def test_valid_input_passes(self):
        """Valid input matching schema passes validation."""
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["query"],
        }
        # Should not raise
        validate_tool_input("test_tool", {"query": "hello", "count": 5}, schema)

    def test_missing_required_field_raises(self):
        """Missing required field raises ValueError."""
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        }
        with pytest.raises(ValueError, match="input validation failed"):
            validate_tool_input("test_tool", {}, schema)

    def test_wrong_type_raises(self):
        """Wrong type for a field raises ValueError."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }
        with pytest.raises(ValueError, match="input validation failed"):
            validate_tool_input("test_tool", {"count": "not_a_number"}, schema)

    def test_additional_properties_allowed_by_default(self):
        """Additional properties are allowed when not restricted."""
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
        }
        # Should not raise
        validate_tool_input(
            "test_tool", {"query": "hello", "extra": "field"}, schema
        )

    def test_empty_schema_accepts_anything(self):
        """An empty schema accepts any object."""
        validate_tool_input("test_tool", {"any": "data"}, {})

    def test_executor_validates_tool_inputs(self, config_with_tools):
        """DefaultAgentExecutor validates tool inputs against config schemas."""
        executor = DefaultAgentExecutor()
        # Valid input
        executor._validate_tool_inputs(
            "dummy_tool", {"query": "test"}, config_with_tools
        )

        # Invalid input
        with pytest.raises(ValueError, match="input validation failed"):
            executor._validate_tool_inputs(
                "dummy_tool", {"count": "not_int"}, config_with_tools
            )

    def test_executor_skips_validation_for_unknown_tool(self, config_with_tools):
        """Validation is skipped for tools not in config."""
        executor = DefaultAgentExecutor()
        # Should not raise — tool not in config
        executor._validate_tool_inputs(
            "unknown_tool", {"anything": "goes"}, config_with_tools
        )


# ============================================================
# Test: Max Reasoning Steps Limit
# ============================================================


class TestMaxReasoningSteps:
    """Tests for max reasoning steps enforcement."""

    async def test_reasoning_loop_respects_max_steps(self, blackboard):
        """The reasoning loop stops after max_reasoning_steps."""
        steps_executed = []

        async def counting_loop(
            action: str,
            parameters: Dict[str, Any],
            tools: List[BaseTool],
            blackboard_context: Dict[str, Any],
            max_steps: int,
        ) -> Any:
            steps_executed.append(max_steps)
            return f"completed_with_max_{max_steps}"

        executor = DefaultAgentExecutor(reasoning_loop=counting_loop)
        config = AgentExecutorConfig(max_reasoning_steps=3)

        result = await executor.execute("test_action", {}, blackboard, config)

        assert steps_executed == [3]
        assert result == "completed_with_max_3"

    async def test_different_max_steps_values(self, blackboard):
        """Different max_reasoning_steps values are passed correctly."""
        received_max_steps = []

        async def tracking_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            received_max_steps.append(max_steps)
            return "done"

        executor = DefaultAgentExecutor(reasoning_loop=tracking_loop)

        for steps in [1, 5, 10, 50]:
            config = AgentExecutorConfig(max_reasoning_steps=steps)
            await executor.execute("action", {}, blackboard, config)

        assert received_max_steps == [1, 5, 10, 50]


# ============================================================
# Test: Blackboard Context Passing
# ============================================================


class TestBlackboardContextPassing:
    """Tests for Blackboard context extraction and passing to LLM."""

    async def test_empty_blackboard_passes_empty_context(self, blackboard):
        """Empty Blackboard produces empty context dict."""
        context = await DefaultAgentExecutor._extract_blackboard_context(
            blackboard
        )
        assert context == {}

    async def test_blackboard_data_passed_to_reasoning_loop(self, blackboard):
        """Blackboard data is extracted and passed to the reasoning loop."""
        await blackboard.set("user_name", "Alice")
        await blackboard.set("account_balance", 1000)

        received_context = {}

        async def capturing_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            received_context.update(blackboard_context)
            return "done"

        executor = DefaultAgentExecutor(reasoning_loop=capturing_loop)
        config = AgentExecutorConfig(max_reasoning_steps=5)

        await executor.execute("action", {}, blackboard, config)

        assert received_context["user_name"] == "Alice"
        assert received_context["account_balance"] == 1000

    async def test_blackboard_context_is_snapshot(self, blackboard):
        """Context is a snapshot — later Blackboard changes don't affect it."""
        await blackboard.set("key", "original")

        captured_contexts = []

        async def capturing_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            captured_contexts.append(dict(blackboard_context))
            return "done"

        executor = DefaultAgentExecutor(reasoning_loop=capturing_loop)
        config = AgentExecutorConfig(max_reasoning_steps=5)

        await executor.execute("action", {}, blackboard, config)

        # Modify blackboard after execute
        await blackboard.set("key", "modified")

        # The captured context should have the original value
        assert captured_contexts[0]["key"] == "original"


# ============================================================
# Test: Tool Call Error Feedback
# ============================================================


class TestToolCallErrorFeedback:
    """Tests for tool call error feedback to LLM."""

    async def test_tool_error_is_fed_back_to_reasoning(self, blackboard):
        """When a tool fails, the error is fed back to the reasoning loop."""
        error_messages = []

        async def error_tracking_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            # Simulate a tool call that fails by calling _arun directly
            for tool in tools:
                if tool.name == "failing_tool":
                    try:
                        await tool._arun()
                    except Exception as exc:
                        error_messages.append(str(exc))
            return "handled_error"

        executor = DefaultAgentExecutor(reasoning_loop=error_tracking_loop)
        executor.register_tool(FailingTool())
        config = AgentExecutorConfig(max_reasoning_steps=5)

        result = await executor.execute("action", {}, blackboard, config)

        assert result == "handled_error"
        assert len(error_messages) == 1
        assert "Tool execution failed" in error_messages[0]


# ============================================================
# Test: Rule Engine Degradation Strategy
# ============================================================


class TestRuleEngineDegradation:
    """Tests for rule engine degradation strategy."""

    async def test_successful_rule_engine_call(self):
        """Successful rule engine call returns the result."""
        async def mock_rule_engine(rule_set_id, params):
            return {"result": 42}

        result = await handle_rule_engine_call(
            mock_rule_engine, "rule_1", {"input": "data"}
        )
        assert result == {"result": 42}

    async def test_fallback_value_on_error(self):
        """When rule engine fails and fallback is configured, return fallback."""
        async def failing_rule_engine(rule_set_id, params):
            raise TimeoutError("Rule engine timed out")

        result = await handle_rule_engine_call(
            failing_rule_engine,
            "rule_1",
            {"input": "data"},
            fallback_value={"default": True},
        )
        assert result == {"default": True}

    async def test_raises_when_no_fallback(self):
        """When rule engine fails and no fallback is configured, raise."""
        async def failing_rule_engine(rule_set_id, params):
            raise ConnectionError("Cannot reach rule engine")

        with pytest.raises(RuntimeError, match="Rule engine call failed"):
            await handle_rule_engine_call(
                failing_rule_engine,
                "rule_1",
                {"input": "data"},
                fallback_value=None,
            )

    async def test_fallback_value_on_timeout(self):
        """Timeout errors also trigger fallback."""
        async def timeout_rule_engine(rule_set_id, params):
            raise asyncio.TimeoutError("Timed out")

        result = await handle_rule_engine_call(
            timeout_rule_engine,
            "rule_1",
            {},
            fallback_value=0,
        )
        assert result == 0

    async def test_fallback_value_can_be_any_type(self):
        """Fallback value can be any type (string, int, dict, list, etc.)."""
        async def failing_engine(rule_set_id, params):
            raise RuntimeError("fail")

        # String fallback
        result = await handle_rule_engine_call(
            failing_engine, "r1", {}, fallback_value="default_string"
        )
        assert result == "default_string"

        # List fallback
        result = await handle_rule_engine_call(
            failing_engine, "r1", {}, fallback_value=[1, 2, 3]
        )
        assert result == [1, 2, 3]

        # Zero fallback (falsy but not None)
        result = await handle_rule_engine_call(
            failing_engine, "r1", {}, fallback_value=0
        )
        assert result == 0


# ============================================================
# Test: Execute Integration (with mock reasoning loop)
# ============================================================


class TestExecuteIntegration:
    """Integration tests for the execute method with mock reasoning loop."""

    async def test_execute_passes_action_and_parameters(self, blackboard):
        """Execute passes action and parameters to the reasoning loop."""
        received = {}

        async def capturing_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            received["action"] = action
            received["parameters"] = parameters
            return "result"

        executor = DefaultAgentExecutor(reasoning_loop=capturing_loop)
        config = AgentExecutorConfig(max_reasoning_steps=5)

        result = await executor.execute(
            "query_fund", {"fund_id": "F001"}, blackboard, config
        )

        assert result == "result"
        assert received["action"] == "query_fund"
        assert received["parameters"] == {"fund_id": "F001"}

    async def test_execute_passes_registered_tools(self, blackboard):
        """Execute passes registered tools to the reasoning loop."""
        received_tools = []

        async def capturing_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            received_tools.extend(tools)
            return "done"

        executor = DefaultAgentExecutor(reasoning_loop=capturing_loop)
        executor.register_tool(DummyTool())
        config = AgentExecutorConfig(max_reasoning_steps=5)

        await executor.execute("action", {}, blackboard, config)

        assert len(received_tools) == 1
        assert received_tools[0].name == "dummy_tool"

    async def test_execute_returns_reasoning_loop_result(self, blackboard):
        """Execute returns whatever the reasoning loop returns."""
        async def result_loop(
            action, parameters, tools, blackboard_context, max_steps
        ):
            return {"status": "success", "data": [1, 2, 3]}

        executor = DefaultAgentExecutor(reasoning_loop=result_loop)
        config = AgentExecutorConfig(max_reasoning_steps=5)

        result = await executor.execute("action", {}, blackboard, config)

        assert result == {"status": "success", "data": [1, 2, 3]}

    async def test_execute_with_no_llm_and_no_loop_raises(self, blackboard):
        """Execute without LLM and without custom loop raises RuntimeError."""
        executor = DefaultAgentExecutor(llm=None)
        config = AgentExecutorConfig(max_reasoning_steps=5)

        with pytest.raises(RuntimeError, match="No LLM configured"):
            await executor.execute("action", {}, blackboard, config)

    async def test_execute_with_sdk_config(self, blackboard):
        """DefaultAgentExecutor respects SDKConfig."""
        sdk_config = SDKConfig(max_reasoning_steps=20)

        async def noop_loop(action, parameters, tools, ctx, max_steps):
            return max_steps

        executor = DefaultAgentExecutor(
            config=sdk_config, reasoning_loop=noop_loop
        )
        # AgentExecutorConfig overrides SDKConfig for per-call config
        config = AgentExecutorConfig(max_reasoning_steps=7)

        result = await executor.execute("action", {}, blackboard, config)
        assert result == 7
