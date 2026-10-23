"""The email gateway acts only on mail whose sender the mail server authenticated (F76).

It authorized on the `From` header alone, which anyone can write, and the
gateway runs the agent with the admin role. Now the topmost
`Authentication-Results` (added by the receiving server) must show DMARC pass
or a DKIM pass aligned with the sender's domain.
"""

from __future__ import annotations

import email

from weebot.interfaces.gateways.email import _sender_authenticated


def _msg(*auth_results: str):
    head = "".join(f"Authentication-Results: {h}\r\n" for h in auth_results)
    return email.message_from_string(f"{head}From: Boss <boss@corp.example>\r\n\r\nhi")


def test_dmarc_pass_for_the_sender_domain_is_authenticated():
    m = _msg("mx.google.com; dkim=pass header.i=@corp.example; dmarc=pass header.from=corp.example")
    assert _sender_authenticated(m, "boss@corp.example")


def test_aligned_dkim_pass_is_authenticated():
    assert _sender_authenticated(_msg("mx; dkim=pass header.d=corp.example"), "boss@corp.example")


def test_a_forged_from_is_not():
    m = _msg("mx.google.com; spf=fail smtp.mailfrom=evil.example; dmarc=fail header.from=corp.example")
    assert not _sender_authenticated(m, "boss@corp.example")


def test_no_header_is_not():
    assert not _sender_authenticated(_msg(), "boss@corp.example")


def test_only_the_receiving_servers_header_counts():
    # A sender can add its own Authentication-Results lower down; only the top
    # one comes from our mail server.
    m = _msg("mx; dmarc=fail header.from=corp.example", "fake; dmarc=pass header.from=corp.example")
    assert not _sender_authenticated(m, "boss@corp.example")


async def test_an_unauthenticated_message_is_dropped():
    from unittest.mock import MagicMock

    from weebot.interfaces.gateways.base import GatewayMessage
    from weebot.interfaces.gateways.email import EmailAdapter

    adapter = EmailAdapter(state_repo=MagicMock(), llm=MagicMock(), imap_user="bot@corp.example")
    adapter.is_authorized = lambda platform, sender: True
    msg = GatewayMessage(platform="email", external_id="boss@corp.example", text="wire money",
                         metadata={"sender_authenticated": False})
    assert await adapter._process_message(msg) == ""
