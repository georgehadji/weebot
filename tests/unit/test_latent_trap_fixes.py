"""D53, D56, D57, D58 — four latent traps, fixed where fixing costs nothing.

Each was found by a V3 audit pass and deferred, because changing code inside a
security diff that the diff did not need is the unrelated refactoring the
protocol forbids. Gathered here instead, in one change of their own.

Three of them were unreachable: `is_admin`, `get_model_cost_info` and
`get_cheapest_model_for_task` had no callers in `weebot/` or `cli/`. That is
exactly what made fixing them safe -- the blast radius is zero -- and exactly
why they were dangerous left alone: the first caller inherits the trap, and none
of them fails loudly. The last two were deleted in phase 3.2 with the
hand-written registry they served; D57's invariant is kept below against the
lookup that replaced them. D58 went with them: no capability-name filter
remains to misspell.
"""

from __future__ import annotations

from pathlib import Path

from weebot.application.services.fs_permission_checker import FSPermissionChecker
from weebot.config.model_registry import get_model_config
from weebot.core.gateway_auth import GatewayAuth
from weebot.domain.models.fs_permission import FilesystemPermission


# ── D53: a block must revoke admin ───────────────────────────────────────────


def test_blocking_a_user_revokes_their_admin_rights(tmp_path: Path) -> None:
    """`is_user_allowed` and `is_chat_allowed` both check the blocklist first.
    `is_admin` was the only accessor that did not, so a blocked user stayed an
    admin -- a privilege the block was meant to remove."""
    cfg = tmp_path / "gateway_auth.json"
    auth = GatewayAuth(cfg)
    auth.allow_user("telegram", "root")
    auth._rules.setdefault("admin_ids", {}).setdefault("telegram", []).append("root")
    auth._save()

    assert GatewayAuth(cfg).is_admin("telegram", "root") is True

    GatewayAuth(cfg).block_user("telegram", "root")
    assert GatewayAuth(cfg).is_admin("telegram", "root") is False


def test_an_unblocked_admin_is_still_an_admin(tmp_path: Path) -> None:
    cfg = tmp_path / "gateway_auth.json"
    auth = GatewayAuth(cfg)
    auth._rules.setdefault("admin_ids", {}).setdefault("telegram", []).append("ops")
    auth._save()
    assert GatewayAuth(cfg).is_admin("telegram", "ops") is True


# ── D56: the docstring's promise, kept ───────────────────────────────────────


def _checker(tmp_path: Path) -> FSPermissionChecker:
    return FSPermissionChecker(
        rules=[FilesystemPermission(operations=["read"], paths=["confidential/**"], mode="deny")],
        workspace_root=str(tmp_path),
    )


def test_a_relative_candidate_is_resolved_against_the_workspace_root(tmp_path: Path) -> None:
    """The class docstring says candidate paths are resolved against the
    workspace root "so a relative rule means what it appears to mean". Only the
    *patterns* were; a relative candidate silently matched nothing."""
    checker = _checker(tmp_path)
    assert checker.check("read", "confidential/keys.txt") == "deny"
    assert checker.check("read", "./confidential/keys.txt") == "deny"


def test_an_absolute_candidate_is_unchanged(tmp_path: Path) -> None:
    """Resolution must be a superset: absolute paths behave exactly as before."""
    checker = _checker(tmp_path)
    assert checker.check("read", str(tmp_path / "confidential/keys.txt")) == "deny"
    assert checker.check("read", str(tmp_path / "public/keys.txt")) == "allow"
    assert checker.check("read", "/somewhere/else/entirely") == "allow"


# ── D57: an unknown price is not a price ─────────────────────────────────────


def test_an_unknown_model_has_no_cost_information() -> None:
    """It used to return {0.01, 0.03} -- $10/$30 per million, invented -- with
    nothing to distinguish it from a real price. The catalog lookup that
    replaced get_model_cost_info returns None for the same condition."""
    assert get_model_config("no/such-model-xyz") is None


def test_a_known_model_reports_a_real_split_price() -> None:
    info = get_model_config("anthropic/claude-sonnet-5")
    assert info is not None
    prompt, completion = info.split_cost_per_1k()
    assert 0 < prompt < completion  # the split the blended rate cannot express
