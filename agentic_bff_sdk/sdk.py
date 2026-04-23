"""Factory for assembling the refactored Agentic BFF SDK."""

from __future__ import annotations

from pathlib import Path

from agentic_bff_sdk.aggregation import Aggregator, DefaultAggregator
from agentic_bff_sdk.channels import ChannelAdapter, ChannelRegistry, DefaultChannelAdapter
from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.dispatch import DefaultDispatcher, Dispatcher
from agentic_bff_sdk.domain import DefaultDomainGateway, DomainGateway, TaskPackage
from agentic_bff_sdk.events import InMemoryEventPublisher
from agentic_bff_sdk.gateway import AgenticBFFSDK
from agentic_bff_sdk.pipeline import DefaultRequestPipeline, RequestPipeline
from agentic_bff_sdk.planning import DefaultPlanner, Planner, SOPCompiler
from agentic_bff_sdk.response import DefaultResponseEngine, ResponseEngine
from agentic_bff_sdk.router import DefaultRouter, Router
from agentic_bff_sdk.session import SessionManager
from agentic_bff_sdk.tasks import TaskManager


def create_sdk(
    config: SDKConfig | str | Path | None = None,
    *,
    router: Router | None = None,
    planner: Planner | None = None,
    sop_compiler: SOPCompiler | None = None,
    domain_gateway: DomainGateway | None = None,
    dispatcher: Dispatcher | None = None,
    aggregator: Aggregator | None = None,
    response_engine: ResponseEngine | None = None,
    task_manager: TaskManager | None = None,
    channel_adapters: dict[str, ChannelAdapter] | None = None,
) -> AgenticBFFSDK:
    if config is None:
        sdk_config = SDKConfig()
    elif isinstance(config, SDKConfig):
        sdk_config = config
    else:
        sdk_config = SDKConfig.from_file(config)

    event_publisher = InMemoryEventPublisher()
    channels = ChannelRegistry()
    for channel_config in sdk_config.channels:
        channels.register(
            channel_config.channel_id,
            DefaultChannelAdapter(channel_config.capabilities),
        )
    for channel_id, adapter in (channel_adapters or {}).items():
        channels.register(channel_id, adapter)

    session_manager = SessionManager(runtime_config=sdk_config.runtime)
    resolved_domain_gateway = domain_gateway or DefaultDomainGateway()
    resolved_dispatcher = dispatcher or DefaultDispatcher(
        resolved_domain_gateway,
        event_publisher=event_publisher,
        default_timeout_seconds=sdk_config.runtime.step_execution_timeout_seconds,
    )

    pipeline: RequestPipeline = DefaultRequestPipeline(
        session_manager=session_manager,
        router=router or DefaultRouter(),
        planner=planner or DefaultPlanner(),
        sop_compiler=sop_compiler,
        dispatcher=resolved_dispatcher,
        aggregator=aggregator or DefaultAggregator(),
        response_engine=response_engine or DefaultResponseEngine(),
        channel_registry=channels,
        event_publisher=event_publisher,
    )
    return AgenticBFFSDK(
        pipeline=pipeline,
        task_manager=task_manager,
        domain_gateway=resolved_domain_gateway,
    )


def register_task_package(sdk: AgenticBFFSDK, package: TaskPackage) -> None:
    sdk.register_task_package(package)
