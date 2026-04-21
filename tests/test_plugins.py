"""Tests for the plugin system and channel adapter (agentic_bff_sdk/plugins.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool

from agentic_bff_sdk.agent_executor import AgentExecutor
from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.card_generator import CardGenerator
from agentic_bff_sdk.config import AgentExecutorConfig
from agentic_bff_sdk.models import (
    CardOutput,
    Card,
    CardType,
    RequestMessage,
    SynthesisResult,
)
from agentic_bff_sdk.plugins import (
    ChannelAdapter,
    DefaultChannelAdapter,
    PluginRegistry,
)
from agentic_bff_sdk.router import TopLevelRouter


# ============================================================
# Concrete test implementations
# ============================================================


class _StubRouter(TopLevelRouter):
    """Minimal concrete TopLevelRouter for testing."""

    async def route(self, user_input, session_state, mode=None):
        return None  # type: ignore

    def register_priority_rule(self, rule):
        pass

    def register_fallback_handler(self, handler):
        pass


class _StubExecutor(AgentExecutor):
    """Minimal concrete AgentExecutor for testing."""

    async def execute(self, action, parameters, blackboard, config):
        return None

    def register_tool(self, tool):
        pass


class _StubGenerator(CardGenerator):
    """Minimal concrete CardGenerator for testing."""

    async def generate(self, synthesis, channel_capabilities):
        return CardOutput(cards=[], raw_text="stub")


class _StubChannelAdapter(ChannelAdapter):
    """Minimal concrete ChannelAdapter for testing."""

    async def adapt_request(self, request):
        return RequestMessage(
            user_input="adapted", session_id="s1", channel_id="c1"
        )

    async def adapt_response(self, response):
        return {"adapted": True}


class _StubTool(BaseTool):
    """Minimal concrete BaseTool for testing."""

    name: str = "stub_tool"
    description: str = "A stub tool"

    def _run(self, *args: Any, **kwargs: Any) -> str:
        return "stub result"


# ============================================================
# ChannelAdapter ABC
# ============================================================


class TestChannelAdapterABC:
    """Tests for the ChannelAdapter abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ChannelAdapter()  # type: ignore[abstract]

    def test_concrete_subclass(self) -> None:
        adapter = _StubChannelAdapter()
        assert isinstance(adapter, ChannelAdapter)


# ============================================================
# DefaultChannelAdapter
# ============================================================


class TestDefaultChannelAdapter:
    """Tests for the DefaultChannelAdapter pass-through implementation."""

    async def test_adapt_request_passthrough(self) -> None:
        adapter = DefaultChannelAdapter()
        msg = RequestMessage(
            user_input="hello", session_id="s1", channel_id="c1"
        )
        result = await adapter.adapt_request(msg)
        assert result is msg

    async def test_adapt_request_from_dict(self) -> None:
        adapter = DefaultChannelAdapter()
        data = {
            "user_input": "hello",
            "session_id": "s1",
            "channel_id": "c1",
        }
        result = await adapter.adapt_request(data)
        assert isinstance(result, RequestMessage)
        assert result.user_input == "hello"
        assert result.session_id == "s1"

    async def test_adapt_request_invalid_type(self) -> None:
        adapter = DefaultChannelAdapter()
        with pytest.raises(TypeError, match="cannot adapt request"):
            await adapter.adapt_request(42)

    async def test_adapt_response_passthrough(self) -> None:
        adapter = DefaultChannelAdapter()
        response = {"content": "test"}
        result = await adapter.adapt_response(response)
        assert result is response


# ============================================================
# PluginRegistry
# ============================================================


