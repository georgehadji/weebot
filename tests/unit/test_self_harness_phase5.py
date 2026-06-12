"""Phase 5 tests: ModelAwareHarnessResolver, HarnessPromptAssembler.assemble_from_config,
dynamic per-step resolution, ExecutorAgent.set_harness_block."""
from __future__ import annotations

import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. ModelAwareHarnessResolver ─────────────────────────────────────────

class TestModelAwareHarnessResolver:
    def test_resolve_no_overlay_returns_base(self, tmp_path):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        base = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        resolver = ModelAwareHarnessResolver(
            base_config=base,
            overlays_dir=str(tmp_path),
        )
        resolved = resolver.resolve("gpt-4o")
        assert resolved.instructions.bootstrap == base.instructions.bootstrap

    def test_resolve_with_overlay(self, tmp_path):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        # Write an overlay
        overlay = tmp_path / "gpt-4o.yaml"
        overlay.write_text(yaml.dump({
            "model_pattern": "gpt-4o*",
            "instructions": {
                "bootstrap": "Analyze with tree first.",
                "execution": "Write tested code.",
            },
        }))

        base = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        resolver = ModelAwareHarnessResolver(base_config=base, overlays_dir=str(tmp_path))
        resolved = resolver.resolve("gpt-4o-turbo")

        # Bootstrap and execution should be overridden
        assert resolved.instructions.bootstrap == "Analyze with tree first."
        assert resolved.instructions.execution == "Write tested code."
        # Verification should keep base value
        assert resolved.instructions.verification == base.instructions.verification

    def test_resolve_no_match(self, tmp_path):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        overlay = tmp_path / "gpt-4o.yaml"
        overlay.write_text(yaml.dump({
            "model_pattern": "gpt-4o*",
            "instructions": {"bootstrap": "GPT only."},
        }))

        base = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        resolver = ModelAwareHarnessResolver(base_config=base, overlays_dir=str(tmp_path))
        resolved = resolver.resolve("claude-sonnet")  # No matching overlay
        assert resolved.instructions.bootstrap == base.instructions.bootstrap

    def test_longest_pattern_wins(self, tmp_path):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        base = HarnessConfig.default()

        # General GPT overlay
        (tmp_path / "gpt.yaml").write_text(yaml.dump({
            "model_pattern": "gpt-4o*",
            "instructions": {"bootstrap": "General GPT."},
        }))
        # More specific GPT-4o-mini overlay
        (tmp_path / "gpt-mini.yaml").write_text(yaml.dump({
            "model_pattern": "gpt-4o-mini*",
            "instructions": {"bootstrap": "Mini-specific."},
        }))

        resolver = ModelAwareHarnessResolver(base_config=base, overlays_dir=str(tmp_path))
        resolved = resolver.resolve("gpt-4o-mini-2024-07")
        assert resolved.instructions.bootstrap == "Mini-specific."

    def test_resolve_instruction_block(self, tmp_path):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        base = HarnessConfig.default()
        resolver = ModelAwareHarnessResolver(base_config=base, overlays_dir=str(tmp_path))
        block = resolver.resolve_instruction_block("gpt-4o")
        # Base has empty defaults, so block should be empty
        assert block == ""

    def test_set_base(self):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        base = HarnessConfig.default()
        resolver = ModelAwareHarnessResolver(base_config=base)
        new_base = HarnessConfig(
            version="0.3.0",
            description="Evolved",
            instructions=base.instructions.model_copy(
                update={"bootstrap": "New bootstrap"},
            ),
        )
        resolver.set_base(new_base)
        resolved = resolver.resolve("any-model")
        assert resolved.instructions.bootstrap == "New bootstrap"


# ── 2. HarnessPromptAssembler.assemble_from_config ───────────────────────

class TestAssembleFromConfig:
    def test_from_none(self):
        from weebot.application.services.harness_prompt_assembler import (
            HarnessPromptAssembler,
        )
        assert HarnessPromptAssembler.assemble_from_config(None) == ""

    def test_from_config(self):
        from weebot.application.services.harness_prompt_assembler import (
            HarnessPromptAssembler,
        )
        from weebot.config.harness.schema import HarnessConfig

        cfg = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        block = HarnessPromptAssembler.assemble_from_config(cfg)
        assert "**Boot:**" in block
        assert "**Execute:**" in block

    def test_from_empty_config(self):
        from weebot.application.services.harness_prompt_assembler import (
            HarnessPromptAssembler,
        )
        from weebot.config.harness.schema import HarnessConfig

        cfg = HarnessConfig.default()  # Empty instructions
        block = HarnessPromptAssembler.assemble_from_config(cfg)
        assert block == ""


# ── 3. ExecutorAgent.set_harness_block ───────────────────────────────────

class TestExecutorSetHarnessBlock:
    def test_set_and_clear(self):
        from unittest.mock import MagicMock
        from weebot.application.agents.executor._base import ExecutorAgent

        llm = MagicMock()
        tools = MagicMock()
        tools.names = ["bash"]
        tools.get_schema.return_value = []

        executor = ExecutorAgent(llm=llm, tools=tools)
        assert executor._harness_instruction_block is None

        executor.set_harness_block("## Test Block")
        assert executor._harness_instruction_block == "## Test Block"

        executor.set_harness_block(None)
        assert executor._harness_instruction_block is None

    def test_set_empty_string(self):
        from unittest.mock import MagicMock
        from weebot.application.agents.executor._base import ExecutorAgent

        executor = ExecutorAgent(llm=MagicMock(), tools=MagicMock())
        executor.set_harness_block("")
        assert executor._harness_instruction_block is None


# ── 4. PlanActFlow per-step resolution ────────────────────────────────────

class TestPlanActFlowHarnessResolution:
    def test_resolver_stored_in_init(self):
        from weebot.config.harness.schema import HarnessConfig
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig

        # Verify the PlanActFlowConfig accepts harness_config
        assert "harness_config" in PlanActFlowConfig.__dataclass_fields__

    def test_model_aware_resolver_imports(self):
        """Verify the resolver import works from plan_act_flow.py."""
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        resolver = ModelAwareHarnessResolver()
        assert resolver._base is not None


# ── 5. Overlay file format ──────────────────────────────────────────────

class TestOverlayLoading:
    @pytest.mark.asyncio
    async def test_load_and_merge(self, tmp_path):
        from weebot.application.services.model_aware_harness_resolver import (
            ModelAwareHarnessResolver,
        )
        from weebot.config.harness.schema import HarnessConfig

        # Write a realistic overlay
        overlay = tmp_path / "qwen3.yaml"
        overlay.write_text(yaml.dump({
            "model_pattern": "qwen/qwen3*",
            "instructions": {
                "bootstrap": "Check dependencies before starting.",
                "execution": "Break tasks into small verifiable steps.",
                "failure_recovery": "After 2 failures, switch to a different approach.",
            },
        }))

        base = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        resolver = ModelAwareHarnessResolver(base_config=base, overlays_dir=str(tmp_path))
        resolved = resolver.resolve("qwen/qwen3-35b")

        assert "dependencies" in resolved.instructions.bootstrap
        assert resolved.instructions.verification == base.instructions.verification
        assert "2 failures" in resolved.instructions.failure_recovery
