"""Unit tests for the DomainGateway module."""

import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.domain_gateway import (
    DefaultDomainGateway,
    DomainGateway,
    TaskPackage,
)
from agentic_bff_sdk.models import DomainRequest, DomainResponse


# ============================================================
# Helpers
# ============================================================


class FakeTaskPackage:
    """A simple TaskPackage that returns a predictable result."""

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        return {"action": action, "params": parameters, "status": "done"}


class FailingTaskPackage:
    """A TaskPackage that always raises an exception."""

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        raise RuntimeError("service unavailable")


def _make_request(
    domain: str = "fund",
    action: str = "query",
    parameters: Dict[str, Any] | None = None,
    request_id: str = "req-001",
) -> DomainRequest:
    return DomainRequest(
        domain=domain,
        action=action,
        parameters=parameters or {},
        request_id=request_id,
    )


# ============================================================
# ABC Tests
# ============================================================


class TestDomainGatewayABC:
    """Tests for the DomainGateway abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            DomainGateway()  # type: ignore[abstract]

    def test_default_gateway_is_subclass(self) -> None:
        assert issubclass(DefaultDomainGateway, DomainGateway)


# ============================================================
# TaskPackage Protocol Tests
# ============================================================


class TestTaskPackageProtocol:
    """Tests for the TaskPackage protocol."""

    def test_fake_task_package_satisfies_protocol(self) -> None:
        assert isinstance(FakeTaskPackage(), TaskPackage)

    def test_failing_task_package_satisfies_protocol(self) -> None:
        assert isinstance(FailingTaskPackage(), TaskPackage)

    def test_non_conforming_object_does_not_satisfy(self) -> None:
        class NotATaskPackage:
            pass

        assert not isinstance(NotATaskPackage(), TaskPackage)


# ============================================================
# register_task_package Tests
# ============================================================


class TestRegisterTaskPackage:
    """Tests for task package registration."""

    def test_register_single_package(self) -> None:
        gw = DefaultDomainGateway()
        pkg = FakeTaskPackage()
        gw.register_task_package("fund", pkg)
        assert gw._task_packages["fund"] is pkg

    def test_register_multiple_packages(self) -> None:
        gw = DefaultDomainGateway()
        pkg1 = FakeTaskPackage()
        pkg2 = FakeTaskPackage()
        gw.register_task_package("fund", pkg1)
        gw.register_task_package("asset", pkg2)
        assert len(gw._task_packages) == 2
        assert gw._task_packages["fund"] is pkg1
        assert gw._task_packages["asset"] is pkg2

    def test_register_overwrites_existing(self) -> None:
        gw = DefaultDomainGateway()
        pkg1 = FakeTaskPackage()
        pkg2 = FakeTaskPackage()
        gw.register_task_package("fund", pkg1)
        gw.register_task_package("fund", pkg2)
        assert gw._task_packages["fund"] is pkg2


# ============================================================
# invoke — Routing Tests
# ============================================================


class TestInvokeRouting:
    """Tests for domain request routing."""

    async def test_invoke_routes_to_registered_package(self) -> None:
        gw = DefaultDomainGateway()
        gw.register_task_package("fund", FakeTaskPackage())
        request = _make_request(domain="fund", action="query", parameters={"id": 1})

        response = await gw.invoke(request)

        assert response.success is True
        assert response.request_id == "req-001"
        assert response.domain == "fund"
        assert response.data == {"action": "query", "params": {"id": 1}, "status": "done"}

    async def test_invoke_unregistered_domain_returns_error(self) -> None:
        gw = DefaultDomainGateway()
        request = _make_request(domain="unknown", action="query")

        response = await gw.invoke(request)

        assert response.success is False
        assert response.domain == "unknown"
        assert response.request_id == "req-001"
        assert "not registered" in (response.error or "").lower()

    async def test_invoke_routes_to_correct_domain(self) -> None:
        """When multiple domains are registered, the correct one is invoked."""
        gw = DefaultDomainGateway()

        class DomainAPackage:
            async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
                return "domain_a_result"

        class DomainBPackage:
            async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
                return "domain_b_result"

        gw.register_task_package("domain_a", DomainAPackage())
        gw.register_task_package("domain_b", DomainBPackage())

        resp_a = await gw.invoke(_make_request(domain="domain_a"))
        resp_b = await gw.invoke(_make_request(domain="domain_b"))

        assert resp_a.data == "domain_a_result"
        assert resp_b.data == "domain_b_result"


# ============================================================
# invoke — Protocol Conversion Tests
# ============================================================


class TestInvokeProtocolConversion:
    """Tests for protocol conversion (DomainRequest → TaskPackage.execute)."""

    async def test_action_and_parameters_are_forwarded(self) -> None:
        mock_pkg = AsyncMock()
        mock_pkg.execute = AsyncMock(return_value={"converted": True})

        gw = DefaultDomainGateway()
        gw.register_task_package("svc", mock_pkg)

        request = _make_request(
            domain="svc",
            action="create_order",
            parameters={"item": "abc", "qty": 5},
        )
        response = await gw.invoke(request)

        mock_pkg.execute.assert_awaited_once_with(
            action="create_order",
            parameters={"item": "abc", "qty": 5},
        )
        assert response.success is True
        assert response.data == {"converted": True}

    async def test_empty_parameters_forwarded(self) -> None:
        mock_pkg = AsyncMock()
        mock_pkg.execute = AsyncMock(return_value="ok")

        gw = DefaultDomainGateway()
        gw.register_task_package("svc", mock_pkg)

        request = _make_request(domain="svc", action="ping", parameters={})
        await gw.invoke(request)

        mock_pkg.execute.assert_awaited_once_with(action="ping", parameters={})


# ============================================================
# invoke — Degradation / Error Handling Tests
# ============================================================


class TestInvokeDegradation:
    """Tests for service unavailability and error handling."""

    async def test_task_package_exception_returns_error_response(self) -> None:
        gw = DefaultDomainGateway()
        gw.register_task_package("broken", FailingTaskPackage())

        request = _make_request(domain="broken", action="do_something")
        response = await gw.invoke(request)

        assert response.success is False
        assert "service unavailable" in (response.error or "").lower()
        assert response.request_id == "req-001"
        assert response.domain == "broken"

    async def test_unregistered_domain_error_message_contains_domain(self) -> None:
        gw = DefaultDomainGateway()
        request = _make_request(domain="missing_domain")
        response = await gw.invoke(request)

        assert response.success is False
        assert "missing_domain" in (response.error or "")


# ============================================================
# invoke — Audit Logging Tests
# ============================================================


class TestInvokeAuditLogging:
    """Tests for audit log recording on invoke calls."""

    async def test_successful_invoke_logs_audit(self, caplog) -> None:
        gw = DefaultDomainGateway()
        gw.register_task_package("fund", FakeTaskPackage())

        with caplog.at_level("INFO", logger="agentic_bff_sdk.domain_gateway"):
            await gw.invoke(_make_request(domain="fund", action="query"))

        audit_msgs = [r.message for r in caplog.records if "AUDIT" in r.message]
        assert len(audit_msgs) >= 1
        assert "SUCCESS" in audit_msgs[0]
        assert "fund" in audit_msgs[0]
        assert "query" in audit_msgs[0]

    async def test_failed_invoke_logs_audit(self, caplog) -> None:
        gw = DefaultDomainGateway()
        gw.register_task_package("broken", FailingTaskPackage())

        with caplog.at_level("ERROR", logger="agentic_bff_sdk.domain_gateway"):
            await gw.invoke(_make_request(domain="broken", action="do"))

        audit_msgs = [r.message for r in caplog.records if "AUDIT" in r.message]
        assert len(audit_msgs) >= 1
        assert "FAILED" in audit_msgs[0]

    async def test_unregistered_domain_logs_audit(self, caplog) -> None:
        gw = DefaultDomainGateway()

        with caplog.at_level("WARNING", logger="agentic_bff_sdk.domain_gateway"):
            await gw.invoke(_make_request(domain="nope", action="x"))

        audit_msgs = [r.message for r in caplog.records if "AUDIT" in r.message]
        assert len(audit_msgs) >= 1
        assert "FAILED" in audit_msgs[0]
        assert "nope" in audit_msgs[0]


# ============================================================
# invoke_rule_engine — Basic Tests
# ============================================================


class TestInvokeRuleEngine:
    """Tests for rule engine invocation via httpx."""

    async def test_rule_engine_call_success(self) -> None:
        config = SDKConfig(
            rule_engine_base_url="https://rules.example.com",
            rule_engine_timeout_seconds=5.0,
            rule_engine_cache_ttl_seconds=300,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"score": 85}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        gw = DefaultDomainGateway(config=config, http_client=mock_client)
        result = await gw.invoke_rule_engine("risk_score", {"user_id": "u1"})

        assert result == {"score": 85}
        mock_client.post.assert_awaited_once_with(
            "https://rules.example.com/rule-sets/risk_score/execute",
            json={"user_id": "u1"},
            timeout=5.0,
        )

    async def test_rule_engine_no_base_url_raises(self) -> None:
        config = SDKConfig(rule_engine_base_url=None)
        gw = DefaultDomainGateway(config=config)

        with pytest.raises(RuntimeError, match="rule_engine_base_url"):
            await gw.invoke_rule_engine("some_rule", {})

    async def test_rule_engine_http_error_propagates(self) -> None:
        config = SDKConfig(rule_engine_base_url="https://rules.example.com")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        gw = DefaultDomainGateway(config=config, http_client=mock_client)

        with pytest.raises(httpx.HTTPStatusError):
            await gw.invoke_rule_engine("bad_rule", {})

    async def test_rule_engine_trailing_slash_in_base_url(self) -> None:
        config = SDKConfig(
            rule_engine_base_url="https://rules.example.com/api/",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        gw = DefaultDomainGateway(config=config, http_client=mock_client)
        await gw.invoke_rule_engine("r1", {"x": 1})

        # Trailing slash should be stripped to avoid double slashes
        call_url = mock_client.post.call_args[0][0]
        assert "//" not in call_url.replace("https://", "")


# ============================================================
# invoke_rule_engine — Cache Tests
# ============================================================


class TestRuleEngineCache:
    """Tests for TTL-based rule engine metadata caching."""

    async def test_cache_hit_avoids_http_call(self) -> None:
        config = SDKConfig(
            rule_engine_base_url="https://rules.example.com",
            rule_engine_cache_ttl_seconds=300,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"cached": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        gw = DefaultDomainGateway(config=config, http_client=mock_client)

        # First call — should hit HTTP
        result1 = await gw.invoke_rule_engine("rule_a", {"p": 1})
        assert result1 == {"cached": True}
        assert mock_client.post.await_count == 1

        # Second call — should use cache
        result2 = await gw.invoke_rule_engine("rule_a", {"p": 2})
        assert result2 == {"cached": True}
        assert mock_client.post.await_count == 1  # No additional HTTP call

    async def test_cache_expired_triggers_new_call(self) -> None:
        config = SDKConfig(
            rule_engine_base_url="https://rules.example.com",
            rule_engine_cache_ttl_seconds=1,  # 1 second TTL
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"v": 1}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        gw = DefaultDomainGateway(config=config, http_client=mock_client)

        # First call
        await gw.invoke_rule_engine("rule_b", {})
        assert mock_client.post.await_count == 1

        # Manually expire the cache entry
        rule_set_id = "rule_b"
        result, _ = gw._rule_cache[rule_set_id]
        gw._rule_cache[rule_set_id] = (result, time.time() - 10)

        # Second call — cache expired, should make new HTTP call
        mock_response.json.return_value = {"v": 2}
        await gw.invoke_rule_engine("rule_b", {})
        assert mock_client.post.await_count == 2

    async def test_different_rule_sets_cached_independently(self) -> None:
        config = SDKConfig(
            rule_engine_base_url="https://rules.example.com",
            rule_engine_cache_ttl_seconds=300,
        )

        call_count = 0

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"rule": url.split("/")[-2]}
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = mock_post

        gw = DefaultDomainGateway(config=config, http_client=mock_client)

        r1 = await gw.invoke_rule_engine("rule_x", {})
        r2 = await gw.invoke_rule_engine("rule_y", {})
        assert call_count == 2

        # Both should now be cached
        r1_again = await gw.invoke_rule_engine("rule_x", {})
        r2_again = await gw.invoke_rule_engine("rule_y", {})
        assert call_count == 2  # No new calls

        assert r1 == r1_again
        assert r2 == r2_again


# ============================================================
# DefaultDomainGateway — Config Tests
# ============================================================


class TestDefaultGatewayConfig:
    """Tests for DefaultDomainGateway configuration."""

    def test_default_config_used_when_none_provided(self) -> None:
        gw = DefaultDomainGateway()
        assert gw._config is not None
        assert isinstance(gw._config, SDKConfig)

    def test_custom_config_is_stored(self) -> None:
        config = SDKConfig(rule_engine_timeout_seconds=42.0)
        gw = DefaultDomainGateway(config=config)
        assert gw._config.rule_engine_timeout_seconds == 42.0

    def test_initial_state_is_empty(self) -> None:
        gw = DefaultDomainGateway()
        assert len(gw._task_packages) == 0
        assert len(gw._rule_cache) == 0
