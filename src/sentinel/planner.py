"""LLM-driven test plan generation.

Given a URL and an optional snapshot of the page contents, ask the LLM
to produce a TestPlan with 2-5 focused Scenarios that exercise the
main user flows visible on the page. Each scenario is short (3-8
steps) so a failure is easy to attribute to a specific action.

We use cascade.llm's structured_call so the plan comes back as a
validated TestPlan Pydantic instance with no JSON parsing fragility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cascade.llm import LLMClient, LLMUsage
from pydantic import BaseModel, ConfigDict, Field

from .schemas import Step, TestPlan


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanOutcome:
    plan: TestPlan
    usage: LLMUsage


@dataclass(frozen=True)
class StepRepair:
    """Outcome of asking the LLM to fix a failed step."""

    repaired_step: "Step"
    usage: LLMUsage
    reasoning: str = ""


def generate_plan(
    *,
    target_url: str,
    page_html: str,
    page_text: str,
    llm: LLMClient,
    temperature: float = 0.2,
) -> PlanOutcome:
    """Generate a TestPlan for a URL.

    Args:
        target_url: The URL Sentinel is testing.
        page_html: Outer HTML of the rendered page. Capped at ~30k chars
            in the prompt to keep token usage sane.
        page_text: Visible text of the page (Playwright's textContent).
            Helps the LLM focus on user-visible elements over markup noise.
        llm: Configured LLM client.
        temperature: Sampling temperature. Default 0.2 for stable plans.

    Returns:
        PlanOutcome with the validated TestPlan and token usage.
    """
    system = _build_system_prompt()
    user = _build_user_prompt(target_url, page_html, page_text)

    response = llm.structured_call(
        system=system,
        user=user,
        schema=TestPlan,
        max_tokens=8192,
        temperature=temperature,
    )
    plan = response.parsed

    # Force the target_url to match what was actually requested. The
    # LLM sometimes invents a URL; we don't trust it.
    if plan.target_url != target_url:
        plan = plan.model_copy(update={"target_url": target_url})

    logger.info(
        "sentinel.plan.generated",
        extra={
            "target_url": target_url,
            "scenario_count": len(plan.scenarios),
        },
    )
    return PlanOutcome(plan=plan, usage=response.usage)


def _build_system_prompt() -> str:
    return (
        "You are a senior QA engineer who writes Playwright tests. You are "
        "looking at the rendered HTML of a single web page and your job is "
        "to write a small set of focused functional tests for the user "
        "flows visible on it.\n\n"
        "Rules:\n\n"
        "  * Produce 2-5 scenarios. More than that is too much for a smoke "
        "    test; less is not enough coverage.\n"
        "  * Each scenario has 3-8 steps. Each step does one thing.\n"
        "  * Start every scenario with a 'navigate' step to the target_url.\n"
        "  * Prefer accessible selectors: text content, role + name, "
        "    'placeholder', 'label'. Avoid fragile CSS selectors like "
        "    '.btn-primary > div.text' unless nothing else identifies "
        "    the element.\n"
        "  * Include at least one 'a11y_scan' step per page state you "
        "    care about (typically at the end of each scenario).\n"
        "  * Include 'screenshot' steps at key moments for visual "
        "    regression. Name them descriptively, e.g. 'homepage-loaded' "
        "    or 'after-clicking-login'.\n"
        "  * Use 'assert_visible' / 'assert_text' / 'assert_url' to "
        "    verify the user actually arrived where they intended.\n"
        "  * Do NOT submit destructive actions (delete, drop, send). "
        "    Sentinel runs on production-like URLs sometimes; respect that.\n"
        "  * Do NOT include login flows unless you have credentials in the "
        "    page (you do not). Skip protected flows for now.\n\n"
        "Available step actions: navigate, click, fill, wait_for, "
        "screenshot, a11y_scan, assert_text, assert_visible, assert_url.\n\n"
        "Your output is a TestPlan with one summary line and a list of "
        "scenarios. Make the summary actionable, not vague."
    )


def _build_user_prompt(target_url: str, page_html: str, page_text: str) -> str:
    # Cap HTML to ~30k chars. The LLM rarely needs more, and we want to
    # keep input tokens predictable.
    html_snippet = page_html[:30_000]
    html_truncated_note = (
        f"\n\n[HTML truncated; original was {len(page_html)} chars]"
        if len(page_html) > 30_000
        else ""
    )

    # Cap text content too.
    text_snippet = page_text[:6_000]
    text_truncated_note = (
        f"\n\n[Visible text truncated; original was {len(page_text)} chars]"
        if len(page_text) > 6_000
        else ""
    )

    return (
        f"# Target URL\n\n{target_url}\n\n"
        f"---\n\n"
        f"# Visible text on the page\n\n{text_snippet}{text_truncated_note}\n\n"
        f"---\n\n"
        f"# Rendered HTML\n\n```html\n{html_snippet}{html_truncated_note}\n```\n\n"
        f"---\n\n"
        f"Generate a TestPlan with 2-5 focused scenarios."
    )


# ---------------------------------------------------------------------------
# Self-healing: re-plan a single failed step
# ---------------------------------------------------------------------------


class _RepairedStepEnvelope(BaseModel):
    """Wraps a Step with a short reasoning string so the LLM explains itself."""

    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=400,
        description="One-line explanation of why the original step failed and how this fix addresses it.",
    )
    step: Step


def regenerate_step(
    *,
    original_step: Step,
    failure_message: str,
    scenario_name: str,
    page_html: str,
    llm: LLMClient,
    temperature: float = 0.0,
) -> StepRepair:
    """Ask the LLM to fix a failed step.

    The typical failure: Playwright strict-mode rejection because the
    selector matches multiple elements. The LLM sees the failure
    message (which Playwright populates with the matching elements)
    and returns a more specific selector.

    Args:
        original_step: The Step that failed.
        failure_message: Playwright error text. Includes matching
            elements in strict-mode failures.
        scenario_name: For context in the prompt.
        page_html: Current page HTML; lets the LLM see what's actually there.
        llm: LLM client (same provider as the rest of the run).
        temperature: 0.0 by default; repairs should be deterministic.

    Returns:
        StepRepair with a new Step the runner can substitute.
    """
    system = (
        "You are a senior QA engineer fixing one failed step in an "
        "automated test scenario. The step failed because Playwright "
        "could not act on the original selector (usually because the "
        "selector matched multiple elements and Playwright's strict "
        "mode refused to guess, or because the selector did not exist "
        "at all). Your job is to rewrite ONLY this step so it works.\n\n"
        "Rules:\n\n"
        "  * Keep the same action and same description.\n"
        "  * Pick the most specific selector that targets exactly one "
        "    element. Prefer get_by_role syntax: "
        "    'role=heading[name=\"Foo\"]' over 'text=Foo'.\n"
        "  * If multiple elements legitimately match, pick the first "
        "    one in document order and disambiguate by parent: "
        "    'role=heading[name=\"Foo\"] >> nth=0' or use a CSS "
        "    selector that includes the parent: '#main h2:has-text(\"Foo\")'.\n"
        "  * For text assertions, prefer assert_visible with a specific "
        "    role-based selector over assert_text with a substring.\n"
        "  * Do NOT change the action type (no swapping click for "
        "    assert_visible) unless the original action is the actual problem.\n\n"
        "Output a Step plus a one-line reasoning explaining your fix."
    )

    user = (
        f"# Scenario context\n\n{scenario_name}\n\n"
        f"---\n\n"
        f"# Original step (failed)\n\n"
        f"action: {original_step.action}\n"
        f"selector: {original_step.selector!r}\n"
        f"value: {original_step.value!r}\n"
        f"description: {original_step.description}\n\n"
        f"---\n\n"
        f"# Playwright failure message\n\n```\n{failure_message[:2000]}\n```\n\n"
        f"---\n\n"
        f"# Current page HTML (first 20k chars)\n\n```html\n{page_html[:20_000]}\n```\n\n"
        f"---\n\n"
        f"Output a repaired Step that resolves the failure."
    )

    response = llm.structured_call(
        system=system,
        user=user,
        schema=_RepairedStepEnvelope,
        max_tokens=2048,
        temperature=temperature,
    )

    repaired = response.parsed.step
    # Preserve the original description so the failure report stays
    # human-readable; we don't want self-healing to rewrite intent.
    repaired = repaired.model_copy(update={"description": original_step.description})

    logger.info(
        "sentinel.planner.step_repaired",
        extra={
            "scenario": scenario_name,
            "original_selector": original_step.selector,
            "repaired_selector": repaired.selector,
        },
    )
    return StepRepair(
        repaired_step=repaired,
        usage=response.usage,
        reasoning=response.parsed.reasoning,
    )
