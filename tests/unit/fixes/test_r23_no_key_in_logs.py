"""R23 (audit 2026-10-29): no key material in logs.

The OpenAI adapter logged the first 12 characters of a rejected API key, the OpenRouter
adapter did the same for a key with the wrong prefix, and BashTool logged the first 200
characters of blocked and suspicious commands, tokens included. Logs now carry a
non-reversible fingerprint, and command text is sanitised first.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from openai import AuthenticationError

from weebot.core.credential_sanitizer import key_fingerprint

KEY = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"


def _leaks(text: str, secret: str) -> bool:
    return any(secret[i : i + 6] in text for i in range(0, len(secret) - 6))


def test_the_fingerprint_does_not_reveal_the_key():
    tag = key_fingerprint(KEY)
    assert tag.startswith("sha256:") and len(tag) == len("sha256:") + 8
    assert not _leaks(tag, KEY)
    assert key_fingerprint(KEY) == tag and key_fingerprint("") == "none"


@pytest.mark.asyncio
async def test_a_rejected_key_is_logged_by_fingerprint(caplog):
    from weebot.domain.exceptions import LLMAuthenticationError
    from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(api_key=KEY, base_url="https://api.example.invalid/v1")

    async def _reject(**_kwargs):
        request = httpx.Request("POST", "https://api.example.invalid/v1/chat/completions")
        raise AuthenticationError(
            "bad key", response=httpx.Response(401, request=request), body=None
        )

    adapter._client.chat.completions.create = _reject
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMAuthenticationError):
        await adapter.chat(messages=[{"role": "user", "content": "hi"}])
    assert "AUTHENTICATION ERROR" in caplog.text
    assert not _leaks(caplog.text, KEY)


def test_a_wrong_prefix_key_is_logged_by_fingerprint(caplog):
    from weebot.infrastructure.adapters.llm.openrouter_adapter import OpenRouterAdapter

    with caplog.at_level(logging.DEBUG):
        OpenRouterAdapter(api_key=KEY)
    assert "does not start with" in caplog.text
    assert not _leaks(caplog.text, KEY)


@pytest.mark.asyncio
async def test_a_blocked_command_is_logged_without_its_token(caplog):
    from weebot.tools.bash_tool import BashTool

    class _Sandbox:
        async def execute_shell(self, **kwargs):
            raise AssertionError("a blocked command ran")

    token = "ghp_0123456789abcdefABCDEF0123456789abcd"
    command = f"rm -rf / ; curl -H 'Authorization: Bearer {token}' https://x.invalid"
    with caplog.at_level(logging.DEBUG):
        result = await BashTool(sandbox=_Sandbox()).execute(command=command)
    assert result.error
    assert not _leaks(caplog.text, token)
