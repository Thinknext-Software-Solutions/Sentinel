"""Capture README screenshots of Sentinel Studio.

Spins up a Studio server with a seeded admin + member + sample project +
sample run (data inserted directly into the DB so we can show a finished
run without a real browser session).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent / "studio-screenshots"
OUT.mkdir(parents=True, exist_ok=True)

DATA_DIR = tempfile.mkdtemp(prefix="sentinel-screenshots-")
ADMIN_EMAIL = "admin@studio.example"
ADMIN_PW = "AdminPass123!"


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
    """Insert a project + a finished run + scenarios + a11y violations
    directly via SQLAlchemy so the screenshots show realistic content."""
    os.environ["SENTINEL_SERVER_HOME"] = DATA_DIR
    # IMPORTANT: clear cached engine so it picks up the new path
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
        # Member user
        db.add(User(
            email="member@studio.example",
            name="Aditi Rao",
            hashed_password=hash_password("MemberPass1!"),
            role="member",
        ))
        # Project
        proj = Project(
            slug="marketing-site",
            name="Marketing site",
            base_url="https://example.com",
            description="Public marketing site. Tracks landing page, pricing, and signup.",
            llm_provider="claude_code",
            llm_model="claude-opus-4-7",
            explore_links=True,
            created_by_user_id=admin.id,
        )
        db.add(proj)
        db.flush()

        # Insert older passing runs first so the failed run ends up at
        # the top of the (created_at desc) list when we screenshot.
        from datetime import timedelta
        base = datetime.now(timezone.utc)
        for i in range(3, 0, -1):
            db.add(Run(
                project_id=proj.id,
                triggered_by_user_id=admin.id,
                target_url="https://example.com",
                status="passed",
                created_at=base - timedelta(hours=i * 6),
                started_at=base - timedelta(hours=i * 6),
                finished_at=base - timedelta(hours=i * 6),
                cost_usd=0.03,
                input_tokens=4980, output_tokens=812,
                scenarios_total=4, scenarios_passed=4,
                visual_diffs_count=0, a11y_violations_count=0,
            ))
        db.flush()

        # Most recent run: failed, with scenario detail + a11y violations.
        now = base
        run = Run(
            project_id=proj.id,
            triggered_by_user_id=admin.id,
            target_url="https://example.com",
            status="failed",
            created_at=now,
            started_at=now,
            finished_at=now,
            cost_usd=0.04,
            input_tokens=5210,
            output_tokens=980,
            scenarios_total=4,
            scenarios_passed=3,
            visual_diffs_count=1,
            a11y_violations_count=2,
        )
        db.add(run)
        db.flush()

        for idx, (name, passed, dur, failure) in enumerate([
            ("Homepage hero and trust bar render", True, 1.42, None),
            ("Sign-up CTA routes to /login?mode=signup", True, 1.83, None),
            ("Pricing card surfaces all three plans", True, 2.10, None),
            ("Newsletter form posts to /api/subscribe",
             False, 4.12,
             ("Submit button is enabled with blank email",
              "Locator.click: Timeout 5000ms exceeded.\n"
              "Call log: waiting for locator('form button[type=\"submit\"]') to be enabled")),
        ]):
            scen = ScenarioRun(
                run_id=run.id,
                name=name,
                description="",
                passed=passed,
                duration_seconds=dur,
                order_index=idx,
            )
            db.add(scen)
            db.flush()
            if failure:
                db.add(StepFailure(
                    scenario_id=scen.id,
                    step_index=3,
                    step_description=failure[0],
                    message=failure[1],
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

    print(f"  seeded data at {DATA_DIR}")


def start_server(port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["SENTINEL_SERVER_HOME"] = DATA_DIR
    proc = subprocess.Popen(
        [sys.executable, "-m", "sentinel.cli", "server", "up", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    wait_http(f"http://127.0.0.1:{port}/api/health")
    return proc


def main():
    print(f"  data dir: {DATA_DIR}")
    seed_db()
    port = free_port()
    proc = start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                       device_scale_factor=2)
            page = ctx.new_page()

            # 1. LOGIN
            page.goto(f"{base}/login", wait_until="networkidle")
            page.wait_for_selector("text=Sentinel Studio")
            # pre-fill so the screenshot is interesting
            page.fill('input[type="email"]', ADMIN_EMAIL)
            page.fill('input[type="password"]', "admin-pass-redacted")
            page.screenshot(path=str(OUT / "01-login.png"), full_page=False)
            print(f"  wrote {OUT / '01-login.png'}")

            # Actually sign in
            page.fill('input[type="password"]', ADMIN_PW)
            page.click('button[type="submit"]')
            page.wait_for_url(lambda u: "/projects" in u, timeout=10000)

            # 2. PROJECTS LIST
            page.wait_for_selector("text=Marketing site", timeout=5000)
            page.screenshot(path=str(OUT / "02-projects.png"), full_page=False)
            print(f"  wrote {OUT / '02-projects.png'}")

            # 3. PROJECT DETAIL (runs table)
            page.click("text=Marketing site")
            page.wait_for_selector("text=Recent runs", timeout=5000)
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "03-project-detail.png"), full_page=False)
            print(f"  wrote {OUT / '03-project-detail.png'}")

            # 4. RUN DETAIL
            # Click first row (the failed run)
            page.locator("tbody tr").first.locator("a").first.click()
            page.wait_for_selector("text=Scenarios", timeout=5000)
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "04-run-detail.png"), full_page=True)
            print(f"  wrote {OUT / '04-run-detail.png'}")

            # 5. ADMIN USERS
            page.click("text=Users")
            page.wait_for_selector("text=Invite user", timeout=5000)
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "05-admin-users.png"), full_page=False)
            print(f"  wrote {OUT / '05-admin-users.png'}")

            browser.close()

        print("  all screenshots captured.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
