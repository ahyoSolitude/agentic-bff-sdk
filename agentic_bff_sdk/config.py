"""Configuration models for the refactored Agentic BFF SDK."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from agentic_bff_sdk.models import ChannelCapabilities


class RuntimeConfig(BaseModel):
    session_idle_timeout_seconds: int = 1800
    max_dialog_history_turns: int = 50
    plan_generation_timeout_seconds: float = 30.0
    step_execution_timeout_seconds: float = 60.0
    fan_in_wait_timeout_seconds: float = 30.0
    max_cross_llm_loops: int = 2


class RuleEngineConfig(BaseModel):
    base_url: str | None = None
    timeout_seconds: float = 10.0
    metadata_cache_ttl_seconds: int = 300
    result_cache_enabled: bool = False


class ChannelConfig(BaseModel):
    channel_id: str
    adapter_class: str | None = None
    capabilities: ChannelCapabilities = Field(default_factory=ChannelCapabilities)


class DomainConfig(BaseModel):
    domain: str
    package_class: str | None = None
    timeout_seconds: float = 30.0


class ObservabilityConfig(BaseModel):
    enable_events: bool = True
    enable_audit: bool = True


class SDKConfig(BaseModel):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rule_engine: RuleEngineConfig = Field(default_factory=RuleEngineConfig)
    channels: list[ChannelConfig] = Field(default_factory=list)
    domains: list[DomainConfig] = Field(default_factory=list)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    def to_yaml(self) -> str:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise RuntimeError("YAML support requires the 'pyyaml' package.") from exc
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "SDKConfig":
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise RuntimeError("YAML support requires the 'pyyaml' package.") from exc
        return cls.model_validate(yaml.safe_load(yaml_str) or {})

    @classmethod
    def from_json(cls, json_str: str) -> "SDKConfig":
        return cls.model_validate_json(json_str)

    @classmethod
    def from_file(cls, path: str | Path) -> "SDKConfig":
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix in (".yaml", ".yml"):
            return cls.from_yaml(content)
        if file_path.suffix == ".json":
            return cls.from_json(content)
        raise ValueError("Unsupported config file format. Use .yaml, .yml, or .json.")
