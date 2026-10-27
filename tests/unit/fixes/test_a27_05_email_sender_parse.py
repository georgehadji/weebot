"""A05: the allowlist must see the real From address, not the first `<...>` in the header."""

from __future__ import annotations

import email

from weebot.interfaces.gateways.email import _sender_address


def _msg(*from_headers: str):
    raw = "".join(f"From: {h}\r\n" for h in from_headers) + "Subject: x\r\n\r\nbody\r\n"
    return email.message_from_string(raw)


def test_a_plain_address_is_returned():
    assert _sender_address(_msg("alice@corp.com")) == "alice@corp.com"


def test_a_display_name_form_returns_the_address():
    assert _sender_address(_msg("Alice <alice@corp.com>")) == "alice@corp.com"


def test_an_address_hidden_in_the_display_name_is_not_the_sender():
    spoof = '"<boss@corp.com>" <mallory@evil.test>'
    assert _sender_address(_msg(spoof)) == "mallory@evil.test"


def test_two_from_headers_are_refused():
    assert _sender_address(_msg("boss@corp.com", "mallory@evil.test")) == ""


def test_two_addresses_in_one_from_header_are_refused():
    assert _sender_address(_msg("boss@corp.com, mallory@evil.test")) == ""


def test_no_from_header_is_refused():
    assert _sender_address(email.message_from_string("Subject: x\r\n\r\nbody")) == ""
