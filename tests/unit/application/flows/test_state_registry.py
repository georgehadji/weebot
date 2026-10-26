"""LAY-2 / plan 3.6: states reach successors through a registry, not sibling imports.

The registry (``states/base.py``) maps ``StateId`` to a class; every state module
imports ``base`` and nothing imports a sibling, which is what dissolved the 8-module
import cycle. These tests pin the table and the no-sibling rule.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import weebot.application.flows.states  # noqa: F401  (populates the registry)
from weebot.application.flows.states import base
from weebot.application.flows.states.base import FlowState, StateId, new_state, state_class

_STATES_DIR = pathlib.Path(base.__file__).parent
_EXPECTED_NAMES = {
    StateId.PLANNING: "PlanningState",
    StateId.CRITIQUING: "CritiquingState",
    StateId.PREMORTEM: "PremortmState",
    StateId.PLAN_REVIEW: "PlanReviewState",
    StateId.EXECUTING: "ExecutingState",
    StateId.VERIFYING: "VerifyingState",
    StateId.UPDATING: "UpdatingState",
    StateId.REVIEWING: "ReviewingState",
    StateId.SUMMARIZING: "SummarizingState",
}
_BUILDABLE = [s for s in StateId if s is not StateId.COMPLETED]


@pytest.mark.parametrize("state_id", _BUILDABLE)
def test_every_state_id_resolves_to_the_expected_class(state_id):
    assert issubclass(state_class(state_id), FlowState)
    assert state_class(state_id).__name__ == _EXPECTED_NAMES[state_id]


@pytest.mark.parametrize("state_id", _BUILDABLE)
def test_the_registry_builds_each_state(state_id):
    if state_id is StateId.REVIEWING:
        state = new_state(state_id, step=None, reviewer=None)
    elif state_id is StateId.CRITIQUING:
        state = new_state(state_id, critic=None)
    else:
        state = new_state(state_id)
    assert isinstance(state, state_class(state_id))


def test_an_unregistered_id_fails_loudly():
    with pytest.raises(LookupError):
        state_class("nope")  # type: ignore[arg-type]


def test_the_plan_review_helper_follows_the_flag(monkeypatch):
    from weebot.config import settings as settings_module

    for enabled, expected in ((False, "ExecutingState"), (True, "PlanReviewState")):
        monkeypatch.setattr(
            settings_module,
            "get_settings",
            lambda enabled=enabled: type("S", (), {"plan_review_enabled": enabled})(),
        )
        assert type(base.next_state_after_plan()).__name__ == expected


def test_no_cycle_member_imports_a_sibling_state():
    """The rule that keeps the cycle gone (lint_module_cycles ratchets the count)."""
    members = {
        "planning", "critiquing", "premortem", "executing", "verifying",
        "updating", "reviewing", "summarizing", "plan_review", "evidence_gate",
    }
    offenders = []
    for path in sorted(_STATES_DIR.glob("*.py")):
        if path.stem not in members:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if (
                    node.module.startswith("weebot.application.flows.states.")
                    and node.module.rsplit(".", 1)[-1] in members
                    # plan_review is a leaf for flow_router's _APPROVE_TOKENS only
                    and not (path.stem == "plan_review" and node.module.endswith("base"))
                ):
                    offenders.append(f"{path.name} -> {node.module}")
    # executing may reach evidence_gate (a leaf function module that imports only base).
    offenders = [o for o in offenders if o != "executing.py -> weebot.application.flows.states.evidence_gate"]
    assert offenders == [], offenders
