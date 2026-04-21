"""Property-based tests for the DomainGateway module.

Uses Hypothesis to verify correctness properties of the DefaultDomainGateway
across randomized inputs: domain routing correctness and rule engine metadata
cache validity.
"""

import asyncio
import time
from typing import Any, Dict, List, Set
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from hypothesis import given, settings, strategies as st, assume

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.domain_gateway import DefaultDomainGateway, TaskPackage
from agentic_bff_sdk.models import DomainRequest, DomainResponse


# ============================================================
# Helpers
# ============================================================


class FakeTaskPackage:
    """A TaskPackage that records calls and returns a predictable result."""

    def __init__(self, domain_label: str = "default") -> None:
        self.domain_label = domain_label
        self.calls: List[Dict[str, Any]] = []

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        self.calls.append({"action": action, "parameters": parameters})
        return {"domain": self.domain_label, "action": action, "status": "ok"}


# ============================================================
# Hypothesis Strategies
# ============================================================

# Domain names: short alphanumeric identifiers
domain_name_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=1,
    max_size=16,
)

# Action names
action_name_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=1,
    max_size=16,
)

# Simple parameter values (JSON-serializable)
simple_param_strategy = st.dictionaries(
    keys=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=1,
        max_size=8,
    ),
    values=st.one_of(
        st.integers(min_value=-1000, max_value=1000),
        st.text(max_size=20),
        st.booleans(),
    ),
    max_size=5,
)

# Request ID
request_id_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=1,
    max_size=32,
)


