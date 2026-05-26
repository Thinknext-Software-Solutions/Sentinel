"""End-to-end Sentinel pipeline: URL -> explore -> plan -> run -> report.

Stages:
  1. Open headless Chromium, navigate to the URL, capture HTML + text
  2. Optionally discover same-origin links and capture them too
     (multi-page exploration; capped to keep token usage sane)
  3. Ask the LLM to produce a TestPlan covering the discovered surface
  4. Run the plan in fresh browser sessions; runner self-heals failed
     steps via one LLM repair attempt before giving up
  5. Return the SentinelReport
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

from cascade.llm import LLMClient

from .browser import open_session
from .config import SentinelConfig
from .planner import generate_plan
from .runner import run_plan
from .schemas import SentinelReport


logger = logging.getLogger(__name__)


# Cap on how many additional pages the explorer pulls so the planner
# prompt stays bounded.
MAX_DISCOVERED_PAGES = 4


def run_sentinel(
    *,
    target_url: str,
    config: SentinelConfig,
    llm: LLMClient,
    workspace_dir: Path,
    explore_links: bool = True,
) -> SentinelReport:
    """Run the full Sentinel pipeline for a URL.

    Args:
        target_url: The URL to test.
        config: Loaded sentinel.yaml config.
        llm: LLM client (from cascade.llm).
        workspace_dir: Where to write screenshots, baselines, diffs.
            Sentinel never writes outside this directory.
        explore_links: If True, also discover up to MAX_DISCOVERED_PAGES
            same-origin links from the target URL and include a brief
            snapshot of each in the planner prompt. Lets the LLM write
            scenarios that span navigation, not just the landing page.

    Returns:
        SentinelReport with the full outcome.
    """
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: explore. Open the URL, grab HTML + text.
    logger.info("sentinel.agent.explore", extra={"url": target_url})
    page_html = ""
    page_text = ""
    discovered_pages: list[tuple[str, str]] = []  # [(url, text_snippet), ...]

    with open_session(config.browser, workspace_dir / "screenshots") as session:
        page = session.page
        page.goto(target_url, timeout=config.browser.timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page_html = page.content()
        page_text = page.evaluate("() => document.body.innerText || ''")

        if explore_links:
            try:
                same_origin_links = _discover_same_origin_links(
                    page, base_url=target_url
                )
                logger.info(
                    "sentinel.agent.discovered_links",
                    extra={"count": len(same_origin_links)},
                )
                # Visit up to MAX_DISCOVERED_PAGES additional pages and
                # capture a short text snippet of each.
                for link in same_origin_links[:MAX_DISCOVERED_PAGES]:
                    try:
                        page.goto(link, timeout=config.browser.timeout_ms)
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            pass
                        snippet = page.evaluate("() => document.body.innerText || ''")
                        discovered_pages.append((link, snippet[:2000]))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "sentinel.agent.discovery_skip",
                            extra={"link": link, "reason": str(exc)[:120]},
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sentinel.agent.discovery_failed",
                    extra={"reason": str(exc)[:120]},
                )

    # If we discovered additional pages, weave a digest into the page_text
    # so the planner sees the broader surface.
    if discovered_pages:
        digest_lines = ["", "# Additional discovered pages:", ""]
        for url, snippet in discovered_pages:
            digest_lines.append(f"## {url}\n{snippet[:800]}\n")
        page_text = page_text + "\n\n" + "\n".join(digest_lines)

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
    # Pass the LLM so the runner can self-heal failed steps with one
    # repair attempt before giving up on a scenario.
    logger.info("sentinel.agent.run", extra={"scenarios": len(plan_outcome.plan.scenarios)})
    report = run_plan(
        plan=plan_outcome.plan,
        config=config,
        workspace_dir=workspace_dir,
        llm=llm,
        self_heal=True,
    )

    # Stage 4: attach LLM usage to the report.
    report.total_input_tokens += plan_outcome.usage.input_tokens
    report.total_output_tokens += plan_outcome.usage.output_tokens
    report.total_llm_cost_usd += plan_outcome.usage.estimated_cost_usd

    return report


def _discover_same_origin_links(page, base_url: str) -> list[str]:
    """Return same-origin links discovered on the current page.

    Filters out external links, anchors-only, mailto:, tel:, javascript:,
    duplicates, and pages we likely don't want to test (login forms,
    logout buttons, admin paths). Returns absolute URLs.
    """
    base = urlparse(base_url)
    base_origin = f"{base.scheme}://{base.netloc}"

    hrefs = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.getAttribute('href'))
            .filter(h => h && !h.startsWith('#') && !h.startsWith('mailto:') && !h.startsWith('tel:') && !h.startsWith('javascript:'))"""
    )

    seen: set[str] = set()
    out: list[str] = []
    excluded_segments = {"login", "logout", "signin", "signout", "admin", "auth"}

    for href in hrefs or []:
        try:
            absolute = urljoin(base_url, str(href))
            parsed = urlparse(absolute)
            # Same-origin only
            if f"{parsed.scheme}://{parsed.netloc}" != base_origin:
                continue
            # Skip pages with auth-related path segments
            path_segments = {s.lower() for s in parsed.path.split("/") if s}
            if path_segments & excluded_segments:
                continue
            # Strip query + fragment for dedup
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if normalized in seen or normalized == base_url.rstrip("/"):
                continue
            seen.add(normalized)
            out.append(normalized)
        except Exception:
            continue

    return out
