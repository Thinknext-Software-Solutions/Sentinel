"""Tests for sentinel.api_client.

Uses httpx's MockTransport so we never make real network calls.
"""

from __future__ import annotations

import httpx
import pytest

from sentinel.api_client import (
    _evaluate_assertion,
    _resolve_json_path,
    _resolve_url,
    execute_scenario,
)
from sentinel.api_schemas import APIAssertion, APIRequest, APIScenario


def make_scenario(method="GET", path="/health", assertions=None):
    return APIScenario(
        name="test scenario",
        description="generic test scenario",
        request=APIRequest(method=method, path=path),
        assertions=assertions
        or [APIAssertion(type="status", description="status 200", expected_status=200)],
    )


def mock_handler(handler):
    """Build a callable that, when used to replace httpx.Client,
    returns a context-manager wrapping a real httpx.Client backed by
    a MockTransport. We capture the REAL httpx.Client class before
    patching so we don't recurse into the patched version.
    """
    real_client_cls = httpx.Client  # capture before any patch is applied

    class _PatchedClient:
        def __init__(self, *args, **kwargs):
            # Strip kwargs the real Client supports; ignore others.
            safe_kwargs = {
                k: v for k, v in kwargs.items() if k in ("timeout", "follow_redirects")
            }
            self._client = real_client_cls(
                transport=httpx.MockTransport(handler), **safe_kwargs
            )

        def __enter__(self):
            return self._client

        def __exit__(self, *args):
            self._client.close()

    return _PatchedClient


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


class TestResolveURL:
    def test_relative_path(self):
        assert _resolve_url("https://x.com/api", "/health") == "https://x.com/health"

    def test_relative_path_no_leading_slash(self):
        assert _resolve_url("https://x.com/api/", "health") == "https://x.com/api/health"

    def test_absolute_path_wins(self):
        assert _resolve_url("https://x.com", "https://other.com/y") == "https://other.com/y"


class TestResolveJSONPath:
    def test_simple_dict(self):
        assert _resolve_json_path({"a": 1}, "a") == 1

    def test_nested_dict(self):
        assert _resolve_json_path({"a": {"b": {"c": 7}}}, "a.b.c") == 7

    def test_list_index(self):
        assert _resolve_json_path({"items": ["x", "y", "z"]}, "items.1") == "y"

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            _resolve_json_path({"a": 1}, "b")

    def test_missing_index_raises(self):
        with pytest.raises(KeyError):
            _resolve_json_path({"items": [1]}, "items.5")

    def test_indexing_scalar_raises(self):
        with pytest.raises(KeyError):
            _resolve_json_path({"a": 7}, "a.b")


# ---------------------------------------------------------------------------
# Assertion evaluator (synthetic responses)
# ---------------------------------------------------------------------------


def make_response(status=200, body=None, headers=None, json_body=None):
    """Build an httpx.Response for assertion testing."""
    if json_body is not None:
        return httpx.Response(
            status_code=status,
            json=json_body,
            headers=headers or {},
        )
    return httpx.Response(
        status_code=status,
        content=(body or "").encode(),
        headers=headers or {},
    )


class TestStatusAssertion:
    def test_pass(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(type="status", description="200 ok", expected_status=200),
            response=make_response(status=200),
            elapsed_ms=10.0,
        )
        assert result is None

    def test_fail(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(type="status", description="200 ok", expected_status=200),
            response=make_response(status=500),
            elapsed_ms=10.0,
        )
        assert result is not None
        assert result["actual"] == "500"


class TestResponseTimeAssertion:
    def test_pass_under_limit(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(type="response_time", description="under 1s", max_response_time_ms=1000),
            response=make_response(status=200),
            elapsed_ms=500.0,
        )
        assert result is None

    def test_fail_over_limit(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(type="response_time", description="under 100ms", max_response_time_ms=100),
            response=make_response(status=200),
            elapsed_ms=500.0,
        )
        assert result is not None
        assert "slower" in result["message"].lower()


class TestHeaderAssertion:
    def test_present_match(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="header",
                description="content-type header",
                header_name="content-type",
                expected_header_value="application/json",
            ),
            response=make_response(status=200, headers={"content-type": "application/json"}),
            elapsed_ms=10.0,
        )
        assert result is None

    def test_substring_match(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="header",
                description="content-type header",
                header_name="content-type",
                expected_header_value="json",
                header_substring=True,
            ),
            response=make_response(status=200, headers={"content-type": "application/json; charset=utf-8"}),
            elapsed_ms=10.0,
        )
        assert result is None

    def test_missing_header(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="header",
                description="content-type header",
                header_name="x-custom",
                expected_header_value="yes",
            ),
            response=make_response(status=200),
            elapsed_ms=10.0,
        )
        assert result is not None
        assert "missing" in result["message"]


