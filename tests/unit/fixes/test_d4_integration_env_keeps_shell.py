"""D4 live check: the integration conftest must not wipe a variable set in the shell.

``tests/integration/conftest.py`` copied ``.env`` into ``os.environ`` with
overwrite, so ``WEEBOT_PG_DSN=`` (empty) in ``.env`` erased the DSN the shell
set and every Postgres integration test skipped.
"""

from __future__ import annotations

import os

from tests.integration.conftest import load_env_file


def test_a_value_set_in_the_shell_wins_over_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("WEEBOT_PG_DSN=\nD4_ONLY_IN_FILE=\"from-file\"\n", encoding="utf-8")
    monkeypatch.setenv("WEEBOT_PG_DSN", "postgresql://shell@127.0.0.1/db")
    monkeypatch.delenv("D4_ONLY_IN_FILE", raising=False)

    load_env_file(env)

    assert os.environ["WEEBOT_PG_DSN"] == "postgresql://shell@127.0.0.1/db"
    assert os.environ["D4_ONLY_IN_FILE"] == "from-file"
    monkeypatch.delenv("D4_ONLY_IN_FILE")
