"""Tests for the configuration models."""

import json

import pytest
import yaml

from agentic_bff_sdk.config import (
    AgentExecutorConfig,
    ChannelAdapterConfig,
    InteractionScene,
    OrchestrationConfig,
    SDKConfig,
    SOPDefinition,
    TaskPackageConfig,
    ToolDefinition,
)


# ============================================================
# InteractionScene Tests
# ============================================================


class TestInteractionScene:
    def test_enum_values(self):
        assert InteractionScene.PHONE == "phone"
        assert InteractionScene.FACE_TO_FACE == "face_to_face"
        assert InteractionScene.ONLINE == "online"

    def test_str_serialization(self):
        assert str(InteractionScene.PHONE) == "InteractionScene.PHONE"
        assert InteractionScene.PHONE.value == "phone"


# ============================================================
# ToolDefinition Tests
# ============================================================


class TestToolDefinition:
    def test_basic_creation(self):
        tool = ToolDefinition(
            name="search",
            description="Search for information",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        assert tool.name == "search"
        assert tool.description == "Search for information"
        assert "query" in tool.input_schema["properties"]

    def test_serialization_round_trip(self):
        tool = ToolDefinition(
            name="calc",
            description="Calculator",
            input_schema={"type": "object"},
        )
        data = tool.model_dump()
        restored = ToolDefinition.model_validate(data)
        assert restored == tool


# ============================================================
# AgentExecutorConfig Tests
# ============================================================


class TestAgentExecutorConfig:
    def test_defaults(self):
        config = AgentExecutorConfig()
        assert config.max_reasoning_steps == 10
        assert config.tools == []

    def test_with_tools(self):
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
        )
        config = AgentExecutorConfig(max_reasoning_steps=5, tools=[tool])
        assert config.max_reasoning_steps == 5
        assert len(config.tools) == 1
        assert config.tools[0].name == "test_tool"


# ============================================================
# SOPDefinition Tests
# ============================================================


class TestSOPDefinition:
    def test_basic_creation(self):
        sop = SOPDefinition(
            sop_id="sop-001",
            name="Customer Onboarding",
            steps=[{"action": "verify_identity"}, {"action": "create_account"}],
            exception_policies={"timeout": "retry", "validation_error": "skip"},
            dialog_templates={
                InteractionScene.PHONE: "Phone template: {step}",
                InteractionScene.ONLINE: "Online template: {step}",
            },
        )
        assert sop.sop_id == "sop-001"
        assert len(sop.steps) == 2
        assert sop.exception_policies["timeout"] == "retry"
        assert InteractionScene.PHONE in sop.dialog_templates

    def test_serialization_round_trip(self):
        sop = SOPDefinition(
            sop_id="sop-002",
            name="Test SOP",
            steps=[{"action": "step1"}],
            exception_policies={"error": "rollback"},
            dialog_templates={InteractionScene.FACE_TO_FACE: "Face to face: {step}"},
        )
        data = sop.model_dump(mode="json")
        restored = SOPDefinition.model_validate(data)
        assert restored == sop


# ============================================================
# SDKConfig Tests
# ============================================================


class TestSDKConfig:
    def test_defaults(self):
        config = SDKConfig()
        assert config.session_idle_timeout_seconds == 1800
        assert config.max_dialog_history_turns == 50
        assert config.dialog_summary_threshold == 30
        assert config.intent_confidence_threshold == 0.7
        assert config.intent_ambiguity_range == 0.1
        assert config.plan_generation_timeout_seconds == 30.0
        assert config.step_execution_timeout_seconds == 60.0
        assert config.max_reasoning_steps == 10
        assert config.fan_in_wait_timeout_seconds == 120.0
        assert config.blackboard_key_ttl_seconds == 3600
        assert config.async_task_callback_url is None
        assert config.async_task_callback_type == "webhook"
        assert config.synthesis_quality_threshold == 0.7
        assert config.max_cross_llm_loops == 3
        assert config.rule_engine_base_url is None
        assert config.rule_engine_timeout_seconds == 10.0
        assert config.rule_engine_cache_ttl_seconds == 300

    def test_custom_values(self):
        config = SDKConfig(
            session_idle_timeout_seconds=3600,
            intent_confidence_threshold=0.8,
            max_reasoning_steps=20,
            rule_engine_base_url="http://rule-engine:8080",
        )
        assert config.session_idle_timeout_seconds == 3600
        assert config.intent_confidence_threshold == 0.8
        assert config.max_reasoning_steps == 20
        assert config.rule_engine_base_url == "http://rule-engine:8080"


# ============================================================
# ChannelAdapterConfig Tests
# ============================================================


