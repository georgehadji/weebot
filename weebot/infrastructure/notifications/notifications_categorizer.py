"""Smart notification categorization (ported from OpenClaw)."""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


BUILTIN_CATEGORIES: Dict[str, List[str]] = {
    "health":   ["blood sugar", "glucose", "cgm", "heart rate", "blood pressure"],
    "urgent":   ["urgent", "critical", "emergency", "asap"],
    "reminder": ["reminder", "don't forget", "remember"],
    "email":    ["email", "inbox", "gmail", "mail from"],
    "calendar": ["calendar", "meeting", "event", "appointment", "standup"],
    "build":    ["build", "ci", "deploy", "pipeline", "test failed"],
    "error":    ["error", "failed", "exception", "traceback"],
}


@dataclass
class UserRule:
    pattern: str
    is_regex: bool
    category: str
    enabled: bool = True


class NotificationCategorizer:
    """
    Three-tier categorization pipeline (first match wins):
    1. Structured metadata (category / intent fields)
    2. User-defined rules (regex or literal)
    3. Built-in keyword matching
    4. Default: "info"
    """

    def __init__(self, user_rules: Optional[List[UserRule]] = None) -> None:
        self._user_rules = [r for r in (user_rules or []) if r.enabled]

        def _compile(r: UserRule):
            if not r.is_regex:
                return None, r
            try:
                return re.compile(r.pattern, re.IGNORECASE), r
            except re.error as exc:
                raise ValueError(f"Invalid regex in UserRule '{r.pattern}': {exc}") from exc

        self._compiled: List[Tuple[Optional[re.Pattern], UserRule]] = [_compile(r) for r in self._user_rules]

    def categorize(self, message: str, metadata: Dict) -> str:
        """Return category string for the given message + metadata."""
        # Tier 1: structured metadata (empty string falls through intentionally)
        if metadata.get("category"):
            return metadata["category"]
        if metadata.get("intent"):
            return metadata["intent"]

        # Tier 2: user rules
        msg_lower = message.lower()
        for compiled_re, rule in self._compiled:
            if compiled_re:
                if compiled_re.search(message):
                    return rule.category
            else:
                if rule.pattern.lower() in msg_lower:
                    return rule.category

        # Tier 3: built-in keywords
        for category, keywords in BUILTIN_CATEGORIES.items():
            if any(kw in msg_lower for kw in keywords):
                return category

        return "info"
