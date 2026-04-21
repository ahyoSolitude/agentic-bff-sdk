"""Tests for the unified error handling framework (agentic_bff_sdk/errors.py)."""

import pytest

from agentic_bff_sdk.errors import (
    AGG_PARTIAL_RESULTS,
    AGG_TIMEOUT,
    DISPATCH_CYCLE_DETECTED,
    DISPATCH_STEP_FAILED,
    DISPATCH_STEP_TIMEOUT,
    DOMAIN_CALL_FAILED,
    DOMAIN_NOT_REGISTERED,
    DOMAIN_SERVICE_UNAVAILABLE,
    PLAN_GENERATION_FAILED,
    PLAN_GENERATION_TIMEOUT,
    PLAN_INVALID_STRUCTURE,
    REQ_INVALID_FORMAT,
    REQ_MISSING_CHANNEL_ID,
    REQ_MISSING_SESSION_ID,
    ROUTE_AMBIGUOUS,
    ROUTE_LOW_CONFIDENCE,
    ROUTE_NO_INTENT,
    RULE_ENGINE_ERROR,
    RULE_ENGINE_NOT_CONFIGURED,
    RULE_ENGINE_TIMEOUT,
    SESSION_EXPIRED,
    SESSION_NOT_FOUND,
    SYNTH_LLM_FAILED,
    SYNTH_QUALITY_LOW,
    SYS_CONFIGURATION_ERROR,
    SYS_INTERNAL_ERROR,
    AggregationError,
    DispatchError,
    DomainError,
    PlanningError,
    RequestValidationError,
    RoutingError,
    RuleEngineError,
    SDKError,
    SessionError,
    SynthesisError,
    SystemError,
    create_partial_failure_response,
    handle_sdk_error,
    is_recoverable,
)
from agentic_bff_sdk.models import ErrorResponse


# ============================================================
# Error Code Constants
# ============================================================


class TestErrorCodeConstants:
    """Verify all error code constants are defined and have correct prefixes."""

    def test_req_codes(self) -> None:
        assert REQ_MISSING_SESSION_ID.startswith("REQ_")
        assert REQ_MISSING_CHANNEL_ID.startswith("REQ_")
        assert REQ_INVALID_FORMAT.startswith("REQ_")

    def test_session_codes(self) -> None:
        assert SESSION_NOT_FOUND.startswith("SESSION_")
        assert SESSION_EXPIRED.startswith("SESSION_")

    def test_route_codes(self) -> None:
        assert ROUTE_NO_INTENT.startswith("ROUTE_")
        assert ROUTE_LOW_CONFIDENCE.startswith("ROUTE_")
        assert ROUTE_AMBIGUOUS.startswith("ROUTE_")

    def test_plan_codes(self) -> None:
        assert PLAN_GENERATION_TIMEOUT.startswith("PLAN_")
        assert PLAN_GENERATION_FAILED.startswith("PLAN_")
        assert PLAN_INVALID_STRUCTURE.startswith("PLAN_")

    def test_dispatch_codes(self) -> None:
        assert DISPATCH_CYCLE_DETECTED.startswith("DISPATCH_")
        assert DISPATCH_STEP_TIMEOUT.startswith("DISPATCH_")
        assert DISPATCH_STEP_FAILED.startswith("DISPATCH_")

    def test_domain_codes(self) -> None:
        assert DOMAIN_NOT_REGISTERED.startswith("DOMAIN_")
        assert DOMAIN_SERVICE_UNAVAILABLE.startswith("DOMAIN_")
        assert DOMAIN_CALL_FAILED.startswith("DOMAIN_")

    def test_rule_codes(self) -> None:
        assert RULE_ENGINE_TIMEOUT.startswith("RULE_")
        assert RULE_ENGINE_ERROR.startswith("RULE_")
        assert RULE_ENGINE_NOT_CONFIGURED.startswith("RULE_")

    def test_agg_codes(self) -> None:
        assert AGG_PARTIAL_RESULTS.startswith("AGG_")
        assert AGG_TIMEOUT.startswith("AGG_")

    def test_synth_codes(self) -> None:
        assert SYNTH_QUALITY_LOW.startswith("SYNTH_")
        assert SYNTH_LLM_FAILED.startswith("SYNTH_")

    def test_sys_codes(self) -> None:
        assert SYS_INTERNAL_ERROR.startswith("SYS_")
        assert SYS_CONFIGURATION_ERROR.startswith("SYS_")


# ============================================================
# SDKError Base
# ============================================================


