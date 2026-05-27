"""Background thread worker that executes Sentinel runs.

Each run row in the DB goes through: queued -> running -> {passed, failed, errored}.
The worker is in-process, single thread per run, capped by a small pool.
This keeps the deployment story simple (no Redis, no Celery) while still
letting the user trigger several runs in parallel from the UI.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from ..agent import run_sentinel
from ..config import SentinelConfig, DEFAULT_SENTINEL_YAML
from ..exceptions import SentinelError
from ..llm import build_client_from_credentials
from ..user_config import load_user_config, resolve_llm_credentials
from .db import get_session_factory
from .models import (
    A11yViolation,
    Project,
    Run,
    ScenarioRun,
    StepFailure,
    VisualDiff,
)
from .paths import runs_dir


logger = logging.getLogger(__name__)


# Pool capped at 2 by default. Each run drives a headless Chromium
# which is memory-hungry; running too many in parallel saturates RAM.
_MAX_PARALLEL_RUNS = int(os.environ.get("SENTINEL_MAX_PARALLEL_RUNS", "2"))
_pool: Optional[ThreadPoolExecutor] = None
_pool_lock = threading.Lock()


def get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=_MAX_PARALLEL_RUNS, thread_name_prefix="sentinel-run"
            )
    return _pool


def shutdown_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=False)
            _pool = None


def enqueue_run(run_id: str) -> None:
    """Submit a run to the pool. Returns immediately."""
    pool = get_pool()
    pool.submit(_execute_run, run_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _execute_run(run_id: str) -> None:
    """Worker entry point. Loads the run + project, executes, persists."""
    factory = get_session_factory()

    # 1. Load run + project and mark running.
    with factory() as db:
        run = db.get(Run, run_id)
        if run is None:
            logger.warning("sentinel.runner.missing_run", extra={"run_id": run_id})
            return
        project = db.get(Project, run.project_id)
        if project is None:
            run.status = "errored"
            run.error_message = "Project deleted"
            run.finished_at = _now()
            db.commit()
            return
        run.status = "running"
        run.started_at = _now()
        workspace = runs_dir() / run.id
        workspace.mkdir(parents=True, exist_ok=True)
        run.workspace_path = str(workspace)
        db.commit()

        target_url = run.target_url
        config_yaml = project.config_yaml or DEFAULT_SENTINEL_YAML
        explore_links = project.explore_links
        provider_override = project.llm_provider or None
        model_override = project.llm_model or None

    # 2. Execute outside the DB session (long-running, blocking).
    try:
        config = _parse_config(config_yaml)
        user_cfg = load_user_config()
        creds = resolve_llm_credentials(
            user_config=user_cfg,
            provider=provider_override or config.agent.provider,
            model_override=model_override or config.agent.model,
        )
        llm = build_client_from_credentials(creds)
        report = run_sentinel(
            target_url=target_url,
            config=config,
            llm=llm,
            workspace_dir=workspace,
            explore_links=explore_links,
        )
        _persist_report(run_id, report)
    except SentinelError as exc:
        _mark_errored(run_id, f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("sentinel.runner.crash", extra={"run_id": run_id})
        _mark_errored(run_id, f"unexpected error: {type(exc).__name__}: {exc}")


def _parse_config(yaml_text: str) -> SentinelConfig:
    """Project stores sentinel.yaml as text; turn it into a SentinelConfig."""
    if not yaml_text.strip():
        data = yaml.safe_load(DEFAULT_SENTINEL_YAML)
    else:
        data = yaml.safe_load(yaml_text) or {}
    return SentinelConfig.model_validate(data)


def _mark_errored(run_id: str, message: str) -> None:
    factory = get_session_factory()
    with factory() as db:
        run = db.get(Run, run_id)
        if run is None:
            return
        run.status = "errored"
        run.error_message = message[:2000]
        run.finished_at = _now()
        db.commit()


def _persist_report(run_id: str, report) -> None:
    """Copy the SentinelReport into the relational tables."""
    factory = get_session_factory()
    with factory() as db:
        run = db.get(Run, run_id)
        if run is None:
            return

        passed_count = sum(1 for s in report.scenario_runs if s.passed)
        run.scenarios_total = len(report.scenario_runs)
        run.scenarios_passed = passed_count
        run.visual_diffs_count = len(report.visual_diffs)
        run.a11y_violations_count = len(report.a11y_violations)
        run.cost_usd = float(report.total_llm_cost_usd or 0.0)
        run.input_tokens = int(report.total_input_tokens or 0)
        run.output_tokens = int(report.total_output_tokens or 0)
        run.finished_at = _now()
        run.status = "passed" if report.passed else "failed"

        for idx, sr in enumerate(report.scenario_runs):
            scenario_row = ScenarioRun(
                run_id=run.id,
                name=sr.scenario,
                description="",
                passed=bool(sr.passed),
                duration_seconds=float(sr.duration_seconds or 0.0),
                order_index=idx,
            )
            db.add(scenario_row)
            db.flush()  # get id
            for failure in getattr(sr, "failures", []):
                db.add(
                    StepFailure(
                        scenario_id=scenario_row.id,
                        step_index=int(getattr(failure, "step_index", 0)),
                        step_description=str(getattr(failure, "step_description", ""))[:2000],
                        message=str(getattr(failure, "message", ""))[:4000],
                        screenshot_path=str(getattr(failure, "screenshot_path", "") or ""),
                    )
                )

        for diff in report.visual_diffs:
            db.add(
                VisualDiff(
                    run_id=run.id,
                    name=str(diff.name),
                    baseline_path=str(diff.baseline_path or ""),
                    current_path=str(diff.current_path or ""),
                    diff_path=str(diff.diff_path or ""),
                    percent_changed=float(diff.percent_changed or 0.0),
                    threshold=float(diff.threshold or 0.0),
                )
            )

        for v in report.a11y_violations:
            db.add(
                A11yViolation(
                    run_id=run.id,
                    page_url=str(getattr(v, "page_url", "") or ""),
                    rule_id=str(v.rule_id),
                    impact=str(v.impact),
                    description=str(v.description)[:2000],
                    sample_selector=str(getattr(v, "sample_selector", "") or ""),
                    nodes_affected=int(getattr(v, "nodes_affected", 0)),
                )
            )

        db.commit()
