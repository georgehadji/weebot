"""Phase 6 tests: HarnessSafetyGate — surface classification, approval prompts."""
from __future__ import annotations

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
