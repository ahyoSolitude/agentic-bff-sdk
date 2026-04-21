"""Card Generator for converting synthesis results to rich media cards.

Implements the CardGenerator abstract base class and DefaultCardGenerator
which transforms SynthesisResult into channel-adapted rich media cards.
Supports multiple card types, channel capability filtering, confirmation
card generation, and JSON Schema output validation.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agentic_bff_sdk.models import (
    Card,
    CardOutput,
    CardType,
    SynthesisResult,
)


class CardGenerator(ABC):
    """Abstract base class for rich media card generators.

    A CardGenerator takes a SynthesisResult and channel capabilities,
    and produces a CardOutput containing one or more rich media cards
    adapted to the target channel's rendering capabilities.
    """

    @abstractmethod
    async def generate(
        self,
        synthesis: SynthesisResult,
        channel_capabilities: Dict[str, Any],
    ) -> CardOutput:
        """Generate rich media cards from synthesis results.

        Args:
            synthesis: The synthesized result containing text, structured
                data, and confirmation requirements.
            channel_capabilities: A dictionary describing the target
                channel's rendering capabilities. Must contain a
                ``supported_card_types`` key with a list of CardType
                values the channel supports.

        Returns:
            CardOutput containing the generated cards and optional raw text.
        """
        ...


def _build_text_card(synthesis: SynthesisResult) -> Card:
    """Build a TEXT card from the synthesis text response.

    Args:
        synthesis: The synthesis result.

    Returns:
        A Card of type TEXT.
    """
    return Card(
        card_type=CardType.TEXT,
        title="Response",
        content={"text": synthesis.text_response},
    )


def _build_table_card(structured_data: Dict[str, Any]) -> Card:
    """Build a TABLE card from structured data.

    Args:
        structured_data: Dictionary containing structured data to display.

    Returns:
        A Card of type TABLE.
    """
    return Card(
        card_type=CardType.TABLE,
        title="Data",
        content={"data": structured_data},
    )


def _build_chart_card(structured_data: Dict[str, Any]) -> Card:
    """Build a CHART card from structured data containing chart info.

    Args:
        structured_data: Dictionary containing chart-related data.

    Returns:
        A Card of type CHART.
    """
    return Card(
        card_type=CardType.CHART,
        title="Chart",
        content={"chart_data": structured_data},
    )


def _build_action_button_card(actions: List[Dict[str, Any]]) -> Card:
    """Build an ACTION_BUTTON card from a list of actions.

    Args:
        actions: List of action dictionaries.

    Returns:
        A Card of type ACTION_BUTTON.
    """
    return Card(
        card_type=CardType.ACTION_BUTTON,
        title="Actions",
        content={"buttons": actions},
        actions=actions,
    )


def _build_confirmation_card(
    confirmation_actions: List[Dict[str, Any]],
    text_response: str,
) -> Card:
    """Build a CONFIRMATION card for user confirmation interactions.

    Args:
        confirmation_actions: List of action dictionaries for confirmation.
        text_response: The text summary to display in the confirmation.

    Returns:
        A Card of type CONFIRMATION with action buttons.
    """
    actions = confirmation_actions if confirmation_actions else [
        {"label": "Confirm", "action": "confirm"},
        {"label": "Cancel", "action": "cancel"},
    ]
    return Card(
        card_type=CardType.CONFIRMATION,
        title="Confirmation Required",
        content={"summary": text_response, "actions": actions},
        actions=actions,
    )


def _filter_cards_by_channel(
    cards: List[Card],
    channel_capabilities: Dict[str, Any],
) -> List[Card]:
    """Filter cards based on channel supported card types.

    Args:
        cards: List of generated cards.
        channel_capabilities: Channel capabilities dict with
            ``supported_card_types`` key.

    Returns:
        Filtered list of cards whose types are supported by the channel.
    """
    supported = channel_capabilities.get("supported_card_types")
    if supported is None:
        # No filtering if capabilities not specified
        return cards

    supported_set = set()
    for ct in supported:
        if isinstance(ct, CardType):
            supported_set.add(ct)
        elif isinstance(ct, str):
            try:
                supported_set.add(CardType(ct))
            except ValueError:
                pass

    return [card for card in cards if card.card_type in supported_set]


def validate_card_output_schema(card_output: CardOutput) -> bool:
    """Validate that a CardOutput conforms to its JSON Schema.

    Uses Pydantic's model_json_schema to generate the schema and
    validates the serialized output against it.

    Args:
        card_output: The CardOutput to validate.

    Returns:
        True if the output is valid, False otherwise.
    """
    import jsonschema

    schema = CardOutput.model_json_schema()
    data = card_output.model_dump(mode="json")
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.ValidationError:
        return False


class DefaultCardGenerator(CardGenerator):
    """Default card generator implementation.

    Converts SynthesisResult into rich media cards with support for:

    - TEXT cards from text responses
    - TABLE cards from structured data
    - CHART cards from chart-specific structured data
    - ACTION_BUTTON cards from action lists
    - CONFIRMATION cards when confirmation is required
    - Channel capability filtering
    - JSON Schema output validation
    """

    async def generate(
        self,
        synthesis: SynthesisResult,
        channel_capabilities: Dict[str, Any],
    ) -> CardOutput:
        """Generate rich media cards from synthesis results.

        The generation logic:
        1. Always generate a TEXT card from the text response.
        2. If structured_data is present, generate a TABLE card.
        3. If structured_data contains ``chart_data``, generate a CHART card.
        4. If confirmation_actions are present (without requires_confirmation),
           generate an ACTION_BUTTON card.
        5. If requires_confirmation is True, generate a CONFIRMATION card.
        6. Filter all cards by channel capabilities.

        Args:
            synthesis: The synthesis result.
            channel_capabilities: Channel capabilities dictionary.

        Returns:
            CardOutput with filtered cards and raw text.
        """
        cards: List[Card] = []

        # 1. Always generate a TEXT card
        cards.append(_build_text_card(synthesis))

        # 2. TABLE card from structured data
        if synthesis.structured_data:
            cards.append(_build_table_card(synthesis.structured_data))

            # 3. CHART card if chart_data is present in structured data
            if "chart_data" in synthesis.structured_data:
                cards.append(
                    _build_chart_card(synthesis.structured_data["chart_data"])
                )

        # 4. ACTION_BUTTON card from confirmation_actions (when not confirmation)
        if synthesis.confirmation_actions and not synthesis.requires_confirmation:
            cards.append(_build_action_button_card(synthesis.confirmation_actions))

        # 5. CONFIRMATION card when requires_confirmation is True
        if synthesis.requires_confirmation:
            cards.append(
                _build_confirmation_card(
                    synthesis.confirmation_actions,
                    synthesis.text_response,
                )
            )

        # 6. Filter by channel capabilities
        filtered_cards = _filter_cards_by_channel(cards, channel_capabilities)

        return CardOutput(
            cards=filtered_cards,
            raw_text=synthesis.text_response,
        )
