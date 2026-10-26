"""scripts/lint_async_io.py: awaited async methods are not blocking I/O."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "lint_async_io", Path(__file__).resolve().parents[2] / "scripts" / "lint_async_io.py"
)
lint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lint)


def _check(tmp_path: Path, body: str) -> list[str]:
    f = tmp_path / "mod.py"
    f.write_text(f"async def run(self, p):\n    {body}\n", encoding="utf-8")
    return lint._check_file(f)


def test_awaited_read_text_not_flagged(tmp_path):
    assert _check(tmp_path, "text = await self.read_text(p)") == []


def test_awaited_write_text_not_flagged(tmp_path):
    assert _check(tmp_path, "await self.write_text(p, 'x')") == []


def test_bare_path_read_text_flagged(tmp_path):
    assert len(_check(tmp_path, "text = p.read_text()")) == 1


def test_to_thread_wrapped_not_flagged(tmp_path):
    assert _check(tmp_path, "text = await asyncio.to_thread(p.read_text)") == []