class TestSDKError:
    """Tests for the base SDKError class."""

    def test_basic_construction(self) -> None:
        err = SDKError(code="TEST_CODE", message="test message")
        assert err.code == "TEST_CODE"
        assert err.message == "test message"
        assert err.details == {}
        assert err.recoverable is False

    def test_with_details_and_recoverable(self) -> None:
        err = SDKError(
            code="TEST_CODE",
            message="test",
            details={"key": "value"},
            recoverable=True,
        )
        assert err.details == {"key": "value"}
        assert err.recoverable is True

    def test_str_representation(self) -> None:
        err = SDKError(code="X", message="msg")
        assert str(err) == "[X] msg"

    def test_to_error_response(self) -> None:
        err = SDKError(code="C", message="m", details={"a": 1})
        resp = err.to_error_response()
        assert isinstance(resp, ErrorResponse)
        assert resp.code == "C"
        assert resp.message == "m"
        assert resp.details == {"a": 1}

    def test_to_error_response_no_details(self) -> None:
        err = SDKError(code="C", message="m")
        resp = err.to_error_response()
        assert resp.details is None

    def test_is_exception(self) -> None:
        err = SDKError(code="C", message="m")
        assert isinstance(err, Exception)


# ============================================================
# Specific Exception Subclasses
# ============================================================


class TestExceptionSubclasses:
    """Tests for each specific exception subclass."""

    def test_request_validation_error_defaults(self) -> None:
        err = RequestValidationError()
        assert err.code == REQ_INVALID_FORMAT
        assert err.recoverable is False
        assert isinstance(err, SDKError)

    def test_request_validation_error_custom(self) -> None:
        err = RequestValidationError(
            code=REQ_MISSING_SESSION_ID,
            message="session_id missing",
        )
        assert err.code == REQ_MISSING_SESSION_ID
        assert err.message == "session_id missing"

    def test_session_error_defaults(self) -> None:
        err = SessionError()
        assert err.code == SESSION_NOT_FOUND
        assert err.recoverable is True

    def test_routing_error_defaults(self) -> None:
        err = RoutingError()
        assert err.code == ROUTE_NO_INTENT
        assert err.recoverable is False

    def test_planning_error_defaults(self) -> None:
        err = PlanningError()
        assert err.code == PLAN_GENERATION_FAILED
        assert err.recoverable is True

    def test_dispatch_error_defaults(self) -> None:
        err = DispatchError()
        assert err.code == DISPATCH_STEP_FAILED
        assert err.recoverable is False

    def test_domain_error_defaults(self) -> None:
        err = DomainError()
        assert err.code == DOMAIN_CALL_FAILED
        assert err.recoverable is True

    def test_rule_engine_error_defaults(self) -> None:
        err = RuleEngineError()
        assert err.code == RULE_ENGINE_ERROR
        assert err.recoverable is True

    def test_aggregation_error_defaults(self) -> None:
        err = AggregationError()
        assert err.code == AGG_PARTIAL_RESULTS
        assert err.recoverable is True

    def test_synthesis_error_defaults(self) -> None:
        err = SynthesisError()
        assert err.code == SYNTH_LLM_FAILED
        assert err.recoverable is True

    def test_system_error_defaults(self) -> None:
        err = SystemError()
        assert err.code == SYS_INTERNAL_ERROR
        assert err.recoverable is False

    def test_all_subclasses_inherit_sdk_error(self) -> None:
        classes = [
            RequestValidationError,
            SessionError,
            RoutingError,
            PlanningError,
            DispatchError,
            DomainError,
            RuleEngineError,
            AggregationError,
            SynthesisError,
            SystemError,
        ]
        for cls in classes:
            err = cls()
            assert isinstance(err, SDKError), f"{cls.__name__} should inherit SDKError"
            assert isinstance(err, Exception), f"{cls.__name__} should be an Exception"


# ============================================================
# Error Propagation Utilities
# ============================================================


class TestErrorPropagation:
    """Tests for error propagation utility functions."""

    def test_handle_sdk_error(self) -> None:
        err = DomainError(code=DOMAIN_NOT_REGISTERED, message="not found")
        resp = handle_sdk_error(err)
        assert isinstance(resp, ErrorResponse)
        assert resp.code == DOMAIN_NOT_REGISTERED

    def test_is_recoverable_true(self) -> None:
        err = SessionError()
        assert is_recoverable(err) is True

    def test_is_recoverable_false(self) -> None:
        err = RequestValidationError()
        assert is_recoverable(err) is False

    def test_create_partial_failure_response(self) -> None:
        resp = create_partial_failure_response(
            session_id="s1",
            partial_content={"data": "partial"},
            missing_info="step_3 timed out",
        )
        assert isinstance(resp, ErrorResponse)
        assert resp.code == AGG_PARTIAL_RESULTS
        assert resp.details is not None
        assert resp.details["session_id"] == "s1"
        assert resp.details["missing_info"] == "step_3 timed out"


# ============================================================
# Exception Raising & Catching
# ============================================================


class TestExceptionRaisingCatching:
    """Test that exceptions can be raised and caught properly."""

    def test_catch_specific_subclass(self) -> None:
        with pytest.raises(RequestValidationError) as exc_info:
            raise RequestValidationError(
                code=REQ_MISSING_SESSION_ID,
                message="missing session_id",
            )
        assert exc_info.value.code == REQ_MISSING_SESSION_ID

    def test_catch_as_sdk_error(self) -> None:
        with pytest.raises(SDKError):
            raise DomainError(message="service down")

    def test_catch_as_exception(self) -> None:
        with pytest.raises(Exception):
            raise RuleEngineError(message="timeout")
