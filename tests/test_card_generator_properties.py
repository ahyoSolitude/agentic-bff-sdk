"""Property-based tests for the CardGenerator module.

Uses Hypothesis to verify correctness properties of card generation
including JSON Schema compliance, channel capability adaptation,
and confirmation card generation.
"""

import asyncio
from typing import Any, Dict, List

import pytest
from hypothesis import given, settings, strategies as st, assume

from agentic_bff_sdk.card_generator import (
    DefaultCardGenerator,
    validate_card_output_schema,
)
from agentic_bff_sdk.models import (
    Card,
    CardOutput,
    CardType,
    SynthesisResult,
)


# ============================================================
# Hypothesis Strategies
# ============================================================

# Strategy for generating card types
card_type_strategy = st.sampled_from(list(CardType))

# Strategy for generating a Card
card_strategy = st.builds(
    Card,
    card_type=card_type_strategy,
    title=st.one_of(st.none(), st.text(min_size=0, max_size=50)),
    content=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(
            st.text(max_size=50),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
        min_size=0,
        max_size=5,
    ),
    actions=st.lists(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.text(max_size=30),
            min_size=1,
            max_size=3,
        ),
        min_size=0,
        max_size=3,
    ),
)

# Strategy for generating a CardOutput
card_output_strategy = st.builds(
    CardOutput,
    cards=st.lists(card_strategy, min_size=0, max_size=5),
    raw_text=st.one_of(st.none(), st.text(max_size=200)),
)

# Strategy for generating simple structured data
structured_data_strategy = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
        values=st.one_of(
            st.text(max_size=50),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
        min_size=0,
        max_size=5,
    ),
)

# Strategy for generating confirmation actions
confirmation_actions_strategy = st.lists(
    st.dictionaries(
        keys=st.sampled_from(["label", "action", "description"]),
        values=st.text(min_size=1, max_size=30),
        min_size=1,
        max_size=3,
    ),
    min_size=0,
    max_size=4,
)

# Strategy for generating a SynthesisResult
synthesis_result_strategy = st.builds(
    SynthesisResult,
    text_response=st.text(min_size=0, max_size=200),
    structured_data=structured_data_strategy,
    requires_confirmation=st.booleans(),
    confirmation_actions=confirmation_actions_strategy,
    quality_score=st.floats(min_value=0.0, max_value=1.0),
)

# Strategy for generating channel capabilities with supported card types
channel_capabilities_strategy = st.fixed_dictionaries(
    {"supported_card_types": st.lists(card_type_strategy, min_size=0, max_size=5)},
)


# ============================================================
# Property 24: 卡片输出 JSON Schema 合规
# ============================================================


@pytest.mark.property
class TestProperty24CardOutputJsonSchemaCompliance:
    """Property 24: 卡片输出 JSON Schema 合规

    **Validates: Requirements 10.4**

    For any generated CardOutput, serializing to JSON should pass
    the predefined JSON Schema validation.
    """

    @given(card_output=card_output_strategy)
    @settings(max_examples=100)
    def test_random_card_output_passes_schema(self, card_output: CardOutput) -> None:
        """Any valid CardOutput instance should pass JSON Schema validation."""
        assert validate_card_output_schema(card_output) is True, (
            f"CardOutput failed JSON Schema validation: {card_output.model_dump_json()}"
        )

    @given(synthesis=synthesis_result_strategy, caps=channel_capabilities_strategy)
    @settings(max_examples=100)
    def test_generated_card_output_passes_schema(
        self, synthesis: SynthesisResult, caps: Dict[str, Any]
    ) -> None:
        """CardOutput from DefaultCardGenerator should pass JSON Schema validation."""

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output = await generator.generate(synthesis, caps)
            assert validate_card_output_schema(output) is True, (
                f"Generated CardOutput failed JSON Schema validation: "
                f"{output.model_dump_json()}"
            )

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 25: 渠道能力适配
# ============================================================


