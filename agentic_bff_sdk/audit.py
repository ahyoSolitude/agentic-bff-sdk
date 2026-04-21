"""Audit logging for the Agentic BFF SDK.

Provides an AuditLogger abstract base class and a DefaultAuditLogger
implementation that records DomainGateway invocation summaries using
Python's standard logging module.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional


# ============================================================
# AuditLogger ABC
# ============================================================


class AuditLogger(ABC):
    """Abstract base class for audit loggers.

    An AuditLogger records summaries of DomainGateway invocations,
    including the domain, action, request/response summaries, success
    status, and duration.
    """

    @abstractmethod
    async def log_invocation(
        self,
        domain: str,
        action: str,
        request_summary: str,
        response_summary: str,
        success: bool,
        duration_ms: float,
    ) -> None:
        """Log a domain invocation.

        Args:
            domain: The domain identifier (e.g. ``"fund"``, ``"asset"``).
            action: The action performed within the domain.
            request_summary: A brief summary of the request parameters.
            response_summary: A brief summary of the response data.
            success: Whether the invocation succeeded.
            duration_ms: The invocation duration in milliseconds.
        """
        ...  # pragma: no cover


# ============================================================
# DefaultAuditLogger
# ============================================================


class DefaultAuditLogger(AuditLogger):
    """Default audit logger using Python's standard logging module.

    Logs each DomainGateway invocation at INFO level (success) or
    WARNING level (failure) with a structured message containing
    domain, action, outcome, duration, and summaries.

    Args:
        logger_name: The name for the Python logger instance.
            Defaults to ``"agentic_bff_sdk.audit"``.
    """

    def __init__(self, logger_name: str = "agentic_bff_sdk.audit") -> None:
        self._logger = logging.getLogger(logger_name)

    @property
    def logger(self) -> logging.Logger:
        """The underlying Python logger instance."""
        return self._logger

    async def log_invocation(
        self,
        domain: str,
        action: str,
        request_summary: str,
        response_summary: str,
        success: bool,
        duration_ms: float,
    ) -> None:
        """Log a domain invocation using Python logging.

        Successful invocations are logged at INFO level.
        Failed invocations are logged at WARNING level.

        Args:
            domain: The domain identifier.
            action: The action performed.
            request_summary: Brief summary of the request.
            response_summary: Brief summary of the response.
            success: Whether the invocation succeeded.
            duration_ms: Duration in milliseconds.
        """
        outcome = "SUCCESS" if success else "FAILED"
        message = (
            f"AUDIT | domain={domain} action={action} "
            f"result={outcome} duration_ms={duration_ms:.1f} "
            f"request={request_summary} response={response_summary}"
        )

        if success:
            self._logger.info(message)
        else:
            self._logger.warning(message)
