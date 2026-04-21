"""MAS Gateway — global entry point for the Agentic BFF SDK.

Provides the MASGateway abstract base class and DefaultMASGateway
implementation that orchestrates the full request processing pipeline:
request validation → session restore → intent routing → plan generation →
concurrent dispatch → result aggregation → synthesis → card generation.

Also supports async task management with priority queues, task status
tracking, callback notifications, and failed task retry.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.card_generator import CardGenerator
from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher
from agentic_bff_sdk.models import (
    CardOutput,
    ClarificationQuestion,
    ErrorResponse,
    RequestMessage,
    ResponseMessage,
    TaskStatus,
)
from agentic_bff_sdk.planner import IMCPlanner
from agentic_bff_sdk.router import TopLevelRouter
from agentic_bff_sdk.session import SessionContext
from agentic_bff_sdk.synthesizer import Synthesizer

logger = logging.getLogger(__name__)


# ============================================================
# MASGateway ABC
# ============================================================


class MASGateway(ABC):
    """全局 MAS 入口抽象基类。

    Defines the contract for the multi-agent system gateway, including
    synchronous request handling, async task management, and plugin
    registration.
    """

    @abstractmethod
    async def handle_request(self, request: RequestMessage) -> ResponseMessage:
        """处理同步请求。

        Args:
            request: The incoming request message.

        Returns:
            A ResponseMessage with the processing result or error.
        """
        ...

    @abstractmethod
    async def submit_async_task(
        self, request: RequestMessage, priority: int = 0
    ) -> str:
        """提交异步任务，返回 task_id。

        Args:
            request: The request to process asynchronously.
            priority: Task priority (lower number = higher priority).

        Returns:
            A unique task_id string.
        """
        ...

    @abstractmethod
    async def get_task_status(self, task_id: str) -> TaskStatus:
        """查询异步任务状态。

        Args:
            task_id: The task identifier.

        Returns:
            Current TaskStatus of the task.
        """
        ...

    @abstractmethod
    def register_plugin(self, plugin_type: str, plugin: Any) -> None:
        """注册自定义插件（路由器、执行器、生成器）。

        Args:
            plugin_type: The type of plugin (e.g. "router", "executor", "generator").
            plugin: The plugin instance.
        """
        ...


# ============================================================
# Async Task Entry
# ============================================================


class _AsyncTaskEntry:
    """Internal representation of an async task."""

    __slots__ = (
        "task_id",
        "request",
        "priority",
        "status",
        "result",
        "error",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        task_id: str,
        request: RequestMessage,
        priority: int,
    ) -> None:
        self.task_id = task_id
        self.request = request
        self.priority = priority
        self.status: TaskStatus = TaskStatus.PENDING
        self.result: Optional[ResponseMessage] = None
        self.error: Optional[str] = None
        self.created_at: float = time.time()
        self.updated_at: float = self.created_at


# ============================================================
# DefaultMASGateway
# ============================================================


class DefaultMASGateway(MASGateway):
    """Default implementation of the MAS Gateway.

    Orchestrates the full request processing pipeline by composing
    all SDK components. Supports:

    - Request validation (session_id / channel_id)
    - Synchronous pipeline: session → routing → planning → dispatch →
      aggregation → synthesis → card generation
    - Async task management with priority queue
    - Task status tracking and callback notifications
    - Failed task recording and manual retry
    - Session idle timeout cleanup
    - Plugin registration
    """

    def __init__(
        self,
        session_context: SessionContext,
        router: TopLevelRouter,
        planner: IMCPlanner,
        dispatcher: ConcurrentDispatcher,
        aggregator: FanInAggregator,
        synthesizer: Synthesizer,
        card_generator: CardGenerator,
        config: Optional[SDKConfig] = None,
        domain_invoker: Optional[
            Callable[..., Coroutine[Any, Any, Any]]
        ] = None,
    ) -> None:
        """Initialize DefaultMASGateway.

        Args:
            session_context: Session management component.
            router: Intent routing component.
            planner: Execution plan generation component.
            dispatcher: DAG concurrent dispatch component.
            aggregator: Fan-in result aggregation component.
            synthesizer: Result synthesis component.
            card_generator: Rich media card generation component.
            config: SDK global configuration.
            domain_invoker: Optional domain invoker callable for the dispatcher.
        """
        self._session_context = session_context
        self._router = router
        self._planner = planner
        self._dispatcher = dispatcher
        self._aggregator = aggregator
        self._synthesizer = synthesizer
        self._card_generator = card_generator
        self._config = config or SDKConfig()
        self._domain_invoker = domain_invoker

        # Plugin registry
        self._plugins: Dict[str, Any] = {}

        # Async task management
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._tasks: Dict[str, _AsyncTaskEntry] = {}
        self._task_worker: Optional[asyncio.Task] = None

        # Callback configuration
        self._callback_url: Optional[str] = self._config.async_task_callback_url
        self._callback_type: str = self._config.async_task_callback_type

    # ----------------------------------------------------------
    # Properties
    # ----------------------------------------------------------

    @property
    def session_context(self) -> SessionContext:
        return self._session_context

    @property
    def config(self) -> SDKConfig:
        return self._config

    @property
    def plugins(self) -> Dict[str, Any]:
        return dict(self._plugins)

    @property
    def tasks(self) -> Dict[str, _AsyncTaskEntry]:
        return self._tasks

    # ----------------------------------------------------------
    # Request Validation
    # ----------------------------------------------------------

    def _validate_request(
        self, request: RequestMessage
    ) -> Optional[ResponseMessage]:
        """Validate the request message.

        Returns an error ResponseMessage if validation fails, None otherwise.
        """
        if not request.session_id:
            return ResponseMessage(
                session_id="",
                content=None,
                error=ErrorResponse(
                    code="REQ_MISSING_SESSION_ID",
                    message="session_id is required and cannot be empty",
                ),
            )
        if not request.channel_id:
            return ResponseMessage(
                session_id=request.session_id,
                content=None,
                error=ErrorResponse(
                    code="REQ_MISSING_CHANNEL_ID",
                    message="channel_id is required and cannot be empty",
                ),
            )
        return None

    # ----------------------------------------------------------
    # handle_request — synchronous pipeline
    # ----------------------------------------------------------

    async def handle_request(self, request: RequestMessage) -> ResponseMessage:
        """Process a synchronous request through the full pipeline.

        Pipeline:
        1. Validate request (session_id, channel_id)
        2. Restore/create session
        3. Route intent
        4. Generate execution plan
        5. Dispatch steps concurrently
        6. Aggregate results
        7. Synthesize response
        8. Generate cards

        Args:
            request: The incoming request message.

        Returns:
            ResponseMessage with card output or error.
        """
        # Step 1: Validate request
        error_response = self._validate_request(request)
        if error_response is not None:
            return error_response

        try:
            # Step 2: Restore or create session
            session_state = await self._session_context.get_or_create(
                request.session_id
            )
            # Update last_active_at
            session_state.last_active_at = time.time()

            # Step 3: Route intent
            route_result = await self._router.route(
                user_input=request.user_input,
                session_state=session_state,
            )

            # If clarification is needed, return it directly
            if isinstance(route_result, ClarificationQuestion):
                await self._session_context.save(
                    request.session_id, session_state
                )
                return ResponseMessage(
                    session_id=request.session_id,
                    content={
                        "question": route_result.question,
                        "candidates": [
                            c.model_dump() for c in route_result.candidates
                        ],
                    },
                )

            # Step 4: Generate execution plan
            intent = route_result
            plan = await self._planner.generate_plan(
                intent=intent,
                session_state=session_state,
            )

            # Step 5: Dispatch steps concurrently
            if self._domain_invoker is not None:
                step_results = await self._dispatcher.dispatch(
                    plan=plan,
                    domain_invoker=self._domain_invoker,
                    step_timeout_seconds=self._config.step_execution_timeout_seconds,
                )
            else:
                step_results = []

            # Step 6: Aggregate results
            expected_step_ids = [s.step_id for s in plan.steps]
            aggregated = await self._aggregator.aggregate(
                step_results=step_results,
                expected_steps=expected_step_ids,
                wait_timeout_seconds=self._config.fan_in_wait_timeout_seconds,
            )

            # Step 7: Synthesize response
            synthesis = await self._synthesizer.synthesize(
                aggregated=aggregated,
                session_state=session_state,
                quality_threshold=self._config.synthesis_quality_threshold,
            )

            # Step 8: Generate cards
            channel_capabilities = request.metadata.get(
                "channel_capabilities", {}
            )
            card_output = await self._card_generator.generate(
                synthesis=synthesis,
                channel_capabilities=channel_capabilities,
            )

            # Save session state
            # Add dialog turn
            session_state.dialog_history.append(
                {"role": "user", "content": request.user_input}
            )
            session_state.dialog_history.append(
                {"role": "assistant", "content": synthesis.text_response}
            )
            await self._session_context.save(
                request.session_id, session_state
            )

            return ResponseMessage(
                session_id=request.session_id,
                content=card_output.model_dump(),
            )

        except Exception as exc:
            logger.exception("Error processing request: %s", exc)
            return ResponseMessage(
                session_id=request.session_id,
                content=None,
                error=ErrorResponse(
                    code="SYS_INTERNAL_ERROR",
                    message=f"Internal error: {exc}",
                ),
            )

    # ----------------------------------------------------------
    # Async Task Management
    # ----------------------------------------------------------

    async def submit_async_task(
        self, request: RequestMessage, priority: int = 0
    ) -> str:
        """Submit an async task with priority.

        Creates a task entry, enqueues it in the priority queue, and
        starts the worker if not already running.

        Args:
            request: The request to process asynchronously.
            priority: Task priority (lower number = higher priority).

        Returns:
            A unique task_id string.
        """
        task_id = str(uuid.uuid4())
        entry = _AsyncTaskEntry(
            task_id=task_id,
            request=request,
            priority=priority,
        )
        self._tasks[task_id] = entry

        # PriorityQueue sorts by first element of tuple
        await self._task_queue.put((priority, time.time(), task_id))

        # Start worker if not running
        if self._task_worker is None or self._task_worker.done():
            self._task_worker = asyncio.create_task(self._process_task_queue())

        return task_id

    async def get_task_status(self, task_id: str) -> TaskStatus:
        """Query the status of an async task.

        Args:
            task_id: The task identifier.

        Returns:
            Current TaskStatus. Returns FAILED if task_id is unknown.
        """
        entry = self._tasks.get(task_id)
        if entry is None:
            return TaskStatus.FAILED
        return entry.status

    async def get_task_result(self, task_id: str) -> Optional[ResponseMessage]:
        """Get the result of a completed async task.

        Args:
            task_id: The task identifier.

        Returns:
            The ResponseMessage result, or None if not completed.
        """
        entry = self._tasks.get(task_id)
        if entry is None:
            return None
        return entry.result

    async def retry_task(self, task_id: str) -> bool:
        """Retry a failed async task.

        Args:
            task_id: The task identifier to retry.

        Returns:
            True if the task was re-enqueued, False if not found or not failed.
        """
        entry = self._tasks.get(task_id)
        if entry is None or entry.status != TaskStatus.FAILED:
            return False

        entry.status = TaskStatus.PENDING
        entry.error = None
        entry.result = None
        entry.updated_at = time.time()

        await self._task_queue.put(
            (entry.priority, time.time(), entry.task_id)
        )

        # Start worker if not running
        if self._task_worker is None or self._task_worker.done():
            self._task_worker = asyncio.create_task(self._process_task_queue())

        return True

    async def _process_task_queue(self) -> None:
        """Worker coroutine that processes tasks from the priority queue."""
        while not self._task_queue.empty():
            try:
                priority, enqueue_time, task_id = await self._task_queue.get()
            except asyncio.CancelledError:
                break

            entry = self._tasks.get(task_id)
            if entry is None:
                continue

            # Skip if already completed or running
            if entry.status not in (TaskStatus.PENDING,):
                continue

            entry.status = TaskStatus.RUNNING
            entry.updated_at = time.time()

            try:
                result = await self.handle_request(entry.request)
                entry.status = TaskStatus.COMPLETED
                entry.result = result
                entry.updated_at = time.time()

                # Callback notification
                await self._notify_callback(entry)

            except Exception as exc:
                entry.status = TaskStatus.FAILED
                entry.error = str(exc)
                entry.updated_at = time.time()
                logger.error(
                    "Async task %s failed: %s", task_id, exc
                )

                # Callback notification for failure
                await self._notify_callback(entry)

    async def _notify_callback(self, entry: _AsyncTaskEntry) -> None:
        """Send callback notification for task status change.

        Supports webhook and message queue callback types.

        Args:
            entry: The task entry with updated status.
        """
        if not self._callback_url:
            return

        try:
            if self._callback_type == "webhook":
                import httpx

                payload = {
                    "task_id": entry.task_id,
                    "status": entry.status.value,
                    "error": entry.error,
                }
                async with httpx.AsyncClient() as client:
                    await client.post(
                        self._callback_url,
                        json=payload,
                        timeout=10.0,
                    )
            elif self._callback_type == "mq":
                # Message queue callback — log for now
                logger.info(
                    "MQ callback: task_id=%s status=%s",
                    entry.task_id,
                    entry.status.value,
                )
        except Exception as exc:
            logger.warning(
                "Failed to send callback for task %s: %s",
                entry.task_id,
                exc,
            )

    # ----------------------------------------------------------
    # Session Cleanup
    # ----------------------------------------------------------

    async def cleanup_idle_sessions(self) -> List[str]:
        """Clean up sessions that have exceeded the idle timeout.

        Returns:
            List of cleaned up session IDs.
        """
        return await self._session_context.cleanup_expired(
            self._config.session_idle_timeout_seconds
        )

    # ----------------------------------------------------------
    # Plugin Registration
    # ----------------------------------------------------------

    def register_plugin(self, plugin_type: str, plugin: Any) -> None:
        """Register a custom plugin.

        Args:
            plugin_type: The type of plugin (e.g. "router", "executor", "generator").
            plugin: The plugin instance.
        """
        self._plugins[plugin_type] = plugin
        logger.info("Registered plugin: type=%s", plugin_type)
