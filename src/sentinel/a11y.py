"""Accessibility scanning via axe-core injected into the page.

We inject the axe-core JS bundle from the unpkg CDN once per page,
then call `axe.run()` and pick the violations out of the result.

For air-gapped environments, we could vendor axe-core into the
package, but that adds ~700KB to the wheel. v0.1.0a1 keeps it as a
runtime CDN load; v0.1.0a2 will let users opt into the vendored
copy via `a11y.bundled: true` in sentinel.yaml.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .schemas import A11yImpact, A11yViolation


logger = logging.getLogger(__name__)


AXE_CDN_URL = "https://unpkg.com/axe-core@4.10.0/axe.min.js"


def scan_page(page) -> list[A11yViolation]:
    """Run axe-core against the current page state. Returns violations.

    Args:
        page: A live Playwright Page object (sync API).

    Returns:
        List of A11yViolation objects. Empty list means no violations.
    """
    try:
        # Inject axe-core. Idempotent: if already present, nothing happens.
        page.add_script_tag(url=AXE_CDN_URL)

        # Run the scan. axe.run() returns a Promise; we await it via
        # Playwright's evaluate-and-return mechanism.
        result = page.evaluate(
            """async () => {
                const r = await axe.run({
                    runOnly: {
                        type: 'tag',
                        values: ['wcag2a', 'wcag2aa', 'wcag21aa']
                    }
                });
                return JSON.stringify(r.violations);
            }"""
        )
    except Exception as exc:
        logger.warning("sentinel.a11y.scan_failed", extra={"reason": str(exc)})
        return []

    try:
        raw_violations = json.loads(result) if isinstance(result, str) else result
    except (json.JSONDecodeError, TypeError):
        logger.warning("sentinel.a11y.parse_failed", extra={"raw": str(result)[:200]})
        return []

    return [_parse_violation(v) for v in raw_violations if v]


def _parse_violation(raw: dict[str, Any]) -> Optional[A11yViolation]:
    """Convert axe-core's violation shape into our A11yViolation."""
    try:
        impact = _normalize_impact(raw.get("impact", "minor"))
        nodes = raw.get("nodes") or []
        sample_selector = None
        if nodes:
            target = nodes[0].get("target")
            if isinstance(target, list) and target:
                sample_selector = str(target[0])

        return A11yViolation(
            rule_id=str(raw.get("id", "unknown")),
            impact=impact,
            description=str(raw.get("description", ""))[:500],
            help_url=str(raw.get("helpUrl", "")),
            nodes_affected=max(1, len(nodes)),
            sample_selector=sample_selector,
        )
    except Exception as exc:
        logger.warning(
            "sentinel.a11y.skipped_violation",
            extra={"rule_id": raw.get("id"), "reason": str(exc)},
        )
        return None


def _normalize_impact(raw: Any) -> A11yImpact:
    """axe-core sometimes returns None or odd capitalizations; normalize."""
    if isinstance(raw, str):
        v = raw.lower()
        if v in ("critical", "serious", "moderate", "minor"):
            return v  # type: ignore[return-value]
    return "minor"
