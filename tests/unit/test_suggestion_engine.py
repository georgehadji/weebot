"""Unit tests for SuggestionEngine."""
from __future__ import annotations

import pytest

from weebot.application.services.suggestion_engine import (
    SuggestionEngine,
    BlueprintSuggestion,
)
from weebot.domain.models.skill import Skill


class TestBlueprintSuggestion:
    """BlueprintSuggestion creation and conversion."""

    def test_minimal_suggestion(self):
        s = BlueprintSuggestion(
            skill_name="test-skill",
            schedule="0 * * * *",
            prompt="Run test skill",
        )
        assert s.id.startswith("suggestion-")
        assert s.skill_name == "test-skill"
        assert s.schedule == "0 * * * *"
        assert s.status == "pending"

    def test_from_skill_with_blueprint(self):
        skill = Skill(
            name="monitor-skill",
            description="A monitoring skill",
            content="# Monitor\nDo monitoring things.",
            blueprint={
                "schedule": "*/5 * * * *",
                "prompt": "Run the monitor",
                "deliver_to": "telegram",
                "destination": "12345",
            },
        )
        s = BlueprintSuggestion.from_skill(skill)
        assert s is not None
        assert s.skill_name == "monitor-skill"
        assert s.schedule == "*/5 * * * *"
        assert s.deliver_to == "telegram"
        assert s.destination == "12345"

    def test_from_skill_without_blueprint(self):
        skill = Skill(name="no-bp", description="No blueprint", content="# No BP")
        s = BlueprintSuggestion.from_skill(skill)
        assert s is None

    def test_to_dict_roundtrip(self):
        s = BlueprintSuggestion(skill_name="test", schedule="0 0 * * *", prompt="Run")
        d = s.to_dict()
        assert d["skill_name"] == "test"
        assert d["schedule"] == "0 0 * * *"
        assert d["status"] == "pending"


class TestSuggestionEngine:
    """SuggestionEngine lifecycle."""

    def setup_method(self):
        self.engine = SuggestionEngine()
        # Replace the file-backed store with in-memory
        self.engine._suggestions = {}

    def test_add_suggestion(self):
        s = BlueprintSuggestion(skill_name="test", schedule="0 * * * *", prompt="Run test")
        self.engine.add_suggestion(s)
        pending = self.engine.list_pending()
        assert len(pending) == 1
        assert pending[0].skill_name == "test"

    def test_accept_suggestion(self):
        s = BlueprintSuggestion(skill_name="test", schedule="0 * * * *", prompt="Run test")
        self.engine.add_suggestion(s)
        accepted = self.engine.accept(s.id)
        assert accepted is not None
        assert accepted.status == "accepted"
        assert len(self.engine.list_pending()) == 0

    def test_dismiss_suggestion(self):
        s = BlueprintSuggestion(skill_name="test", schedule="0 * * * *", prompt="Run test")
        self.engine.add_suggestion(s)
        assert self.engine.dismiss(s.id) is True
        assert len(self.engine.list_pending()) == 0
        assert len(self.engine.list_all()) == 1

    def test_accept_unknown_id(self):
        assert self.engine.accept("nonexistent") is None

    def test_dismiss_unknown_id(self):
        assert self.engine.dismiss("nonexistent") is False

    def test_add_from_skill_with_blueprint(self):
        skill = Skill(
            name="auto-skill",
            description="Auto",
            content="# Auto",
            blueprint={"schedule": "0 * * * *", "prompt": "Auto run"},
        )
        s = self.engine.add_from_skill(skill)
        assert s is not None
        assert s.skill_name == "auto-skill"
        assert len(self.engine.list_pending()) == 1

    def test_add_from_skill_without_blueprint(self):
        skill = Skill(name="no-bp", description="no bp", content="# no")
        s = self.engine.add_from_skill(skill)
        assert s is None
        assert len(self.engine.list_pending()) == 0
