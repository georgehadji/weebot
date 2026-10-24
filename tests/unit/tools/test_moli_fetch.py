"""moli_fetch: page to Markdown through the Moli headless browser.

Fetched pages are third-party text, so the tool is on the trust boundary (fenced
and egress-tainting). The command line is fixed: no --eval, headers, cookies or
profile from the model; private networks are always blocked.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weebot.core.trust_boundary import must_fence, must_taint, trust_of
from weebot.tools.moli_fetch import MoliFetchTool


class _Proc:
    def __init__(self, out: bytes = b"# Title\n\nbody", err: bytes = b"", code: int = 0):
        self._out, self._err, self.returncode = out, err, code

    async def communicate(self):
        return self._out, self._err

    def kill(self) -> None:
        pass


@pytest.fixture
def fake_moli(monkeypatch, tmp_path):
    exe = tmp_path / "moli.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("MOLI_PATH", str(exe))
    calls: list[tuple] = []
    proc = {"value": _Proc()}

    async def _exec(*args, **kwargs):
        calls.append(args)
        return proc["value"]

    monkeypatch.setattr("asyncio.create_subprocess_exec", _exec)
    return calls, proc


def test_moli_fetch_is_on_the_trust_boundary():
    trust = trust_of(MoliFetchTool)
    assert must_fence(trust)
    assert must_taint(trust, False)


async def test_a_page_comes_back_as_markdown_with_a_fixed_safe_command(fake_moli):
    calls, _ = fake_moli
    result = await MoliFetchTool().execute(url="https://example.com/a")
    assert not result.is_error and "# Title" in result.output
    argv = calls[0]
    assert argv[1:4] == ("fetch", "--dump", "markdown")
    assert "--block-private-networks" in argv and "--fail" in argv
    assert argv[-1] == "https://example.com/a"
    assert not any(a in argv for a in ("--eval", "--eval-file", "-H", "--profile-dir", "-c"))


@pytest.mark.parametrize("url", ["file:///C:/secret.txt", "javascript:alert(1)", "ftp://x/y", ""])
async def test_only_http_and_https_urls_run(fake_moli, url):
    calls, _ = fake_moli
    result = await MoliFetchTool().execute(url=url)
    assert result.is_error and calls == []


async def test_an_http_error_is_an_error(fake_moli):
    _, proc = fake_moli
    proc["value"] = _Proc(out=b"", err=b"HTTP status 404", code=22)
    result = await MoliFetchTool().execute(url="https://example.com/missing")
    assert result.is_error and "404" in result.error
    assert "camofox_browser" not in result.error


@pytest.mark.parametrize("status", [b"403", b"429"])
async def test_a_bot_block_points_to_camofox(fake_moli, status):
    """Skills are retrieved from step text, not from errors, so the hint goes here."""
    _, proc = fake_moli
    err = b"Reason: final main document returned HTTP status " + status + b" at `x`"
    proc["value"] = _Proc(out=b"", err=err, code=22)
    result = await MoliFetchTool().execute(url="https://example.com/")
    assert result.is_error and "camofox_browser" in result.error


async def test_long_output_is_truncated(fake_moli):
    _, proc = fake_moli
    proc["value"] = _Proc(out=b"x" * 5000)
    result = await MoliFetchTool().execute(url="https://example.com", max_chars=1000)
    assert len(result.output) < 1200 and "truncated" in result.output


async def test_semantic_tree_format_is_allowed_and_others_are_not(fake_moli):
    calls, _ = fake_moli
    await MoliFetchTool().execute(url="https://example.com", format="semantic_tree_text")
    assert calls[0][3] == "semantic_tree_text"
    result = await MoliFetchTool().execute(url="https://example.com", format="screenshot")
    assert result.is_error and len(calls) == 1


async def test_a_missing_binary_says_how_to_configure_it(monkeypatch, tmp_path):
    monkeypatch.setenv("MOLI_PATH", str(tmp_path / "nope.exe"))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = await MoliFetchTool().execute(url="https://example.com")
    assert result.is_error and "MOLI_PATH" in result.error


def test_the_registry_offers_it_to_browsing_roles():
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    for role in ("researcher", "admin", "webhook"):
        assert "moli_fetch" in RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS[role]
    assert RoleBasedToolRegistry.build_tool_class_map().get("moli_fetch") is MoliFetchTool


@pytest.mark.external
async def test_live_fetch_of_example_com():
    result = await MoliFetchTool().execute(url="https://example.com")
    if result.is_error and "MOLI_PATH" in result.error:
        pytest.skip("moli is not installed")
    assert "documentation examples" in result.output
