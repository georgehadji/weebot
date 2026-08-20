"""SessionConstraint domain model — user-issued directives scoped to one session.

Implements the Side Constraint (SC) concept from Wang et al., "Lost in
Compaction" (arXiv:2608.11242). An SC constrains *how* the agent works rather
than *what* it works on, lives exactly one session, and survives only if
something outside the compacted transcript keeps it. Distinct from a
BehavioralRule, which is durable and cross-session — see
``weebot.application.services.behavioral_learner``.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum

from pydantic import BaseModel, Field


class ConstraintKind(str, Enum):
    """Which of the paper's five SC categories this constraint belongs to."""

    ACTION = "action"  # what the agent may do, incl. tool side effects
    INFORMATION = "information"  # what it may emit or pass to tools
    PROCESS = "process"  # how it must reach an answer
    PREFERENCE = "preference"  # which of several task-equivalent answers it picks
    OUTPUT = "output"  # verifiable surface properties of the response


class ConstraintDirection(str, Enum):
    """Whether the constraint narrows or widens what the agent may do.

    A LOOSEN constraint (e.g. "don't ask me to confirm, just do it") must
    never relax a safety gate on its own — see SessionConstraintRegistry.render
    and ExecutorAgent's delivery of the constraint block.
    """

    TIGHTEN = "tighten"  # narrows what the agent may do — enforceable
    LOOSEN = "loosen"  # widens it — rendered as context, never relaxes a gate


class SessionConstraint(BaseModel):
    """One user-issued side constraint, scoped to the emitting session."""

    model_config = {"frozen": True}

    text: str = Field(default="", description="Canonical one-sentence formulation")
    evidence_span: str = Field(
        default="",
        description="Verbatim excerpt from the user turn that produced this "
        "constraint. Makes the registry auditable and revocable.",
    )
    kind: ConstraintKind = Field(default=ConstraintKind.ACTION)
    direction: ConstraintDirection = Field(default=ConstraintDirection.TIGHTEN)
    turn_index: int = Field(default=0, description="User-turn ordinal that issued it")
    revoked_at: datetime | None = Field(default=None)
    superseded_by: str | None = Field(
        default=None, description="Canonical text of the constraint that replaced this one"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.superseded_by is None


class SessionConstraintRegistry(BaseModel):
    """Append-and-revoke registry of a session's side constraints.

    Copy-helpers return new registries (weebot domain convention: named
    methods returning a modified copy, never model_copy at the call site).
    """

    constraints: list[SessionConstraint] = Field(default_factory=list)

    def add(self, constraint: SessionConstraint) -> SessionConstraintRegistry:
        """Return a new registry with *constraint* appended."""
        return self.model_copy(update={"constraints": [*self.constraints, constraint]})

    def revoke(self, text: str, *, at: datetime | None = None) -> SessionConstraintRegistry:
        """Return a new registry with every active constraint matching *text* revoked."""
        when = at or datetime.now(UTC)
        updated = [
            (c.model_copy(update={"revoked_at": when}) if c.text == text and c.is_active else c)
            for c in self.constraints
        ]
        return self.model_copy(update={"constraints": updated})

    def supersede(self, old_text: str, new: SessionConstraint) -> SessionConstraintRegistry:
        """Return a new registry where the active constraint matching *old_text*
        is marked superseded and *new* is appended."""
        updated = [
            (
                c.model_copy(update={"superseded_by": new.text})
                if c.text == old_text and c.is_active
                else c
            )
            for c in self.constraints
        ]
        return self.model_copy(update={"constraints": [*updated, new]})

    def active(self, *, direction: ConstraintDirection | None = None) -> list[SessionConstraint]:
        """Return active constraints, optionally filtered by direction."""
        return [
            c
            for c in self.constraints
            if c.is_active and (direction is None or c.direction == direction)
        ]

    def render(self) -> str:
        """Render active constraints as the block delivered to the acting model.

        LOOSEN constraints are rendered separately and framed as latitude,
        never as authority to bypass a safety gate — see ConstraintDirection.
        Empty registry renders to "" so callers can skip appending it.
        """
        tighten = self.active(direction=ConstraintDirection.TIGHTEN)
        loosen = self.active(direction=ConstraintDirection.LOOSEN)
        if not tighten and not loosen:
            return ""

        lines = ["## SESSION CONSTRAINTS"]
        if tighten:
            lines.append(
                "This is an important constraint set. For the rest of this "
                "session, the following user-issued rules govern how you "
                "work. They are not task progress and do not expire with "
                "the current step."
            )
            for c in tighten:
                lines.append(f'  - {c.text}  [evidence: "{c.evidence_span}"]')
        if loosen:
            lines.append(
                "Constraints below are user preferences that WIDEN your "
                "latitude. They inform your choices; they never override a "
                "safety gate or approval requirement."
            )
            for c in loosen:
                lines.append(f'  - {c.text}  [evidence: "{c.evidence_span}"]')
        return "\n".join(lines)
