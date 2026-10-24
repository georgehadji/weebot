"""WORKSPACE_ROOT is always absolute, whatever WEEBOT_WORKSPACE holds.

A `.env` with `WEEBOT_WORKSPACE=.` made the root relative, so every check of "is this
absolute path inside the workspace" silently stopped matching, and the filesystem
policy tests failed only when `.env` was loaded first (tests/integration/conftest.py).
Each case runs in a subprocess: the value is read at import time.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_PRINT_ROOT = "from weebot.config.settings import WORKSPACE_ROOT as r; print(r)"


def _root(value: str | None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "WEEBOT_WORKSPACE"}
    if value is not None:
        env["WEEBOT_WORKSPACE"] = value
    out = subprocess.run(
        [sys.executable, "-c", _PRINT_ROOT], capture_output=True, text=True, env=env, check=True
    )
    return out.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("value", [None, "", ".", "tests/.."])
def test_the_root_is_absolute(value):
    assert os.path.isabs(_root(value))
