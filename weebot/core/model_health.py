"""Startup model health check — verifies the default LLM is reachable.

Called during ``Container.configure_defaults()`` and from the ``weebot health``
CLI command.  Skips if ``WEEBOT_SKIP_MODEL_CHECK=1`` is set.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from weebot.config.constants import MAX_TOKENS_PROBE, TEMPERATURE_DETERMINISTIC

logger = logging.getLogger(__name__)

# ── Public API ──────────────────────────────────────────────────────

async def check_default_model(llm, model_id: str, timeout: float = 10.0) -> bool:
    """Ping *model_id* with a minimal message to verify it's reachable.

    Args:
        llm: An :class:`~weebot.application.ports.llm_port.LLMPort` instance.
        model_id: The OpenRouter-qualified model ID to test.
        timeout: Maximum seconds to wait for a response.

    Returns:
        ``True`` if the model responded successfully, ``False`` otherwise.
    """
    if os.environ.get("WEEBOT_SKIP_MODEL_CHECK") == "1":
        logger.info("Model health check skipped (WEEBOT_SKIP_MODEL_CHECK=1)")
        return True  # treat skip as pass

    try:
        resp = await asyncio.wait_for(
            llm.chat(
                messages=[{"role": "user", "content": "ping"}],
                model=model_id,
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_PROBE,
            ),
            timeout=timeout,
        )
        if resp and resp.content:
            logger.info(
                "Model health check PASSED: %s (response: %r)", model_id, resp.content[:50]
            )
            return True
        logger.warning("Model health check: %s returned empty response", model_id)
        return False
    except asyncio.TimeoutError:
        logger.warning("Model health check TIMED OUT after %.1fs: %s", timeout, model_id)
        return False
    except Exception as exc:
        msg = str(exc)[:200]
        logger.warning("Model health check FAILED for %s: %s", model_id, msg)
        logger.warning(
            "Possible causes:\n"
            "  - Invalid or expired OPENROUTER_API_KEY\n"
            "  - Zero OpenRouter credits (check https://openrouter.ai/credits)\n"
            "  - Model ID renamed or removed (check https://openrouter.ai/models)\n"
            "  - Network connectivity issue"
        )
        return False


async def check_model_cascade(
    llm, models: list[str], timeout: float = 10.0
) -> dict[str, bool]:
    """Check every model in *models* and return per-model results.

    Args:
        llm: An :class:`~weebot.application.ports.llm_port.LLMPort` instance.
        models: List of model IDs to test.
        timeout: Per-model timeout in seconds.

    Returns:
        Dict mapping model_id → reachable (bool).
    """
    results: dict[str, bool] = {}
    for model_id in models:
        results[model_id] = await check_default_model(llm, model_id, timeout=timeout)
    return results
