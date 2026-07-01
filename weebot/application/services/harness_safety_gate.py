"""HarnessSafetyGate — classifies harness edits as autonomous vs. gated.

The Self-Harness loop can autonomously promote edits to instruction
surfaces (bootstrap, execution, verification, failure_recovery).
Edits to safety-critical surfaces (runtime_control, subagents) require
human approval via ``WaitForUserEvent``.

This gate runs AFTER the RegressionGate has accepted the candidate,
so the user is shown edits that already pass regression testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from weebot.domain.models.harness_edit import HarnessEdit


# Surfaces that can be auto-promoted without human review.
# These are the paper's primary edit targets — instruction text changes
# that do not affect the agent's capabilities or safety boundaries.
# Patterns ending with ``.*`` match any surface starting with that prefix
# (e.g. ``"instructions.*"`` matches ``"instructions.bootstrap"``).
AUTONOMOUS_SURFACES: frozenset[str] = frozenset({
    # Instruction surfaces — the paper's primary edit targets
    "instructions.system_prompt_extension",  # Policy note: broad but safe (text only)
    "instructions.bootstrap",
    "instructions.execution",
    "instructions.verification",
    "instructions.failure_recovery",
    # Skill and structural tuning knobs
    "skill_selection.active_skills",
    "skill_retrieval.enabled",
    "skill_retrieval.top_k",
    "skill_retrieval.retriever",
    "trajectory.repetition_threshold",
    "trajectory.stagnation_window",
    "trajectory.budget_hotspot_ratio",
    "trajectory.exhaustion_ratio",
})

# Surfaces that require human approval before promotion.
# Changes here can affect safety (tool errors, loop detection) or
# agent delegation (subagent definitions).
# Patterns ending with ``.*`` match any surface starting with that prefix
# (e.g. ``"middleware.*"`` matches ``"middleware.add:loop_breaker"``).
GATED_SURFACES: frozenset[str] = frozenset({
    "runtime_control.enabled",
    "runtime_control.max_recent_tool_errors",
    "runtime_control.max_total_tool_messages",
    "runtime_control.loop_detection_instruction",
    "subagents.definitions",
    "subagents.*",
    "middleware.*",
    "tool_policies.*",
})


class HarnessSafetyGate:
    """Classifies harness edits and checks whether human approval is needed.

    Usage::

        gate = HarnessSafetyGate()
        result = gate.check(edits)
        if result.requires_approval:
            yield WaitForUserEvent(question=result.approval_prompt)
    """

    @staticmethod
    def check(edits: list[HarnessEdit]) -> "SafetyCheckResult":
        """Classify a list of HarnessEdits.

        Returns:
            ``SafetyCheckResult`` with:
            - ``requires_approval``: True if any edit touches a gated surface
            - ``autonomous_edits``: edits that can be auto-promoted
            - ``gated_edits``: edits that need human approval
            - ``approval_prompt``: human-readable summary (empty if autonomous)
        """
        autonomous: list[HarnessEdit] = []
        gated: list[HarnessEdit] = []

        for edit in edits:
            surface = edit.target_surface
            if _matches_any(surface, AUTONOMOUS_SURFACES):
                autonomous.append(edit)
            elif _matches_any(surface, GATED_SURFACES):
                gated.append(edit)
            else:
                # Unknown surface — treat as gated (fail-safe)
                gated.append(edit)

        requires_approval = len(gated) > 0
        if requires_approval:
            approval_prompt = _build_approval_prompt(autonomous, gated)
        else:
            approval_prompt = ""

        return SafetyCheckResult(
            requires_approval=requires_approval,
            autonomous_edits=autonomous,
            gated_edits=gated,
            approval_prompt=approval_prompt,
        )


# ── Result type ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SafetyCheckResult:
    """Result of a safety check on harness edits."""

    requires_approval: bool = False
    autonomous_edits: list[HarnessEdit] = field(default_factory=list)
    gated_edits: list[HarnessEdit] = field(default_factory=list)
    approval_prompt: str = ""

    def __repr__(self) -> str:
        return (
            f"SafetyCheckResult("
            f"auto={len(self.autonomous_edits)}, "
            f"gated={len(self.gated_edits)}, "
            f"requires_approval={self.requires_approval})"
        )


# ── Helpers ───────────────────────────────────────────────────────────────

def _matches_any(surface: str, patterns: frozenset[str]) -> bool:
    """Check if *surface* matches any pattern in *patterns*.

    Supports two match modes:
    - Exact: ``surface in patterns`` (fast path)
    - Prefix: if a pattern ends with ``.*``, match any surface starting
      with that prefix (e.g. ``"middleware.*"`` matches
      ``"middleware.add:loop_breaker"``)
    """
    if surface in patterns:
        return True
    for pattern in patterns:
        if pattern.endswith(".*") and surface.startswith(pattern[:-2]):
            return True
    return False


def _build_approval_prompt(
    autonomous: list[HarnessEdit],
    gated: list[HarnessEdit],
) -> str:
    """Build a human-readable approval prompt for gated edits."""
    lines = [
        "**Self-Harness proposes harness edits that require your approval.**",
        "",
        "These edits have passed automated regression testing "
        "(Δ_in ≥ 0, Δ_ho ≥ 0) and are ready for promotion.",
        "",
    ]

    if gated:
        lines.append("### ⚠️ Edits requiring approval (safety-critical surfaces)")
        lines.append("")
        for e in gated:
            lines.append(f"- **{e.target_surface}**: `{e.old_value}` → `{e.new_value}`")
            if e.expected_effect:
                lines.append(f"  - Expected effect: {e.expected_effect}")
            if e.targeted_mechanism:
                lines.append(f"  - Addresses: {e.targeted_mechanism}")
        lines.append("")

    if autonomous:
        lines.append("### ✅ Edits that will auto-apply (instruction surfaces)")
        lines.append("")
        for e in autonomous:
            lines.append(f"- **{e.target_surface}**: `{e.old_value}` → `{e.new_value}`")
        lines.append("")

    lines.extend([
        "**Approve:** Auto-promote all proposed edits.",
        "**Reject:** Discard all proposed edits.",
        "**Modify:** (Not supported yet — reject and manually apply the gated edits you want, then re-run.)",
    ])

    return "\n".join(lines)
