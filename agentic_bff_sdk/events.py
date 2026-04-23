"""Execution event model and lightweight publisher implementation."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    REQUEST_ACCEPTED = "request_accepted"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_OUTPUT = "step_output"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TASK_STATUS_CHANGED = "task_status_changed"
    RESPONSE_READY = "response_ready"


class ExecutionEvent(BaseModel):
    event_id: str
    event_type: EventType
    request_id: str
    session_id: str
    task_id: str | None = None
    step_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        event_type: EventType,
        *,
        request_id: str,
        session_id: str,
        task_id: str | None = None,
        step_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> "ExecutionEvent":
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            request_id=request_id,
            session_id=session_id,
            task_id=task_id,
            step_id=step_id,
            payload=payload or {},
        )


class EventSubscriber(ABC):
    @abstractmethod
    async def handle(self, event: ExecutionEvent) -> None:
        ...


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: ExecutionEvent) -> None:
        ...


class InMemoryEventPublisher(EventPublisher):
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, subscriber: EventSubscriber) -> None:
        self._subscribers.append(subscriber)

    async def publish(self, event: ExecutionEvent) -> None:
        self.events.append(event)
        for subscriber in list(self._subscribers):
            try:
                await subscriber.handle(event)
            except Exception:
                # Subscribers are observability hooks and must not break execution.
                continue
