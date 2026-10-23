"""F13: run_mcp.main() must run the key check on a settings instance.

`run_mcp.py:87` used to call `WeebotSettings.validate_at_least_one_key()` on
the class, which raised TypeError that `except ValueError` did not catch.
Fixed in W1.1; see tasks/icm_fix_plan.md. Unlike tests/unit/interfaces/
test_run_mcp.py, this test does not patch the check away.
"""

import sys

import pytest


class _ReachedBuildServer(Exception):
    """Raised by the patched _build_server: the key check passed."""


def test_main_passes_key_check_when_a_key_is_set(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    import run_mcp

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(sys, "argv", ["run_mcp.py"])

    def _stop():
        raise _ReachedBuildServer

    monkeypatch.setattr(run_mcp, "_build_server", _stop)

    with pytest.raises(_ReachedBuildServer):
        run_mcp.main()


def test_main_exits_cleanly_without_a_key(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    import run_mcp

    monkeypatch.setattr(sys, "argv", ["run_mcp.py"])
    with pytest.raises(SystemExit) as exc:
        run_mcp.main()
    assert exc.value.code == 1
