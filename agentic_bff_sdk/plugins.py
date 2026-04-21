"""Plugin system and channel adapter mechanism for the Agentic BFF SDK.

Provides:
- ChannelAdapter ABC and DefaultChannelAdapter for request/response adaptation
- PluginRegistry for registering custom TopLevelRouter, AgentExecutor,
  CardGenerator, and ChannelAdapter instances
- LangChain Tool/Chain registration for custom business logic
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from langchain_core.tools import BaseTool

from agentic_bff_sdk.agent_executor import AgentExecutor
from agentic_bff_sdk.card_generator import CardGenerator
from agentic_bff_sdk.models import RequestMessage
from agentic_bff_sdk.router import TopLevelRouter


# ============================================================
# ChannelAdapter ABC
# ============================================================


class ChannelAdapter(ABC):
    """Abstract base class for channel adapters.

    A ChannelAdapter transforms incoming channel-specific requests into
    the SDK's internal RequestMessage format, and transforms outgoing
    responses back into the channel-specific format.

    Each channel (web, mobile, phone, etc.) implements its own adapter
    to handle format differences without modifying core orchestration logic.
    """

    @abstractmethod
    async def adapt_request(self, request: Any) -> RequestMessage:
        """Adapt a channel-specific request to a RequestMessage.

        Args:
            request: The raw channel-specific request object.

        Returns:
            A RequestMessage in the SDK's internal format.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def adapt_response(self, response: Any) -> Any:
        """Adapt an SDK response to the channel-specific format.

        Args:
            response: The SDK's ResponseMessage or similar output.

        Returns:
            The channel-specific response object.
        """
        ...  # pragma: no cover


# ============================================================
# DefaultChannelAdapter
# ============================================================


class DefaultChannelAdapter(ChannelAdapter):
    """Default channel adapter that passes through without transformation.

    Suitable for channels that already use the SDK's RequestMessage and
    ResponseMessage formats directly.
    """

    async def adapt_request(self, request: Any) -> RequestMessage:
        """Pass through the request unchanged.

        If the request is already a RequestMessage, return it directly.
        Otherwise, attempt to construct a RequestMessage from a dict.

        Args:
            request: A RequestMessage instance or a dict with matching fields.

        Returns:
            A RequestMessage instance.

        Raises:
            TypeError: If the request cannot be converted to a RequestMessage.
        """
        if isinstance(request, RequestMessage):
            return request
        if isinstance(request, dict):
            return RequestMessage(**request)
        raise TypeError(
            f"DefaultChannelAdapter cannot adapt request of type {type(request).__name__}. "
            "Expected RequestMessage or dict."
        )

    async def adapt_response(self, response: Any) -> Any:
        """Pass through the response unchanged.

        Args:
            response: The SDK response object.

        Returns:
            The same response object, unmodified.
        """
        return response


# ============================================================
# PluginRegistry
# ============================================================


