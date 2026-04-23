"""Response decision, synthesis, and card generation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentic_bff_sdk.models import (
    AggregatedResult,
    Card,
    CardAction,
    CardType,
    ChannelCapabilities,
    DecisionOutcome,
    DecisionStatus,
    ExecutionContext,
    ResponseEnvelope,
    SynthesisResult,
)


class DecisionEngine(ABC):
    @abstractmethod
    async def decide(self, aggregated: AggregatedResult, context: ExecutionContext) -> DecisionOutcome:
        ...


class DefaultDecisionEngine(DecisionEngine):
    async def decide(self, aggregated: AggregatedResult, context: ExecutionContext) -> DecisionOutcome:
        status = DecisionStatus.PARTIAL if aggregated.is_partial else DecisionStatus.READY
        return DecisionOutcome(
            status=status,
            summary="已完成请求处理。" if not aggregated.is_partial else "已生成部分结果。",
            structured_payload={
                "results": [result.model_dump(mode="json") for result in aggregated.results],
                "missing_steps": aggregated.missing_steps,
                "failed_steps": aggregated.failed_steps,
            },
        )


class Synthesizer(ABC):
    @abstractmethod
    async def synthesize(self, decision: DecisionOutcome, context: ExecutionContext) -> SynthesisResult:
        ...


class DefaultSynthesizer(Synthesizer):
    async def synthesize(self, decision: DecisionOutcome, context: ExecutionContext) -> SynthesisResult:
        return SynthesisResult(
            text=decision.summary,
            structured_payload=decision.structured_payload,
            confirmation_actions=decision.confirmation_actions,
            compliance_flags=decision.compliance_flags,
        )


class CardGenerator(ABC):
    @abstractmethod
    async def generate(self, synthesis: SynthesisResult, capabilities: ChannelCapabilities) -> ResponseEnvelope:
        ...


class DefaultCardGenerator(CardGenerator):
    async def generate(self, synthesis: SynthesisResult, capabilities: ChannelCapabilities) -> ResponseEnvelope:
        cards = [Card(card_type=CardType.TEXT, body={"text": synthesis.text})]
        if synthesis.structured_payload and capabilities.supports_table_card:
            cards.append(Card(card_type=CardType.TABLE, title="结构化结果", body=synthesis.structured_payload))
        if synthesis.confirmation_actions and capabilities.supports_action_card:
            cards.append(
                Card(
                    card_type=CardType.CONFIRMATION,
                    title="请确认",
                    body={"text": synthesis.text},
                    actions=[
                        CardAction(action_id=action.action_id, label=action.label, payload=action.payload)
                        for action in synthesis.confirmation_actions
                    ],
                )
            )
        return ResponseEnvelope(
            text=synthesis.text,
            cards=cards[: capabilities.max_card_count],
            metadata={"compliance_flags": synthesis.compliance_flags},
        )


class ResponseEngine(ABC):
    @abstractmethod
    async def compose(
        self,
        aggregated: AggregatedResult,
        context: ExecutionContext,
        capabilities: ChannelCapabilities,
    ) -> ResponseEnvelope:
        ...


class DefaultResponseEngine(ResponseEngine):
    def __init__(
        self,
        decision_engine: DecisionEngine | None = None,
        synthesizer: Synthesizer | None = None,
        card_generator: CardGenerator | None = None,
    ) -> None:
        self._decision = decision_engine or DefaultDecisionEngine()
        self._synthesizer = synthesizer or DefaultSynthesizer()
        self._cards = card_generator or DefaultCardGenerator()

    async def compose(
        self,
        aggregated: AggregatedResult,
        context: ExecutionContext,
        capabilities: ChannelCapabilities,
    ) -> ResponseEnvelope:
        decision = await self._decision.decide(aggregated, context)
        synthesis = await self._synthesizer.synthesize(decision, context)
        return await self._cards.generate(synthesis, capabilities)
