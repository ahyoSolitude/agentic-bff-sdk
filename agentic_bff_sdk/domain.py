"""Domain routing and task package integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from agentic_bff_sdk.agent_executor import AgentExecutorFactory, DefaultAgentExecutorFactory, ToolCallable
from agentic_bff_sdk.models import AgentExecutorConfig, DomainCommand, DomainResult, ExecutionContext, ToolSpec


class TaskPackage(Protocol):
    name: str
    domain: str

    def get_tools(self) -> dict[str, ToolCallable]:
        ...

    def get_executor_config(self) -> AgentExecutorConfig:
        ...


class DomainGateway(ABC):
    @abstractmethod
    def register_task_package(self, package: TaskPackage) -> None:
        ...

    @abstractmethod
    async def invoke(self, command: DomainCommand, context: ExecutionContext) -> DomainResult:
        ...


class DefaultDomainGateway(DomainGateway):
    def __init__(self, executor_factory: AgentExecutorFactory | None = None) -> None:
        self._packages: dict[str, TaskPackage] = {}
        self._executor_factory = executor_factory or DefaultAgentExecutorFactory()

    def register_task_package(self, package: TaskPackage) -> None:
        self._packages[package.domain] = package

    async def invoke(self, command: DomainCommand, context: ExecutionContext) -> DomainResult:
        package = self._packages.get(command.domain)
        if package is None:
            return DomainResult(
                request_id=command.request_id,
                step_id=command.step_id,
                domain=command.domain,
                success=False,
                error_code="domain_unavailable",
                error_message=f"Domain '{command.domain}' is not registered.",
            )
        executor = self._executor_factory.create(package)
        return await executor.execute(command, context)
