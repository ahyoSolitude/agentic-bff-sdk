"""SDK factory for building a complete Agentic BFF SDK instance from configuration.

Provides ``create_sdk`` which takes an OrchestrationConfig (or a config file
path) and wires up all components into a DefaultMASGateway ready for use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.card_generator import CardGenerator, DefaultCardGenerator
from agentic_bff_sdk.config import OrchestrationConfig
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher
from agentic_bff_sdk.domain_gateway import DefaultDomainGateway, DomainGateway
from agentic_bff_sdk.gateway import DefaultMASGateway
from agentic_bff_sdk.planner import IMCPlanner
from agentic_bff_sdk.plugins import (
    ChannelAdapter,
    DefaultChannelAdapter,
    PluginRegistry,
)
from agentic_bff_sdk.router import TopLevelRouter
from agentic_bff_sdk.session import InMemoryStorageBackend, SessionContext
from agentic_bff_sdk.synthesizer import Synthesizer


def create_sdk(
    config: OrchestrationConfig | str | Path,
    *,
    router: Optional[TopLevelRouter] = None,
    planner: Optional[IMCPlanner] = None,
    synthesizer: Optional[Synthesizer] = None,
    card_generator: Optional[CardGenerator] = None,
    domain_gateway: Optional[DomainGateway] = None,
    plugin_registry: Optional[PluginRegistry] = None,
    domain_invoker: Optional[Callable[..., Coroutine[Any, Any, Any]]] = None,
) -> DefaultMASGateway:
    """Create a fully wired DefaultMASGateway from configuration.

    This factory method builds all SDK components from the provided
    OrchestrationConfig and assembles them into a DefaultMASGateway.
    Components can be overridden by passing explicit instances.

    If ``config`` is a string or Path, it is loaded via
    ``OrchestrationConfig.from_file``.

    Args:
        config: An OrchestrationConfig instance, or a path to a YAML/JSON
            config file.
        router: Optional custom TopLevelRouter. If not provided, the
            router from the plugin_registry is used (if any). A router
            must be provided either directly or via the registry.
        planner: Optional custom IMCPlanner. Must be provided.
        synthesizer: Optional custom Synthesizer. Must be provided.
        card_generator: Optional custom CardGenerator. Defaults to
            DefaultCardGenerator if not provided.
        domain_gateway: Optional custom DomainGateway. Defaults to
            DefaultDomainGateway if not provided.
        plugin_registry: Optional PluginRegistry with pre-registered
            plugins. Plugins from the registry are used as fallbacks
            when explicit component arguments are not provided.
        domain_invoker: Optional domain invoker callable for the dispatcher.

    Returns:
        A fully configured DefaultMASGateway instance.

    Raises:
        ValueError: If required components (router, planner, synthesizer)
            are not provided either directly or via the plugin registry.
    """
    # Load config from file if needed
    if isinstance(config, (str, Path)):
        config = OrchestrationConfig.from_file(config)

    sdk_config = config.sdk
    registry = plugin_registry or PluginRegistry()

    # Resolve components: explicit arg > plugin registry > default
    resolved_router = router or registry.router
    if resolved_router is None:
        raise ValueError(
            "A TopLevelRouter must be provided either directly via the "
            "'router' argument or registered in the PluginRegistry."
        )

    resolved_planner = planner
    if resolved_planner is None:
        raise ValueError(
            "An IMCPlanner must be provided via the 'planner' argument."
        )

    resolved_synthesizer = synthesizer
    if resolved_synthesizer is None:
        raise ValueError(
            "A Synthesizer must be provided via the 'synthesizer' argument."
        )

    resolved_card_generator = card_generator or registry.generator or DefaultCardGenerator()

    # Build infrastructure components
    session_context = SessionContext(storage=InMemoryStorageBackend())
    dispatcher = ConcurrentDispatcher()
    aggregator = FanInAggregator()

    # Build domain gateway and register task packages from config
    resolved_domain_gateway = domain_gateway or DefaultDomainGateway(config=sdk_config)

    # Register channel adapters from config
    for channel_config in config.channels:
        # Register a default adapter for each configured channel
        adapter = DefaultChannelAdapter()
        registry.register_channel_adapter(channel_config.channel_id, adapter)

    # Build the gateway
    gateway = DefaultMASGateway(
        session_context=session_context,
        router=resolved_router,
        planner=resolved_planner,
        dispatcher=dispatcher,
        aggregator=aggregator,
        synthesizer=resolved_synthesizer,
        card_generator=resolved_card_generator,
        config=sdk_config,
        domain_invoker=domain_invoker,
    )

    # Register tools from the plugin registry into the gateway
    for tool in registry.tools:
        gateway.register_plugin("tool", tool)

    for chain in registry.chains:
        gateway.register_plugin("chain", chain)

    return gateway
