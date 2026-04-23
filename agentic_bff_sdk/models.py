"""Public data models for the Agentic BFF SDK.

The models in this module are the stable contracts shared by gateway,
pipeline, planning, dispatch, domain execution, response generation, and
channel adapters.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    SESSION_NOT_FOUND = "session_not_found"
    INTENT_NOT_RECOGNIZED = "intent_not_recognized"
    PLAN_VALIDATION_FAILED = "plan_validation_failed"
    DOMAIN_UNAVAILABLE = "domain_unavailable"
    RULE_ENGINE_ERROR = "rule_engine_error"
    INTERNAL_ERROR = "internal_error"


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class GatewayRequest(BaseModel):
    user_input: str
    session_id: str
    channel_id: str
    metadata: dict[str, object] = Field(default_factory=dict)
    trace_id: str | None = None


class GatewayResponse(BaseModel):
    session_id: str
    request_id: str
    content: "ResponseEnvelope | None" = None
    error: ErrorResponse | None = None
    task_id: str | None = None
    is_async: bool = False


class TopicStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Topic(BaseModel):
    topic_id: str
    name: str
    status: TopicStatus
    created_at: float
    metadata: dict[str, object] = Field(default_factory=dict)


class SessionMessage(BaseModel):
    role: str
    content: str
    timestamp: float


class SessionState(BaseModel):
    session_id: str
    dialog_history: list[SessionMessage] = Field(default_factory=list)
    user_profile_summary: str | None = None
    active_topics: list[Topic] = Field(default_factory=list)
    created_at: float
    last_active_at: float


class RequestContext(BaseModel):
    request_id: str
    session_id: str
    channel_id: str
    user_input: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    request: RequestContext
    session: SessionState
    blackboard_keys: list[str] = Field(default_factory=list)


class RouterMode(str, Enum):
    GENERATE = "generate"
    CONFIRM = "confirm"


class ResolvedIntent(BaseModel):
    intent_name: str
    confidence: float = 1.0
    parameters: dict[str, object] = Field(default_factory=dict)
    sop_id: str | None = None


class ClarificationPrompt(BaseModel):
    question: str
    candidates: list[ResolvedIntent] = Field(default_factory=list)


class FallbackRoute(BaseModel):
    reason: str
    message: str = "I could not determine the intent."


class RoutingResult(BaseModel):
    intent: ResolvedIntent | None = None
    clarification: ClarificationPrompt | None = None
    fallback: FallbackRoute | None = None

    @field_validator("fallback")
    @classmethod
    def validate_one_result(cls, fallback: FallbackRoute | None, info):  # type: ignore[no-untyped-def]
        return fallback


class PlanSource(str, Enum):
    INTENT = "intent"
    SOP = "sop"


class StepKind(str, Enum):
    DOMAIN_CALL = "domain_call"
    RULE_EVAL = "rule_eval"
    REACT_AGENT = "react_agent"
    HUMAN_CONFIRM = "human_confirm"
    KNOWLEDGE_QUERY = "knowledge_query"


class ParameterBinding(BaseModel):
    target_field: str
    source: Literal["literal", "session", "blackboard", "step_output", "user_input"]
    value: str | int | float | bool | None = None
    expr: str | None = None


class ExecutionStep(BaseModel):
    step_id: str
    kind: StepKind
    description: str
    domain: str | None = None
    action: str | None = None
    bindings: list[ParameterBinding] = Field(default_factory=list)
    parameters: dict[str, object] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None
    retryable: bool = True
    optional: bool = False


class ExecutionPlan(BaseModel):
    plan_id: str
    source: PlanSource
    intent_name: str
    steps: list[ExecutionStep]
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        step_ids = [step.step_id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Duplicate step_id found in execution plan.")
        known = set(step_ids)
        for step in steps:
            missing = [dep for dep in step.dependencies if dep not in known]
            if missing:
                raise ValueError(f"Missing dependencies for {step.step_id}: {missing}")
        return steps


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    step_id: str
    status: StepStatus
    output: dict[str, object] = Field(default_factory=dict)
    error_message: str | None = None
    duration_ms: float = 0.0


class DomainCommand(BaseModel):
    request_id: str
    session_id: str
    step_id: str
    domain: str
    action: str
    payload: dict[str, object] = Field(default_factory=dict)


class DomainResult(BaseModel):
    request_id: str
    step_id: str
    domain: str
    success: bool
    output: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class AggregatedResult(BaseModel):
    results: list[StepResult] = Field(default_factory=list)
    missing_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    is_partial: bool = False


class DecisionStatus(str, Enum):
    READY = "ready"
    NEEDS_CONFIRMATION = "needs_confirmation"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class ConfirmationAction(BaseModel):
    action_id: str
    label: str
    summary: str
    payload: dict[str, object] = Field(default_factory=dict)


class DecisionOutcome(BaseModel):
    status: DecisionStatus
    summary: str
    structured_payload: dict[str, object] = Field(default_factory=dict)
    confirmation_actions: list[ConfirmationAction] = Field(default_factory=list)
    compliance_flags: list[str] = Field(default_factory=list)


class SynthesisResult(BaseModel):
    text: str
    structured_payload: dict[str, object] = Field(default_factory=dict)
    confirmation_actions: list[ConfirmationAction] = Field(default_factory=list)
    compliance_flags: list[str] = Field(default_factory=list)


class CardType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    CHART = "chart"
    ACTION = "action"
    CONFIRMATION = "confirmation"


class CardAction(BaseModel):
    action_id: str
    label: str
    payload: dict[str, object] = Field(default_factory=dict)


class Card(BaseModel):
    card_type: CardType
    title: str | None = None
    body: dict[str, object] = Field(default_factory=dict)
    actions: list[CardAction] = Field(default_factory=list)
    schema_version: str = "1.0"


class ResponseEnvelope(BaseModel):
    text: str
    cards: list[Card] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class ChannelCapabilities(BaseModel):
    supports_markdown: bool = True
    supports_table_card: bool = True
    supports_chart_card: bool = False
    supports_action_card: bool = True
    max_card_count: int = 5
    schema_version: str = "1.0"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStateSnapshot(BaseModel):
    task_id: str
    status: TaskStatus
    request_id: str
    session_id: str
    progress_percent: float = 0.0
    latest_event_type: str | None = None
    error: ErrorResponse | None = None
    result: ResponseEnvelope | None = None


class BlackboardEntry(BaseModel):
    key: str
    value: object
    expires_at: float | None = None
    version: int = 1


class RuleMetadata(BaseModel):
    rule_set_id: str
    version: str
    input_schema: dict[str, object] = Field(default_factory=dict)
    output_schema: dict[str, object] = Field(default_factory=dict)


class RuleEvaluationRequest(BaseModel):
    rule_set_id: str
    version: str | None = None
    inputs: dict[str, object] = Field(default_factory=dict)


class RuleEvaluationResult(BaseModel):
    rule_set_id: str
    version: str
    outputs: dict[str, object] = Field(default_factory=dict)
    hit_rules: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, object] = Field(default_factory=dict)


class AgentExecutorConfig(BaseModel):
    max_reasoning_steps: int = 10
    tools: list[ToolSpec] = Field(default_factory=list)
