"""Pytest configuration — load .env for real-API integration tests."""
from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config) -> None:
    """Load .env into os.environ before any test collection.

    This runs before the test module's _load_dotenv(), so real-API
    tests can access keys via os.getenv() without race conditions.
    """
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
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
            os.environ[key] = value
