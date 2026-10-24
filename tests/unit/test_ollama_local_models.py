"""Local models through Ollama (docs/OLLAMA.md): off by default, local-first for chosen roles.

Pins the six pieces: the factory branch, the settings, the catalog entry, the role cascade,
the routing adapter that keeps `ollama/...` ids away from OpenRouter, and the cascade's
credit filter.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMPort
from weebot.application.services.model_registry._service import ModelSelectionService
from weebot.application.strategies.llm_pool import unwrap_llm
from weebot.config._catalog_validator import CatalogValidator
from weebot.config.local_models import local_models, role_models
from weebot.config.model_refs import ROLE_MODEL_CONFIG, get_model_cascade_for_role
from weebot.config.model_registry import ModelProvider, get_model_config
from weebot.config.settings import get_settings
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory
from weebot.infrastructure.adapters.llm.local_router_adapter import LocalModelRouter
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter

TAG = "qwen3:8b"
LOCAL_ID = f"ollama/{TAG}"
CLOUD_TAG = "gemma4:31b-cloud"
CLOUD_ID = f"ollama/{CLOUD_TAG}"


@pytest.fixture
def ollama_on(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_MODEL", TAG)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestOffByDefault:
    @pytest.fixture(autouse=True)
    def _settings_without_the_developers_env(self):
        # The cached settings may have been built while an earlier import put .env in os.environ.
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_nothing_changes_without_the_switch(self):
        assert local_models() == {}
        assert get_model_config(LOCAL_ID) is None
        assert LOCAL_ID not in ModelSelectionService().available_models()
        for role in ("summarizer", "documentation", "planner"):
            assert get_model_cascade_for_role(role) == list(ROLE_MODEL_CONFIG[role])

    def test_the_factory_does_not_wrap_when_off(self):
        adapter = AdapterFactory().create_adapter("openrouter", api_key="k")
        assert not isinstance(adapter, LocalModelRouter)


class TestWhenEnabled:
    def test_the_catalog_has_a_free_local_entry(self, ollama_on):
        cfg = get_model_config(LOCAL_ID)
        assert cfg is not None
        assert (cfg.provider, cfg.cost_per_1k_tokens) == ("ollama", 0.0)
        assert LOCAL_ID in ModelSelectionService().available_models()

    def test_the_catalog_validator_gains_no_warning(self, monkeypatch):
        off = CatalogValidator.run_default_validation()
        monkeypatch.setenv("OLLAMA_ENABLED", "true")
        get_settings.cache_clear()
        on = CatalogValidator.run_default_validation()
        get_settings.cache_clear()
        assert off.total_models_checked > 0
        assert on.warning_count == off.warning_count

    def test_chosen_roles_try_the_local_model_first_and_keep_the_cloud_behind_it(self, ollama_on):
        for role in ("summarizer", "documentation"):
            cascade = get_model_cascade_for_role(role)
            assert cascade[0] == LOCAL_ID
            assert cascade[1:] == list(ROLE_MODEL_CONFIG[role])

    def test_other_roles_never_use_it(self, ollama_on):
        for role in ("planner", "coder", "reviewer", "executor", "verifier", None):
            assert LOCAL_ID not in get_model_cascade_for_role(role)

    def test_the_role_list_is_configurable(self, ollama_on, monkeypatch):
        monkeypatch.setenv("OLLAMA_ROLES", "researcher")
        get_settings.cache_clear()
        assert get_model_cascade_for_role("researcher")[0] == LOCAL_ID
        assert get_model_cascade_for_role("summarizer")[0] != LOCAL_ID

    def test_two_models_serve_different_roles(self, ollama_on, monkeypatch):
        monkeypatch.setenv(
            "OLLAMA_ROLES", "summarizer, verifier=gemma4:31b-cloud ,subagent=gemma4:31b-cloud"
        )
        get_settings.cache_clear()
        assert role_models() == {
            "summarizer": TAG,
            "verifier": CLOUD_TAG,
            "subagent": CLOUD_TAG,
        }
        assert get_model_cascade_for_role("summarizer")[0] == LOCAL_ID
        assert get_model_cascade_for_role("verifier")[0] == CLOUD_ID
        assert get_model_cascade_for_role("verifier")[1:] == list(ROLE_MODEL_CONFIG["verifier"])
        assert get_model_cascade_for_role("documentation")[0] != LOCAL_ID  # not listed now

    def test_both_models_are_in_the_catalog_with_their_own_shape(self, ollama_on, monkeypatch):
        monkeypatch.setenv("OLLAMA_ROLES", "summarizer,verifier=gemma4:31b-cloud")
        get_settings.cache_clear()
        local, cloud = get_model_config(LOCAL_ID), get_model_config(CLOUD_ID)
        assert (local.tier.value, cloud.tier.value) == ("local", "standard")
        assert cloud.context_window == 262144 and local.context_window == 4096
        assert cloud.tool_use_score > local.tool_use_score
        report = CatalogValidator.run_default_validation()
        assert not [w for w in report.warnings if "ollama" in str(w).lower()]

    def test_the_default_tag_is_always_catalogued_even_when_unused(self, ollama_on, monkeypatch):
        monkeypatch.setenv("OLLAMA_ROLES", "verifier=gemma4:31b-cloud")
        get_settings.cache_clear()
        assert set(local_models()) == {LOCAL_ID, CLOUD_ID}

    def test_the_provider_is_ollama(self):
        assert ModelProvider.from_model_name(LOCAL_ID) is ModelProvider.OLLAMA

    def test_the_low_credit_filter_never_drops_it(self):
        assert CascadeExecutor._is_openrouter_model(LOCAL_ID) is False
        assert CascadeExecutor._is_openrouter_model("qwen/qwen3.8-flash") is True


class TestFactory:
    def test_the_ollama_adapter_points_at_the_local_server_with_a_dummy_key(self, ollama_on):
        resilient = AdapterFactory().create_adapter("ollama", model=LOCAL_ID)
        inner = resilient._inner
        assert isinstance(inner, OpenAIAdapter)
        assert str(inner._client.base_url).startswith("http://localhost:11434/v1")
        assert inner._client.api_key == "ollama"
        assert inner._default_model == TAG

    def test_the_ollama_timeout_is_long(self):
        assert AdapterFactory().get_provider_config("ollama")["timeout"] >= 300

    def test_other_providers_are_wrapped_in_the_router_when_on(self, ollama_on):
        adapter = AdapterFactory().create_adapter("openrouter", api_key="k")
        assert isinstance(adapter, LocalModelRouter)
        assert isinstance(unwrap_llm(adapter), ResilientLLMAdapter)


class _Fake(LLMPort):
    def __init__(self, name):
        self.name, self.calls = name, []

    async def chat(self, messages, tools=None, tool_choice="auto", response_format=None,
                   model=None, temperature=None, max_tokens=None):
        self.calls.append(model)
        return SimpleNamespace(content=self.name)

    def extra(self):
        return "default-only surface"


class TestRouter:
    @pytest.mark.asyncio
    async def test_ollama_ids_go_local_with_the_prefix_stripped(self):
        default, local = _Fake("cloud"), _Fake("local")
        router = LocalModelRouter(default, lambda: local)
        out = await router.chat(messages=[], model=LOCAL_ID)
        assert (out.content, local.calls, default.calls) == ("local", [TAG], [])

    @pytest.mark.asyncio
    async def test_everything_else_goes_where_it_went_before(self):
        default, local = _Fake("cloud"), _Fake("local")
        built = []
        router = LocalModelRouter(default, lambda: built.append(1) or local)
        out = await router.chat(messages=[], model="deepseek/deepseek-v4-flash")
        assert (out.content, default.calls, built) == ("cloud", ["deepseek/deepseek-v4-flash"], [])
        await router.chat(messages=[])
        assert default.calls[-1] is None

    @pytest.mark.asyncio
    async def test_the_local_adapter_is_built_once_and_only_on_use(self):
        built = []
        router = LocalModelRouter(_Fake("cloud"), lambda: built.append(1) or _Fake("local"))
        assert built == []
        await router.chat(messages=[], model=LOCAL_ID)
        await router.chat(messages=[], model=LOCAL_ID)
        assert built == [1]

    def test_it_is_transparent_to_attribute_access_and_unwrap(self):
        default = _Fake("cloud")
        router = LocalModelRouter(default, lambda: _Fake("local"))
        assert router.extra() == "default-only surface"
        assert unwrap_llm(router) is default


@pytest.mark.external
@pytest.mark.asyncio
async def test_a_real_round_trip_to_the_local_server(ollama_on):
    """Needs `ollama serve` with qwen3:8b pulled (WEEBOT_TEST_LIVE=1)."""
    adapter = AdapterFactory().create_adapter("openrouter", api_key="unused")
    resp = await adapter.chat(
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        model=LOCAL_ID,
        max_tokens=300,
    )
    assert "ok" in (resp.content or "").lower()
