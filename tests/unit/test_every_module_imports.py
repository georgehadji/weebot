"""Every module under weebot/ and cli/ must be importable.

Not a style check. A module that cannot be imported is code that has never run
and cannot run, and nothing else in this repository notices: ruff's CI selector
(F821, E9) sees `asyncio.coroutine` as an ordinary attribute access, not an
undefined name, and no test imported the module, so every gate passed on a file
that raises at import time.

Two were found this way, out of 807 scanned:

  weebot.core.alerting
      `AsyncAlertHandler = Callable[[Alert], asyncio.coroutine]` at module
      level. `asyncio.coroutine` was removed in Python 3.11; this project and
      its CI both run 3.12. The whole alerting subsystem -- AlertManager,
      severities, grouping, deduplication, handler dispatch -- could not load.
      An alerting system that cannot be imported is the purest case of the
      failure this audit keeps finding: the thing meant to tell you something
      is wrong is itself broken, and silent.

  weebot.application.services.strategy_adaptation
      `from weebot.workflow_planner import ...`, a path that has not existed
      since the Clean Architecture refactor moved it to
      weebot.application.flows.workflow_planner. Nobody noticed because nobody
      imports strategy_adaptation either.

Both had zero importers, which is why they stayed broken and why fixing them
is safe. The ceiling here is zero: unlike the debt ratchets, there is no
legitimate un-importable module to grandfather.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import warnings
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# Vendored trees and benchmark harnesses with their own dependency sets.
_SKIP_PARTS = {"GitNexus-main", "osworld", "node_modules", "__pycache__"}


def _modules() -> list[str]:
    names = []
    for root in ("weebot", "cli"):
        for f in sorted((_ROOT / root).rglob("*.py")):
            rel = f.relative_to(_ROOT)
            if _SKIP_PARTS & set(rel.parts) or f.name == "__main__.py":
                continue
            mod = ".".join(rel.with_suffix("").parts)
            names.append(mod[: -len(".__init__")] if mod.endswith(".__init__") else mod)
    return names


@pytest.mark.parametrize("module", _modules())
def test_the_module_can_be_imported(module):
    warnings.simplefilter("ignore")
    try:
        # Import side effects belong to the module, not to this test's output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            importlib.import_module(module)
    except ImportError as exc:
        # A genuinely optional third-party dependency is not this gate's
        # business. A missing FIRST-PARTY module is -- that is a stale path,
        # which is exactly what this found in strategy_adaptation.
        missing = getattr(exc, "name", "") or ""
        if missing.startswith(("weebot", "cli")):
            pytest.fail(f"{module} imports {missing}, which does not exist")
        pytest.skip(f"optional dependency not installed: {missing or exc}")
    except Exception as exc:
        pytest.fail(f"{module} raises at import time: {type(exc).__name__}: {exc}")
