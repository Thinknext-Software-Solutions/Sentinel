"""Playwright wrapper that hides the async/sync split.

Sentinel runs each scenario in its own browser context for isolation.
We use Playwright's sync API so the rest of Sentinel can stay sync
(matching Cascade and Relay's posture). The cost is a small thread
overhead per call, which is fine for a CLI tool that runs interactively.

The wrapper exposes three things:

  * BrowserSession: context-manager around Playwright's page + context.
  * run_step: execute one Step against an open page.
  * The dependency Playwright is imported lazily so `sentinel --help`
    works without the heavy `playwright` install having happened yet.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from cascade.exceptions import CascadeError

from .config import BrowserConfig
from .schemas import Step


logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Outcome of executing one Step."""

    passed: bool
    message: str = ""
    screenshot_path: Optional[str] = None
    a11y_violations: list = None  # populated only when action == "a11y_scan"

    def __post_init__(self):
        if self.a11y_violations is None:
            self.a11y_violations = []


class BrowserSession:
    """Owns a single Playwright page + context for the duration of a scenario."""

    def __init__(self, page, context, screenshots_dir: Path):
        self._page = page
        self._context = context
        self._screenshots_dir = screenshots_dir
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)

    @property
    def page(self):
        return self._page

    def screenshot(self, name: str) -> Path:
        """Capture a full-page screenshot, return its path."""
        path = self._screenshots_dir / f"{_safe_filename(name)}.png"
        self._page.screenshot(path=str(path), full_page=True)
        return path

    def url(self) -> str:
        return self._page.url


@contextmanager
def open_session(
    cfg: BrowserConfig, screenshots_dir: Path
) -> Iterator[BrowserSession]:
    """Open a Playwright page, hand it to the caller, close on exit."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise CascadeError(
            "Playwright is not installed.",
            hint=(
                "Run: pip install sentinel-agent  (Playwright is a dependency). "
                "Then run: playwright install chromium  (one-time browser download)."
            ),
        ) from exc

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=cfg.headless)
        except Exception as exc:
            raise CascadeError(
                "Could not launch Chromium",
                hint=(
                    "Run `playwright install chromium` once to download "
                    "the browser binary."
                ),
            ) from exc

        context = browser.new_context(
            viewport={"width": cfg.viewport_width, "height": cfg.viewport_height}
        )
        context.set_default_timeout(cfg.timeout_ms)
        page = context.new_page()
        try:
            yield BrowserSession(page=page, context=context, screenshots_dir=screenshots_dir)
        finally:
            context.close()
            browser.close()


def run_step(session: BrowserSession, step: Step) -> StepResult:
    """Execute one Step against the open page. Returns a StepResult.

    Each action is wrapped in try/except so a step failure produces a
    structured StepResult rather than raising. The scenario runner
    decides whether to stop or continue based on this.
    """
    page = session.page

    try:
        if step.action == "navigate":
            if not step.value:
                return StepResult(False, "navigate step missing URL value")
            page.goto(step.value, timeout=step.timeout_ms)
            return StepResult(True)

        if step.action == "click":
            if not step.selector:
                return StepResult(False, "click step missing selector")
            page.click(step.selector, timeout=step.timeout_ms)
            return StepResult(True)

        if step.action == "fill":
            if not step.selector or step.value is None:
                return StepResult(False, "fill step needs selector and value")
            page.fill(step.selector, step.value, timeout=step.timeout_ms)
            return StepResult(True)

        if step.action == "wait_for":
            if not step.selector:
                return StepResult(False, "wait_for step missing selector")
            page.wait_for_selector(step.selector, timeout=step.timeout_ms)
            return StepResult(True)

        if step.action == "screenshot":
            name = step.value or "screenshot"
            path = session.screenshot(name)
            return StepResult(True, message=f"screenshot saved: {path}", screenshot_path=str(path))

        if step.action == "assert_text":
            if not step.value:
                return StepResult(False, "assert_text step missing value")
            content = page.content()
            if step.value not in content:
                return StepResult(
                    False, f"text {step.value!r} not found on page"
                )
            return StepResult(True)

        if step.action == "assert_visible":
            if not step.selector:
                return StepResult(False, "assert_visible step missing selector")
            element = page.locator(step.selector)
            if not element.is_visible():
                return StepResult(
                    False, f"selector {step.selector!r} is not visible"
                )
            return StepResult(True)

        if step.action == "assert_url":
            if not step.value:
                return StepResult(False, "assert_url step missing value pattern")
            current = page.url
            if step.value not in current:
                return StepResult(
                    False, f"URL {current!r} does not match pattern {step.value!r}"
                )
            return StepResult(True)

        if step.action == "a11y_scan":
            # Handled by a11y module; runner detects this action and
            # invokes a11y.scan_page directly. This branch exists for
            # completeness but is normally bypassed.
            return StepResult(True, message="a11y_scan delegated to a11y module")

        return StepResult(False, f"unknown action: {step.action}")

    except Exception as exc:
        # Playwright timeouts and selector misses come through here.
        # Attempt a failure screenshot so the report has context.
        screenshot_path = None
        try:
            screenshot_path = str(
                session.screenshot(f"failure-{step.action}-{_safe_filename(step.description)}")
            )
        except Exception:
            pass
        return StepResult(
            passed=False,
            message=f"{type(exc).__name__}: {exc}",
            screenshot_path=screenshot_path,
        )


def _safe_filename(name: str) -> str:
    """Replace path-unfriendly chars in a screenshot name."""
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    return "".join(c if c in keep else "-" for c in name)[:80] or "screenshot"
