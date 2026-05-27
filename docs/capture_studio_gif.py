"""Build an animated walkthrough GIF of Sentinel Studio for the README.

Uses Playwright to capture a sequence of full-page snapshots through the
canonical flow (sign in -> projects -> project detail -> run detail ->
admin users), then stitches them into a single animated GIF with Pillow.

Output: docs/studio-walkthrough.gif

Each frame gets a caption banner so a reader can follow the flow at a
glance without playing the GIF more than once.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "studio-walkthrough.gif"
FRAMES_DIR = Path(__file__).resolve().parent / "_walkthrough_frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = tempfile.mkdtemp(prefix="sentinel-walkthrough-")
ADMIN_EMAIL = "admin@studio.example"
ADMIN_PW = "AdminPass123!"

# Wide enough to read; not so big the GIF is huge.
VIEWPORT_W = 1200
VIEWPORT_H = 720
# Caption banner height added on top of each frame.
CAPTION_H = 56
# Frame duration in milliseconds. Slow enough to read.
FRAME_MS = 2200
# Final frame lingers a bit longer so the loop has a natural pause.
LAST_FRAME_MS = 3200


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server at {url} never came up")


def seed_db() -> None:
    os.environ["SENTINEL_SERVER_HOME"] = DATA_DIR
    from sentinel.server import db as db_mod
    db_mod.reset_for_tests()

    from sentinel.server.bootstrap import init_database, create_or_update_admin
    init_database()
    admin = create_or_update_admin(ADMIN_EMAIL, ADMIN_PW, name="Admin")

    from sentinel.server.auth import hash_password
    from sentinel.server.db import session_scope
    from sentinel.server.models import (
        A11yViolation, Project, Run, ScenarioRun, StepFailure, User, VisualDiff,
    )

    with session_scope() as db:
        db.add(User(
            email="member@studio.example",
            name="Aditi Rao",
            hashed_password=hash_password("MemberPass1!"),
            role="member",
        ))
        proj = Project(
            slug="marketing-site",
            name="Marketing site",
            base_url="https://example.com",
            description="Public marketing site. Tracks landing page, pricing, signup.",
            llm_provider="claude_code",
            llm_model="claude-opus-4-7",
            explore_links=True,
            created_by_user_id=admin.id,
        )
        db.add(proj)
        db.flush()

        base = datetime.now(timezone.utc)
        for i in range(3, 0, -1):
            db.add(Run(
                project_id=proj.id, triggered_by_user_id=admin.id,
                target_url="https://example.com", status="passed",
                created_at=base - timedelta(hours=i * 6),
                started_at=base - timedelta(hours=i * 6),
                finished_at=base - timedelta(hours=i * 6),
                cost_usd=0.03, input_tokens=4980, output_tokens=812,
                scenarios_total=4, scenarios_passed=4,
                visual_diffs_count=0, a11y_violations_count=0,
            ))
        db.flush()

        run = Run(
            project_id=proj.id, triggered_by_user_id=admin.id,
            target_url="https://example.com", status="failed",
            created_at=base, started_at=base, finished_at=base,
            cost_usd=0.04, input_tokens=5210, output_tokens=980,
            scenarios_total=4, scenarios_passed=3,
            visual_diffs_count=1, a11y_violations_count=2,
        )
        db.add(run)
        db.flush()

        scenarios = [
            ("Homepage hero and trust bar render", True, 1.42, None),
            ("Sign-up CTA routes to /login?mode=signup", True, 1.83, None),
            ("Pricing card surfaces all three plans", True, 2.10, None),
            ("Newsletter form posts to /api/subscribe", False, 4.12,
             ("Submit button is enabled with blank email",
              "Locator.click: Timeout 5000ms exceeded.\n"
              "Call log: waiting for locator('form button[type=\"submit\"]') to be enabled")),
        ]
        for idx, (name, passed, dur, failure) in enumerate(scenarios):
            scen = ScenarioRun(
                run_id=run.id, name=name, description="",
                passed=passed, duration_seconds=dur, order_index=idx,
            )
            db.add(scen)
            db.flush()
            if failure:
                db.add(StepFailure(
                    scenario_id=scen.id, step_index=3,
                    step_description=failure[0], message=failure[1],
                ))

        db.add(A11yViolation(
            run_id=run.id, page_url="https://example.com",
            rule_id="color-contrast", impact="serious",
            description="Elements must meet minimum color contrast (WCAG 2 AA).",
            sample_selector=".text-slate-500", nodes_affected=12,
        ))
        db.add(A11yViolation(
            run_id=run.id, page_url="https://example.com/pricing",
            rule_id="image-alt", impact="moderate",
            description="Images must have alt text.",
            sample_selector="img.plan-icon", nodes_affected=3,
        ))
        db.add(VisualDiff(
            run_id=run.id, name="homepage-hero",
            baseline_path="hero.baseline.png", current_path="hero.current.png",
            diff_path="hero.diff.png",
            percent_changed=1.18, threshold=0.50,
        ))


def start_server(port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["SENTINEL_SERVER_HOME"] = DATA_DIR
    proc = subprocess.Popen(
        [sys.executable, "-m", "sentinel.cli", "server", "up", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    wait_http(f"http://127.0.0.1:{port}/api/health")
    return proc


# ---------------------------------------------------------------------------
# Frame compositing
# ---------------------------------------------------------------------------


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Best-effort font lookup. Falls back to default if no TTF is around."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def add_caption(img: Image.Image, step: str, caption: str) -> Image.Image:
    """Add a banner at the top with a step number + short caption."""
    w, h = img.size
    out = Image.new("RGB", (w, h + CAPTION_H), color=(15, 23, 42))  # slate-900
    out.paste(img, (0, CAPTION_H))
    draw = ImageDraw.Draw(out)
    step_font = _font(20)
    cap_font = _font(18)

    # Step pill on the left
    pill_text = step
    bbox = draw.textbbox((0, 0), pill_text, font=step_font)
    pw = bbox[2] - bbox[0]
    px, py = 16, (CAPTION_H - (bbox[3] - bbox[1])) // 2 - 2
    draw.rounded_rectangle(
        (px - 8, py - 6, px + pw + 8, py + (bbox[3] - bbox[1]) + 6),
        radius=10, fill=(34, 211, 238),  # cyan-400
    )
    draw.text((px, py - 2), pill_text, font=step_font, fill=(15, 23, 42))

    # Caption to the right of the pill
    cx = px + pw + 26
    cy = (CAPTION_H - 18) // 2 - 2
    draw.text((cx, cy), caption, font=cap_font, fill=(248, 250, 252))
    return out


def shoot(page, step: str, caption: str, save_path: Path) -> None:
    raw = page.screenshot(full_page=False)
    img = Image.open(BytesIO(raw)).convert("RGB")
    framed = add_caption(img, step, caption)
    framed.save(save_path, format="PNG", optimize=True)


# ---------------------------------------------------------------------------
# Walk through Studio and capture frames
# ---------------------------------------------------------------------------


def walk_and_capture(base_url: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    frames: list[tuple[Path, str, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
        )
        page = ctx.new_page()

        # 1. Login (pre-filled)
        page.goto(f"{base_url}/login", wait_until="networkidle")
        page.wait_for_selector("text=Sentinel Studio")
        page.fill('input[type="email"]', ADMIN_EMAIL)
        page.fill('input[type="password"]', "************")
        f = FRAMES_DIR / "f01-login.png"
        shoot(page, "1 / 5", "Sign in. Cookie session, no SaaS.", f)
        frames.append((f, "1 / 5", ""))

        # Real sign-in
        page.fill('input[type="password"]', ADMIN_PW)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda u: "/projects" in u, timeout=10000)
        page.wait_for_selector("text=Marketing site", timeout=5000)
        f = FRAMES_DIR / "f02-projects.png"
        shoot(page, "2 / 5", "Projects. Each one is a named app + base URL.", f)
        frames.append((f, "2 / 5", ""))

        # 3. Project detail
        page.click("text=Marketing site")
        page.wait_for_selector("text=Recent runs", timeout=5000)
        page.wait_for_timeout(400)
        f = FRAMES_DIR / "f03-project.png"
        shoot(page, "3 / 5", "Run history, per-project config, one-click trigger.", f)
        frames.append((f, "3 / 5", ""))

        # 4. Run detail (failed run with scenarios + a11y)
        page.locator("tbody tr").first.locator("a").first.click()
        page.wait_for_selector("text=Scenarios", timeout=5000)
        page.wait_for_timeout(400)
        # Scroll a bit so the a11y violations are visible
        page.evaluate("window.scrollTo(0, 250)")
        page.wait_for_timeout(200)
        f = FRAMES_DIR / "f04-run-detail.png"
        shoot(page, "4 / 5", "Run detail: scenarios, step failures, visual diffs, a11y.", f)
        frames.append((f, "4 / 5", ""))

        # 5. Admin users
        page.evaluate("window.scrollTo(0, 0)")
        page.click("text=Users")
        page.wait_for_selector("text=Invite user", timeout=5000)
        page.wait_for_timeout(400)
        f = FRAMES_DIR / "f05-users.png"
        shoot(page, "5 / 5", "Admins manage roles: admin / member / viewer.", f)
        frames.append((f, "5 / 5", ""))

        browser.close()

    return [p for p, _, _ in frames]


def build_gif(frame_paths: list[Path], out: Path) -> None:
    images = [Image.open(p).convert("P", palette=Image.Palette.ADAPTIVE) for p in frame_paths]
    # Per-frame durations: each frame holds, last one holds longer.
    durations = [FRAME_MS] * (len(images) - 1) + [LAST_FRAME_MS]
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"  wrote {out} ({out.stat().st_size // 1024} KB)")


def main():
    print(f"  data dir: {DATA_DIR}")
    seed_db()
    port = free_port()
    proc = start_server(port)
    try:
        frames = walk_and_capture(f"http://127.0.0.1:{port}")
        for f in frames:
            print(f"    captured {f.name}")
        build_gif(frames, OUT)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
