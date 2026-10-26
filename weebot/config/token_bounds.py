"""The completion cap each LLM adapter applies when the caller passes none.

Why this exists (E1 of the 2026-10 wave-2 plan): the cascade called `chat()` without
`max_tokens` at two sites and let each adapter choose. The adapters chose differently --
16384 in `openai_adapter.py` and 4096 in `anthropic_adapter.py` -- so the orchestrator
that decides *which model to call* did not decide *how long the answer may be*, and the
bound lived in two unrelated files with no name.

This module does not change any of those numbers. It names them in one place and resolves
them by adapter type, so the cascade can pass the number the adapter would have used. An
adapter that is not listed gets `None`, which means "pass nothing", which means the
adapter decides exactly as it does today -- the mapping is opt-in per adapter rather than
a new default every path inherits.

Deliberately NOT here: one number for all providers. The two values differ by 4x, so
picking one would either cut the OpenAI path's ceiling by 8x or raise Anthropic's by 4x.
That is a spend decision, and it belongs to whoever sets the budget, not to a refactor.

This module takes an already-unwrapped adapter and imports nothing, so `config` stays
inner-most: the unwrapping lives in `llm_pool.unwrap_llm`, where the wrappers are known.
"""

from __future__ import annotations

from typing import Any

# Adapter class name (lower-cased, as matched by `completion_bound`) -> cap.
#
# The values are the adapters' current hard-coded defaults, so routing them through here
# is behaviour-preserving by construction. Changing one changes spend for that provider
# only, which is the point of having them in one table.
COMPLETION_TOKENS_BY_ADAPTER: dict[str, int] = {
    "anthropicadapter": 4096,  # anthropic_adapter.py: `max_tokens or 4096`
    "anthropicowningadapter": 4096,  # the caching wrapper around it
    "openaiadapter": 16384,  # openai_adapter.py: the OpenRouter free/credit default
    "openrouteradapter": 16384,
}


def completion_bound(adapter: Any) -> int | None:
    """The `max_tokens` the given adapter would apply, or `None` if unknown.

    `None` is the safe answer, not a failure: it means the caller passes no bound and the
    adapter keeps choosing, which is what every unlisted adapter does today.
    """
    if adapter is None:
        return None
    for cls in type(adapter).__mro__:
        bound = COMPLETION_TOKENS_BY_ADAPTER.get(cls.__name__.lower())
        if bound is not None:
            return bound
    return None
