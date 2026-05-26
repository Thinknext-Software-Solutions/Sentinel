"""Tests for sentinel.visual."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from sentinel.visual import check_against_baseline


def write_image(path: Path, size=(50, 50), color=(255, 255, 255)) -> None:
    Image.new("RGB", size, color).save(path)


class TestLoggingDoesNotCrash:
    """Regression: visual.py used extra={"name": ...} which collides with
    Python LogRecord's reserved 'name' attribute. First live run crashed
    with KeyError. This test exercises the log path with a real Python
    logger to catch the bug at unit-test time."""

    def test_baseline_capture_logs_cleanly(self, tmp_path, caplog):
        current = tmp_path / "homepage.png"
        write_image(current, color=(255, 0, 0))
        baselines = tmp_path / "baselines"

        with caplog.at_level(logging.INFO, logger="sentinel.visual"):
            diff = check_against_baseline(
                name="homepage",
                current_path=current,
                baseline_dir=baselines,
            )

        assert diff is None
        # If we got here without a KeyError, the log call succeeded.
        # Also assert the log record actually went out.
        assert any(
            "baseline_captured" in r.message for r in caplog.records
        )


class TestCheckAgainstBaseline:
    def test_first_run_creates_baseline(self, tmp_path):
        current = tmp_path / "homepage.png"
        write_image(current, color=(255, 0, 0))
        baselines = tmp_path / "baselines"

        diff = check_against_baseline(
            name="homepage",
            current_path=current,
            baseline_dir=baselines,
        )
        assert diff is None
        assert (baselines / "homepage.png").exists()

    def test_identical_images_return_none(self, tmp_path):
        current = tmp_path / "homepage.png"
        baselines = tmp_path / "baselines"
        write_image(current, color=(255, 0, 0))

        # First run captures baseline
        check_against_baseline("homepage", current, baselines)
        # Second run with identical image: should match
        diff = check_against_baseline("homepage", current, baselines)
        assert diff is None

    def test_minor_change_under_threshold(self, tmp_path):
        baselines = tmp_path / "baselines"
        baseline_image = tmp_path / "first.png"
        current_image = tmp_path / "second.png"

        # Create a baseline of 100x100 red
        write_image(baseline_image, size=(100, 100), color=(255, 0, 0))
        check_against_baseline("homepage", baseline_image, baselines)

        # Create a current that differs in only a few pixels (well under
        # 0.5% threshold on a 10000-pixel image)
        Image.new("RGB", (100, 100), (255, 0, 0)).save(current_image)
        img = Image.open(current_image)
        # Change ~10 pixels = 0.1%
        for x in range(10):
            img.putpixel((x, 0), (0, 0, 0))
        img.save(current_image)

        diff = check_against_baseline(
            "homepage", current_image, baselines, threshold_percent=0.5
        )
        # 0.1% < 0.5% threshold -> no regression
        assert diff is None

    def test_large_change_flags_diff(self, tmp_path):
        baselines = tmp_path / "baselines"
        baseline_image = tmp_path / "first.png"
        current_image = tmp_path / "second.png"

        # Baseline: 100x100 red
        write_image(baseline_image, size=(100, 100), color=(255, 0, 0))
        check_against_baseline("homepage", baseline_image, baselines)

        # Current: 100x100 blue (every pixel differs)
        write_image(current_image, size=(100, 100), color=(0, 0, 255))

        diff = check_against_baseline(
            "homepage", current_image, baselines, threshold_percent=0.5
        )
        assert diff is not None
        assert diff.percent_changed > 50.0
        assert diff.severity == "warning"
        assert Path(diff.diff_path).exists()

    def test_size_mismatch_is_error(self, tmp_path):
        baselines = tmp_path / "baselines"
        baseline_image = tmp_path / "first.png"
        current_image = tmp_path / "second.png"

        write_image(baseline_image, size=(100, 100))
        check_against_baseline("homepage", baseline_image, baselines)

        # Current is a different size (a resize, a layout change, etc.)
        write_image(current_image, size=(200, 100))

        diff = check_against_baseline("homepage", current_image, baselines)
        assert diff is not None
        assert diff.severity == "error"
        assert diff.percent_changed == 100.0
