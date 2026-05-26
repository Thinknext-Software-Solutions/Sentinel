"""Light CLI tests using click's CliRunner."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from sentinel import __version__
from sentinel.cli import cli
from sentinel.config import DEFAULT_CONFIG_FILENAME


def test_version_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_commands():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "init" in result.output


def test_init_scaffolds_sentinel_yaml(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        cfg = Path.cwd() / DEFAULT_CONFIG_FILENAME
        assert cfg.exists()
        content = cfg.read_text()
        assert "version: 1" in content
        assert "headless" in content


def test_init_skips_existing_without_force(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(DEFAULT_CONFIG_FILENAME).write_text("existing\n")
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "exists" in result.output
        assert Path(DEFAULT_CONFIG_FILENAME).read_text() == "existing\n"


def test_init_force_overwrites(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(DEFAULT_CONFIG_FILENAME).write_text("existing\n")
        result = runner.invoke(cli, ["init", "--force"])
        assert result.exit_code == 0
        assert "version: 1" in Path(DEFAULT_CONFIG_FILENAME).read_text()
