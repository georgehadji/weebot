"""SkillTriggerTester — validates skill descriptions trigger correctly.

Uses an LLM to generate should-trigger and should-NOT-trigger test
queries for a given skill, then evaluates whether the skill's
description causes correct trigger behaviour.

Inspired by revfactory/harness Phase 6-4 trigger verification methodology.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Optional

from weebot.domain.models.skill import Skill

logger = logging.getLogger(__name__)


@dataclass
class TriggerTestResult:
    """Result of a single trigger test query."""
    query: str
    expected_trigger: bool
    actual_triggered: bool
    passed: bool


@dataclass
class TriggerTestReport:
    """Full report for a skill trigger test."""
    skill_name: str
    results: list[TriggerTestResult] = field(default_factory=list)
    should_triggers: list[TriggerTestResult] = field(default_factory=list)
    should_not_triggers: list[TriggerTestResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.pass_count / self.total

    @property
    def should_trigger_pass_rate(self) -> float:
        if not self.should_triggers:
            return 0.0
        return sum(1 for r in self.should_triggers if r.passed) / len(self.should_triggers)

    @property
    def should_not_trigger_pass_rate(self) -> float:
        if not self.should_not_triggers:
            return 0.0
        return sum(1 for r in self.should_not_triggers if r.passed) / len(self.should_not_triggers)


class SkillTriggerTester:
    """Generates and evaluates trigger test queries for a skill.

    Args:
        llm: Optional LLM port for query generation. If None, uses
            hardcoded templates (deterministic, no API call).
    """

    # Hardcoded templates used when no LLM is available (deterministic mode)
    SHOULD_TRIGGER_TEMPLATES = [
        "I need you to {action}",
        "Can you {action} for me?",
        "Please {action}",
        "Run {action} on this data",
        "Let's {action} together",
    ]

    SHOULD_NOT_TRIGGER_TEMPLATES = [
        "What is the weather like today?",
        "Tell me a joke",
        "Write a poem about autumn",
        "Explain quantum computing in simple terms",
        "What is 2 + 2?",
    ]

    def __init__(self, llm: Optional[object] = None) -> None:
        self._llm = llm

    async def test_skill(
        self,
        skill: Skill,
        num_should: int = 5,
        num_should_not: int = 5,
    ) -> TriggerTestReport:
        """Run trigger validation against a skill.

        Generates *num_should* queries that should trigger the skill
        and *num_should_not* queries that should NOT trigger it,
        then evaluates each against the skill's description.

        Args:
            skill: The skill to test.
            num_should: Number of should-trigger queries to generate.
            num_should_not: Number of should-NOT-trigger queries.

        Returns:
            ``TriggerTestReport`` with per-query results.
        """
        report = TriggerTestReport(skill_name=skill.name)

        # Generate test queries
        should_queries = self._generate_should_trigger(skill, num_should)
        should_not_queries = self._generate_should_not_trigger(skill, num_should_not)

        # Evaluate each query
        for query in should_queries:
            triggered = self._evaluate_trigger(skill, query)
            result = TriggerTestResult(
                query=query,
                expected_trigger=True,
                actual_triggered=triggered,
                passed=triggered is True,
            )
            report.results.append(result)
            report.should_triggers.append(result)

        for query in should_not_queries:
            triggered = self._evaluate_trigger(skill, query)
            result = TriggerTestResult(
                query=query,
                expected_trigger=False,
                actual_triggered=triggered,
                passed=triggered is False,
            )
            report.results.append(result)
            report.should_not_triggers.append(result)

        return report

    def _generate_should_trigger(self, skill: Skill, count: int) -> list[str]:
        """Generate queries that SHOULD trigger the skill."""
        if self._llm:
            return self._generate_via_llm(skill, count, should_trigger=True)

        # Deterministic fallback: build queries from description keywords
        keywords = self._extract_keywords(skill.description)
        if not keywords:
            # Fall back to skill name
            keywords = [skill.name.replace("_", " ").replace("-", " ")]

        queries = []
        for keyword in keywords[:count]:
            template = random.choice(self.SHOULD_TRIGGER_TEMPLATES)
            queries.append(template.format(action=keyword))

        # Pad with generic queries if not enough keywords
        while len(queries) < count:
            queries.append(f"Perform {skill.name} task")
            if len(queries) >= count:
                break
            queries.append(f"Help me with {skill.name}")

        return queries[:count]

    def _generate_should_not_trigger(self, skill: Skill, count: int) -> list[str]:
        """Generate queries that should NOT trigger the skill."""
        if self._llm:
            return self._generate_via_llm(skill, count, should_trigger=False)

        return self.SHOULD_NOT_TRIGGER_TEMPLATES[:count]

    def _generate_via_llm(self, skill: Skill, count: int, should_trigger: bool) -> list[str]:
        """Generate queries using an LLM (future: implement with LLMPort)."""
        # Placeholder — returns deterministic fallback
        if should_trigger:
            keywords = self._extract_keywords(skill.description)
            return [f"Perform {k}" for k in keywords[:count]] or [f"Use {skill.name}"]
        return self.SHOULD_NOT_TRIGGER_TEMPLATES[:count]

    @staticmethod
    def _extract_keywords(description: str) -> list[str]:
        """Extract action-oriented keywords from a skill description."""
        import re
        # Find nouns and verbs that look like actions
        words = re.findall(r'\b[a-zA-Z]{3,}\b', description)
        # Filter out common stop words
        stop_words = {"the", "and", "for", "are", "but", "not", "you", "all",
                      "can", "has", "was", "had", "its", "may", "use", "when",
                      "this", "that", "with", "from", "your", "which", "will"}
        return [w for w in words if w.lower() not in stop_words][:10]

    @staticmethod
    def _evaluate_trigger(skill: Skill, query: str) -> bool:
        """Determine if *query* would trigger *skill*.

        Simple keyword-based evaluation:
        - If query contains a keyword from the skill's description or name → trigger
        - Otherwise → no trigger

        This is a deterministic heuristic. An LLM-based evaluator would
        be more accurate but adds latency and cost.
        """
        q = query.lower()
        # Check skill name (with separators normalized)
        name_parts = skill.name.lower().replace("_", " ").replace("-", " ").split()
        if any(part in q for part in name_parts if len(part) > 2):
            return True

        # Check description keywords
        keywords = SkillTriggerTester._extract_keywords(skill.description)
        if any(kw.lower() in q for kw in keywords):
            return True

        return False
