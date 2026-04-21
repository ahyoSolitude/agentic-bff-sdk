"""Unit tests for the CardGenerator module."""

from typing import Any, Dict, List

import pytest

from agentic_bff_sdk.card_generator import (
    CardGenerator,
    DefaultCardGenerator,
    _build_action_button_card,
    _build_chart_card,
    _build_confirmation_card,
    _build_table_card,
    _build_text_card,
    _filter_cards_by_channel,
    validate_card_output_schema,
)
from agentic_bff_sdk.models import (
    Card,
    CardOutput,
    CardType,
    SynthesisResult,
)


# ============================================================
# Helpers
# ============================================================


def _make_synthesis(
    text_response: str = "Hello world",
    structured_data: Dict[str, Any] | None = None,
    requires_confirmation: bool = False,
    confirmation_actions: List[Dict[str, Any]] | None = None,
    quality_score: float = 0.8,
) -> SynthesisResult:
    return SynthesisResult(
        text_response=text_response,
        structured_data=structured_data,
        requires_confirmation=requires_confirmation,
        confirmation_actions=confirmation_actions or [],
        quality_score=quality_score,
    )


def _all_types_capabilities() -> Dict[str, Any]:
    return {"supported_card_types": list(CardType)}


def _text_only_capabilities() -> Dict[str, Any]:
    return {"supported_card_types": [CardType.TEXT]}


# ============================================================
# CardGenerator ABC tests
# ============================================================


class TestCardGeneratorABC:
    """Tests for the CardGenerator abstract base class."""

    def test_card_generator_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            CardGenerator()  # type: ignore[abstract]

    def test_subclass_must_implement_generate(self) -> None:
        class IncompleteGenerator(CardGenerator):
            pass

        with pytest.raises(TypeError):
            IncompleteGenerator()  # type: ignore[abstract]


# ============================================================
# Card builder function tests
# ============================================================


class TestCardBuilders:
    """Tests for individual card builder functions."""

    def test_build_text_card(self) -> None:
        synthesis = _make_synthesis(text_response="Test text")
        card = _build_text_card(synthesis)
        assert card.card_type == CardType.TEXT
        assert card.content["text"] == "Test text"

    def test_build_table_card(self) -> None:
        data = {"key": "value", "count": 42}
        card = _build_table_card(data)
        assert card.card_type == CardType.TABLE
        assert card.content["data"] == data

    def test_build_chart_card(self) -> None:
        chart_data = {"labels": ["A", "B"], "values": [10, 20]}
        card = _build_chart_card(chart_data)
        assert card.card_type == CardType.CHART
        assert card.content["chart_data"] == chart_data

    def test_build_action_button_card(self) -> None:
        actions = [{"label": "Click", "action": "do_something"}]
        card = _build_action_button_card(actions)
        assert card.card_type == CardType.ACTION_BUTTON
        assert card.actions == actions

    def test_build_confirmation_card_with_actions(self) -> None:
        actions = [{"label": "Yes", "action": "confirm"}]
        card = _build_confirmation_card(actions, "Please confirm")
        assert card.card_type == CardType.CONFIRMATION
        assert card.actions == actions
        assert card.content["summary"] == "Please confirm"

    def test_build_confirmation_card_default_actions(self) -> None:
        card = _build_confirmation_card([], "Confirm?")
        assert card.card_type == CardType.CONFIRMATION
        assert len(card.actions) == 2
        assert card.actions[0]["label"] == "Confirm"
        assert card.actions[1]["label"] == "Cancel"


# ============================================================
# Channel filtering tests
# ============================================================


class TestChannelFiltering:
    """Tests for channel capability filtering."""

    def test_no_supported_types_key_returns_all(self) -> None:
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "hi"}),
            Card(card_type=CardType.TABLE, content={"data": {}}),
        ]
        filtered = _filter_cards_by_channel(cards, {})
        assert len(filtered) == 2

    def test_filter_to_text_only(self) -> None:
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "hi"}),
            Card(card_type=CardType.TABLE, content={"data": {}}),
            Card(card_type=CardType.CHART, content={"chart_data": {}}),
        ]
        filtered = _filter_cards_by_channel(cards, _text_only_capabilities())
        assert len(filtered) == 1
        assert filtered[0].card_type == CardType.TEXT

    def test_filter_with_string_card_types(self) -> None:
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "hi"}),
            Card(card_type=CardType.TABLE, content={"data": {}}),
        ]
        caps = {"supported_card_types": ["text", "table"]}
        filtered = _filter_cards_by_channel(cards, caps)
        assert len(filtered) == 2

    def test_filter_with_invalid_string_type_ignored(self) -> None:
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "hi"}),
        ]
        caps = {"supported_card_types": ["text", "invalid_type"]}
        filtered = _filter_cards_by_channel(cards, caps)
        assert len(filtered) == 1

    def test_empty_supported_types_filters_all(self) -> None:
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "hi"}),
        ]
        caps = {"supported_card_types": []}
        filtered = _filter_cards_by_channel(cards, caps)
        assert len(filtered) == 0

    def test_all_types_supported_returns_all(self) -> None:
        cards = [
            Card(card_type=CardType.TEXT, content={"text": "hi"}),
            Card(card_type=CardType.TABLE, content={"data": {}}),
            Card(card_type=CardType.CONFIRMATION, content={"summary": "ok"}, actions=[]),
        ]
        filtered = _filter_cards_by_channel(cards, _all_types_capabilities())
        assert len(filtered) == 3


