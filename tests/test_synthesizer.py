"""Unit tests for the Synthesizer module."""

import time
from typing import Any, Dict, List, Optional

import pytest

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    AggregatedResult,
    SessionState,
    StepResult,
    StepStatus,
    SynthesisResult,
    Topic,
)
from agentic_bff_sdk.synthesizer import (
    DefaultSynthesizer,
    Synthesizer,
    _build_synthesis_prompt,
    _compute_quality_score,
    _extract_rule_engine_data,
)


# ============================================================
# Helpers
# ============================================================


def _make_session_state(
    dialog_history: Optional[List[Dict[str, Any]]] = None,
) -> SessionState:
    now = time.time()
    return SessionState(
        session_id="test-session",
        dialog_history=dialog_history or [],
        created_at=now,
        last_active_at=now,
    )


def _make_step_result(
    step_id: str,
    status: StepStatus = StepStatus.COMPLETED,
    result: Any = "ok",
    error: Optional[str] = None,
) -> StepResult:
    return StepResult(
        step_id=step_id,
        status=status,
        result=result,
        error=error,
        duration_ms=100.0,
    )


def _make_aggregated(
    results: Optional[List[StepResult]] = None,
    missing_steps: Optional[List[str]] = None,
    is_partial: bool = False,
) -> AggregatedResult:
    return AggregatedResult(
        results=results or [],
        missing_steps=missing_steps or [],
        is_partial=is_partial,
    )


# ============================================================
# Synthesizer ABC tests
# ============================================================


