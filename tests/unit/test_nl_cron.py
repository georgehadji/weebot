"""Unit tests for Natural Language Cron (Hermes M7).

Covers:
- parse_schedule for all pattern types
- Edge cases (invalid input, boundary times)
- CLI command registration
"""
import pytest


class TestNLCronParser:
    """Validates parse_schedule()."""

    def test_every_day_at_time(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every day at 9am")
        assert result is not None
        assert result["cron_expression"] == "0 9 * * *"
        assert "Daily" in result["description"]

    def test_every_day_with_minutes(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("daily at 14:30")
        assert result is not None
        assert "30 14" in result["cron_expression"]

    def test_every_weekday(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every weekday at 8am")
        assert result is not None
        assert result["cron_expression"] == "0 8 * * 1-5"

    def test_every_monday(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every Monday at 2pm")
        assert result is not None
        assert result["cron_expression"] == "0 14 * * 1"

    def test_every_monday_and_wednesday(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every Monday and Wednesday at 10am")
        assert result is not None
        # Should contain 1 and 3
        assert "1" in result["cron_expression"]
        assert "3" in result["cron_expression"]

    def test_every_3_hours(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every 3 hours")
        assert result is not None
        assert "*/3" in result["cron_expression"]

    def test_every_30_minutes(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every 30 minutes")
        assert result is not None
        assert "*/30" in result["cron_expression"]

    def test_every_hour(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every hour")
        assert result is not None
        assert "0 *" in result["cron_expression"]

    def test_weekly_on_friday(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("weekly on Friday at 5pm")
        assert result is not None
        assert "0 17 * * 5" in result["cron_expression"]

    def test_monthly_on_1st(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("monthly on the 1st at 9am")
        assert result is not None
        assert "0 9 1 * *" in result["cron_expression"]

    def test_invalid_schedule(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("this is not a schedule at all")
        assert result is None

    def test_pm_conversion(self):
        from weebot.scheduling.nl_cron import parse_schedule

        # 2pm should become hour 14
        result = parse_schedule("every day at 2pm")
        assert result is not None
        assert "14" in result["cron_expression"]

    def test_12am_midnight(self):
        from weebot.scheduling.nl_cron import parse_schedule

        result = parse_schedule("every day at 12am")
        assert result is not None
        assert "0 0" in result["cron_expression"]  # 12am = hour 0



