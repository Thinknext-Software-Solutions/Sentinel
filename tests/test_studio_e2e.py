"""End-to-end test of Sentinel Studio: real uvicorn + real Chromium.

Covers the canonical first-time flow:
  1. Admin signs in via the React login page.
  2. Empty projects list shows the "Create your first project" CTA.
  3. Admin creates a project via the form.
  4. Project appears in the list and on the detail page.
  5. Admin invites a member via /admin/users.
  6. Member signs in and sees the project (read-only triggers visible).

We do NOT trigger a real Sentinel run here -- that would launch a
second nested Chromium inside the runner thread, which Playwright dev
servers don't love. The run-trigger path is covered by the API tests.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(url: str, timeout: float = 15.0) -> None:
    import httpx
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


@contextmanager
def _studio_server(tmp_data_dir: Path, admin_email: str, admin_password: str):
    """Start uvicorn in a subprocess with an isolated data dir."""
    env = dict(os.environ)
    env["SENTINEL_SERVER_HOME"] = str(tmp_data_dir)

    init = subprocess.run(
        [
            sys.executable, "-m", "sentinel.cli", "server", "init",
            "--email", admin_email,
            "--password", admin_password,
            "--name", "E2E Admin",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert init.returncode == 0, init.stderr

    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "sentinel.cli", "server", "up",
            "--port", str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_for_http(f"{base}/api/health")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    static_dir = (
        Path(__file__).resolve().parents[1] / "src" / "sentinel" / "server" / "static"
    )
    if not (static_dir / "index.html").is_file():
        pytest.skip(
            "Frontend not built. Run `npm --prefix web run build:install` to enable."
        )
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")

    data_dir = tmp_path_factory.mktemp("studio-e2e")
    admin_email = "admin@studio.example"
    admin_password = "AdminPass123!"
    with _studio_server(data_dir, admin_email, admin_password) as base:
        yield {
            "base": base,
            "admin_email": admin_email,
            "admin_password": admin_password,
        }


class TestStudioE2E:
    def test_admin_login_create_project_invite_member(self, studio, tmp_path):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()

            # 1. Land on root, get redirected to /login
            page.goto(f"{studio['base']}/", wait_until="domcontentloaded")
            page.wait_for_selector("text=Sentinel Studio", timeout=10000)

            # 2. Sign in as admin
            page.fill('input[type="email"]', studio["admin_email"])
            page.fill('input[type="password"]', studio["admin_password"])
            page.click('button[type="submit"]')

            # 3. Land on projects page (empty state)
            page.wait_for_url(lambda url: "/projects" in url, timeout=10000)
            # Wait for the projects query to settle so we see either the
            # empty state OR the list (in this test it must be the empty
            # state since the DB is fresh).
            page.wait_for_selector("text=No projects yet", timeout=10000)

            # 4. Create a project
            page.click("text=Create your first project")
            page.fill("#proj-slug", "demo-app")
            page.fill("#proj-name", "Demo App")
            page.fill("#proj-url", "https://example.com")
            page.fill("#proj-desc", "End-to-end test project")
            page.click('button:has-text("Create project")')

            # 5. Project appears in the list
            page.wait_for_selector("text=Demo App", timeout=5000)
            assert page.locator("text=demo-app").count() > 0

            # 6. Click into project detail
            page.click("text=Demo App")
            page.wait_for_selector("text=Recent runs", timeout=5000)
            assert page.locator("text=https://example.com").count() > 0
            assert page.locator("text=Configuration").count() > 0

            # 7. Edit configuration
            page.click('button:has-text("Edit")')
            page.fill(
                "textarea",
                "version: 1\nagent:\n  provider: claude_code\n",
            )
            page.click('button:has-text("Save changes")')
            page.wait_for_selector("text=provider: claude_code", timeout=5000)

            # 8. Go to admin users page
            page.click("text=Users")
            page.wait_for_selector("text=Invite user", timeout=5000)
            page.click('button:has-text("Invite user")')
            page.fill('input[type="email"]', "member@studio.example")
            page.fill('input[type="password"]', "MemberPass1!")
            page.click('button:has-text("Create user")')
            page.wait_for_selector("text=member@studio.example", timeout=5000)

            # 9. Sign out
            page.click('button:has-text("Sign out")')
            page.wait_for_url(lambda url: "/login" in url, timeout=5000)

            # 10. Sign in as the member
            page.fill('input[type="email"]', "member@studio.example")
            page.fill('input[type="password"]', "MemberPass1!")
            page.click('button[type="submit"]')

            # Wait for sign-in to complete (any post-login URL)
            page.wait_for_url(
                lambda url: "/login" not in url,
                timeout=10000,
            )
            # Navigate explicitly to /projects (member should see it)
            page.goto(f"{studio['base']}/projects")
            page.wait_for_selector("text=Demo App", timeout=10000)

            # Member does NOT see the Users nav item
            assert page.locator('nav >> text=Users').count() == 0

            browser.close()
