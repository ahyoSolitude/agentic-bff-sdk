"""Synthesizer for generating coherent natural language responses.

Implements the Synthesizer abstract base class and DefaultSynthesizer
which uses an LLM to synthesize aggregated multi-domain results into
a coherent response. Supports quality scoring, cross-LLM retry loops,
and rule engine result integration.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from langchain_core.language_models import BaseLanguageModel

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    AggregatedResult,
    SessionState,
    StepStatus,
    SynthesisResult,
)


class Synthesizer(ABC):
    """Abstract base class for result synthesizers.

    A Synthesizer takes aggregated multi-domain execution results and
    produces a coherent natural language response with quality scoring.
    """

    @abstractmethod
    async def synthesize(
        self,
        aggregated: AggregatedResult,
        session_state: SessionState,
        quality_threshold: float = 0.7,
    ) -> SynthesisResult:
        """Synthesize aggregated results into a coherent response.

        Args:
            aggregated: The aggregated results from multiple execution steps.
            session_state: Current session state with dialog history.
            quality_threshold: Minimum quality score threshold. If the
                generated response scores below this, a cross-LLM retry
                loop is triggered.

        Returns:
            SynthesisResult with the generated text, quality score,
            and optional structured data.
        """
        ...


def _build_synthesis_prompt(
    aggregated: AggregatedResult,
    session_state: SessionState,
    rule_engine_data: List[Dict[str, Any]],
    is_retry: bool = False,
    previous_response: Optional[str] = None,
    previous_score: Optional[float] = None,
) -> str:
    """Build the prompt for LLM synthesis.

    Args:
        aggregated: Aggregated step results.
        session_state: Current session state.
        rule_engine_data: Extracted rule engine outputs.
        is_retry: Whether this is a retry attempt.
        previous_response: The previous response text (for retry).
        previous_score: The previous quality score (for retry).

    Returns:
        A formatted prompt string.
    """
    parts: List[str] = []

    parts.append("You are a response synthesizer. Generate a coherent natural language response based on the following execution results.")

    # Add session context
    if session_state.dialog_history:
        recent = session_state.dialog_history[-3:]
        parts.append(f"\nRecent dialog context: {recent}")

    # Add step results
    parts.append("\nExecution results:")
    for step_result in aggregated.results:
        status_label = step_result.status.value
        parts.append(f"  - Step {step_result.step_id}: status={status_label}, result={step_result.result}")

    # Add missing steps info
    if aggregated.missing_steps:
        parts.append(f"\nMissing steps (partial result): {aggregated.missing_steps}")

    # Add rule engine data
    if rule_engine_data:
        parts.append(f"\nRule engine outputs: {rule_engine_data}")

    # Retry context
    if is_retry and previous_response is not None:
        parts.append(f"\nPrevious response (quality score {previous_score:.2f}, below threshold):")
        parts.append(f"  {previous_response}")
        parts.append("\nPlease generate an improved, more comprehensive response.")

    parts.append("\nGenerate a clear, coherent response that integrates all available information.")

    return "\n".join(parts)


def _extract_rule_engine_data(aggregated: AggregatedResult) -> List[Dict[str, Any]]:
    """Extract rule engine outputs from aggregated results.

    Looks for step results whose result data contains rule engine
    markers (dict with 'rule_engine_output' key).

    Args:
        aggregated: The aggregated results.

    Returns:
        List of rule engine output dictionaries.
    """
    rule_data: List[Dict[str, Any]] = []
    for step_result in aggregated.results:
        if isinstance(step_result.result, dict) and "rule_engine_output" in step_result.result:
            rule_data.append(step_result.result["rule_engine_output"])
    return rule_data


def _compute_quality_score(
    response_text: str,
    aggregated: AggregatedResult,
    rule_engine_data: List[Dict[str, Any]],
) -> float:
    """Compute a quality score for the synthesized response.

    The score is based on:
    - Response length (non-empty responses score higher)
    - Coverage of completed step results
    - Integration of rule engine data
    - Partial result penalty

    Args:
        response_text: The generated response text.
        aggregated: The aggregated results.
        rule_engine_data: Extracted rule engine outputs.

    Returns:
        A quality score between 0.0 and 1.0.
    """
    if not response_text or not response_text.strip():
        return 0.0

    score = 0.0

    # Base score for non-empty response
    score += 0.3

    # Length score: longer responses (up to a point) score higher
    text_len = len(response_text.strip())
    if text_len >= 10:
        score += 0.2
    elif text_len >= 1:
        score += 0.1

    # Coverage: check how many completed steps are referenced
    completed_steps = [
        r for r in aggregated.results if r.status == StepStatus.COMPLETED
    ]
    if completed_steps:
        score += 0.3
    elif aggregated.results:
        score += 0.1

    # Rule engine integration bonus
    if rule_engine_data:
        score += 0.1

    # Partial result penalty
    if aggregated.is_partial:
        score -= 0.1

    return max(0.0, min(1.0, score))


class DefaultSynthesizer(Synthesizer):
    """Default synthesizer implementation using an LLM.

    Uses a LangChain BaseLanguageModel to generate coherent natural
    language responses from aggregated multi-domain results. Supports:

    - Quality scoring for generated responses
    - Cross-LLM retry loop when quality is below threshold
    - Rule engine result integration
    - Optional custom synthesis function for testability

    Args:
        llm: A LangChain BaseLanguageModel for text generation.
        config: Optional SDKConfig for quality threshold and retry settings.
        synthesis_fn: Optional callable for custom synthesis logic.
            Signature: (prompt: str) -> str. When provided, this is used
            instead of the LLM for generating responses.
    """

    def __init__(
        self,
        llm: Optional[BaseLanguageModel] = None,
        config: Optional[SDKConfig] = None,
        synthesis_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._llm = llm
        self._config = config or SDKConfig()
        self._synthesis_fn = synthesis_fn

    async def _generate_response(self, prompt: str) -> str:
        """Generate a response using the synthesis function or LLM.

        Args:
            prompt: The synthesis prompt.

        Returns:
            Generated response text.
        """
        if self._synthesis_fn is not None:
            return self._synthesis_fn(prompt)

        if self._llm is None:
            raise ValueError(
                "DefaultSynthesizer requires either an LLM or a synthesis_fn"
            )

        result = await self._llm.ainvoke(prompt)
        # Handle both string and AIMessage responses
        if isinstance(result, str):
            return result
        return str(result.content) if hasattr(result, "content") else str(result)

    async def synthesize(
        self,
        aggregated: AggregatedResult,
        session_state: SessionState,
        quality_threshold: float = 0.7,
    ) -> SynthesisResult:
        """Synthesize aggregated results into a coherent response.

        Generates a response using the LLM, scores its quality, and
        retries with supplementary context if the score is below the
        quality threshold (up to max_cross_llm_loops times).

        Args:
            aggregated: The aggregated results from execution steps.
            session_state: Current session state.
            quality_threshold: Minimum acceptable quality score.

        Returns:
            SynthesisResult with generated text and quality score.
        """
        max_loops = self._config.max_cross_llm_loops

        # Extract rule engine data for integration
        rule_engine_data = _extract_rule_engine_data(aggregated)

        # Initial synthesis
        prompt = _build_synthesis_prompt(
            aggregated=aggregated,
            session_state=session_state,
            rule_engine_data=rule_engine_data,
        )
        response_text = await self._generate_response(prompt)
        quality_score = _compute_quality_score(
            response_text, aggregated, rule_engine_data
        )

        # Cross-LLM retry loop: retry if quality is below threshold
        loop_count = 0
        while quality_score < quality_threshold and loop_count < max_loops:
            loop_count += 1
            retry_prompt = _build_synthesis_prompt(
                aggregated=aggregated,
                session_state=session_state,
                rule_engine_data=rule_engine_data,
                is_retry=True,
                previous_response=response_text,
                previous_score=quality_score,
            )
            response_text = await self._generate_response(retry_prompt)
            quality_score = _compute_quality_score(
                response_text, aggregated, rule_engine_data
            )

        # Build structured data from rule engine outputs if present
        structured_data: Optional[Dict[str, Any]] = None
        if rule_engine_data:
            structured_data = {"rule_engine_results": rule_engine_data}

        return SynthesisResult(
            text_response=response_text,
            structured_data=structured_data,
            quality_score=quality_score,
        )
