"""Visual regression: PIL-based pixel diff with tolerance threshold.

Workflow:
  * On first run, no baseline exists. Current screenshot is saved as
    the new baseline. Reported as info, not a regression.
  * On subsequent runs, current is compared against baseline. If more
    than `threshold_percent` of pixels differ, a VisualDiff is recorded
    along with a diff image.

The diff image highlights changed pixels in magenta on a darkened
copy of the current screenshot. Easy to eyeball at PR-review speed.

Tolerance is calibrated against the % of pixels that changed, not the
magnitude of change per pixel. This is the right metric for catching
layout regressions (whole blocks move) while tolerating anti-aliasing
noise (single pixels in a font shift slightly).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops

from .schemas import VisualDiff


logger = logging.getLogger(__name__)


def check_against_baseline(
    name: str,
    current_path: Path,
    baseline_dir: Path,
    threshold_percent: float = 0.5,
) -> Optional[VisualDiff]:
    """Compare current screenshot against baseline.

    Args:
        name: Logical name (used to locate the baseline file).
        current_path: Path to the just-captured screenshot.
        baseline_dir: Directory holding baseline images.
        threshold_percent: 0-100. Percent of pixels that may differ
            before this is flagged as a regression.

    Returns:
        VisualDiff if the diff exceeds threshold; None if it matches
        OR if this is a first-run baseline capture.
    """
    baseline_dir = Path(baseline_dir)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / f"{name}.png"

    if not baseline_path.exists():
        # First run: capture the baseline. No regression to report.
        _copy_image(current_path, baseline_path)
        logger.info(
            "sentinel.visual.baseline_captured",
            extra={"screenshot_name": name, "path": str(baseline_path)},
        )
        return None

    try:
        baseline = Image.open(baseline_path).convert("RGB")
        current = Image.open(current_path).convert("RGB")
    except Exception as exc:
        logger.warning("sentinel.visual.read_failed", extra={"reason": str(exc)})
        return None

    # Size mismatch is itself a regression (layout shift).
    if baseline.size != current.size:
        diff_path = current_path.parent / f"{name}-diff.png"
        # Resize current to baseline size for the diff image so the
        # output is visually meaningful.
        try:
            current.resize(baseline.size).save(diff_path)
        except Exception:
            pass
        return VisualDiff(
            name=name,
            baseline_path=str(baseline_path),
            current_path=str(current_path),
            diff_path=str(diff_path),
            percent_changed=100.0,
            threshold=threshold_percent,
            severity="error",
        )

    diff = ImageChops.difference(baseline, current)
    bbox = diff.getbbox()
    if bbox is None:
        # Pixel-identical. No regression.
        return None

    # Count differing pixels.
    changed = 0
    total = baseline.size[0] * baseline.size[1]
    for pixel in diff.getdata():
        if any(c > 5 for c in pixel):  # Tolerance for trivial AA noise.
            changed += 1
    percent_changed = (changed / total) * 100.0 if total else 0.0

    if percent_changed <= threshold_percent:
        return None

    # Build a diff visualization: darken the current screenshot, then
    # paint magenta where pixels differ.
    diff_path = current_path.parent / f"{name}-diff.png"
    _render_diff_image(current, diff, diff_path)

    return VisualDiff(
        name=name,
        baseline_path=str(baseline_path),
        current_path=str(current_path),
        diff_path=str(diff_path),
        percent_changed=round(percent_changed, 3),
        threshold=threshold_percent,
        severity="warning",
    )


def _copy_image(src: Path, dst: Path) -> None:
    """Re-save the image at dst so the format is normalized."""
    Image.open(src).save(dst, "PNG")


def _render_diff_image(current: Image.Image, diff: Image.Image, out_path: Path) -> None:
    """Overlay magenta highlights on a darkened current image."""
    # Darken the current image to 50% brightness.
    darkened = Image.eval(current, lambda v: int(v * 0.5))
    # Build a magenta layer the size of the image.
    magenta = Image.new("RGB", current.size, (255, 0, 255))
    # Build a mask from the diff (any nonzero pixel becomes 255).
    mask = diff.convert("L").point(lambda v: 255 if v > 5 else 0)
    composed = Image.composite(magenta, darkened, mask)
    composed.save(out_path, "PNG")
