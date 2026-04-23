"""Single-request orchestration pipeline."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod

from agentic_bff_sdk.aggregation import Aggregator
from agentic_bff_sdk.channels import ChannelRegistry
from agentic_bff_sdk.dispatch import Dispatcher
from agentic_bff_sdk.errors import PlanningError, to_error_response
from agentic_bff_sdk.events import EventPublisher, EventType, ExecutionEvent
from agentic_bff_sdk.models import (
    ExecutionContext,
    GatewayRequest,
    GatewayResponse,
    RequestContext,
    ResponseEnvelope,
    SessionMessage,
)
from agentic_bff_sdk.planning import Planner, SOPCompiler, validate_plan
from agentic_bff_sdk.response import ResponseEngine
from agentic_bff_sdk.router import Router
from agentic_bff_sdk.session import SessionManager


class RequestPipeline(ABC):
    @abstractmethod
    async def run(self, request: GatewayRequest) -> GatewayResponse:
        ...


class DefaultRequestPipeline(RequestPipeline):
    def __init__(
        self,
        *,
        session_manager: SessionManager,
        router: Router,
        planner: Planner,
        dispatcher: Dispatcher,
        aggregator: Aggregator,
        response_engine: ResponseEngine,
        channel_registry: ChannelRegistry,
        sop_compiler: SOPCompiler | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._sessions = session_manager
        self._router = router
        self._planner = planner
        self._sop_compiler = sop_compiler
        self._dispatcher = dispatcher
        self._aggregator = aggregator
        self._response = response_engine
        self._channels = channel_registry
        self._events = event_publisher

    async def run(self, request: GatewayRequest) -> GatewayResponse:
        request_id = str(uuid.uuid4())
        try:
            context = RequestContext(
                request_id=request_id,
                session_id=request.session_id,
                channel_id=request.channel_id,
                user_input=request.user_input,
                metadata=request.metadata,
            )
            session = await self._sessions.get_or_create(request.session_id)
            await self._publish(EventType.REQUEST_ACCEPTED, context)
            routing = await self._router.resolve(context, session)

            if routing.clarification is not None:
                envelope = ResponseEnvelope(
                    text=routing.clarification.question,
                    metadata={"candidates": [item.model_dump(mode="json") for item in routing.clarification.candidates]},
                )
                return GatewayResponse(session_id=request.session_id, request_id=request_id, content=envelope)
            if routing.fallback is not None or routing.intent is None:
                envelope = ResponseEnvelope(text=routing.fallback.message if routing.fallback else "无法识别意图。")
                return GatewayResponse(session_id=request.session_id, request_id=request_id, content=envelope)

            intent = routing.intent
            if intent.sop_id:
                if self._sop_compiler is None:
                    raise PlanningError("SOP intent received but no SOPCompiler is configured.")
                plan = await self._sop_compiler.compile(intent.sop_id, context)
            else:
                plan = await self._planner.plan(intent, context)
            validate_plan(plan)
            await self._publish(EventType.PLAN_CREATED, context, {"plan_id": plan.plan_id})

            execution_context = ExecutionContext(request=context, session=session)
            step_results = await self._dispatcher.dispatch(plan, execution_context)
            aggregated = await self._aggregator.aggregate(plan, step_results)
            capabilities = self._channels.get(request.channel_id).get_capabilities()
            envelope = await self._response.compose(aggregated, execution_context, capabilities)

            session.dialog_history.append(SessionMessage(role="user", content=request.user_input, timestamp=time.time()))
            session.dialog_history.append(SessionMessage(role="assistant", content=envelope.text, timestamp=time.time()))
            await self._sessions.save(session)
            await self._publish(EventType.RESPONSE_READY, context)
            return GatewayResponse(session_id=request.session_id, request_id=request_id, content=envelope)
        except Exception as exc:
            return GatewayResponse(session_id=request.session_id, request_id=request_id, error=to_error_response(exc))

    async def _publish(
        self,
        event_type: EventType,
        context: RequestContext,
        payload: dict[str, object] | None = None,
    ) -> None:
        if self._events is None:
            return
        await self._events.publish(
            ExecutionEvent.create(
                event_type,
                request_id=context.request_id,
                session_id=context.session_id,
                payload=payload,
            )
        )
