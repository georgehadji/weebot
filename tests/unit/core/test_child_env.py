"""Child processes get an allowlisted environment, never the parent's secrets (H1)."""

from __future__ import annotations

import pytest

from weebot.core.child_env import build_child_env

SOURCE = {
    "PATH": "/bin",
    "HOME": "/home/u",
    "OPENROUTER_API_KEY": "sk-secret",
    "GITHUB_TOKEN": "gh-secret",
    "HTTPS_PROXY": "http://proxy:3128",
}


def test_secrets_are_not_inherited():
    env = build_child_env(SOURCE, platform="linux")
    assert "OPENROUTER_API_KEY" not in env and "GITHUB_TOKEN" not in env
    assert env["PATH"] == "/bin" and env["HTTPS_PROXY"] == "http://proxy:3128"


def test_declared_wins_and_passthrough_is_opt_in():
    env = build_child_env(
        SOURCE, declared={"PATH": "/mine", "X": "1"}, passthrough=["GITHUB_TOKEN"], platform="linux"
    )
    assert env["PATH"] == "/mine" and env["X"] == "1" and env["GITHUB_TOKEN"] == "gh-secret"


def test_proxy_can_be_dropped_and_empty_source_gives_empty_dict_not_none():
    assert build_child_env({}, platform="linux") == {}
    assert "HTTPS_PROXY" not in build_child_env(SOURCE, inherit_proxy=False, platform="linux")


def test_windows_names_match_case_insensitively():
    env = build_child_env(
        {"Path": "C:/bin", "AppData": "C:/a", "OPENAI_API_KEY": "k"},
        declared={"PATH": "D:/x"},
        platform="win32",
    )
    assert env == {"AppData": "C:/a", "PATH": "D:/x"}


@pytest.mark.asyncio
async def test_mcp_stdio_child_does_not_receive_provider_keys(monkeypatch):
    from contextlib import AsyncExitStack
    from unittest.mock import AsyncMock, MagicMock, patch

    from weebot.config.secret_accessor import SecretAccessor
    from weebot.infrastructure.mcp import mcp_client_manager as mod

    SecretAccessor.set_source({"PATH": "/bin", "OPENROUTER_API_KEY": "sk-secret", "G": "tok"})
    captured = {}

    def fake_stdio(params):
        captured["env"] = params.env
        raise RuntimeError("stop")

    try:
        with patch.object(mod, "stdio_client", fake_stdio):
            mgr = mod.MCPClientManager.__new__(mod.MCPClientManager)
            mgr._clients = {}
            with pytest.raises(Exception):
                async with AsyncExitStack() as stack:
                    await mgr._connect_stdio(
                        "s",
                        {"command": "x", "env": {"GITHUB_TOKEN": "decl"}, "env_passthrough": ["G"]},
                        stack,
                    )
    finally:
        SecretAccessor.set_source(None)
    assert "OPENROUTER_API_KEY" not in captured["env"]
    assert captured["env"]["GITHUB_TOKEN"] == "decl" and captured["env"]["G"] == "tok"
