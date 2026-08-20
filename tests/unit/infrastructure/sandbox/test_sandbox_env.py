"""Tests for H6 sandbox env scrubbing."""

from weebot.infrastructure.sandbox.native_windows import _build_child_env
from weebot.application.ports.sandbox_port import SandboxConfig


class TestSandboxEnvScrubbing:
    """H6 — child process environment is scrubbed of secrets."""

    def test_api_key_excluded(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
        config = SandboxConfig()
        env = _build_child_env(config)
        assert "OPENROUTER_API_KEY" not in env

    def test_path_included(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin")
        config = SandboxConfig()
        env = _build_child_env(config)
        assert env.get("PATH") == "/usr/bin"

    def test_config_env_vars_override(self):
        config = SandboxConfig(env_vars={"MY_VAR": "value"})
        env = _build_child_env(config)
        assert env["MY_VAR"] == "value"

    def test_network_disabled_sets_proxy(self):
        config = SandboxConfig(allow_network=False)
        env = _build_child_env(config)
        assert env["HTTP_PROXY"] == "http://127.0.0.1:9"
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:9"
        assert env["ALL_PROXY"] == "http://127.0.0.1:9"
        assert env["NO_PROXY"] == ""

    def test_network_enabled_no_proxy(self):
        config = SandboxConfig(allow_network=True)
        env = _build_child_env(config)
        assert "HTTP_PROXY" not in env
        assert "HTTPS_PROXY" not in env
        assert "ALL_PROXY" not in env
        assert "NO_PROXY" not in env

    def test_extra_vars_overlay(self):
        config = SandboxConfig()
        env = _build_child_env(config, extra={"EXTRA": "val"})
        assert env["EXTRA"] == "val"