class PluginRegistry:
    """Registry for SDK plugins.

    Stores plugins by type, supporting registration and retrieval of:
    - ``router``: Custom TopLevelRouter implementations
    - ``executor``: Custom AgentExecutor implementations
    - ``generator``: Custom CardGenerator implementations
    - ``channel_adapter``: Custom ChannelAdapter implementations
    - ``tool``: LangChain BaseTool instances for custom business logic
    - ``chain``: LangChain Chain/Runnable instances for custom pipelines

    Each plugin type can hold multiple registered instances (except router,
    executor, and generator which store the most recently registered one
    as the active plugin).
    """

    # Valid plugin type keys
    VALID_TYPES = ("router", "executor", "generator", "channel_adapter", "tool", "chain")

    def __init__(self) -> None:
        self._routers: Optional[TopLevelRouter] = None
        self._executors: Optional[AgentExecutor] = None
        self._generators: Optional[CardGenerator] = None
        self._channel_adapters: Dict[str, ChannelAdapter] = {}
        self._tools: List[BaseTool] = []
        self._chains: List[Any] = []

    # ----------------------------------------------------------
    # Registration
    # ----------------------------------------------------------

    def register_router(self, router: TopLevelRouter) -> None:
        """Register a custom TopLevelRouter.

        Args:
            router: A TopLevelRouter implementation.

        Raises:
            TypeError: If the argument is not a TopLevelRouter instance.
        """
        if not isinstance(router, TopLevelRouter):
            raise TypeError(
                f"Expected TopLevelRouter instance, got {type(router).__name__}"
            )
        self._routers = router

    def register_executor(self, executor: AgentExecutor) -> None:
        """Register a custom AgentExecutor.

        Args:
            executor: An AgentExecutor implementation.

        Raises:
            TypeError: If the argument is not an AgentExecutor instance.
        """
        if not isinstance(executor, AgentExecutor):
            raise TypeError(
                f"Expected AgentExecutor instance, got {type(executor).__name__}"
            )
        self._executors = executor

    def register_generator(self, generator: CardGenerator) -> None:
        """Register a custom CardGenerator.

        Args:
            generator: A CardGenerator implementation.

        Raises:
            TypeError: If the argument is not a CardGenerator instance.
        """
        if not isinstance(generator, CardGenerator):
            raise TypeError(
                f"Expected CardGenerator instance, got {type(generator).__name__}"
            )
        self._generators = generator

    def register_channel_adapter(
        self, channel_id: str, adapter: ChannelAdapter
    ) -> None:
        """Register a channel adapter for a specific channel.

        Args:
            channel_id: The channel identifier.
            adapter: A ChannelAdapter implementation.

        Raises:
            TypeError: If the adapter is not a ChannelAdapter instance.
        """
        if not isinstance(adapter, ChannelAdapter):
            raise TypeError(
                f"Expected ChannelAdapter instance, got {type(adapter).__name__}"
            )
        self._channel_adapters[channel_id] = adapter

    def register_tool(self, tool: BaseTool) -> None:
        """Register a LangChain Tool for custom business logic.

        Args:
            tool: A LangChain BaseTool instance.

        Raises:
            TypeError: If the argument is not a BaseTool instance.
        """
        if not isinstance(tool, BaseTool):
            raise TypeError(
                f"Expected BaseTool instance, got {type(tool).__name__}"
            )
        self._tools.append(tool)

    def register_chain(self, chain: Any) -> None:
        """Register a LangChain Chain/Runnable for custom pipelines.

        Args:
            chain: A LangChain Chain or Runnable instance.
        """
        self._chains.append(chain)

    def register(self, plugin_type: str, plugin: Any, **kwargs: Any) -> None:
        """Generic registration method.

        Routes to the appropriate type-specific registration method.

        Args:
            plugin_type: One of "router", "executor", "generator",
                "channel_adapter", "tool", "chain".
            plugin: The plugin instance.
            **kwargs: Additional keyword arguments (e.g. ``channel_id``
                for channel_adapter registration).

        Raises:
            ValueError: If plugin_type is not recognized.
        """
        if plugin_type == "router":
            self.register_router(plugin)
        elif plugin_type == "executor":
            self.register_executor(plugin)
        elif plugin_type == "generator":
            self.register_generator(plugin)
        elif plugin_type == "channel_adapter":
            channel_id = kwargs.get("channel_id", "default")
            self.register_channel_adapter(channel_id, plugin)
        elif plugin_type == "tool":
            self.register_tool(plugin)
        elif plugin_type == "chain":
            self.register_chain(plugin)
        else:
            raise ValueError(
                f"Unknown plugin type '{plugin_type}'. "
                f"Valid types: {', '.join(self.VALID_TYPES)}"
            )

    # ----------------------------------------------------------
    # Retrieval
    # ----------------------------------------------------------

    @property
    def router(self) -> Optional[TopLevelRouter]:
        """The registered custom router, or None."""
        return self._routers

    @property
    def executor(self) -> Optional[AgentExecutor]:
        """The registered custom executor, or None."""
        return self._executors

    @property
    def generator(self) -> Optional[CardGenerator]:
        """The registered custom generator, or None."""
        return self._generators

    def get_channel_adapter(self, channel_id: str) -> Optional[ChannelAdapter]:
        """Get the channel adapter for a specific channel.

        Args:
            channel_id: The channel identifier.

        Returns:
            The registered ChannelAdapter, or None if not found.
        """
        return self._channel_adapters.get(channel_id)

    @property
    def channel_adapters(self) -> Dict[str, ChannelAdapter]:
        """All registered channel adapters, keyed by channel_id."""
        return dict(self._channel_adapters)

    @property
    def tools(self) -> List[BaseTool]:
        """All registered LangChain tools."""
        return list(self._tools)

    @property
    def chains(self) -> List[Any]:
        """All registered LangChain chains."""
        return list(self._chains)
