"""Free-tier providers (Groq, Gemini) tried first for chosen roles, then the paid cascade.

Off until WEEBOT_FREE_ROLES names a role and that provider's key is set. Pins:
- the role cascade puts ``free/<provider>/<model>`` first and keeps the paid cascade behind it;
- the factory builds the provider's own OpenAI-compatible adapter with the provider's key,
  and refuses without one (OpenAIAdapter would otherwise send the OpenRouter key);
- the router sends ``free/`` ids there with the bare model name;
- a session that has read untrusted content never reaches a provider that trains on prompts;
- single-model role LLMs (no fallback) skip the free model;
- the catalog lists the models at cost 0 and the low-credit filter keeps them.
"""

from __future__ import annotations

import asyncio
import unittest.mock as m
from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.agents.executor._session_scope import get_session_scope
from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.services.model_registry._service import ModelSelectionService
from weebot.config._catalog_validator import CatalogValidator
from weebot.config.free_models import free_models, role_models, trains_on_prompts
from weebot.config.model_refs import ROLE_MODEL_CONFIG, get_model_cascade_for_role
from weebot.config.model_registry import ModelProvider, get_model_config
from weebot.config.settings import get_settings
from weebot.core.log_context import session_id_var
from weebot.core.model_cascade_tracker import CascadeTier
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory
from weebot.infrastructure.adapters.llm.local_router_adapter import LocalModelRouter
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

GROQ_ID = "free/groq/openai/gpt-oss-120b"
GEMINI_ID = "free/gemini/gemini-2.5-flash"
ROLES = "executor=groq/openai/gpt-oss-120b, coder=gemini/gemini-2.5-flash"


def _settings(monkeypatch, roles="", groq="", gemini=""):
    monkeypatch.setenv("WEEBOT_FREE_ROLES", roles)
    monkeypatch.setenv("GROQ_API_KEY", groq)
    monkeypatch.setenv("GEMINI_API_KEY", gemini)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def free_on(monkeypatch):
    _settings(monkeypatch, ROLES, groq="gsk-test", gemini="gm-test")


class TestOffByDefault:
    def test_nothing_changes_without_roles(self, monkeypatch):
        _settings(monkeypatch, groq="gsk-test", gemini="gm-test")
        assert free_models() == {} and role_models() == {}
        assert GROQ_ID not in get_model_cascade_for_role("executor")
        assert get_model_config(GROQ_ID) is None

    def test_a_listed_role_without_its_key_is_ignored(self, monkeypatch):
        _settings(monkeypatch, ROLES, gemini="gm-test")
        assert role_models() == {"coder": GEMINI_ID}
        assert GROQ_ID not in get_model_cascade_for_role("executor")


class TestWhenListed:
    def test_listed_roles_try_the_free_model_first_and_keep_the_paid_cascade(self, free_on):
        executor = get_model_cascade_for_role("executor")
        assert executor[0] == GROQ_ID and executor[1:] == list(ROLE_MODEL_CONFIG["executor"])
        assert get_model_cascade_for_role("coder")[0] == GEMINI_ID
        for role in ("planner", "verifier", None):
            assert not any(mid.startswith("free/") for mid in get_model_cascade_for_role(role))

    def test_the_catalog_lists_them_at_cost_zero(self, free_on):
        cfg = get_model_config(GROQ_ID)
        assert cfg is not None and cfg.cost_per_1k_tokens == 0.0
        assert cfg.api_key_env == "GROQ_API_KEY"
        assert {GROQ_ID, GEMINI_ID} <= set(ModelSelectionService().available_models())

    def test_the_catalog_validator_gains_no_warning(self, monkeypatch):
        _settings(monkeypatch)
        off = CatalogValidator.run_default_validation()
        _settings(monkeypatch, ROLES, groq="gsk-test", gemini="gm-test")
        on = CatalogValidator.run_default_validation()
        assert on.warning_count == off.warning_count

    def test_the_provider_is_free_and_the_tier_is_free(self):
        assert ModelProvider.from_model_name(GROQ_ID) is ModelProvider.FREE
        assert CascadeExecutor._tier_of(GROQ_ID) is CascadeTier.FREE

    def test_the_low_credit_filter_never_drops_them(self):
        assert CascadeExecutor._is_openrouter_model(GROQ_ID) is False

    def test_which_providers_train_on_prompts(self):
        assert trains_on_prompts(GEMINI_ID) is True
        assert trains_on_prompts(GROQ_ID) is False
        assert trains_on_prompts("deepseek/deepseek-v4-flash") is False