@pytest.mark.property
class TestProperty25ChannelCapabilityAdaptation:
    """Property 25: 渠道能力适配

    **Validates: Requirements 10.3**

    For any channel capability description, generated cards should
    only use card types that the channel supports.
    """

    @given(
        synthesis=synthesis_result_strategy,
        supported_types=st.lists(card_type_strategy, min_size=0, max_size=5),
    )
    @settings(max_examples=100)
    def test_generated_cards_only_use_supported_types(
        self,
        synthesis: SynthesisResult,
        supported_types: List[CardType],
    ) -> None:
        """All cards in the output should have types in supported_card_types."""
        caps = {"supported_card_types": supported_types}
        supported_set = set(supported_types)

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output = await generator.generate(synthesis, caps)

            for card in output.cards:
                assert card.card_type in supported_set, (
                    f"Card type {card.card_type} not in supported types "
                    f"{supported_types}. Generated cards: "
                    f"{[c.card_type for c in output.cards]}"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(synthesis=synthesis_result_strategy)
    @settings(max_examples=100)
    def test_empty_supported_types_yields_no_cards(
        self, synthesis: SynthesisResult
    ) -> None:
        """When supported_card_types is empty, no cards should be generated."""
        caps: Dict[str, Any] = {"supported_card_types": []}

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output = await generator.generate(synthesis, caps)
            assert len(output.cards) == 0, (
                f"Expected no cards with empty supported types, "
                f"got {len(output.cards)} cards: "
                f"{[c.card_type for c in output.cards]}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(synthesis=synthesis_result_strategy)
    @settings(max_examples=100)
    def test_all_types_supported_preserves_all_cards(
        self, synthesis: SynthesisResult
    ) -> None:
        """When all card types are supported, no cards should be filtered out."""
        all_caps: Dict[str, Any] = {"supported_card_types": list(CardType)}
        no_filter_caps: Dict[str, Any] = {}

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output_all = await generator.generate(synthesis, all_caps)
            output_no_filter = await generator.generate(synthesis, no_filter_caps)

            # Both should produce the same cards
            assert len(output_all.cards) == len(output_no_filter.cards), (
                f"All-types ({len(output_all.cards)}) should match "
                f"no-filter ({len(output_no_filter.cards)})"
            )

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 26: 确认操作生成交互卡片
# ============================================================


@st.composite
def confirmation_synthesis_strategy(draw: st.DrawFn) -> SynthesisResult:
    """Generate a SynthesisResult with requires_confirmation=True."""
    return SynthesisResult(
        text_response=draw(st.text(min_size=1, max_size=200)),
        structured_data=draw(structured_data_strategy),
        requires_confirmation=True,
        confirmation_actions=draw(confirmation_actions_strategy),
        quality_score=draw(st.floats(min_value=0.0, max_value=1.0)),
    )


@pytest.mark.property
class TestProperty26ConfirmationCardGeneration:
    """Property 26: 确认操作生成交互卡片

    **Validates: Requirements 10.5**

    For any SynthesisResult with requires_confirmation=True, the
    generated CardOutput should contain at least one CONFIRMATION
    card with action buttons.
    """

    @given(synthesis=confirmation_synthesis_strategy())
    @settings(max_examples=100)
    def test_confirmation_required_generates_confirmation_card(
        self, synthesis: SynthesisResult
    ) -> None:
        """When requires_confirmation=True, output must contain a CONFIRMATION card."""
        # Use capabilities that support CONFIRMATION
        caps: Dict[str, Any] = {"supported_card_types": list(CardType)}

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output = await generator.generate(synthesis, caps)

            confirmation_cards = [
                c for c in output.cards if c.card_type == CardType.CONFIRMATION
            ]
            assert len(confirmation_cards) >= 1, (
                f"Expected at least one CONFIRMATION card when "
                f"requires_confirmation=True. Got card types: "
                f"{[c.card_type for c in output.cards]}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(synthesis=confirmation_synthesis_strategy())
    @settings(max_examples=100)
    def test_confirmation_card_has_actions(
        self, synthesis: SynthesisResult
    ) -> None:
        """CONFIRMATION card must have action buttons."""
        caps: Dict[str, Any] = {"supported_card_types": list(CardType)}

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output = await generator.generate(synthesis, caps)

            confirmation_cards = [
                c for c in output.cards if c.card_type == CardType.CONFIRMATION
            ]
            assert len(confirmation_cards) >= 1

            for card in confirmation_cards:
                assert len(card.actions) > 0, (
                    f"CONFIRMATION card must have action buttons, "
                    f"got empty actions list"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(synthesis=confirmation_synthesis_strategy())
    @settings(max_examples=100)
    def test_confirmation_not_generated_when_channel_unsupported(
        self, synthesis: SynthesisResult
    ) -> None:
        """When channel doesn't support CONFIRMATION, no CONFIRMATION card is generated."""
        caps: Dict[str, Any] = {"supported_card_types": [CardType.TEXT]}

        async def _run() -> None:
            generator = DefaultCardGenerator()
            output = await generator.generate(synthesis, caps)

            confirmation_cards = [
                c for c in output.cards if c.card_type == CardType.CONFIRMATION
            ]
            assert len(confirmation_cards) == 0, (
                f"Should not generate CONFIRMATION card when channel "
                f"doesn't support it"
            )

        asyncio.get_event_loop().run_until_complete(_run())