@st.composite
def domain_routing_scenario(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a scenario with registered domains and a request.

    Returns a dict with:
    - registered_domains: set of domain names that are registered
    - request_domain: the domain in the request (may or may not be registered)
    - action: the action to invoke
    - parameters: request parameters
    - request_id: unique request identifier
    """
    # Generate a set of registered domain names (at least 1)
    num_domains = draw(st.integers(min_value=1, max_value=8))
    registered_domains = draw(
        st.lists(
            domain_name_strategy,
            min_size=num_domains,
            max_size=num_domains,
            unique=True,
        )
    )

    # Decide whether the request targets a registered or unregistered domain
    target_registered = draw(st.booleans())

    if target_registered and registered_domains:
        request_domain = draw(st.sampled_from(registered_domains))
    else:
        # Generate a domain name that is NOT in the registered set
        request_domain = draw(domain_name_strategy)
        assume(request_domain not in registered_domains)

    action = draw(action_name_strategy)
    parameters = draw(simple_param_strategy)
    request_id = draw(request_id_strategy)

    return {
        "registered_domains": registered_domains,
        "request_domain": request_domain,
        "action": action,
        "parameters": parameters,
        "request_id": request_id,
    }


# ============================================================
# Property 20: 领域路由正确性
# ============================================================


@pytest.mark.property
class TestProperty20DomainRoutingCorrectness:
    """Property 20: 领域路由正确性

    **Validates: Requirements 7.1, 7.2, 7.3, 7.5**

    For any DomainRequest, if its domain has a registered TaskPackage,
    the request should be routed to that TaskPackage and return a
    successful DomainResponse. If the domain is not registered, the
    gateway should return an error DomainResponse.
    """

    @given(scenario=domain_routing_scenario())
    @settings(max_examples=100)
    def test_registered_domain_routes_successfully(
        self, scenario: Dict[str, Any]
    ) -> None:
        """Registered domains route to the correct TaskPackage and succeed."""
        registered = scenario["registered_domains"]
        request_domain = scenario["request_domain"]

        # Only test when the request targets a registered domain
        assume(request_domain in registered)

        async def _run() -> None:
            gw = DefaultDomainGateway()

            # Register FakeTaskPackages for all domains
            packages: Dict[str, FakeTaskPackage] = {}
            for domain in registered:
                pkg = FakeTaskPackage(domain_label=domain)
                gw.register_task_package(domain, pkg)
                packages[domain] = pkg

            request = DomainRequest(
                domain=request_domain,
                action=scenario["action"],
                parameters=scenario["parameters"],
                request_id=scenario["request_id"],
            )

            response = await gw.invoke(request)

            # The response should be successful
            assert response.success is True, (
                f"Expected success for registered domain '{request_domain}', "
                f"got error: {response.error}"
            )
            assert response.request_id == scenario["request_id"]
            assert response.domain == request_domain

            # The correct TaskPackage should have been called
            target_pkg = packages[request_domain]
            assert len(target_pkg.calls) == 1, (
                f"Expected exactly 1 call to domain '{request_domain}', "
                f"got {len(target_pkg.calls)}"
            )
            assert target_pkg.calls[0]["action"] == scenario["action"]
            assert target_pkg.calls[0]["parameters"] == scenario["parameters"]

            # Other packages should NOT have been called
            for domain, pkg in packages.items():
                if domain != request_domain:
                    assert len(pkg.calls) == 0, (
                        f"Domain '{domain}' should not have been called, "
                        f"but received {len(pkg.calls)} calls"
                    )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(scenario=domain_routing_scenario())
    @settings(max_examples=100)
    def test_unregistered_domain_returns_error(
        self, scenario: Dict[str, Any]
    ) -> None:
        """Unregistered domains return an error DomainResponse."""
        registered = scenario["registered_domains"]
        request_domain = scenario["request_domain"]

        # Only test when the request targets an unregistered domain
        assume(request_domain not in registered)

        async def _run() -> None:
            gw = DefaultDomainGateway()

            # Register FakeTaskPackages for all domains
            packages: Dict[str, FakeTaskPackage] = {}
            for domain in registered:
                pkg = FakeTaskPackage(domain_label=domain)
                gw.register_task_package(domain, pkg)
                packages[domain] = pkg

            request = DomainRequest(
                domain=request_domain,
                action=scenario["action"],
                parameters=scenario["parameters"],
                request_id=scenario["request_id"],
            )

            response = await gw.invoke(request)

            # The response should indicate failure
            assert response.success is False, (
                f"Expected failure for unregistered domain '{request_domain}', "
                f"but got success"
            )
            assert response.request_id == scenario["request_id"]
            assert response.domain == request_domain
            assert response.error is not None and len(response.error) > 0, (
                "Error message should be non-empty for unregistered domain"
            )

            # No TaskPackage should have been called
            for domain, pkg in packages.items():
                assert len(pkg.calls) == 0, (
                    f"Domain '{domain}' should not have been called for "
                    f"unregistered request domain '{request_domain}'"
                )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(
        domains=st.lists(domain_name_strategy, min_size=2, max_size=6, unique=True),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_routing_isolation_across_domains(
        self, domains: List[str], data: st.DataObject
    ) -> None:
        """Each request is routed only to its target domain, not others."""
        # Pick a random domain from the registered set to target
        target_domain = data.draw(st.sampled_from(domains))
        action = data.draw(action_name_strategy)
        params = data.draw(simple_param_strategy)

        async def _run() -> None:
            gw = DefaultDomainGateway()

            packages: Dict[str, FakeTaskPackage] = {}
            for domain in domains:
                pkg = FakeTaskPackage(domain_label=domain)
                gw.register_task_package(domain, pkg)
                packages[domain] = pkg

            request = DomainRequest(
                domain=target_domain,
                action=action,
                parameters=params,
                request_id="isolation-test",
            )

            response = await gw.invoke(request)

            assert response.success is True
            # Verify the response data comes from the correct package
            assert response.data["domain"] == target_domain

            # Only the target package was invoked
            for domain, pkg in packages.items():
                if domain == target_domain:
                    assert len(pkg.calls) == 1
                else:
                    assert len(pkg.calls) == 0

        asyncio.get_event_loop().run_until_complete(_run())


# ============================================================
# Property 31: 规则元数据缓存有效性
# ============================================================


@pytest.mark.property
class TestProperty31RuleMetadataCacheValidity:
    """Property 31: 规则元数据缓存有效性

    **Validates: Requirements 13.5**

    For any rule metadata query, after the first query, subsequent
    queries within the TTL should return cached data without triggering
    an actual HTTP call to the Rule Engine.
    """

    @given(
        rule_set_id=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
            min_size=1,
            max_size=32,
        ),
        ttl=st.integers(min_value=10, max_value=3600),
        params=simple_param_strategy,
    )
    @settings(max_examples=100)
    def test_second_call_within_ttl_uses_cache(
        self, rule_set_id: str, ttl: int, params: Dict[str, Any]
    ) -> None:
        """The second call within TTL returns cached data without HTTP call."""

        async def _run() -> None:
            config = SDKConfig(
                rule_engine_base_url="https://rules.example.com",
                rule_engine_cache_ttl_seconds=ttl,
            )

            expected_result = {"rule": rule_set_id, "computed": True}

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = expected_result
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.post = AsyncMock(return_value=mock_response)

            gw = DefaultDomainGateway(config=config, http_client=mock_client)

            # First call — should trigger HTTP
            result1 = await gw.invoke_rule_engine(rule_set_id, params)
            assert result1 == expected_result
            assert mock_client.post.await_count == 1

            # Second call — should use cache, no additional HTTP call
            result2 = await gw.invoke_rule_engine(rule_set_id, params)
            assert result2 == expected_result
            assert mock_client.post.await_count == 1, (
                f"Expected 1 HTTP call (cached), but got {mock_client.post.await_count}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(
        rule_set_ids=st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
                min_size=1,
                max_size=16,
            ),
            min_size=2,
            max_size=5,
            unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_different_rule_sets_cached_independently(
        self, rule_set_ids: List[str]
    ) -> None:
        """Each rule_set_id has its own independent cache entry."""

        async def _run() -> None:
            config = SDKConfig(
                rule_engine_base_url="https://rules.example.com",
                rule_engine_cache_ttl_seconds=300,
            )

            call_count = 0

            mock_client = AsyncMock(spec=httpx.AsyncClient)

            async def mock_post(url: str, **kwargs: Any) -> MagicMock:
                nonlocal call_count
                call_count += 1
                resp = MagicMock()
                resp.status_code = 200
                # Extract rule_set_id from URL for unique results
                rsid = url.split("/")[-2]
                resp.json.return_value = {"rule_set": rsid, "call": call_count}
                resp.raise_for_status = MagicMock()
                return resp

            mock_client.post = mock_post

            gw = DefaultDomainGateway(config=config, http_client=mock_client)

            # First pass: call each rule_set_id once
            first_results: Dict[str, Any] = {}
            for rsid in rule_set_ids:
                result = await gw.invoke_rule_engine(rsid, {})
                first_results[rsid] = result

            assert call_count == len(rule_set_ids), (
                f"Expected {len(rule_set_ids)} HTTP calls, got {call_count}"
            )

            # Second pass: call each again — all should be cached
            for rsid in rule_set_ids:
                result = await gw.invoke_rule_engine(rsid, {})
                assert result == first_results[rsid], (
                    f"Cached result for '{rsid}' should match first result"
                )

            # No additional HTTP calls should have been made
            assert call_count == len(rule_set_ids), (
                f"Expected {len(rule_set_ids)} total HTTP calls (all cached), "
                f"got {call_count}"
            )

        asyncio.get_event_loop().run_until_complete(_run())

    @given(
        rule_set_id=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            min_size=1,
            max_size=16,
        ),
    )
    @settings(max_examples=100)
    def test_cache_returns_same_data_on_repeated_calls(
        self, rule_set_id: str
    ) -> None:
        """Multiple calls within TTL all return the exact same cached data."""

        async def _run() -> None:
            config = SDKConfig(
                rule_engine_base_url="https://rules.example.com",
                rule_engine_cache_ttl_seconds=300,
            )

            expected_result = {"id": rule_set_id, "value": 42}

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = expected_result
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.post = AsyncMock(return_value=mock_response)

            gw = DefaultDomainGateway(config=config, http_client=mock_client)

            # Call 3 times — only the first should trigger HTTP
            results = []
            for _ in range(3):
                result = await gw.invoke_rule_engine(rule_set_id, {})
                results.append(result)

            # All results should be identical
            for i, result in enumerate(results):
                assert result == expected_result, (
                    f"Call {i+1} returned {result}, expected {expected_result}"
                )

            # Only 1 HTTP call should have been made
            assert mock_client.post.await_count == 1

        asyncio.get_event_loop().run_until_complete(_run())
