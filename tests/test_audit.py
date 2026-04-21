"""Tests for the audit logging module (agentic_bff_sdk/audit.py)."""

import logging
from unittest.mock import AsyncMock

import pytest

from agentic_bff_sdk.audit import AuditLogger, DefaultAuditLogger


# ============================================================
# AuditLogger ABC
# ============================================================


class TestAuditLoggerABC:
    """Tests for the AuditLogger abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            AuditLogger()  # type: ignore[abstract]

    def test_concrete_subclass(self) -> None:
        """A concrete subclass implementing log_invocation should work."""

        class MyLogger(AuditLogger):
            async def log_invocation(
                self,
                domain: str,
                action: str,
                request_summary: str,
                response_summary: str,
                success: bool,
                duration_ms: float,
            ) -> None:
                pass

        logger = MyLogger()
        assert isinstance(logger, AuditLogger)


# ============================================================
# DefaultAuditLogger
# ============================================================


class TestDefaultAuditLogger:
    """Tests for the DefaultAuditLogger implementation."""

    def test_default_logger_name(self) -> None:
        audit = DefaultAuditLogger()
        assert audit.logger.name == "agentic_bff_sdk.audit"

    def test_custom_logger_name(self) -> None:
        audit = DefaultAuditLogger(logger_name="my.custom.audit")
        assert audit.logger.name == "my.custom.audit"

    def test_is_audit_logger(self) -> None:
        audit = DefaultAuditLogger()
        assert isinstance(audit, AuditLogger)

    async def test_log_success_invocation(self, caplog: pytest.LogCaptureFixture) -> None:
        audit = DefaultAuditLogger()
        with caplog.at_level(logging.INFO, logger="agentic_bff_sdk.audit"):
            await audit.log_invocation(
                domain="fund",
                action="query_balance",
                request_summary="user=123",
                response_summary="balance=1000",
                success=True,
                duration_ms=42.5,
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.INFO
        assert "AUDIT" in record.message
        assert "domain=fund" in record.message
        assert "action=query_balance" in record.message
        assert "result=SUCCESS" in record.message
        assert "duration_ms=42.5" in record.message
        assert "request=user=123" in record.message
        assert "response=balance=1000" in record.message

    async def test_log_failure_invocation(self, caplog: pytest.LogCaptureFixture) -> None:
        audit = DefaultAuditLogger()
        with caplog.at_level(logging.WARNING, logger="agentic_bff_sdk.audit"):
            await audit.log_invocation(
                domain="asset",
                action="transfer",
                request_summary="from=A to=B",
                response_summary="error: insufficient funds",
                success=False,
                duration_ms=150.0,
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "result=FAILED" in record.message
        assert "domain=asset" in record.message

    async def test_log_zero_duration(self, caplog: pytest.LogCaptureFixture) -> None:
        audit = DefaultAuditLogger()
        with caplog.at_level(logging.INFO, logger="agentic_bff_sdk.audit"):
            await audit.log_invocation(
                domain="test",
                action="ping",
                request_summary="",
                response_summary="pong",
                success=True,
                duration_ms=0.0,
            )

        assert len(caplog.records) == 1
        assert "duration_ms=0.0" in caplog.records[0].message
