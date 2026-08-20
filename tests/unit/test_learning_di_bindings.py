"""DI binding tests for the three previously-dead learning services (Phase 7).

BehavioralLearner, CorrectionTracker and SessionConstraintExtractor each had
a port, an implementation, consumers, and -- in two cases -- a config field
and a legacy kwarg, while having **zero constructors anywhere in weebot/**.
Every consumer was therefore unreachable at runtime.

That is the failure mode the whole plan is built around ("weebot's binding
constraint is unwired code, not absent capability"), so it gets a test rather
than a comment. These assert the container actually *constructs* each
service, not merely that a key is registered -- a factory that raises resolves
to a crash, not a None, and that is exactly how the first version of this
binding failed (wrong import path for StateRepositoryPort).

See tasks/specs/side_constraint_integrity_plan.md Phase 7.
"""
from __future__ import annotations

import pytest

from weebot.application.di import Container

_KEYS = [
    ("behavioral_learner", "BehavioralLearner"),
    ("correction_tracker", "CorrectionTracker"),
    ("session_constraint_extractor", "SessionConstraintExtractor"),
]


@pytest.fixture(scope="module")
def container():
    """Module-scoped deliberately.

    Resolving these keys constructs a real LLM adapter (see
    _create_llm_for_role), and building one loads an SSL context -- ~24 of
    them on a per-test fixture, which is slow enough to trip pytest's
    timeout. The container is only read here, never mutated, so sharing it
    is safe.
    """
    c = Container()
    c.configure_defaults(db_path=":memory:")
    return c


@pytest.mark.parametrize("key,expected_type", _KEYS, ids=[k for k, _ in _KEYS])
def test_service_resolves_to_a_real_instance(container, key, expected_type):
    obj = container._maybe_get_str(key)
    assert obj is not None, f"{key} resolved to None -- it is dead again"
    assert type(obj).__name__ == expected_type


@pytest.mark.parametrize("key,_t", _KEYS, ids=[k for k, _ in _KEYS])
def test_service_is_a_singleton(container, key, _t):
    """Container.get caches per key; two flows must share one learner."""
    assert container._maybe_get_str(key) is container._maybe_get_str(key)


def test_learner_has_a_state_repo(container):
    """Without one, persistence and hydration are both no-ops."""
    learner = container._maybe_get_str("behavioral_learner")
    assert learner._state_repo is not None


def test_flow_factory_passes_all_three(container):
    """The binding is worthless if create_flow does not read it.

    Guards the specific regression: these services were registered in DI in
    one commit and still not passed by the user-facing factory, leaving them
    exactly as dead as before.
    """
    import inspect

    from weebot.interfaces import factories

    source = inspect.getsource(factories.create_flow)
    for key, _ in _KEYS:
        assert f'_cached("{key}")' in source, (
            f"create_flow never resolves {key} -- the DI binding is unused"
        )
