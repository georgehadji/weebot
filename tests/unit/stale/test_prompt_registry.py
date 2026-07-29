"""Tests for PromptVariant model and PromptRegistry service."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from weebot.domain.models.prompt_variant import PromptVariant, PromptVariantSource
from weebot.application.services.prompt_registry import PromptRegistry


class TestPromptVariant:
    """Tests for the PromptVariant domain model."""

    def test_defaults(self) -> None:
        v = PromptVariant()
        assert v.variant_id == ""
        assert v.agent_type == ""
        assert v.source == PromptVariantSource.HUMAN
        assert v.is_active is False

    def test_create_with_fields(self) -> None:
        v = PromptVariant(
            variant_id="test-1",
            parent_id="parent-0",
            agent_type="executor",
            prompt_content="You are an executor...",
            source=PromptVariantSource.SELF_IMPROVER,
            score=0.9,
            is_active=True,
        )
        assert v.agent_type == "executor"
        assert v.source == PromptVariantSource.SELF_IMPROVER
        assert v.is_active is True


class TestPromptRegistry:
    """Tests for PromptRegistry with temp directory."""

    @pytest.fixture
    def tmp_dir(self) -> Path:
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def registry(self, tmp_dir: Path) -> PromptRegistry:
        return PromptRegistry(variants_dir=tmp_dir)

    def test_create_persists_to_disk(self, registry: PromptRegistry, tmp_dir: Path) -> None:
        vid = registry.create(
            parent_id=None,
            content="Test prompt content",
            agent_type="executor",
        )
        assert vid
        # Verify file was written
        file_path = tmp_dir / f"{vid}.txt"
        assert file_path.exists()
        assert file_path.read_text() == "Test prompt content"

    def test_set_active_and_get(self, registry: PromptRegistry) -> None:
        vid = registry.create(
            parent_id=None,
            content="Active executor prompt",
            agent_type="executor",
        )
        registry.set_active("executor", vid)

        content = registry.get("executor")
        assert content == "Active executor prompt"

    def test_get_returns_none_for_unknown_type(self, registry: PromptRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_list_variants_filtered(self, registry: PromptRegistry) -> None:
        registry.create(None, "Prompt A", agent_type="executor")
        registry.create(None, "Prompt B", agent_type="planner")
        registry.create(None, "Prompt C", agent_type="executor")

        exec_variants = registry.list_variants(agent_type="executor")
        assert len(exec_variants) == 2

        all_variants = registry.list_variants()
        assert len(all_variants) == 3

    def test_get_variant_by_id(self, registry: PromptRegistry) -> None:
        vid = registry.create(None, "Some prompt", agent_type="planner")
        variant = registry.get_variant(vid)
        assert variant is not None
        assert variant.prompt_content == "Some prompt"

    def test_load_from_disk_across_instances(self, registry: PromptRegistry, tmp_dir: Path) -> None:
        """Variants persisted by one registry are readable by another."""
        vid = registry.create(None, "Persisted prompt", agent_type="executor")
        registry.set_active("executor", vid)

        # New registry pointing to same directory
        registry2 = PromptRegistry(variants_dir=tmp_dir)
        content = registry2.get("executor")
        assert content == "Persisted prompt"
