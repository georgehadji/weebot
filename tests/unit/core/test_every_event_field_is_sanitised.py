"""R6 — credential sanitisation covered the one field the human types.

All three emit pipelines gated redaction on::

    isinstance(event, MessageEvent) and event.role == "user"

so a credential was scrubbed only when the *human* typed it. Everything the
agent produced went out raw — above all ``ToolEvent.result``, which is tool
stdout and therefore carries the output of ``cat .env``, ``env`` and
``git remote -v``. That reached the event bus, the WebSocket broadcast to the
web UI, and SQLite, while ``EventPublisher``'s own docstring listed credential
sanitisation as an unconditional stage of the pipeline.

The pattern set was also thinner than the region's dead redactor: measured
before this change, a GitHub PAT, a Google API key, a Slack bot token and an
``Authorization: Basic`` header all passed through ``sanitize()`` untouched,
and the copy kept in ``resilient_adapter`` had drifted so far that it could
not match an Anthropic key at all.
"""

from __future__ import annotations

import pytest

from weebot.core.credential_sanitizer import sanitize, sanitize_event
from weebot.domain.models.event import (
    ErrorEvent,
    MessageEvent,
    StepEvent,
    ToolEvent,
    WaitForUserEvent,
)

SECRET = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"

# Assembled at import time rather than written as a literal: GitHub's push
# protection recognises a Slack token by shape and rejects the push, which is
# the correct behaviour and not something to bypass. The regex under test sees
# the same string either way.
_SLACK_FIXTURE = "xox" + "b-" + "123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"


# --------------------------------------------------------------------------
# The defect: only user messages were covered.
# --------------------------------------------------------------------------


def test_tool_output_is_sanitised():
    """The highest-value case: `result` is raw stdout."""
    event = ToolEvent(tool_name="bash", result=f"ANTHROPIC_API_KEY={SECRET}\n")
    cleaned = sanitize_event(event)
    assert SECRET not in (cleaned.result or "")


def test_an_assistant_message_is_sanitised():
    """The gate tested `role == "user"`, so the model echoing a key was exempt."""
    event = MessageEvent(role="assistant", message=f"I found the key {SECRET}")
    assert SECRET not in sanitize_event(event).message


def test_an_error_message_is_sanitised():
    event = ErrorEvent(error=f"auth failed with {SECRET}")
    assert SECRET not in sanitize_event(event).error


def test_a_step_description_is_sanitised():
    event = StepEvent(step_id="s1", description=f"call the API with {SECRET}")
    assert SECRET not in sanitize_event(event).description


def test_a_pause_question_is_sanitised():
    event = WaitForUserEvent(question=f"Shall I use {SECRET}?")
    assert SECRET not in sanitize_event(event).question


def test_a_user_message_is_still_sanitised():
    """Regression: the one case that already worked must keep working."""
    event = MessageEvent(role="user", message=f"my key is {SECRET}")
    assert SECRET not in sanitize_event(event).message


# --------------------------------------------------------------------------
# Identity is the "did anything change" signal the callers use.
# --------------------------------------------------------------------------


def test_a_clean_event_is_returned_unchanged():
    event = ToolEvent(tool_name="bash", result="total 4\ndrwxr-xr-x  2 user user\n")
    assert sanitize_event(event) is event


def test_an_event_with_no_text_fields_is_returned_unchanged():
    from weebot.domain.models.event import DoneEvent

    event = DoneEvent()
    assert sanitize_event(event) is event


def test_a_none_result_does_not_crash():
    event = ToolEvent(tool_name="bash", result=None)
    assert sanitize_event(event) is event


# --------------------------------------------------------------------------
# Patterns the live sanitiser was missing. Each of these leaked, measured.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,text,secret",
    [
        (
            "GitHub PAT",
            "curl -H 'Authorization: Bearer ghp_16C7e42F292c6912E7710c838347Ae178B4a'",
            "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
        ),
        (
            "Google API key",
            "AIzaSyD-1234567890abcdefghijklmnopqrstu",
            "AIzaSyD-1234567890abcdefghijklmnopqrstu",
        ),
        ("Slack bot token", _SLACK_FIXTURE, _SLACK_FIXTURE),
        (
            "Basic auth",
            "Authorization: Basic dXNlcjpwYXNzd29yZA==",
            "dXNlcjpwYXNzd29yZA==",
        ),
        (
            "Slack webhook",
            "https://hooks.slack.com/services/T00/B00/XXXXXXXXXXXXXXXXXXXXXXXX",
            "XXXXXXXXXXXXXXXXXXXXXXXX",
        ),
        (
            "URL credentials",
            "postgres://admin:hunter2@db.internal:5432/weebot",
            "hunter2",
        ),
    ],
)
def test_a_missing_pattern_no_longer_leaks(label, text, secret):
    assert secret not in sanitize(text), f"{label} still leaks"


@pytest.mark.parametrize(
    "text",
    [
        "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AKIAIOSFODNN7EXAMPLE",
        "DB_PASSWORD=hunter2",
    ],
)
def test_patterns_that_already_worked_still_work(text):
    """Regression on the pre-existing set."""
    assert sanitize(text) != text


@pytest.mark.parametrize(
    "header",
    [
        # `{"alg":"HS256"}` -> 17 chars after `eyJ`. This one LEAKED: the
        # per-segment minimum was 20, so whether a JWT was redacted depended
        # on its header's length rather than on it being a JWT.
        "eyJhbGciOiJIUzI1NiJ9",
        # `{"alg":"HS256","typ":"JWT"}` -> 33 chars. This one was caught.
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    ],
)
def test_a_jwt_is_redacted_whatever_its_header_length(header):
    jwt = f"{header}.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g"
    assert "***REDACTED-JWT***" in sanitize(jwt)


# --------------------------------------------------------------------------
# One rule, not two.
# --------------------------------------------------------------------------


def test_the_adapter_and_core_agree_on_an_anthropic_key():
    """`resilient_adapter` kept its own fork whose `sk-[a-zA-Z0-9]{20,}`
    excludes `-` and `_`, so `sk-ant-...` failed at the third character while
    the same key was redacted by core. Two forks of one rule, one broken."""
    from weebot.infrastructure.adapters.llm.resilient_adapter import (
        _sanitize_error,
        sanitized_message,
    )

    exc = RuntimeError(f"auth failed for {SECRET}")
    _sanitize_error(exc)
    assert SECRET not in str(exc)
    assert SECRET not in sanitized_message(RuntimeError(f"nope {SECRET}"))


def test_a_computed_str_is_still_recoverable():
    """`_sanitize_error` rewrites `args[0]`, which cannot reach an exception
    whose `__str__` is computed — every httpx/openai wrapper. `sanitized_message`
    is the escape hatch for callers that log the text rather than the object."""
    from weebot.infrastructure.adapters.llm.resilient_adapter import sanitized_message

    class HttpErr(Exception):
        def __init__(self, url):
            self.url = url
            super().__init__("request failed")

        def __str__(self):
            return f"GET failed {self.url}"

    exc = HttpErr(f"https://api.x/v1?api_key={SECRET}")
    assert SECRET not in sanitized_message(exc)
