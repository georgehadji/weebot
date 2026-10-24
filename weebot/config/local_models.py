"""Catalog entries for models served by the user's own Ollama (docs/OLLAMA.md).

``model_catalog.py`` is generated from OpenRouter and cannot hold a model that only exists
on one machine, so the local model is described here and merged in by ``all_models()``.
The entry exists only while ``OLLAMA_ENABLED`` is set, so a default install sees the same
catalog as before. The id is ``ollama/<tag>``; the prefix is what routes the call.
"""

from __future__ import annotations

from weebot.config.model_catalog import MODELS
from weebot.domain.models.model_config import ModelConfig, ModelTier
from weebot.domain.models.task_type import TaskType

OLLAMA_PREFIX = "ollama/"
# An Ollama tag ending in this runs on Ollama's servers, not on this machine: prompts leave it.
CLOUD_SUFFIX = "-cloud"
# Ollama's gemma4 page: the medium models have a 256K context.
CLOUD_CONTEXT_WINDOW = 262144


def local_model_id(tag: str) -> str:
    return f"{OLLAMA_PREFIX}{tag}"


def is_cloud_tag(tag: str) -> bool:
    return tag.endswith(CLOUD_SUFFIX)


def role_models() -> dict[str, str]:
    """``{role: ollama tag}`` from OLLAMA_ROLES; empty when Ollama is not enabled.

    Each comma-separated entry is ``role`` (uses OLLAMA_MODEL) or ``role=tag``, so a small
    local model and a larger cloud one can serve different roles:
    ``summarizer,documentation,verifier=gemma4:31b-cloud``.
    """
    from weebot.config.settings import get_settings

    settings = get_settings()
    if not settings.ollama_enabled:
        return {}
    mapping: dict[str, str] = {}
    for entry in settings.ollama_roles.split(","):
        role, _, tag = entry.partition("=")
        if role.strip():
            mapping[role.strip()] = tag.strip() or settings.ollama_model
    return mapping


def _entry(tag: str, local_context: int) -> ModelConfig:
    if is_cloud_tag(tag):
        # A 31B-class model: strong enough for review and verification, not yet measured
        # on Weebot's tool loop, so the tool-use score stays below the cloud leaders'.
        return ModelConfig(
            name=f"Ollama cloud: {tag}",
            provider="ollama",
            cost_per_1k_tokens=0.0,  # a plan quota (GPU time), not a per-token price
            context_window=CLOUD_CONTEXT_WINDOW,
            strengths=[
                TaskType.CHAT,
                TaskType.DOCUMENTATION,
                TaskType.CODE_REVIEW,
                TaskType.REASONING,
            ],
            tier=ModelTier.STANDARD,
            api_key_env="",  # `ollama signin` authenticates the local daemon
            tool_use_score=5,
            prompt_cost_per_1k=0.0,
            completion_cost_per_1k=0.0,
            input_modalities=["text"],
        )
    return ModelConfig(
        name=f"Ollama: {tag}",
        provider="ollama",
        cost_per_1k_tokens=0.0,
        context_window=local_context,
        # Small local models are for bulk text work, not the tool loop.
        strengths=[TaskType.CHAT, TaskType.DOCUMENTATION],
        tier=ModelTier.LOCAL,
        api_key_env="",  # nothing to authenticate with: the server is on this machine
        tool_use_score=3,
        prompt_cost_per_1k=0.0,
        completion_cost_per_1k=0.0,
        input_modalities=["text"],
    )


def local_models() -> dict[str, ModelConfig]:
    """Catalog entries for the default tag and every tag in OLLAMA_ROLES; {} when off."""
    from weebot.config.settings import get_settings

    settings = get_settings()
    if not settings.ollama_enabled:
        return {}
    tags = {settings.ollama_model, *role_models().values()}
    return {
        local_model_id(tag): _entry(tag, settings.ollama_context_window) for tag in sorted(tags)
    }


def all_models() -> dict[str, ModelConfig]:
    """The generated OpenRouter catalog plus the local model, when enabled."""
    return {**MODELS, **local_models()}
