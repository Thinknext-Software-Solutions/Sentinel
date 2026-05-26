"""Pydantic schemas for Sentinel.

The agent loop produces a TestPlan (a list of Scenarios, each with Steps),
runs the plan against a browser, and produces a SentinelReport with three
classes of findings: test failures, visual regressions, and accessibility
violations.

All schemas are pure-data Pydantic; nothing here imports Playwright. That
keeps the schemas testable without a browser and serializable to disk for
inspection later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Test plan (what the LLM produces)
# ---------------------------------------------------------------------------


StepAction = Literal[
    "navigate",   # go to a URL
    "click",      # click a selector
    "fill",       # type text into an input
    "wait_for",   # wait for a selector to appear
    "screenshot", # capture a screenshot for visual regression
    "a11y_scan",  # run axe-core against the current page
    "assert_text",   # assert a substring appears on the page
    "assert_visible", # assert a selector is visible
    "assert_url",  # assert the current URL matches a pattern
]


class Step(BaseModel):
    """One action inside a Scenario."""

    model_config = ConfigDict(extra="forbid")

    action: StepAction
    selector: Optional[str] = Field(
        default=None,
        description=(
            "CSS or text selector for click/fill/wait_for/assert_visible. "
            "Sentinel prefers role + accessible-name selectors when possible: "
            "'role=button[name=\"Save\"]' over '.btn-save'."
        ),
    )
    value: Optional[str] = Field(
        default=None,
        description=(
            "Payload: URL for navigate; text for fill; pattern for assert_text "
            "or assert_url; name for screenshot (used as filename); none for "
            "wait_for and a11y_scan."
        ),
    )
    description: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="One-line description that becomes the test report row.",
    )
    timeout_ms: int = Field(default=5000, ge=100, le=60000)


class Scenario(BaseModel):
    """A named sequence of steps that together test one user flow."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=5, max_length=600)
    steps: list[Step] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    """A full test plan: multiple scenarios.

    Produced by the planner stage (or read from disk via `sentinel test`).
    """

    model_config = ConfigDict(extra="forbid")

    target_url: str = Field(..., description="The URL the plan was generated for.")
    summary: str = Field(..., min_length=10, max_length=600)
    scenarios: list[Scenario] = Field(..., min_length=1)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Findings (what the run produces)
# ---------------------------------------------------------------------------


Severity = Literal["error", "warning", "info"]


class TestFailure(BaseModel):
    """A scenario step failed (assertion missed, selector not found, timeout)."""

    model_config = ConfigDict(extra="forbid")

    scenario: str
    step_index: int = Field(..., ge=0)
    step_description: str
    severity: Severity = "error"
    message: str
    screenshot_path: Optional[str] = None


class VisualDiff(BaseModel):
    """A screenshot differs from its baseline by more than the tolerance."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="The screenshot's name (becomes filename).")
    baseline_path: str
    current_path: str
    diff_path: str
    percent_changed: float = Field(..., ge=0.0, le=100.0)
    threshold: float = Field(..., ge=0.0, le=100.0)
    severity: Severity = "warning"


A11yImpact = Literal["minor", "moderate", "serious", "critical"]


class A11yViolation(BaseModel):
    """One axe-core violation."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., description="axe-core rule ID, e.g. 'color-contrast'.")
    impact: A11yImpact
    description: str
    help_url: str
    nodes_affected: int = Field(..., ge=1)
    sample_selector: Optional[str] = None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class ScenarioRun(BaseModel):
    """Outcome of one scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario: str
    passed: bool
    duration_seconds: float
    failures: list[TestFailure] = Field(default_factory=list)


class SentinelReport(BaseModel):
    """End-to-end output of one `sentinel run` invocation."""

    model_config = ConfigDict(extra="forbid")

    target_url: str
    plan_summary: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    scenario_runs: list[ScenarioRun] = Field(default_factory=list)
    visual_diffs: list[VisualDiff] = Field(default_factory=list)
    a11y_violations: list[A11yViolation] = Field(default_factory=list)
    total_llm_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def passed(self) -> bool:
        """True iff every scenario passed and no visual diff or a11y
        violation crossed the error severity."""
        if any(not s.passed for s in self.scenario_runs):
            return False
        if any(d.severity == "error" for d in self.visual_diffs):
            return False
        if any(v.impact in ("critical", "serious") for v in self.a11y_violations):
            return False
        return True

    @property
    def total_failures(self) -> int:
        return sum(len(s.failures) for s in self.scenario_runs)

    def summary_line(self) -> str:
        """One-line CLI summary."""
        passed = sum(1 for s in self.scenario_runs if s.passed)
        total = len(self.scenario_runs)
        return (
            f"{passed}/{total} scenarios passed, "
            f"{len(self.visual_diffs)} visual diff(s), "
            f"{len(self.a11y_violations)} a11y violation(s)"
        )
