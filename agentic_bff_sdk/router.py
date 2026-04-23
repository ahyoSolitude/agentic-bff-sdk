"""Intent routing for the refactored SDK."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from agentic_bff_sdk.models import (
    ClarificationPrompt,
    FallbackRoute,
    RequestContext,
    ResolvedIntent,
    RoutingResult,
    SessionState,
)

IntentRecognizer = Callable[[RequestContext, SessionState], Awaitable[list[ResolvedIntent]]]


class Router(ABC):
    @abstractmethod
    async def resolve(self, request: RequestContext, session: SessionState) -> RoutingResult:
        ...


class DefaultRouter(Router):
    def __init__(
        self,
        *,
        confidence_threshold: float = 0.7,
        ambiguity_range: float = 0.1,
        recognizer: IntentRecognizer | None = None,
    ) -> None:
        self._confidence_threshold = confidence_threshold
        self._ambiguity_range = ambiguity_range
        self._recognizer = recognizer
        self._priority_rules: list[dict[str, object]] = []

    def register_priority_rule(self, rule: dict[str, object]) -> None:
        if "pattern" not in rule or "intent_name" not in rule:
            raise ValueError("Priority rule must contain 'pattern' and 'intent_name'.")
        self._priority_rules.append(rule)

    async def resolve(self, request: RequestContext, session: SessionState) -> RoutingResult:
        priority = self._match_priority_rule(request.user_input)
        if priority is not None:
            return RoutingResult(intent=priority)

        candidates = await self._recognize(request, session)
        if not candidates:
            return RoutingResult(fallback=FallbackRoute(reason="no_intent"))
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        best = candidates[0]
        if len(candidates) > 1 and best.confidence - candidates[1].confidence < self._ambiguity_range:
            return RoutingResult(
                clarification=ClarificationPrompt(
                    question="请确认你想办理哪一类事项？",
                    candidates=candidates[:3],
                )
            )
        if best.confidence < self._confidence_threshold:
            return RoutingResult(
                clarification=ClarificationPrompt(
                    question="我还不确定你的意图，请补充说明。",
                    candidates=candidates[:3],
                )
            )
        return RoutingResult(intent=best)

    def _match_priority_rule(self, user_input: str) -> ResolvedIntent | None:
        for rule in self._priority_rules:
            pattern = str(rule["pattern"])
            matched = False
            try:
                matched = re.search(pattern, user_input, re.IGNORECASE) is not None
            except re.error:
                matched = pattern.lower() in user_input.lower()
            if matched:
                params = {k: v for k, v in rule.items() if k not in ("pattern", "intent_name")}
                return ResolvedIntent(intent_name=str(rule["intent_name"]), confidence=1.0, parameters=params)
        return None

    async def _recognize(self, request: RequestContext, session: SessionState) -> list[ResolvedIntent]:
        if self._recognizer is not None:
            return await self._recognizer(request, session)
        if not request.user_input.strip():
            return []
        return [ResolvedIntent(intent_name="default", confidence=0.8, parameters={"input": request.user_input})]
