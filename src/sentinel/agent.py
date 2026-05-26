"""End-to-end Sentinel pipeline: URL -> plan -> run -> report.

Stages:
  1. Open a headless Chromium, navigate to the URL
  2. Capture the rendered HTML + visible text
  3. Ask the LLM to produce a TestPlan
  4. Close the exploration session, run the plan in fresh sessions
  5. Return the SentinelReport

A future v0.1.0a2 will let the agent iterate: if scenarios fail in
ways the LLM can fix (e.g. "the selector I chose doesn't exist"),
regenerate just those scenarios. v0.1.0a1 is single-shot.
"""

from __future__ import annotations

import logging
from pathlib import Path

from cascade.llm import LLMClient

from .browser import open_session
from .config import SentinelConfig
from .planner import generate_plan
from .runner import run_plan
from .schemas import SentinelReport


logger = logging.getLogger(__name__)


def run_sentinel(
    *,
    target_url: str,
    config: SentinelConfig,
    llm: LLMClient,
    workspace_dir: Path,
) -> SentinelReport:
    """Run the full Sentinel pipeline for a URL.

    Args:
        target_url: The URL to test.
        config: Loaded sentinel.yaml config.
        llm: LLM client (from cascade.llm).
        workspace_dir: Where to write screenshots, baselines, diffs.
            Sentinel never writes outside this directory.

    Returns:
        SentinelReport with the full outcome.
    """
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: explore. Open the URL, grab HTML + text.
    logger.info("sentinel.agent.explore", extra={"url": target_url})
    page_html = ""
    page_text = ""
    with open_session(config.browser, workspace_dir / "screenshots") as session:
        page = session.page
        page.goto(target_url, timeout=config.browser.timeout_ms)
        # Wait for the page to settle (no network for 500ms).
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            # Some apps never go idle (live polling, websockets). That's fine.
            pass
        page_html = page.content()
        page_text = page.evaluate("() => document.body.innerText || ''")

    # Stage 2: plan. LLM produces a TestPlan from what we saw.
    logger.info("sentinel.agent.plan")
    plan_outcome = generate_plan(
        target_url=target_url,
        page_html=page_html,
        page_text=page_text,
        llm=llm,
        temperature=config.agent.temperature,
    )

    # Stage 3: run. Walk the plan in fresh browser sessions.
    logger.info("sentinel.agent.run", extra={"scenarios": len(plan_outcome.plan.scenarios)})
    report = run_plan(
        plan=plan_outcome.plan,
        config=config,
        workspace_dir=workspace_dir,
    )

    # Stage 4: attach LLM usage to the report.
    report.total_input_tokens = plan_outcome.usage.input_tokens
    report.total_output_tokens = plan_outcome.usage.output_tokens
    report.total_llm_cost_usd = plan_outcome.usage.estimated_cost_usd

    return report
