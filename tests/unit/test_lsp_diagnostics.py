"""H20 LSP delta diagnostics, against a fake language server that speaks real stdio framing."""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from weebot.application.middleware.base import ToolCall
from weebot.application.services import lsp_diagnostics
from weebot.application.services.lsp_diagnostics import LspDiagnosticsMiddleware, diagnostic_delta
from weebot.domain.models.diagnostic import Diagnostic
from weebot.domain.models.tool_result import ToolResult
from weebot.infrastructure.lsp.manager import LspManager

# Publishes a warning for "existing_issue" and an error for "undefined_name" on every line that
# has them; "SLOW" in the text delays the publish by 0.6 s.
FAKE_SERVER = textwrap.dedent(
    """
    import json, sys, time
    out, inp = sys.stdout.buffer, sys.stdin.buffer

    def send(msg):
        body = json.dumps(msg).encode()
        out.write(b"Content-Length: %d\\r\\n\\r\\n" % len(body) + body)
        out.flush()

    def read():
        length = 0
        while True:
            line = inp.readline()
            if not line:
                return None
            if not line.strip():
                break
            name, _, value = line.partition(b":")
            if name.lower() == b"content-length":
                length = int(value)
        return json.loads(inp.read(length))

    def publish(uri, text):
        if "SLOW" in text:
            time.sleep(0.6)
        found = []
        for n, line in enumerate(text.splitlines()):
            for needle, sev, code in (("existing_issue", 2, "W1"), ("undefined_name", 1, "F821")):
                if needle in line:
                    rng = {"start": {"line": n, "character": 0}, "end": {"line": n, "character": 5}}
                    found.append({"range": rng, "severity": sev, "code": code,
                                  "message": needle, "source": "fake"})
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": uri, "diagnostics": found}})

    while (msg := read()) is not None:
        method = msg.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
        elif method == "exit":
            break
        elif method == "textDocument/didOpen":
            publish(msg["params"]["textDocument"]["uri"], msg["params"]["textDocument"]["text"])
        elif method == "textDocument/didChange":
            doc = msg["params"]["textDocument"]
            publish(doc["uri"], msg["params"]["contentChanges"][0]["text"])
    """
)


def _diag(line: int, code: str = "F821", message: str = "undefined_name") -> Diagnostic:
    return Diagnostic("a.py", line, 0, line, 5, "error", code, message, "fake")


def _manager(tmp_path: Path, *roots: Path, max_servers: int = 3) -> LspManager:
    script = tmp_path / "fake_lsp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return LspManager(
        tmp_path / "ws",
        list(roots),
        servers={"python": ((sys.executable, str(script)),)},
        which=lambda name: name,
        max_servers=max_servers,
    )


def test_delta_drops_an_old_diagnostic_that_moved_two_lines_but_not_three():
    assert diagnostic_delta([_diag(10)], [_diag(12)]) == []
    assert diagnostic_delta([_diag(10)], [_diag(13)]) == [_diag(13)]
    assert diagnostic_delta([_diag(10)], [_diag(10, message="other")]) != []


async def test_an_edit_that_adds_an_undefined_name_reports_only_the_new_diagnostic(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "mod.py"
    target.write_text("existing_issue = 1\n", encoding="utf-8")
    manager = _manager(tmp_path)
    middleware = LspDiagnosticsMiddleware(manager, workspace)
    try:
        call = ToolCall("file_editor", {"command": "insert", "path": "mod.py"})
        await middleware.before_tool_call(call)
        target.write_text("existing_issue = 1\nx = undefined_name\n", encoding="utf-8")
        result = await middleware.transform_tool_result(call, ToolResult(output="edited"))
    finally:
        await manager.close_all()

    assert result.output.count("line ") == 1
    assert "line 2: error undefined_name (F821, fake)" in result.output
    assert "existing_issue" not in result.output
    assert "[new diagnostics in mod.py]" in result.output


async def test_a_late_answer_is_attached_to_the_next_tool_result(tmp_path, monkeypatch):
    monkeypatch.setattr(lsp_diagnostics, "WAIT_S", 0.2)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "mod.py"
    target.write_text("x = 1\n", encoding="utf-8")
    manager = _manager(tmp_path)
    middleware = LspDiagnosticsMiddleware(manager, workspace)
    try:
        call = ToolCall("file_editor", {"command": "create", "path": "mod.py"})
        await middleware.before_tool_call(call)
        target.write_text("SLOW\nx = undefined_name\n", encoding="utf-8")
        first = await middleware.transform_tool_result(call, ToolResult(output="edited"))
        assert "undefined_name" not in first.output

        await asyncio.sleep(1.2)
        other = ToolCall("bash", {"command": "ls"})
        second = await middleware.transform_tool_result(other, ToolResult(output="listing"))
    finally:
        await manager.close_all()

    assert second.output.startswith("listing")
    assert "[late diagnostics]" in second.output and "undefined_name" in second.output


async def test_an_untrusted_root_starts_no_server(tmp_path):
    spawned: list[str] = []
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    manager = LspManager(
        tmp_path / "ws",
        servers={"python": (("fake-server",),)},
        which=lambda name: spawned.append(name) or name,
    )
    path = str(outside / "mod.py")

    await manager.open(path, "x = undefined_name\n")
    await manager.change(path, "x = undefined_name\n")

    assert await manager.diagnostics(path, 0.1) == []
    assert spawned == []


async def test_a_listed_trusted_root_does_start_a_server(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    manager = _manager(tmp_path, outside)
    path = str(outside / "mod.py")
    try:
        await manager.change(path, "x = undefined_name\n")
        found = await manager.diagnostics(path, 3)
    finally:
        await manager.close_all()
    assert found is not None and [d.code for d in found] == ["F821"]


async def test_a_failed_tool_call_is_left_alone(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = _manager(tmp_path)
    middleware = LspDiagnosticsMiddleware(manager, workspace)
    call = ToolCall("file_editor", {"command": "create", "path": "mod.py"})

    result = await middleware.transform_tool_result(call, ToolResult(output="", error="denied"))

    assert result.output == "" and result.error == "denied"
    await manager.close_all()


async def test_the_least_recently_used_server_is_closed_past_the_limit(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    manager = _manager(tmp_path, first, second, max_servers=1)
    try:
        await manager.change(str(first / "a.py"), "x = 1\n")
        old = next(iter(manager._clients.values()))
        await manager.change(str(second / "b.py"), "x = 1\n")
        assert len(manager._clients) == 1
        assert not old.alive
    finally:
        await manager.close_all()


@pytest.mark.parametrize("name,command", [("file_editor", "view"), ("bash", "create")])
def test_reads_and_other_tools_are_ignored(tmp_path, name, command):
    middleware = LspDiagnosticsMiddleware(_manager(tmp_path), tmp_path)

    assert middleware._target(ToolCall(name, {"command": command, "path": "a.py"})) is None
