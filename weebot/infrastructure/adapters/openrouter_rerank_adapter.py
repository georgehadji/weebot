"""OpenRouterRerankAdapter — calls Cohere rerank models via OpenRouter.

Implements :class:`~weebot.application.ports.rerank_port.RerankPort` by
calling ``POST https://openrouter.ai/api/v1/rerank`` with the standard
Cohere-compatible JSON body.

All rerank models use ``text->rerank`` modality — they are NOT chat models
and cannot be called via ``LLMPort.chat()``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

from weebot.application.ports.rerank_port import RerankPort
from weebot.config.model_refs import RERANK_MODEL_FAST, RERANK_MODEL_VERIFIED
from weebot.domain.models.rerank import RerankResult
from weebot.utils.backoff import BackoffConfig, RetryWithBackoff

logger = logging.getLogger(__name__)

_RERANK_URL = "https://openrouter.ai/api/v1/rerank"
_DEFAULT_TIMEOUT = 15.0  # seconds


def _get_api_key() -> str | None:
    """Resolve the OpenRouter API key from the environment."""
    return os.environ.get("OPENROUTER_API_KEY")


class OpenRouterRerankAdapter(RerankPort):
    """Calls the OpenRouter rerank endpoint with Cohere models.

    Args:
        api_key: OpenRouter API key.  Defaults to ``OPENROUTER_API_KEY`` env var.
        default_model: Model ID used when *model* is not passed to ``rerank()``.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = RERANK_MODEL_FAST,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or _get_api_key()
        self._default_model = default_model
        self._timeout = timeout
        if not self._api_key:
            logger.warning(
                "OpenRouterRerankAdapter: OPENROUTER_API_KEY not set — "
                "rerank calls will fail until configured"
            )

    # ── RerankPort implementation ───────────────────────────────────

    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """Rerank *documents* against *query* via the OpenRouter rerank endpoint."""
        if not documents:
            return []
        if not self._api_key:
            logger.warning("Rerank skipped: no API key configured")
            return self._identity_results(documents)

        effective_model = model or self._default_model
        try:
            return await self._call_rerank(query, documents, top_n, effective_model)
        except Exception as exc:
            if effective_model != RERANK_MODEL_VERIFIED:
                logger.warning(
                    "Rerank with model %s failed (%s) — retrying with verified fallback %s",
                    effective_model, exc, RERANK_MODEL_VERIFIED,
                )
                try:
                    return await self._call_rerank(query, documents, top_n, RERANK_MODEL_VERIFIED)
                except Exception as fallback_exc:
                    logger.warning(
                        "Rerank fallback to %s also failed (%d docs): %s",
                        RERANK_MODEL_VERIFIED, len(documents), fallback_exc,
                    )
            else:
                logger.warning(
                    "Rerank failed after retries for model %s (%d docs): %s",
                    effective_model, len(documents), exc,
                )
            return self._identity_results(documents)

    async def _call_rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None,
        model_id: str,
    ) -> list[RerankResult]:
        """Call the rerank API with retry backoff for a specific model."""
        body: dict = {
            "model": model_id,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            body["top_n"] = top_n

        retry = RetryWithBackoff(BackoffConfig(delays=[1, 2, 4], jitter=0.25))
        return await retry.call(self._call_api, body)

    async def _call_api(self, body: dict) -> list[RerankResult]:
        """Single API call with timeout."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _RERANK_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[RerankResult] = []
        for item in data.get("results", []):
            idx = item.get("index", 0)
            doc = body["documents"][idx] if idx < len(body["documents"]) else ""
            results.append(
                RerankResult(
                    index=idx,
                    document=doc,
                    score=float(item.get("relevance_score", 0.0)),
                )
            )

        # Sort by score descending (should already be sorted, but ensure)
        results.sort(key=lambda r: r.score, reverse=True)
        logger.debug(
            "Rerank: %d docs → %d results (model=%s, top_score=%.3f)",
            len(body["documents"]), len(results),
            body.get("model", "?"),
            results[0].score if results else 0.0,
        )
        return results

    @staticmethod
    def _identity_results(documents: list[str]) -> list[RerankResult]:
        """Return identity-mapped results (original order, score=1.0)."""
        return [
            RerankResult(index=i, document=doc, score=1.0)
            for i, doc in enumerate(documents)
        ]
