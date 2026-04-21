"""Unit tests for the TopLevelRouter module."""

import time
from typing import Any, List
from unittest.mock import AsyncMock

import pytest

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    ClarificationQuestion,
    IntentResult,
    RouterMode,
    SessionState,
)
from agentic_bff_sdk.router import DefaultTopLevelRouter, TopLevelRouter


# ============================================================
# Helpers
# ============================================================


def _make_session_state(session_id: str = "test-session") -> SessionState:
    now = time.time()
    return SessionState(
        session_id=session_id,
        dialog_history=[],
        created_at=now,
        last_active_at=now,
    )


def _make_mock_llm() -> AsyncMock:
    """Create a mock LLM that satisfies BaseLanguageModel interface."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value="[]")
    return mock


async def _fixed_recognizer(
    llm: Any,
    user_input: str,
    session_state: SessionState,
    candidates: List[IntentResult] | None = None,
) -> List[IntentResult]:
    """A recognizer factory that returns fixed candidates."""
    return candidates or []


# ============================================================
# TopLevelRouter ABC Tests
# ============================================================


class TestTopLevelRouterABC:
    """Tests verifying TopLevelRouter is a proper ABC."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            TopLevelRouter()  # type: ignore[abstract]


# ============================================================
# DefaultTopLevelRouter Initialization Tests
# ============================================================


