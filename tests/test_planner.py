"""Tests for sentinel.planner."""

from __future__ import annotations

from sentinel.planner import generate_plan
from sentinel.schemas import Scenario, Step, TestPlan

from conftest import FakeLLM


def make_canned_plan(target: str = "https://example.com/") -> TestPlan:
    return TestPlan(
        target_url=target,
        summary="Verify the homepage loads and shows the heading.",
        scenarios=[
            Scenario(
                name="Homepage",
                description="Open the page and confirm the heading.",
                steps=[
                    Step(action="navigate", value=target, description="open"),
                    Step(action="assert_text", value="Hello", description="check"),
                    Step(action="a11y_scan", description="scan"),
                ],
            )
        ],
    )


class TestGeneratePlan:
    def test_returns_planoutcome_with_usage(self):
        canned = make_canned_plan()
        llm = FakeLLM(responses={"TestPlan": canned})

        outcome = generate_plan(
            target_url="https://example.com/",
            page_html="<html></html>",
            page_text="hello",
            llm=llm,
        )

        assert isinstance(outcome.plan, TestPlan)
        assert outcome.plan.target_url == "https://example.com/"
        assert outcome.usage.input_tokens == 10
        assert "TestPlan" in llm.calls

    def test_overrides_target_url_if_llm_invents_one(self):
        """The LLM occasionally returns a target_url different from
        what we asked. Sentinel should force the agreed-on URL."""
        canned = make_canned_plan(target="https://wrong.com/")  # LLM hallucinated
        llm = FakeLLM(responses={"TestPlan": canned})

        outcome = generate_plan(
            target_url="https://right.com/",
            page_html="<html></html>",
            page_text="hello",
            llm=llm,
        )
        assert outcome.plan.target_url == "https://right.com/"

    def test_html_truncation_does_not_crash_on_huge_pages(self):
        canned = make_canned_plan()
        llm = FakeLLM(responses={"TestPlan": canned})

        huge_html = "<html>" + ("<div>x</div>" * 5000) + "</html>"
        outcome = generate_plan(
            target_url="https://example.com/",
            page_html=huge_html,
            page_text="x" * 50000,
            llm=llm,
        )
        # Should still produce a plan; truncation is silent
        assert outcome.plan.target_url == "https://example.com/"
