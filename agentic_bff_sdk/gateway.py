"""SDK gateway facade."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentic_bff_sdk.errors import ValidationError
from agentic_bff_sdk.domain import DomainGateway, TaskPackage
from agentic_bff_sdk.models import GatewayRequest, GatewayResponse, TaskStateSnapshot
from agentic_bff_sdk.pipeline import RequestPipeline
from agentic_bff_sdk.tasks import TaskManager


class MASGateway(ABC):
    @abstractmethod
    async def handle_request(self, request: GatewayRequest) -> GatewayResponse:
        ...

    @abstractmethod
    async def submit_task(self, request: GatewayRequest, *, priority: int = 0) -> str:
        ...

    @abstractmethod
    async def get_task(self, task_id: str) -> TaskStateSnapshot:
        ...


class AgenticBFFSDK(MASGateway):
    def __init__(
        self,
        pipeline: RequestPipeline,
        task_manager: TaskManager | None = None,
        domain_gateway: DomainGateway | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._tasks = task_manager or TaskManager(pipeline)
        self._domain_gateway = domain_gateway

    async def handle_request(self, request: GatewayRequest) -> GatewayResponse:
        try:
            self._validate_request(request)
        except ValidationError as exc:
            return GatewayResponse(
                session_id=request.session_id,
                request_id="",
                error=exc.to_error_response(),
            )
        return await self._pipeline.run(request)

    async def submit_task(self, request: GatewayRequest, *, priority: int = 0) -> str:
        self._validate_request(request)
        return await self._tasks.submit(request, priority=priority)

    async def get_task(self, task_id: str) -> TaskStateSnapshot:
        return await self._tasks.get_snapshot(task_id)

    async def retry_task(self, task_id: str) -> bool:
        return await self._tasks.retry(task_id)

    def register_task_package(self, package: TaskPackage) -> None:
        if self._domain_gateway is None:
            raise RuntimeError("This SDK instance was not created with a DomainGateway.")
        self._domain_gateway.register_task_package(package)

    @staticmethod
    def _validate_request(request: GatewayRequest) -> None:
        if not request.session_id:
            raise ValidationError("session_id is required.")
        if not request.channel_id:
            raise ValidationError("channel_id is required.")
