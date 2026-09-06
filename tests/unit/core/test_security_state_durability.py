"""D52 — persisted security-control state must survive a crash and a bad parse.

`GatewayAuth` and `RecipientAllowlist` both persist a security decision that an
operator took deliberately: "this user is blocked", "this recipient is
approved". Both wrote it with `Path.write_text`, which truncates the file before
writing, and both answered a parse failure by silently substituting an empty or
default rule set. The next administrative action then saved that substitute over
the unreadable file.

Violated property: **a persisted access-control decision survives a process
restart.** `block_user` is durable by contract -- after it returns, the block
must still be recoverable. One interrupted write breaks that, and the next save
makes it unrecoverable with no copy kept.

These fire against the original code and pass after the fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weebot.core.egress_guard import RecipientAllowlist
from weebot.core.gateway_auth import GatewayAuth


def _half_written(_self: Path, data: str, **_kw: object) -> int:
    """Model a write that dies partway: the file is truncated, then it fails.

    This is what a crash, a full disk or an evicted container leaves behind, and
    it is the state `Path.write_text` can leave the real file in because it
    truncates before writing.
    """
    _self.write_bytes(data[: len(data) // 2].encode("utf-8"))
    raise OSError(28, "No space left on device")


def test_a_save_that_dies_partway_does_not_leave_the_gateway_config_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed write must not destroy the config it was replacing."""
    cfg = tmp_path / "gateway_auth.json"
    auth = GatewayAuth(cfg)
    auth.block_user("telegram", "mallory")

    monkeypatch.setattr(Path, "write_text", _half_written)
    try:
        auth.allow_user("telegram", "alice")
    except OSError:
        pass  # the write failed; the question is what it left behind

    rules = json.loads(cfg.read_text(encoding="utf-8"))  # fails today: truncated JSON
    assert "mallory" in rules["blocked_users"]["telegram"]


def test_an_unreadable_gateway_config_is_preserved_rather_than_overwritten(
    tmp_path: Path,
) -> None:
    """A config that will not parse is evidence. Do not silently destroy it."""
    cfg = tmp_path / "gateway_auth.json"
    auth = GatewayAuth(cfg)
    auth.block_user("telegram", "mallory")
    auth.allow_chat("telegram", "trusted-chat")
    original = cfg.read_text(encoding="utf-8")

    cfg.write_text(original[: len(original) // 2], encoding="utf-8")
    corrupt = cfg.read_text(encoding="utf-8")

    GatewayAuth(cfg).allow_user("telegram", "alice")  # any admin action saves

    preserved = list(tmp_path.glob("*.corrupt.bak"))
    assert preserved, "the unreadable config was overwritten with no copy kept"
    assert preserved[0].read_text(encoding="utf-8") == corrupt


def test_an_unreadable_gateway_config_is_reported_loudly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Losing an access-control list is not a warning-level event."""
    cfg = tmp_path / "gateway_auth.json"
    GatewayAuth(cfg).block_user("telegram", "mallory")
    cfg.write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level("ERROR", logger="weebot.core.gateway_auth"):
        GatewayAuth(cfg)
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_a_save_that_dies_partway_does_not_lose_the_egress_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same property, same failure, on the egress recipient allowlist."""
    path = tmp_path / "egress_allowlist.json"
    allowlist = RecipientAllowlist(path)
    allowlist.approve("finance@example.com")

    monkeypatch.setattr(Path, "write_text", _half_written)
    allowlist.approve("ops@example.com")  # _save swallows its own exceptions

    reloaded = RecipientAllowlist(path)
    assert reloaded.is_known("finance@example.com")


# ── D52, second half: JSON that parses is not JSON that is shaped right ──────
#
# Found by the RAR invalid-input vector while reviewing the atomic-write fix.
# Every payload below is valid JSON, and every one of them used to raise out of
# the authorization decision itself.


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '"a string"',
        "null",
        "123",
        '{"allowed_platforms": null}',
        '{"allowed_platforms": ["telegram"], "blocked_users": "nope"}',
        '{"allowed_users": {"telegram": null}}',
        '{"admin_ids": 7}',
    ],
)
def test_a_misshapen_config_cannot_crash_the_authorization_decision(
    payload: str, tmp_path: Path
) -> None:
    """An access-control gate must not be crashable by editing its config."""
    cfg = tmp_path / "gateway_auth.json"
    cfg.write_text(payload, encoding="utf-8")

    auth = GatewayAuth(cfg)
    verdicts = (
        auth.is_platform_allowed("telegram"),
        auth.is_user_allowed("telegram", "someone"),
        auth.is_admin("telegram", "someone"),
    )
    assert all(isinstance(v, bool) for v in verdicts), f"non-boolean verdict: {verdicts}"


def test_a_rejected_value_is_not_put_back_by_the_recovery_path(tmp_path: Path) -> None:
    """The first draft of the fix re-admitted exactly what it had just rejected.

    `_normalized` dropped a wrongly-typed key and then a `setdefault` pass over
    the raw payload restored it, so `allow_all_by_default: "yes"` came back as a
    truthy string and opened the gate.
    """
    cfg = tmp_path / "gateway_auth.json"
    cfg.write_text('{"allow_all_by_default": "yes"}', encoding="utf-8")

    auth = GatewayAuth(cfg)
    assert auth.is_user_allowed("telegram", "anyone") is False
    assert auth.get_config().get("allow_all_by_default", False) != "yes"


def test_an_unrecognised_key_is_carried_through(tmp_path: Path) -> None:
    """Only keys this class interprets are type-checked; the rest survive."""
    cfg = tmp_path / "gateway_auth.json"
    cfg.write_text('{"custom_operator_note": "renewal 2027"}', encoding="utf-8")
    assert GatewayAuth(cfg).get_config()["custom_operator_note"] == "renewal 2027"
