"""sentinel.yaml schema + loader.

Single config file. Lives in the project root next to the app being tested
(or anywhere the user runs `sentinel run` from).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .exceptions import SentinelError


class AgentConfig(BaseModel):
    """LLM provider for the planner stage."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="anthropic")
    model: Optional[str] = Field(default=None)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class VisualConfig(BaseModel):
    """Visual-regression behavior."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True)
    baseline_dir: str = Field(
        default="sentinel-baselines",
        description="Directory where reference screenshots live.",
    )
    diff_threshold_percent: float = Field(
        default=0.5,
        ge=0.0,
        le=100.0,
        description=(
            "Percent of pixels that may differ before flagging a regression. "
            "0.5 means 0.5% of pixels can change and we still consider it a match."
        ),
    )


class A11yConfig(BaseModel):
    """Accessibility scan behavior."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True)
    fail_on: list[str] = Field(
        default_factory=lambda: ["critical", "serious"],
        description=(
            "axe impact levels that count as test failures. "
            "Anything not in this list is reported but does not fail the run."
        ),
    )


class BrowserConfig(BaseModel):
    """Playwright browser config."""

    model_config = ConfigDict(extra="forbid")

    headless: bool = Field(default=True)
    viewport_width: int = Field(default=1280, ge=320, le=4096)
    viewport_height: int = Field(default=720, ge=240, le=4096)
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)


class SentinelConfig(BaseModel):
    """Parsed sentinel.yaml."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1)
    target_url: Optional[str] = Field(
        default=None,
        description="Default target URL; overridden by CLI arg.",
    )
    agent: AgentConfig = Field(default_factory=AgentConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    a11y: A11yConfig = Field(default_factory=A11yConfig)


DEFAULT_CONFIG_FILENAME = "sentinel.yaml"


def load_config(repo_root: Optional[Path] = None) -> SentinelConfig:
    """Load sentinel.yaml from repo_root, fall back to all-defaults."""
    root = repo_root or Path.cwd()
    cfg_path = root / DEFAULT_CONFIG_FILENAME
    if not cfg_path.exists():
        return SentinelConfig()
    try:
        raw = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise SentinelError(
            f"sentinel.yaml at {cfg_path} is not valid YAML",
            hint=str(exc),
        ) from exc
    if not isinstance(raw, dict):
        raise SentinelError(
            f"sentinel.yaml at {cfg_path} must be a mapping at the top level"
        )
    try:
        return SentinelConfig.model_validate(raw)
    except Exception as exc:
        raise SentinelError(
            f"sentinel.yaml at {cfg_path} is invalid", hint=str(exc)
        ) from exc


DEFAULT_SENTINEL_YAML = """\
version: 1

# target_url: https://example.com    # Optional; overridden by CLI arg

agent:
  provider: anthropic
  model: claude-opus-4-7
  temperature: 0.2

browser:
  headless: true
  viewport_width: 1280
  viewport_height: 720
  timeout_ms: 30000

visual:
  enabled: true
  baseline_dir: sentinel-baselines
  diff_threshold_percent: 0.5

a11y:
  enabled: true
  fail_on:
    - critical
    - serious
"""
