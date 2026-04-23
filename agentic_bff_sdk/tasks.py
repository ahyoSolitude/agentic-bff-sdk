"""Async task lifecycle management."""

from __future__ import annotations

import asyncio
import time
import uuid

from agentic_bff_sdk.models import ErrorCode, ErrorResponse, GatewayRequest, ResponseEnvelope, TaskStateSnapshot, TaskStatus
from agentic_bff_sdk.pipeline import RequestPipeline


class TaskManager:
    def __init__(self, pipeline: RequestPipeline) -> None:
        self._pipeline = pipeline
        self._queue: asyncio.PriorityQueue[tuple[int, float, str]] = asyncio.PriorityQueue()
        self._snapshots: dict[str, TaskStateSnapshot] = {}
        self._requests: dict[str, GatewayRequest] = {}
        self._worker: asyncio.Task | None = None

    async def submit(self, request: GatewayRequest, *, priority: int = 0) -> str:
        task_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        self._requests[task_id] = request
        self._snapshots[task_id] = TaskStateSnapshot(
            task_id=task_id,
            status=TaskStatus.PENDING,
            request_id=request_id,
            session_id=request.session_id,
        )
        await self._queue.put((priority, time.time(), task_id))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        return task_id

    async def get_snapshot(self, task_id: str) -> TaskStateSnapshot:
        snapshot = self._snapshots.get(task_id)
        if snapshot is None:
            return TaskStateSnapshot(
                task_id=task_id,
                status=TaskStatus.FAILED,
                request_id="",
                session_id="",
                error=ErrorResponse(code=ErrorCode.INVALID_REQUEST, message="Unknown task_id."),
            )
        return snapshot

    async def retry(self, task_id: str) -> bool:
        snapshot = self._snapshots.get(task_id)
        if snapshot is None or snapshot.status != TaskStatus.FAILED:
            return False
        snapshot.status = TaskStatus.PENDING
        snapshot.error = None
        snapshot.result = None
        await self._queue.put((0, time.time(), task_id))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        return True

    async def _run(self) -> None:
        while not self._queue.empty():
            _, _, task_id = await self._queue.get()
            request = self._requests[task_id]
            snapshot = self._snapshots[task_id]
            snapshot.status = TaskStatus.RUNNING
            snapshot.progress_percent = 10.0
            response = await self._pipeline.run(request)
            if response.error:
                snapshot.status = TaskStatus.FAILED
                snapshot.error = response.error
                snapshot.progress_percent = 100.0
            else:
                snapshot.status = TaskStatus.COMPLETED
                snapshot.result = response.content or ResponseEnvelope(text="")
                snapshot.progress_percent = 100.0
