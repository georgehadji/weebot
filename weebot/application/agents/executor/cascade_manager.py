"""CascadeManager — model fallback, circuit breaker, and retry orchestration.

Extracted from ExecutorAgent (weebot/application/agents/executor.py) as part
of H1 decomposition. Reduces the God class by ~200 lines.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.config.constants import TEMPERATURE_BALANCED
from weebot.config.model_refs import (
    MODEL_CASCADE_TIER2,
    MODEL_CASCADE_TIER3,
    MODEL_CASCADE_TIER4,
    MODEL_CODE_REVIEW,
    get_model_cascade_for_role,
)
from weebot.core.error_classifier import ErrorClassifier
from weebot.domain.exceptions import AllModelsTrippedError
from weebot.application.models.tool_collection import ToolCollection

logger = logging.getLogger(__name__)


class CascadeManager:
    """Manages the model cascade: primary → fallback → rescue.

    Handles circuit breaker state tracking per session, fast-fail detection,
    parallel model racing, sequential fallback, and live model refresh.
    """

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        agent_role: str = "admin",
        review_model: Optional[str] = None,
        tier2: Optional[str] = None,
        tier3: Optional[str] = None,
        tier4: Optional[str] = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._agent_role = agent_role
        self._REVIEW_MODEL = review_model or MODEL_CODE_REVIEW
        self._TIER2_MODEL = tier2 or MODEL_CASCADE_TIER2
        self._TIER3_MODEL = tier3 or MODEL_CASCADE_TIER3
        self._TIER4_MODEL = tier4 or MODEL_CASCADE_TIER4

        # Circuit breaker: track consecutive failures per model
        self._circuit_breaker_failures: dict[str, int] = {}
        # First-error tracking per model for diagnostics
        self._first_error: dict[str, str] = {}
        # Fast-fail flag: if set, reduce cascade timeouts to 15s
        self._fast_fail_detected: bool = False

    # ── Public API ─────────────────────────────────────────────────

    async def call_with_cascade(
        self,
        messages: List[Dict[str, Any]],
        description: str = "",
        is_review: bool = False,
        track_usage_callback=None,
    ) -> LLMResponse:
        """Execute model cascade: parallel phase → sequential → rescue.

        Args:
            messages: Chat messages to send.
            description: Step description for model selection.
            is_review: If True, use the review model as tier2.
            track_usage_callback: Optional async callback(resp) for usage tracking.

        Returns:
            LLMResponse from the first successful model.

        Raises:
            AllModelsTrippedError: If all models fail.
        """
        tier2_model = self._REVIEW_MODEL if is_review else self._TIER2_MODEL

        # ── Per-role model cascade ──────────────────────────────────
        role_cascade = get_model_cascade_for_role(self._agent_role)
        role_primary = role_cascade[0]
        role_fallback1 = role_cascade[1] if len(role_cascade) > 1 else self._TIER2_MODEL
        role_fallback2 = role_cascade[2] if len(role_cascade) > 2 else self._TIER3_MODEL

        # ── Phase 1: fire role-primary + role-fallback1 in parallel (90s) ──
        parallel_models: list[str] = []
        for m in (role_primary, role_fallback1):
            if m and m not in parallel_models:
                parallel_models.append(m)

        tasks = {
            asyncio.ensure_future(self._try_chat(messages, m, timeout=90.0)): m
            for m in parallel_models
        }
        if tasks:
            done, _pending = await asyncio.wait(
                tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for fut in done:
                resp = fut.result()
                if resp is not None:
                    for pf in _pending:
                        pf.cancel()
                    for pf in _pending:
                        if pf.cancelled():
                            continue
                        try:
                            exc = pf.exception()
                        except asyncio.InvalidStateError:
                            continue
                        if exc is not None:
                            logger.debug(
                                "Suppressed exception from cancelled cascade task: %s", exc,
                            )
                    if track_usage_callback:
                        await track_usage_callback(resp)
                    return resp

        # ── Phase 2: sequential — role-fallback2 → tier4 (60s timeout) ──
        remaining = [
            m for m in (role_fallback2, self._TIER4_MODEL)
            if m and not self._is_tripped(m) and m not in parallel_models
        ]
        for model_id in remaining:
            resp = await self._try_chat(messages, model_id, timeout=60.0)
            if resp is not None:
                if track_usage_callback:
                    await track_usage_callback(resp)
                return resp

        # ── Live model refresh fallback (all-404 rescue) ──────────
        if self._fast_fail_detected and self._first_error and all(
            any(kw in (err or "").lower() for kw in ("404", "not found"))
            for err in self._first_error.values()
        ):
            rescue_model = await self._try_live_model_rescue(messages)
            if rescue_model is not None:
                if track_usage_callback:
                    await track_usage_callback(rescue_model)
                return rescue_model

        raise AllModelsTrippedError(
            f"All models in the cascade have tripped their circuit breakers. "
            f"Check OpenRouter credits at https://openrouter.ai/credits"
        )

    def reset_failures(self) -> None:
        """Reset all circuit breaker counters (e.g. on new step)."""
        self._circuit_breaker_failures.clear()
        self._first_error.clear()
        self._fast_fail_detected = False

    # ── Internal circuit breaker ───────────────────────────────────

    def _is_tripped(self, model_id: str) -> bool:
        return self._circuit_breaker_failures.get(model_id, 0) >= 5

    def _record_failure(self, model_id: str) -> None:
        self._circuit_breaker_failures[model_id] = (
            self._circuit_breaker_failures.get(model_id, 0) + 1
        )
        if self._circuit_breaker_failures[model_id] >= 3:
            logger.warning("Circuit breaker tripped for %s", model_id)

    @staticmethod
    def _is_fast_fail_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(kw in msg for kw in (
            "404", "401", "403", "not found", "unauthorized",
            "permission denied", "invalid api key", "resource_not_found",
        ))

    # ── Internal chat helper ───────────────────────────────────────

    async def _try_chat(
        self,
        messages: List[Dict[str, Any]],
        model_id: str,
        timeout: float = 15.0,
    ) -> Optional[LLMResponse]:
        if self._is_tripped(model_id):
            return None
        effective_timeout = min(timeout, 15.0) if self._fast_fail_detected else timeout
        try:
            resp = await asyncio.wait_for(
                self._llm.chat(
                    messages=messages,
                    tools=self._tools.to_params(),
                    tool_choice="auto",
                    model=model_id,
                    temperature=TEMPERATURE_BALANCED,
                ),
                timeout=effective_timeout,
            )
            if resp and (resp.content or resp.tool_calls):
                self._circuit_breaker_failures[model_id] = 0
                return resp
            return None
        except asyncio.TimeoutError:
            logger.debug("Model %s timed out (%.1fs)", model_id, effective_timeout)
            return None
        except Exception as exc:
            if ErrorClassifier.should_fail_fast(exc):
                raise
            if not self._fast_fail_detected and self._is_fast_fail_error(exc):
                self._fast_fail_detected = True
                logger.warning(
                    "Fast-fail detected (%s on %s) — reducing cascade timeouts to 15s",
                    type(exc).__name__, model_id,
                )
            if model_id not in self._first_error:
                err_detail = str(exc)[:300] if str(exc) else type(exc).__name__
                self._first_error[model_id] = err_detail
                logger.warning("Model %s first error: %s", model_id, err_detail)
            else:
                logger.debug("Model %s failed: %s", model_id, exc)
            self._record_failure(model_id)
            return None

    # ── Live rescue ────────────────────────────────────────────────

    @staticmethod
    async def _try_live_model_rescue(
        messages: List[Dict[str, Any]],
    ) -> Optional[LLMResponse]:
        """Fetch current free models from OpenRouter as last-resort fallback.

        Used when every model in the configured cascade returned 404/not-found,
        indicating the model IDs may be globally stale.
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://openrouter.ai/api/v1/models")
                if resp.status_code != 200:
                    logger.warning("Live model refresh failed: HTTP %s", resp.status_code)
                    return None
                data = resp.json()
                free_models = [
                    m["id"] for m in data.get("data", [])
                    if m.get("pricing", {}).get("prompt") == "0"
                ]
                if not free_models:
                    logger.warning("Live model refresh: no free models found")
                    return None
                logger.info(
                    "Attempting live rescue with free model: %s", free_models[0]
                )
                return None  # Placeholder — caller must attempt the rescue
        except Exception as exc:
            logger.warning("Live model refresh failed: %s", exc)
            return None
