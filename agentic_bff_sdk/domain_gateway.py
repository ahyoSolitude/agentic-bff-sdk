"""Domain Gateway for the Agentic BFF SDK.

Provides a unified gateway for routing domain requests to registered
TaskPackages, invoking the rule engine via async HTTP, and maintaining
an audit log of all invocations.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

import httpx

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import DomainRequest, DomainResponse

logger = logging.getLogger(__name__)


# ============================================================
# TaskPackage Protocol
# ============================================================


@runtime_checkable
class TaskPackage(Protocol):
    """Protocol that domain task packages must implement.

    Each TaskPackage encapsulates the business logic for a specific domain
    and exposes an async ``execute`` method.
    """

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        """Execute a domain action with the given parameters.

        Args:
            action: The action to perform within this domain.
            parameters: Action parameters.

        Returns:
            The result of the domain action.
        """
        ...  # pragma: no cover


# ============================================================
# DomainGateway ABC
# ============================================================


class DomainGateway(ABC):
    """领域网关抽象基类。

    Provides a unified API for routing requests to domain task packages,
    registering task packages, and invoking the rule engine.
    """

    @abstractmethod
    async def invoke(self, request: DomainRequest) -> DomainResponse:
        """Route and execute a domain call.

        Args:
            request: The domain request containing domain, action, and parameters.

        Returns:
            A DomainResponse indicating success or failure.
        """
        ...  # pragma: no cover

    @abstractmethod
    def register_task_package(self, domain: str, task_package: TaskPackage) -> None:
        """Register a domain task package.

        Args:
            domain: The domain identifier.
            task_package: The task package implementation.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def invoke_rule_engine(
        self, rule_set_id: str, params: Dict[str, Any]
    ) -> Any:
        """Invoke the rule engine for a given rule set.

        Args:
            rule_set_id: Identifier of the rule set to execute.
            params: Input parameters for the rule engine.

        Returns:
            The rule engine computation result.
        """
        ...  # pragma: no cover


# ============================================================
# DefaultDomainGateway
# ============================================================


class DefaultDomainGateway(DomainGateway):
    """Default implementation of the DomainGateway.

    Features:
    - Routes requests to registered TaskPackages by domain identifier
    - Protocol conversion from SDK internal format to task package format
    - Audit logging of every invocation (domain, action, success/failure)
    - Rule engine invocation via httpx async HTTP client
    - TTL-based caching for rule engine metadata
    - Graceful degradation when a domain is not registered
    """

    def __init__(
        self,
        config: Optional[SDKConfig] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._config = config or SDKConfig()
        self._task_packages: Dict[str, TaskPackage] = {}
        # Rule engine cache: rule_set_id -> (result, timestamp)
        self._rule_cache: Dict[str, Tuple[Any, float]] = {}
        # Allow injection of httpx client for testing
        self._http_client = http_client
        self._owns_http_client = http_client is None

    # ----------------------------------------------------------
    # TaskPackage registration
    # ----------------------------------------------------------

    def register_task_package(self, domain: str, task_package: TaskPackage) -> None:
        """Register a domain task package.

        Args:
            domain: The domain identifier (e.g. ``"fund"``, ``"asset"``).
            task_package: An object implementing the :class:`TaskPackage` protocol.
        """
        self._task_packages[domain] = task_package
        logger.info("Registered task package for domain '%s'", domain)

    # ----------------------------------------------------------
    # invoke
    # ----------------------------------------------------------

    async def invoke(self, request: DomainRequest) -> DomainResponse:
        """Route a domain request to the corresponding TaskPackage.

        Protocol conversion:
            The incoming :class:`DomainRequest` is unwrapped into the
            ``(action, parameters)`` pair expected by the TaskPackage's
            ``execute`` method.

        Degradation:
            If the requested domain has no registered TaskPackage, an error
            ``DomainResponse`` is returned immediately.

        Audit:
            Every call is logged with domain, action, and outcome.
        """
        domain = request.domain
        action = request.action

        # --- Check if domain is registered ---
        task_package = self._task_packages.get(domain)
        if task_package is None:
            error_msg = (
                f"Domain '{domain}' is not registered. "
                "No TaskPackage available to handle this request."
            )
            logger.warning(
                "AUDIT | domain=%s action=%s result=FAILED error=%s",
                domain,
                action,
                error_msg,
            )
            return DomainResponse(
                request_id=request.request_id,
                domain=domain,
                success=False,
                error=error_msg,
            )

        # --- Protocol conversion & execution ---
        try:
            result = await task_package.execute(
                action=action,
                parameters=request.parameters,
            )
            logger.info(
                "AUDIT | domain=%s action=%s result=SUCCESS",
                domain,
                action,
            )
            return DomainResponse(
                request_id=request.request_id,
                domain=domain,
                success=True,
                data=result,
            )
        except Exception as exc:
            error_msg = f"TaskPackage execution failed: {exc}"
            logger.error(
                "AUDIT | domain=%s action=%s result=FAILED error=%s",
                domain,
                action,
                error_msg,
            )
            return DomainResponse(
                request_id=request.request_id,
                domain=domain,
                success=False,
                error=error_msg,
            )

    # ----------------------------------------------------------
    # invoke_rule_engine
    # ----------------------------------------------------------

    async def invoke_rule_engine(
        self, rule_set_id: str, params: Dict[str, Any]
    ) -> Any:
        """Invoke the rule engine via async HTTP.

        Uses TTL-based caching: if a cached result for ``rule_set_id``
        exists and has not expired, it is returned without making an
        HTTP call.

        Args:
            rule_set_id: Identifier of the rule set to execute.
            params: Input parameters for the rule engine.

        Returns:
            The rule engine computation result (JSON-decoded).

        Raises:
            RuntimeError: If the rule engine base URL is not configured.
            httpx.HTTPStatusError: If the rule engine returns an HTTP error.
            httpx.TimeoutException: If the call exceeds the configured timeout.
        """
        # --- Check cache ---
        cached = self._rule_cache.get(rule_set_id)
        if cached is not None:
            result, cached_at = cached
            ttl = self._config.rule_engine_cache_ttl_seconds
            if time.time() - cached_at < ttl:
                logger.debug(
                    "Rule engine cache HIT for rule_set_id='%s'", rule_set_id
                )
                return result

        # --- Validate configuration ---
        base_url = self._config.rule_engine_base_url
        if not base_url:
            raise RuntimeError(
                "rule_engine_base_url is not configured in SDKConfig."
            )

        # --- Make HTTP call ---
        url = f"{base_url.rstrip('/')}/rule-sets/{rule_set_id}/execute"
        timeout = self._config.rule_engine_timeout_seconds

        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.post(
                url,
                json=params,
                timeout=timeout,
            )
            response.raise_for_status()
            result = response.json()
        finally:
            # Only close the client if we created it ourselves
            if self._http_client is None:
                await client.aclose()

        # --- Update cache ---
        self._rule_cache[rule_set_id] = (result, time.time())
        logger.debug(
            "Rule engine cache STORE for rule_set_id='%s'", rule_set_id
        )

        return result
