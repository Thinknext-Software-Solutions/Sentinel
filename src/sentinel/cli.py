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
def run(target_url: str, workspace: Path, config_dir: Path | None) -> None:
    """Run the full pipeline on a URL: explore, plan, test, report.

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
    click.echo()

    try:
        report = run_sentinel(
            target_url=target_url,
            config=config,
            llm=llm,
            workspace_dir=workspace.resolve(),
        )
    except CascadeError as exc:
        echo_error(exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style(f"  FAILED: {type(exc).__name__}: {exc}", fg="red"), err=True)
        sys.exit(1)

    _render_report(report)
    sys.exit(0 if report.passed else 1)


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
