"""LLM-driven plan generation for API testing.

Two modes:

  * generate_api_plan_from_spec: feeds an OpenAPI/Swagger spec to the
    LLM and asks for a TestPlan covering each operation.
  * generate_api_plan_from_url: probes a base URL (issues a GET) and
    asks the LLM to write a plan based on the response shape. Useful
    when no spec is available.

The plan output is APITestPlan (validated Pydantic), same pattern as
the web planner.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from cascade.llm import LLMClient, LLMUsage

from .api_schemas import APITestPlan


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class APIPlanOutcome:
    plan: APITestPlan
    usage: LLMUsage


def generate_api_plan_from_spec(
    *,
    base_url: str,
    spec: dict[str, Any],
    llm: LLMClient,
    temperature: float = 0.2,
    max_scenarios: int = 12,
) -> APIPlanOutcome:
    """Build an APITestPlan from an OpenAPI / Swagger spec dict.

    Args:
        base_url: Resolved base URL (e.g. https://api.example.com/v1).
        spec: Parsed OpenAPI spec (JSON or YAML deserialized to dict).
        llm: LLM client.
        temperature: Sampling temperature. Default 0.2.
        max_scenarios: Soft cap; the prompt asks for this many.

    Returns:
        APIPlanOutcome with validated APITestPlan + token usage.
    """
    spec_summary = _summarize_openapi(spec)
    system = _system_prompt(max_scenarios)
    user = (
        f"# Target base URL\n\n{base_url}\n\n"
        f"---\n\n"
        f"# OpenAPI spec (summarized)\n\n{spec_summary}\n\n"
        f"---\n\n"
        f"Build an APITestPlan that exercises the most important "
        f"operations. Cap at {max_scenarios} scenarios."
    )

    response = llm.structured_call(
        system=system,
        user=user,
        schema=APITestPlan,
        max_tokens=8192,
        temperature=temperature,
    )

    # Force base_url to the agreed value (LLM sometimes invents one).
    plan = response.parsed
    if plan.target_base_url != base_url:
        plan = plan.model_copy(update={"target_base_url": base_url})

    logger.info(
        "sentinel.api_planner.from_spec",
        extra={"base_url": base_url, "scenario_count": len(plan.scenarios)},
    )
    return APIPlanOutcome(plan=plan, usage=response.usage)


def generate_api_plan_from_url(
    *,
    base_url: str,
    probe_response: Optional[dict[str, Any]] = None,
    llm: LLMClient,
    temperature: float = 0.2,
    max_scenarios: int = 6,
) -> APIPlanOutcome:
    """Build a plan when no spec is available.

    Args:
        base_url: The base URL.
        probe_response: Optional dict of {url: response_summary} the
            agent gathered by hitting the base URL + common discovery
            endpoints (/, /health, /api, /docs). Helps the LLM.
        llm: LLM client.
        temperature: Sampling temperature.
        max_scenarios: Soft cap.

    Returns:
        APIPlanOutcome.
    """
    system = _system_prompt(max_scenarios)
    probe_section = ""
    if probe_response:
        probe_section = "\n\n---\n\n# Probe responses\n\n"
        for url, summary in probe_response.items():
            probe_section += f"## {url}\n\n```\n{summary[:1500]}\n```\n\n"

    user = (
        f"# Target base URL\n\n{base_url}\n\n"
        f"---\n\n"
        f"# Context\n\nNo OpenAPI/Swagger spec was provided. Generate a "
        f"conservative smoke-test plan based on the base URL and any "
        f"probe responses below. Prefer GET requests on plausible "
        f"endpoints like /, /health, /healthz, /api, /api/v1, /metrics. "
        f"Do NOT generate destructive requests (POST/PUT/DELETE) without "
        f"explicit endpoint evidence."
        f"{probe_section}\n\n"
        f"---\n\n"
        f"Build an APITestPlan with up to {max_scenarios} conservative scenarios."
    )

    response = llm.structured_call(
        system=system,
        user=user,
        schema=APITestPlan,
        max_tokens=4096,
        temperature=temperature,
    )

    plan = response.parsed
    if plan.target_base_url != base_url:
        plan = plan.model_copy(update={"target_base_url": base_url})

    logger.info(
        "sentinel.api_planner.from_url",
        extra={"base_url": base_url, "scenario_count": len(plan.scenarios)},
    )
    return APIPlanOutcome(plan=plan, usage=response.usage)


# ---------------------------------------------------------------------------
# Prompts + helpers
# ---------------------------------------------------------------------------


def _system_prompt(max_scenarios: int) -> str:
    return (
        "You are a senior backend QA engineer who writes API contract "
        "tests. Produce an APITestPlan: a target_base_url, a one-line "
        "summary, and a list of scenarios.\n\n"
        "Each scenario is exactly one HTTP request plus one or more "
        "assertions about the response. Scenarios do not share state. "
        "Treat each scenario as a stand-alone smoke test.\n\n"
        "Rules:\n\n"
        f"  * Produce at most {max_scenarios} scenarios. Less is fine.\n"
        "  * Lead with assertions about response status (always include "
        "    one). Add response_time assertions only if you have a "
        "    reasonable upper bound (e.g. < 2000 ms).\n"
        "  * For JSON APIs, include json_field assertions on the "
        "    structural fields you'd expect (e.g. data is an array, "
        "    error is null, version is a string).\n"
        "  * Use json_field_type when you want to verify shape without "
        "    pinning to a specific value.\n"
        "  * Use header assertions for content-type, cache-control, etc.\n"
        "  * Body_contains is a fallback when you can't predict JSON "
        "    structure but expect specific text in the response.\n"
        "  * Path can be relative ('/health') or absolute "
        "    ('https://api.example.com/health'). Prefer relative.\n"
        "  * NEVER generate DELETE requests against unknown endpoints.\n"
        "  * NEVER generate POST/PUT/PATCH against unknown endpoints "
        "    unless you have explicit evidence from a spec.\n"
        "  * Headers should be functional only (Accept, Content-Type). "
        "    Authorization is configured at the run level, not in the plan.\n\n"
        "Available assertion types: status, json_field, json_field_type, "
        "header, body_contains, response_time."
    )


def _summarize_openapi(spec: dict[str, Any]) -> str:
    """Reduce an OpenAPI spec to a compact, LLM-friendly listing.

    We strip schemas and component definitions (too verbose); keep
    operation paths, methods, parameters, and one-line descriptions.
    Caps total output at ~25k chars.
    """
    lines: list[str] = []
    info = spec.get("info", {})
    lines.append(f"# {info.get('title', '(no title)')}  v{info.get('version', '?')}")
    if info.get("description"):
        lines.append(str(info["description"])[:400])
    lines.append("")

    servers = spec.get("servers", [])
    if servers:
        lines.append("Servers:")
        for s in servers[:3]:
            lines.append(f"  - {s.get('url')}")
        lines.append("")

    paths = spec.get("paths", {})
    lines.append(f"Operations ({sum(len(p) for p in paths.values())} total):")
    lines.append("")

    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    count = 0
    for path, ops in paths.items():
        for method, op in ops.items():
            if method.lower() not in methods:
                continue
            summary = (op.get("summary") or op.get("operationId") or "")[:120]
            params = op.get("parameters", [])
            param_strs = []
            for p in params[:4]:
                name = p.get("name", "?")
                in_ = p.get("in", "?")
                required = "*" if p.get("required") else ""
                param_strs.append(f"{name}{required}({in_})")
            param_summary = ", ".join(param_strs) if param_strs else ""
            lines.append(f"  {method.upper():7s} {path}  -- {summary}")
            if param_summary:
                lines.append(f"           params: {param_summary}")
            count += 1
            if count > 80:
                lines.append(f"  ... ({sum(len(p) for p in paths.values()) - count} more operations omitted)")
                break
        if count > 80:
            break

    text = "\n".join(lines)
    return text[:25_000] + ("...[truncated]" if len(text) > 25_000 else "")
