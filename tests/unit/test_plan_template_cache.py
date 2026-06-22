"""Tests for plan template cache — signature, matching, and seeding."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.services.plan_template_cache import (
    build_meta_notes,
    compute_task_hash,
    find_matching_templates,
    jaccard_similarity,
    tokenize,
)
from weebot.domain.models.plan_template import PlanTemplate


class TestTaskHash:
    def test_stable_hash(self):
        """Same task produces same hash."""
        h1 = compute_task_hash("write a python script to read a file")
        h2 = compute_task_hash("write a python script to read a file")
        assert h1 == h2

    def test_stopwords_stripped(self):
        """Stopwords don't affect the hash."""
        h1 = compute_task_hash("please help me write a python script")
        h2 = compute_task_hash("write python script")
        assert h1 == h2

    def test_different_tasks_different_hash(self):
        """Different tasks produce different hashes."""
        h1 = compute_task_hash("write a python script")
        h2 = compute_task_hash("deploy to kubernetes")
        assert h1 != h2


class TestTokenize:
    def test_basic(self):
        tokens = tokenize("write a python script to read files")
        assert "write" in tokens
        assert "python" in tokens
        assert "script" in tokens
        assert "a" not in tokens  # stopword
        assert "to" not in tokens  # stopword

    def test_empty(self):
        assert tokenize("") == set()
        assert tokenize("a an the") == set()


class TestJaccardSimilarity:
    def test_identical(self):
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial(self):
        sim = jaccard_similarity({"a", "b"}, {"a", "c"})
        assert sim == 1/3

    def test_empty(self):
        assert jaccard_similarity(set(), {"a"}) == 0.0


class TestFindMatchingTemplates:
    @pytest.fixture
    def sample_templates(self):
        return [
            PlanTemplate(
                template_id="t1", task_hash="a", task_description="write python script to parse csv",
                plan_json='{"steps": [{"description": "read csv"}]}', success_score=0.9,
            ),
            PlanTemplate(
                template_id="t2", task_hash="b", task_description="deploy docker container to kubernetes",
                plan_json='{"steps": [{"description": "build image"}]}', success_score=0.8,
            ),
        ]

    async def test_exact_hash_match(self, sample_templates):
        repo = MagicMock()
        repo.find_plan_templates_by_hash = AsyncMock(return_value=[sample_templates[0]])
        result = await find_matching_templates(repo, "write python script to parse csv")
        assert len(result) == 1
        assert result[0].template_id == "t1"

    async def test_jaccard_fallback(self, sample_templates):
        repo = MagicMock()
        repo.find_plan_templates_by_hash = AsyncMock(return_value=[])
        repo.list_all_plan_templates = AsyncMock(return_value=sample_templates)
        result = await find_matching_templates(repo, "parse csv with python", threshold=0.3)
        assert len(result) >= 1

    async def test_no_match(self, sample_templates):
        repo = MagicMock()
        repo.find_plan_templates_by_hash = AsyncMock(return_value=[])
        repo.list_all_plan_templates = AsyncMock(return_value=sample_templates)
        result = await find_matching_templates(repo, "build a mobile app with react native", threshold=0.8)
        assert len(result) == 0


class TestBuildMetaNotes:
    def test_empty_templates(self):
        assert build_meta_notes([]) == ""

    def test_with_templates(self):
        tpl = PlanTemplate(
            template_id="t1", task_hash="a", task_description="write python script",
            plan_json='{"steps": [{"description": "open file"}, {"description": "read data"}]}',
        )
        result = build_meta_notes([tpl])
        assert "Plan templates" in result
        assert "open file" in result
