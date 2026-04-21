"""Core data models for the Agentic BFF SDK.

All models are based on Pydantic BaseModel with proper type annotations.
Enums use str-based Enum for JSON serialization compatibility.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ============================================================
# Enums
# ============================================================


class TaskStatus(str, Enum):
    """异步任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RouterMode(str, Enum):
    """意图路由模式枚举。"""

    GENERATE = "generate"
    CONFIRM = "confirm"


class StepStatus(str, Enum):
    """步骤执行状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class CardType(str, Enum):
    """富媒体卡片类型枚举。"""

    TEXT = "text"
    TABLE = "table"
    CHART = "chart"
    ACTION_BUTTON = "action_button"
    CONFIRMATION = "confirmation"


# ============================================================
# Request / Response Models
# ============================================================


class ErrorResponse(BaseModel):
    """标准错误响应模型。"""

    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class RequestMessage(BaseModel):
    """请求消息模型。"""

    user_input: str
    session_id: str
    channel_id: str
    metadata: Dict[str, Any] = {}


class ResponseMessage(BaseModel):
    """响应消息模型。"""

    session_id: str
    content: Any  # Card or text
    task_id: Optional[str] = None
    is_async: bool = False
    error: Optional[ErrorResponse] = None


# ============================================================
# Session Models
# ============================================================


class Topic(BaseModel):
    """会话话题模型。"""

    topic_id: str
    name: str
    status: str  # "active", "suspended", "closed"
    created_at: float
    metadata: Dict[str, Any] = {}


class SessionState(BaseModel):
    """会话状态模型。"""

    session_id: str
    dialog_history: List[Dict[str, Any]]
    user_profile_summary: Optional[str] = None
    active_topics: List[Topic] = []
    created_at: float
    last_active_at: float


# ============================================================
# Intent Models
# ============================================================


class IntentResult(BaseModel):
    """意图识别结果模型。"""

    intent_type: str
    confidence: float
    parameters: Dict[str, Any] = {}


class ClarificationQuestion(BaseModel):
    """澄清问题模型。"""

    question: str
    candidates: List[IntentResult] = []


# ============================================================
# Execution Plan Models
# ============================================================


class PlanStep(BaseModel):
    """执行计划步骤模型。"""

    step_id: str
    domain: str
    action: str
    parameters: Dict[str, Any] = {}
    dependencies: List[str] = []  # step_ids this step depends on
    is_react_node: bool = False  # 是否为 ReAct 循环节点


class ExecutionPlan(BaseModel):
    """执行计划模型。"""

    plan_id: str
    intent: IntentResult
    steps: List[PlanStep]
    created_at: float
    timeout_seconds: Optional[float] = None


# ============================================================
# Step Status Models
# ============================================================


class StepResult(BaseModel):
    """步骤执行结果模型。"""

    step_id: str
    status: StepStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0


# ============================================================
# Domain Call Models
# ============================================================


class DomainRequest(BaseModel):
    """领域调用请求模型。"""

    domain: str
    action: str
    parameters: Dict[str, Any] = {}
    request_id: str


class DomainResponse(BaseModel):
    """领域调用响应模型。"""

    request_id: str
    domain: str
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


# ============================================================
# Aggregation / Synthesis Models
# ============================================================


class AggregatedResult(BaseModel):
    """聚合结果模型。"""

    results: List[StepResult]
    missing_steps: List[str] = []
    is_partial: bool = False


class SynthesisResult(BaseModel):
    """综合结果模型。"""

    text_response: str
    structured_data: Optional[Dict[str, Any]] = None
    requires_confirmation: bool = False
    confirmation_actions: List[Dict[str, Any]] = []
    quality_score: float = 0.0


# ============================================================
# Card Models
# ============================================================


class Card(BaseModel):
    """富媒体卡片模型。"""

    card_type: CardType
    title: Optional[str] = None
    content: Dict[str, Any]
    actions: List[Dict[str, Any]] = []


class CardOutput(BaseModel):
    """卡片输出模型。"""

    cards: List[Card]
    raw_text: Optional[str] = None
