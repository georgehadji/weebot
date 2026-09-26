"""Provider inference and model-metadata lookup.

``ModelProvider.from_model_name`` picks the adapter family for a model id.
``get_model_config`` reads metadata -- pricing, context, capabilities,
reasoning -- from the generated OpenRouter catalog in ``model_catalog``.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.domain.models.model_config import ModelConfig


class ModelProvider(Enum):
    """Supported AI model providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    AZURE = "azure"
    AWS_BEDROCK = "bedrock"
    COHERE = "cohere"
    ANYSCALE = "anyscale"
    PERPLEXITY = "perplexity"
    MISTRAL = "mistral"
    GROQ = "groq"
    TOGETHER_AI = "together_ai"
    OLLAMA = "ollama"
    HUGGINGFACE = "huggingface"
    DEEPSEEK = "deepseek"
    MINIMAX = "minimax"
    MOONSHOT = "moonshot"
    XAI = "xai"
    POOLSIDE = "poolside"
    RECRAFT = "recraft"
    SOURCEFUL = "sourceful"
    BLACK_FOREST_LABS = "black_forest_labs"
    BYTEDANCE = "bytedance"
    MICROSOFT = "microsoft"
    NVIDIA = "nvidia_nim"
    FIREWORKS_AI = "fireworks_ai"
    LEONARDO_AI = "leonardo_ai"
    REPLICATE = "replicate"
    VERTEX_AI = "vertex_ai"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    LM_STUDIO = "lm_studio"
    VLLM = "vllm"
    CUSTOM_OPENAI = "custom_openai"

    @classmethod
    def from_model_name(cls, model_name: str) -> "ModelProvider":
        """Infer provider from a model name string."""
        return _infer_provider_from_model_name(model_name)


def _infer_provider_from_model_name(model_name: str) -> ModelProvider:
    """Infer provider from model name pattern.

    Covers both prefixed names (``openrouter/auto``) and bare names
    (``deepseek-chat``, ``kimi-k2-0905``).
    """
    name = model_name.lower()
    # Known direct-provider prefixes (checked BEFORE the generic OpenRouter catch-all).
    # These have direct API adapters with provider-specific API keys.
    if name.startswith("deepseek/"):
        return ModelProvider.DEEPSEEK
    if name.startswith("moonshotai/") or name.startswith("moonshot/"):
        return ModelProvider.MOONSHOT
    if name.startswith("minimax/"):
        return ModelProvider.MINIMAX
    if name.startswith("recraft/"):
        return ModelProvider.RECRAFT
    if name.startswith("sourceful/"):
        return ModelProvider.SOURCEFUL
    if name.startswith("black-forest-labs/"):
        return ModelProvider.BLACK_FOREST_LABS
    if name.startswith("bytedance-seed/"):
        return ModelProvider.BYTEDANCE
    if name.startswith("microsoft/"):
        return ModelProvider.MICROSOFT
    if name.startswith("x-ai/"):
        return ModelProvider.XAI
    if name.startswith("poolside/"):
        return ModelProvider.POOLSIDE
    if name.startswith("claude/"):
        return ModelProvider.ANTHROPIC
    if name.startswith("gemini/") or name.startswith("google/"):
        return ModelProvider.GOOGLE
    if name.startswith("azure/"):
        return ModelProvider.AZURE
    if name.startswith("bedrock/"):
        return ModelProvider.AWS_BEDROCK
    # Remaining prefixed names → OpenRouter
    if name.startswith("openrouter/") or "/" in name:
        return ModelProvider.OPENROUTER
    # Bare names (direct provider model IDs)
    if name.startswith("gpt-"):
        return ModelProvider.OPENAI
    if name.startswith("claude-") or name.startswith("claude"):
        return ModelProvider.ANTHROPIC
    if name.startswith("deepseek"):
        return ModelProvider.DEEPSEEK
    if name.startswith("kimi-") or name.startswith("moonshot"):
        return ModelProvider.MOONSHOT
    if name.startswith("grok"):
        return ModelProvider.XAI
    if name.startswith("gemini") or name.startswith("google-"):
        return ModelProvider.GEMINI
    if name.startswith("mistral"):
        return ModelProvider.MISTRAL
    if name.startswith("llama") or name.startswith("qwen") or name.startswith("phi"):
        return ModelProvider.OLLAMA
    # Default to OpenAI for unknown models
    return ModelProvider.OPENAI


# ── Model metadata ──────────────────────────────────────────────────────────
# This module held a second, hand-written metadata catalog: 103 entries in one
# 1,339-line function, disagreeing with the generated catalog on 13 of the 14
# models the two shared (grok-4.3 at 131K context against 1M live, minimax-m3
# free against $0.0012/1k). Phase 3.2 made the generated OpenRouter catalog the
# one source; what this module still owns is provider inference above.

# Weebot routing variants, not OpenRouter model ids: `:thinking` is stripped by
# OpenAIAdapter before the request, `:nitro` / `:free` select a routing mode.
ROUTING_SUFFIXES = (":thinking", ":free", ":nitro")


def strip_routing_suffix(model_id: str) -> str:
    """``z-ai/glm-5.2:thinking`` -> ``z-ai/glm-5.2``."""
    for suffix in ROUTING_SUFFIXES:
        if model_id.endswith(suffix):
            return model_id[: -len(suffix)]
    return model_id


def get_model_config(model_id: str) -> ModelConfig | None:
    """Catalog metadata for *model_id*, or None when the catalog has no entry.

    Tries the id as given (``:free`` variants are catalog entries of their own),
    then without a routing suffix. None is "unknown", never a guessed default:
    a placeholder price or capability is indistinguishable from a real one at
    the call site (see D57 in tests/unit/test_latent_trap_fixes.py's history).
    """
    from weebot.config.model_catalog import MODELS

    return MODELS.get(model_id) or MODELS.get(strip_routing_suffix(model_id))
