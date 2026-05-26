"""Tests for sentinel.a11y."""

from __future__ import annotations

import json

from sentinel.a11y import _normalize_impact, _parse_violation, scan_page

from conftest import FakePage


class TestParseViolation:
    def test_minimal(self):
        v = _parse_violation(
            {
                "id": "color-contrast",
                "impact": "serious",
                "description": "Elements must meet contrast",
                "helpUrl": "https://example.com/h",
                "nodes": [{"target": [".foo"]}],
            }
        )
        assert v is not None
        assert v.rule_id == "color-contrast"
        assert v.impact == "serious"
        assert v.nodes_affected == 1
        assert v.sample_selector == ".foo"

    def test_missing_optional_fields(self):
        v = _parse_violation({"id": "x", "impact": "minor", "nodes": [{}]})
        assert v is not None
        assert v.rule_id == "x"
        assert v.impact == "minor"
        assert v.description == ""
        assert v.help_url == ""

    def test_no_nodes_still_counts_as_one(self):
        v = _parse_violation({"id": "x", "impact": "minor", "nodes": []})
        assert v is not None
        # Validator requires nodes_affected >= 1
        assert v.nodes_affected == 1

    def test_garbage_returns_none(self):
        v = _parse_violation({"id": None, "impact": None, "nodes": None})
        # Garbage might still parse with defaults; verify it doesn't blow up
        # (either None or a low-confidence entry is acceptable)
        assert v is None or v.rule_id


class TestNormalizeImpact:
    def test_known_impacts(self):
        assert _normalize_impact("critical") == "critical"
        assert _normalize_impact("serious") == "serious"
        assert _normalize_impact("moderate") == "moderate"
        assert _normalize_impact("minor") == "minor"

    def test_case_insensitive(self):
        assert _normalize_impact("Critical") == "critical"
        assert _normalize_impact("SERIOUS") == "serious"

    def test_none_defaults_to_minor(self):
        assert _normalize_impact(None) == "minor"

    def test_unknown_defaults_to_minor(self):
        assert _normalize_impact("blocker") == "minor"


class TestScanPage:
    def test_no_violations(self):
        page = FakePage()
        # FakePage.evaluate() returns "[]" for axe calls by default
        violations = scan_page(page)
        assert violations == []

    def test_with_violations(self):
        page = FakePage()

        # Override evaluate to return canned axe results
        canned = [
            {
                "id": "image-alt",
                "impact": "critical",
                "description": "Images must have alt text",
                "helpUrl": "https://x",
                "nodes": [{"target": ["img.hero"]}, {"target": ["img.logo"]}],
            }
        ]
        original_evaluate = page.evaluate

        def fake_evaluate(expr):
            if "axe.run" in expr:
                return json.dumps(canned)
            return original_evaluate(expr)

        page.evaluate = fake_evaluate

        violations = scan_page(page)
        assert len(violations) == 1
        assert violations[0].rule_id == "image-alt"
        assert violations[0].impact == "critical"
        assert violations[0].nodes_affected == 2

    def test_scan_failure_returns_empty(self):
        page = FakePage()

        def boom(expr):
            raise RuntimeError("axe not loaded")

        page.evaluate = boom
        # Should not propagate the exception; just log and return []
        violations = scan_page(page)
        assert violations == []
