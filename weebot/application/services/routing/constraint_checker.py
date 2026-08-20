"""ConstraintChecker — hard-gate filter for model candidates.

Applies three gates in order, returning only the models that pass all of them:

1. **Capability flags** — checks ``supports_function_calling`` and
   ``supports_vision`` against the ``TaskRequirement``.  Fails **closed**
   (missing capability → model excluded).

2. **Context fit** — checks that the estimated input tokens fit within the
   model's ``max_input_tokens``.  Fails closed for known estimates; skipped
   when ``context_tokens=0`` (unknown).

3. **Availability** — checks circuit-breaker state via the ``is_tripped``
   callback.  Fails **open** on probe error (if the callback raises, the
   model is *kept* to avoid deadlocking the cascade).

Gate order matters: capability and context checks are cheap lookups; the
availability check is potentially more expensive and runs last so cheap
filtering happens first.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from weebot.config.model_registry import get_model_info
from weebot.domain.models.capability import TaskRequirement

logger = logging.getLogger(__name__)


class ConstraintChecker:
    """Hard-gate filter for model candidates.

    Args:
        is_tripped: Optional callback ``(model_id) -> bool`` that returns
            ``True`` if the model's circuit breaker is open.  When omitted,
            the availability gate is skipped.
        estimate_context: Optional callback ``() -> int`` returning an
            estimate of the context length for the current call.  Defaults
            to returning 0 (no context check).
    """

    def __init__(
        self,
        is_tripped: Callable[[str], bool] | None = None,
        estimate_context: Callable[[], int] | None = None,
    ) -> None:
        self._is_tripped = is_tripped
        self._estimate_context = estimate_context or (lambda: 0)

    # ── Public API ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_model_info(model_id: str):
        """Resolve model info, trying both prefixed and unprefixed names.

        The CATEGORY_MODEL map uses ``provider/name`` format (OpenRouter-style)
        while the internal registry sometimes uses just ``name``.
        """
        info = get_model_info(model_id)
        if info is not None:
            return info
        # Try stripping the provider prefix
        if "/" in model_id:
            short_name = model_id.split("/", 1)[1]
            info = get_model_info(short_name)
            if info is not None:
                return info
        # Try prepending "openrouter/"
        alt = f"openrouter/{model_id}"
        return get_model_info(alt)

    def eligible(
        self, candidates: list[str], requirement: TaskRequirement, context_tokens: int = 0
    ) -> list[str]:
        """Return the subset of *candidates* that pass all hard gates.

        Models that fail any gate are logged at ``DEBUG`` level and excluded.

        Args:
            candidates: Model IDs to filter.
            requirement: Hard constraints from the task category.
            context_tokens: Estimated input tokens for this call (0 = unknown).

        Returns:
            List of eligible model IDs (preserving input order).
        """
        # Gate 1: capability flags
        cap_gated: list[str] = []
        for model_id in candidates:
            info = self._resolve_model_info(model_id)
            if info is None:
                logger.debug("ConstraintChecker: no ModelInfo for %s — excluding", model_id)
                continue
            if requirement.requires_tools and not info.supports_function_calling:
                logger.debug("ConstraintChecker: %s lacks function_calling — excluding", model_id)
                continue
            if requirement.requires_vision and not info.supports_vision:
                logger.debug("ConstraintChecker: %s lacks vision — excluding", model_id)
                continue
            cap_gated.append(model_id)

        # Gate 2: context fit
        effective_ctx = context_tokens or self._estimate_context()
        ctx_gated: list[str] = []
        if effective_ctx > 0:
            for model_id in cap_gated:
                info = self._resolve_model_info(model_id)
                if info is None:
                    continue  # already filtered above, but guard against race
                if effective_ctx > info.max_input_tokens:
                    logger.debug(
                        "ConstraintChecker: %s max_input=%d < required=%d — excluding",
                        model_id,
                        info.max_input_tokens,
                        effective_ctx,
                    )
                    continue
                ctx_gated.append(model_id)
        else:
            ctx_gated = cap_gated  # unknown context — skip the gate

        # Gate 3: availability (fail-open)
        if self._is_tripped is None:
            return ctx_gated  # no availability gate

        avail_gated: list[str] = []
        for model_id in ctx_gated:
            try:
                if self._is_tripped(model_id):
                    logger.debug("ConstraintChecker: %s breaker tripped — excluding", model_id)
                    continue
            except Exception:
                logger.debug(
                    "ConstraintChecker: is_tripped probe failed for %s — " "keeping (fail-open)",
                    model_id,
                )
            avail_gated.append(model_id)

        return avail_gated

    @staticmethod
    def estimate_context_tokens(
        messages: list[dict],
        tokens_per_message: int = 4,
        tokens_per_name: int = 1,
        tokens_per_char: float = 0.25,
    ) -> int:
        """Roughly estimate the number of input tokens for a message list.

        Uses a heuristic approximation (4 tokens base per message + name
        tokens + character count / 4).  This is intentionally crude — exact
        token counts require a tokenizer, which is too expensive inside the
        constraint checker.

        Args:
            messages: The message list to estimate.
            tokens_per_message: Base tokens per message (default 4).
            tokens_per_name: Extra tokens if the message has a ``name`` field.
            tokens_per_char: Tokens per character (default 0.25 ≈ 4 chars/token).

        Returns:
            Estimated token count.
        """
        total = 0
        for msg in messages:
            total += tokens_per_message
            if msg.get("name"):
                total += tokens_per_name
            content = msg.get("content", "")
            if isinstance(content, str):
                total += int(len(content) * tokens_per_char)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "") or part.get("image_url", {}).get("url", "")
                        if isinstance(text, str):
                            total += int(len(text) * tokens_per_char)
        return max(total, 1)