class TestDefaultTopLevelRouterInit:
    """Tests for DefaultTopLevelRouter initialization."""

    def test_default_config(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        assert router.config == SDKConfig()
        assert router.llm is llm
        assert router.priority_rules == []
        assert router.fallback_handler is None

    def test_custom_config(self) -> None:
        llm = _make_mock_llm()
        config = SDKConfig(intent_confidence_threshold=0.5, intent_ambiguity_range=0.2)
        router = DefaultTopLevelRouter(llm=llm, config=config)
        assert router.config.intent_confidence_threshold == 0.5
        assert router.config.intent_ambiguity_range == 0.2


# ============================================================
# Priority Rule Registration Tests
# ============================================================


class TestPriorityRuleRegistration:
    """Tests for register_priority_rule."""

    def test_register_valid_rule(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        rule = {"pattern": "balance", "intent_type": "check_balance"}
        router.register_priority_rule(rule)
        assert len(router.priority_rules) == 1
        assert router.priority_rules[0]["intent_type"] == "check_balance"

    def test_register_multiple_rules(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        router.register_priority_rule({"pattern": "balance", "intent_type": "check_balance"})
        router.register_priority_rule({"pattern": "transfer", "intent_type": "transfer_funds"})
        assert len(router.priority_rules) == 2

    def test_register_rule_missing_pattern_raises(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        with pytest.raises(ValueError, match="pattern"):
            router.register_priority_rule({"intent_type": "check_balance"})

    def test_register_rule_missing_intent_type_raises(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        with pytest.raises(ValueError, match="intent_type"):
            router.register_priority_rule({"pattern": "balance"})


# ============================================================
# Fallback Handler Registration Tests
# ============================================================


class TestFallbackHandlerRegistration:
    """Tests for register_fallback_handler."""

    def test_register_fallback_handler(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        handler = lambda x, y: IntentResult(intent_type="fallback", confidence=0.0)
        router.register_fallback_handler(handler)
        assert router.fallback_handler is handler


# ============================================================
# Priority Rule Matching Tests
# ============================================================


class TestPriorityRuleMatching:
    """Tests for priority rule matching in route()."""

    async def test_keyword_match_returns_intent(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        router.register_priority_rule({"pattern": "balance", "intent_type": "check_balance"})

        state = _make_session_state()
        result = await router.route("What is my balance?", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "check_balance"
        assert result.confidence == 1.0

    async def test_regex_match_returns_intent(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        router.register_priority_rule(
            {"pattern": r"transfer\s+\d+", "intent_type": "transfer_funds"}
        )

        state = _make_session_state()
        result = await router.route("I want to transfer 100 dollars", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "transfer_funds"
        assert result.confidence == 1.0

    async def test_priority_rule_skipped_in_confirm_mode(self) -> None:
        """Priority rules are only checked in GENERATE mode."""
        llm = _make_mock_llm()
        # Use a recognizer that returns a high-confidence intent
        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="confirmed", confidence=0.95)]

        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_priority_rule({"pattern": "balance", "intent_type": "check_balance"})

        state = _make_session_state()
        result = await router.route("balance", state, mode=RouterMode.CONFIRM)

        # Should NOT match priority rule in CONFIRM mode
        assert isinstance(result, IntentResult)
        assert result.intent_type == "confirmed"

    async def test_first_matching_rule_wins(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        router.register_priority_rule({"pattern": "fund", "intent_type": "fund_query"})
        router.register_priority_rule({"pattern": "fund", "intent_type": "fund_purchase"})

        state = _make_session_state()
        result = await router.route("Tell me about fund options", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "fund_query"

    async def test_priority_rule_extra_params(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        router.register_priority_rule(
            {"pattern": "help", "intent_type": "help", "category": "general"}
        )

        state = _make_session_state()
        result = await router.route("I need help", state)

        assert isinstance(result, IntentResult)
        assert result.parameters == {"category": "general"}

    async def test_case_insensitive_keyword_match(self) -> None:
        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm)
        router.register_priority_rule({"pattern": "BALANCE", "intent_type": "check_balance"})

        state = _make_session_state()
        result = await router.route("check my balance please", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "check_balance"


# ============================================================
# Confidence Threshold Tests
# ============================================================


class TestConfidenceThreshold:
    """Tests for confidence threshold behavior."""

    async def test_low_confidence_returns_clarification(self) -> None:
        """When max confidence < threshold, return ClarificationQuestion."""
        config = SDKConfig(intent_confidence_threshold=0.7)

        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="maybe", confidence=0.5)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("something vague", state)

        assert isinstance(result, ClarificationQuestion)
        assert len(result.candidates) == 1
        assert result.candidates[0].confidence == 0.5

    async def test_high_confidence_returns_intent(self) -> None:
        """When max confidence >= threshold, return IntentResult."""
        config = SDKConfig(intent_confidence_threshold=0.7)

        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="clear_intent", confidence=0.9)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("clear request", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "clear_intent"
        assert result.confidence == 0.9

    async def test_exact_threshold_returns_intent(self) -> None:
        """When confidence == threshold, return IntentResult."""
        config = SDKConfig(intent_confidence_threshold=0.7)

        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="borderline", confidence=0.7)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("borderline input", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "borderline"


# ============================================================
# Ambiguity Detection Tests
# ============================================================


class TestAmbiguityDetection:
    """Tests for ambiguity detection between top candidates."""

    async def test_ambiguous_intents_return_clarification(self) -> None:
        """When top 2 intents' confidence diff < ambiguity_range, return clarification."""
        config = SDKConfig(
            intent_confidence_threshold=0.5,
            intent_ambiguity_range=0.1,
        )

        async def recognizer(llm_inst, user_input, session_state):
            return [
                IntentResult(intent_type="intent_a", confidence=0.85),
                IntentResult(intent_type="intent_b", confidence=0.82),
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("ambiguous input", state)

        assert isinstance(result, ClarificationQuestion)
        assert len(result.candidates) >= 2

    async def test_non_ambiguous_intents_return_best(self) -> None:
        """When top 2 intents' confidence diff >= ambiguity_range, return best."""
        config = SDKConfig(
            intent_confidence_threshold=0.5,
            intent_ambiguity_range=0.1,
        )

        async def recognizer(llm_inst, user_input, session_state):
            return [
                IntentResult(intent_type="intent_a", confidence=0.9),
                IntentResult(intent_type="intent_b", confidence=0.6),
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("clear input", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "intent_a"

    async def test_ambiguity_not_checked_in_confirm_mode(self) -> None:
        """In CONFIRM mode, ambiguity detection is skipped."""
        config = SDKConfig(
            intent_confidence_threshold=0.5,
            intent_ambiguity_range=0.1,
        )

        async def recognizer(llm_inst, user_input, session_state):
            return [
                IntentResult(intent_type="intent_a", confidence=0.85),
                IntentResult(intent_type="intent_b", confidence=0.82),
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("confirm this", state, mode=RouterMode.CONFIRM)

        # In CONFIRM mode, ambiguity check is skipped, so best intent is returned
        assert isinstance(result, IntentResult)
        assert result.intent_type == "intent_a"

    async def test_single_candidate_no_ambiguity(self) -> None:
        """With only one candidate, no ambiguity check is needed."""
        config = SDKConfig(
            intent_confidence_threshold=0.5,
            intent_ambiguity_range=0.1,
        )

        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="only_one", confidence=0.8)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("single intent", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "only_one"


# ============================================================
# Fallback Handler Tests
# ============================================================


class TestFallbackHandler:
    """Tests for fallback handler behavior."""

    async def test_no_candidates_no_fallback_returns_clarification(self) -> None:
        """When no candidates and no fallback, return ClarificationQuestion."""
        async def recognizer(llm_inst, user_input, session_state):
            return []

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("gibberish", state)

        assert isinstance(result, ClarificationQuestion)
        assert result.candidates == []

    async def test_no_candidates_with_sync_fallback(self) -> None:
        """When no candidates and sync fallback registered, use fallback."""
        async def recognizer(llm_inst, user_input, session_state):
            return []

        def fallback(user_input, session_state):
            return IntentResult(intent_type="fallback_intent", confidence=0.0)

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_fallback_handler(fallback)

        state = _make_session_state()
        result = await router.route("unknown input", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "fallback_intent"

    async def test_no_candidates_with_async_fallback(self) -> None:
        """When no candidates and async fallback registered, use fallback."""
        async def recognizer(llm_inst, user_input, session_state):
            return []

        async def fallback(user_input, session_state):
            return IntentResult(intent_type="async_fallback", confidence=0.0)

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_fallback_handler(fallback)

        state = _make_session_state()
        result = await router.route("unknown input", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "async_fallback"

    async def test_fallback_returning_clarification(self) -> None:
        """Fallback handler can return ClarificationQuestion."""
        async def recognizer(llm_inst, user_input, session_state):
            return []

        def fallback(user_input, session_state):
            return ClarificationQuestion(
                question="Fallback: what do you mean?", candidates=[]
            )

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_fallback_handler(fallback)

        state = _make_session_state()
        result = await router.route("unknown", state)

        assert isinstance(result, ClarificationQuestion)
        assert "Fallback" in result.question

    async def test_non_callable_fallback_handler(self) -> None:
        """Non-callable fallback handler returns a default fallback IntentResult."""
        async def recognizer(llm_inst, user_input, session_state):
            return []

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_fallback_handler("some_handler_reference")

        state = _make_session_state()
        result = await router.route("unknown", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "fallback"


# ============================================================
# Full Routing Flow Tests
# ============================================================


class TestFullRoutingFlow:
    """Integration-style tests for the complete routing flow."""

    async def test_priority_rule_takes_precedence_over_llm(self) -> None:
        """Priority rules should be checked before LLM, regardless of LLM result."""
        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="llm_intent", confidence=0.99)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_priority_rule({"pattern": "balance", "intent_type": "check_balance"})

        state = _make_session_state()
        result = await router.route("check my balance", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "check_balance"
        assert result.confidence == 1.0

    async def test_no_priority_match_falls_through_to_llm(self) -> None:
        """When no priority rule matches, LLM is used."""
        async def recognizer(llm_inst, user_input, session_state):
            return [IntentResult(intent_type="llm_intent", confidence=0.85)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, intent_recognizer=recognizer)
        router.register_priority_rule({"pattern": "balance", "intent_type": "check_balance"})

        state = _make_session_state()
        result = await router.route("what is the weather?", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "llm_intent"

    async def test_candidates_sorted_by_confidence(self) -> None:
        """Candidates from recognizer are sorted by confidence descending."""
        config = SDKConfig(intent_confidence_threshold=0.5, intent_ambiguity_range=0.01)

        async def recognizer(llm_inst, user_input, session_state):
            return [
                IntentResult(intent_type="low", confidence=0.3),
                IntentResult(intent_type="high", confidence=0.9),
                IntentResult(intent_type="mid", confidence=0.6),
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(llm=llm, config=config, intent_recognizer=recognizer)

        state = _make_session_state()
        result = await router.route("some input", state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "high"
        assert result.confidence == 0.9
