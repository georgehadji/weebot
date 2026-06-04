"""NaturalLanguageCron — converts human-readable schedules to cron expressions.

Simple keyword-based parser for common scheduling patterns.
For complex cases, an LLM-based parser can be used (future enhancement).

Supported patterns:
- "every day at HH:MM" → "MM HH * * *"
- "every weekday at HH:MM" → "MM HH * * 1-5"
- "every Monday at HH:MM" → "MM HH * * 1"
- "every Monday and Wednesday at HH:MM" → "MM HH * * 1,3"
- "every N hours/minutes" → "*/N * * * *"
- "every hour" → "0 * * * *"
- "daily at HH:MM" → "MM HH * * *"
- "weekly on Monday at HH:MM" → "MM HH * * 1"
- "monthly on the 1st at HH:MM" → "MM HH 1 * *"
"""
from __future__ import annotations

import re
from typing import Optional

# Day name to cron day-of-week number
_DAY_NAMES = {
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2, "tues": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
    "sunday": 7, "sun": 7,
}


def parse_schedule(text: str) -> Optional[dict]:
    """Parse a natural-language schedule into a cron trigger config.

    Args:
        text: Natural language schedule, e.g. "every Friday at 2pm"
            or "every 3 hours".

    Returns:
        A dict with keys ``cron_expression`` and ``description``, or
        ``None`` if the schedule could not be parsed.

    Example:
        >>> parse_schedule("every day at 9am")
        {"cron_expression": "0 9 * * *", "description": "Daily at 09:00"}
    """
    text_lower = text.strip().lower()

    # Extract time (HH:MM or HHam/HHpm)
    hour, minute = _extract_time(text_lower)

    # Pattern 1: "every N hours/minutes" → interval
    interval_match = re.search(r'every (\d+)\s*(hour|minute|min|h|m)s?', text_lower)
    if interval_match:
        amount = int(interval_match.group(1))
        unit = interval_match.group(2)
        if unit in ("hour", "h"):
            return {
                "cron_expression": f"0 */{amount} * * *",
                "description": f"Every {amount} hour(s)",
            }
        else:
            return {
                "cron_expression": f"*/{amount} * * * *",
                "description": f"Every {amount} minute(s)",
            }

    # Pattern 2: "every hour"
    if "every hour" in text_lower or re.search(r'\bevery\s+hour\b', text_lower):
        return {
            "cron_expression": "0 * * * *",
            "description": "Every hour",
        }

    # Pattern 3: "every day at X"
    if "every day" in text_lower or "daily" in text_lower:
        h = hour if hour is not None else 9
        m = minute if minute is not None else 0
        return {
            "cron_expression": f"{m} {h} * * *",
            "description": f"Daily at {h:02d}:{m:02d}",
        }

    # Pattern 4: "every weekday at X"
    if "every weekday" in text_lower or "weekdays" in text_lower:
        h = hour if hour is not None else 9
        m = minute if minute is not None else 0
        return {
            "cron_expression": f"{m} {h} * * 1-5",
            "description": f"Weekdays at {h:02d}:{m:02d}",
        }

    # Pattern 5: "every [day[,] and [day]] at X"
    day_names = "|".join(_DAY_NAMES.keys())
    day_match = re.search(
        rf'\b(({day_names})(\s+and\s+({day_names}))?)\b',
        text_lower,
    )
    if day_match:
        h = hour if hour is not None else 9
        m = minute if minute is not None else 0
        days = []
        for d in re.findall(r'(' + day_names + r')', text_lower):
            days.append(str(_DAY_NAMES.get(d, "")))
        return {
            "cron_expression": f"{m} {h} * * {','.join(set(days))}",
            "description": f"{', '.join(d.capitalize() for d in set(days))} at {h:02d}:{m:02d}",
        }

    # Pattern 6: "weekly on X at Y"
    if "weekly" in text_lower:
        h = hour if hour is not None else 9
        m = minute if minute is not None else 0
        day_name_match = re.search(r'on\s+(' + day_names + r')\b', text_lower)
        if day_name_match:
            day_num = _DAY_NAMES.get(day_name_match.group(1), 1)
            return {
                "cron_expression": f"{m} {h} * * {day_num}",
                "description": f"Weekly on {day_name_match.group(1).capitalize()} at {h:02d}:{m:02d}",
            }
        # Weekly default: Monday
        return {
            "cron_expression": f"{m} {h} * * 1",
            "description": f"Weekly on Monday at {h:02d}:{m:02d}",
        }

    # Pattern 7: "monthly on the Nth at X"
    monthly_match = re.search(r'monthly\s+on\s+the\s+(\d+)(st|nd|rd|th)?', text_lower)
    if monthly_match:
        h = hour if hour is not None else 9
        m = minute if minute is not None else 0
        day_of_month = int(monthly_match.group(1))
        return {
            "cron_expression": f"{m} {h} {day_of_month} * *",
            "description": f"Monthly on the {day_of_month}th at {h:02d}:{m:02d}",
        }

    return None


def _extract_time(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract hour and minute from a text string.

    Supports: "9am", "2pm", "09:00", "14:30", "at 9", etc.
    Returns ``(hour, minute)`` or ``(None, None)``.
    """
    hour = None
    minute = 0

    # Pattern: HH:MM
    time_match = re.search(r'(\d{1,2}):(\d{2})', text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        # Adjust for 12-hour clock
        if "pm" in text and hour < 12:
            hour += 12
        elif "am" in text and hour == 12:
            hour = 0
        return hour, minute

    # Pattern: 9am, 2pm, 9 am, 2 pm (check BEFORE bare numbers below)
    # Use negative lookbehind to avoid matching "at 12am" as "at 12"
    ampm_match = re.search(r'(\d{1,2})\s*(am|pm)\b', text)
    if ampm_match:
        hour = int(ampm_match.group(1))
        if ampm_match.group(2) == "pm" and hour < 12:
            hour += 12
        elif ampm_match.group(2) == "am" and hour == 12:
            hour = 0
        return hour, 0

    # Pattern: "at 9" (24-hour clock, only if no am/pm word nearby)
    if "am" not in text and "pm" not in text:
        at_match = re.search(r'\bat\s+(\d{1,2})\b', text)
        if at_match:
            hour = int(at_match.group(1))
            return hour, 0

    return None, None
