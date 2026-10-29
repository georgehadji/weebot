"""OpenRouter LLM adapter — OpenAI-compatible with OpenRouter base URL and headers."""

from __future__ import annotations

import logging
import os

from weebot.core.credential_sanitizer import key_fingerprint

from .openai_adapter import OpenAIAdapter
from weebot.config.model_refs import MODEL_FACTORY_OPENROUTER
from weebot.config.api_endpoints import OPENROUTER_API_BASE

_log = logging.getLogger(__name__)

# OpenRouter API keys are prefixed with ``sk-or-v1-`` (OpenRouter docs).
# https://openrouter.ai/docs/quick-start#api-keys
_OPENROUTER_KEY_PREFIX = "sk-or-v1-"


class OpenRouterAdapter(OpenAIAdapter):
    """Adapter for OpenRouter (unified API for 350+ models)."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = MODEL_FACTORY_OPENROUTER,
        http_referer: str | None = None,
        x_title: str | None = None,
    ):
        key = api_key
        if not key:
            try:
                from weebot.config.settings import get_settings

                key = get_settings().openrouter_api_key
            except Exception:
                key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            key = os.getenv("OPENROUTER_API_KEY") or "no-key"

        # ── Early key-format validation ─────────────────────────────
        # OpenRouter returns 401 "User not found" when the key is missing
        # or malformed.  Catch that here with a readable error instead of
        # a cryptic auth failure during the first LLM call.
        if key == "no-key":
            _log.error(
                "OPENROUTER_API_KEY is not set.  "
                "Set it in .env or pass it to the adapter.  "
                "Get a key at https://openrouter.ai/keys"
            )
        elif not key.startswith(_OPENROUTER_KEY_PREFIX):
            _log.warning(
                "OPENROUTER_API_KEY (%s) does not start with '%s'.  "
                "OpenRouter keys should begin with '%s'.  "
                "Got an OpenAI key instead?",
                key_fingerprint(key),  # never key characters (R23)
                _OPENROUTER_KEY_PREFIX,
                _OPENROUTER_KEY_PREFIX,
            )

        headers = {
            "HTTP-Referer": http_referer or "https://github.com/weebot",
            "X-Title": x_title or "weebot",
        }
        # The parent sets up everything its methods read, the fallback flag included (R11).
        super().__init__(
            api_key=key,
            base_url=OPENROUTER_API_BASE,
            default_model=default_model,
            default_headers=headers,
        )
