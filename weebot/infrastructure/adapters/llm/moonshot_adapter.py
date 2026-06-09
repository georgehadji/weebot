"""Moonshot (Kimi) LLM adapter — OpenAI-compatible with Moonshot base URL.

Uses ``KIMI_API_KEY`` (priority) or ``MOONSHOT_API_KEY`` (fallback)
environment variable.  Falls back to OpenRouter when no direct API key
is available or the call fails.

Kimi K2.6 requires ``temperature=1`` — the adapter overrides any other
value to prevent ``BadRequestError`` (400: invalid temperature).

Kimi K2.6 API docs: https://platform.kimi.ai/docs/api/
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .openai_adapter import OpenAIAdapter
from weebot.application.ports.llm_port import LLMResponse
from weebot.config.api_endpoints import MOONSHOT_API_BASE
from weebot.config.model_refs import MODEL_CASCADE_TIER1 as _MODEL_CASCADE_TIER1

# Strip OpenRouter prefix + ":free" suffix for direct API:
# "moonshotai/kimi-k2.6:free" → "kimi-k2.6"
_tmp = _MODEL_CASCADE_TIER1.split("/", 1)[-1] if "/" in _MODEL_CASCADE_TIER1 else _MODEL_CASCADE_TIER1
_MODEL_CASCADE_TIER1_STRIPPED = _tmp.split(":")[0] if ":" in _tmp else _tmp
del _MODEL_CASCADE_TIER1, _tmp

_log = logging.getLogger(__name__)


class MoonshotAdapter(OpenAIAdapter):
    """Adapter for Moonshot / Kimi API (OpenAI-compatible).

    Connects directly to ``https://api.moonshot.ai/v1`` using either
    ``KIMI_API_KEY`` (tried first) or ``MOONSHOT_API_KEY`` (official
    env var from Kimi docs).  This bypasses OpenRouter markup, reducing
    cost and latency for Kimi models.

    The native model name is ``kimi-k2.6`` (confirmed via platform.kimi.ai
    API docs — both partial mode and tool-use examples use this ID).
    """

    # Kimi K2.6 only accepts temperature=1.0
    _FORCED_TEMPERATURE: float = 1.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = _MODEL_CASCADE_TIER1_STRIPPED,
    ):
        key = (
            api_key
            or os.getenv("KIMI_API_KEY")
            or os.getenv("MOONSHOT_API_KEY")
            or ""
        )
        super().__init__(
            api_key=key,
            base_url=MOONSHOT_API_BASE,
            default_model=default_model,
        )

    @staticmethod
    def _sanitize_messages_for_kimi(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return a copy of *messages* with Kimi K2.6-incompatible fields fixed.

        Kimi's API rejects shapes that OpenAI / OpenRouter accept:

        1. Assistant messages with ``tool_calls`` but ``content: null`` →
           set content to ``""`` (Kimi requires non-null content).
        2. ``reasoning_content: null`` → strip (Kimi rejects explicit null).
        3. Assistant messages with ``tool_calls`` but no ``reasoning_content``
           at all → add ``reasoning_content: ""`` (Kimi thinking model
           requires this field on every assistant message with tool_calls,
           even when the content is empty).
        4. **Tool-call ID chain integrity** — Kimi validates that every
           ``tool_call_id`` in a ``tool``-role message references an ``id``
           inside ``tool_calls`` on the **immediately preceding** assistant
           message.  If the chain is broken (e.g. after conversation
           compression, model-cascade switching, or message re-ordering),
           orphan ``tool`` messages are stripped to avoid a 400 error.
        """
        import uuid

        sanitized: List[Dict[str, Any]] = []
        # Track valid tool_call_ids from the most recent assistant message
        valid_tool_call_ids: set[str] = set()

        for msg in messages:
            m = dict(msg)  # shallow copy — don't mutate caller's list
            role = m.get("role", "")
            has_tool_calls = bool(m.get("tool_calls"))

            # ── Track valid IDs from the most recent assistant ──
            if role == "assistant" and has_tool_calls:
                valid_tool_call_ids.clear()
                for tc in m["tool_calls"]:
                    tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tid:
                        valid_tool_call_ids.add(tid)

            # ── Strip orphan tool messages ──────────────────────
            if role == "tool":
                tcid = m.get("tool_call_id", "")
                if tcid and tcid not in valid_tool_call_ids:
                    # Orphaned tool_call_id — skip this message and log
                    _log.warning(
                        "Stripping orphan tool message with tool_call_id=%s "
                        "(not found in preceding assistant tool_calls)",
                        tcid,
                    )
                    continue

            # Fix 1: null content on assistant tool-call messages
            if role == "assistant" and has_tool_calls and m.get("content") is None:
                m["content"] = ""

            # Fix 2: explicit null reasoning_content
            if "reasoning_content" in m and m["reasoning_content"] is None:
                del m["reasoning_content"]

            # Fix 3: Kimi thinking model requires reasoning_content on
            # every assistant message that has tool_calls.  If absent
            # entirely, add an empty placeholder.
            if (
                role == "assistant"
                and has_tool_calls
                and "reasoning_content" not in m
            ):
                m["reasoning_content"] = ""

            sanitized.append(m)
        return sanitized

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
        """Override chat for Kimi K2.6 compatibility.

        Sanitizes messages for Kimi API quirks (null content, null
        reasoning_content), then delegates to OpenAIAdapter.  Temperature
        is omitted so the API uses its default (required for K2.6 thinking).

        Per https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model
        """
        messages = self._sanitize_messages_for_kimi(messages)
        effective_temp = None  # Omit — let API use default for thinking models
        return await super().chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            model=model,
            temperature=effective_temp,
            max_tokens=max_tokens,
        )
