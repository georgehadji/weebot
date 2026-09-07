"""R6 C1/C6/C7/C8 — the redactor that was declared, never ran, and could not.

`settings.py` declares `secret_redaction_enabled: bool = True`, described as
redacting secrets "in tool output and logs". `SecretRedactor` is 184 lines
with **zero callers**. A configuration reporting a control that has never run.

It was not wired earlier because wiring it as it stood would have shipped a
log-corruption bug on the same commit as a security fix. Measured on the
unfixed class:

    'line one\\nline two\\tindented'  ->  'line one line two indented'
    'listening on port 8080'        ->  'listening on port [CVV_REDACTED]'
    'HTTP 404 Not Found'            ->  'HTTP [CVV_REDACTED] Not Found'
    'file.py:123'                   ->  '[HIGH_ENTROPY_REDACTED]'
    'passwd: abc' / 'secret: abc'   ->  'password=[REDACTED]'   (both)

The `file.py:123` case is the one worth pausing on: the token is 11 characters,
below the 20-character entropy threshold. The CVV rule fired first, and its own
marker made the token 22 characters — so a redaction lengthened the text into
the next rule's range and a source location disappeared. Redaction output fed
back into redaction input.

And `redact_dict` presented four shapes as sanitised while leaving them intact:
a secret as a dict KEY, a `bytes` value, a dict below two list levels, and a
tuple.

The entropy pass is a separate finding and is NOT wired. On this codebase's own
tool output it redacts commit SHAs, session UUIDs, sha256 digests and file
paths — see `test_the_entropy_pass_would_eat_this_codebase`.
"""

from __future__ import annotations

import logging

import pytest

from weebot.config.secret_accessor import SecretAccessor
from weebot.core.credential_sanitizer import sanitize
from weebot.core.secret_redaction import SecretRedactor


# Stripe-shaped fixtures, assembled at import time rather than written out.
# GitHub push protection rejected the literal form of these — correctly, they
# match a real key's shape. The unblock URL exists and is not the answer: a
# gate that fires is a gate to satisfy, not to wave through.
_STRIPE_PREFIX = "sk" + "_" + "live" + "_"
_STRIPE_A = _STRIPE_PREFIX + "A" * 24
_STRIPE_B = _STRIPE_PREFIX + "B" * 24


@pytest.fixture(autouse=True)
def _reset_secret_source():
    """`SecretAccessor.set_source` is process-wide state.

    Without this, the dict set by the C6 tests below stays installed for every
    later test in the run — which is exactly what happened: it made
    `test_run_mcp.py` fail with "--allow-remote requires WEEBOT_MCP_API_KEY",
    because the accessor was answering from this file's fixture instead of the
    environment. `tests/unit/test_secret_accessor.py` has the same fixture for
    the same reason.
    """
    SecretAccessor.set_source(None)
    yield
    SecretAccessor.set_source(None)


# ── C7: redact() must not rewrite the text around the secret ──────────


def test_redaction_preserves_the_shape_of_the_text():
    """A sanitiser that reflows a log is a sanitiser nobody can wire in."""
    log = "line one\nline two\tindented\n\ntrailing"
    assert SecretRedactor().redact(log) == log


def test_ordinary_small_integers_are_not_cvvs():
    """A CVV cannot be recognised from digits alone, and this tried."""
    r = SecretRedactor()
    for text in (
        "listening on port 8080",
        "HTTP 404 Not Found",
        "year 2026",
        "took 250 ms",
        "file.py:123",
    ):
        assert r.redact(text) == text, f"{text!r} was mangled"


def test_a_labelled_cvv_is_still_redacted():
    """Context is what makes the detection possible, so context is required.

    REGRESSION GUARD: passes on the unfixed code too, because `\b\d{3,4}\b`
    matched a labelled CVV along with everything else. What it pins is that
    narrowing the rule did not lose the detection it was named for.
    """
    r = SecretRedactor()
    for text in ("cvv: 123", "CVC=4321", "card security code 999"):
        out = r.redact(text)
        assert "[CVV_REDACTED]" in out, f"{text!r} was not redacted"
        assert "123" not in out or "cvv" in out.lower()


