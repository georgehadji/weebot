"""CascadeExecutor — AI model cascade orchestration for ExecutorAgent.

Responsible for per-role model cascade: parallel probes → sequential fallback
→ live model rescue.  Extracted from the original ExecutorAgent god class to
isolate LLM-calling logic from step orchestration.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from weebot.core.model_cascade_config import estimate_cost as _estimate_cost
from weebot.utils.backoff import deadline_scope
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.application.ports.provider_account_port import ProviderAccountPort
    from weebot.application.strategies.llm_pool import LLMPool

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.models.tool_collection import ToolCollection
from weebot.config.constants import TEMPERATURE_BALANCED
from weebot.config.model_refs import MODEL_CASCADE_TIER2, MODEL_CASCADE_TIER3, MODEL_CASCADE_TIER4
from weebot.config.token_bounds import completion_bound
from weebot.core.error_classifier import ErrorClassifier
from weebot.application.strategies.llm_pool import unwrap_llm

# Import for ACR telemetry enrichment (Phase P0)
from weebot.core.model_cascade_tracker import (
    CascadeDecision,
    CascadeOutcome,
    CascadeTier,
    ModelCascadeTracker,
)

logger = logging.getLogger(__name__)

# `ExecutingState` matches the first sentence to skip a replan that cannot help.
ALL_MODELS_TRIPPED_MESSAGE = (
    "All models in the cascade have tripped their circuit breakers. "
    "Check the provider API key and the model names, and the account credits "
    "(https://openrouter.ai/credits for OpenRouter)."
)


class CascadeExecutor:
    """Manages the per-role model cascade: parallel → sequential → rescue.

    Wraps circuit-breaker state, per-model timeouts, and fallback logic
    so ExecutorAgent.execute_step stays focused on orchestration.
    """

    # Default tier models when role cascade is not configured
    _TIER2_MODEL: str = MODEL_CASCADE_TIER2
    _TIER3_MODEL: str = MODEL_CASCADE_TIER3
    _TIER4_MODEL: str = MODEL_CASCADE_TIER4

    # OpenRouter balance (USD, as /auth/key reports it) below which the
    # cascade skips OpenRouter-only models to avoid 402s that waste timeouts.
    # Override via OPENROUTER_MIN_CREDIT_USD. It used to be 10000 "tokens"
    # compared with a field OpenRouter does not send, so it always tripped.
    _OPENROUTER_MIN_CREDIT_USD: float = 0.10
    # Seconds a Phase 1 probe runs alone before the next one is started.
    _HEDGE_DELAY_S: float = 20.0
    # Consecutive failures after which a model is skipped for the rest of the session,
    # and the earlier count at which the log starts warning about it.
    _BREAKER_TRIP_AT: int = 5
    _BREAKER_WARN_AT: int = 3

    @classmethod
    def _get_credit_threshold(cls) -> float:
        """Return the credit threshold in USD, respecting env-var override."""
        import os as _os

        try:
            return float(
                _os.environ.get("OPENROUTER_MIN_CREDIT_USD", cls._OPENROUTER_MIN_CREDIT_USD)
            )
        except (TypeError, ValueError):
            return cls._OPENROUTER_MIN_CREDIT_USD

    _TASK_CATEGORY_CACHE: dict[str, str] = {}  # description → category lookup cache

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        agent_role: str | None = None,
        model_provider=None,  # Callable[[str], str | list[str] | None] — resolves step model(s)
        llm_pool: LLMPool | None = None,  # Global LLM concurrency bound (see llm_pool.py)
        on_success=None,  # Optional callback after successful response
        tracker: ModelCascadeTracker | None = None,  # ACR telemetry sink (Phase P0)
        acr_router=None,  # Optional AdaptiveCapabilityRouter for outcome recording
        # Credit balance + live model list. None: no credit filtering, no rescue.
        provider_account: ProviderAccountPort | None = None,
        # Awaited with an LLMCallCompleted after each successful call (W4.1, F23).
        on_call_completed=None,
        pinned_model: str | None = None,  # `flow run --model`: tried before the role cascade
        # SessionCostMeter: past the soft limit PREMIUM models are skipped (plan 2.4, D6).
        cost_meter=None,
    ) -> None:
        self._cost_meter = cost_meter
        self._llm = llm
        self._tools = tools
        self._agent_role = agent_role
        self._model_provider = model_provider
        self._pinned_model = pinned_model
        self._llm_pool = llm_pool
        self._on_success = on_success
        self._tracker = tracker or ModelCascadeTracker()
        self._acr_router = acr_router  # Optional ACR router for bandit outcome recording
        self._provider_account = provider_account
        self._on_call_completed = on_call_completed
        # Per-session circuit breaker state
        self._circuit_breaker_failures: dict[str, int] = {}
        # Per-run: models that returned 5xx are skipped in current cascade
        self._server_error_models: set[str] = set()
        # E1: resolved once, from the adapter, so both call sites pass the same number
        # the adapter would otherwise have chosen for itself (see config/token_bounds).
        self._completion_bound = completion_bound(unwrap_llm(llm))

    @staticmethod
    def _classify_description(description: str) -> str:
        """Return the task category for *description*, cached.

        Uses ``task_model_router.category_for_step`` for classification.
        Once computed for a description, the result is cached in a class-level
        dict for the lifetime of the process.
        """
        if not description:
            return "general"
        cached = CascadeExecutor._TASK_CATEGORY_CACHE.get(description)
        if cached is not None:
            return cached
        try:
            from weebot.application.services.task_model_router import category_for_step

            cat = category_for_step(description)
        except Exception:
            cat = "general"
        CascadeExecutor._TASK_CATEGORY_CACHE[description] = cat
        return cat

    # ── Circuit breaker helpers ─────────────────────────────────────

    def cascade_is_tripped(self, model_id: str) -> bool:
        """Return True if *model_id* has tripped its per-session breaker."""
        return self._circuit_breaker_failures.get(model_id, 0) >= self._BREAKER_TRIP_AT

    def _cascade_record_failure(self, model_id: str) -> None:
        c = self._circuit_breaker_failures[model_id] = (
            self._circuit_breaker_failures.get(model_id, 0) + 1
        )
        if c >= self._BREAKER_TRIP_AT:
            logger.warning("Circuit breaker tripped for %s after %d failures", model_id, c)
        elif c >= self._BREAKER_WARN_AT:
            logger.warning(
                "Circuit breaker warning for %s: %d failures in a row (trips at %d)",
                model_id, c, self._BREAKER_TRIP_AT,
            )

    def _cascade_reset(self, model_id: str) -> None:
        self._circuit_breaker_failures[model_id] = 0

    # ── OpenRouter credit pre-check ────────────────────────────────

    async def _remaining_credits(self) -> float | None:
        """Remaining OpenRouter credit, or None when unknown or not wired."""
        if self._provider_account is None:
            return None
        return await self._provider_account.remaining_credits()

    @staticmethod
    def _is_openrouter_model(model_id: str) -> bool:
        """Return True if the model routes exclusively through OpenRouter.

        Models with a native adapter (x-ai, deepseek, moonshotai, recraft) do
        NOT exclusively use OpenRouter, so they should NOT be filtered. minimax
        is not one: its adapter only reaches OpenRouter (adapter_factory).
        """
        # "ollama" is local: it needs no OpenRouter credit, so a low balance must not drop it.
        known_direct = {"x-ai", "deepseek", "moonshotai", "recraft", "ollama"}
        prefix = model_id.split("/")[0] if "/" in model_id else ""
        return prefix not in known_direct

    async def get_credits_and_filter_direct(self, model_ids: list[str]) -> list[str]:
        """Filter ``model_ids`` to only include non-OpenRouter models if
        credits are below threshold.  Returns all models on success.

        Used by the cascade to skip OpenRouter-dependent models when
        credits are too low to pay for a generation request.
        """
        threshold = CascadeExecutor._get_credit_threshold()
        credits = await self._remaining_credits()
        if credits is None:
            # Unknown credits: try the models and let a real out-of-credits
            # response fall through to the next tier, which is what the cascade
            # exists to do. Dropping models on a failed check degrades quality
            # for a network blip.
            logger.debug("OpenRouter credit check unavailable — not filtering")
            return model_ids
        if credits >= threshold:
            return model_ids  # enough credits — use all models

        # Credits below threshold — filter out OpenRouter-only models
        filtered = [m for m in model_ids if not CascadeExecutor._is_openrouter_model(m)]
        if filtered != model_ids:
            skipped = len(model_ids) - len(filtered)
            logger.info(
                "OpenRouter balance low ($%.2f, need $%.2f), skipping %d OpenRouter-only model(s)",
                credits,
                threshold,
                skipped,
            )
        return filtered

    def _record_decision(
        self,
        model_name: str,
        tier: CascadeTier,
        outcome: CascadeOutcome,
        latency_ms: float,
        token_count: int = 0,
        cost_estimate: float = 0.0,
        error_message: str = "",
        task_category: str = "general",
    ) -> None:
        """Record a cascade decision to the tracker, and to the ACR router if wired."""
        decision = CascadeDecision(
            model_name=model_name,
            tier=tier,
            outcome=outcome,
            latency_ms=latency_ms,
            token_count=token_count,
            cost_estimate=cost_estimate,
            error_message=error_message,
            task_category=task_category,
        )
        self._tracker.record(decision)
        if self._acr_router is not None:
            self._acr_router.record_cascade_outcome(decision)

    async def _call_completed(
        self, model_id: str, prompt_tokens: int, completion_tokens: int, cached_prompt: int = 0
    ) -> None:
        """Report one successful call; the hook must never fail the call."""
        if self._on_call_completed is None:
            return
        from weebot.domain.models.event import LLMCallCompleted

        try:
            await self._on_call_completed(
                LLMCallCompleted(
                    model=model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost=_estimate_cost(
                        model_id, prompt_tokens, completion_tokens, cached_prompt=cached_prompt
                    ),
                )
            )
        except Exception:
            logger.warning("LLMCallCompleted hook failed for %s", model_id, exc_info=True)

    @staticmethod
    def _usage_tokens(resp: LLMResponse) -> tuple[int, int]:
        usage = getattr(resp, "usage", None) or {}
        return (
            int(usage.get("prompt_tokens", 0) or 0),
            int(usage.get("completion_tokens", 0) or 0),
        )

    # ── Single model call (with retry + pool) ───────────────────────

    @staticmethod
    def _is_fast_fail_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            kw in msg
            for kw in (
                "404",
                "401",
                "403",
                "not found",
                "unauthorized",
                "permission denied",
                "invalid api key",
                "resource_not_found",
            )
        )

    async def _cascade_try_chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str,
        timeout: float = 15.0,
        fast_fail: bool = False,
        first_error: dict[str, str] | None = None,
        *,
        tier: CascadeTier = CascadeTier.BUDGET,
        task_category: str = "general",
    ) -> LLMResponse | None:
        """Hold an LLM concurrency slot around one model attempt.

        The slot is acquired HERE, before the attempt's latency clock starts
        and outside its ``wait_for``. Time spent queuing for a slot is not the
        model's latency and must not count against the model's timeout --
        otherwise, under load, a 15s fast-fail budget expires in the queue and
        a healthy model is recorded as having timed out.

        ``LLMCapacityExhaustedError`` from the pool propagates out of this
        method on purpose. It never reaches the per-model handlers in
        ``_cascade_try_chat_unpooled``, so saturation is not charged to any
        model, and it stops the cascade rather than queuing every remaining
        model behind the same full pool.

        A tripped model skips the queue: it returns without calling anything,
        so waiting for a slot to do nothing would only take one from a caller
        that needs it.
        """
        kwargs = dict(
            timeout=timeout,
            fast_fail=fast_fail,
            first_error=first_error,
            tier=tier,
            task_category=task_category,
        )
        if self._llm_pool is None or self.cascade_is_tripped(model_id):
            return await self._cascade_try_chat_unpooled(messages, model_id, **kwargs)
        async with self._llm_pool:
            return await self._cascade_try_chat_unpooled(messages, model_id, **kwargs)

    async def _cascade_try_chat_unpooled(
        self,
        messages: list[dict[str, Any]],
        model_id: str,
        timeout: float = 15.0,
        fast_fail: bool = False,
        first_error: dict[str, str] | None = None,
        *,
        tier: CascadeTier = CascadeTier.BUDGET,
        task_category: str = "general",
    ) -> LLMResponse | None:
        """Try a single model call with tiered timeout.

        Returns LLMResponse on success, None on transient failure,
        raises on fatal errors (auth, context length).

        Records a CascadeDecision via the internal tracker.
        """
        import time as _cascade_time

        if self.cascade_is_tripped(model_id):
            self._record_decision(
                model_name=model_id,
                tier=tier,
                outcome=CascadeOutcome.CIRCUIT_OPEN,
                latency_ms=0.0,
                task_category=task_category,
            )
            return None
        effective = min(timeout, 15.0) if fast_fail else timeout
        # Starts only once the caller holds an LLM slot -- see _cascade_try_chat.
        start = _cascade_time.monotonic()

        try:
            # The retry layer below reads this deadline and stops scheduling retries
            # that could not finish inside it (ORCH-3), instead of sleeping into the
            # cancellation.
            with deadline_scope(effective):
                resp = await asyncio.wait_for(
                    self._llm.chat(
                        messages=messages,
                        tools=self._tools.to_params(),
                        tool_choice="auto",
                        model=model_id,
                        temperature=TEMPERATURE_BALANCED,
                        # The orchestrator owns the length bound now: resolved from the
                        # adapter (E1), so the number this call would have inherited is
                        # passed explicitly and lives in one named table.
                        max_tokens=self._completion_bound,
                    ),
                    timeout=effective,
                )
            if resp and (resp.content or resp.tool_calls):
                elapsed = (_cascade_time.monotonic() - start) * 1000
                self._cascade_reset(model_id)
                logger.debug("Model %s succeeded in %.0fms", model_id, elapsed)
                # `hasattr(resp, "usage")` was vacuous -- usage is a declared
                # field, so it is always present -- and four adapters set it to
                # None when a provider omits it, making `.get` raise on the
                # success path. The adapters themselves already use the correct
                # `getattr(response, "usage", None)` truthiness form.
                _usage = getattr(resp, "usage", None) or {}
                _prompt_tokens = int(_usage.get("prompt_tokens", 0) or 0)
                _completion_tokens = int(_usage.get("completion_tokens", 0) or 0)
                _cached = int(_usage.get("cached_tokens", 0) or 0)
                self._record_decision(
                    model_name=model_id,
                    tier=tier,
                    outcome=CascadeOutcome.SUCCESS,
                    latency_ms=elapsed,
                    token_count=int(
                        _usage.get("total_tokens", _prompt_tokens + _completion_tokens) or 0
                    ),
                    # No caller ever supplied this, so the tracker's
                    # total_cost_estimate was structurally 0.0 -- and
                    # mcp/resources.py:297 publishes that number as cost accounting.
                    cost_estimate=_estimate_cost(
                        model_id, _prompt_tokens, _completion_tokens, cached_prompt=_cached
                    ),
                    task_category=task_category,
                )
                await self._call_completed(model_id, _prompt_tokens, _completion_tokens, _cached)
                return resp
            elapsed = (_cascade_time.monotonic() - start) * 1000
            logger.debug("Model %s returned empty in %.0fms", model_id, elapsed)
            self._record_decision(
                model_name=model_id,
                tier=tier,
                outcome=CascadeOutcome.FAILED,
                latency_ms=elapsed,
                error_message="empty response",
                task_category=task_category,
            )
            return None
        except TimeoutError:
            elapsed = (_cascade_time.monotonic() - start) * 1000
            logger.debug("Model %s timed out after %.0fms", model_id, elapsed)
            self._record_decision(
                model_name=model_id,
                tier=tier,
                outcome=CascadeOutcome.FAILED,
                latency_ms=elapsed,
                error_message="timeout",
                task_category=task_category,
            )
            return None
        except Exception as exc:
            if ErrorClassifier.should_fail_fast(exc):
                # Fast-fail errors (401, bad key) do NOT raise — the cascade must
                # try other models — and fail the same way every time, so this
                # model is skipped for the rest of the run.
                logger.warning(
                    "Fast-fail from %s: %s — suppressing to continue cascade",
                    model_id,
                    str(exc)[:200],
                )
                self._server_error_models.add(model_id)
            else:
                if first_error is not None and model_id not in first_error:
                    first_error[model_id] = str(exc)[:300] or type(exc).__name__
                self._cascade_record_failure(model_id)
                # Track server errors so we skip this model in the current cascade run
                from weebot.core.error_classifier import ErrorCategory

                if ErrorClassifier.classify(exc) == ErrorCategory.SERVER_ERROR:
                    self._server_error_models.add(model_id)
                    logger.debug("Server error from %s — skipping for rest of cascade", model_id)
            elapsed = (_cascade_time.monotonic() - start) * 1000
            self._record_decision(
                model_name=model_id,
                tier=tier,
                outcome=CascadeOutcome.FAILED,
                latency_ms=elapsed,
                error_message=str(exc)[:200],
                task_category=task_category,
            )
            return None

    @staticmethod
    def _tier_of(model_id: str) -> CascadeTier:
        """The model's own cost tier, for telemetry and the ACR bandit."""
        from weebot.config.model_refs import PREMIUM_MODELS

        if ":free" in model_id:
            return CascadeTier.FREE
        return CascadeTier.PREMIUM if model_id in PREMIUM_MODELS else CascadeTier.BUDGET

    def _within_budget(self, models: list[str]) -> list[str]:
        """Past the soft cost limit drop PREMIUM models, but never empty the list (D6)."""
        if self._cost_meter is None:
            return models
        from weebot.core.log_context import session_id_var

        if not self._cost_meter.soft_exceeded(session_id_var.get()):
            return models
        cheaper = [m for m in models if not m or self._tier_of(m) is not CascadeTier.PREMIUM]
        if len(cheaper) < len(models) and any(cheaper):
            logger.info("soft cost limit: skipping %d PREMIUM model(s)", len(models) - len(cheaper))
            return cheaper
        return models

    # ── Full cascade orchestration ──────────────────────────────────

    async def call_with_cascade(
        self, messages: list[dict[str, Any]], description: str = ""
    ) -> LLMResponse:
        """Per-role cascade: primary → fallback1 → fallback2 → tier3 → tier4.

        Phase 1 — hedged probes: one runs (90s timeout); the next starts when it fails or
        after _HEDGE_DELAY_S without an answer; the first success wins.
        Phase 2 — sequential fallback (60s each).
        Phase 3 — live model rescue (all-404 fallback to OpenRouter free models).

        Raises:
            AllModelsTrippedError: if every model in the cascade failed.
        """
        from weebot.config.model_refs import get_model_cascade_for_role

        role_cascade = get_model_cascade_for_role(self._agent_role)
        role_primary = role_cascade[0]
        role_fallback1 = role_cascade[1] if len(role_cascade) > 1 else self._TIER2_MODEL
        role_fallback2 = role_cascade[2] if len(role_cascade) > 2 else self._TIER3_MODEL

        # model_provider returns a list (ACR) or a single model (static router)
        task_model_raw = self._model_provider(description) if self._model_provider else None
        if isinstance(task_model_raw, list):
            acr_models = task_model_raw  # ordered candidate list from ACR
            task_model = None
        else:
            acr_models = []
            task_model = task_model_raw

        # Classify the step description once for ACR telemetry
        task_category = self._classify_description(description)

        fast_fail: bool = False
        first_error: dict[str, str] = {}
        self._server_error_models.clear()  # fresh per-run set

        async def _try(
            model: str, tmo: float, *, tier: CascadeTier = CascadeTier.BUDGET
        ) -> LLMResponse | None:
            nonlocal fast_fail
            resp = await self._cascade_try_chat(
                messages, model, tmo, fast_fail, first_error, tier=tier, task_category=task_category
            )
            if resp is None and not fast_fail:
                if any(self._is_fast_fail_error(ee) for ee in first_error.values() if ee):
                    fast_fail = True
                    logger.warning(
                        "Fast-fail detected — reducing remaining cascade timeouts to 15s"
                    )
            return resp

        # ── Credit pre-check: filter OpenRouter models if low credits ──
        all_models = list(
            dict.fromkeys(
                m
                for m in (self._pinned_model, role_primary, *acr_models, task_model, role_fallback1)
                if m
            )
        )
        filtered_models = self._within_budget(await self.get_credits_and_filter_direct(all_models))

        # ── Phase 1: parallel probes (90s timeout) ──────────────────
        parallel = list(
            dict.fromkeys(m for m in filtered_models if m not in self._server_error_models)
        )
        if parallel:
            # Hedge, don't race: a non-streamed request cancelled client-side
            # still bills (measured: a call cancelled after 3s cost the full
            # completion), so starting every probe at once paid for all of
            # them on every call. One probe runs; the next starts when it
            # fails, or after _HEDGE_DELAY_S without an answer.
            queue = list(parallel)

            def _launch() -> asyncio.Future:
                model = queue.pop(0)
                return asyncio.ensure_future(_try(model, 90.0, tier=self._tier_of(model)))

            # Wait for a probe that actually SUCCEEDS, not merely one that
            # finishes first.
            #
            # `_cascade_try_chat` returns None for every failure and never
            # raises, and a 429 or 503 comes back in ~200ms against seconds for
            # a real completion — so the first future to complete is
            # preferentially the fastest *failure*. Cancellation used to live
            # inside the `resp is not None` branch, so that common case fell
            # through to Phase 2 with every probe still running. Measured on
            # this code with the fastest probe failing (five probes, two of
            # them slow successes):
            #
            #     requests sent  5     billed  5     cancelled  0
            #
            # Both slow probes had *succeeded*; their responses were discarded
            # and the cascade fell through to Phase 2 to buy the answer again.
            #
            # Waiting for a success instead spends the probes already paid for.
            # The cost is latency in exactly the case where escalating was the
            # alternative: worst case is the slowest probe's 90s cap rather than
            # the fastest probe's return.
            pending = {_launch()}
            winner = None
            try:
                while pending and winner is None:
                    done, pending = await asyncio.wait(
                        pending,
                        timeout=self._HEDGE_DELAY_S if queue else None,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for fut in done:
                        resp = fut.result()
                        if resp is not None:
                            winner = resp
                            break
                    if winner is None and queue:
                        pending.add(_launch())  # a failure, or the hedge delay ran out
            finally:
                # Always, on every exit: a probe left uncancelled runs to
                # completion and bills. The old drain loop below this was a
                # no-op — `pf.cancelled()` is still False immediately after
                # `cancel()`, and `pf.exception()` on a task that is not done
                # raises InvalidStateError, which the suppress swallowed.
                #
                # Bounded rather than gathered: `asyncio.wait` gives the
                # cancellations a chance to land without hanging the cascade on
                # an adapter that swallows CancelledError.
                for pf in pending:
                    pf.cancel()
                if pending:
                    await asyncio.wait(pending, timeout=5.0)

            if winner is not None:
                if self._on_success:
                    await self._on_success(winner)
                return winner

        # ── Phase 2: sequential fallback (60s) ──────────────────────
        remaining = [
            m
            for m in self._within_budget([role_fallback2, self._TIER4_MODEL])
            if m
            and not self.cascade_is_tripped(m)
            and m not in parallel
            and m not in self._server_error_models
        ]
        for m in remaining:
            resp = await _try(m, 60.0, tier=self._tier_of(m))
            if resp is not None:
                if self._on_success:
                    await self._on_success(resp)
                return resp

        # ── Live model rescue (all-404) ─────────────────────────────
        if (
            fast_fail
            and first_error
            and all(
                any(kw in (e or "").lower() for kw in ("404", "not found"))
                for e in first_error.values()
            )
        ):
            rescue_model = await self._live_model_rescue(messages)
            if rescue_model is not None:
                if self._on_success:
                    await self._on_success(rescue_model)
                return rescue_model

        # ── Terminal ────────────────────────────────────────────────
        from weebot.domain.exceptions import AllModelsTrippedError

        raise AllModelsTrippedError(ALL_MODELS_TRIPPED_MESSAGE)

    # ── Live model rescue ───────────────────────────────────────────

    async def _live_model_rescue(self, messages: list[dict[str, Any]]) -> LLMResponse | None:
        """Last-resort: fetch available models from OpenRouter and try the best.

        Prefers paid models with tools support; falls back to free models only
        if no paid models are available.
        """
        if self._provider_account is None:
            return None
        try:
            listings = await self._provider_account.list_models()
        except Exception as exc:
            logger.warning("Live model rescue: failed to fetch model list: %s", exc)
            return None

        paid_models: list[dict] = []
        free_models: list[dict] = []
        from weebot.config.model_refs import claude_model_allowed

        for m in listings:
            if not m.supports_tools or not claude_model_allowed(m.id):
                continue
            entry = {"id": m.id, "ctx": m.context_length}
            if ":free" in m.id:
                free_models.append(entry)
            else:
                paid_models.append(entry)

        # Prefer paid models; fall back to free only as absolute last resort
        candidates = paid_models if paid_models else free_models

        if not candidates:
            logger.warning("Live model rescue: no models with tools support found")
            return None

        # Cheapest catalog-priced model with a long enough context; unpriced
        # models last. Sorting by context alone picked premium models.
        from weebot.config.model_registry import get_model_config

        def _rank(m: dict) -> tuple:
            cfg = get_model_config(m["id"])
            cost = cfg.cost_per_1k_tokens if cfg is not None else None
            return (m["ctx"] < 128_000, cost is None, cost or 0.0, -m["ctx"])

        candidates.sort(key=_rank)
        rescue_id = candidates[0]["id"]
        logger.warning(
            "Live model rescue: trying %s (from %d paid + %d free candidates)",
            rescue_id,
            len(paid_models),
            len(free_models),
        )

        # This used to build a whole new Container per rescue and call its
        # LLMPort -- the same port as self._llm in the container's executor,
        # but outside the LLM pool, so the one request made when everything
        # else had failed was the one the concurrency bound never saw. Pool
        # exhaustion propagates, as it does from _cascade_try_chat.
        async with self._llm_pool or contextlib.nullcontext():
            try:
                resp = await asyncio.wait_for(
                    self._llm.chat(
                        messages=messages,
                        model=rescue_id,
                        temperature=TEMPERATURE_BALANCED,
                        max_tokens=self._completion_bound,
                    ),
                    timeout=30.0,
                )
                if resp and (resp.content or resp.tool_calls):
                    logger.info("Live model rescue SUCCESS with %s", rescue_id)
                    await self._call_completed(rescue_id, *self._usage_tokens(resp))
                    return resp
            except Exception as exc:
                logger.warning("Live model rescue failed with %s: %s", rescue_id, exc)

        return None
