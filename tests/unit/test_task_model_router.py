"""Regression test for task model router — 25-case benchmark.

Any pattern change to task_model_router.py or semantic_task_router.py
must maintain or improve this accuracy.
"""
from __future__ import annotations

import pytest

from weebot.application.services.task_model_router import classify_step, TaskCategory

# 25-case benchmark — expected ground truth per step description
BENCHMARK: list[tuple[str, TaskCategory]] = [
    # CODING (5)
    ("refactor the database module", TaskCategory.CODING),
    ("implement login endpoint with JWT", TaskCategory.CODING),
    ("write a Python function for fibonacci", TaskCategory.CODING),
    ("fix the bug in auth middleware", TaskCategory.CODING),
    ("build a REST API for user profiles", TaskCategory.CODING),
    # FILE_OPS (5)
    ("list all Python files recursively", TaskCategory.FILE_OPS),
    ("create output directory for reports", TaskCategory.FILE_OPS),
    ("read the configuration file", TaskCategory.FILE_OPS),
    ("scan all python files under the project", TaskCategory.FILE_OPS),
    ("rename the old manifest to archive", TaskCategory.FILE_OPS),
    # RESEARCH (5)
    ("search for Clean Architecture patterns", TaskCategory.RESEARCH),
    ("web_search LLM agent frameworks", TaskCategory.RESEARCH),
    ("investigate the root cause of the crash", TaskCategory.RESEARCH),
    ("gather requirements for the new feature", TaskCategory.RESEARCH),
    ("browse the competitor pricing page", TaskCategory.RESEARCH),
    # REVIEW (5)
    ("audit security in auth.py", TaskCategory.REVIEW),
    ("review code for best practices", TaskCategory.REVIEW),
    ("inspect the deployment config for issues", TaskCategory.REVIEW),
    ("evaluate the test coverage report", TaskCategory.REVIEW),
    ("find bugs in the payment module", TaskCategory.REVIEW),
    # EDGE CASES (5)
    ("research and implement feature X", TaskCategory.RESEARCH),
    ("refactor and review the logging module", TaskCategory.CODING),
    ("create and test a new endpoint", TaskCategory.CODING),
    ("audit and fix security vulnerabilities", TaskCategory.REVIEW),
    ("summarize the meeting notes", TaskCategory.SUMMARIZATION),
]


class TestTaskRouterAccuracy:
    """Keyword router must maintain ≥ 70% on the 25-case benchmark."""

    def test_keyword_router_accuracy(self):
        correct = sum(
            1 for desc, expected in BENCHMARK
            if classify_step(desc) == expected
        )
        accuracy = correct / len(BENCHMARK)
        assert accuracy >= 0.70, (
            f"Keyword router accuracy {accuracy:.0%} below 70% threshold. "
            f"{correct}/{len(BENCHMARK)} correct. "
            "Check task_model_router.py patterns."
        )

    def test_individual_categories_above_50_percent(self):
        """Each category must have >50% precision."""
        from collections import defaultdict

        cat_correct: dict[TaskCategory, int] = defaultdict(int)
        cat_total: dict[TaskCategory, int] = defaultdict(int)
        for desc, expected in BENCHMARK:
            cat_total[expected] += 1
            if classify_step(desc) == expected:
                cat_correct[expected] += 1

        failures = []
        for cat, total in cat_total.items():
            precision = cat_correct[cat] / total
            if precision <= 0.5:
                failures.append(f"{cat.value}: {cat_correct[cat]}/{total} ({precision:.0%})")

        assert not failures, (
            f"Categories below 50% precision: {'; '.join(failures)}"
        )