def test_a_redaction_marker_does_not_trip_the_next_rule():
    """`file.py:123` -> `file.py:[CVV_REDACTED]` -> `[HIGH_ENTROPY_REDACTED]`.

    The guard skipped tokens that `startswith("[")`, which misses a marker
    substituted into the middle of one.
    """
    r = SecretRedactor(enable_entropy=True)
    assert r.redact("file.py:123") == "file.py:123"
    # `path:line` and `path:line:col` — grep, tracebacks, every linter. Writing
    # this case is what found that the shape exclusion did not cover the suffix.
    for loc in ("some/path/file.py:123", "weebot/core/secret_redaction.py:142:9"):
        assert "_REDACTED]" not in r.redact(loc), f"{loc!r} was redacted"


def test_the_label_in_the_text_survives():
    """`secret: x` used to come out claiming to be a password."""
    r = SecretRedactor()
    assert r.redact("passwd: abc123").startswith("passwd=")
    assert r.redact("secret: abc123").startswith("secret=")


# ── C8: redact_dict must not present four shapes as sanitised ─────────


def test_redact_dict_covers_the_four_shapes_it_missed():
    r = SecretRedactor()
    out = r.redact_dict(
        {
            _STRIPE_A: "value",
            "as_bytes": b"password=hunter2",
            "nested_lists": [[{"note": "password=hunter2"}]],
            "a_tuple": ("password=hunter2",),
        }
    )
    assert _STRIPE_A not in out, "a secret survived as a KEY"
    assert b"hunter2" not in out["as_bytes"], "bytes were not redacted"
    assert "hunter2" not in out["nested_lists"][0][0]["note"], "two list levels down"
    assert "hunter2" not in out["a_tuple"][0], "a tuple was not recursed"
    assert isinstance(out["a_tuple"], tuple), "the tuple's type was not preserved"


def test_redacting_keys_never_silently_drops_a_value():
    """Two distinct secret keys redact to the same marker.

    Collapsing them would make this a data-destroying sanitiser, which is a
    worse failure than the one it fixes.

    Passes on the unfixed code, and vacuously: keys were not redacted at all
    there, so no collision could occur. It only becomes a real assertion once
    keys ARE redacted, which is the point at which the hazard appears.
    """
    out = SecretRedactor().redact_dict(
        {
            _STRIPE_A: 1,
            _STRIPE_B: 2,
        }
    )
    assert len(out) == 2, f"a value was dropped: {out!r}"
    assert sorted(out.values()) == [1, 2]


def test_scalars_keep_their_type_unless_a_secret_was_found():
    r = SecretRedactor()
    out = r.redact_dict({"port": 8080, "flag": True, "ratio": 1.5, "pan": 4111111111111111})
    assert out["port"] == 8080 and isinstance(out["port"], int)
    assert out["flag"] is True
    assert out["ratio"] == 1.5
    assert out["pan"] == "[PAN_REDACTED]", "an int that is a valid PAN must not survive"


# ── The entropy pass: why it stays off ────────────────────────────────


