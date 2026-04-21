"""Configuration models for the Agentic BFF SDK.

All configuration models are based on Pydantic BaseModel.
OrchestrationConfig supports serialization to/from YAML and JSON.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel


# ============================================================
# SOP Related Models
# ============================================================


class InteractionScene(str, Enum):
    """交互场景枚举。"""

    PHONE = "phone"
    FACE_TO_FACE = "face_to_face"
    ONLINE = "online"


class SOPDefinition(BaseModel):
    """SOP 定义模型。"""

    sop_id: str
    name: str
    steps: List[Dict[str, Any]]
    exception_policies: Dict[str, str]  # error_type -> action (retry/skip/rollback)
    dialog_templates: Dict[InteractionScene, str]


# ============================================================
# Tool & Agent Executor Config
# ============================================================


class ToolDefinition(BaseModel):
    """工具定义模型。"""

    name: str
    description: str
    input_schema: Dict[str, Any]


class AgentExecutorConfig(BaseModel):
    """Agent 执行器配置。"""

    max_reasoning_steps: int = 10
    tools: List[ToolDefinition] = []


# ============================================================
# SDK Global Config
# ============================================================


class SDKConfig(BaseModel):
    """SDK 全局配置。"""

    # 会话管理
    session_idle_timeout_seconds: int = 1800  # 30 分钟
    max_dialog_history_turns: int = 50
    dialog_summary_threshold: int = 30

    # 意图路由
    intent_confidence_threshold: float = 0.7
    intent_ambiguity_range: float = 0.1

    # 执行控制
    plan_generation_timeout_seconds: float = 30.0
    step_execution_timeout_seconds: float = 60.0
    max_reasoning_steps: int = 10
    fan_in_wait_timeout_seconds: float = 120.0

    # Blackboard
    blackboard_key_ttl_seconds: int = 3600  # 1 小时

    # 异步任务
    async_task_callback_url: Optional[str] = None
    async_task_callback_type: str = "webhook"  # webhook | mq

    # 综合决策
    synthesis_quality_threshold: float = 0.7
    max_cross_llm_loops: int = 3

    # 规则引擎
    rule_engine_base_url: Optional[str] = None
    rule_engine_timeout_seconds: float = 10.0
    rule_engine_cache_ttl_seconds: int = 300


# ============================================================
# Channel & Task Package Config
# ============================================================


class ChannelAdapterConfig(BaseModel):
    """渠道适配器配置。"""

    channel_id: str
    channel_name: str
    capabilities: Dict[str, Any] = {}  # 渠道渲染能力描述
    adapter_class: str  # 适配器类的完整路径


class TaskPackageConfig(BaseModel):
    """领域任务包配置。"""

    domain: str
    name: str
    tools: List[ToolDefinition] = []
    protocol: str = "http"  # http | grpc
    base_url: str
    timeout_seconds: float = 30.0


# ============================================================
# Orchestration Config (supports YAML/JSON)
# ============================================================


class OrchestrationConfig(BaseModel):
    """编排流程配置（YAML/JSON 声明式）。"""

    sdk: SDKConfig = SDKConfig()
    channels: List[ChannelAdapterConfig] = []
    task_packages: List[TaskPackageConfig] = []
    priority_rules: List[Dict[str, Any]] = []
    sop_definitions: List[SOPDefinition] = []

    def to_yaml(self) -> str:
        """序列化为 YAML 字符串。"""
        return yaml.dump(
            self.model_dump(mode="json"),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON 字符串。"""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "OrchestrationConfig":
        """从 YAML 字符串反序列化。"""
        data = yaml.safe_load(yaml_str)
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "OrchestrationConfig":
        """从 JSON 字符串反序列化。"""
        return cls.model_validate_json(json_str)

    @classmethod
    def from_file(cls, path: str | Path) -> "OrchestrationConfig":
        """从文件加载配置，根据文件扩展名自动选择 YAML 或 JSON 解析。"""
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")

        if file_path.suffix in (".yaml", ".yml"):
            return cls.from_yaml(content)
        elif file_path.suffix == ".json":
            return cls.from_json(content)
        else:
            raise ValueError(
                f"Unsupported config file format: {file_path.suffix}. "
                "Use .yaml, .yml, or .json."
            )
