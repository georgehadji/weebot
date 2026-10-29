"""R02 (audit 2026-10-29): the egress check judges the JMAP request as it will be sent.

The atomic_mail adapter fills ``$NAME`` placeholders into ``ops`` before sending, but the
egress check searched the raw text for "EmailSubmission". ``Email$S/set`` with
``vars={"S": "Submission"}`` became ``EmailSubmission/set`` after the check: mail was sent
with no approval, even in a session that had read untrusted content.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from weebot.core.egress_guard import EgressGuard, RecipientAllowlist
from weebot.core.jmap_ops import fill_vars, method_names, sends_mail


def _guard() -> EgressGuard:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.write_text(json.dumps({}))
    return EgressGuard(allowlist=RecipientAllowlist(path))


def _call(ops: str, **vars: str) -> dict:
    return {"action": "jmap_request", "ops": ops, "vars": vars}


def test_a_send_spelled_through_a_placeholder_is_egress():
    ops = '[["Email$S/set", {"create": {}}, "0"]]'
    decision = _guard().classify("atomic_mail", _call(ops, S="Submission"))
    assert decision.is_egress and decision.requires_approval


@pytest.mark.parametrize(
    "ops",
    [
        '[["EmailSubmission/set", {"create": {}}, "0"]]',
        '[["Email/set", {}, "0"], ["emailsubmission/set", {}, "1"]]',  # case
        "not json at all",  # unreadable: fail closed
        '{"using": []}',  # not a method-call list: fail closed
    ],
)
def test_sends_and_unreadable_requests_are_egress(ops):
    assert _guard().classify("atomic_mail", _call(ops)).is_egress


@pytest.mark.parametrize(
    "ops",
    [
        '[["Email/query", {}, "0"]]',
        '[["Email/set", {"create": {}}, "0"]]',  # a draft
        '[["Mailbox/get", {"accountId": "$ACCOUNT_ID"}, "0"]]',  # session var left as is
        '[["Email/get", {"note": "mentions EmailSubmission in a value"}, "0"]]',
    ],
)
def test_reads_and_drafts_are_not_egress(ops):
    assert not _guard().classify("atomic_mail", _call(ops)).is_egress


def test_the_adapter_and_the_guard_fill_placeholders_the_same_way():
    import importlib

    # The package re-exports a function of the same name; take the module.
    jmap_request = importlib.import_module("weebot.infrastructure.adapters.atomicmail.jmap_request")

    raw = '[["Email$S/set", {"to": "$TO"}, "0"]]'
    values = {"S": "Submission", "TO": "a@b.example"}
    assert jmap_request._substitute_vars(raw, values, {}) == fill_vars(raw, values)
    assert method_names(fill_vars(raw, values)) == ["EmailSubmission/set"]
    assert sends_mail(raw, values)
