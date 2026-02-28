"""Unit tests for NotificationCategorizer."""
import pytest
from weebot.notifications_categorizer import NotificationCategorizer, UserRule


class TestBuiltinKeywords:
    def setup_method(self):
        self.cat = NotificationCategorizer()

    def test_urgent_keyword(self):
        assert self.cat.categorize("urgent task needed", {}) == "urgent"

    def test_health_keyword(self):
        assert self.cat.categorize("blood sugar is 120", {}) == "health"

    def test_reminder_keyword(self):
        assert self.cat.categorize("reminder: take medicine", {}) == "reminder"

    def test_email_keyword(self):
        assert self.cat.categorize("new email in inbox", {}) == "email"

    def test_calendar_keyword(self):
        assert self.cat.categorize("meeting in 10 minutes", {}) == "calendar"

    def test_build_keyword(self):
        assert self.cat.categorize("CI build failed on main", {}) == "build"

    def test_error_keyword(self):
        assert self.cat.categorize("error: connection refused", {}) == "error"

    def test_default_when_no_match(self):
        assert self.cat.categorize("hello world", {}) == "info"


class TestMetadataOverride:
    def setup_method(self):
        self.cat = NotificationCategorizer()

    def test_metadata_category_wins_over_keywords(self):
        result = self.cat.categorize("urgent meeting", {"category": "calendar"})
        assert result == "calendar"

    def test_metadata_intent_used_when_no_category(self):
        result = self.cat.categorize("your glucose is high", {"intent": "health"})
        assert result == "health"


class TestUserRules:
    def setup_method(self):
        self.cat = NotificationCategorizer(user_rules=[
            UserRule(pattern="invoice|receipt", is_regex=True, category="email"),
            UserRule(pattern="standup", is_regex=False, category="calendar"),
        ])

    def test_regex_rule_matches(self):
        assert self.cat.categorize("new invoice available", {}) == "email"

    def test_literal_rule_matches(self):
        assert self.cat.categorize("standup in 5 mins", {}) == "calendar"

    def test_rule_wins_over_keywords(self):
        assert self.cat.categorize("invoice due", {}) == "email"

    def test_metadata_wins_over_user_rules(self):
        result = self.cat.categorize("invoice due", {"category": "urgent"})
        assert result == "urgent"

    def test_disabled_rule_is_skipped(self):
        cat = NotificationCategorizer(user_rules=[
            UserRule(pattern="invoice", is_regex=False, category="email", enabled=False),
        ])
        assert cat.categorize("invoice received", {}) == "info"

    def test_metadata_intent_wins_over_user_rules(self):
        cat = NotificationCategorizer(user_rules=[
            UserRule(pattern="invoice", is_regex=False, category="email"),
        ])
        result = cat.categorize("invoice due", {"intent": "urgent"})
        assert result == "urgent"
