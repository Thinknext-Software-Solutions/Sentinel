"""HTTP client + assertion evaluator for Sentinel's API testing module.

httpx is the HTTP library (cascade-agent already uses it as a transitive
dep via anthropic). Each scenario's request runs once; all assertions
run against that one response.

Assertions are evaluated against a parsed response. The evaluator
returns a list of APIFinding for each assertion that failed; an empty
list means the scenario passed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional
from urllib.parse import urljoin

from .exceptions import SentinelError

from .api_schemas import (
    APIAssertion,
    APIFinding,
    APIRequest,
    APIScenario,
    APIScenarioRun,
)


logger = logging.getLogger(__name__)


def execute_scenario(
    *,
    scenario: APIScenario,
    base_url: str,
    extra_headers: Optional[dict[str, str]] = None,
    timeout_seconds: float = 30.0,
) -> APIScenarioRun:
    """Send one request and evaluate all assertions against the response.

    Returns an APIScenarioRun even on network/DNS errors (with
    request_error populated and passed=False).
    """
    try:
        import httpx  # type: ignore
    except ImportError as exc:
        raise SentinelError(
            "httpx is not installed.",
            hint="pip install sentinel-agent (httpx is a dependency).",
        ) from exc

    req = scenario.request
    url = _resolve_url(base_url, req.path)
    headers = {**req.headers, **(extra_headers or {})}

    start = time.time()
    response = None
    request_error: Optional[str] = None

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.request(
                method=req.method,
                url=url,
                json=req.body if req.body is not None else None,
                headers=headers,
                params=req.query_params or None,
            )
    except httpx.HTTPError as exc:
        request_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        request_error = f"unexpected error: {type(exc).__name__}: {exc}"

    elapsed_ms = (time.time() - start) * 1000.0

    if response is None:
        return APIScenarioRun(
            scenario=scenario.name,
            request_method=req.method,
            request_url=url,
            passed=False,
            status_code=None,
            response_time_ms=round(elapsed_ms, 2),
            request_error=request_error,
            findings=[],
        )

    findings: list[APIFinding] = []
    for idx, assertion in enumerate(scenario.assertions):
        result = _evaluate_assertion(
            assertion=assertion,
            response=response,
            elapsed_ms=elapsed_ms,
        )
        if result is not None:
            findings.append(
                APIFinding(
                    scenario=scenario.name,
                    assertion_index=idx,
                    assertion_type=assertion.type,
                    assertion_description=assertion.description,
                    **result,
                )
            )

    return APIScenarioRun(
        scenario=scenario.name,
        request_method=req.method,
        request_url=url,
        passed=len(findings) == 0,
        status_code=response.status_code,
        response_time_ms=round(elapsed_ms, 2),
        findings=findings,
    )


def _resolve_url(base: str, path: str) -> str:
    """Join base + path.

      * Absolute URLs (http://, https://) win and are returned unchanged.
      * Path-absolute (starts with '/') joins to the base's origin only
        (scheme://host), discarding any path component in `base`.
      * Relative paths join to `base` including any trailing path segments.
    """
    if path.startswith(("http://", "https://")):
        return path
    if path.startswith("/"):
        from urllib.parse import urlparse

        parsed = urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    # Relative: ensure trailing slash so urljoin keeps the last segment of base.
    if not base.endswith("/"):
        base = base + "/"
    return urljoin(base, path)


def _evaluate_assertion(
    *,
    assertion: APIAssertion,
    response,
    elapsed_ms: float,
) -> Optional[dict]:
    """Evaluate one assertion against a response.

    Returns a dict with severity/message/expected/actual to construct
    an APIFinding if the assertion failed. Returns None if it passed.
    """
    t = assertion.type

    if t == "status":
        if assertion.expected_status is None:
            return {
                "severity": "error",
                "message": "status assertion missing expected_status",
                "expected": None,
                "actual": None,
            }
        if response.status_code != assertion.expected_status:
            return {
                "severity": "error",
                "message": f"status mismatch",
                "expected": str(assertion.expected_status),
                "actual": str(response.status_code),
            }
        return None

    if t == "response_time":
        if assertion.max_response_time_ms is None:
            return {
                "severity": "error",
                "message": "response_time assertion missing max_response_time_ms",
            }
        if elapsed_ms > assertion.max_response_time_ms:
            return {
                "severity": "warning",
                "message": "response slower than allowed",
                "expected": f"<= {assertion.max_response_time_ms} ms",
                "actual": f"{elapsed_ms:.0f} ms",
            }
        return None

    if t == "header":
        if not assertion.header_name:
            return {"severity": "error", "message": "header assertion missing header_name"}
        actual = response.headers.get(assertion.header_name)
        if actual is None:
            return {
                "severity": "error",
                "message": f"header {assertion.header_name!r} missing",
                "expected": str(assertion.expected_header_value),
                "actual": None,
            }
        if assertion.expected_header_value is not None:
            match = (
                assertion.expected_header_value in actual
                if assertion.header_substring
                else actual == assertion.expected_header_value
            )
            if not match:
                return {
                    "severity": "error",
                    "message": f"header {assertion.header_name!r} mismatch",
                    "expected": str(assertion.expected_header_value),
                    "actual": str(actual),
                }
        return None

    if t == "body_contains":
        if not assertion.expected_substring:
            return {"severity": "error", "message": "body_contains assertion missing expected_substring"}
        body_text = response.text
        if assertion.expected_substring not in body_text:
            return {
                "severity": "error",
                "message": f"body does not contain {assertion.expected_substring!r}",
                "expected": assertion.expected_substring,
                "actual": (body_text[:200] + "...") if len(body_text) > 200 else body_text,
            }
        return None

    if t == "json_field":
        if not assertion.field_path:
            return {"severity": "error", "message": "json_field assertion missing field_path"}
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return {
                "severity": "error",
                "message": "response is not valid JSON",
                "expected": f"JSON with field {assertion.field_path!r}",
                "actual": (response.text[:200] + "...") if len(response.text) > 200 else response.text,
            }
        try:
            actual_value = _resolve_json_path(payload, assertion.field_path)
        except KeyError:
            return {
                "severity": "error",
                "message": f"field {assertion.field_path!r} not found",
                "expected": str(assertion.expected_value) if assertion.expected_value is not None else "field to exist",
                "actual": None,
            }
        if assertion.expected_value is not None and actual_value != assertion.expected_value:
            return {
                "severity": "error",
                "message": f"field {assertion.field_path!r} value mismatch",
                "expected": json.dumps(assertion.expected_value),
                "actual": json.dumps(actual_value, default=str),
            }
        return None

    if t == "json_field_type":
        if not assertion.field_path or not assertion.expected_type:
            return {
                "severity": "error",
                "message": "json_field_type needs both field_path and expected_type",
            }
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return {
                "severity": "error",
                "message": "response is not valid JSON",
            }
        try:
            actual_value = _resolve_json_path(payload, assertion.field_path)
        except KeyError:
            return {
                "severity": "error",
                "message": f"field {assertion.field_path!r} not found",
            }
        if not _matches_json_type(actual_value, assertion.expected_type):
            return {
                "severity": "error",
                "message": f"field {assertion.field_path!r} type mismatch",
                "expected": assertion.expected_type,
                "actual": _json_type_of(actual_value),
            }
        return None

    if t == "schema_valid":
        # Deferred to v0.1.0a4. For now, no-op (returns pass).
        return None

    return {
        "severity": "error",
        "message": f"unknown assertion type: {assertion.type}",
    }


def _resolve_json_path(payload: Any, path: str) -> Any:
    """Resolve a dotted path like 'data.users.0.name' against a JSON value.

    Numeric segments index into lists; everything else is a dict key.
    Raises KeyError on a missing path.
    """
    current = payload
    for segment in path.split("."):
        if isinstance(current, list):
            try:
                idx = int(segment)
                current = current[idx]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"index {segment!r} out of range") from exc
        elif isinstance(current, dict):
            if segment not in current:
                raise KeyError(f"key {segment!r} not in dict")
            current = current[segment]
        else:
            raise KeyError(f"cannot index {type(current).__name__} with {segment!r}")
    return current


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        # In JSON, integers are also numbers; we want strict int, not bool
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _json_type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__