class TestBodyContainsAssertion:
    def test_pass(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="body_contains",
                description="has hello",
                expected_substring="hello",
            ),
            response=make_response(status=200, body="hello world"),
            elapsed_ms=10.0,
        )
        assert result is None

    def test_fail(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="body_contains",
                description="has hello",
                expected_substring="goodbye",
            ),
            response=make_response(status=200, body="hello world"),
            elapsed_ms=10.0,
        )
        assert result is not None


class TestJSONFieldAssertion:
    def test_field_exists(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="json_field",
                description="status field",
                field_path="status",
            ),
            response=make_response(status=200, json_body={"status": "ok"}),
            elapsed_ms=10.0,
        )
        assert result is None

    def test_field_value_match(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="json_field",
                description="status=ok",
                field_path="status",
                expected_value="ok",
            ),
            response=make_response(status=200, json_body={"status": "ok"}),
            elapsed_ms=10.0,
        )
        assert result is None

    def test_field_value_mismatch(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="json_field",
                description="status=ok",
                field_path="status",
                expected_value="ok",
            ),
            response=make_response(status=200, json_body={"status": "error"}),
            elapsed_ms=10.0,
        )
        assert result is not None
        assert "mismatch" in result["message"]

    def test_missing_field(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="json_field",
                description="status=ok",
                field_path="status",
            ),
            response=make_response(status=200, json_body={"x": 1}),
            elapsed_ms=10.0,
        )
        assert result is not None
        assert "not found" in result["message"]

    def test_non_json_response(self):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="json_field",
                description="check x",
                field_path="a",
            ),
            response=make_response(status=200, body="<html>not json</html>"),
            elapsed_ms=10.0,
        )
        assert result is not None
        assert "not valid JSON" in result["message"]


class TestJSONFieldTypeAssertion:
    @pytest.mark.parametrize(
        "value,expected_type,should_pass",
        [
            ("hello", "string", True),
            (42, "integer", True),
            (3.14, "number", True),
            (True, "boolean", True),
            ([1, 2], "array", True),
            ({"a": 1}, "object", True),
            (None, "null", True),
            (42, "string", False),
            (True, "integer", False),  # bool is not int
            ("42", "integer", False),
        ],
    )
    def test_type_check(self, value, expected_type, should_pass):
        result = _evaluate_assertion(
            assertion=APIAssertion(
                type="json_field_type",
                description="type check",
                field_path="x",
                expected_type=expected_type,
            ),
            response=make_response(status=200, json_body={"x": value}),
            elapsed_ms=10.0,
        )
        if should_pass:
            assert result is None
        else:
            assert result is not None


# ---------------------------------------------------------------------------
# execute_scenario (end-to-end with mocked HTTP)
# ---------------------------------------------------------------------------


class TestExecuteScenario:
    def test_happy_path_get(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert "/health" in str(request.url)
            return httpx.Response(200, json={"status": "ok"})

        import sentinel.api_client as ac
        monkeypatch.setattr(ac.httpx if hasattr(ac, "httpx") else __import__("httpx"), "Client", mock_handler(handler))

        scenario = make_scenario(
            method="GET",
            path="/health",
            assertions=[
                APIAssertion(type="status", description="200 ok", expected_status=200),
                APIAssertion(
                    type="json_field",
                    description="status=ok",
                    field_path="status",
                    expected_value="ok",
                ),
            ],
        )
        run = execute_scenario(scenario=scenario, base_url="https://api.example.com")
        assert run.passed is True
        assert run.status_code == 200
        assert run.findings == []

    def test_network_error_captured_as_request_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "Client", mock_handler(handler))

        scenario = make_scenario()
        run = execute_scenario(scenario=scenario, base_url="https://api.example.com")
        assert run.passed is False
        assert run.status_code is None
        assert run.request_error is not None
        assert "ConnectError" in run.request_error or "connection" in run.request_error.lower()

    def test_multiple_assertions_one_fails(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"})

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "Client", mock_handler(handler))

        scenario = make_scenario(
            assertions=[
                APIAssertion(type="status", description="200", expected_status=200),  # pass
                APIAssertion(
                    type="json_field",
                    description="status=excellent",
                    field_path="status",
                    expected_value="excellent",
                ),  # fail
            ],
        )
        run = execute_scenario(scenario=scenario, base_url="https://api.example.com")
        assert run.passed is False
        assert len(run.findings) == 1
        assert run.findings[0].assertion_index == 1