class TestSynthesizerABC:
    """Tests for the Synthesizer abstract base class."""

    def test_synthesizer_is_abstract(self) -> None:
        """Synthesizer cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Synthesizer()  # type: ignore[abstract]

    def test_synthesizer_subclass_must_implement_synthesize(self) -> None:
        """Subclass without synthesize raises TypeError."""

        class IncompleteSynthesizer(Synthesizer):
            pass

        with pytest.raises(TypeError):
            IncompleteSynthesizer()  # type: ignore[abstract]


# ============================================================
# Quality scoring tests
# ============================================================


class TestQualityScoring:
    """Tests for the quality scoring mechanism."""

    def test_empty_response_scores_zero(self) -> None:
        """Empty response text should score 0.0."""
        aggregated = _make_aggregated()
        score = _compute_quality_score("", aggregated, [])
        assert score == 0.0

    def test_whitespace_only_response_scores_zero(self) -> None:
        """Whitespace-only response should score 0.0."""
        aggregated = _make_aggregated()
        score = _compute_quality_score("   ", aggregated, [])
        assert score == 0.0

    def test_short_response_with_completed_steps(self) -> None:
        """Short response with completed steps gets a reasonable score."""
        results = [_make_step_result("s1")]
        aggregated = _make_aggregated(results=results)
        score = _compute_quality_score("Hello", aggregated, [])
        assert 0.0 < score <= 1.0

    def test_longer_response_scores_higher(self) -> None:
        """Longer response should score higher than very short one."""
        results = [_make_step_result("s1")]
        aggregated = _make_aggregated(results=results)
        short_score = _compute_quality_score("Hi", aggregated, [])
        long_score = _compute_quality_score(
            "This is a detailed response covering all results.", aggregated, []
        )
        assert long_score >= short_score

    def test_rule_engine_data_boosts_score(self) -> None:
        """Presence of rule engine data should boost the score."""
        results = [_make_step_result("s1")]
        aggregated = _make_aggregated(results=results)
        score_without = _compute_quality_score(
            "A good response text here.", aggregated, []
        )
        score_with = _compute_quality_score(
            "A good response text here.", aggregated, [{"rule": "data"}]
        )
        assert score_with > score_without

    def test_partial_result_penalizes_score(self) -> None:
        """Partial results should reduce the quality score."""
        results = [_make_step_result("s1")]
        complete = _make_aggregated(results=results, is_partial=False)
        partial = _make_aggregated(
            results=results, missing_steps=["s2"], is_partial=True
        )
        score_complete = _compute_quality_score(
            "A good response text here.", complete, []
        )
        score_partial = _compute_quality_score(
            "A good response text here.", partial, []
        )
        assert score_complete > score_partial

    def test_score_is_clamped_between_0_and_1(self) -> None:
        """Quality score should always be between 0.0 and 1.0."""
        results = [_make_step_result("s1")]
        aggregated = _make_aggregated(results=results)
        score = _compute_quality_score(
            "A very detailed and comprehensive response.", aggregated, [{"r": "d"}]
        )
        assert 0.0 <= score <= 1.0


# ============================================================
# Rule engine data extraction tests
# ============================================================


class TestRuleEngineExtraction:
    """Tests for extracting rule engine data from aggregated results."""

    def test_no_rule_engine_data(self) -> None:
        """When no step has rule engine output, returns empty list."""
        results = [_make_step_result("s1", result="plain text")]
        aggregated = _make_aggregated(results=results)
        rule_data = _extract_rule_engine_data(aggregated)
        assert rule_data == []

    def test_extracts_rule_engine_output(self) -> None:
        """Extracts rule_engine_output from step results."""
        rule_output = {"score": 95, "recommendation": "approve"}
        results = [
            _make_step_result("s1", result={"rule_engine_output": rule_output}),
            _make_step_result("s2", result="plain text"),
        ]
        aggregated = _make_aggregated(results=results)
        rule_data = _extract_rule_engine_data(aggregated)
        assert len(rule_data) == 1
        assert rule_data[0] == rule_output

    def test_extracts_multiple_rule_engine_outputs(self) -> None:
        """Extracts multiple rule engine outputs from different steps."""
        rule1 = {"score": 95}
        rule2 = {"risk": "low"}
        results = [
            _make_step_result("s1", result={"rule_engine_output": rule1}),
            _make_step_result("s2", result={"rule_engine_output": rule2}),
        ]
        aggregated = _make_aggregated(results=results)
        rule_data = _extract_rule_engine_data(aggregated)
        assert len(rule_data) == 2

    def test_ignores_non_dict_results(self) -> None:
        """Non-dict results are ignored during extraction."""
        results = [
            _make_step_result("s1", result=42),
            _make_step_result("s2", result=["list", "data"]),
        ]
        aggregated = _make_aggregated(results=results)
        rule_data = _extract_rule_engine_data(aggregated)
        assert rule_data == []


# ============================================================
# Prompt building tests
# ============================================================


class TestPromptBuilding:
    """Tests for synthesis prompt construction."""

    def test_basic_prompt_includes_results(self) -> None:
        """Prompt should include step results."""
        results = [_make_step_result("s1")]
        aggregated = _make_aggregated(results=results)
        session = _make_session_state()
        prompt = _build_synthesis_prompt(aggregated, session, [])
        assert "s1" in prompt
        assert "completed" in prompt

    def test_prompt_includes_missing_steps(self) -> None:
        """Prompt should mention missing steps for partial results."""
        aggregated = _make_aggregated(missing_steps=["s2", "s3"], is_partial=True)
        session = _make_session_state()
        prompt = _build_synthesis_prompt(aggregated, session, [])
        assert "s2" in prompt
        assert "s3" in prompt

    def test_prompt_includes_rule_engine_data(self) -> None:
        """Prompt should include rule engine outputs."""
        aggregated = _make_aggregated()
        session = _make_session_state()
        rule_data = [{"score": 95}]
        prompt = _build_synthesis_prompt(aggregated, session, rule_data)
        assert "Rule engine" in prompt
        assert "95" in prompt

    def test_retry_prompt_includes_previous_response(self) -> None:
        """Retry prompt should include previous response and score."""
        aggregated = _make_aggregated()
        session = _make_session_state()
        prompt = _build_synthesis_prompt(
            aggregated,
            session,
            [],
            is_retry=True,
            previous_response="Old response",
            previous_score=0.3,
        )
        assert "Old response" in prompt
        assert "0.30" in prompt
        assert "improved" in prompt

    def test_prompt_includes_dialog_history(self) -> None:
        """Prompt should include recent dialog history."""
        session = _make_session_state(
            dialog_history=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ]
        )
        aggregated = _make_aggregated()
        prompt = _build_synthesis_prompt(aggregated, session, [])
        assert "Hello" in prompt


# ============================================================
# DefaultSynthesizer basic tests
# ============================================================


class TestDefaultSynthesizerBasic:
    """Tests for DefaultSynthesizer basic behavior."""

    async def test_synthesize_with_synthesis_fn(self) -> None:
        """synthesis_fn is used to generate the response."""
        synthesizer = DefaultSynthesizer(
            synthesis_fn=lambda prompt: "Generated response from synthesis_fn"
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        result = await synthesizer.synthesize(aggregated, session)

        assert isinstance(result, SynthesisResult)
        assert result.text_response == "Generated response from synthesis_fn"
        assert result.quality_score > 0.0

    async def test_synthesize_returns_quality_score(self) -> None:
        """Result should include a quality score."""
        synthesizer = DefaultSynthesizer(
            synthesis_fn=lambda prompt: "A detailed response covering all aspects."
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        result = await synthesizer.synthesize(aggregated, session)

        assert 0.0 <= result.quality_score <= 1.0

    async def test_synthesize_without_llm_or_fn_raises(self) -> None:
        """Synthesizer without LLM or synthesis_fn raises ValueError."""
        synthesizer = DefaultSynthesizer()
        aggregated = _make_aggregated(results=[_make_step_result("s1")])
        session = _make_session_state()

        with pytest.raises(ValueError, match="requires either an LLM or a synthesis_fn"):
            await synthesizer.synthesize(aggregated, session)

    async def test_synthesize_empty_results(self) -> None:
        """Synthesize with empty results still produces a response."""
        synthesizer = DefaultSynthesizer(
            synthesis_fn=lambda prompt: "No results available."
        )
        aggregated = _make_aggregated()
        session = _make_session_state()

        result = await synthesizer.synthesize(aggregated, session)

        assert result.text_response == "No results available."


# ============================================================
# Cross-LLM retry loop tests
# ============================================================


class TestCrossLLMRetryLoop:
    """Tests for the cross-LLM retry loop mechanism."""

    async def test_no_retry_when_quality_above_threshold(self) -> None:
        """No retry when initial quality is above threshold."""
        call_count = 0

        def counting_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "A detailed response covering all aspects of the query."

        synthesizer = DefaultSynthesizer(synthesis_fn=counting_fn)
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        result = await synthesizer.synthesize(
            aggregated, session, quality_threshold=0.5
        )

        assert call_count == 1
        assert result.quality_score >= 0.5

    async def test_retry_when_quality_below_threshold(self) -> None:
        """Retries when quality is below threshold."""
        call_count = 0

        def improving_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""  # Empty response -> score 0.0
            return "A much better and detailed response now."

        synthesizer = DefaultSynthesizer(
            synthesis_fn=improving_fn,
            config=SDKConfig(max_cross_llm_loops=3),
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        result = await synthesizer.synthesize(
            aggregated, session, quality_threshold=0.5
        )

        assert call_count == 2  # Initial + 1 retry
        assert result.quality_score >= 0.5

    async def test_max_retries_respected(self) -> None:
        """Stops retrying after max_cross_llm_loops."""
        call_count = 0

        def always_bad_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return ""  # Always empty -> score 0.0

        config = SDKConfig(max_cross_llm_loops=2)
        synthesizer = DefaultSynthesizer(
            synthesis_fn=always_bad_fn, config=config
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        result = await synthesizer.synthesize(
            aggregated, session, quality_threshold=0.9
        )

        # 1 initial + 2 retries = 3 total calls
        assert call_count == 3
        assert result.quality_score < 0.9

    async def test_zero_max_loops_means_no_retry(self) -> None:
        """With max_cross_llm_loops=0, no retries happen."""
        call_count = 0

        def bad_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return ""

        config = SDKConfig(max_cross_llm_loops=0)
        synthesizer = DefaultSynthesizer(
            synthesis_fn=bad_fn, config=config
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        result = await synthesizer.synthesize(
            aggregated, session, quality_threshold=0.9
        )

        assert call_count == 1

    async def test_retry_prompt_differs_from_initial(self) -> None:
        """Retry prompts should include previous response context."""
        prompts_received: List[str] = []

        def capturing_fn(prompt: str) -> str:
            prompts_received.append(prompt)
            if len(prompts_received) == 1:
                return ""  # Bad quality to trigger retry
            return "Improved response with more detail."

        synthesizer = DefaultSynthesizer(
            synthesis_fn=capturing_fn,
            config=SDKConfig(max_cross_llm_loops=2),
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        await synthesizer.synthesize(aggregated, session, quality_threshold=0.5)

        assert len(prompts_received) == 2
        # Retry prompt should contain "improved" or reference previous response
        assert "improved" in prompts_received[1].lower() or "previous" in prompts_received[1].lower()


# ============================================================
# Rule engine integration tests
# ============================================================


class TestRuleEngineIntegration:
    """Tests for rule engine result integration in synthesis."""

    async def test_rule_engine_data_included_in_structured_data(self) -> None:
        """Rule engine outputs are included in structured_data."""
        rule_output = {"score": 95, "recommendation": "approve"}
        results = [
            _make_step_result(
                "s1", result={"rule_engine_output": rule_output}
            ),
        ]
        aggregated = _make_aggregated(results=results)
        session = _make_session_state()

        synthesizer = DefaultSynthesizer(
            synthesis_fn=lambda p: "Response integrating rule engine results."
        )
        result = await synthesizer.synthesize(aggregated, session)

        assert result.structured_data is not None
        assert "rule_engine_results" in result.structured_data
        assert result.structured_data["rule_engine_results"][0] == rule_output

    async def test_no_rule_engine_data_means_no_structured_data(self) -> None:
        """Without rule engine outputs, structured_data is None."""
        results = [_make_step_result("s1", result="plain text")]
        aggregated = _make_aggregated(results=results)
        session = _make_session_state()

        synthesizer = DefaultSynthesizer(
            synthesis_fn=lambda p: "Simple response."
        )
        result = await synthesizer.synthesize(aggregated, session)

        assert result.structured_data is None

    async def test_rule_engine_data_passed_to_prompt(self) -> None:
        """Rule engine data should be included in the synthesis prompt."""
        prompts_received: List[str] = []

        def capturing_fn(prompt: str) -> str:
            prompts_received.append(prompt)
            return "Response with rule data."

        rule_output = {"risk_level": "low"}
        results = [
            _make_step_result(
                "s1", result={"rule_engine_output": rule_output}
            ),
        ]
        aggregated = _make_aggregated(results=results)
        session = _make_session_state()

        synthesizer = DefaultSynthesizer(synthesis_fn=capturing_fn)
        await synthesizer.synthesize(aggregated, session)

        assert len(prompts_received) == 1
        assert "risk_level" in prompts_received[0]


# ============================================================
# Config integration tests
# ============================================================


class TestConfigIntegration:
    """Tests for SDKConfig integration with DefaultSynthesizer."""

    async def test_uses_config_max_cross_llm_loops(self) -> None:
        """max_cross_llm_loops from config controls retry count."""
        call_count = 0

        def bad_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return ""

        config = SDKConfig(max_cross_llm_loops=5)
        synthesizer = DefaultSynthesizer(
            synthesis_fn=bad_fn, config=config
        )
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        await synthesizer.synthesize(aggregated, session, quality_threshold=0.9)

        # 1 initial + 5 retries = 6 total
        assert call_count == 6

    async def test_default_config_used_when_none_provided(self) -> None:
        """Default SDKConfig is used when no config is provided."""
        call_count = 0

        def bad_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return ""

        synthesizer = DefaultSynthesizer(synthesis_fn=bad_fn)
        aggregated = _make_aggregated(
            results=[_make_step_result("s1")]
        )
        session = _make_session_state()

        await synthesizer.synthesize(aggregated, session, quality_threshold=0.9)

        # Default max_cross_llm_loops is 3: 1 initial + 3 retries = 4
        assert call_count == 4
