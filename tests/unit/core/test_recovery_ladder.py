"""The recovery ladder picks one untried rung at a time and always ends (H3)."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._recovery import (
    call_with_recovery,
    prune_tool_outputs,
    strip_media,
    terminal_error,
)
from weebot.core.error_classifier import ErrorCategory, ErrorClassifier, RecoveryAction
from weebot.core.recovery_ladder import (
    LADDERS,
    RECOVERABLE,
    RecoveryAttempt,
    failure_message,
    plan_recovery,
)
from weebot.domain.exceptions import AllModelsTrippedError, RecoverableLLMError


def _walk(category, retry_after=None):
    """Follow the ladder to its end, as the runner does; returns the actions in order."""
    attempt, actions = RecoveryAttempt(retry_after=retry_after), []
    while (rung := plan_recovery(category, attempt)) is not None:
        actions.append(rung.action)
        attempt = RecoveryAttempt(attempt.rungs_used | {rung}, retry_after)
    return actions


def test_overflow_compresses_twice_then_asks_for_a_larger_model():
    assert _walk(ErrorCategory.CONTEXT_LENGTH) == [
        RecoveryAction.COMPRESS,
        RecoveryAction.COMPRESS,
        RecoveryAction.LARGER_CONTEXT_MODEL,
    ]


def test_a_long_retry_after_skips_the_same_model_backoff():
    assert _walk(ErrorCategory.RATE_LIMIT_UPSTREAM, retry_after=60) == [
        RecoveryAction.FALLBACK_MODEL
    ]
    assert _walk(ErrorCategory.RATE_LIMIT_UPSTREAM, retry_after=2) == [
        RecoveryAction.BACKOFF,
        RecoveryAction.FALLBACK_MODEL,
    ]


@pytest.mark.parametrize("category", [ErrorCategory.QUOTA_EXHAUSTED, ErrorCategory.AUTH])
def test_account_level_failures_have_no_rungs(category):
    assert _walk(category) == []


def test_every_category_has_a_ladder_entry_or_is_deliberately_unrecoverable():
    """Dict coverage: a new category must be placed on purpose, not fall through."""
    # These retry in the adapter, fail fast, or escalate; none is the executor's to recover.
    assert {c for c in ErrorCategory if c not in LADDERS} == {
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.MODEL_UNAVAILABLE,
        ErrorCategory.TOOL_ERROR,
        ErrorCategory.NETWORK,
        ErrorCategory.CONTENT_FILTER,
        ErrorCategory.BAD_REQUEST,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.TIMEOUT,
        ErrorCategory.UNKNOWN,
    }
    assert RECOVERABLE <= set(LADDERS)
    for category in ErrorCategory:
        assert isinstance(failure_message(category), str)


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("This model's maximum context length is 8192 tokens", ErrorCategory.CONTEXT_LENGTH),
        ("413 Request Entity Too Large", ErrorCategory.PAYLOAD_TOO_LARGE),
        ("model does not support image input", ErrorCategory.MULTIMODAL_UNSUPPORTED),
        ("Insufficient credits", ErrorCategory.QUOTA_EXHAUSTED),
        (
            "anthropic/claude-sonnet-5.5 is temporarily rate-limited upstream",
            ErrorCategory.RATE_LIMIT_UPSTREAM,
        ),
        ("tool definitions rejected: invalid schema", ErrorCategory.TOOL_SCHEMA_REJECTED),
    ],
)
def test_classifier_recognises_the_ladder_categories(text, category):
    assert ErrorClassifier.classify(Exception(text)) is category


def test_overflow_is_not_retried_on_the_same_payload():
    from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter

    adapter = ResilientLLMAdapter.__new__(ResilientLLMAdapter)
    assert adapter._is_retryable_error(Exception("context length exceeded")) is False
    assert adapter._is_retryable_error(Exception("tool definitions rejected: invalid schema")) is False
    assert adapter._is_retryable_error(Exception("rate limit")) is True
    assert adapter._is_retryable_error(Exception("503 service unavailable")) is True


def test_terminal_error_types_the_cause_and_reads_retry_after():
    err = terminal_error(
        {"a": "timed out", "b": "upstream rate-limited, retry-after: 60"}, "default"
    )
    assert isinstance(err, RecoverableLLMError)
    assert err.category == "rate_limit_upstream" and err.retry_after == 60.0
    plain = terminal_error({"a": "connection reset"}, "default")
    assert type(plain) is AllModelsTrippedError and str(plain) == "default"


def test_strip_media_and_prune_are_pure_and_counted():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}, image]}]
    out, n = strip_media(msgs)
    assert n == 1 and out[0]["content"][1] == {"type": "text", "text": "[image omitted: 1]"}
    assert msgs[0]["content"][1] is image  # input untouched

    tools = [{"role": "tool", "content": f"out{i}"} for i in range(7)]
    pruned, k = prune_tool_outputs(tools, keep_last=2)
    assert k == 5 and pruned[-1]["content"] == "out6" and "pruned" in pruned[0]["content"]


class _Cascade:
    """Overflows while the payload is over the limit, as a real small-window model would."""

    def __init__(self, limit):
        self.limit, self.calls = limit, 0

    async def call_with_cascade(self, messages, description=""):
        self.calls += 1
        if sum(len(m["content"]) for m in messages) > self.limit:
            raise RecoverableLLMError("full", category="context_length")
        return SimpleNamespace(content="ok", tool_calls=None)


def _executor(cascade, buffer, force_compress):
    return SimpleNamespace(
        _cascade=cascade,
        _conversation_buffer=buffer,
        _context_compressor=SimpleNamespace(force_compress=force_compress),
    )


@pytest.mark.asyncio
async def test_overflow_compresses_once_then_succeeds_with_a_smaller_payload():
    """Before H3 this retried the same oversized payload six times, then gave up."""
    buffer = deque({"role": "user", "content": "x" * 100} for _ in range(10))
    cascade = _Cascade(limit=500)

    async def force_compress():
        keep = list(buffer)[-3:]
        buffer.clear()
        buffer.extend(keep)
        return True

    async def rebuild():
        return list(buffer)

    first = list(buffer)
    response, messages = await call_with_recovery(
        _executor(cascade, buffer, force_compress), first, "step", rebuild
    )
    assert response.content == "ok"
    assert cascade.calls == 2 and len(messages) < len(first)


@pytest.mark.asyncio
async def test_a_spent_ladder_raises_the_original_error():
    buffer = deque([{"role": "user", "content": "x" * 100}])
    cascade = _Cascade(limit=1)

    async def nothing_to_compress():
        return False

    async def rebuild():
        return list(buffer)

    with pytest.raises(RecoverableLLMError):
        await call_with_recovery(
            _executor(cascade, buffer, nothing_to_compress), list(buffer), "step", rebuild
        )
    assert cascade.calls == 1  # no rung changed the payload, so no blind retry
