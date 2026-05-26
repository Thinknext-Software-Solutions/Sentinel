"""Tests for sentinel.api_planner (LLM-driven, uses FakeLLM)."""

from __future__ import annotations

from sentinel.api_planner import generate_api_plan_from_spec, generate_api_plan_from_url
from sentinel.api_schemas import APIAssertion, APIRequest, APIScenario, APITestPlan

from conftest import FakeLLM


def make_canned_plan(base="https://api.example.com") -> APITestPlan:
    return APITestPlan(
        target_base_url=base,
        summary="Smoke-test the public API surface.",
        scenarios=[
            APIScenario(
                name="health check",
                description="GET /health returns 200",
                request=APIRequest(method="GET", path="/health"),
                assertions=[
                    APIAssertion(type="status", description="200 OK", expected_status=200),
                    APIAssertion(
                        type="json_field",
                        description="status field is ok",
                        field_path="status",
                        expected_value="ok",
                    ),
                ],
            ),
        ],
    )


class TestGenerateAPIPlanFromSpec:
    def test_returns_plan_and_usage(self):
        canned = make_canned_plan()
        llm = FakeLLM(responses={"APITestPlan": canned})

        spec = {
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/health": {"get": {"summary": "Health check"}},
                "/users": {"get": {"summary": "List users"}},
            },
        }

        outcome = generate_api_plan_from_spec(
            base_url="https://api.example.com",
            spec=spec,
            llm=llm,
        )
        assert isinstance(outcome.plan, APITestPlan)
        assert outcome.plan.target_base_url == "https://api.example.com"
        assert len(outcome.plan.scenarios) == 1
        assert "APITestPlan" in llm.calls

    def test_overrides_hallucinated_base_url(self):
        """LLM occasionally invents a base URL different from what we
        asked for. Planner should pin it back to the agreed value."""
        canned = make_canned_plan(base="https://wrong.example.com")
        llm = FakeLLM(responses={"APITestPlan": canned})

        outcome = generate_api_plan_from_spec(
            base_url="https://right.example.com",
            spec={"info": {"title": "x", "version": "1"}, "paths": {}},
            llm=llm,
        )
        assert outcome.plan.target_base_url == "https://right.example.com"


class TestGenerateAPIPlanFromURL:
    def test_no_probe_response(self):
        canned = make_canned_plan()
        llm = FakeLLM(responses={"APITestPlan": canned})

        outcome = generate_api_plan_from_url(
            base_url="https://api.example.com",
            llm=llm,
        )
        assert outcome.plan.target_base_url == "https://api.example.com"

    def test_with_probe_responses(self):
        canned = make_canned_plan()
        llm = FakeLLM(responses={"APITestPlan": canned})

        outcome = generate_api_plan_from_url(
            base_url="https://api.example.com",
            probe_response={
                "https://api.example.com/": "API root: see /v1",
                "https://api.example.com/health": '{"status":"ok"}',
            },
            llm=llm,
        )
        assert outcome.plan.target_base_url == "https://api.example.com"
        # If probe responses were truncated past their cap, we'd see issues;
        # just verify the call succeeded.
