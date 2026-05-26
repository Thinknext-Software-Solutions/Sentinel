"""Tests for sentinel.browser (the step runner)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.browser import BrowserSession, run_step
from sentinel.schemas import Step

from conftest import FakePage


def make_session(page: FakePage, tmp_path: Path) -> BrowserSession:
    return BrowserSession(page=page, context=None, screenshots_dir=tmp_path / "shots")


class TestRunStep:
    def test_navigate(self, tmp_path):
        page = FakePage()
        s = make_session(page, tmp_path)
        step = Step(action="navigate", value="https://x.com", description="goo")
        result = run_step(s, step)
        assert result.passed
        assert ("goto", {"url": "https://x.com", "timeout": 5000}) in page.calls

    def test_navigate_missing_url(self, tmp_path):
        s = make_session(FakePage(), tmp_path)
        step = Step(action="navigate", description="oops")
        result = run_step(s, step)
        assert not result.passed
        assert "missing URL" in result.message

    def test_click_present_selector(self, tmp_path):
        page = FakePage(selectors_present={".btn"})
        s = make_session(page, tmp_path)
        step = Step(action="click", selector=".btn", description="ccc")
        result = run_step(s, step)
        assert result.passed

    def test_click_missing_selector_fails(self, tmp_path):
        page = FakePage()
        s = make_session(page, tmp_path)
        step = Step(action="click", selector=".missing", description="ccc")
        result = run_step(s, step)
        assert not result.passed
        # Failure screenshot should have been attempted
        assert result.screenshot_path is not None

    def test_fill_requires_selector_and_value(self, tmp_path):
        s = make_session(FakePage(), tmp_path)
        step = Step(action="fill", selector=None, value="hi", description="ddd")
        result = run_step(s, step)
        assert not result.passed

    def test_assert_text_found(self, tmp_path):
        page = FakePage(content_value="<html><body>Hello world</body></html>")
        s = make_session(page, tmp_path)
        step = Step(action="assert_text", value="Hello world", description="check")
        result = run_step(s, step)
        assert result.passed

    def test_assert_text_not_found(self, tmp_path):
        page = FakePage(content_value="<html><body>Bye</body></html>")
        s = make_session(page, tmp_path)
        step = Step(action="assert_text", value="Hello", description="check")
        result = run_step(s, step)
        assert not result.passed

    def test_assert_url_match(self, tmp_path):
        page = FakePage(url_value="https://example.com/dashboard")
        s = make_session(page, tmp_path)
        step = Step(action="assert_url", value="/dashboard", description="ddd")
        result = run_step(s, step)
        assert result.passed

    def test_assert_url_no_match(self, tmp_path):
        page = FakePage(url_value="https://example.com/")
        s = make_session(page, tmp_path)
        step = Step(action="assert_url", value="/dashboard", description="ddd")
        result = run_step(s, step)
        assert not result.passed

    def test_assert_visible_true(self, tmp_path):
        page = FakePage(selectors_visible={".header"})
        s = make_session(page, tmp_path)
        step = Step(action="assert_visible", selector=".header", description="ddd")
        result = run_step(s, step)
        assert result.passed

    def test_assert_visible_false(self, tmp_path):
        page = FakePage()  # nothing visible
        s = make_session(page, tmp_path)
        step = Step(action="assert_visible", selector=".header", description="ddd")
        result = run_step(s, step)
        assert not result.passed

    def test_screenshot(self, tmp_path):
        page = FakePage()
        s = make_session(page, tmp_path)
        step = Step(action="screenshot", value="homepage", description="snap")
        result = run_step(s, step)
        assert result.passed
        assert result.screenshot_path is not None
        assert Path(result.screenshot_path).exists()

    def test_wait_for_present(self, tmp_path):
        page = FakePage(selectors_present={".modal"})
        s = make_session(page, tmp_path)
        step = Step(action="wait_for", selector=".modal", description="ddd")
        result = run_step(s, step)
        assert result.passed
