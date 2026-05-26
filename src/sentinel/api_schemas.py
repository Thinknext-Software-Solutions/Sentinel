"""Pydantic schemas for Sentinel's API testing module.

API testing follows a similar shape to web testing but is simpler:
each scenario is exactly one HTTP request plus N assertions about the
response. There's no multi-step navigation; each scenario stands on
its own.

The split from sentinel.schemas keeps web and API contracts visually
separate so neither pollutes the other's namespace.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class APIRequest(BaseModel):
    """A single HTTP request to make."""

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Request path. Either an absolute URL or a path relative to the "
            "configured base_url. Path params should be inlined: '/users/42'."
        ),
    )
    body: Optional[Any] = Field(
        default=None,
        description="JSON-serializable request body (for POST/PUT/PATCH). None for GET/DELETE/HEAD.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Request headers. Authorization should be configured at the run level, not here.",
    )
    query_params: dict[str, str] = Field(default_factory=dict)


AssertionType = Literal[
    "status",            # Response status code equals expected
    "json_field",        # JSON response has a field at a dotted path with a given value (or just exists)
    "json_field_type",   # JSON response field at path has a given JSON type
    "header",            # Response has a header with a given value
    "body_contains",     # Response body (string) contains a substring
    "response_time",     # Response time is below a max (ms)
    "schema_valid",      # Response body conforms to a JSON Schema (out of v0.1.0a3 scope; planned a4)
]


class APIAssertion(BaseModel):
    """One assertion about the response.

    A scenario's request runs once; all its assertions run against
    that one response.
    """

    model_config = ConfigDict(extra="forbid")

    type: AssertionType
    description: str = Field(..., min_length=3, max_length=200)

    # For status:
    expected_status: Optional[int] = Field(default=None, ge=100, le=599)

    # For json_field / json_field_type:
    field_path: Optional[str] = Field(
        default=None,
        description="Dotted JSON path, e.g. 'data.user.id' or 'items.0.name'.",
    )
    expected_value: Optional[Any] = Field(
        default=None,
        description="Expected value at field_path. If None on a json_field assertion, only existence is checked.",
    )
    expected_type: Optional[Literal["string", "number", "integer", "boolean", "array", "object", "null"]] = Field(
        default=None,
        description="For json_field_type assertions.",
    )

    # For header:
    header_name: Optional[str] = None
    expected_header_value: Optional[str] = None
    header_substring: bool = Field(
        default=False,
        description="If True, expected_header_value just needs to be a substring of the actual header.",
    )

    # For body_contains:
    expected_substring: Optional[str] = None

    # For response_time:
    max_response_time_ms: Optional[int] = Field(default=None, ge=1, le=120000)


class APIScenario(BaseModel):
    """One named scenario: a request plus assertions."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=5, max_length=600)
    request: APIRequest
    assertions: list[APIAssertion] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class APITestPlan(BaseModel):
    """A full API test plan: multiple scenarios."""

    model_config = ConfigDict(extra="forbid")

    target_base_url: str = Field(
        ...,
        description="The base URL all relative paths resolve against.",
    )
    summary: str = Field(..., min_length=10, max_length=600)
    scenarios: list[APIScenario] = Field(..., min_length=1)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


Severity = Literal["error", "warning", "info"]


class APIFinding(BaseModel):
    """One failed assertion. Multiple assertions can fail per scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario: str
    assertion_index: int = Field(..., ge=0)
    assertion_type: AssertionType
    assertion_description: str
    severity: Severity = "error"
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None


class APIScenarioRun(BaseModel):
    """Outcome of one API scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario: str
    request_method: HttpMethod
    request_url: str
    passed: bool
    status_code: Optional[int] = None
    response_time_ms: float = 0.0
    findings: list[APIFinding] = Field(default_factory=list)
    request_error: Optional[str] = Field(
        default=None,
        description="Set if the HTTP request itself failed (network, DNS, timeout) and no response was received.",
    )


class APITestReport(BaseModel):
    """End-to-end output of one `sentinel api` invocation."""

    model_config = ConfigDict(extra="forbid")

    target_base_url: str
    plan_summary: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    scenario_runs: list[APIScenarioRun] = Field(default_factory=list)
    total_llm_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.scenario_runs) and len(self.scenario_runs) > 0

    @property
    def total_findings(self) -> int:
        return sum(len(s.findings) for s in self.scenario_runs)

    def summary_line(self) -> str:
        passed = sum(1 for s in self.scenario_runs if s.passed)
        total = len(self.scenario_runs)
        return (
            f"{passed}/{total} scenarios passed, "
            f"{self.total_findings} finding(s) across {total} request(s)"
        )