class TestChannelAdapterConfig:
    def test_basic_creation(self):
        config = ChannelAdapterConfig(
            channel_id="web",
            channel_name="Web Channel",
            capabilities={"supports_charts": True, "max_cards": 10},
            adapter_class="myapp.adapters.WebAdapter",
        )
        assert config.channel_id == "web"
        assert config.channel_name == "Web Channel"
        assert config.capabilities["supports_charts"] is True
        assert config.adapter_class == "myapp.adapters.WebAdapter"

    def test_empty_capabilities(self):
        config = ChannelAdapterConfig(
            channel_id="sms",
            channel_name="SMS Channel",
            adapter_class="myapp.adapters.SMSAdapter",
        )
        assert config.capabilities == {}


# ============================================================
# TaskPackageConfig Tests
# ============================================================


class TestTaskPackageConfig:
    def test_basic_creation(self):
        config = TaskPackageConfig(
            domain="fund",
            name="Fund Management",
            base_url="http://fund-service:8080",
        )
        assert config.domain == "fund"
        assert config.name == "Fund Management"
        assert config.protocol == "http"
        assert config.base_url == "http://fund-service:8080"
        assert config.timeout_seconds == 30.0
        assert config.tools == []

    def test_with_tools_and_grpc(self):
        tool = ToolDefinition(
            name="query_fund",
            description="Query fund info",
            input_schema={"type": "object"},
        )
        config = TaskPackageConfig(
            domain="fund",
            name="Fund Management",
            tools=[tool],
            protocol="grpc",
            base_url="fund-service:50051",
            timeout_seconds=15.0,
        )
        assert config.protocol == "grpc"
        assert len(config.tools) == 1
        assert config.timeout_seconds == 15.0


# ============================================================
# OrchestrationConfig Tests
# ============================================================


class TestOrchestrationConfig:
    def _make_full_config(self) -> OrchestrationConfig:
        """Create a fully populated OrchestrationConfig for testing."""
        return OrchestrationConfig(
            sdk=SDKConfig(
                session_idle_timeout_seconds=900,
                intent_confidence_threshold=0.8,
                rule_engine_base_url="http://rules:8080",
            ),
            channels=[
                ChannelAdapterConfig(
                    channel_id="web",
                    channel_name="Web",
                    capabilities={"charts": True},
                    adapter_class="app.WebAdapter",
                ),
            ],
            task_packages=[
                TaskPackageConfig(
                    domain="fund",
                    name="Fund Mgmt",
                    base_url="http://fund:8080",
                    tools=[
                        ToolDefinition(
                            name="query",
                            description="Query fund",
                            input_schema={"type": "object"},
                        )
                    ],
                ),
            ],
            priority_rules=[{"pattern": "transfer*", "intent": "transfer"}],
            sop_definitions=[
                SOPDefinition(
                    sop_id="sop-1",
                    name="Onboarding",
                    steps=[{"action": "verify"}],
                    exception_policies={"timeout": "retry"},
                    dialog_templates={InteractionScene.PHONE: "Hello {name}"},
                ),
            ],
        )

    def test_defaults(self):
        config = OrchestrationConfig()
        assert config.sdk == SDKConfig()
        assert config.channels == []
        assert config.task_packages == []
        assert config.priority_rules == []
        assert config.sop_definitions == []

    def test_json_round_trip(self):
        original = self._make_full_config()
        json_str = original.to_json()
        restored = OrchestrationConfig.from_json(json_str)
        assert restored == original

    def test_yaml_round_trip(self):
        original = self._make_full_config()
        yaml_str = original.to_yaml()
        restored = OrchestrationConfig.from_yaml(yaml_str)
        assert restored == original

    def test_json_is_valid_json(self):
        config = self._make_full_config()
        json_str = config.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "sdk" in parsed
        assert "channels" in parsed

    def test_yaml_is_valid_yaml(self):
        config = self._make_full_config()
        yaml_str = config.to_yaml()
        parsed = yaml.safe_load(yaml_str)
        assert isinstance(parsed, dict)
        assert "sdk" in parsed
        assert "channels" in parsed

    def test_from_file_yaml(self, tmp_path):
        config = self._make_full_config()
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(config.to_yaml(), encoding="utf-8")
        restored = OrchestrationConfig.from_file(yaml_file)
        assert restored == config

    def test_from_file_json(self, tmp_path):
        config = self._make_full_config()
        json_file = tmp_path / "config.json"
        json_file.write_text(config.to_json(), encoding="utf-8")
        restored = OrchestrationConfig.from_file(json_file)
        assert restored == config

    def test_from_file_yml_extension(self, tmp_path):
        config = self._make_full_config()
        yml_file = tmp_path / "config.yml"
        yml_file.write_text(config.to_yaml(), encoding="utf-8")
        restored = OrchestrationConfig.from_file(yml_file)
        assert restored == config

    def test_from_file_unsupported_extension(self, tmp_path):
        txt_file = tmp_path / "config.txt"
        txt_file.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported config file format"):
            OrchestrationConfig.from_file(txt_file)

    def test_from_file_accepts_string_path(self, tmp_path):
        config = OrchestrationConfig()
        json_file = tmp_path / "config.json"
        json_file.write_text(config.to_json(), encoding="utf-8")
        restored = OrchestrationConfig.from_file(str(json_file))
        assert restored == config
