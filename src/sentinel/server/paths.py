"""Resolution of on-disk locations for Studio state."""

from __future__ import annotations

import os
from pathlib import Path


def server_home() -> Path:
    """Where Studio keeps its state (SQLite DB, secret key, run workspaces).

    Honors $SENTINEL_SERVER_HOME, else $XDG_DATA_HOME/sentinel, else
    ~/.local/share/sentinel. The user config (~/.config/sentinel) is
    intentionally separate -- credentials there, data here.
    """
    explicit = os.environ.get("SENTINEL_SERVER_HOME")
    if explicit:
        return Path(explicit)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "sentinel"
    return Path.home() / ".local" / "share" / "sentinel"


def db_path() -> Path:
    return server_home() / "studio.db"


def secret_key_path() -> Path:
    return server_home() / "secret_key"


def runs_dir() -> Path:
    """Each run gets a subdir for screenshots, baselines, diffs."""
    return server_home() / "runs"


def ensure_dirs() -> None:
    server_home().mkdir(parents=True, exist_ok=True)
    runs_dir().mkdir(parents=True, exist_ok=True)
