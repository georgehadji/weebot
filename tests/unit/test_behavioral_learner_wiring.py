"""Regression tests for BehavioralLearner's three wiring defects (Phase 7).

The learner had zero constructors anywhere in weebot/, so none of these ever
surfaced at runtime. Registering it in DI without fixing them first would
have wired dead code to dead code:

1. `save_behavioral_rule(rule)` vs the repo's
   `save_behavioral_rule(rule_id, rule_text, ...)` -- every persist raised
   TypeError into a bare `except`, so persistence silently did nothing;
2. `_store` was never hydrated from the repo, so `get_rules_for_prompt()`
   returned "" in every fresh process regardless of what was stored;
3. `_determine_scope` defaulted to `'global'`, making one offhand correction
   a durable cross-session rule with no expiry.

See tasks/specs/side_constraint_integrity_plan.md Phase 7.1.
"""

from __future__ import annotations

from weebot.application.services.behavioral_learner import BehavioralLearner
from weebot.domain.models.behavioral_rule import BehavioralRule


class _FakeRepo:
    """Mimics SQLiteStateRepository's actual behavioral-rule signatures."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.saved: list[tuple] = []

    async def save_behavioral_rule(
        self, rule_id, rule_text, source_session_id="", source_message="", scope="global"
    ):
        self.saved.append((rule_id, rule_text, source_session_id, source_message, scope))

    async def list_behavioral_rules(self):
        return self.rows


def _row(rule_id, text, scope="global"):
    return {
        "id": rule_id,
        "rule_text": text,
        "source_session_id": "s0",
        "source_message": "m",
        "scope": scope,
    }


class TestPersistArity:
    async def test_persist_calls_repo_with_fields_not_the_model(self):
        """Defect 1: passing the model raised TypeError on every call."""
        repo = _FakeRepo()
        learner = BehavioralLearner(state_repo=repo)

        rule = await learner.learn_from_correction(
            "No, never use tabs for indentation.",
            {"session_id": "s1", "step_description": "", "tool_name": ""},
        )

        assert rule is not None, "the correction should have produced a rule"
        assert len(repo.saved) == 1, "the rule was not persisted"
        rule_id, rule_text, session_id, _msg, scope = repo.saved[0]
        assert rule_id == rule.id
        assert rule_text == rule.rule_text
        assert session_id == "s1"
        assert scope == rule.scope


class TestScope:
    def test_defaults_to_session_not_global(self):
        """Defect 3: a one-off correction must not become a durable rule."""
        assert BehavioralLearner._determine_scope("never use tabs", {}) == "session"

    def test_tool_scoped_rule_still_detected(self):
        scope = BehavioralLearner._determine_scope("never call bash with rm", {"tool_name": "bash"})
        assert scope == "per_tool"


class TestHydration:
    async def test_global_rules_load_into_the_prompt(self):
        """Defect 2: stored rules were invisible to every new process."""
        repo = _FakeRepo([_row("r1", "always run tests", scope="global")])
        learner = BehavioralLearner(state_repo=repo)

        assert learner.get_rules_for_prompt() == ""
        await learner.hydrate()

        prompt = learner.get_rules_for_prompt()
        assert "always run tests" in prompt
        assert "# Behavioral Rules" in prompt

    async def test_session_scoped_rules_do_not_leak_across_sessions(self):
        repo = _FakeRepo(
            [
                _row("r1", "session-only rule", scope="session"),
                _row("r2", "durable rule", scope="global"),
            ]
        )
        learner = BehavioralLearner(state_repo=repo)
        await learner.hydrate()

        prompt = learner.get_rules_for_prompt()
        assert "durable rule" in prompt
        assert "session-only rule" not in prompt

    async def test_hydrate_is_idempotent(self):
        repo = _FakeRepo([_row("r1", "always run tests")])
        learner = BehavioralLearner(state_repo=repo)

        await learner.hydrate()
        await learner.hydrate()

        assert len(await learner.get_active_rules()) == 1

    async def test_hydrate_does_not_duplicate_existing_rules(self):
        existing = BehavioralRule(
            id="r1",
            rule_text="always run tests",
            source_session_id="s0",
            source_message="m",
            scope="global",
        )
        repo = _FakeRepo([_row("r1", "always run tests")])
        learner = BehavioralLearner(state_repo=repo, store=[existing])

        await learner.hydrate()

        assert len(await learner.get_active_rules()) == 1

    async def test_hydrate_without_repo_is_a_noop(self):
        learner = BehavioralLearner()
        await learner.hydrate()
        assert await learner.get_active_rules() == []

    async def test_repo_failure_does_not_raise(self):
        class _Broken(_FakeRepo):
            async def list_behavioral_rules(self):
                raise RuntimeError("db exploded")

        learner = BehavioralLearner(state_repo=_Broken())
        await learner.hydrate()  # must not propagate
        assert await learner.get_active_rules() == []

    async def test_malformed_row_does_not_poison_the_rest(self):
        repo = _FakeRepo(
            [{"scope": "global"}, _row("r2", "good rule")]  # no id -> KeyError inside the loop
        )
        learner = BehavioralLearner(state_repo=repo)
        await learner.hydrate()

        assert "good rule" in learner.get_rules_for_prompt()
