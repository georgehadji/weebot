"""F28: JSON-quoted secrets are redacted, and the key list lives in one place.

Both `secret_redaction` and `credential_sanitizer` needed the key, then `:` or `=` with
nothing between, so `{"password": "x"}` and `"token": "abc"` passed through; and the two
modules carried two copies of the key list. One pattern builder, with optional quotes around
the key and the value, now serves both.
"""

from __future__ import annotations

import inspect

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from weebot.core import credential_sanitizer, secret_redaction
from weebot.core.credential_sanitizer import has_credentials, sanitize
from weebot.core.secret_redaction import SECRET_KEYS, SecretRedactor, redact_key_values

STYLES = {
    "plain": "{key}={value}",
    "colon": "{key}: {value}",
    "json": '{{"{key}": "{value}"}}',
    "json_compact": '{{"{key}":"{value}"}}',
    "single": "{{'{key}':'{value}'}}",
    "query": "https://h.example/x?{key}={value}&user=bob",
}

CASES = [
    ("password=hunter22", "hunter22"),
    ('{"password": "hunter22"}', "hunter22"),
    ('"token": "abc12345"', "abc12345"),
    ("'token':'abc12345'", "abc12345"),
    ("passwd: hunter22", "hunter22"),
    ('{"api_key": "sk_live_abcdef1234567890"}', "abcdef1234567890"),
    ('{"client_secret": "zzzz9999"}', "zzzz9999"),
    ("Authorization: Bearer abcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwx"),
    ("db_password = 'p@ss w0rd'", "p@ss w0rd"),
]


@pytest.mark.parametrize(("text", "secret"), CASES)
def test_sanitize_removes_the_value(text, secret):
    assert secret not in sanitize(text), text


@pytest.mark.parametrize(("text", "secret"), CASES)
def test_the_redactor_alone_removes_the_value(text, secret):
    if text.startswith("Authorization"):
        pytest.skip("the Authorization header is the sanitizer's own pattern")
    assert secret not in SecretRedactor().redact(text), text


@pytest.mark.parametrize(("text", "secret"), CASES)
def test_has_credentials_sees_each_style(text, secret):
    assert has_credentials(text), text


def test_the_json_shape_survives_redaction():
    out = sanitize('{"password": "hunter22", "user": "bob"}')
    assert out.startswith('{"password": "') and '"user": "bob"' in out


def test_redaction_is_idempotent():
    once = sanitize('{"password": "hunter22"} token=abc12345')
    assert sanitize(once) == once


@pytest.mark.parametrize(
    "text",
    ["max_tokens: 4096", "port 8080", "HTTP 404 Not Found", "the secretary spoke", "tokenize(x)"],
)
def test_text_that_is_not_a_secret_is_left_alone(text):
    assert sanitize(text) == text


@settings(max_examples=120, deadline=None)
@given(
    st.sampled_from(sorted(SECRET_KEYS)),
    st.sampled_from(sorted(STYLES)),
    st.from_regex(r"[A-Za-z0-9]{8,20}", fullmatch=True),
)
def test_for_any_key_and_style_the_value_does_not_survive(key, style, value):
    key = key.replace("[_-]?", "_")
    assume(value.lower() not in ("redacted", key.lower()) and value not in "REDACTED")
    text = STYLES[style].format(key=key, value=value)
    assert value not in sanitize(text), text
    assert value not in redact_key_values(text, "[X]"), text


def test_there_is_one_key_list():
    """The sanitizer builds nothing of its own from key names."""
    source = inspect.getsource(credential_sanitizer)
    assert "passwd" not in source and "api[_-]?key" not in source
    assert "SECRET_KEYS" in inspect.getsource(secret_redaction)
