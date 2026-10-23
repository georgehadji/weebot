"""Tests for Phase 4: RoleModelSelector."""

import pytest

from weebot.application.services.role_model_selector import RoleModelSelector
from weebot.config.model_refs import ROLE_MODEL_CONFIG


@pytest.fixture
def selector():
    return RoleModelSelector(default_model="x-ai/grok-build-0.1")


def test_returns_primary_model_for_configured_role(selector):
    """'critic' returns the first model in ROLE_MODEL_CONFIG, read from there:
    a copied id here is a second home for a routing fact."""
    assert selector.select("critic") == ROLE_MODEL_CONFIG["critic"][0]


def test_planner_uses_its_role_primary(selector):
    assert selector.select("planner") == ROLE_MODEL_CONFIG["planner"][0]


def test_falls_back_to_default_for_unknown_role(selector):
    """Unregistered role returns default_model."""
    model = selector.select("unknown_role")
    assert model == "x-ai/grok-build-0.1"


def test_raises_without_default_for_unknown_role():
    """No default + unknown role raises ValueError."""
    s = RoleModelSelector(default_model=None)
    with pytest.raises(ValueError, match="No model configured"):
        s.select("nonexistent_role")


def test_fallback_chain_has_entries(selector):
    """Chain has >= 2 entries for 'planner'."""
    chain = selector.fallback_chain("planner")
    assert len(chain) >= 2


def test_fallback_chain_for_unknown_role(selector):
    """Unknown role returns default in list."""
    chain = selector.fallback_chain("nonexistent")
    assert len(chain) == 1
    assert chain[0] == "x-ai/grok-build-0.1"
