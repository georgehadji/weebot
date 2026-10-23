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


def _direct_key_of(adapter) -> str | None:
    return getattr(getattr(adapter._primary, "_client", None), "api_key", None)


def _fake_keys(monkeypatch):
    from weebot.infrastructure.adapters.llm import adapter_factory as af

    keys = {
        "DEEPSEEK_API_KEY": "ds-key",
        "KIMI_API_KEY": "kimi-key",
        "OPENROUTER_API_KEY": "or-key",
    }
    monkeypatch.setattr(af, "_resolve_direct_key", lambda env_var: keys.get(env_var))
    return af.AdapterFactory()


def test_deepseek_direct_gets_its_own_key_not_the_callers_openrouter_key(monkeypatch):
    # The key lived only in .env (settings), not os.environ, and the caller's
    # api_key is the OpenRouter key: DeepSeek-direct got "no-key" or a wrong
    # key, so every call silently went to OpenRouter.
    factory = _fake_keys(monkeypatch)
    adapter = factory._create_inner_adapter(
        provider="deepseek", model="deepseek/deepseek-v4.1-flash", api_key="or-key"
    )
    assert _direct_key_of(adapter) == "ds-key"


def test_moonshot_direct_gets_its_own_key_not_the_callers_openrouter_key(monkeypatch):
    factory = _fake_keys(monkeypatch)
    adapter = factory._create_inner_adapter(
        provider="moonshot", model="moonshotai/kimi-k2.6", api_key="or-key"
    )
    assert _direct_key_of(adapter) == "kimi-key"


def test_openai_and_anthropic_direct_get_their_own_keys(monkeypatch):
    # Same class of bug as DeepSeek: the keys live in .env-backed settings,
    # the adapters read os.environ only, so provider "openai" sent "no-key".
    from weebot.infrastructure.adapters.llm import adapter_factory as af

    keys = {"OPENAI_API_KEY": "sk-openai-key", "ANTHROPIC_API_KEY": "sk-ant-key"}
    monkeypatch.setattr(af, "_resolve_direct_key", lambda env_var: keys.get(env_var))
    factory = af.AdapterFactory()
    openai = factory._create_inner_adapter(provider="openai", model="gpt-6-luna", api_key=None)
    assert openai._client.api_key == "sk-openai-key"
    anthropic = factory._create_inner_adapter(
        provider="anthropic", model="claude-sonnet-5.5", api_key=None
    )
    assert getattr(anthropic, "_client").api_key == "sk-ant-key"
