"""Unified error handling framework for the Agentic BFF SDK.

Defines error code constants, a custom exception hierarchy, and error
propagation utilities supporting recoverable retry/degradation,
unrecoverable ErrorResponse returns, and partial failure continuation.
"""

from typing import Any, Dict, Optional

from agentic_bff_sdk.models import ErrorResponse


# ============================================================
# Error Code Constants
# ============================================================

# Request validation errors
REQ_MISSING_SESSION_ID = "REQ_MISSING_SESSION_ID"
REQ_MISSING_CHANNEL_ID = "REQ_MISSING_CHANNEL_ID"
REQ_INVALID_FORMAT = "REQ_INVALID_FORMAT"

# Session errors
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
SESSION_EXPIRED = "SESSION_EXPIRED"

# Intent routing errors
ROUTE_NO_INTENT = "ROUTE_NO_INTENT"
ROUTE_LOW_CONFIDENCE = "ROUTE_LOW_CONFIDENCE"
ROUTE_AMBIGUOUS = "ROUTE_AMBIGUOUS"

# Plan generation errors
PLAN_GENERATION_TIMEOUT = "PLAN_GENERATION_TIMEOUT"
PLAN_GENERATION_FAILED = "PLAN_GENERATION_FAILED"
PLAN_INVALID_STRUCTURE = "PLAN_INVALID_STRUCTURE"

# Dispatch errors
DISPATCH_CYCLE_DETECTED = "DISPATCH_CYCLE_DETECTED"
DISPATCH_STEP_TIMEOUT = "DISPATCH_STEP_TIMEOUT"
DISPATCH_STEP_FAILED = "DISPATCH_STEP_FAILED"

# Domain call errors
DOMAIN_NOT_REGISTERED = "DOMAIN_NOT_REGISTERED"
DOMAIN_SERVICE_UNAVAILABLE = "DOMAIN_SERVICE_UNAVAILABLE"
DOMAIN_CALL_FAILED = "DOMAIN_CALL_FAILED"

# Rule engine errors
RULE_ENGINE_TIMEOUT = "RULE_ENGINE_TIMEOUT"
RULE_ENGINE_ERROR = "RULE_ENGINE_ERROR"
RULE_ENGINE_NOT_CONFIGURED = "RULE_ENGINE_NOT_CONFIGURED"

# Aggregation errors
AGG_PARTIAL_RESULTS = "AGG_PARTIAL_RESULTS"
AGG_TIMEOUT = "AGG_TIMEOUT"

# Synthesis errors
SYNTH_QUALITY_LOW = "SYNTH_QUALITY_LOW"
SYNTH_LLM_FAILED = "SYNTH_LLM_FAILED"

# System errors
SYS_INTERNAL_ERROR = "SYS_INTERNAL_ERROR"
SYS_CONFIGURATION_ERROR = "SYS_CONFIGURATION_ERROR"


# ============================================================
# Exception Hierarchy
# ============================================================


class SDKError(Exception):
    """Base exception for all Agentic BFF SDK errors.

    Attributes:
        code: The error code constant.
        message: Human-readable error description.
        details: Optional additional error context.
        recoverable: Whether the error is potentially recoverable via retry/degradation.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")

    def to_error_response(self) -> ErrorResponse:
        """Convert this exception to an ErrorResponse model.

        Returns:
            An ErrorResponse with the error code, message, and details.
        """
        return ErrorResponse(
            code=self.code,
            message=self.message,
            details=self.details if self.details else None,
        )


class RequestValidationError(SDKError):
    """Raised when request validation fails (missing fields, bad format)."""

    def __init__(
        self,
        code: str = REQ_INVALID_FORMAT,
        message: str = "Request validation failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=False)


class SessionError(SDKError):
    """Raised for session-related errors (not found, expired)."""

    def __init__(
        self,
        code: str = SESSION_NOT_FOUND,
        message: str = "Session error",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class RoutingError(SDKError):
    """Raised when intent routing fails."""

    def __init__(
        self,
        code: str = ROUTE_NO_INTENT,
        message: str = "Intent routing failed",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class PlanningError(SDKError):
    """Raised when execution plan generation fails."""

    def __init__(
        self,
        code: str = PLAN_GENERATION_FAILED,
        message: str = "Plan generation failed",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class DispatchError(SDKError):
    """Raised for dispatch/scheduling errors (cycles, timeouts)."""

    def __init__(
        self,
        code: str = DISPATCH_STEP_FAILED,
        message: str = "Dispatch error",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class DomainError(SDKError):
    """Raised for domain call errors (service unavailable, call failed)."""

    def __init__(
        self,
        code: str = DOMAIN_CALL_FAILED,
        message: str = "Domain call failed",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class RuleEngineError(SDKError):
    """Raised for rule engine errors (timeout, computation error)."""

    def __init__(
        self,
        code: str = RULE_ENGINE_ERROR,
        message: str = "Rule engine error",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class AggregationError(SDKError):
    """Raised for aggregation errors (partial results, timeout)."""

    def __init__(
        self,
        code: str = AGG_PARTIAL_RESULTS,
        message: str = "Aggregation error",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class SynthesisError(SDKError):
    """Raised for synthesis errors (low quality, LLM failure)."""

    def __init__(
        self,
        code: str = SYNTH_LLM_FAILED,
        message: str = "Synthesis error",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


class SystemError(SDKError):
    """Raised for internal system errors."""

    def __init__(
        self,
        code: str = SYS_INTERNAL_ERROR,
        message: str = "Internal system error",
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(code=code, message=message, details=details, recoverable=recoverable)


# ============================================================
# Error Propagation Utilities
# ============================================================


def handle_sdk_error(error: SDKError) -> ErrorResponse:
    """Convert an SDKError to an ErrorResponse for returning to the caller.

    This is the standard way to convert unrecoverable errors into
    client-facing error responses.

    Args:
        error: The SDKError to convert.

    Returns:
        An ErrorResponse model.
    """
    return error.to_error_response()


def is_recoverable(error: SDKError) -> bool:
    """Check whether an SDKError is potentially recoverable.

    Recoverable errors can be retried or degraded. Unrecoverable errors
    should be returned as ErrorResponse immediately.

    Args:
        error: The SDKError to check.

    Returns:
        True if the error is recoverable, False otherwise.
    """
    return error.recoverable


def create_partial_failure_response(
    session_id: str,
    partial_content: Any,
    missing_info: str,
) -> ErrorResponse:
    """Create an ErrorResponse indicating partial failure.

    Used when some steps failed but enough results are available to
    produce a partial response. The caller can decide to continue
    with the partial data.

    Args:
        session_id: The session identifier.
        partial_content: The partial content that was successfully produced.
        missing_info: Description of what is missing.

    Returns:
        An ErrorResponse with AGG_PARTIAL_RESULTS code.
    """
    return ErrorResponse(
        code=AGG_PARTIAL_RESULTS,
        message="Partial results available; some steps failed or timed out.",
        details={
            "session_id": session_id,
            "partial_content": partial_content,
            "missing_info": missing_info,
        },
    )
