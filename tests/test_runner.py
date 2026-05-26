"""Tests for sentinel.runner.

We patch sentinel.runner.open_session with a context manager that
returns a BrowserSession wrapping FakePage so the runner thinks it has
a real browser. No Playwright needed.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from sentinel.browser import BrowserSession
from sentinel.config import SentinelConfig
from sentinel.runner import run_plan
from sentinel.schemas import Scenario, Step, TestPlan

from conftest import FakePage


@contextmanager
def fake_session_cm(page: FakePage, screenshots_dir: Path):
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    session = BrowserSession(page=page, context=None, screenshots_dir=screenshots_dir)
    yield session


def make_plan(steps):
    return TestPlan(
        target_url="https://x.com/",
        summary="x" * 12,
        scenarios=[
            Scenario(name="s1", description="d" * 12, steps=steps),
        ],
    )


class TestRunPlan:
    def test_all_steps_pass(self, tmp_path, monkeypatch):
        page = FakePage(content_value="<html><body>Hello world</body></html>")

        def fake_open_session(cfg, screenshots_dir):
            return fake_session_cm(page, screenshots_dir)

        import sentinel.runner as runner_mod
        monkeypatch.setattr(runner_mod, "open_session", fake_open_session)

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="assert_text", value="Hello world", description="check"),
            ]
        )
        report = run_plan(plan=plan, config=SentinelConfig(), workspace_dir=tmp_path)

        assert len(report.scenario_runs) == 1
        assert report.scenario_runs[0].passed is True
        assert report.scenario_runs[0].failures == []
        assert report.passed is True

    def test_step_failure_stops_scenario(self, tmp_path, monkeypatch):
        page = FakePage(content_value="<html><body>Bye</body></html>")
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="assert_text", value="Hello", description="check fails"),
                Step(action="assert_text", value="never", description="should not run"),
            ]
        )
        report = run_plan(plan=plan, config=SentinelConfig(), workspace_dir=tmp_path)

        assert report.scenario_runs[0].passed is False
        assert len(report.scenario_runs[0].failures) == 1
        # The failing step index should be 1 (second step)
        assert report.scenario_runs[0].failures[0].step_index == 1

    def test_screenshot_triggers_visual_check(self, tmp_path, monkeypatch):
        page = FakePage()
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="screenshot", value="home", description="snap"),
            ]
        )
        report = run_plan(plan=plan, config=SentinelConfig(), workspace_dir=tmp_path)

        # First run: baseline captured, no diff
        assert report.scenario_runs[0].passed is True
        assert report.visual_diffs == []
        assert (tmp_path / "sentinel-baselines" / "home.png").exists()

    def test_a11y_scan_step_calls_axe(self, tmp_path, monkeypatch):
        page = FakePage()
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="a11y_scan", description="scan"),
            ]
        )
        report = run_plan(plan=plan, config=SentinelConfig(), workspace_dir=tmp_path)

        # No violations from default FakePage; scan should have been
        # attempted (evaluate called with axe.run)
        axe_calls = [c for c in page.calls if c[0] == "evaluate" and "axe.run" in c[1].get("expr", "")]
        assert len(axe_calls) >= 1

    def test_a11y_disabled_skips_scan(self, tmp_path, monkeypatch):
        page = FakePage()
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        cfg = SentinelConfig()
        cfg = cfg.model_copy(update={"a11y": cfg.a11y.model_copy(update={"enabled": False})})

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="a11y_scan", description="scan"),
            ]
        )
        report = run_plan(plan=plan, config=cfg, workspace_dir=tmp_path)
        # No axe calls were made
        axe_calls = [c for c in page.calls if c[0] == "evaluate" and "axe.run" in c[1].get("expr", "")]
        assert len(axe_calls) == 0
