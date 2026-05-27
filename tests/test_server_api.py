"""End-to-end smoke tests for Sentinel Studio HTTP API.

Uses TestClient + isolated SQLite DB per test session, no network.
The Sentinel runner is NOT exercised here (it would launch a real
browser). We verify the request/response contracts only.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def server_home(tmp_path_factory):
    """Isolated data dir for the whole test module."""
    tmp = tmp_path_factory.mktemp("studio")
    os.environ["SENTINEL_SERVER_HOME"] = str(tmp)
    # Reset the cached engine so it picks up the new DB path
    from sentinel.server import db as db_mod
    db_mod.reset_for_tests()
    yield tmp
    db_mod.reset_for_tests()


@pytest.fixture(scope="module")
def client(server_home):
    from sentinel.server.app import create_app
    from sentinel.server.bootstrap import init_database, create_or_update_admin

    init_database()
    create_or_update_admin("admin@test.example", "AdminPass1!", name="Admin")
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_session(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@test.example", "password": "AdminPass1!"},
    )
    assert r.status_code == 200, r.text
    return r.cookies


class TestAuth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_login_rejects_bad_password(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "admin@test.example", "password": "wrongwrong"},
        )
        assert r.status_code == 401

    def test_login_succeeds(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "admin@test.example", "password": "AdminPass1!"},
        )
        assert r.status_code == 200
        assert r.json()["email"] == "admin@test.example"
        assert "sentinel_session" in r.cookies

    def test_me_requires_session(self, client):
        # New TestClient call without cookies should 401
        from fastapi.testclient import TestClient
        from sentinel.server.app import create_app
        with TestClient(create_app()) as fresh:
            r = fresh.get("/api/auth/me")
            assert r.status_code == 401

    def test_me_returns_user_with_session(self, client, admin_session):
        r = client.get("/api/auth/me", cookies=admin_session)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_logout_clears_session(self, client, admin_session):
        r = client.post("/api/auth/logout", cookies=admin_session)
        assert r.status_code == 204


class TestUsers:
    def test_admin_can_create_user(self, client, admin_session):
        r = client.post(
            "/api/users",
            cookies=admin_session,
            json={
                "email": "member@test.example",
                "name": "Member",
                "password": "MemberPass1!",
                "role": "member",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "member"

    def test_non_admin_cannot_create_user(self, client):
        login = client.post(
            "/api/auth/login",
            json={"email": "member@test.example", "password": "MemberPass1!"},
        )
        assert login.status_code == 200
        cookies = login.cookies
        r = client.post(
            "/api/users",
            cookies=cookies,
            json={
                "email": "x@test.example",
                "password": "XPass1234!",
                "role": "viewer",
            },
        )
        assert r.status_code == 403

    def test_duplicate_email_rejected(self, client, admin_session):
        r = client.post(
            "/api/users",
            cookies=admin_session,
            json={
                "email": "member@test.example",
                "password": "OtherPass1!",
            },
        )
        assert r.status_code == 409

    def test_admin_cannot_demote_last_admin(self, client, admin_session):
        me = client.get("/api/auth/me", cookies=admin_session).json()
        r = client.patch(
            f"/api/users/{me['id']}",
            cookies=admin_session,
            json={"role": "member"},
        )
        assert r.status_code == 400


class TestProjects:
    def test_member_can_create_project(self, client):
        login = client.post(
            "/api/auth/login",
            json={"email": "member@test.example", "password": "MemberPass1!"},
        )
        cookies = login.cookies
        r = client.post(
            "/api/projects",
            cookies=cookies,
            json={
                "slug": "demo",
                "name": "Demo App",
                "base_url": "https://example.com",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["slug"] == "demo"

    def test_anon_cannot_list_projects(self, client):
        from fastapi.testclient import TestClient
        from sentinel.server.app import create_app
        with TestClient(create_app()) as fresh:
            assert fresh.get("/api/projects").status_code == 401

    def test_list_returns_created_project(self, client, admin_session):
        r = client.get("/api/projects", cookies=admin_session)
        assert r.status_code == 200
        slugs = [p["slug"] for p in r.json()]
        assert "demo" in slugs

    def test_duplicate_slug_rejected(self, client, admin_session):
        r = client.post(
            "/api/projects",
            cookies=admin_session,
            json={
                "slug": "demo",
                "name": "Other",
                "base_url": "https://other.com",
            },
        )
        assert r.status_code == 409

    def test_invalid_slug_rejected(self, client, admin_session):
        r = client.post(
            "/api/projects",
            cookies=admin_session,
            json={
                "slug": "Demo App",
                "name": "x",
                "base_url": "https://example.com",
            },
        )
        assert r.status_code == 422


class TestRuns:
    def test_member_can_trigger_run(self, client, admin_session, monkeypatch):
        # Replace enqueue_run with a no-op so the test doesn't launch Playwright.
        from sentinel.server.api import runs as runs_api
        called = {}

        def fake_enqueue(run_id):
            called["run_id"] = run_id

        monkeypatch.setattr(runs_api, "enqueue_run", fake_enqueue)

        projects = client.get("/api/projects", cookies=admin_session).json()
        project_id = next(p["id"] for p in projects if p["slug"] == "demo")
        r = client.post(
            f"/api/projects/{project_id}/runs",
            cookies=admin_session,
            json={},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "queued"
        assert called.get("run_id") == body["id"]

    def test_list_project_runs(self, client, admin_session):
        projects = client.get("/api/projects", cookies=admin_session).json()
        project_id = next(p["id"] for p in projects if p["slug"] == "demo")
        r = client.get(f"/api/projects/{project_id}/runs", cookies=admin_session)
        assert r.status_code == 200
        assert len(r.json()) >= 1
