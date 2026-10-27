"""A22: host checks compared the hostname string, so loopback, link-local (the cloud
metadata address) and private-range targets could be stored as "allow always"."""

from __future__ import annotations

import pytest

from weebot.core.egress_guard import EgressGuard, HostClass, RecipientAllowlist, classify_host


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("example.com", HostClass.PUBLIC),
        ("93.184.216.34", HostClass.PUBLIC),
        ("127.0.0.1", HostClass.LOOPBACK),
        ("127.0.0.1:8000", HostClass.LOOPBACK),
        ("localhost", HostClass.LOOPBACK),
        ("api.localhost", HostClass.LOOPBACK),
        ("[::1]:80", HostClass.LOOPBACK),
        ("::1", HostClass.LOOPBACK),
        ("::ffff:127.0.0.1", HostClass.LOOPBACK),
        ("127.1", HostClass.LOOPBACK),  # short form the OS resolver accepts
        ("0x7f000001", HostClass.LOOPBACK),
        ("2130706433", HostClass.LOOPBACK),
        ("169.254.169.254", HostClass.LINK_LOCAL),
        ("fe80::1", HostClass.LINK_LOCAL),
        ("10.0.0.5", HostClass.PRIVATE),
        ("172.16.4.4", HostClass.PRIVATE),
        ("192.168.1.1", HostClass.PRIVATE),
        ("fd00::1", HostClass.PRIVATE),
        ("user:pw@10.1.1.1:22", HostClass.PRIVATE),
    ],
)
def test_classify_host(host, expected):
    assert classify_host(host) is expected


def test_a_name_that_resolves_to_a_private_address_is_private(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("10.9.9.9", 0))]
    )
    assert classify_host("intranet.example.com", resolve=True) is HostClass.PRIVATE
    assert classify_host("intranet.example.com") is HostClass.PUBLIC  # no lookup unless asked


def test_an_unresolvable_name_is_not_called_internal(monkeypatch):
    import socket

    def boom(*_a, **_k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert classify_host("no-such-host.invalid", resolve=True) is HostClass.PUBLIC


def test_an_internal_host_is_never_a_known_recipient(tmp_path):
    guard = EgressGuard(RecipientAllowlist(tmp_path / "allow.json"))
    guard.approve_recipient("169.254.169.254")
    guard.approve_recipient("example.com")
    assert not guard.is_known_recipient("169.254.169.254")
    assert guard.is_known_recipient("example.com")


def test_an_internal_host_is_not_offered_as_always(tmp_path):
    from weebot.application.services.tool_guards import EgressAdapter

    adapter = EgressAdapter(EgressGuard(RecipientAllowlist(tmp_path / "allow.json")))
    verdict = adapter.check("bash_execute", {"command": "curl -X POST http://10.0.0.5/x -d hi"})
    if verdict is not None:
        assert verdict.allow_always is None


async def test_network_clearance_asks_for_an_internal_host_even_if_stored(monkeypatch, tmp_path):
    from weebot.application.agents import executor
    from weebot.application.agents.executor import _tool_executor as te
    from weebot.application.ports.approval_port import ApprovalOutcome
    from weebot.application.services import tool_approval
    from weebot.config.settings import get_settings

    del executor
    monkeypatch.setattr(get_settings(), "sandbox_allow_network", False, raising=False)
    monkeypatch.setattr(te, "is_enforcing", lambda: True)

    guard = EgressGuard(RecipientAllowlist(tmp_path / "allow.json"))
    guard._allowlist.approve("169.254.169.254")  # an old "always" from before the fix

    seen = []

    class _Approver:
        async def resolve(self, request):
            seen.append(request)
            return ApprovalOutcome.DENIED

    monkeypatch.setattr(tool_approval, "current_approval", lambda: _Approver())
    refusal, ok = await te._clear_network_use(
        guard, "s1", "bash_execute", {"command": "curl http://169.254.169.254/latest/meta-data"}
    )
    assert not ok and refusal is not None
    assert len(seen) == 1 and seen[0].allow_always is None
