"""sentinel command-line interface.

Three commands for v0.1.0a1:

  sentinel run <url>    Full pipeline: explore -> plan -> test -> report
  sentinel init         Scaffold sentinel.yaml
  sentinel version      Print version

Credentials are reused from cascade-agent's user config (Sentinel
shares LLM clients with Cascade and Relay so users configure once).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from cascade.error_format import echo_error
from cascade.exceptions import CascadeError
from cascade.llm import build_client_from_credentials
from cascade.user_config import load_user_config, resolve_llm_credentials

from . import __version__
from .agent import run_sentinel
from .api_planner import generate_api_plan_from_spec, generate_api_plan_from_url
from .api_runner import run_api_plan
from .config import DEFAULT_CONFIG_FILENAME, DEFAULT_SENTINEL_YAML, load_config


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        stream=sys.stderr,
    )


@click.group()
@click.version_option(__version__, prog_name="sentinel")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug-level logs.")
def cli(verbose: bool) -> None:
    """Sentinel: AI-driven functional testing agent."""
    _setup_logging(verbose)


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite an existing sentinel.yaml.")
def init(force: bool) -> None:
    """Scaffold sentinel.yaml in the current directory."""
    path = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if path.exists() and not force:
        click.echo(f"  exists  {path.name} (use --force to overwrite)")
        return
    path.write_text(DEFAULT_SENTINEL_YAML)
    click.echo(f"  wrote   {path.name}")
    click.echo()
    click.echo("Sentinel configured. Next steps:")
    click.echo("  1. (One-time) install Chromium: `playwright install chromium`")
    click.echo("  2. Set your LLM: `cascade configure llm anthropic --key ...`")
    click.echo("     (Sentinel reuses Cascade's credentials.)")
    click.echo("  3. Run a smoke test: `sentinel run https://your-app.com`")


@cli.command()
@click.argument("target_url")
@click.option(
    "--workspace",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".sentinel"),
    show_default=True,
    help="Where to write screenshots, baselines, diffs.",
)
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing sentinel.yaml. Defaults to cwd.",
)
@click.option(
    "--no-explore",
    is_flag=True,
    help="Skip multi-page link discovery; only test the landing URL.",
)
def run(target_url: str, workspace: Path, config_dir: Path | None, no_explore: bool) -> None:
    """Run the full web pipeline on a URL: explore, plan, test, report.

    Example:
        sentinel run https://example.com
    """
    try:
        config = load_config(config_dir or Path.cwd())
        user_cfg = load_user_config()
        llm_creds = resolve_llm_credentials(
            user_config=user_cfg,
            provider=config.agent.provider,
            model_override=config.agent.model,
        )
        llm = build_client_from_credentials(llm_creds)
    except CascadeError as exc:
        echo_error(exc)
        sys.exit(1)

    click.echo()
    click.echo(f"==> Sentinel run: {target_url}")
    click.echo(f"    LLM:        {llm.provider_name} / {llm.model}")
    click.echo(f"    Workspace:  {workspace}")
    click.echo(f"    Explore:    {'off' if no_explore else 'on (up to 4 same-origin links)'}")
    click.echo()

    try:
        report = run_sentinel(
            target_url=target_url,
            config=config,
            llm=llm,
            workspace_dir=workspace.resolve(),
            explore_links=not no_explore,
        )
    except CascadeError as exc:
        echo_error(exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style(f"  FAILED: {type(exc).__name__}: {exc}", fg="red"), err=True)
        sys.exit(1)

    _render_report(report)
    sys.exit(0 if report.passed else 1)


# ---------------------------------------------------------------------------
# sentinel api
# ---------------------------------------------------------------------------


@cli.command(name="api")
@click.argument("base_url")
@click.option(
    "--spec",
    type=str,
    default=None,
    help=(
        "Path or URL to an OpenAPI / Swagger spec (JSON or YAML). "
        "If provided, the planner generates scenarios per operation. "
        "If omitted, the planner probes the base URL with conservative "
        "GET requests."
    ),
)
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--header",
    "-H",
    multiple=True,
    help=(
        "Extra header to send with every request (e.g. "
        "-H 'Authorization: Bearer xxx'). Can be repeated."
    ),
)
@click.option(
    "--timeout",
    type=float,
    default=30.0,
    show_default=True,
    help="Per-request HTTP timeout, seconds.",
)
def api_cmd(
    base_url: str,
    spec: str | None,
    config_dir: Path | None,
    header: tuple[str, ...],
    timeout: float,
) -> None:
    """Run API contract tests against BASE_URL.

    With --spec, the planner generates scenarios per OpenAPI operation.
    Without --spec, it probes the URL with a small set of conservative
    GET requests.

    Examples:
        sentinel api https://api.example.com/v1
        sentinel api https://api.example.com/v1 --spec ./openapi.yaml
        sentinel api https://api.example.com/v1 -H "Authorization: Bearer xxx"
    """
    try:
        config = load_config(config_dir or Path.cwd())
        user_cfg = load_user_config()
        llm_creds = resolve_llm_credentials(
            user_config=user_cfg,
            provider=config.agent.provider,
            model_override=config.agent.model,
        )
        llm = build_client_from_credentials(llm_creds)
    except CascadeError as exc:
        echo_error(exc)
        sys.exit(1)

    # Parse -H "Name: value" flags
    extra_headers: dict[str, str] = {}
    for h in header:
        if ":" not in h:
            click.echo(
                click.style(f"  bad --header value (need 'Name: value'): {h!r}", fg="red"),
                err=True,
            )
            sys.exit(1)
        name, value = h.split(":", 1)
        extra_headers[name.strip()] = value.strip()

    click.echo()
    click.echo(f"==> Sentinel API run: {base_url}")
    click.echo(f"    LLM:        {llm.provider_name} / {llm.model}")
    if spec:
        click.echo(f"    Spec:       {spec}")
    if extra_headers:
        masked = {k: ("<redacted>" if "auth" in k.lower() else v) for k, v in extra_headers.items()}
        click.echo(f"    Headers:    {masked}")
    click.echo()

    # Plan
    try:
        if spec:
            spec_dict = _load_spec(spec)
            plan_outcome = generate_api_plan_from_spec(
                base_url=base_url,
                spec=spec_dict,
                llm=llm,
                temperature=config.agent.temperature,
            )
        else:
            plan_outcome = generate_api_plan_from_url(
                base_url=base_url,
                llm=llm,
                temperature=config.agent.temperature,
            )
    except CascadeError as exc:
        echo_error(exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style(f"  PLAN FAILED: {type(exc).__name__}: {exc}", fg="red"), err=True)
        sys.exit(1)

    click.echo(f"  plan: {len(plan_outcome.plan.scenarios)} scenario(s)")
    click.echo()

    # Run
    report = run_api_plan(
        plan=plan_outcome.plan,
        extra_headers=extra_headers,
        timeout_seconds=timeout,
    )
    report.total_input_tokens = plan_outcome.usage.input_tokens
    report.total_output_tokens = plan_outcome.usage.output_tokens
    report.total_llm_cost_usd = plan_outcome.usage.estimated_cost_usd

    _render_api_report(report)
    sys.exit(0 if report.passed else 1)


def _load_spec(spec_arg: str) -> dict:
    """Load an OpenAPI spec from a URL or local file. JSON or YAML."""
    import json as _json

    raw: str
    if spec_arg.startswith(("http://", "https://")):
        try:
            import httpx  # type: ignore
        except ImportError as exc:
            raise CascadeError("httpx not installed") from exc
        r = httpx.get(spec_arg, timeout=15.0)
        r.raise_for_status()
        raw = r.text
    else:
        path = Path(spec_arg)
        if not path.exists():
            raise CascadeError(f"spec file not found: {spec_arg}")
        raw = path.read_text()

    # Try JSON first, fall back to YAML
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        pass
    try:
        import yaml
        return yaml.safe_load(raw)
    except Exception as exc:
        raise CascadeError(
            f"could not parse {spec_arg} as JSON or YAML",
            hint=str(exc),
        ) from exc


def _render_api_report(report) -> None:
    """Pretty-print an APITestReport."""
    icon = click.style("✓", fg="green") if report.passed else click.style("✗", fg="red")
    click.echo(f"  {icon}  {report.summary_line()}")
    click.echo()

    for sr in report.scenario_runs:
        status_icon = click.style("✓", fg="green") if sr.passed else click.style("✗", fg="red")
        status_text = f"{sr.status_code}" if sr.status_code else "(no response)"
        click.echo(
            f"  {status_icon}  {sr.scenario}  "
            f"({sr.request_method} {sr.request_url} → {status_text}, "
            f"{sr.response_time_ms:.0f}ms)"
        )
        if sr.request_error:
            click.echo(click.style(f"      request error: {sr.request_error}", fg="red"))
        for f in sr.findings:
            click.echo(click.style(f"      [{f.severity}] {f.assertion_description}", fg="red"))
            click.echo(click.style(f"      {f.message}", fg="red"))
            if f.expected is not None:
                click.echo(f"      expected: {f.expected}")
            if f.actual is not None:
                click.echo(f"      actual:   {f.actual}")
    click.echo()
    click.echo(
        f"  cost:    ${report.total_llm_cost_usd:.2f} "
        f"({report.total_input_tokens:,} in / {report.total_output_tokens:,} out tokens)"
    )


def _render_report(report) -> None:
    """Pretty-print a SentinelReport to stdout."""
    icon = click.style("✓", fg="green") if report.passed else click.style("✗", fg="red")
    click.echo(f"  {icon}  {report.summary_line()}")
    click.echo()

    # Scenarios
    for sr in report.scenario_runs:
        scenario_icon = click.style("✓", fg="green") if sr.passed else click.style("✗", fg="red")
        click.echo(
            f"  {scenario_icon}  {sr.scenario}  ({sr.duration_seconds:.2f}s)"
        )
        for failure in sr.failures:
            click.echo(
                click.style(f"      step {failure.step_index}: {failure.step_description}", fg="red")
            )
            click.echo(click.style(f"      {failure.message}", fg="red"))
            if failure.screenshot_path:
                click.echo(f"      screenshot: {failure.screenshot_path}")

    # Visual diffs
    if report.visual_diffs:
        click.echo()
        click.echo(click.style("  Visual regressions:", fg="yellow"))
        for d in report.visual_diffs:
            click.echo(
                f"    {d.name}: {d.percent_changed:.2f}% changed "
                f"(threshold {d.threshold:.2f}%)"
            )
            click.echo(f"      baseline: {d.baseline_path}")
            click.echo(f"      current:  {d.current_path}")
            click.echo(f"      diff:     {d.diff_path}")

    # A11y violations
    if report.a11y_violations:
        click.echo()
        click.echo(click.style("  Accessibility violations:", fg="yellow"))
        for v in report.a11y_violations:
            color = "red" if v.impact in ("critical", "serious") else "yellow"
            click.echo(
                click.style(f"    [{v.impact}] {v.rule_id}", fg=color)
                + f": {v.description[:80]}"
            )
            if v.sample_selector:
                click.echo(f"      sample: {v.sample_selector}")
            click.echo(f"      ({v.nodes_affected} node(s) affected)")

    click.echo()
    click.echo(
        f"  cost:    ${report.total_llm_cost_usd:.2f} "
        f"({report.total_input_tokens:,} in / {report.total_output_tokens:,} out tokens)"
    )


@cli.command()
def version() -> None:
    """Print the Sentinel version."""
    click.echo(f"sentinel-agent {__version__}")


def main() -> None:
    """Entry point referenced from pyproject.toml [project.scripts]."""
    cli()


if __name__ == "__main__":
    main()
