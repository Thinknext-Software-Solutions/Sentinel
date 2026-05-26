"""Execute a TestPlan against a browser, building a SentinelReport.

The runner is the boring orchestrator that walks each Scenario's
Steps in order, captures findings, and aggregates them. It does NOT
make LLM calls (the planner already did that) and does NOT decide
how to fix failures (that's a future product).

For each scenario we open a fresh browser context so test order does
not matter and one scenario's leftover state cannot pollute another.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .a11y import scan_page
from .browser import open_session, run_step
from .config import SentinelConfig
from .schemas import (
    A11yViolation,
    ScenarioRun,
    SentinelReport,
    TestFailure,
    TestPlan,
    VisualDiff,
)
from .visual import check_against_baseline


logger = logging.getLogger(__name__)


def run_plan(
    *,
    plan: TestPlan,
    config: SentinelConfig,
    workspace_dir: Path,
) -> SentinelReport:
    """Run a TestPlan and return a SentinelReport.

    Args:
        plan: The TestPlan to execute.
        config: Sentinel config (browser settings, thresholds, etc.).
        workspace_dir: Directory for screenshots, diffs, baselines.

    Returns:
        SentinelReport with one ScenarioRun per scenario plus
        accumulated visual diffs and a11y violations.
    """
    screenshots_dir = workspace_dir / "screenshots"
    baselines_dir = workspace_dir / config.visual.baseline_dir

    report = SentinelReport(target_url=plan.target_url, plan_summary=plan.summary)

    for scenario in plan.scenarios:
        scenario_start = time.time()
        failures: list[TestFailure] = []
        a11y_acc: list[A11yViolation] = []
        visual_acc: list[VisualDiff] = []

        with open_session(config.browser, screenshots_dir) as session:
            for step_index, step in enumerate(scenario.steps):
                # a11y_scan needs the live Page object, not the StepResult shape
                if step.action == "a11y_scan" and config.a11y.enabled:
                    violations = scan_page(session.page)
                    a11y_acc.extend(violations)
                    continue

                result = run_step(session, step)

                # Visual regression check, if this was a screenshot step
                if (
                    step.action == "screenshot"
                    and result.passed
                    and result.screenshot_path
                    and config.visual.enabled
                ):
                    diff = check_against_baseline(
                        name=step.value or "screenshot",
                        current_path=Path(result.screenshot_path),
                        baseline_dir=baselines_dir,
                        threshold_percent=config.visual.diff_threshold_percent,
                    )
                    if diff is not None:
                        visual_acc.append(diff)

                if not result.passed:
                    failures.append(
                        TestFailure(
                            scenario=scenario.name,
                            step_index=step_index,
                            step_description=step.description,
                            message=result.message,
                            screenshot_path=result.screenshot_path,
                        )
                    )
                    # Stop the scenario at the first failure so we don't
                    # cascade errors from a missing precondition.
                    break

        duration = time.time() - scenario_start
        report.scenario_runs.append(
            ScenarioRun(
                scenario=scenario.name,
                passed=len(failures) == 0,
                duration_seconds=round(duration, 3),
                failures=failures,
            )
        )
        report.visual_diffs.extend(visual_acc)
        # Deduplicate a11y violations across scenarios by rule_id +
        # selector so a single failure doesn't spam the report.
        for v in a11y_acc:
            key = (v.rule_id, v.sample_selector)
            if not any(
                (existing.rule_id, existing.sample_selector) == key
                for existing in report.a11y_violations
            ):
                report.a11y_violations.append(v)

    from datetime import datetime, timezone

    report.finished_at = datetime.now(timezone.utc)
    logger.info(
        "sentinel.runner.complete",
        extra={
            "scenarios": len(report.scenario_runs),
            "passed": sum(1 for s in report.scenario_runs if s.passed),
            "visual_diffs": len(report.visual_diffs),
            "a11y_violations": len(report.a11y_violations),
        },
    )
    return report
