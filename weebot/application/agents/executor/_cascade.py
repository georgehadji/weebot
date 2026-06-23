"""CascadeExecutor — AI model cascade orchestration for ExecutorAgent.

Responsible for per-role model cascade: parallel probes → sequential fallback
→ live model rescue.  Extracted from the original ExecutorAgent god class to
isolate LLM-calling logic from step orchestration.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from weebot.application.di import Container
from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.models.tool_collection import ToolCollection
from weebot.config.constants import TEMPERATURE_BALANCED
from weebot.config.model_refs import MODEL_CASCADE_TIER2, MODEL_CASCADE_TIER3, MODEL_CASCADE_TIER4
from weebot.core.error_classifier import ErrorClassifier

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

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        agent_role: str | None = None,
        model_provider=None,  # Callable[[str], str] — resolves step model
        llm_pool: Any = None,  # Optional concurrency semaphore
        on_success=None,  # Optional callback after successful response
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._agent_role = agent_role
        self._model_provider = model_provider
        self._llm_pool = llm_pool
        self._on_success = on_success
        # Per-session circuit breaker state
        self._circuit_breaker_failures: dict[str, int] = {}
        # Per-run: models that returned 5xx are skipped in current cascade
        self._server_error_models: set[str] = set()

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
        messages: List[Dict[str, Any]],
        model_id: str,
        timeout: float = 15.0,
        fast_fail: bool = False,
        first_error: dict[str, str] | None = None,
    ) -> LLMResponse | None:
        """Try a single model call with tiered timeout.

        Returns LLMResponse on success, None on transient failure,
        raises on fatal errors (auth, context length).
        """
        import time as _cascade_time

        if self.cascade_is_tripped(model_id):
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
                return resp
            elapsed = (_cascade_time.monotonic() - start) * 1000
            logger.debug("Model %s returned empty in %.0fms", model_id, elapsed)
            return None
        except asyncio.TimeoutError:
            elapsed = (_cascade_time.monotonic() - start) * 1000
            logger.debug("Model %s timed out after %.0fms", model_id, elapsed)
            return None
        except Exception as exc:
            if ErrorClassifier.should_fail_fast(exc):
                raise
            if first_error is not None and model_id not in first_error:
                first_error[model_id] = str(exc)[:300] or type(exc).__name__
            self._cascade_record_failure(model_id)
            # Track server errors so we skip this model in the current cascade run
            from weebot.core.error_classifier import ErrorCategory
            if ErrorClassifier.classify(exc) == ErrorCategory.SERVER_ERROR:
                self._server_error_models.add(model_id)
                logger.debug("Server error from %s — skipping for rest of cascade", model_id)
            return None

    # ── Full cascade orchestration ──────────────────────────────────

    async def call_with_cascade(
        self,
        messages: List[Dict[str, Any]],
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
        task_model = self._model_provider(description) if self._model_provider else None

        fast_fail: bool = False
        first_error: dict[str, str] = {}
        self._server_error_models.clear()  # fresh per-run set

        async def _try(model: str, tmo: float) -> LLMResponse | None:
            nonlocal fast_fail
            resp = await self._cascade_try_chat(messages, model, tmo, fast_fail, first_error)
            if resp is None and not fast_fail:
                if any(self._is_fast_fail_error(ee) for ee in first_error.values() if ee):
                    fast_fail = True
                    logger.warning(
                        "Fast-fail detected — reducing remaining cascade timeouts to 15s"
                    )
            return resp

        # ── Credit pre-check: filter OpenRouter models if low credits ──
        all_models = list(dict.fromkeys(
            m for m in (role_primary, task_model, role_fallback1) if m
        ))
        filtered_models = await self.get_credits_and_filter_direct(all_models)

        # ── Phase 1: parallel probes (90s timeout) ──────────────────
        parallel = list(dict.fromkeys(
            m for m in filtered_models if m not in self._server_error_models
        ))
        if parallel:
            tasks = {asyncio.ensure_future(_try(m, 90.0)): m for m in parallel}
            done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                resp = fut.result()
                if resp is not None:
                    for pf in pending:
                        pf.cancel()
                    for pf in pending:
                        if not pf.cancelled():
                            try:
                                pf.exception()
                            except (asyncio.InvalidStateError, asyncio.CancelledError):
                                pass
                    if self._on_success:
                        await self._on_success(resp)
                    return resp

        # ── Phase 2: sequential fallback (60s) ──────────────────────
        remaining = [m for m in (role_fallback2, self._TIER4_MODEL)
                     if m and not self.cascade_is_tripped(m)
                     and m not in parallel
                     and m not in self._server_error_models]
        for m in remaining:
            resp = await _try(m, 60.0)
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
        messages: List[Dict[str, Any]],
    ) -> LLMResponse | None:
        """Last-resort: fetch current free models from OpenRouter and try the first."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://openrouter.ai/api/v1/models")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Live model rescue: failed to fetch model list: %s", exc)
            return None

        free_models: list[dict] = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if ":free" not in mid:
                continue
            params = m.get("supported_parameters", [])
            if "tools" not in params:
                continue
            ctx = m.get("context_length", 0)
            free_models.append({"id": mid, "ctx": ctx})

        if not free_models:
            for m in data.get("data", []):
                if ":free" in m.get("id", ""):
                    free_models.append({"id": m["id"], "ctx": m.get("context_length", 0)})

        if not free_models:
            logger.warning("Live model rescue: no free models found")
            return None

        free_models.sort(key=lambda m: m["ctx"], reverse=True)
        rescue_id = free_models[0]["id"]
        logger.warning(
            "Live model rescue: trying %s (from %d live free models)",
            rescue_id, len(free_models),
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
