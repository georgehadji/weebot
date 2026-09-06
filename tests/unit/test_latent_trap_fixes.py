"""D53, D56, D57, D58 — four latent traps, fixed where fixing costs nothing.

Each was found by a V3 audit pass and deferred, because changing code inside a
security diff that the diff did not need is the unrelated refactoring the
protocol forbids. Gathered here instead, in one change of their own.

Three of them are unreachable today: `is_admin`, `get_model_cost_info` and
`get_cheapest_model_for_task` have no callers in `weebot/` or `cli/`. That is
exactly what makes fixing them safe -- the blast radius is zero -- and exactly
why they are dangerous left alone: the first caller inherits the trap, and none
of them fails loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weebot.application.services.fs_permission_checker import FSPermissionChecker
from weebot.config.model_registry import (
    MODEL_REGISTRY,
    get_cheapest_model_for_task,
    get_model_cost_info,
)
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


def test_an_unknown_model_has_no_cost_information(tmp_path: Path) -> None:
    """It used to return {0.01, 0.03} -- $10/$30 per million, invented -- with
    nothing to distinguish it from a real price."""
    assert get_model_cost_info("no/such-model-xyz") is None


def test_a_known_model_still_reports_its_cost() -> None:
    name = next(iter(MODEL_REGISTRY))
    info = get_model_cost_info(name)
    assert info is not None
    assert set(info) == {"input_cost_per_1k_tokens", "output_cost_per_1k_tokens"}


# ── D58: an unrecognised requirement must not filter nothing ─────────────────


def test_an_unknown_capability_is_rejected_rather_than_ignored() -> None:
    """`required_capabilities=["json_mode"]` returned a model, because the
    chained `cap == "x" and not supports_x` clauses are all False for a name no
    clause mentions. The caller believed a filter had been applied."""
    with pytest.raises(ValueError, match="json_mode"):
        get_cheapest_model_for_task(1000, 100, required_capabilities=["json_mode"])


def test_a_misspelled_capability_is_rejected() -> None:
    with pytest.raises(ValueError, match="funtcion_calling"):
        get_cheapest_model_for_task(1000, 100, required_capabilities=["funtcion_calling"])


@pytest.mark.parametrize(
    "capability", ["function_calling", "vision", "system_messages", "response_schema", "prompt_caching"]
)
def test_every_supported_capability_still_filters(capability: str) -> None:
    model = get_cheapest_model_for_task(1000, 100, required_capabilities=[capability])
    if model is not None:
        assert getattr(model, f"supports_{capability}") is True


def test_no_capability_requirement_still_returns_the_cheapest() -> None:
    assert get_cheapest_model_for_task(1000, 100) is not None
