"""Property-based tests for the TopLevelRouter module.

Uses Hypothesis to verify correctness properties of the DefaultTopLevelRouter
across randomized inputs: confidence thresholds, priority rules, ambiguity
detection, and fallback routing.
"""

import time
from typing import Any, List
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings, strategies as st

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    ClarificationQuestion,
    IntentResult,
    RouterMode,
    SessionState,
)
from agentic_bff_sdk.router import DefaultTopLevelRouter


# ============================================================
# Helpers
# ============================================================


def _make_session_state(session_id: str = "prop-test-session") -> SessionState:
    now = time.time()
    return SessionState(
        session_id=session_id,
        dialog_history=[],
        created_at=now,
        last_active_at=now,
    )


def _make_mock_llm() -> AsyncMock:
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value="[]")
    return mock


# ============================================================
# Strategies
# ============================================================

# Confidence values strictly below a given threshold
# We'll parameterize per-test using .filter or .flatmap

# Safe text for intent types and keywords (printable, non-empty)
safe_intent_type = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

# Keywords that are safe for regex matching (alphanumeric only)
safe_keyword = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=2,
    max_size=20,
)


# ============================================================
# Property 8: 低置信度意图触发澄清
# ============================================================


@pytest.mark.property
class TestProperty8LowConfidenceClarification:
    """Property 8: 低置信度意图触发澄清

    *For any* intent recognition result where the highest confidence is below
    the configured intent_confidence_threshold, the TopLevelRouter SHALL return
    a ClarificationQuestion rather than an IntentResult.

    **Validates: Requirements 3.3**
    """

    @given(
        confidence=st.floats(min_value=0.0, max_value=0.69, allow_nan=False),
        threshold=st.floats(min_value=0.3, max_value=0.95, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_below_threshold_returns_clarification(
        self, confidence: float, threshold: float
    ) -> None:
        """When the best candidate's confidence < threshold, return ClarificationQuestion."""
        # Ensure confidence is strictly below threshold
        if confidence >= threshold:
            return  # skip this example — not in the target domain

        config = SDKConfig(intent_confidence_threshold=threshold)

        async def recognizer(
            llm: Any, user_input: str, session_state: SessionState
        ) -> List[IntentResult]:
            return [IntentResult(intent_type="test_intent", confidence=confidence)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, config=config, intent_recognizer=recognizer
        )

        state = _make_session_state()
        result = await router.route("test input", state)

        assert isinstance(result, ClarificationQuestion), (
            f"Expected ClarificationQuestion for confidence={confidence} "
            f"< threshold={threshold}, got {type(result).__name__}"
        )
        assert len(result.candidates) >= 1
        assert result.candidates[0].confidence == confidence

    @given(
        threshold=st.floats(min_value=0.1, max_value=0.99, allow_nan=False),
        data=st.data(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_at_or_above_threshold_returns_intent(
        self, threshold: float, data: st.DataObject
    ) -> None:
        """When the best candidate's confidence >= threshold, return IntentResult."""
        confidence = data.draw(
            st.floats(min_value=threshold, max_value=1.0, allow_nan=False)
        )

        config = SDKConfig(
            intent_confidence_threshold=threshold,
            # Set ambiguity range to 0 so ambiguity check doesn't interfere
            intent_ambiguity_range=0.0,
        )

        async def recognizer(
            llm: Any, user_input: str, session_state: SessionState
        ) -> List[IntentResult]:
            return [IntentResult(intent_type="clear_intent", confidence=confidence)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, config=config, intent_recognizer=recognizer
        )

        state = _make_session_state()
        result = await router.route("test input", state)

        assert isinstance(result, IntentResult), (
            f"Expected IntentResult for confidence={confidence} "
            f">= threshold={threshold}, got {type(result).__name__}"
        )
        assert result.confidence == confidence


# ============================================================
# Property 9: 优先匹配规则优先生效
# ============================================================


@pytest.mark.property
class TestProperty9PriorityRulesTakePrecedence:
    """Property 9: 优先匹配规则优先生效

    *For any* user input that matches a registered priority rule, the
    TopLevelRouter SHALL return the rule's corresponding intent regardless
    of LLM recognition results.

    **Validates: Requirements 3.4**
    """

    @given(
        keyword=safe_keyword,
        intent_type=safe_intent_type,
        llm_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_priority_rule_overrides_llm(
        self, keyword: str, intent_type: str, llm_confidence: float
    ) -> None:
        """A matching priority rule always wins over LLM results."""
        # Build user input that contains the keyword
        user_input = f"I want to {keyword} something"

        async def recognizer(
            llm: Any, ui: str, session_state: SessionState
        ) -> List[IntentResult]:
            return [
                IntentResult(
                    intent_type="llm_intent", confidence=llm_confidence
                )
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, intent_recognizer=recognizer
        )
        router.register_priority_rule(
            {"pattern": keyword, "intent_type": intent_type}
        )

        state = _make_session_state()
        result = await router.route(user_input, state)

        assert isinstance(result, IntentResult), (
            f"Expected IntentResult from priority rule, got {type(result).__name__}"
        )
        assert result.intent_type == intent_type
        assert result.confidence == 1.0

    @given(
        keyword=safe_keyword,
        intent_type=safe_intent_type,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_priority_rule_skipped_in_confirm_mode(
        self, keyword: str, intent_type: str
    ) -> None:
        """Priority rules are NOT checked in CONFIRM mode."""
        user_input = f"I want to {keyword} something"

        async def recognizer(
            llm: Any, ui: str, session_state: SessionState
        ) -> List[IntentResult]:
            return [IntentResult(intent_type="confirmed", confidence=0.95)]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, intent_recognizer=recognizer
        )
        router.register_priority_rule(
            {"pattern": keyword, "intent_type": intent_type}
        )

        state = _make_session_state()
        result = await router.route(user_input, state, mode=RouterMode.CONFIRM)

        assert isinstance(result, IntentResult)
        assert result.intent_type == "confirmed", (
            "Priority rule should be skipped in CONFIRM mode"
        )

    @given(
        keywords=st.lists(safe_keyword, min_size=2, max_size=5, unique=True),
        intent_types=st.lists(safe_intent_type, min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_first_matching_rule_wins(
        self, keywords: List[str], intent_types: List[str]
    ) -> None:
        """When multiple rules could match, the first registered rule wins."""
        # Ensure we have matching counts
        n = min(len(keywords), len(intent_types))
        if n < 2:
            return

        keywords = keywords[:n]
        intent_types = intent_types[:n]

        # Use the first keyword in the input
        user_input = f"please {keywords[0]} now"

        async def recognizer(
            llm: Any, ui: str, session_state: SessionState
        ) -> List[IntentResult]:
            return []

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, intent_recognizer=recognizer
        )

        for kw, it in zip(keywords, intent_types):
            router.register_priority_rule({"pattern": kw, "intent_type": it})

        state = _make_session_state()
        result = await router.route(user_input, state)

        assert isinstance(result, IntentResult)
        assert result.intent_type == intent_types[0]


# ============================================================
# Property 10: 歧义意图返回候选列表
# ============================================================


@pytest.mark.property
class TestProperty10AmbiguousIntentsCandidateList:
    """Property 10: 歧义意图返回候选列表

    *For any* intent recognition result set where the top two candidates'
    confidence difference is within the configured intent_ambiguity_range,
    the TopLevelRouter SHALL return a ClarificationQuestion containing
    the candidate list.

    **Validates: Requirements 3.5**
    """

    @given(
        base_confidence=st.floats(min_value=0.5, max_value=0.95, allow_nan=False),
        ambiguity_range=st.floats(min_value=0.05, max_value=0.3, allow_nan=False),
        data=st.data(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_ambiguous_pair_returns_clarification(
        self, base_confidence: float, ambiguity_range: float, data: st.DataObject
    ) -> None:
        """When top two confidences differ by less than ambiguity_range, return clarification."""
        # Generate a second confidence within the ambiguity range
        max_diff = ambiguity_range * 0.99  # strictly less than range
        diff = data.draw(
            st.floats(min_value=0.0, max_value=max_diff, allow_nan=False)
        )
        second_confidence = base_confidence - diff

        if second_confidence < 0.0:
            return  # skip invalid

        # Both must be above threshold to avoid triggering low-confidence path
        threshold = min(base_confidence, second_confidence) - 0.01
        if threshold < 0.0:
            threshold = 0.0

        config = SDKConfig(
            intent_confidence_threshold=threshold,
            intent_ambiguity_range=ambiguity_range,
        )

        async def recognizer(
            llm: Any, user_input: str, session_state: SessionState
        ) -> List[IntentResult]:
            return [
                IntentResult(intent_type="intent_a", confidence=base_confidence),
                IntentResult(intent_type="intent_b", confidence=second_confidence),
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, config=config, intent_recognizer=recognizer
        )

        state = _make_session_state()
        result = await router.route("ambiguous input", state)

        assert isinstance(result, ClarificationQuestion), (
            f"Expected ClarificationQuestion for diff={diff:.4f} "
            f"< ambiguity_range={ambiguity_range:.4f}, "
            f"got {type(result).__name__}"
        )
        assert len(result.candidates) >= 2

    @given(
        base_confidence=st.floats(min_value=0.5, max_value=0.95, allow_nan=False),
        ambiguity_range=st.floats(min_value=0.05, max_value=0.3, allow_nan=False),
        data=st.data(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_non_ambiguous_pair_returns_intent(
        self, base_confidence: float, ambiguity_range: float, data: st.DataObject
    ) -> None:
        """When top two confidences differ by >= ambiguity_range, return best IntentResult."""
        # Generate a second confidence with diff strictly > ambiguity_range
        # Add a small epsilon to avoid floating-point boundary issues
        max_second = base_confidence - ambiguity_range - 1e-9
        if max_second < 0.0:
            return  # skip — can't create valid non-ambiguous pair

        second_confidence = data.draw(
            st.floats(min_value=0.0, max_value=max_second, allow_nan=False)
        )

        # Both must be above threshold
        threshold = min(base_confidence, second_confidence) - 0.01
        if threshold < 0.0:
            threshold = 0.0

        config = SDKConfig(
            intent_confidence_threshold=threshold,
            intent_ambiguity_range=ambiguity_range,
        )

        async def recognizer(
            llm: Any, user_input: str, session_state: SessionState
        ) -> List[IntentResult]:
            return [
                IntentResult(intent_type="intent_a", confidence=base_confidence),
                IntentResult(intent_type="intent_b", confidence=second_confidence),
            ]

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, config=config, intent_recognizer=recognizer
        )

        state = _make_session_state()
        result = await router.route("clear input", state)

        assert isinstance(result, IntentResult), (
            f"Expected IntentResult for diff={base_confidence - second_confidence:.4f} "
            f">= ambiguity_range={ambiguity_range:.4f}, "
            f"got {type(result).__name__}"
        )
        assert result.intent_type == "intent_a"


# ============================================================
# Property 11: 无匹配意图路由到兜底链路
# ============================================================


@pytest.mark.property
class TestProperty11FallbackRouting:
    """Property 11: 无匹配意图路由到兜底链路

    *For any* user input where no intent can be matched (empty candidate list),
    the TopLevelRouter SHALL route the request to the registered fallback handler.

    **Validates: Requirements 3.6**
    """

    @given(
        user_input=st.text(min_size=1, max_size=100),
        fallback_intent_type=safe_intent_type,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_empty_candidates_triggers_sync_fallback(
        self, user_input: str, fallback_intent_type: str
    ) -> None:
        """When recognizer returns empty list and fallback is registered, fallback is used."""
        async def recognizer(
            llm: Any, ui: str, session_state: SessionState
        ) -> List[IntentResult]:
            return []

        def fallback(ui: str, session_state: SessionState) -> IntentResult:
            return IntentResult(
                intent_type=fallback_intent_type, confidence=0.0
            )

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, intent_recognizer=recognizer
        )
        router.register_fallback_handler(fallback)

        state = _make_session_state()
        result = await router.route(user_input, state)

        assert isinstance(result, IntentResult), (
            f"Expected IntentResult from fallback, got {type(result).__name__}"
        )
        assert result.intent_type == fallback_intent_type

    @given(
        user_input=st.text(min_size=1, max_size=100),
        fallback_intent_type=safe_intent_type,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_empty_candidates_triggers_async_fallback(
        self, user_input: str, fallback_intent_type: str
    ) -> None:
        """When recognizer returns empty list and async fallback is registered, fallback is used."""
        async def recognizer(
            llm: Any, ui: str, session_state: SessionState
        ) -> List[IntentResult]:
            return []

        async def fallback(ui: str, session_state: SessionState) -> IntentResult:
            return IntentResult(
                intent_type=fallback_intent_type, confidence=0.0
            )

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, intent_recognizer=recognizer
        )
        router.register_fallback_handler(fallback)

        state = _make_session_state()
        result = await router.route(user_input, state)

        assert isinstance(result, IntentResult), (
            f"Expected IntentResult from async fallback, got {type(result).__name__}"
        )
        assert result.intent_type == fallback_intent_type

    @given(user_input=st.text(min_size=1, max_size=100))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_empty_candidates_no_fallback_returns_clarification(
        self, user_input: str
    ) -> None:
        """When recognizer returns empty list and no fallback, return ClarificationQuestion."""
        async def recognizer(
            llm: Any, ui: str, session_state: SessionState
        ) -> List[IntentResult]:
            return []

        llm = _make_mock_llm()
        router = DefaultTopLevelRouter(
            llm=llm, intent_recognizer=recognizer
        )

        state = _make_session_state()
        result = await router.route(user_input, state)

        assert isinstance(result, ClarificationQuestion), (
            f"Expected ClarificationQuestion when no fallback, got {type(result).__name__}"
        )
        assert result.candidates == []
