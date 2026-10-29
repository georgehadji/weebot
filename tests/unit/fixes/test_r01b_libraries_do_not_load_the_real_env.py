"""Under pytest, a library's ``load_dotenv()`` must not copy the repo's ``.env`` into the run.

``browser_use/agent/service.py`` calls ``load_dotenv()`` at import. Any test that builds the
tool class map imports it, and from then on every later test saw the developer's real
settings: with ``WEEBOT_FREE_ROLES`` in ``.env``, ``test_w61_model_ssot`` got a free-tier
model for the coder role. weebot's own loaders (``cli/main.py``, ``interfaces/web/main.py``)
already skip under pytest; ``tests/conftest.py`` now makes the library call inert too.
"""

from __future__ import annotations

import os


def test_load_dotenv_is_inert_under_pytest(tmp_path, monkeypatch):
    import dotenv

    env = tmp_path / ".env"
    env.write_text("R01B_LEAK_PROBE=1\n", encoding="utf-8")
    monkeypatch.delenv("R01B_LEAK_PROBE", raising=False)
    dotenv.load_dotenv(env)
    assert "R01B_LEAK_PROBE" not in os.environ


def test_browser_use_got_the_inert_one():
    import dotenv
    from browser_use.agent import service

    assert service.load_dotenv is dotenv.load_dotenv
