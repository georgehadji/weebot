"""Phase 3 tests: OptimizationTarget protocol, HarnessOptimizationTarget,
HarnessEdit, HarnessOptFlow."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
import yaml


# ── 1. OptimizationTarget protocol ───────────────────────────────────────

class TestOptimizationTarget:
    def test_protocol_has_abstract_methods(self):
        from weebot.application.ports.optimization_target_port import OptimizationTarget
        assert OptimizationTarget.__abstractmethods__  # Has abstract methods
        assert "load" in OptimizationTarget.__abstractmethods__
        assert "apply_edits" in OptimizationTarget.__abstractmethods__
        assert "save" in OptimizationTarget.__abstractmethods__
        assert "rollback" in OptimizationTarget.__abstractmethods__
        assert "close" in OptimizationTarget.__abstractmethods__


# ── 2. HarnessOptimizationTarget ─────────────────────────────────────────

class TestHarnessOptimizationTarget:
    def test_init(self):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        assert target._harness_path.name == "v0.2.0.yaml"
        assert target._version == 0

    @pytest.mark.asyncio
    async def test_load_v020(self):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        cfg = await target.load()
        assert cfg.version == "0.2.0"
        assert target._current is not None
        assert target.name == "0.2.0"

    @pytest.mark.asyncio
    async def test_content_property(self):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        await target.load()
        content = target.content
        assert "Harness: 0.2.0" in content
        assert "bootstrap" in content
        assert "Runtime Control" in content

    @pytest.mark.asyncio
    async def test_apply_edits(self):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        await target.load()

        candidate = await target.apply_edits([
            {"target": "instructions.bootstrap", "value": "Check deps first"},
            {"target": "instructions.execution", "value": "Be concise"},
        ])
        assert candidate.instructions.bootstrap == "Check deps first"
        assert candidate.instructions.execution == "Be concise"
        assert candidate.version == "0.2.0"  # Not saved yet, version unchanged

    @pytest.mark.asyncio
    async def test_apply_edits_invalid_path(self):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        await target.load()

        candidate = await target.apply_edits([
            {"target": "instructions.nonexistent", "value": "ignored"},
        ])
        # Should log warning but not crash

    @pytest.mark.asyncio
    async def test_save_and_rollback(self, tmp_path):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        # Copy base harness to temp dir
        base = Path("weebot/config/harness/v0.2.0.yaml")
        output = tmp_path / "harness"
        output.mkdir()
        import shutil
        shutil.copy(base, output / "v0.2.0.yaml")

        target = HarnessOptimizationTarget(
            harness_path=output / "v0.2.0.yaml",
            output_dir=output,
        )
        await target.load()

        # Edit and save
        candidate = await target.apply_edits([
            {"target": "instructions.bootstrap", "value": "Custom bootstrap"},
        ])
        saved = await target.save(candidate)
        assert saved.version == "0.2.1"
        assert (output / "v0.2.1.yaml").exists()

        # Rollback
        rolled = await target.rollback()
        assert rolled.version == "0.2.0"
        assert target._version == 0

    @pytest.mark.asyncio
    async def test_bump_patch(self):
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        bump = HarnessOptimizationTarget._bump_patch
        assert bump("0.2.0") == "0.2.1"
        assert bump("1.0.9") == "1.0.10"
        assert bump("0.0.0") == "0.0.1"


# ── 3. HarnessEdit domain model ─────────────────────────────────────────

class TestHarnessEdit:
    def test_creation(self):
        from weebot.domain.models.harness_edit import HarnessEdit
        edit = HarnessEdit(
            target_surface="instructions.bootstrap",
            old_value="old text",
            new_value="new text",
            targeted_mechanism="unproductive_repetition",
        )
        assert edit.target_surface == "instructions.bootstrap"
        assert edit.new_value == "new text"
        assert edit.accepted is False

    def test_to_edit_dict(self):
        from weebot.domain.models.harness_edit import HarnessEdit
        edit = HarnessEdit(
            target_surface="instructions.bootstrap",
            new_value="Do X first",
        )
        d = edit.to_edit_dict()
        assert d["target"] == "instructions.bootstrap"
        assert d["value"] == "Do X first"

    def test_promotion_decision(self):
        from weebot.domain.models.harness_edit import PromotionDecision
        d = PromotionDecision(accepted=True, delta_in=0.1, delta_ho=0.05,
                              reason="Good improvement")
        assert d.accepted
        assert d.delta_in == 0.1


# ── 4. ApplyHarnessEditsCommand + Handler ────────────────────────────────

class TestApplyHarnessEditsCommand:
    def test_creation(self):
        from weebot.application.cqrs.commands.harness_edit_commands import (
            ApplyHarnessEditsCommand,
        )
        cmd = ApplyHarnessEditsCommand(
            edits=[{"target": "instructions.bootstrap", "value": "test"}],
        )
        assert len(cmd.edits) == 1

    def test_validate_empty_edits_raises(self):
        from weebot.application.cqrs.commands.harness_edit_commands import (
            ApplyHarnessEditsCommand,
        )
        cmd = ApplyHarnessEditsCommand(edits=[])
        with pytest.raises(ValueError, match="At least one edit"):
            cmd.validate()


class TestApplyHarnessEditsHandler:
    @pytest.mark.asyncio
    async def test_apply_edits(self):
        from weebot.application.cqrs.commands.harness_edit_commands import (
            ApplyHarnessEditsCommand,
        )
        from weebot.application.cqrs.handlers.harness_edit_handler import (
            ApplyHarnessEditsHandler,
        )
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )

        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        handler = ApplyHarnessEditsHandler(target)

        cmd = ApplyHarnessEditsCommand(
            edits=[{"target": "instructions.bootstrap", "value": "test"}],
        )
        result = await handler.handle(cmd)
        assert result.success
        assert result.data["edits_applied"] == 1
        assert result.data["candidate"]["instructions"]["bootstrap"] == "test"


# ── 5. HarnessOptFlow ────────────────────────────────────────────────────

class TestHarnessOptFlow:
    @pytest.mark.asyncio
    async def test_no_held_in_tasks_finishes_immediately(self):
        from weebot.application.flows.harness_opt_flow import HarnessOptFlow
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )

        llm = AsyncMock()
        llm.chat.return_value = MagicMock(content='{"result": "ok"}')
        repo = AsyncMock()
        repo.get_clusters.return_value = []
        repo.count_trajectories.return_value = 0

        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        flow = HarnessOptFlow(
            llm=llm,
            target=target,
            trajectory_repo=repo,
            held_in_tasks=[],
            held_out_tasks=[],
        )
        events = []
        async for event in flow.run():
            events.append(type(event).__name__)
        assert "DoneEvent" in events

    @pytest.mark.asyncio
    async def test_mine_failure_patterns_empty(self):
        from weebot.application.flows.harness_opt_flow import HarnessOptFlow
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )

        llm = AsyncMock()
        repo = AsyncMock()
        repo.get_clusters.return_value = []
        repo.count_trajectories.return_value = 0

        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        flow = HarnessOptFlow(
            llm=llm, target=target, trajectory_repo=repo,
            held_in_tasks=["test-task"],
        )

        bundle = await flow._mine_failure_patterns(min_support=1)
        assert bundle.total_failures == 0
        assert len(bundle.clusters) == 0

    @pytest.mark.asyncio
    async def test_propose_edits(self):
        from weebot.domain.models.failure_signature import (
            EvidenceBundle, FailureCluster, FailureSignature,
        )
        from weebot.application.flows.harness_opt_flow import HarnessOptFlow
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )

        llm = AsyncMock()
        llm.chat.return_value = MagicMock(
            content=json.dumps({
                "target": "instructions.bootstrap",
                "value": "Check deps first",
                "mechanism": "missing_dependency",
                "expected_effect": "Fewer dependency failures",
                "risks": ["Slightly longer init"],
            }),
        )
        repo = AsyncMock()
        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")
        await target.load()

        flow = HarnessOptFlow(
            llm=llm, target=target, trajectory_repo=repo,
            max_proposals=1,
        )

        sig = FailureSignature(
            session_id="s1", task_id="t1",
            terminal_cause="missing_artifact",
            agent_behavior="dependency_untested",
            mechanism="missing_dependency",
            actionability_score=0.8,
        )
        cluster = FailureCluster.from_signatures([sig])
        bundle = EvidenceBundle(
            clusters=[cluster],
            total_failures=1, total_trajectories=10,
        )

        edits = await flow._propose_edits(
            harness_content=target.content,
            bundle=bundle,
        )
        assert len(edits) >= 1
        assert edits[0].target_surface == "instructions.bootstrap"
        assert edits[0].new_value == "Check deps first"


# ── 6. RegressionGate stub ───────────────────────────────────────────────

class TestRegressionGate:
    @pytest.mark.asyncio
    async def test_stub_auto_accept_flag(self):
        """auto_accept=True skips regression validation."""
        from weebot.application.services.regression_gate import RegressionGate
        gate = RegressionGate(auto_accept=True)
        decision = await gate.validate(
            baseline={"version": "0.2.0"},
            candidate={"version": "0.2.1"},
        )
        assert decision.accepted
        assert "auto_accept" in decision.reason
