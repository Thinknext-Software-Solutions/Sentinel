"""Tests for self-healing: failed steps trigger one LLM repair + retry."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sentinel.browser import BrowserSession
from sentinel.config import SentinelConfig
from sentinel.planner import StepRepair
from sentinel.runner import run_plan
from sentinel.schemas import Scenario, Step, TestPlan

from conftest import FakePage


@contextmanager
def fake_session_cm(page: FakePage, screenshots_dir: Path):
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    yield BrowserSession(page=page, context=None, screenshots_dir=screenshots_dir)


def make_plan(steps):
    return TestPlan(
        target_url="https://x.com/",
        summary="x" * 12,
        scenarios=[Scenario(name="s1", description="d" * 12, steps=steps)],
    )


class TestSelfHealing:
    def test_repair_succeeds_on_retry(self, tmp_path, monkeypatch):
        """A click on a missing selector fails, the LLM suggests a
        replacement selector that exists, the retry passes."""
        page = FakePage(selectors_present={".real-btn"})

        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        # Stub regenerate_step to return a working selector
        def fake_repair(*, original_step, failure_message, scenario_name, page_html, llm, temperature=0.0):
            from sentinel.llm import LLMUsage
            repaired = original_step.model_copy(update={"selector": ".real-btn"})
            return StepRepair(
                repaired_step=repaired,
                usage=LLMUsage(
                    input_tokens=5, output_tokens=5, model="fake", provider="fake", estimated_cost_usd=0.0
                ),
                reasoning="picked the actually-present selector",
            )

        monkeypatch.setattr(runner_mod, "regenerate_step", fake_repair)

        # Fake LLM doesn't matter (we patched regenerate_step) but
        # must be non-None to enable healing
        class _NullLLM:
            provider_name = "fake"
            model = "fake"
            def structured_call(self, **kwargs):
                raise AssertionError("should not be called directly")

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="click", selector=".missing-btn", description="click the button"),
            ]
        )
        report = run_plan(
            plan=plan,
            config=SentinelConfig(),
            workspace_dir=tmp_path,
            llm=_NullLLM(),  # type: ignore[arg-type]
            self_heal=True,
        )
        assert report.scenario_runs[0].passed is True
        # repair tokens should have been counted in the report
        assert report.total_input_tokens >= 5
        assert report.total_output_tokens >= 5

    def test_no_healing_when_llm_is_none(self, tmp_path, monkeypatch):
        """Without an LLM, failures stay as failures even with self_heal=True."""
        page = FakePage()  # nothing present
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="click", selector=".missing", description="click"),
            ]
        )
        report = run_plan(
            plan=plan,
            config=SentinelConfig(),
            workspace_dir=tmp_path,
            llm=None,
            self_heal=True,
        )
        assert report.scenario_runs[0].passed is False
        assert len(report.scenario_runs[0].failures) == 1

    def test_self_heal_off_disables_repair(self, tmp_path, monkeypatch):
        page = FakePage()
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        # If regenerate_step IS called, blow up loudly
        def boom(**kwargs):
            raise AssertionError("regenerate_step called despite self_heal=False")

        monkeypatch.setattr(runner_mod, "regenerate_step", boom)

        class _NullLLM:
            provider_name = "fake"
            model = "fake"
            def structured_call(self, **kwargs):
                raise AssertionError("should not be called")

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="click", selector=".missing", description="click"),
            ]
        )
        report = run_plan(
            plan=plan,
            config=SentinelConfig(),
            workspace_dir=tmp_path,
            llm=_NullLLM(),  # type: ignore[arg-type]
            self_heal=False,  # explicitly off
        )
        assert report.scenario_runs[0].passed is False

    def test_repair_retry_also_fails_augments_message(self, tmp_path, monkeypatch):
        """If the LLM picks another bad selector, the report shows
        both the original failure AND the repair failure."""
        page = FakePage()  # nothing present
        import sentinel.runner as runner_mod
        monkeypatch.setattr(
            runner_mod, "open_session",
            lambda cfg, screenshots_dir: fake_session_cm(page, screenshots_dir),
        )

        def fake_repair(*, original_step, failure_message, scenario_name, page_html, llm, temperature=0.0):
            from sentinel.llm import LLMUsage
            # Returns a STILL-missing selector
            repaired = original_step.model_copy(update={"selector": ".also-missing"})
            return StepRepair(
                repaired_step=repaired,
                usage=LLMUsage(input_tokens=5, output_tokens=5, model="fake", provider="fake", estimated_cost_usd=0.0),
                reasoning="tried a different selector",
            )

        monkeypatch.setattr(runner_mod, "regenerate_step", fake_repair)

        class _NullLLM:
            provider_name = "fake"
            model = "fake"
            def structured_call(self, **kwargs):
                raise AssertionError("should not be called")

        plan = make_plan(
            [
                Step(action="navigate", value="https://x.com/", description="open"),
                Step(action="click", selector=".missing", description="click"),
            ]
        )
        report = run_plan(
            plan=plan,
            config=SentinelConfig(),
            workspace_dir=tmp_path,
            llm=_NullLLM(),  # type: ignore[arg-type]
            self_heal=True,
        )
        assert report.scenario_runs[0].passed is False
        assert "self-heal retry also failed" in report.scenario_runs[0].failures[0].message
