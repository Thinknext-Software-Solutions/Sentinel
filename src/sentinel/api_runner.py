"""Execute an APITestPlan and build an APITestReport.

Boring orchestrator: walks each scenario, runs it via api_client,
collects results. Does NOT make LLM calls (api_planner already did).

Future v0.1.0a4 work: self-healing for API scenarios (e.g. retry a
GET with a different path if the original returned 404 and the LLM
suggests a similar endpoint).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .api_client import execute_scenario
from .api_schemas import APITestPlan, APITestReport


logger = logging.getLogger(__name__)


def run_api_plan(
    *,
    plan: APITestPlan,
    extra_headers: Optional[dict[str, str]] = None,
    timeout_seconds: float = 30.0,
) -> APITestReport:
    """Run all scenarios in an APITestPlan.

    Args:
        plan: The plan to execute.
        extra_headers: Headers added to every request (typically
            Authorization). Per-scenario request.headers wins.
        timeout_seconds: Per-request HTTP timeout.

    Returns:
        APITestReport with one APIScenarioRun per scenario.
    """
    report = APITestReport(
        target_base_url=plan.target_base_url, plan_summary=plan.summary
    )

    for scenario in plan.scenarios:
        run = execute_scenario(
            scenario=scenario,
            base_url=plan.target_base_url,
            extra_headers=extra_headers,
            timeout_seconds=timeout_seconds,
        )
        report.scenario_runs.append(run)
        logger.info(
            "sentinel.api_runner.scenario_complete",
            extra={
                "scenario": scenario.name,
                "passed": run.passed,
                "status_code": run.status_code,
                "findings": len(run.findings),
            },
        )

    report.finished_at = datetime.now(timezone.utc)
    logger.info(
        "sentinel.api_runner.complete",
        extra={
            "scenarios": len(report.scenario_runs),
            "passed_scenarios": sum(1 for s in report.scenario_runs if s.passed),
            "total_findings": report.total_findings,
        },
    )
    return report
