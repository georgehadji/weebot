"""R21 (audit 2026-10-29): an unbalanced quote does not crash the command parser.

``shlex.split("/what's up")`` raises ``ValueError: No closing quotation``, and the
dispatcher called it unguarded from ``is_command``, so the Telegram message was dropped
with only a log line. The parser now falls back to splitting on whitespace.
"""

from __future__ import annotations

from weebot.application.services.gateway_command_dispatcher import build_default_dispatcher


def test_an_unbalanced_quote_is_not_a_crash():
    dispatcher = build_default_dispatcher()
    assert dispatcher.is_command("/what's up") is False
    assert dispatcher.dispatch("/what's up") is None


def test_a_known_command_with_an_apostrophe_still_parses():
    dispatcher = build_default_dispatcher()
    assert dispatcher.is_command("/model set it's")
    assert dispatcher._parse("/model set it's") == ("model", ["set", "it's"], "set it's")


def test_quotes_still_group_words():
    assert build_default_dispatcher()._parse('/model set "a b"')[1] == ["set", "a b"]
