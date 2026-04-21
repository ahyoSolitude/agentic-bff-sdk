"""Property-based tests for configuration models.

Uses Hypothesis to generate random OrchestrationConfig instances and verify
YAML/JSON round-trip serialization correctness.
"""

import pytest
from hypothesis import given, settings, strategies as st

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
# Hypothesis Strategies
# ============================================================

# Safe text strategy: printable strings that survive YAML/JSON round-trips.
# Avoid control characters, null bytes, and excessively long strings.
safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00\ufeff",
    ),
    min_size=1,
    max_size=50,
)

# Non-empty identifier-like strings for IDs and names
safe_id = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=1,
    max_size=30,
)

# Safe float strategy: finite floats that survive JSON/YAML round-trips.
# Avoid NaN, Inf, -Inf, and subnormal values.
safe_positive_float = st.floats(
    min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False
)

safe_unit_float = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

safe_positive_int = st.integers(min_value=1, max_value=100_000)

# JSON-safe primitive values for Dict[str, Any] fields
json_primitive = st.one_of(
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    safe_text,
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)

# Simple JSON-safe dict (one level deep to keep generation fast)
json_safe_dict = st.dictionaries(
    keys=safe_id,
    values=json_primitive,
    max_size=5,
)

# ToolDefinition strategy
tool_definition_st = st.builds(
    ToolDefinition,
    name=safe_id,
    description=safe_text,
    input_schema=json_safe_dict,
)

# AgentExecutorConfig strategy
agent_executor_config_st = st.builds(
    AgentExecutorConfig,
    max_reasoning_steps=st.integers(min_value=1, max_value=100),
    tools=st.lists(tool_definition_st, max_size=3),
)

# InteractionScene strategy
interaction_scene_st = st.sampled_from(list(InteractionScene))

# SOPDefinition strategy
sop_definition_st = st.builds(
    SOPDefinition,
    sop_id=safe_id,
    name=safe_text,
    steps=st.lists(json_safe_dict, min_size=1, max_size=5),
    exception_policies=st.dictionaries(
        keys=safe_id,
        values=st.sampled_from(["retry", "skip", "rollback"]),
        min_size=1,
        max_size=3,
    ),
    dialog_templates=st.dictionaries(
        keys=interaction_scene_st,
        values=safe_text,
        min_size=1,
        max_size=3,
    ),
)

# SDKConfig strategy
sdk_config_st = st.builds(
    SDKConfig,
    session_idle_timeout_seconds=safe_positive_int,
    max_dialog_history_turns=safe_positive_int,
    dialog_summary_threshold=safe_positive_int,
    intent_confidence_threshold=safe_unit_float,
    intent_ambiguity_range=safe_unit_float,
    plan_generation_timeout_seconds=safe_positive_float,
    step_execution_timeout_seconds=safe_positive_float,
    max_reasoning_steps=st.integers(min_value=1, max_value=100),
    fan_in_wait_timeout_seconds=safe_positive_float,
    blackboard_key_ttl_seconds=safe_positive_int,
    async_task_callback_url=st.one_of(st.none(), safe_text),
    async_task_callback_type=st.sampled_from(["webhook", "mq"]),
    synthesis_quality_threshold=safe_unit_float,
    max_cross_llm_loops=st.integers(min_value=1, max_value=20),
    rule_engine_base_url=st.one_of(st.none(), safe_text),
    rule_engine_timeout_seconds=safe_positive_float,
    rule_engine_cache_ttl_seconds=safe_positive_int,
)

# ChannelAdapterConfig strategy
channel_adapter_config_st = st.builds(
    ChannelAdapterConfig,
    channel_id=safe_id,
    channel_name=safe_text,
    capabilities=json_safe_dict,
    adapter_class=safe_text,
)

# TaskPackageConfig strategy
task_package_config_st = st.builds(
    TaskPackageConfig,
    domain=safe_id,
    name=safe_text,
    tools=st.lists(tool_definition_st, max_size=3),
    protocol=st.sampled_from(["http", "grpc"]),
    base_url=safe_text,
    timeout_seconds=safe_positive_float,
)

# OrchestrationConfig strategy
orchestration_config_st = st.builds(
    OrchestrationConfig,
    sdk=sdk_config_st,
    channels=st.lists(channel_adapter_config_st, max_size=3),
    task_packages=st.lists(task_package_config_st, max_size=3),
    priority_rules=st.lists(json_safe_dict, max_size=3),
    sop_definitions=st.lists(sop_definition_st, max_size=2),
)


# ============================================================
# Property 29: 编排配置 Round-Trip
# ============================================================


@pytest.mark.property
class TestOrchestrationConfigRoundTrip:
    """Property 29: 编排配置 Round-Trip

    For any valid OrchestrationConfig, serializing to YAML/JSON and
    deserializing back should produce an equivalent instance.

    **Validates: Requirements 12.2**
    """

    @given(config=orchestration_config_st)
    @settings(max_examples=100)
    def test_json_round_trip(self, config: OrchestrationConfig):
        """JSON round-trip: serialize to JSON then deserialize should equal original.

        **Validates: Requirements 12.2**
        """
        json_str = config.to_json()
        restored = OrchestrationConfig.from_json(json_str)
        assert restored == config

    @given(config=orchestration_config_st)
    @settings(max_examples=100)
    def test_yaml_round_trip(self, config: OrchestrationConfig):
        """YAML round-trip: serialize to YAML then deserialize should equal original.

        **Validates: Requirements 12.2**
        """
        yaml_str = config.to_yaml()
        restored = OrchestrationConfig.from_yaml(yaml_str)
        assert restored == config
