"""Phase 3.1: rejected credentials cross the adapter boundary as a domain type.

VerifyingState imported ``openai.AuthenticationError`` to tell "the key was
rejected" (stamp NOT_RUN) apart from an ordinary failure. That was a vendor
leak and also a hole: an Anthropic-backed verifier raises
``anthropic.AuthenticationError``, which that handler never caught, so a dead
key read as "no questions to ask" and verification completed silently.

ResilientLLMAdapter wraps every factory-built LLM, so the translation lives
there, keyed on HTTP 401 rather than on any SDK's class.
"""

from __future__ import annotations

import httpx
import openai
import pytest

from weebot.domain.exceptions import LLMAuthenticationError
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter


class _Raising:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def chat(self, **kwargs):
        raise self._exc


class _OtherVendorAuthError(Exception):
    """Shape of anthropic.AuthenticationError: a status_code, no openai base."""

    status_code = 401


def _resilient(exc: Exception) -> ResilientLLMAdapter:
    return ResilientLLMAdapter(
        inner_adapter=_Raising(exc),
        model_name="m",
        enable_circuit_breaker=False,
        enable_retry=False,
    )


def _openai_auth_error() -> openai.AuthenticationError:
    req = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    return openai.AuthenticationError(
        "invalid api key", response=httpx.Response(401, request=req), body=None
    )


@pytest.mark.parametrize(
    "exc",
    [_openai_auth_error(), _OtherVendorAuthError("authentication failed")],
    ids=["openai", "other-vendor"],
)
async def test_a_401_from_any_vendor_becomes_the_domain_type(exc):
    with pytest.raises(LLMAuthenticationError) as info:
        await _resilient(exc).chat(messages=[{"role": "user", "content": "hi"}])
    assert info.value.__cause__ is exc


async def test_other_fail_fast_errors_keep_their_type():
    """ErrorClassifier's AUTH category also matches 402/403 text. Those stop
    retries, but they are not rejected credentials and must not be renamed."""
    exc = RuntimeError("402 payment required")
    with pytest.raises(RuntimeError) as info:
        await _resilient(exc).chat(messages=[{"role": "user", "content": "hi"}])
    assert info.value is exc
