"""Pytest configuration — load .env for real-API integration tests."""

from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config) -> None:
    """Load .env into os.environ before collection, for live runs only (WEEBOT_TEST_LIVE=1).

    Real-API tests then read keys with os.getenv(). It used to load on every run that
    collected this folder, which put the developer's .env (free-provider roles, keys) into
    every unit test of the run.
    """
    if os.environ.get("WEEBOT_TEST_LIVE", "").strip().lower() not in ("1", "true", "yes"):
        return
    load_env_file(Path(__file__).resolve().parent.parent.parent / ".env")


def load_env_file(env_path: Path) -> None:
    """Copy *env_path* into os.environ; a variable already set in the shell wins."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
