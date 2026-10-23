"""Hand-maintained corrections applied on top of the OpenRouter model list.

``model_catalog.py`` is generated wholesale from OpenRouter's ``/api/v1/models``
response, so anything a human knows that the API does not say is destroyed by
the next regeneration. This module is where that knowledge lives instead.

``scripts/generate_catalog.py`` reads it and bakes the result into
``model_catalog.py``. **Nothing imports this module at runtime** -- the generated
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
# Empty since 2026-10-23: OpenRouter lists all seventeen models that used to be
# here (the ten `~*-latest` aliases included), and EXTRA_MODELS merges with
# ``setdefault``, so the payload already won for every one of them. Their
# hand-measured fields live on in PINNED_FIELDS below. Add an entry again only
# for a model the API does not list, with the reason beside it.
EXTRA_MODELS: dict[str, dict] = {}

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
# dropped no longer holds, delete it here -- do not delete it from model_catalog.py.
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
