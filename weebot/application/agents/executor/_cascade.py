"""CascadeExecutor — AI model cascade orchestration for ExecutorAgent.

Responsible for per-role model cascade: parallel probes → sequential fallback
→ live model rescue.  Extracted from the original ExecutorAgent god class to
isolate LLM-calling logic from step orchestration.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from weebot.application.di import Container
from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.models.tool_collection import ToolCollection
from weebot.config.constants import TEMPERATURE_BALANCED
from weebot.config.model_refs import MODEL_CASCADE_TIER2, MODEL_CASCADE_TIER3, MODEL_CASCADE_TIER4
from weebot.core.error_classifier import ErrorClassifier

# Import for ACR telemetry enrichment (Phase P0)
from weebot.core.model_cascade_tracker import (
    CascadeDecision,
    CascadeOutcome,
    CascadeTier,
    ModelCascadeTracker,
)

logger = logging.getLogger(__name__)


class CascadeExecutor:
    """Manages the per-role model cascade: parallel → sequential → rescue.

    Wraps circuit-breaker state, per-model timeouts, and fallback logic
    so ExecutorAgent.execute_step stays focused on orchestration.
    """

    # Default tier models when role cascade is not configured
    _TIER2_MODEL: str = MODEL_CASCADE_TIER2
    _TIER3_MODEL: str = MODEL_CASCADE_TIER3
    _TIER4_MODEL: str = MODEL_CASCADE_TIER4

    # OpenRouter credit threshold — below this (in tokens), skip
    # OpenRouter models to avoid 402 errors that waste cascade timeouts.
    # Override via OPENROUTER_MIN_CREDITS env var (default: 10000).
    _OPENROUTER_MIN_CREDITS: int = 10000

    @classmethod
    def _get_credit_threshold(cls) -> int:
        """Return the credit threshold, respecting env-var override."""
        import os as _os
        try:
            return int(_os.environ.get("OPENROUTER_MIN_CREDITS", cls._OPENROUTER_MIN_CREDITS))
        except (TypeError, ValueError):
            return cls._OPENROUTER_MIN_CREDITS

    _TASK_CATEGORY_CACHE: dict[str, str] = {}  # description → category lookup cache

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        agent_role: str | None = None,
        model_provider=None,  # Callable[[str], str | list[str] | None] — resolves step model(s)
        llm_pool: Any = None,  # Optional concurrency semaphore
        on_success=None,  # Optional callback after successful response
        tracker: ModelCascadeTracker | None = None,  # ACR telemetry sink (Phase P0)
        acr_router=None,  # Optional AdaptiveCapabilityRouter for outcome recording
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._agent_role = agent_role
        self._model_provider = model_provider
        self._llm_pool = llm_pool
        self._on_success = on_success
        self._tracker = tracker or ModelCascadeTracker()
        self._acr_router = acr_router  # Optional ACR router for bandit outcome recording
        # Per-session circuit breaker state
        self._circuit_breaker_failures: dict[str, int] = {}
        # Per-run: models that returned 5xx are skipped in current cascade
        self._server_error_models: set[str] = set()

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
        return self._circuit_breaker_failures.get(model_id, 0) >= 5

    def _cascade_record_failure(self, model_id: str) -> None:
        c = self._circuit_breaker_failures[model_id] = (
            self._circuit_breaker_failures.get(model_id, 0) + 1
        )
        if c >= 3:
            logger.warning("Circuit breaker tripped for %s", model_id)

    def _cascade_reset(self, model_id: str) -> None:
        self._circuit_breaker_failures[model_id] = 0

    # ── OpenRouter credit pre-check ────────────────────────────────

    @staticmethod
    async def _check_openrouter_credits() -> int:
        """Query OpenRouter's auth key endpoint for remaining credits.

        Returns:
            Remaining credits in tokens, or 0 if the check fails.
        """
        import os
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            return 0
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return int(data.get("data", {}).get("credits", 0))
                return 0
        except Exception:
            return 0  # fail open: assume OK on API error

    @staticmethod
    def _is_openrouter_model(model_id: str) -> bool:
        """Return True if the model routes exclusively through OpenRouter.

        Models with a native provider (x-ai, deepseek, moonshotai, minimax)
        do NOT exclusively use OpenRouter, so they should NOT be filtered.
        """
        known_direct = {"x-ai", "deepseek", "moonshotai", "minimax", "recraft"}
        prefix = model_id.split("/")[0] if "/" in model_id else ""
        return prefix not in known_direct

    @staticmethod
    async def get_credits_and_filter_direct(
        model_ids: list[str],
    ) -> list[str]:
        """Filter ``model_ids`` to only include non-OpenRouter models if
        credits are below threshold.  Returns all models on success.

        Used by the cascade to skip OpenRouter-dependent models when
        credits are too low to pay for a generation request.
        """
        threshold = CascadeExecutor._get_credit_threshold()
        credits = await CascadeExecutor._check_openrouter_credits()
        if credits >= threshold:
            return model_ids  # enough credits — use all models

        # Credits below threshold — filter out OpenRouter-only models
        filtered = [m for m in model_ids if not CascadeExecutor._is_openrouter_model(m)]
        if filtered != model_ids:
            skipped = len(model_ids) - len(filtered)
            logger.info(
                "OpenRouter credits low (%d — need %d), skipping %d "
                "OpenRouter-only model(s)",
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

    # ── Single model call (with retry + pool) ───────────────────────

    @staticmethod
    def _is_fast_fail_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(kw in msg for kw in (
            "404", "401", "403", "not found", "unauthorized",
            "permission denied", "invalid api key", "resource_not_found",
        ))

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
        start = _cascade_time.monotonic()
        pool = self._llm_pool

        async def _chat_with_pool():
            if pool is not None:
                async with pool:
                    return await asyncio.wait_for(
                        self._llm.chat(
                            messages=messages,
                            tools=self._tools.to_params(),
                            tool_choice="auto",
                            model=model_id,
                            temperature=TEMPERATURE_BALANCED,
                        ),
                        timeout=effective,
                    )
            return await asyncio.wait_for(
                self._llm.chat(
                    messages=messages,
                    tools=self._tools.to_params(),
                    tool_choice="auto",
                    model=model_id,
                    temperature=TEMPERATURE_BALANCED,
                ),
                timeout=effective,
            )

        try:
            resp = await _chat_with_pool()
            if resp and (resp.content or resp.tool_calls):
                elapsed = (_cascade_time.monotonic() - start) * 1000
                self._cascade_reset(model_id)
                logger.debug("Model %s succeeded in %.0fms", model_id, elapsed)
                self._record_decision(
                    model_name=model_id,
                    tier=tier,
                    outcome=CascadeOutcome.SUCCESS,
                    latency_ms=elapsed,
                    token_count=getattr(resp, "usage", {}).get("total_tokens", 0) if hasattr(resp, "usage") else 0,
                    task_category=task_category,
                )
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
        except asyncio.TimeoutError:
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
                # Fast-fail errors (401, 403, 404) are recorded as FAILED
                # but do NOT raise — the cascade must try other models.
                logger.warning("Fast-fail from %s: %s — suppressing to continue cascade",
                               model_id, str(exc)[:200])
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

    # ── Full cascade orchestration ──────────────────────────────────

    async def call_with_cascade(
        self,
        messages: list[dict[str, Any]],
        description: str = "",
    ) -> LLMResponse:
        """Per-role cascade: primary → fallback1 → fallback2 → tier3 → tier4.

        Phase 1 — parallel probes (90s timeout, first-completed wins).
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

        async def _try(model: str, tmo: float, *, tier: CascadeTier = CascadeTier.BUDGET) -> LLMResponse | None:
            nonlocal fast_fail
            resp = await self._cascade_try_chat(
                messages, model, tmo, fast_fail, first_error,
                tier=tier, task_category=task_category,
            )
            if resp is None and not fast_fail:
                if any(self._is_fast_fail_error(ee) for ee in first_error.values() if ee):
                    fast_fail = True
                    logger.warning(
                        "Fast-fail detected — reducing remaining cascade timeouts to 15s"
                    )
            return resp

        # ── Credit pre-check: filter OpenRouter models if low credits ──
        all_models = list(dict.fromkeys(
            m for m in (role_primary, *acr_models, task_model, role_fallback1) if m
        ))
        filtered_models = await self.get_credits_and_filter_direct(all_models)

        # ── Phase 1: parallel probes (90s timeout) ──────────────────
        parallel = list(dict.fromkeys(
            m for m in filtered_models if m not in self._server_error_models
        ))
        if parallel:
            tasks = {asyncio.ensure_future(_try(m, 90.0, tier=CascadeTier.FREE)): m for m in parallel}
            done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                resp = fut.result()
                if resp is not None:
                    for pf in pending:
                        pf.cancel()
                    for pf in pending:
                        if not pf.cancelled():
                            with contextlib.suppress(
                                asyncio.InvalidStateError, asyncio.CancelledError
                            ):
                                pf.exception()
                    if self._on_success:
                        await self._on_success(resp)
                    return resp

        # ── Phase 2: sequential fallback (60s) ──────────────────────
        remaining = [m for m in (role_fallback2, self._TIER4_MODEL)
                     if m and not self.cascade_is_tripped(m)
                     and m not in parallel
                     and m not in self._server_error_models]
        remaining_tiers = [CascadeTier.BUDGET, CascadeTier.PREMIUM]
        for m, t in zip(remaining, remaining_tiers[:len(remaining)]):
            resp = await _try(m, 60.0, tier=t)
            if resp is not None:
                if self._on_success:
                    await self._on_success(resp)
                return resp

        # ── Live model rescue (all-404) ─────────────────────────────
        if fast_fail and first_error and all(
            any(kw in (e or "").lower() for kw in ("404", "not found"))
            for e in first_error.values()
        ):
            rescue_model = await self._live_model_rescue(messages)
            if rescue_model is not None:
                if self._on_success:
                    await self._on_success(rescue_model)
                return rescue_model

        # ── Terminal ────────────────────────────────────────────────
        from weebot.domain.exceptions import AllModelsTrippedError
        raise AllModelsTrippedError(
            "All models in the cascade have tripped their circuit breakers. "
            "Check OpenRouter credits at https://openrouter.ai/credits"
        )

    # ── Live model rescue ───────────────────────────────────────────

    async def _live_model_rescue(
        self,
        messages: list[dict[str, Any]],
    ) -> LLMResponse | None:
        """Last-resort: fetch available models from OpenRouter and try the best.

        Prefers paid models with tools support; falls back to free models only
        if no paid models are available.
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://openrouter.ai/api/v1/models")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Live model rescue: failed to fetch model list: %s", exc)
            return None

        paid_models: list[dict] = []
        free_models: list[dict] = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            params = m.get("supported_parameters", [])
            if "tools" not in params:
                continue
            ctx = m.get("context_length", 0)
            entry = {"id": mid, "ctx": ctx}
            if ":free" in mid:
                free_models.append(entry)
            else:
                paid_models.append(entry)

        # Prefer paid models; fall back to free only as absolute last resort
        candidates = paid_models if paid_models else free_models

        if not candidates:
            logger.warning("Live model rescue: no models with tools support found")
            return None

        candidates.sort(key=lambda m: m["ctx"], reverse=True)
        rescue_id = candidates[0]["id"]
        logger.warning(
            "Live model rescue: trying %s (from %d paid + %d free candidates)",
            rescue_id, len(paid_models), len(free_models),
        )

        try:
            c = Container()
            c.configure_defaults()
            llm = c.get(LLMPort)
            resp = await asyncio.wait_for(
                llm.chat(
                    messages=messages,
                    model=rescue_id,
                    temperature=TEMPERATURE_BALANCED,
                ),
                timeout=30.0,
            )
            if resp and (resp.content or resp.tool_calls):
                logger.info("Live model rescue SUCCESS with %s", rescue_id)
                return resp
        except Exception as exc:
            logger.warning("Live model rescue failed with %s: %s", rescue_id, exc)

        return None