# ============================================================
# JSON Schema validation tests
# ============================================================


class TestSchemaValidation:
    """Tests for JSON Schema output validation."""

    def test_valid_card_output_passes_schema(self) -> None:
        output = CardOutput(
            cards=[Card(card_type=CardType.TEXT, content={"text": "hi"})],
            raw_text="hi",
        )
        assert validate_card_output_schema(output) is True

    def test_empty_cards_passes_schema(self) -> None:
        output = CardOutput(cards=[], raw_text=None)
        assert validate_card_output_schema(output) is True

    def test_multiple_cards_passes_schema(self) -> None:
        output = CardOutput(
            cards=[
                Card(card_type=CardType.TEXT, content={"text": "hi"}),
                Card(card_type=CardType.TABLE, content={"data": {"k": "v"}}),
                Card(
                    card_type=CardType.CONFIRMATION,
                    content={"summary": "ok"},
                    actions=[{"label": "Yes", "action": "confirm"}],
                ),
            ],
            raw_text="hi",
        )
        assert validate_card_output_schema(output) is True


# ============================================================
# DefaultCardGenerator tests
# ============================================================


class TestDefaultCardGenerator:
    """Tests for DefaultCardGenerator."""

    async def test_basic_text_response(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(text_response="Hello")
        output = await gen.generate(synthesis, _all_types_capabilities())

        assert len(output.cards) >= 1
        assert output.cards[0].card_type == CardType.TEXT
        assert output.raw_text == "Hello"

    async def test_structured_data_generates_table(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            structured_data={"key": "value"}
        )
        output = await gen.generate(synthesis, _all_types_capabilities())

        card_types = [c.card_type for c in output.cards]
        assert CardType.TABLE in card_types

    async def test_chart_data_generates_chart(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            structured_data={"chart_data": {"labels": ["A"], "values": [1]}}
        )
        output = await gen.generate(synthesis, _all_types_capabilities())

        card_types = [c.card_type for c in output.cards]
        assert CardType.CHART in card_types

    async def test_confirmation_generates_confirmation_card(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            requires_confirmation=True,
            confirmation_actions=[{"label": "OK", "action": "confirm"}],
        )
        output = await gen.generate(synthesis, _all_types_capabilities())

        card_types = [c.card_type for c in output.cards]
        assert CardType.CONFIRMATION in card_types

    async def test_confirmation_card_has_actions(self) -> None:
        gen = DefaultCardGenerator()
        actions = [{"label": "Yes", "action": "approve"}]
        synthesis = _make_synthesis(
            requires_confirmation=True,
            confirmation_actions=actions,
        )
        output = await gen.generate(synthesis, _all_types_capabilities())

        confirmation_cards = [
            c for c in output.cards if c.card_type == CardType.CONFIRMATION
        ]
        assert len(confirmation_cards) == 1
        assert confirmation_cards[0].actions == actions

    async def test_channel_filtering_applied(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            structured_data={"key": "value"},
            requires_confirmation=True,
        )
        output = await gen.generate(synthesis, _text_only_capabilities())

        for card in output.cards:
            assert card.card_type == CardType.TEXT

    async def test_action_buttons_without_confirmation(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            requires_confirmation=False,
            confirmation_actions=[{"label": "Do it", "action": "execute"}],
        )
        output = await gen.generate(synthesis, _all_types_capabilities())

        card_types = [c.card_type for c in output.cards]
        assert CardType.ACTION_BUTTON in card_types
        assert CardType.CONFIRMATION not in card_types

    async def test_output_passes_json_schema(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            structured_data={"key": "value"},
            requires_confirmation=True,
            confirmation_actions=[{"label": "OK", "action": "confirm"}],
        )
        output = await gen.generate(synthesis, _all_types_capabilities())

        assert validate_card_output_schema(output) is True

    async def test_no_capabilities_key_returns_all_cards(self) -> None:
        gen = DefaultCardGenerator()
        synthesis = _make_synthesis(
            structured_data={"key": "value"},
            requires_confirmation=True,
        )
        output = await gen.generate(synthesis, {})

        # Without supported_card_types, all cards should be present
        assert len(output.cards) >= 2  # TEXT + TABLE + CONFIRMATION at minimum
