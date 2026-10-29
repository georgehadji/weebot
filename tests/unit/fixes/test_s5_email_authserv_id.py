"""S5 (remaining-work plan 2026-10-29): only our mail server's verdict authenticates a sender.

The gateway trusted the topmost ``Authentication-Results`` header whoever wrote it. When
the receiving server adds none, the topmost one is the sender's own, so a forged
``dmarc=pass`` let a spoofed ``From`` through (the rest of A27). A header now counts only
when its authserv-id (RFC 8601) is one the receiving server uses.
"""

from __future__ import annotations

import email

from weebot.interfaces.gateways.email import (
    EmailAdapter,
    _sender_authenticated,
    _trusted_ids_for,
)

_PASS = "dkim=pass header.i=@corp.example; dmarc=pass header.from=corp.example"


def _msg(*auth_results: str):
    head = "".join(f"Authentication-Results: {h}\r\n" for h in auth_results)
    return email.message_from_string(f"{head}From: Boss <boss@corp.example>\r\n\r\nhi")


def test_a_verdict_from_an_unknown_server_does_not_count():
    trusted = _trusted_ids_for("imap.gmail.com", None)
    assert not _sender_authenticated(_msg(f"evil.example; {_PASS}"), "boss@corp.example", trusted)


def test_gmail_stamps_mx_google_com():
    trusted = _trusted_ids_for("imap.gmail.com", None)
    assert _sender_authenticated(_msg(f"mx.google.com; {_PASS}"), "boss@corp.example", trusted)


def test_a_forged_header_above_ours_is_skipped():
    trusted = _trusted_ids_for("imap.gmail.com", None)
    forged = f"evil.example; {_PASS}"
    ours = "mx.google.com; dmarc=fail header.from=corp.example"
    assert not _sender_authenticated(_msg(forged, ours), "boss@corp.example", trusted)


def test_a_version_after_the_id_is_allowed():
    trusted = _trusted_ids_for("mail.corp.example", None)
    assert _sender_authenticated(_msg(f"mail.corp.example 1; {_PASS}"), "boss@corp.example", trusted)


def test_the_setting_replaces_the_default():
    trusted = _trusted_ids_for("imap.gmail.com", "mx.corp.example, MX2.corp.example")
    assert trusted == frozenset({"mx.corp.example", "mx2.corp.example"})


def test_the_adapter_uses_its_imap_host():
    adapter = EmailAdapter(state_repo=None, llm=None, imap_server="imap.gmail.com")
    assert "mx.google.com" in adapter._trusted_authserv_ids
