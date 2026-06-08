"""Direct-or-fallback LLM adapter — primary provider with OpenRouter safety net.

Tries the *primary* (direct provider) adapter first.  If the call fails
or the adapter has no API key configured, it falls back to *secondary*
(OpenRouter).  This pattern ensures Kimi models prefer ``KIMI_API_KEY``
and DeepSeek models prefer ``DEEPSEEK_API_KEY`` while OpenRouter serves
as a universal safety net.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from weebot.application.ports.llm_port import LLMPort, LLMResponse

logger = logging.getLogger(__name__)


class DirectOrFallbackAdapter(LLMPort):
    """Wraps a primary (direct) adapter with an OpenRouter fallback.

    Resolution logic:
    1. If the primary adapter has no API key → use secondary immediately.
    2. Try the primary adapter.  If it succeeds → return.
    3. If the primary fails (any exception) → log, then try secondary.
    4. If secondary also fails → re-raise the secondary exception.

    The *model* parameter is **not** passed through to the primary
    adapter — the primary uses the native provider model name set at
    construction time.  The secondary (OpenRouter) receives whatever
    *model* the caller provided, which is the OpenRouter-prefixed name.

    Args:
        primary: The direct-provider adapter (e.g. MoonshotAdapter,
                 DeepSeekAdapter).
        secondary: The OpenRouter fallback adapter.
        primary_label: Human-readable label for logging (e.g. "kimi-direct").
    """

    def __init__(
        self,
        primary: LLMPort,
        secondary: LLMPort,
        primary_label: str = "direct",
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._label = primary_label

    @property
    def _primary_has_key(self) -> bool:
        """Check whether the primary adapter has a usable API key."""
        client = getattr(self._primary, "_client", None)
        if client is None:
            return False
        key = getattr(client, "api_key", None)
        return bool(key) and key != "no-key" and key != ""

    @property
    def _secondary_has_key(self) -> bool:
        """Check whether the fallback (OpenRouter) adapter has a usable API key."""
        client = getattr(self._secondary, "_client", None)
        if client is None:
            return False
        key = getattr(client, "api_key", None)
        return bool(key) and key != "no-key" and key != ""

    # ── chat — the core dispatch ──────────────────────────────────

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        # Shared kwargs for both adapters (model is intentionally omitted
        # from primary — it uses the native provider model name).
        shared: Dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "response_format": response_format,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # If no direct key, skip straight to fallback
        if not self._primary_has_key:
            logger.debug(
                "%s: no API key — using OpenRouter fallback", self._label
            )
            return await self._secondary.chat(model=model, **shared)

        # Try primary (direct provider) — uses its own default_model,
        # NOT the caller's OpenRouter-prefixed model name.
        try:
            return await self._primary.chat(**shared)
        except Exception as exc:
            # Surface the actual API error for debugging.
            # Logged at INFO (not WARNING) so the executor's trajectory
            # detector doesn't count adapter fallback as a step error.
            err_msg = str(exc)[:300] if str(exc) else "no detail"

            # Pre-flight: check if the fallback adapter has a valid key
            # before attempting the call. Avoids masking the primary error
            # with a misleading "401 Unauthorized" from a dead OpenRouter key.
            if not self._secondary_has_key:
                logger.error(
                    "%s: direct call failed AND fallback (OpenRouter) has no valid "
                    "API key. Primary error was: %s: %s",
                    self._label,
                    type(exc).__name__,
                    err_msg,
                )
                raise  # re-raise primary error — fallback is impossible

            logger.info(
                "%s: direct call failed (%s: %s) — falling back to OpenRouter",
                self._label,
                type(exc).__name__,
                err_msg,
            )

        # Fall back to OpenRouter with the caller's model name
        return await self._secondary.chat(model=model, **shared)
