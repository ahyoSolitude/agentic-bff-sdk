"""Rule engine client and cache semantics."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from agentic_bff_sdk.config import RuleEngineConfig
from agentic_bff_sdk.errors import RuleEngineError
from agentic_bff_sdk.models import RuleEvaluationRequest, RuleEvaluationResult, RuleMetadata


class RuleEngineClient(ABC):
    @abstractmethod
    async def get_rule_metadata(self, rule_set_id: str) -> RuleMetadata:
        ...

    @abstractmethod
    async def evaluate(self, request: RuleEvaluationRequest) -> RuleEvaluationResult:
        ...


class HttpRuleEngineClient(RuleEngineClient):
    def __init__(self, config: RuleEngineConfig | None = None, http_client: object | None = None) -> None:
        self._config = config or RuleEngineConfig()
        self._client = http_client
        self._metadata_cache: dict[str, tuple[RuleMetadata, float]] = {}

    async def get_rule_metadata(self, rule_set_id: str) -> RuleMetadata:
        cached = self._metadata_cache.get(rule_set_id)
        now = time.time()
        if cached and now - cached[1] < self._config.metadata_cache_ttl_seconds:
            return cached[0]
        if not self._config.base_url:
            metadata = RuleMetadata(rule_set_id=rule_set_id, version="default")
            self._metadata_cache[rule_set_id] = (metadata, now)
            return metadata
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise RuleEngineError("HTTP rule engine support requires the 'httpx' package.") from exc
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                f"{self._config.base_url.rstrip('/')}/rule-sets/{rule_set_id}/metadata",
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            metadata = RuleMetadata.model_validate(response.json())
            self._metadata_cache[rule_set_id] = (metadata, now)
            return metadata
        except Exception as exc:
            raise RuleEngineError(f"Failed to fetch rule metadata: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def evaluate(self, request: RuleEvaluationRequest) -> RuleEvaluationResult:
        if not self._config.base_url:
            return RuleEvaluationResult(rule_set_id=request.rule_set_id, version=request.version or "default")
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise RuleEngineError("HTTP rule engine support requires the 'httpx' package.") from exc
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                f"{self._config.base_url.rstrip('/')}/rule-sets/{request.rule_set_id}/evaluate",
                json=request.model_dump(mode="json"),
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            return RuleEvaluationResult.model_validate(response.json())
        except Exception as exc:
            raise RuleEngineError(f"Rule evaluation failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
