"""Tests for sentinel.config."""

from __future__ import annotations

import pytest

from cascade.exceptions import CascadeError

from sentinel.config import DEFAULT_SENTINEL_YAML, SentinelConfig, load_config


class TestSentinelConfig:
    def test_all_defaults(self):
        cfg = SentinelConfig()
        assert cfg.version == 1
        assert cfg.agent.provider == "anthropic"
        assert cfg.browser.headless is True
        assert cfg.browser.viewport_width == 1280
        assert cfg.visual.enabled is True
        assert cfg.visual.diff_threshold_percent == 0.5
        assert cfg.a11y.enabled is True
        assert "critical" in cfg.a11y.fail_on
        assert "serious" in cfg.a11y.fail_on

    def test_default_yaml_parses(self, tmp_path):
        (tmp_path / "sentinel.yaml").write_text(DEFAULT_SENTINEL_YAML)
        cfg = load_config(tmp_path)
        assert cfg.version == 1

    def test_partial_override(self, tmp_path):
        (tmp_path / "sentinel.yaml").write_text(
            """
version: 1
browser:
  headless: false
  viewport_width: 1920
visual:
  diff_threshold_percent: 2.0
"""
        )
        cfg = load_config(tmp_path)
        assert cfg.browser.headless is False
        assert cfg.browser.viewport_width == 1920
        assert cfg.visual.diff_threshold_percent == 2.0
        # Untouched defaults
        assert cfg.browser.viewport_height == 720
        assert cfg.a11y.enabled is True

    def test_invalid_yaml(self, tmp_path):
        (tmp_path / "sentinel.yaml").write_text("not: : valid: yaml: : :")
        with pytest.raises(CascadeError, match="not valid YAML"):
            load_config(tmp_path)

    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert cfg == SentinelConfig()

    def test_viewport_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SentinelConfig.model_validate({"browser": {"viewport_width": 100}})
        with pytest.raises(ValidationError):
            SentinelConfig.model_validate({"browser": {"viewport_width": 9999}})

    def test_diff_threshold_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SentinelConfig.model_validate({"visual": {"diff_threshold_percent": -1.0}})
        with pytest.raises(ValidationError):
            SentinelConfig.model_validate({"visual": {"diff_threshold_percent": 101.0}})
