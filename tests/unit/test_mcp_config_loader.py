"""Tests for weebot.infrastructure.mcp.config_loader — expand_env and ConfigError."""
from __future__ import annotations

import os

import pytest

from weebot.infrastructure.mcp.config_loader import expand_env, ConfigError


class TestExpandEnv:
    """Environment variable expansion in MCP config values."""

    def test_simple_var_expands(self):
        os.environ["TEST_X_BEARER"] = "my-token-123"
        try:
            result = expand_env("${TEST_X_BEARER}")
            assert result == "my-token-123"
        finally:
            del os.environ["TEST_X_BEARER"]

    def test_var_in_url_expands(self):
        os.environ["TEST_X_HOST"] = "api.x.com"
        try:
            result = expand_env("https://${TEST_X_HOST}/mcp")
            assert result == "https://api.x.com/mcp"
        finally:
            del os.environ["TEST_X_HOST"]

    def test_unset_var_raises(self):
        with pytest.raises(ConfigError, match="X_BEARER"):
            expand_env("${X_BEARER}")

    def test_unset_var_in_url_raises(self):
        with pytest.raises(ConfigError, match="X_CLIENT_ID"):
            expand_env("https://${X_CLIENT_ID}:${X_CLIENT_SECRET}@api.x.com")

    def test_non_string_passthrough(self):
        assert expand_env(42) == 42
        assert expand_env(True) is True
        assert expand_env(None) is None
        assert expand_env(3.14) == 3.14

    def test_dict_values_expanded(self):
        os.environ["TEST_TOKEN"] = "tok_abc"
        try:
            data = {
                "url": "https://api.x.com/mcp",
                "auth": {"type": "bearer", "token": "${TEST_TOKEN}"},
                "timeout": 30,
            }
            result = expand_env(data)
            assert result["auth"]["token"] == "tok_abc"
            assert result["url"] == "https://api.x.com/mcp"
            assert result["timeout"] == 30
        finally:
            del os.environ["TEST_TOKEN"]

    def test_list_values_expanded(self):
        os.environ["TEST_ARGS"] = "--verbose"
        try:
            result = expand_env(["npx", "-y", "${TEST_ARGS}"])
            assert result == ["npx", "-y", "--verbose"]
        finally:
            del os.environ["TEST_ARGS"]

    def test_nested_dict_expansion(self):
        os.environ["TEST_CLIENT_ID"] = "my-client"
        os.environ["TEST_CLIENT_SECRET"] = "my-secret"
        try:
            data = {
                "xapi": {
                    "env": {
                        "CLIENT_ID": "${TEST_CLIENT_ID}",
                        "CLIENT_SECRET": "${TEST_CLIENT_SECRET}",
                    },
                    "timeout_seconds": 300,
                }
            }
            result = expand_env(data)
            assert result["xapi"]["env"]["CLIENT_ID"] == "my-client"
            assert result["xapi"]["env"]["CLIENT_SECRET"] == "my-secret"
            assert result["xapi"]["timeout_seconds"] == 300
        finally:
            del os.environ["TEST_CLIENT_ID"]
            del os.environ["TEST_CLIENT_SECRET"]

    def test_partially_unset_nested_raises(self):
        if "NONEXISTENT_VAR_XYZZY" in os.environ:
            del os.environ["NONEXISTENT_VAR_XYZZY"]
        data = {
            "server": {
                "auth": {"token": "${NONEXISTENT_VAR_XYZZY}"},
                "url": "https://example.com",
            }
        }
        with pytest.raises(ConfigError):
            expand_env(data)

    def test_empty_string_passthrough(self):
        assert expand_env("") == ""
