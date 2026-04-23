"""Stable error hierarchy for the Agentic BFF SDK."""

from __future__ import annotations

from agentic_bff_sdk.models import ErrorCode, ErrorResponse


class SDKError(Exception):
    """Base SDK error that can be converted to an ErrorResponse."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_error_response(self) -> ErrorResponse:
        return ErrorResponse(code=self.code, message=self.message, details=self.details)


class ValidationError(SDKError):
    code = ErrorCode.INVALID_REQUEST


class RoutingError(SDKError):
    code = ErrorCode.INTENT_NOT_RECOGNIZED


class PlanningError(SDKError):
    code = ErrorCode.PLAN_VALIDATION_FAILED


class DispatchError(SDKError):
    code = ErrorCode.INTERNAL_ERROR


class DomainExecutionError(SDKError):
    code = ErrorCode.DOMAIN_UNAVAILABLE


class RuleEngineError(SDKError):
    code = ErrorCode.RULE_ENGINE_ERROR


def to_error_response(error: Exception) -> ErrorResponse:
    if isinstance(error, SDKError):
        return error.to_error_response()
    return ErrorResponse(code=ErrorCode.INTERNAL_ERROR, message=str(error))