class TestFactory:
    def test_the_adapter_points_at_the_provider_with_its_own_key(self, free_on):
        inner = AdapterFactory().create_adapter("free", model=GROQ_ID)._inner
        assert isinstance(inner, OpenAIAdapter)
        assert str(inner._client.base_url).startswith("https://api.groq.com/openai/v1")
        assert inner._client.api_key == "gsk-test"
        assert inner._default_model == "openai/gpt-oss-120b"

    def test_without_its_key_it_refuses_and_never_uses_the_openrouter_key(self, monkeypatch):
        _settings(monkeypatch, ROLES)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-must-not-leak")
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            AdapterFactory().create_adapter("free", model=GROQ_ID)

    def test_an_unknown_provider_is_refused(self, free_on):
        with pytest.raises(ValueError, match="nope"):
            AdapterFactory().create_adapter("free", model="free/nope/x")

    def test_other_providers_are_wrapped_in_the_router_when_roles_are_listed(self, free_on):
        assert isinstance(AdapterFactory().create_adapter("openrouter", api_key="k"), LocalModelRouter)


class _Fake(LLMPort):
    def __init__(self, name):
        self.name, self.calls = name, []

    async def chat(self, messages, tools=None, tool_choice="auto", response_format=None,
                   model=None, temperature=None, max_tokens=None):
        self.calls.append(model)
        return SimpleNamespace(content=self.name)


class TestRouter:
    @pytest.mark.asyncio
    async def test_free_ids_go_to_their_provider_with_the_bare_model(self):
        default, free, built = _Fake("default"), _Fake("free"), []
        router = LocalModelRouter(default, free_factory=lambda mid: built.append(mid) or free)
        out = await router.chat(messages=[], model=GROQ_ID)
        assert (out.content, free.calls, built, default.calls) == (
            "free", ["openai/gpt-oss-120b"], [GROQ_ID], []
        )

    @pytest.mark.asyncio
    async def test_everything_else_goes_to_the_default(self):
        default, free = _Fake("default"), _Fake("free")
        router = LocalModelRouter(default, free_factory=lambda mid: free)
        await router.chat(messages=[], model="deepseek/deepseek-v4-flash")
        assert (default.calls, free.calls) == (["deepseek/deepseek-v4-flash"], [])


class _RecordingLLM:
    def __init__(self, works: set[str]):
        self.works, self.started = works, []

    async def chat(self, *args, **kwargs):
        model = kwargs.get("model")
        self.started.append(model)
        await asyncio.sleep(0.01)
        if model not in self.works:
            raise RuntimeError(f"injected failure for {model}")
        return LLMResponse(content=f"ok from {model}", tool_calls=None, usage=None)


async def _ident(model_ids):
    return model_ids


def _executor(llm, cascade, monkeypatch) -> CascadeExecutor:
    import weebot.config.model_refs as refs

    monkeypatch.setattr(refs, "get_model_cascade_for_role", lambda role: list(cascade))
    for tier in ("_TIER2_MODEL", "_TIER3_MODEL", "_TIER4_MODEL"):
        monkeypatch.setattr(CascadeExecutor, tier, "dead/never", raising=False)
    monkeypatch.setattr(CascadeExecutor, "get_credits_and_filter_direct", staticmethod(_ident))
    tools = m.MagicMock()
    tools.to_params.return_value = []
    return CascadeExecutor(llm=llm, tools=tools, agent_role="executor")


class TestPrivacy:
    @pytest.mark.asyncio
    async def test_a_tainted_session_never_reaches_a_provider_that_trains(self, monkeypatch):
        llm = _RecordingLLM(works={GEMINI_ID, GROQ_ID})
        ex = _executor(llm, [GEMINI_ID, GROQ_ID, "dead/never"], monkeypatch)
        token = session_id_var.set("s-free-tainted")
        get_session_scope().mark_tainted("s-free-tainted")
        try:
            resp = await ex.call_with_cascade(messages=[{"role": "user", "content": "hi"}])
        finally:
            get_session_scope().close("s-free-tainted")
            session_id_var.reset(token)
        assert GEMINI_ID not in llm.started
        assert resp.content == f"ok from {GROQ_ID}"

    @pytest.mark.asyncio
    async def test_a_clean_session_may_use_it(self, monkeypatch):
        llm = _RecordingLLM(works={GEMINI_ID})
        ex = _executor(llm, [GEMINI_ID, "dead/never"], monkeypatch)
        token = session_id_var.set("s-free-clean")
        try:
            resp = await ex.call_with_cascade(messages=[{"role": "user", "content": "hi"}])
        finally:
            session_id_var.reset(token)
        assert resp.content == f"ok from {GEMINI_ID}"


def test_single_model_role_llms_skip_the_free_model(free_on, monkeypatch):
    from weebot.application.di import Container

    monkeypatch.setenv("WEEBOT_FREE_ROLES", "verifier=groq/openai/gpt-oss-120b")
    get_settings.cache_clear()
    assert get_model_cascade_for_role("verifier")[0] == GROQ_ID
    container = Container()
    built = []
    monkeypatch.setattr(container, "_create_llm", lambda model=None: built.append(model))
    container._create_llm_for_role("verifier")
    assert built and built[0] != GROQ_ID and not built[0].startswith("free/")
