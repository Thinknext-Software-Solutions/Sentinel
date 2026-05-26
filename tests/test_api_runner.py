"""Tests for sentinel.api_runner."""

from __future__ import annotations

import httpx

from sentinel.api_runner import run_api_plan
from sentinel.api_schemas import APIAssertion, APIRequest, APIScenario, APITestPlan


def mock_client_factory(handler):
    """Return a class that mimics httpx.Client but uses MockTransport.

    Captures the REAL httpx.Client at definition time so we don't
    recurse into the patched version when constructing the underlying
    client.
    """
    real_client_cls = httpx.Client

    class _PatchedClient:
        def __init__(self, *args, **kwargs):
            self._kwargs = {
                k: v for k, v in kwargs.items() if k in ("timeout", "follow_redirects")
            }

        def __enter__(self):
            self._client = real_client_cls(
                transport=httpx.MockTransport(handler), **self._kwargs
            )
            return self._client

        def __exit__(self, *args):
            self._client.close()

    return _PatchedClient


def make_plan(scenarios):
    return APITestPlan(
        target_base_url="https://api.example.com",
        summary="x" * 12,
        scenarios=scenarios,
    )


class TestRunAPIPlan:
    def test_all_scenarios_pass(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"})

        monkeypatch.setattr(httpx, "Client", mock_client_factory(handler))

        plan = make_plan(
            [
                APIScenario(
                    name="s1",
                    description="d" * 12,
                    request=APIRequest(method="GET", path="/x"),
                    assertions=[
                        APIAssertion(type="status", description="200", expected_status=200)
                    ],
                ),
                APIScenario(
                    name="s2",
                    description="d" * 12,
                    request=APIRequest(method="GET", path="/y"),
                    assertions=[
                        APIAssertion(type="status", description="200", expected_status=200)
                    ],
                ),
            ]
        )

        report = run_api_plan(plan=plan)
        assert report.passed is True
        assert len(report.scenario_runs) == 2
        assert all(s.status_code == 200 for s in report.scenario_runs)

    def test_one_failure_in_one_scenario(self, monkeypatch):
        responses = iter([200, 500])

        def handler(request: httpx.Request) -> httpx.Response:
            code = next(responses)
            return httpx.Response(code, json={})

        monkeypatch.setattr(httpx, "Client", mock_client_factory(handler))

        plan = make_plan(
            [
                APIScenario(
                    name="ok",
                    description="d" * 12,
                    request=APIRequest(method="GET", path="/a"),
                    assertions=[
                        APIAssertion(type="status", description="200", expected_status=200)
                    ],
                ),
                APIScenario(
                    name="boom",
                    description="d" * 12,
                    request=APIRequest(method="GET", path="/b"),
                    assertions=[
                        APIAssertion(type="status", description="200", expected_status=200)
                    ],
                ),
            ]
        )

        report = run_api_plan(plan=plan)
        assert report.passed is False
        assert report.scenario_runs[0].passed is True
        assert report.scenario_runs[1].passed is False
        assert report.scenario_runs[1].status_code == 500
        assert len(report.scenario_runs[1].findings) == 1

    def test_extra_headers_applied(self, monkeypatch):
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(dict(request.headers))
            return httpx.Response(200)

        monkeypatch.setattr(httpx, "Client", mock_client_factory(handler))

        plan = make_plan(
            [
                APIScenario(
                    name="auth",
                    description="d" * 12,
                    request=APIRequest(method="GET", path="/private"),
                    assertions=[
                        APIAssertion(type="status", description="200", expected_status=200)
                    ],
                ),
            ]
        )

        run_api_plan(plan=plan, extra_headers={"Authorization": "Bearer xyz"})
        assert seen_headers.get("authorization") == "Bearer xyz"
