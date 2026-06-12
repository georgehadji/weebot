"""Phase 6 tests: HarnessSafetyGate — surface classification, approval prompts."""
from __future__ import annotations

import pytest

from weebot.domain.models.harness_edit import HarnessEdit


# ── Surface Classification ────────────────────────────────────────────────

class TestHarnessSafetyGate:
    def test_autonomous_surface(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edit = HarnessEdit(
            target_surface="instructions.bootstrap",
            new_value="Check deps first",
        )
        result = HarnessSafetyGate.check([edit])
        assert not result.requires_approval
        assert len(result.autonomous_edits) == 1
        assert len(result.gated_edits) == 0

    def test_gated_surface(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edit = HarnessEdit(
            target_surface="runtime_control.max_recent_tool_errors",
            new_value="5",
        )
        result = HarnessSafetyGate.check([edit])
        assert result.requires_approval
        assert len(result.gated_edits) == 1

    def test_all_autonomous_surfaces(self):
        from weebot.application.services.harness_safety_gate import (
            HarnessSafetyGate, AUTONOMOUS_SURFACES,
        )

        edits = [HarnessEdit(target_surface=s, new_value="test")
                 for s in AUTONOMOUS_SURFACES]
        result = HarnessSafetyGate.check(edits)
        assert not result.requires_approval
        assert len(result.autonomous_edits) == len(AUTONOMOUS_SURFACES)

    def test_all_gated_surfaces(self):
        from weebot.application.services.harness_safety_gate import (
            HarnessSafetyGate, GATED_SURFACES,
        )

        edits = [HarnessEdit(target_surface=s, new_value="test")
                 for s in GATED_SURFACES]
        result = HarnessSafetyGate.check(edits)
        assert result.requires_approval
        assert len(result.gated_edits) == len(GATED_SURFACES)

    def test_mixed_edits(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edits = [
            HarnessEdit(target_surface="instructions.bootstrap", new_value="X"),
            HarnessEdit(target_surface="runtime_control.enabled", new_value="true"),
        ]
        result = HarnessSafetyGate.check(edits)
        assert result.requires_approval
        assert len(result.autonomous_edits) == 1
        assert len(result.gated_edits) == 1

    def test_unknown_surface_is_gated(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edit = HarnessEdit(
            target_surface="some.unknown.field",
            new_value="test",
        )
        result = HarnessSafetyGate.check([edit])
        assert result.requires_approval  # Fail-safe: unknown = gated
        assert len(result.gated_edits) == 1

    def test_empty_edits(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        result = HarnessSafetyGate.check([])
        assert not result.requires_approval
        assert len(result.autonomous_edits) == 0
        assert len(result.gated_edits) == 0

    def test_approval_prompt_format(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edits = [
            HarnessEdit(
                target_surface="runtime_control.max_recent_tool_errors",
                new_value="5",
                old_value="3",
                targeted_mechanism="unproductive_repetition",
                expected_effect="Fewer retry loops",
            ),
        ]
        result = HarnessSafetyGate.check(edits)
        assert result.requires_approval
        assert "⚠️" in result.approval_prompt  # Warning icon
        assert "max_recent_tool_errors" in result.approval_prompt
        assert "expected_effect" in result.approval_prompt.lower() or "Fewer" in result.approval_prompt

    def test_autonomous_prompt_empty(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edit = HarnessEdit(target_surface="instructions.bootstrap", new_value="X")
        result = HarnessSafetyGate.check([edit])
        assert result.approval_prompt == ""

    def test_repr(self):
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edit = HarnessEdit(target_surface="runtime_control.enabled", new_value="true")
        result = HarnessSafetyGate.check([edit])
        assert "gated=1" in repr(result)

    def test_structural_surfaces_are_autonomous(self):
        """skill_retrieval.* and trajectory.* should be autonomous."""
        from weebot.application.services.harness_safety_gate import HarnessSafetyGate

        edits = [
            HarnessEdit(target_surface="skill_retrieval.top_k", new_value="5"),
            HarnessEdit(target_surface="trajectory.repetition_threshold", new_value="6"),
        ]
        result = HarnessSafetyGate.check(edits)
        assert not result.requires_approval
        assert len(result.autonomous_edits) == 2


# ── Integration: HarnessOptFlow yields WaitForUserEvent for gated edits ──

class TestHarnessOptFlowSafetyIntegration:
    @pytest.mark.asyncio
    async def test_gated_edit_yields_wait_for_user_event(self):
        """When regression gate accepts a gated-surface edit, flow must
        yield WaitForUserEvent before saving."""
        import json
        from unittest.mock import AsyncMock, MagicMock

        from weebot.application.flows.harness_opt_flow import HarnessOptFlow
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        from weebot.application.services.regression_gate import RegressionGate
        from weebot.domain.models.event import WaitForUserEvent
        from weebot.domain.models.failure_signature import (
            FailureCluster, FailureSignature,
        )
        from weebot.domain.models.harness_edit import PromotionDecision

        # Mock LLM to propose a GATED edit (runtime_control)
        llm = AsyncMock()
        llm.chat.return_value = MagicMock(
            content=json.dumps({
                "target": "runtime_control.max_recent_tool_errors",
                "value": "5",
                "mechanism": "unproductive_repetition",
                "expected_effect": "Fewer retries",
                "risks": [],
            }),
        )

        # Mock trajectory repo with one failure cluster
        repo = AsyncMock()
        sig = FailureSignature(
            session_id="s1", task_id="t1",
            terminal_cause="timeout",
            agent_behavior="retry_loop",
            mechanism="unproductive_repetition",
            actionability_score=0.8,
        )
        repo.get_clusters.return_value = [
            FailureCluster.from_signatures([sig]),
        ]
        repo.count_trajectories.return_value = 10

        # Mock regression gate to always accept
        gate = RegressionGate()  # No task_runner → auto-accept

        target = HarnessOptimizationTarget("weebot/config/harness/v0.2.0.yaml")

        flow = HarnessOptFlow(
            llm=llm,
            target=target,
            trajectory_repo=repo,
            flow_factory=lambda s: AsyncMock(),
            held_in_tasks=["t1"],
            max_proposals=1,
            gate=gate,
        )

        event_types = []
        async for event in flow.run():
            event_types.append(type(event).__name__)

        assert "WaitForUserEvent" in event_types, (
            f"Expected WaitForUserEvent for gated edit but got: {event_types}"
        )
