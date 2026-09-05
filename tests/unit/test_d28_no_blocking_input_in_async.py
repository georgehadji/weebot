"""D28 — `input()` inside `async def` stops the whole event loop.

`input()` blocks the calling thread until the user presses return. Called from a
coroutine that is the event loop's thread, so nothing else in the process runs
for as long as the prompt is on screen: no timer fires, no socket is read, no
WebSocket keepalive is sent, no cancellation is delivered. A CLI prompt is
*meant* to wait for a person, but only that one task should wait; here the loop
waits with it, and any task sharing it stalls.

Two tests, because the defect has two shapes.

The behavioural one drives real code -- `console_approval_callback` -- against a
`input` that takes real wall-clock time, and measures whether a concurrently
running task made progress. That is the property, stated directly: the loop
keeps turning.

The static one is a gate rather than a probe. The three sites found here were
found by grep, and grep is not run on anybody's behalf; nothing stopped a fourth
being added. It walks every `async def` in `weebot/` and `cli/` and fails on a
bare `input()` in any of them.

The gate's limit, stated rather than discovered later: it attributes a call to
its *nearest* enclosing function. A synchronous helper that calls `input()` and
is awaited from a coroutine blocks the loop just as hard and is not caught --
finding that needs a call graph, not a syntax tree.
"""

from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

import pytest

from weebot.core.approval import ApprovalDecision, ApprovalRequest, console_approval_callback
from weebot.core.bash_guard import RiskLevel

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES = ("weebot", "cli")

# The fake prompt blocks for this long. Long enough that a blocked loop is
# unambiguous, short enough to keep the suite quick.
BLOCK_FOR = 0.4
# A loop that is turning ticks far more often than this; a blocked one ticks
# once or not at all.
MIN_TICKS = 3


class _Ticker:
    """Counts how many times the event loop got a turn."""

    def __init__(self) -> None:
        self.ticks = 0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(0.01)
            self.ticks += 1

    async def __aenter__(self) -> _Ticker:
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)  # let it reach its first await
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._task is not None
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


def _request() -> ApprovalRequest:
    return ApprovalRequest(
        command="echo hi",
        risk_level=RiskLevel.SUSPICIOUS,
        checks=[],
        session_id="s1",
    )


async def test_console_approval_does_not_freeze_the_event_loop(monkeypatch):
    """A prompt may block its own task. It may not block everybody else's."""

    def blocking_input(_prompt: str = "") -> str:
        time.sleep(BLOCK_FOR)  # a real person, taking a real moment
        return "y"

    monkeypatch.setattr("builtins.input", blocking_input)

    async with _Ticker() as ticker:
        decision = await console_approval_callback(_request())

    assert decision is ApprovalDecision.APPROVED
    assert ticker.ticks >= MIN_TICKS, (
        f"the event loop turned {ticker.ticks} times while a {BLOCK_FOR}s prompt "
        "was open -- it was blocked, not merely waiting"
    )


async def test_console_approval_still_denies_on_eof(monkeypatch):
    """The non-interactive path must keep failing closed."""

    def eof_input(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof_input)

    assert await console_approval_callback(_request()) is ApprovalDecision.DENIED


async def test_console_approval_still_denies_on_n(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p="": "n")
    assert await console_approval_callback(_request()) is ApprovalDecision.DENIED


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class _AsyncInputFinder(ast.NodeVisitor):
    """Records bare `input(...)` calls whose nearest enclosing def is async."""

    def __init__(self) -> None:
        self.hits: list[int] = []
        self._async_depth = 0

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._async_depth += 1
        self.generic_visit(node)
        self._async_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # A plain `def` nested in an `async def` runs synchronously when called;
        # attribute its body to the sync function, not the coroutine.
        outer, self._async_depth = self._async_depth, 0
        self.generic_visit(node)
        self._async_depth = outer

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self._async_depth
            and isinstance(node.func, ast.Name)
            and node.func.id == "input"
        ):
            self.hits.append(node.lineno)
        self.generic_visit(node)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for pkg in _PACKAGES:
        files.extend(sorted((_ROOT / pkg).rglob("*.py")))
    return files


def test_the_gate_sees_a_planted_violation(tmp_path):
    """The gate must be able to fail, or it proves nothing."""
    probe = tmp_path / "probe.py"
    probe.write_text("async def f():\n    return input('x')\n")
    finder = _AsyncInputFinder()
    finder.visit(ast.parse(probe.read_text()))
    assert finder.hits == [2]


def test_the_gate_does_not_fire_on_a_sync_def(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("def f():\n    return input('x')\n")
    finder = _AsyncInputFinder()
    finder.visit(ast.parse(probe.read_text()))
    assert finder.hits == []


def test_the_gate_does_not_fire_on_an_attribute_named_input(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("async def f(o):\n    return o.input('x')\n")
    finder = _AsyncInputFinder()
    finder.visit(ast.parse(probe.read_text()))
    assert finder.hits == []


def test_no_blocking_input_inside_any_coroutine():
    """Zero tolerance: `input()` in an `async def` anywhere in weebot/ or cli/.

    There is no ceiling here because the correct count is zero and the fix --
    `await asyncio.to_thread(input, ...)` -- is a single line. A ceiling would
    only invite the next one.
    """
    offenders: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # not ours to police
            continue
        finder = _AsyncInputFinder()
        finder.visit(tree)
        offenders.extend(
            f"{path.relative_to(_ROOT)}:{line}" for line in finder.hits
        )

    assert not offenders, (
        "`input()` called inside `async def` blocks the whole event loop. "
        "Use `await asyncio.to_thread(input, prompt)`. Offenders:\n  "
        + "\n  ".join(offenders)
    )
