"""Channel adaptation and capability negotiation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentic_bff_sdk.models import ChannelCapabilities, GatewayRequest, ResponseEnvelope


class ChannelAdapter(ABC):
    @abstractmethod
    async def adapt_inbound(self, payload: object) -> GatewayRequest:
        ...

    @abstractmethod
    async def adapt_outbound(self, response: ResponseEnvelope) -> object:
        ...

    @abstractmethod
    def get_capabilities(self) -> ChannelCapabilities:
        ...


class DefaultChannelAdapter(ChannelAdapter):
    def __init__(self, capabilities: ChannelCapabilities | None = None) -> None:
        self._capabilities = capabilities or ChannelCapabilities()

    async def adapt_inbound(self, payload: object) -> GatewayRequest:
        if isinstance(payload, GatewayRequest):
            return payload
        if isinstance(payload, dict):
            return GatewayRequest(**payload)
        raise TypeError(f"Cannot adapt inbound payload of type {type(payload).__name__}.")

    async def adapt_outbound(self, response: ResponseEnvelope) -> object:
        return response.model_dump(mode="json")

    def get_capabilities(self) -> ChannelCapabilities:
        return self._capabilities


class ChannelRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, channel_id: str, adapter: ChannelAdapter) -> None:
        self._adapters[channel_id] = adapter

    def get(self, channel_id: str) -> ChannelAdapter:
        return self._adapters.get(channel_id, DefaultChannelAdapter())
