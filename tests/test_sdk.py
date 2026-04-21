"""Tests for the SDK factory (agentic_bff_sdk/sdk.py)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from agentic_bff_sdk.card_generator import DefaultCardGenerator
from agentic_bff_sdk.config import (
    ChannelAdapterConfig,
    OrchestrationConfig,
    SDKConfig,
    TaskPackageConfig,
)
from agentic_bff_sdk.gateway import DefaultMASGateway
from agentic_bff_sdk.plugins import DefaultChannelAdapter, PluginRegistry
from agentic_bff_sdk.sdk import create_sdk


# ============================================================
# Helpers — minimal stubs for required components
# ============================================================


def _make_stub_router():
    """Create a minimal stub TopLevelRouter."""
    from agentic_bff_sdk.router import TopLevelRouter

    class _R(TopLevelRouter):
        async def route(self, user_input, session_state, mode=None):
            return None  # type: ignore

        def register_priority_rule(self, rule):
            pass

        def register_fallback_handler(self, handler):
            pass

    return _R()


def _make_stub_planner():
    """Create a minimal stub IMCPlanner."""
    from agentic_bff_sdk.planner import IMCPlanner

    class _P(IMCPlanner):
        async def generate_plan(self, intent, session_state, timeout_seconds=None):
            return None  # type: ignore

        async def persist_plan(self, plan):
            return "plan-id"

    return _P()


def _make_stub_synthesizer():
    """Create a minimal stub Synthesizer."""
    from agentic_bff_sdk.synthesizer import Synthesizer

    class _S(Synthesizer):
        async def synthesize(self, aggregated, session_state, quality_threshold=0.7):
            return None  # type: ignore

    return _S()


# ============================================================
# create_sdk Tests
# ============================================================


class TestCreateSDK:
    """Tests for the create_sdk factory function."""

    def test_create_with_all_required_components(self) -> None:
        config = OrchestrationConfig()
        gw = create_sdk(
            config,
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
        )
        assert isinstance(gw, DefaultMASGateway)

    def test_missing_router_raises(self) -> None:
        config = OrchestrationConfig()
        with pytest.raises(ValueError, match="TopLevelRouter must be provided"):
            create_sdk(
                config,
                planner=_make_stub_planner(),
                synthesizer=_make_stub_synthesizer(),
            )

    def test_missing_planner_raises(self) -> None:
        config = OrchestrationConfig()
        with pytest.raises(ValueError, match="IMCPlanner must be provided"):
            create_sdk(
                config,
                router=_make_stub_router(),
                synthesizer=_make_stub_synthesizer(),
            )

    def test_missing_synthesizer_raises(self) -> None:
        config = OrchestrationConfig()
        with pytest.raises(ValueError, match="Synthesizer must be provided"):
            create_sdk(
                config,
                router=_make_stub_router(),
                planner=_make_stub_planner(),
            )

    def test_router_from_plugin_registry(self) -> None:
        config = OrchestrationConfig()
        registry = PluginRegistry()
        registry.register_router(_make_stub_router())
        gw = create_sdk(
            config,
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
            plugin_registry=registry,
        )
        assert isinstance(gw, DefaultMASGateway)

    def test_custom_card_generator(self) -> None:
        config = OrchestrationConfig()
        custom_gen = DefaultCardGenerator()
        gw = create_sdk(
            config,
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
            card_generator=custom_gen,
        )
        assert isinstance(gw, DefaultMASGateway)

    def test_load_from_yaml_file(self, tmp_path: Path) -> None:
        config_data = OrchestrationConfig().model_dump(mode="json")
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml.dump(config_data))

        gw = create_sdk(
            str(yaml_file),
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
        )
        assert isinstance(gw, DefaultMASGateway)

    def test_load_from_json_file(self, tmp_path: Path) -> None:
        config_data = OrchestrationConfig().model_dump(mode="json")
        json_file = tmp_path / "config.json"
        json_file.write_text(json.dumps(config_data))

        gw = create_sdk(
            json_file,
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
        )
        assert isinstance(gw, DefaultMASGateway)

    def test_channels_registered_from_config(self) -> None:
        config = OrchestrationConfig(
            channels=[
                ChannelAdapterConfig(
                    channel_id="web",
                    channel_name="Web Channel",
                    adapter_class="agentic_bff_sdk.plugins.DefaultChannelAdapter",
                ),
                ChannelAdapterConfig(
                    channel_id="mobile",
                    channel_name="Mobile Channel",
                    adapter_class="agentic_bff_sdk.plugins.DefaultChannelAdapter",
                ),
            ]
        )
        registry = PluginRegistry()
        gw = create_sdk(
            config,
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
            plugin_registry=registry,
        )
        assert isinstance(gw, DefaultMASGateway)
        # Verify channel adapters were registered in the registry
        assert registry.get_channel_adapter("web") is not None
        assert registry.get_channel_adapter("mobile") is not None

    def test_tools_registered_from_registry(self) -> None:
        from langchain_core.tools import BaseTool
        from typing import Any

        class _T(BaseTool):
            name: str = "test_tool"
            description: str = "test"

            def _run(self, *args: Any, **kwargs: Any) -> str:
                return "ok"

        config = OrchestrationConfig()
        registry = PluginRegistry()
        registry.register_tool(_T())

        gw = create_sdk(
            config,
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
            plugin_registry=registry,
        )
        assert isinstance(gw, DefaultMASGateway)
        # Tool should be registered as a plugin in the gateway
        assert "tool" in gw.plugins

    def test_sdk_config_propagated(self) -> None:
        custom_config = SDKConfig(session_idle_timeout_seconds=999)
        config = OrchestrationConfig(sdk=custom_config)
        gw = create_sdk(
            config,
            router=_make_stub_router(),
            planner=_make_stub_planner(),
            synthesizer=_make_stub_synthesizer(),
        )
        assert gw.config.session_idle_timeout_seconds == 999
