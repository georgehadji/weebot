"""net_trust: pure Host, Origin and peer checks behind the web API's loopback trust.

With no API key, a request from the machine's own loopback address counts as the operator.
DNS rebinding and a hostile web page both reach that address through the operator's browser,
carrying a Host or Origin that is not the operator's. These functions decide which are theirs.
They do no I/O and read no settings.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from weebot.core.net_trust import (
    DEFAULT_ALLOWED_HOSTS,
    host_allowed,
    is_loopback_peer,
    origin_allowed,
    parse_allowed_hosts,
)

ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("localhost", True),
        ("localhost:8000", True),
        ("LOCALHOST:8000", True),
        ("127.0.0.1", True),
        ("127.0.0.1:8000", True),
        ("[::1]", True),
        ("[::1]:8000", True),
        ("localhost.", False),
        ("localhost.evil.test", False),
        ("127.0.0.1.evil.test", False),
        ("evil.test", False),
        ("evil.test:8000", False),
        ("evil.test:localhost", False),
        ("localhost@evil.test", False),
        ("", False),
        (None, False),
        ("[::1", False),
        ("::1", False),  # an IPv6 literal must be bracketed in a Host header
    ],
)
def test_host_allowed_table(header, expected):
    assert host_allowed(header, DEFAULT_ALLOWED_HOSTS) is expected


def test_host_allowed_honours_a_configured_name():
    allowed = DEFAULT_ALLOWED_HOSTS | parse_allowed_hosts("weebot.lan, Dash.Example:8443")
    assert host_allowed("weebot.lan:8000", allowed)
    assert host_allowed("dash.example", allowed)
    assert not host_allowed("evil.weebot.lan", allowed)


def test_parse_allowed_hosts_drops_blanks_and_ports():
    assert parse_allowed_hosts("") == frozenset()
    assert parse_allowed_hosts(" , a.test:80,B.TEST ,") == frozenset({"a.test", "b.test"})


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", min_size=1, max_size=30))
def test_a_host_is_allowed_only_when_it_equals_an_allowed_name(name):
    assert host_allowed(name, DEFAULT_ALLOWED_HOSTS) is (name in DEFAULT_ALLOWED_HOSTS)
    assert host_allowed(f"{name}:8000", DEFAULT_ALLOWED_HOSTS) is (name in DEFAULT_ALLOWED_HOSTS)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("http://localhost:3000", True),
        ("http://127.0.0.1:3000", True),
        ("HTTP://LOCALHOST:3000", True),
        ("http://localhost:3001", False),
        ("https://localhost:3000", False),
        ("http://evil.test", False),
        ("http://localhost:3000.evil.test", False),
        ("http://localhost:3000/", True),
        ("null", False),
        ("", False),
        (None, False),
    ],
)
def test_origin_allowed_table(origin, expected):
    assert origin_allowed(origin, ORIGINS) is expected


@pytest.mark.parametrize(
    ("peer", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("127.5.5.5", False),  # the repo's identity rule is the exact set, as before
        ("localhost", False),  # a peer is an address, never a name
        ("10.0.0.5", False),
        ("172.18.0.3", False),
        ("evil.test", False),
        ("", False),
        (None, False),
    ],
)
def test_is_loopback_peer(peer, expected):
    assert is_loopback_peer(peer) is expected
