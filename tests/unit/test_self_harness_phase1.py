"""Unit tests for Self-Harness Phase 1: behavioural instruction surfaces.

Tests cover:
1. Domain models (InstructionConfig, RuntimeControlConfig, etc.)
2. HarnessPromptAssembler — field-keyed assembly, empty handling
3. HarnessConfig schema — v0.1.0 backward compat, v0.2.0 load, round-trip
4. DI wiring — harness_config field exists in PlanActFlowConfig
5. Executor integration — harness block injection
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── 1. Domain Models ──────────────────────────────────────────────────────

class TestInstructionConfig:
    """InstructionConfig defaults are empty strings for backward-compat."""

    def test_defaults_are_empty(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        ic = InstructionConfig()
        assert ic.system_prompt_extension == ""
        assert ic.bootstrap == ""
        assert ic.execution == ""
        assert ic.verification == ""
        assert ic.failure_recovery == ""

    def test_explicit_values_preserved(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        ic = InstructionConfig(
            bootstrap="Do X first",
            execution="Be concise",
        )
        assert ic.bootstrap == "Do X first"
        assert ic.execution == "Be concise"
        assert ic.verification == ""  # Still empty

    def test_serialization_roundtrip(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        ic = InstructionConfig(
            bootstrap="Check deps first",
            failure_recovery="Stop after 3 retries",
        )
        data = ic.model_dump()
        restored = InstructionConfig.model_validate(data)
        assert restored.bootstrap == ic.bootstrap
        assert restored.failure_recovery == ic.failure_recovery


class TestRuntimeControlConfig:
    def test_defaults_disabled(self):
        from weebot.domain.models.harness_instructions import RuntimeControlConfig
        rc = RuntimeControlConfig()
        assert rc.enabled is False
        assert rc.max_recent_tool_errors is None
        assert rc.max_total_tool_messages is None
        assert rc.loop_detection_instruction is None


class TestSubagentConfig:
    def test_defaults_empty(self):
        from weebot.domain.models.harness_instructions import SubagentConfig
        sc = SubagentConfig()
        assert sc.definitions == []
        assert sc.max_parallel == 0


class TestSkillSelectionConfig:
    def test_defaults_empty(self):
        from weebot.domain.models.harness_instructions import SkillSelectionConfig
        ss = SkillSelectionConfig()
        assert ss.active_skills == []


# ── 2. HarnessPromptAssembler ────────────────────────────────────────────

class TestHarnessPromptAssembler:
    """Tests for the field-keyed assembly logic."""

    def test_none_instructions_returns_empty(self):
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        result = HarnessPromptAssembler.assemble(instructions=None)
        assert result == ""

    def test_all_empty_instructions_returns_empty(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        ic = InstructionConfig()  # all empty defaults
        result = HarnessPromptAssembler.assemble(instructions=ic)
        assert result == ""

    def test_single_field_renders_correctly(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        ic = InstructionConfig(bootstrap="Inspect workspace first")
        result = HarnessPromptAssembler.assemble(instructions=ic)
        assert "## Harness Instructions" in result
        assert "**Boot:** Inspect workspace first" in result
        # Other sections should be absent
        assert "**Execute:**" not in result
        assert "**Verify:**" not in result
        assert "**Recover:**" not in result

    def test_multiple_fields_no_positional_misalignment(self):
        """Key fix: skipping fields must not shift subsequent sections."""
        from weebot.domain.models.harness_instructions import InstructionConfig
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        # Skip bootstrap, set execution and failure_recovery
        ic = InstructionConfig(
            execution="Be direct",
            failure_recovery="Adapt on error",
        )
        result = HarnessPromptAssembler.assemble(instructions=ic)
        assert "**Boot:**" not in result  # bootstrap is empty → not rendered
        assert "**Execute:** Be direct" in result
        assert "**Recover:** Adapt on error" in result

    def test_all_fields_populated(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        ic = InstructionConfig(
            bootstrap="A",
            execution="B",
            verification="C",
            failure_recovery="D",
            system_prompt_extension="Extra stuff",
        )
        result = HarnessPromptAssembler.assemble(instructions=ic)
        assert "**Boot:** A" in result
        assert "**Execute:** B" in result
        assert "**Verify:** C" in result
        assert "**Recover:** D" in result
        assert "Extra stuff" in result

    def test_assemble_compact_all_empty(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        ic = InstructionConfig()
        result = HarnessPromptAssembler.assemble_compact(instructions=ic)
        assert result == "harness: none"

    def test_assemble_compact_some_fields(self):
        from weebot.domain.models.harness_instructions import InstructionConfig
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        ic = InstructionConfig(bootstrap="X", verification="Y")
        result = HarnessPromptAssembler.assemble_compact(instructions=ic)
        assert "bootstrap" in result
        assert "verification" in result
        assert "execution" not in result

    def test_assemble_compact_none(self):
        from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
        result = HarnessPromptAssembler.assemble_compact(instructions=None)
        assert result == "harness: none"


# ── 3. HarnessConfig Schema ─────────────────────────────────────────────

class TestHarnessConfig:
    """Tests for HarnessConfig load, default, and backward-compat."""

    def test_load_v010_backward_compat(self):
        """Loading v0.1.0 should NOT inject behavioral instructions."""
        from weebot.config.harness.schema import HarnessConfig
        cfg = HarnessConfig.load(Path("weebot/config/harness/v0.1.0.yaml"))
        assert cfg.version == "0.1.0"
        # InstructionConfig defaults → all empty
        assert cfg.instructions.bootstrap == ""
        assert cfg.instructions.execution == ""
        assert cfg.runtime_control.enabled is False
        assert cfg.subagents.definitions == []

    def test_load_v020_has_instructions(self):
        """Loading v0.2.0 should populate instruction fields from YAML."""
        from weebot.config.harness.schema import HarnessConfig
        cfg = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        assert cfg.version == "0.2.0"
        assert cfg.evolved_from == "0.1.0"
        assert cfg.instructions.bootstrap != ""
        assert cfg.instructions.execution != ""
        assert cfg.instructions.verification != ""
        assert cfg.instructions.failure_recovery != ""

    def test_default_factory(self):
        from weebot.config.harness.schema import HarnessConfig
        cfg = HarnessConfig.default()
        assert cfg.version == "0.0.0"
        assert cfg.instructions.bootstrap == ""  # Empty defaults

    def test_yaml_roundtrip(self):
        import yaml
        from weebot.config.harness.schema import HarnessConfig
        cfg = HarnessConfig.load(Path("weebot/config/harness/v0.2.0.yaml"))
        dumped = yaml.safe_dump(cfg.model_dump(), default_flow_style=False)
        restored = HarnessConfig.model_validate(yaml.safe_load(dumped))
        assert restored.version == cfg.version
        assert restored.instructions.bootstrap == cfg.instructions.bootstrap
        assert restored.runtime_control.enabled == cfg.runtime_control.enabled


# ── 4. DI Wiring ────────────────────────────────────────────────────────

class TestDIWiring:
    """Verify harness_config field exists and DI factories reference it."""

    def test_plan_act_flow_config_has_field(self):
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        assert "harness_config" in PlanActFlowConfig.__dataclass_fields__

    def test_agent_tools_mixin_passes_harness(self):
        """The DI agent tools factory should pass harness_config."""
        import inspect
        from weebot.application.di._agent_tools import AgentToolsMixin
        src = inspect.getsource(AgentToolsMixin._build_plan_act_flow_for_session)
        assert "harness_config" in src

    def test_skillopt_mixin_passes_harness(self):
        """The SkillOpt target flow factory should pass harness_config."""
        import inspect
        from weebot.application.di._skillopt import SkillOptMixin
        src = inspect.getsource(SkillOptMixin._create_target_flow_factory)
        assert "harness_config" in src


# ── 5. Executor Integration ──────────────────────────────────────────────

class TestExecutorHarnessInjection:
    """Verify the executor accepts and injects the harness block."""

    def test_executor_accepts_harness_kwarg(self):
        import inspect
        from weebot.application.agents.executor import ExecutorAgent
        sig = inspect.signature(ExecutorAgent.__init__)
        assert "harness_instruction_block" in sig.parameters

    def test_executor_stores_block(self):
        """Executor stores the harness_instruction_block attribute."""
        from unittest.mock import MagicMock
        from weebot.application.agents.executor._base import ExecutorAgent

        llm = MagicMock()
        tools = MagicMock()
        tools.names = ["bash", "file_editor"]
        tools.get_schema.return_value = []

        executor = ExecutorAgent(
            llm=llm,
            tools=tools,
            harness_instruction_block="## Test Harness Block",
        )
        assert executor._harness_instruction_block == "## Test Harness Block"

    def test_executor_none_block_is_none(self):
        """When not passed, harness_instruction_block is None."""
        from unittest.mock import MagicMock
        from weebot.application.agents.executor._base import ExecutorAgent

        llm = MagicMock()
        tools = MagicMock()
        tools.names = ["bash"]
        tools.get_schema.return_value = []

        executor = ExecutorAgent(llm=llm, tools=tools)
        assert executor._harness_instruction_block is None
