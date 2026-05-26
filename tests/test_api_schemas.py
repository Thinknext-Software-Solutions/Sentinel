"""Tests for sentinel.api_schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.api_schemas import (
    APIAssertion,
    APIFinding,
    APIRequest,
    APIScenario,
    APIScenarioRun,
    APITestPlan,
    APITestReport,
)


class TestAPIRequest:
    def test_minimal(self):
        r = APIRequest(method="GET", path="/health")
        assert r.method == "GET"
        assert r.body is None
        assert r.headers == {}
        assert r.query_params == {}

    def test_unknown_method_rejected(self):
        with pytest.raises(ValidationError):
            APIRequest(method="TRACE", path="/x")  # type: ignore[arg-type]

    def test_empty_path_rejected(self):
        with pytest.raises(ValidationError):
            APIRequest(method="GET", path="")


class TestAPIAssertion:
    def test_status_assertion(self):
        a = APIAssertion(type="status", description="200 OK", expected_status=200)
        assert a.expected_status == 200

    def test_status_bounds(self):
        with pytest.raises(ValidationError):
            APIAssertion(type="status", description="bad", expected_status=99)
        with pytest.raises(ValidationError):
            APIAssertion(type="status", description="bad", expected_status=600)

    def test_response_time_assertion(self):
        a = APIAssertion(
            type="response_time",
            description="under 2s",
            max_response_time_ms=2000,
        )
        assert a.max_response_time_ms == 2000

    def test_json_field_assertion(self):
        a = APIAssertion(
            type="json_field",
            description="data.status is ok",
            field_path="data.status",
            expected_value="ok",
        )
        assert a.field_path == "data.status"

    def test_short_description_rejected(self):
        with pytest.raises(ValidationError):
            APIAssertion(type="status", description="x", expected_status=200)


class TestAPIScenario:
    def test_minimal(self):
        s = APIScenario(
            name="health check",
            description="GET /health returns 200",
            request=APIRequest(method="GET", path="/health"),
            assertions=[
                APIAssertion(type="status", description="200 OK", expected_status=200)
            ],
        )
        assert s.request.method == "GET"
        assert len(s.assertions) == 1

    def test_empty_assertions_rejected(self):
        with pytest.raises(ValidationError):
            APIScenario(
                name="x",
                description="x" * 10,
                request=APIRequest(method="GET", path="/x"),
                assertions=[],
            )


class TestAPITestReport:
    def _scenario_run(self, passed: bool, findings_count: int = 0) -> APIScenarioRun:
        return APIScenarioRun(
            scenario="x",
            request_method="GET",
            request_url="https://x.com/x",
            passed=passed,
            status_code=200 if passed else 500,
            response_time_ms=10.0,
            findings=[
                APIFinding(
                    scenario="x",
                    assertion_index=i,
                    assertion_type="status",
                    assertion_description="d" * 10,
                    message="boom",
                )
                for i in range(findings_count)
            ],
        )

    def test_passed_when_all_scenarios_passed(self):
        r = APITestReport(
            target_base_url="https://x.com",
            plan_summary="x" * 12,
            scenario_runs=[self._scenario_run(True), self._scenario_run(True)],
        )
        assert r.passed is True

    def test_failed_when_any_scenario_failed(self):
        r = APITestReport(
            target_base_url="https://x.com",
            plan_summary="x" * 12,
            scenario_runs=[self._scenario_run(True), self._scenario_run(False)],
        )
        assert r.passed is False

    def test_empty_report_does_not_pass(self):
        """A report with zero scenarios shouldn't claim 'passed'; that
        would mask 'did the planner produce nothing'."""
        r = APITestReport(target_base_url="https://x.com", plan_summary="x" * 12)
        assert r.passed is False

    def test_total_findings_counts_across_scenarios(self):
        r = APITestReport(
            target_base_url="https://x.com",
            plan_summary="x" * 12,
            scenario_runs=[
                self._scenario_run(False, findings_count=2),
                self._scenario_run(False, findings_count=1),
            ],
        )
        assert r.total_findings == 3
