"""Regression tests for AdapterFactory's consolidated direct-key resolution.

Phase 3: adapter_factory.py used to resolve the xAI direct key inline with
its own settings-first/env-fallback logic, duplicating _has_direct_key()'s
field map. Both now go through _resolve_direct_key(), so they can no
longer disagree.
"""

from __future__ import annotations

from weebot.infrastructure.adapters.llm.adapter_factory import _has_direct_key, _resolve_direct_key


def test_unmapped_env_var_resolves_from_raw_environ(monkeypatch):
    monkeypatch.delenv("SOME_OTHER_PROVIDER_KEY", raising=False)
    assert _resolve_direct_key("SOME_OTHER_PROVIDER_KEY") is None
    assert _has_direct_key("SOME_OTHER_PROVIDER_KEY") is False

    monkeypatch.setenv("SOME_OTHER_PROVIDER_KEY", "raw-value")
    assert _resolve_direct_key("SOME_OTHER_PROVIDER_KEY") == "raw-value"
    assert _has_direct_key("SOME_OTHER_PROVIDER_KEY") is True


def test_mapped_env_var_resolves_via_settings_or_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "some-key")
    resolved = _resolve_direct_key("DEEPSEEK_API_KEY")
    assert resolved  # settings-backed or env-backed, either way non-empty
    assert _has_direct_key("DEEPSEEK_API_KEY") == bool(resolved)


def test_has_direct_key_always_agrees_with_resolve_direct_key(monkeypatch):
    for env_var in ("XAI_API_KEY", "KIMI_API_KEY", "OPENROUTER_API_KEY"):
        assert _has_direct_key(env_var) == bool(_resolve_direct_key(env_var))
