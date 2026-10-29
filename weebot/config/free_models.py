"""Free-tier providers that speak the OpenAI API (Groq, Gemini), tried first for chosen roles.

Off by default: nothing changes until WEEBOT_FREE_ROLES names a role, and an entry counts only
while its provider's key is set. Ids are ``free/<provider>/<model>``; the prefix is what routes
the call (``LocalModelRouter``), and the adapter factory builds that provider's endpoint.

A free tier is rate-limited (a 429 trips that model's circuit breaker and the cascade moves on
to the paid models behind it) and may use prompts for training: a ``trains_on_prompts``
provider is skipped once a session has read untrusted content (``CascadeExecutor``).
"""

from __future__ import annotations

from dataclasses import dataclass

from weebot.domain.models.model_config import ModelConfig, ModelTier
from weebot.domain.models.task_type import TaskType

FREE_PREFIX = "free/"


@dataclass(frozen=True)
class FreeProvider:
    base_url: str
    key_env: str
    settings_field: str
    trains_on_prompts: bool
    context_window: int


# Terms as published in 2026-10; a provider can change its free tier at any time.
PROVIDERS: dict[str, FreeProvider] = {
    "groq": FreeProvider(
        "https://api.groq.com/openai/v1", "GROQ_API_KEY", "groq_api_key", False, 131072
    ),
    "gemini": FreeProvider(
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GEMINI_API_KEY",
        "gemini_api_key",
        True,  # the free tier may use prompts to improve Google's models
        1048576,
    ),
}


def free_model_id(provider: str, model: str) -> str:
    return f"{FREE_PREFIX}{provider}/{model}"


def split_free_id(model_id: str) -> tuple[str, str] | None:
    """``("groq", "openai/gpt-oss-120b")`` for ``free/groq/openai/gpt-oss-120b``, else None."""
    if not model_id.startswith(FREE_PREFIX):
        return None
    provider, _, model = model_id[len(FREE_PREFIX) :].partition("/")
    return (provider, model) if provider and model else None


def provider_key(provider: str) -> str | None:
    """The provider's API key from settings (``.env``), or None when it is unset or unknown."""
    from weebot.config.settings import get_settings

    spec = PROVIDERS.get(provider)
    value = getattr(get_settings(), spec.settings_field, None) if spec else None
    return value.strip() if value and value.strip() else None


def trains_on_prompts(model_id: str) -> bool:
    """True for a free tier that may log or train on prompts.

    OpenRouter ``:free`` variants count too (plan S2): their providers may keep prompts,
    and ``keep_private`` used to let them through because only ``free/`` ids were known.
    """
    if ":free" in model_id:
        return True
    parts = split_free_id(model_id)
    spec = PROVIDERS.get(parts[0]) if parts else None
    return bool(spec and spec.trains_on_prompts)


def role_models() -> dict[str, str]:
    """``{role: free id}`` from WEEBOT_FREE_ROLES (``role=provider/model``, comma separated).

    An entry whose provider is unknown or has no key is left out, so a role listed before its
    key is set keeps its normal cascade.
    """
    from weebot.config.settings import get_settings

    mapping: dict[str, str] = {}
    for entry in get_settings().free_roles.split(","):
        role, _, target = entry.partition("=")
        provider, _, model = target.strip().partition("/")
        if role.strip() and model and provider_key(provider):
            mapping[role.strip()] = free_model_id(provider, model)
    return mapping


def free_models() -> dict[str, ModelConfig]:
    """Catalog entries for every model a role uses; {} when none is listed."""
    entries: dict[str, ModelConfig] = {}
    for model_id in sorted(set(role_models().values())):
        provider, model = split_free_id(model_id)  # type: ignore[misc]  # built by role_models
        spec = PROVIDERS[provider]
        entries[model_id] = ModelConfig(
            name=f"Free tier ({provider}): {model}",
            provider="free",
            cost_per_1k_tokens=0.0,
            context_window=spec.context_window,
            strengths=[TaskType.CHAT, TaskType.CODE_GENERATION, TaskType.REASONING],
            tier=ModelTier.FAST,
            api_key_env=spec.key_env,
            # Not yet measured on Weebot's tool loop, so below the cloud leaders'.
            tool_use_score=5,
            prompt_cost_per_1k=0.0,
            completion_cost_per_1k=0.0,
            input_modalities=["text"],
        )
    return entries
