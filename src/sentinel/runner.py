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
from typing import Optional

from cascade.llm import LLMClient

from .a11y import scan_page
from .browser import open_session, run_step
from .config import SentinelConfig
from .planner import regenerate_step
from .schemas import (
    A11yViolation,
    ScenarioRun,
    SentinelReport,
    Step,
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
    llm: Optional[LLMClient] = None,
    self_heal: bool = True,
) -> SentinelReport:
    """Run a TestPlan and return a SentinelReport.

    Args:
        plan: The TestPlan to execute.
        config: Sentinel config (browser settings, thresholds, etc.).
        workspace_dir: Directory for screenshots, diffs, baselines.
        llm: Optional LLM client. If provided AND self_heal=True, failed
            steps trigger one LLM-driven repair attempt before the
            scenario gives up.
        self_heal: Whether to attempt self-healing on step failures.
            No-op if `llm` is None.

    Returns:
        SentinelReport with one ScenarioRun per scenario plus
        accumulated visual diffs and a11y violations.
    """
    screenshots_dir = workspace_dir / "screenshots"
    baselines_dir = workspace_dir / config.visual.baseline_dir
    healing_enabled = self_heal and llm is not None

    report = SentinelReport(target_url=plan.target_url, plan_summary=plan.summary)
    # LLMUsage is frozen, so we accumulate self-healing token usage in
    # plain ints and add them to the report at the end.
    repair_in_tokens = 0
    repair_out_tokens = 0
    repair_cost_usd = 0.0

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

                # Self-healing: if the step failed and we have an LLM,
                # ask for a better selector and retry once.
                if not result.passed and healing_enabled and step.action in (
                    "click", "fill", "wait_for", "assert_visible"
                ):
                    try:
                        page_html = session.page.content()
                        repair = regenerate_step(
                            original_step=step,
                            failure_message=result.message,
                            scenario_name=scenario.name,
                            page_html=page_html,
                            llm=llm,  # type: ignore[arg-type]
                        )
                        repair_in_tokens += repair.usage.input_tokens
                        repair_out_tokens += repair.usage.output_tokens
                        repair_cost_usd += repair.usage.estimated_cost_usd
                        logger.info(
                            "sentinel.runner.retry_with_repair",
                            extra={
                                "scenario": scenario.name,
                                "step_index": step_index,
                                "reasoning": repair.reasoning[:120],
                            },
                        )
                        retry_result = run_step(session, repair.repaired_step)
                        if retry_result.passed:
                            result = retry_result  # treat as success
                        else:
                            # Augment the original failure message so the
                            # report tells the reader self-healing was tried.
                            result.message = (
                                f"{result.message}\n\n[self-heal retry also failed: "
                                f"{retry_result.message}]"
                            )
                    except Exception as exc:  # noqa: BLE001
                        # Don't let a flaky self-heal call mask the
                        # original failure. Log the actual exception
                        # so debugging doesn't require source-diving.
                        logger.warning(
                            "sentinel.runner.self_heal_failed: %s",
                            f"{type(exc).__name__}: {exc}",
                        )

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
    # Fold any self-healing LLM cost into the report so the user sees
    # the full bill, not just the planner stage.
    report.total_input_tokens += repair_in_tokens
    report.total_output_tokens += repair_out_tokens
    report.total_llm_cost_usd += repair_cost_usd
    logger.info(
        "sentinel.runner.complete",
        extra={
            "scenarios": len(report.scenario_runs),
            "passed": sum(1 for s in report.scenario_runs if s.passed),
            "visual_diffs": len(report.visual_diffs),
            "a11y_violations": len(report.a11y_violations),
            "repair_calls_in": repair_in_tokens,
            "repair_calls_out": repair_out_tokens,
        },
    )
    return report
