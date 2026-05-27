"""Shared fixtures for Sentinel tests.

Hermetic: no real Playwright, no real LLM. FakeLLM gives canned plans;
FakePage simulates a Playwright Page well enough for runner unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from sentinel.llm import LLMClient, LLMResponse, LLMUsage

from sentinel.schemas import Scenario, Step, TestPlan


# ---------------------------------------------------------------------------
# FakeLLM
# ---------------------------------------------------------------------------


@dataclass
class FakeLLM(LLMClient):
    """Returns canned responses keyed by Pydantic schema name."""

    responses: dict[str, Any] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    def structured_call(
        self, *, system: str, user: str, schema, max_tokens=8192, temperature=0.2
    ):
        name = schema.__name__
        self.calls.append(name)
        if name not in self.responses:
            raise AssertionError(
                f"FakeLLM called with unexpected schema {name!r}; "
                f"available: {list(self.responses.keys())}"
            )
        return LLMResponse(
            parsed=self.responses[name],
            raw_text=repr(self.responses[name]),
            usage=LLMUsage(
                input_tokens=10,
                output_tokens=10,
                model="fake-model",
                provider="fake",
                estimated_cost_usd=0.0,
            ),
        )


# ---------------------------------------------------------------------------
# FakePage / FakeSession
# ---------------------------------------------------------------------------


@dataclass
class FakePage:
    """Minimal stand-in for a Playwright Page.

    Tracks what was called so tests can assert on it. Most methods are
    no-ops; the few that need to return something (content, url) have
    configurable backing fields.
    """

    url_value: str = "https://example.com/"
    content_value: str = "<html><body><h1>Test page</h1></body></html>"
    text_value: str = "Test page"
    calls: list[tuple[str, dict]] = field(default_factory=list)
    selectors_visible: set = field(default_factory=set)
    selectors_present: set = field(default_factory=set)
    # If True, click/fill/wait_for raise to simulate missing selectors
    fail_on_missing_selector: bool = True
    # Counter so tests can assert on action ordering
    action_count: int = 0

    @property
    def url(self) -> str:
        return self.url_value

    def goto(self, url: str, timeout: int = 30000) -> None:
        self.calls.append(("goto", {"url": url, "timeout": timeout}))
        self.url_value = url
        self.action_count += 1

    def click(self, selector: str, timeout: int = 5000) -> None:
        self.calls.append(("click", {"selector": selector}))
        if self.fail_on_missing_selector and selector not in self.selectors_present:
            raise RuntimeError(f"selector not found: {selector}")
        self.action_count += 1

    def fill(self, selector: str, value: str, timeout: int = 5000) -> None:
        self.calls.append(("fill", {"selector": selector, "value": value}))
        if self.fail_on_missing_selector and selector not in self.selectors_present:
            raise RuntimeError(f"selector not found: {selector}")
        self.action_count += 1

    def wait_for_selector(self, selector: str, timeout: int = 5000) -> None:
        self.calls.append(("wait_for_selector", {"selector": selector}))
        if self.fail_on_missing_selector and selector not in self.selectors_present:
            raise RuntimeError(f"timeout waiting for selector: {selector}")
        self.action_count += 1

    def wait_for_load_state(self, state: str, timeout: int = 10000) -> None:
        self.calls.append(("wait_for_load_state", {"state": state}))

    def content(self) -> str:
        return self.content_value

    def evaluate(self, expr: str) -> Any:
        self.calls.append(("evaluate", {"expr": expr[:80]}))
        # Heuristic stubs:
        if "innerText" in expr:
            return self.text_value
        if "axe.run" in expr:
            # No violations by default
            return "[]"
        return None

    def add_script_tag(self, url: str) -> None:
        self.calls.append(("add_script_tag", {"url": url}))

    def screenshot(self, path: str, full_page: bool = False) -> None:
        self.calls.append(("screenshot", {"path": path, "full_page": full_page}))
        # Write a tiny PNG so visual.check_against_baseline can read it.
        from PIL import Image
        Image.new("RGB", (10, 10), (255, 255, 255)).save(path)

    def locator(self, selector: str):
        class Loc:
            def __init__(self, visible):
                self._visible = visible

            def is_visible(self):
                return self._visible

        return Loc(selector in self.selectors_visible)


# ---------------------------------------------------------------------------
# Sample plan fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_plan() -> TestPlan:
    return TestPlan(
        target_url="https://example.com/",
        summary="Verify the homepage loads and shows expected content.",
        scenarios=[
            Scenario(
                name="Homepage smoke",
                description="Load the homepage and verify the heading appears.",
                steps=[
                    Step(
                        action="navigate",
                        value="https://example.com/",
                        description="Open the homepage",
                    ),
                    Step(
                        action="assert_text",
                        value="Test page",
                        description="Heading text is present",
                    ),
                    Step(
                        action="screenshot",
                        value="homepage",
                        description="Capture homepage for visual regression",
                    ),
                    Step(
                        action="a11y_scan",
                        description="Scan for accessibility violations",
                    ),
                ],
            )
        ],
    )
