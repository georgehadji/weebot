"""Hand-maintained corrections applied on top of the OpenRouter model list.

``_catalog.py`` is generated wholesale from OpenRouter's ``/api/v1/models``
response, so anything a human knows that the API does not say is destroyed by
the next regeneration. This module is where that knowledge lives instead.

``scripts/generate_catalog.py`` reads it and bakes the result into
``_catalog.py``. **Nothing imports this module at runtime** -- the generated
catalog remains the single thing the application loads -- so the values here
are plain primitives rather than ``ModelConfig``/``TaskType`` objects, and this
file adds no import edge to the package.

Three kinds of correction, in the order the generator applies them:

``EXTRA_MODELS``
    Models to add that the API response does not contain. Full ``ModelConfig``
    keyword arguments. Use for a model reachable through a provider-direct
    adapter, or one listed by OpenRouter under a different id.

``PINNED_FIELDS``
    Fields to force onto a model the API *does* return, overriding whatever was
    derived from the payload. Use where the derivation is known to be wrong for
    a specific model -- a mis-tiered model, a tool-use score measured by hand.

``SUPPRESSED_MODELS``
    Models to drop even though the API lists them. A deliberate removal is a
    decision; without recording it here, the next regeneration silently undoes
    it.

Every entry should say *why* it is here. An override with no rationale cannot
be retired later, because nobody can tell whether the thing it worked around
was ever fixed.
"""

from __future__ import annotations

