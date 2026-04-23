"""Domain agent execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Protocol

from agentic_bff_sdk.models import AgentExecutorConfig, DomainCommand, DomainResult, ExecutionContext, ToolSpec

ToolCallable = Callable[[dict[str, object], ExecutionContext], Awaitable[dict[str, object]]]


class TaskPackageForExecutor(Protocol):
    def get_tools(self) -> dict[str, ToolCallable]:
        ...

    def get_executor_config(self) -> AgentExecutorConfig:
        ...


class AgentExecutor(ABC):
    @abstractmethod
    async def execute(self, command: DomainCommand, context: ExecutionContext) -> DomainResult:
        ...


class DefaultAgentExecutor(AgentExecutor):
    def __init__(self, config: AgentExecutorConfig | None = None) -> None:
        self._config = config or AgentExecutorConfig()
        self._tools: dict[str, ToolCallable] = {}

    def register_tool(self, spec: ToolSpec, tool: ToolCallable) -> None:
        self._tools[spec.name] = tool

    async def execute(self, command: DomainCommand, context: ExecutionContext) -> DomainResult:
        tool = self._tools.get(command.action)
        if tool is None:
            return DomainResult(
                request_id=command.request_id,
                step_id=command.step_id,
                domain=command.domain,
                success=True,
                output={"domain": command.domain, "action": command.action, "payload": command.payload},
            )
        try:
            output = await tool(command.payload, context)
            return DomainResult(
                request_id=command.request_id,
                step_id=command.step_id,
                domain=command.domain,
                success=True,
                output=output,
            )
        except Exception as exc:
            return DomainResult(
                request_id=command.request_id,
                step_id=command.step_id,
                domain=command.domain,
                success=False,
                error_message=str(exc),
            )


class AgentExecutorFactory(ABC):
    @abstractmethod
    def create(self, package: TaskPackageForExecutor) -> AgentExecutor:
        ...


class DefaultAgentExecutorFactory(AgentExecutorFactory):
    def create(self, package: TaskPackageForExecutor) -> AgentExecutor:
        executor = DefaultAgentExecutor(package.get_executor_config())
        for name, tool in package.get_tools().items():
            executor.register_tool(ToolSpec(name=name, description=name), tool)
        return executor