def test_the_entropy_pass_would_eat_this_codebase():
    """Not caution — measurement. This is why `from_settings` leaves it off.

    A hex digest and a hex key have the same character distribution, so no
    threshold separates them. `_NOT_A_SECRET_SHAPES` removes the shapes below
    for anyone who turns the pass on; a base64 blob still goes.
    """
    off = SecretRedactor()
    on = SecretRedactor(enable_entropy=True)
    for text in (
        "commit b91a29ae9713861b86bc73dbf10be8a7b4823310",
        "/home/user/weebot/weebot/infrastructure/adapters/llm/_client_policy.py",
        "session a779ecbb-1b3a-5bd9-a2db-8bff1bb2fbce",
        "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    ):
        assert off.redact(text) == text, f"the default pass mangled {text!r}"
        assert on.redact(text) == text, f"the shape exclusion missed {text!r}"

    assert SecretRedactor.from_settings()._enable_entropy is False


# ── C1: it is actually wired now ──────────────────────────────────────


def test_the_live_sanitiser_now_reaches_the_redactor():
    """The whole point of C1: the declared control runs on the live path.

    These three are `SecretRedactor`'s, not the denylist's, so a pass here
    proves the wiring rather than the pattern.
    """
    assert "[PAN_REDACTED]" in sanitize("card 4111 1111 1111 1111 here")
    assert "[STRIPE_KEY_REDACTED]" in sanitize(f"key {_STRIPE_A}")
    assert "[CVV_REDACTED]" in sanitize("cvv: 123")


def test_wiring_the_redactor_did_not_break_the_denylist():
    """REGRESSION GUARD on the wiring, not a red-before-green case."""
    assert "***REDACTED-GITHUB-TOKEN***" in sanitize("ghp_AAAAAAAAAAAAAAAAAAAA")
    # A real JWT. The first fixture here had a 7-character first segment and
    # the pattern requires 8 — the test was wrong, not the rule.
    assert "***REDACTED-JWT***" in sanitize(
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )


def test_the_live_sanitiser_leaves_paths_and_shas_alone():
    """The regression the wiring had to avoid, pinned.

    REGRESSION GUARD: green before the wiring too, because nothing was wired.
    It is what would have gone red had the entropy pass been switched on.
    """
    for text in (
        "/home/user/weebot/weebot/core/credential_sanitizer.py",
        "commit b91a29ae9713861b86bc73dbf10be8a7b4823310",
        "listening on port 8080",
    ):
        assert sanitize(text) == text, f"wiring the redactor mangled {text!r}"


# ── C6: a name is not evidence about a value ──────────────────────────


def test_a_url_on_the_non_secret_allowlist_does_not_log_its_password(caplog):
    """`_is_non_secret` waves through any key ending in URL/HOST/PORT/...

    That is a deny-by-shape heuristic used as an ALLOW rule, and URLs are
    exactly where credentials live. All three below were logged in full.
    """
    caplog.set_level(logging.DEBUG, logger="weebot.config.secret_accessor")
    for key, value in (
        ("DATABASE_URL", "postgres://admin:hunter2@db.internal:5432/prod"),
        ("REDIS_URL", "rediss://:s3cr3tpassword@cache.internal:6379/0"),
        ("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T00/B00/XXXXXXXXXXXXXXXXXXXX"),
    ):
        SecretAccessor.set_source({key: value})
        SecretAccessor.get(key)

    assert "hunter2" not in caplog.text
    assert "s3cr3tpassword" not in caplog.text
    assert "hooks.slack.com/services/T00" not in caplog.text
    # The diagnostic value the allowlist exists for must survive.
    assert "db.internal" in caplog.text
    assert "cache.internal" in caplog.text


def test_an_actually_non_secret_value_is_still_logged_plainly(caplog):
    """REGRESSION GUARD for the existing contract this must not overrule.

    `tests/unit/test_secret_accessor.py` already asserts the TIMEOUT case; this
    repeats it here because the C6 fix runs on exactly this path, and the
    cheapest way to break it would be to redact everything.
    """
    caplog.set_level(logging.DEBUG, logger="weebot.config.secret_accessor")
    SecretAccessor.set_source({"TIMEOUT": "30", "WEEBOT_HOST": "0.0.0.0"})
    SecretAccessor.get("TIMEOUT")
    SecretAccessor.get("WEEBOT_HOST")
    assert "30" in caplog.text
    assert "0.0.0.0" in caplog.text
    assert "<REDACTED>" not in caplog.text