# ── Models absent from the OpenRouter response ───────────────────────────────
#
# Provenance: these nineteen were added to _catalog.py by hand -- nine after the
# last self-consistent generation (343 entries, commit 21e177e1), plus the ten
# `~*-latest` aliases below, which predate it -- and would have been destroyed
# by the next `--write`. They are reproduced here verbatim so that a
# regeneration preserves them. Re-verify against the API when it is reachable:
# any that OpenRouter now lists should be deleted from this dict and allowed to
# come from the payload instead.
EXTRA_MODELS: dict[str, dict] = {
    "google/gemini-3.6-flash": {
        "name": "Google: Gemini 3.6 Flash",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.0045,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "REASONING",
            "AGENTIC", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 6,
    },
    "meituan/longcat-2.0": {
        "name": "Meituan: LongCat 2.0",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.00075,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "REASONING",
            "AGENTIC", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 6,
    },
    "meta/muse-spark-1.1": {
        "name": "Meta: Muse Spark 1.1",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.00275,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "AGENTIC", "REASONING", "CODE_REVIEW",
            "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 6,
    },
    "moonshotai/kimi-k3": {
        "name": "MoonshotAI: Kimi K3",
        "provider": "moonshot",
        "cost_per_1k_tokens": 0.009,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "DEBUGGING",
            "REASONING", "AGENTIC", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "PREMIUM",
        "api_key_env": "KIMI_API_KEY",
        "tool_use_score": 7,
    },
    "poolside/laguna-s-2.1": {
        "name": "Poolside: Laguna S 2.1",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.00015,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "AGENTIC",
            "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "FAST",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 6,
    },
    "qwen/qwen3.7-flash": {
        # $0.03/1M in + $0.13/1M out -- verified via OpenRouter API 2026-08-01.
        # 0.00008 is the *mean* of the two per-1k rates, not the max the
        # generator computes. See the cost-model note in generate_catalog.py.
        "name": "Qwen: Qwen3.7 Flash",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.00008,
        "context_window": 1000000,
        "strengths": ["CHAT", "REASONING", "CODE_REVIEW", "DOCUMENTATION"],
        "tier": "FAST",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "qwen/qwen3.8-max": {
        "name": "Qwen: Qwen3.8 Max",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.0037500000000000003,
        "context_window": 1000000,
        "strengths": [
            "CHAT", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "thinkingmachines/inkling": {
        "name": "Thinking Machines: Inkling",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.002525,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CODE_REVIEW", "REASONING", "AGENTIC",
            "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 6,
    },
    "thinkingmachines/inkling-small": {
        # $0.50/1M in + $1.20/1M out -- verified via OpenRouter API 2026-08-01.
        # 0.00085 is again the mean of the two per-1k rates.
        "name": "Thinking Machines: Inkling Small",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.00085,
        "context_window": 524288,
        "strengths": ["CHAT", "REASONING", "DOCUMENTATION"],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    # ── `~vendor/model-latest` floating aliases ──────────────────────────────
    #
    # These ten are a weebot convention, not OpenRouter ids: a stable name that
    # points at whatever the vendor currently ships. The API cannot return them,
    # so nothing in the payload will ever recreate them and a regeneration that
    # does not carry them here deletes all ten -- 3% of the catalog, far under
    # --max-shrink, so no guard would have fired. They were missed on the first
    # pass because the baseline they were diffed against (21e177e1) had been
    # hand-edited too, and already contained them.
    "~anthropic/claude-fable-latest": {
        "name": "Anthropic: Claude Fable Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.05,
        "context_window": 1000000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~anthropic/claude-haiku-latest": {
        "name": "Anthropic Claude Haiku Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.005,
        "context_window": 200000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~anthropic/claude-opus-latest": {
        "name": "Anthropic: Claude Opus Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.025,
        "context_window": 1000000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~anthropic/claude-sonnet-latest": {
        "name": "Anthropic Claude Sonnet Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.01,
        "context_window": 1000000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~google/gemini-flash-latest": {
        "name": "Google Gemini Flash Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.009000000000000001,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~google/gemini-pro-latest": {
        "name": "Google Gemini Pro Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.012,
        "context_window": 1048576,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~moonshotai/kimi-latest": {
        "name": "MoonshotAI Kimi Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.00341,
        "context_window": 262144,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~openai/gpt-latest": {
        "name": "OpenAI GPT Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.030000000000000002,
        "context_window": 1050000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~openai/gpt-mini-latest": {
        "name": "OpenAI GPT Mini Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.0045000000000000005,
        "context_window": 400000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
    "~x-ai/grok-latest": {
        "name": "xAI: Grok Latest",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.006,
        "context_window": 500000,
        "strengths": [
            "CHAT", "CREATIVE", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    },
}

# ── Field-level corrections to models the API does return ────────────────────
#
# Populate when a derived value is wrong for a named model, rather than
# special-casing it inside the generator: a rule in the generator applies to
# every model that happens to match it, an entry here applies to the one model
# somebody actually checked.
#
# The entries below exist because EXTRA_MODELS merges with ``setdefault``: the
# day OpenRouter starts listing one of those models, the payload-derived values
# win and the hand-measured ones are silently discarded. These three fields are
# exactly the ones the generator cannot derive -- ``determine_strengths`` has no
# rule that can ever emit AGENTIC, ``tier`` is inferred from cost alone (so
# PREMIUM is unreachable), and ``tool_use_score`` falls back to 5. Pinning them
# means the API can refresh price, context and name while the measured
# capabilities survive.
PINNED_FIELDS: dict[str, dict] = {
    "google/gemini-3.6-flash": {
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "REASONING", "AGENTIC", "DOCUMENTATION",
            "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "tool_use_score": 6,
    },
    "meituan/longcat-2.0": {
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "REASONING", "AGENTIC", "DOCUMENTATION",
            "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "tool_use_score": 6,
    },
    "meta/muse-spark-1.1": {
        "strengths": [
            "CHAT", "AGENTIC", "REASONING", "CODE_REVIEW", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "tool_use_score": 6,
    },
    "moonshotai/kimi-k3": {
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "DEBUGGING", "REASONING", "AGENTIC",
            "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "PREMIUM",
        "tool_use_score": 7,
    },
    "poolside/laguna-s-2.1": {
        "strengths": [
            "CHAT", "CODE_GENERATION", "CODE_REVIEW", "AGENTIC", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "FAST",
        "tool_use_score": 6,
    },
    "qwen/qwen3.7-flash": {
        "strengths": ["CHAT", "REASONING", "CODE_REVIEW", "DOCUMENTATION"],
        "tier": "FAST",
        "tool_use_score": 5,
    },
    "qwen/qwen3.8-max": {
        "strengths": ["CHAT", "CODE_REVIEW", "REASONING", "DOCUMENTATION", "ARCHITECTURE"],
        "tier": "STANDARD",
        "tool_use_score": 5,
    },
    "thinkingmachines/inkling": {
        "strengths": [
            "CHAT", "CODE_REVIEW", "REASONING", "AGENTIC", "DOCUMENTATION", "ARCHITECTURE",
        ],
        "tier": "STANDARD",
        "tool_use_score": 6,
    },
    "thinkingmachines/inkling-small": {
        "strengths": ["CHAT", "REASONING", "DOCUMENTATION"],
        "tier": "STANDARD",
        "tool_use_score": 5,
    },
}

# ── Models to drop even when the API lists them ──────────────────────────────
#
# qwen/qwen3.7-max was present in the 343-entry generation and removed by hand
# afterwards. Without this set, the next regeneration would bring it back, and
# the removal would have to be discovered and repeated. If the reason it was
# dropped no longer holds, delete it here -- do not delete it from _catalog.py.
SUPPRESSED_MODELS: set[str] = {
    "qwen/qwen3.7-max",
    # model_refs.py's module docstring states plainly that openrouter/auto is
    # FORBIDDEN. It was nonetheless in the catalog, and -- because OpenRouter
    # prices its meta-routers at -1 and the generator stored that as a real
    # rate of -1000.0 -- it *won* every cost-based selection, past any budget.
    # The pricing guard in generate_catalog.py now drops variable-priced models
    # on its own; this entry keeps the policy in force even if openrouter/auto
    # is one day given a real price.
    "openrouter/auto",
    # Removed alongside openrouter/auto in the same change, and for the same
    # reason: OpenRouter prices all four of its meta-routers at -1. The pricing
    # guard drops them on its own today, but a removal that rests only on a
    # heuristic is not recorded -- give any of these a real price upstream and
    # the next regeneration quietly brings it back.
    "openrouter/bodybuilder",
    "openrouter/fusion",
    "openrouter/pareto-code",
}