class TestPluginRegistry:
    """Tests for the PluginRegistry class."""

    def test_initial_state(self) -> None:
        registry = PluginRegistry()
        assert registry.router is None
        assert registry.executor is None
        assert registry.generator is None
        assert registry.channel_adapters == {}
        assert registry.tools == []
        assert registry.chains == []

    # -- Router registration --

    def test_register_router(self) -> None:
        registry = PluginRegistry()
        router = _StubRouter()
        registry.register_router(router)
        assert registry.router is router

    def test_register_router_invalid_type(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(TypeError, match="Expected TopLevelRouter"):
            registry.register_router("not a router")  # type: ignore

    # -- Executor registration --

    def test_register_executor(self) -> None:
        registry = PluginRegistry()
        executor = _StubExecutor()
        registry.register_executor(executor)
        assert registry.executor is executor

    def test_register_executor_invalid_type(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(TypeError, match="Expected AgentExecutor"):
            registry.register_executor("not an executor")  # type: ignore

    # -- Generator registration --

    def test_register_generator(self) -> None:
        registry = PluginRegistry()
        gen = _StubGenerator()
        registry.register_generator(gen)
        assert registry.generator is gen

    def test_register_generator_invalid_type(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(TypeError, match="Expected CardGenerator"):
            registry.register_generator("not a generator")  # type: ignore

    # -- Channel adapter registration --

    def test_register_channel_adapter(self) -> None:
        registry = PluginRegistry()
        adapter = _StubChannelAdapter()
        registry.register_channel_adapter("web", adapter)
        assert registry.get_channel_adapter("web") is adapter

    def test_register_channel_adapter_invalid_type(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(TypeError, match="Expected ChannelAdapter"):
            registry.register_channel_adapter("web", "not an adapter")  # type: ignore

    def test_get_channel_adapter_not_found(self) -> None:
        registry = PluginRegistry()
        assert registry.get_channel_adapter("unknown") is None

    def test_multiple_channel_adapters(self) -> None:
        registry = PluginRegistry()
        adapter1 = _StubChannelAdapter()
        adapter2 = DefaultChannelAdapter()
        registry.register_channel_adapter("web", adapter1)
        registry.register_channel_adapter("mobile", adapter2)
        assert len(registry.channel_adapters) == 2
        assert registry.get_channel_adapter("web") is adapter1
        assert registry.get_channel_adapter("mobile") is adapter2

    # -- Tool registration --

    def test_register_tool(self) -> None:
        registry = PluginRegistry()
        tool = _StubTool()
        registry.register_tool(tool)
        assert len(registry.tools) == 1
        assert registry.tools[0].name == "stub_tool"

    def test_register_tool_invalid_type(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(TypeError, match="Expected BaseTool"):
            registry.register_tool("not a tool")  # type: ignore

    def test_register_multiple_tools(self) -> None:
        registry = PluginRegistry()
        tool1 = _StubTool()
        tool2 = _StubTool()
        registry.register_tool(tool1)
        registry.register_tool(tool2)
        assert len(registry.tools) == 2

    # -- Chain registration --

    def test_register_chain(self) -> None:
        registry = PluginRegistry()
        chain = MagicMock()
        registry.register_chain(chain)
        assert len(registry.chains) == 1

    # -- Generic register method --

    def test_generic_register_router(self) -> None:
        registry = PluginRegistry()
        router = _StubRouter()
        registry.register("router", router)
        assert registry.router is router

    def test_generic_register_executor(self) -> None:
        registry = PluginRegistry()
        executor = _StubExecutor()
        registry.register("executor", executor)
        assert registry.executor is executor

    def test_generic_register_generator(self) -> None:
        registry = PluginRegistry()
        gen = _StubGenerator()
        registry.register("generator", gen)
        assert registry.generator is gen

    def test_generic_register_channel_adapter(self) -> None:
        registry = PluginRegistry()
        adapter = _StubChannelAdapter()
        registry.register("channel_adapter", adapter, channel_id="phone")
        assert registry.get_channel_adapter("phone") is adapter

    def test_generic_register_channel_adapter_default_id(self) -> None:
        registry = PluginRegistry()
        adapter = _StubChannelAdapter()
        registry.register("channel_adapter", adapter)
        assert registry.get_channel_adapter("default") is adapter

    def test_generic_register_tool(self) -> None:
        registry = PluginRegistry()
        tool = _StubTool()
        registry.register("tool", tool)
        assert len(registry.tools) == 1

    def test_generic_register_chain(self) -> None:
        registry = PluginRegistry()
        chain = MagicMock()
        registry.register("chain", chain)
        assert len(registry.chains) == 1

    def test_generic_register_unknown_type(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(ValueError, match="Unknown plugin type"):
            registry.register("unknown_type", MagicMock())

    # -- Overwrite behavior --

    def test_router_overwrite(self) -> None:
        registry = PluginRegistry()
        router1 = _StubRouter()
        router2 = _StubRouter()
        registry.register_router(router1)
        registry.register_router(router2)
        assert registry.router is router2

    def test_channel_adapter_overwrite(self) -> None:
        registry = PluginRegistry()
        adapter1 = _StubChannelAdapter()
        adapter2 = DefaultChannelAdapter()
        registry.register_channel_adapter("web", adapter1)
        registry.register_channel_adapter("web", adapter2)
        assert registry.get_channel_adapter("web") is adapter2
