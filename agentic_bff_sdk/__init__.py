"""Agentic BFF SDK - Multi-Agent System Orchestration Framework.

基于 Python + LangChain/LangGraph 构建的多智能体系统（MAS）编排 SDK，
为上层渠道端提供统一的智能体编排与调度能力。
"""

__version__ = "0.1.0"

# ============================================================
# Core Data Models
# ============================================================
from agentic_bff_sdk.models import (
    AggregatedResult,
    Card,
    CardOutput,
    CardType,
    ClarificationQuestion,
    DomainRequest,
    DomainResponse,
    ErrorResponse,
    ExecutionPlan,
    IntentResult,
    PlanStep,
    RequestMessage,
    ResponseMessage,
    RouterMode,
    SessionState,
    StepResult,
    StepStatus,
    SynthesisResult,
    TaskStatus,
    Topic,
)

# ============================================================
# Configuration Models
# ============================================================
from agentic_bff_sdk.config import (
    AgentExecutorConfig,
    ChannelAdapterConfig,
    InteractionScene,
    OrchestrationConfig,
    SDKConfig,
    SOPDefinition,
    TaskPackageConfig,
    ToolDefinition,
)

# ============================================================
# Gateway (MAS Entry Point)
# ============================================================
from agentic_bff_sdk.gateway import DefaultMASGateway, MASGateway

# ============================================================
# Core Components
# ============================================================
from agentic_bff_sdk.router import TopLevelRouter
from agentic_bff_sdk.planner import IMCPlanner
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher
from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.synthesizer import Synthesizer
from agentic_bff_sdk.card_generator import CardGenerator
from agentic_bff_sdk.domain_gateway import DomainGateway
from agentic_bff_sdk.agent_executor import AgentExecutor
from agentic_bff_sdk.session import SessionContext
from agentic_bff_sdk.blackboard import Blackboard

# ============================================================
# Plugin System
# ============================================================
from agentic_bff_sdk.plugins import (
    ChannelAdapter,
    DefaultChannelAdapter,
    PluginRegistry,
)

# ============================================================
# Error Handling
# ============================================================
from agentic_bff_sdk.errors import (
    SDKError,
    RequestValidationError,
    SessionError,
    RoutingError,
    PlanningError,
    DispatchError,
    DomainError,
    RuleEngineError,
    AggregationError,
    SynthesisError,
)

# ============================================================
# Audit Logging
# ============================================================
from agentic_bff_sdk.audit import AuditLogger, DefaultAuditLogger

# ============================================================
# SDK Factory
# ============================================================
from agentic_bff_sdk.sdk import create_sdk

# ============================================================
# Public API
# ============================================================
__all__ = [
    # Version
    "__version__",
    # Models
    "RequestMessage",
    "ResponseMessage",
    "ErrorResponse",
    "SessionState",
    "Topic",
    "IntentResult",
    "ClarificationQuestion",
    "RouterMode",
    "PlanStep",
    "ExecutionPlan",
    "StepStatus",
    "StepResult",
    "DomainRequest",
    "DomainResponse",
    "AggregatedResult",
    "SynthesisResult",
    "CardType",
    "Card",
    "CardOutput",
    "TaskStatus",
    # Config
    "SDKConfig",
    "OrchestrationConfig",
    "ChannelAdapterConfig",
    "TaskPackageConfig",
    "SOPDefinition",
    "InteractionScene",
    "ToolDefinition",
    "AgentExecutorConfig",
    # Gateway
    "MASGateway",
    "DefaultMASGateway",
    # Components
    "TopLevelRouter",
    "IMCPlanner",
    "ConcurrentDispatcher",
    "FanInAggregator",
    "Synthesizer",
    "CardGenerator",
    "DomainGateway",
    "AgentExecutor",
    "SessionContext",
    "Blackboard",
    # Plugins
    "ChannelAdapter",
    "DefaultChannelAdapter",
    "PluginRegistry",
    # Errors
    "SDKError",
    "RequestValidationError",
    "SessionError",
    "RoutingError",
    "PlanningError",
    "DispatchError",
    "DomainError",
    "RuleEngineError",
    "AggregationError",
    "SynthesisError",
    # Audit
    "AuditLogger",
    "DefaultAuditLogger",
    # Factory
    "create_sdk",
]
