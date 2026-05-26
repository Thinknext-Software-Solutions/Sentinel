"""Tests for sentinel.schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.schemas import (
    A11yViolation,
    Scenario,
    ScenarioRun,
    SentinelReport,
    Step,
    TestFailure,
    TestPlan,
    VisualDiff,
)


class TestStep:
    def test_minimal(self):
        s = Step(action="navigate", value="https://x.com", description="open")
        assert s.action == "navigate"
        assert s.timeout_ms == 5000

    def test_unknown_action_rejected(self):
        with pytest.raises(ValidationError):
            Step(action="teleport", description="ddd")  # type: ignore[arg-type]

    def test_timeout_bounds(self):
        with pytest.raises(ValidationError):
            Step(action="navigate", description="ddd", timeout_ms=50)
        with pytest.raises(ValidationError):
            Step(action="navigate", description="ddd", timeout_ms=999999)


class TestScenario:
    def test_minimal(self):
        sc = Scenario(
            name="x",
            description="xxx" * 10,
            steps=[Step(action="navigate", value="https://x", description="xxx")],
        )
        assert len(sc.steps) == 1

    def test_steps_required(self):
        with pytest.raises(ValidationError):
            Scenario(name="x", description="xxx" * 10, steps=[])


class TestTestPlan:
    def test_minimal(self):
        p = TestPlan(
            target_url="https://x.com",
            summary="x" * 12,
            scenarios=[
                Scenario(
                    name="x",
                    description="xxx" * 12,
                    steps=[Step(action="navigate", value="x", description="xxx")],
                )
            ],
        )
        assert p.target_url == "https://x.com"
        assert p.generated_at.tzinfo is not None


class TestSentinelReport:
    def test_passed_empty(self):
        r = SentinelReport(target_url="https://x", plan_summary="x")
        assert r.passed is True
        assert r.total_failures == 0
        assert "0/0" in r.summary_line()

    def test_passed_one_clean_scenario(self):
        r = SentinelReport(
            target_url="https://x",
            plan_summary="x",
            scenario_runs=[ScenarioRun(scenario="s", passed=True, duration_seconds=0.1)],
        )
        assert r.passed is True
        assert "1/1" in r.summary_line()

    def test_failed_when_scenario_failed(self):
        r = SentinelReport(
            target_url="https://x",
            plan_summary="x",
            scenario_runs=[
                ScenarioRun(
                    scenario="s",
                    passed=False,
                    duration_seconds=0.1,
                    failures=[
                        TestFailure(
                            scenario="s",
                            step_index=0,
                            step_description="ddd",
                            message="boom",
                        )
                    ],
                )
            ],
        )
        assert r.passed is False
        assert r.total_failures == 1

    def test_failed_when_critical_a11y_violation(self):
        r = SentinelReport(
            target_url="https://x",
            plan_summary="x",
            a11y_violations=[
                A11yViolation(
                    rule_id="x",
                    impact="critical",
                    description="ddd",
                    help_url="h",
                    nodes_affected=1,
                )
            ],
        )
        assert r.passed is False

    def test_minor_a11y_does_not_fail(self):
        r = SentinelReport(
            target_url="https://x",
            plan_summary="x",
            a11y_violations=[
                A11yViolation(
                    rule_id="x",
                    impact="minor",
                    description="ddd",
                    help_url="h",
                    nodes_affected=1,
                )
            ],
        )
        assert r.passed is True

    def test_visual_diff_warning_does_not_fail(self):
        r = SentinelReport(
            target_url="https://x",
            plan_summary="x",
            visual_diffs=[
                VisualDiff(
                    name="x",
                    baseline_path="b",
                    current_path="c",
                    diff_path="d",
                    percent_changed=1.0,
                    threshold=0.5,
                    severity="warning",
                )
            ],
        )
        assert r.passed is True

    def test_visual_diff_error_fails(self):
        r = SentinelReport(
            target_url="https://x",
            plan_summary="x",
            visual_diffs=[
                VisualDiff(
                    name="x",
                    baseline_path="b",
                    current_path="c",
                    diff_path="d",
                    percent_changed=100.0,
                    threshold=0.5,
                    severity="error",
                )
            ],
        )
        assert r.passed is False
