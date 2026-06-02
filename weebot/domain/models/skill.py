"""Skill domain model — modular capability extensions for agents.

Extended with optimization state for the SkillOpt loop: version history,
bounded edit application, protected slow-update section, and best-skill
export.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .skill_edit import SLOW_UPDATE_END, SLOW_UPDATE_START, SkillEdit


class SkillMetadata(BaseModel):
    """Metadata for a skill."""
    emoji: Optional[str] = Field(default=None)
    env: List[str] = Field(default_factory=list)
    primary_env: Optional[str] = Field(default=None)
    homepage: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None)


class SkillVersion(BaseModel):
    """Immutable snapshot of a skill at a point in time."""
    version: int = 0
    content: str = ""
    validation_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    accepted_at: Optional[datetime] = None
    edit_history: list["SkillEditApplied"] = Field(default_factory=list)


class SkillEditApplied(BaseModel):
    """Record of an edit that was applied (audit trail entry)."""
    op: str = ""  # Literal["append", "insert_after", "replace", "delete"]
    target: Optional[str] = None
    content: str = ""
    support_count: int = 1
    source_type: str = "failure"
    accepted: bool = False
    score_delta: Optional[float] = None
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TransferResult(BaseModel):
    """Result of evaluating a skill on a different model/harness pair.

    Stored in Skill.transfer_scores keyed by "model_id:harness".
    """
    target_model: str = Field(default="", description="e.g., 'openai/gpt-5.4-mini'")
    target_harness: str = Field(default="direct_chat", description="e.g., 'direct_chat' | 'codex'")
    baseline_score: float = Field(default=0.0, ge=0.0, le=1.0)
    transfer_score: float = Field(default=0.0, ge=0.0, le=1.0)
    delta: float = Field(default=0.0, description="transfer_score - baseline_score")
    n_tasks: int = Field(default=0, description="Number of validation tasks run")
    latency_s: float = Field(default=0.0, description="Wall-clock time for evaluation")
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvolutionEntry(BaseModel):
    """LLM-generated narrative summarising one optimization epoch.

    Accumulated in Skill.evolution_log (capped at 20) and fed back into
    the optimizer's reflection prompts so it can avoid repeating failed
    approaches across epochs.
    """
    epoch: int = 0
    narrative: str = ""
    accepted_count: int = 0
    rejected_count: int = 0
    best_score: float = 0.0
    score_delta: float = 0.0
    slow_update_applied: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Skill(BaseModel):
    """A skill extends agent capabilities via prompts and metadata.

    Extended with version history for the SkillOpt optimization loop.
    Each successful edit creates a new SkillVersion, and the best
    validated version is exported as best_skill.md.
    """
    name: str = Field(default="")
    description: str = Field(default="")
    content: str = Field(default="", description="Markdown body of SKILL.md")
    metadata: SkillMetadata = Field(default_factory=SkillMetadata)
    source_path: Optional[str] = Field(default=None)

    # --- SkillOpt optimisation state ---
    versions: list[SkillVersion] = Field(default_factory=list)
    current_version: int = Field(default=0, description="Index into versions[]")
    best_version: int = Field(default=0, description="Index of best validated version")
    slow_update_content: str = Field(
        default="",
        description="Protected section content (wrapped in SLOW_UPDATE markers)",
    )
    rejected_edit_buffer: list[SkillEditApplied] = Field(
        default_factory=list,
        description="Recent rejected edits (negative feedback)",
    )
    meta_skill: str = Field(
        default="",
        description="Optimizer-side coaching (never deployed with target model)",
    )
    transfer_scores: dict[str, TransferResult] = Field(
        default_factory=dict,
        description="Transfer evaluation results keyed by 'model_id:harness'",
    )
    evolution_log: list[EvolutionEntry] = Field(
        default_factory=list,
        description="LLM-generated epoch narratives for longitudinal optimizer memory (capped at 20)",
    )

    # --- computed properties ---

    @property
    def current(self) -> SkillVersion:
        if not self.versions:
            return SkillVersion(content=self.content, version=0)
        return self.versions[self.current_version]

    @property
    def best(self) -> SkillVersion:
        if not self.versions:
            return SkillVersion(content=self.content, version=0)
        return self.versions[self.best_version]

    # --- public API ---

    def to_system_prompt_extension(self) -> str:
        """Convert skill content to a system prompt extension."""
        lines = [f"## Skill: {self.name}"]
        if self.description:
            lines.append(self.description)
        lines.append("")
        lines.append(self.content)
        return "\n".join(lines)

    def check_env(self) -> Dict[str, bool]:
        """Check whether required environment variables are set."""
        import os
        return {name: os.getenv(name) is not None for name in self.metadata.env}

    def is_ready(self) -> bool:
        """Return True if all required env vars are present."""
        if not self.metadata.env:
            return True
        return all(self.check_env().values())

    # --- optimization methods ---

    def apply_edits(
        self,
        edits: list[SkillEdit],
        budget: Optional[int] = None,
    ) -> Skill:
        """Apply bounded edits to produce a new candidate skill version.

        Args:
            edits: Proposed edits, sorted by priority.
            budget: Maximum number of edits to apply.
                None means apply all (no budget).

        Returns:
            A new Skill with an appended candidate version (not yet accepted).
        """
        # Sort by support_count descending
        sorted_edits = sorted(edits, key=lambda e: e.support_count, reverse=True)
        if budget is not None:
            sorted_edits = sorted_edits[:budget]

        new_content = self.content
        for edit in sorted_edits:
            new_content = edit.apply_to(new_content)

        # Build history records
        history = [
            SkillEditApplied(
                op=edit.op,
                target=edit.target,
                content=edit.content,
                support_count=edit.support_count,
                source_type=edit.source_type,
            )
            for edit in sorted_edits
        ]

        new_version_number = len(self.versions)
        candidate = SkillVersion(
            version=new_version_number,
            content=new_content,
            edit_history=history,
        )

        return self.model_copy(
            update={
                "content": new_content,
                "versions": self.versions + [candidate],
                "current_version": new_version_number,
            }
        )

    def accept_current(self, validation_score: float) -> Skill:
        """Accept the current candidate version.

        Updates the current version's validation_score.  If the score
        exceeds the best known score, updates best_version and exports
        the content.  Rejected edits from prior iterations remain in
        the rejected_edit_buffer.
        """
        if not self.versions:
            return self

        version_idx = self.current_version
        version = self.versions[version_idx]
        updated = version.model_copy(
            update={
                "validation_score": validation_score,
                "accepted_at": datetime.now(timezone.utc),
            }
        )
        new_versions = list(self.versions)
        new_versions[version_idx] = updated

        new_best = self.best_version
        best_score = self.best.validation_score
        if best_score is None or validation_score > best_score:
            new_best = version_idx

        return self.model_copy(
            update={
                "versions": new_versions,
                "best_version": new_best,
            }
        )

    def reject_current(
        self,
        score_drop: float,
        failure_analysis: str = "",
    ) -> Skill:
        """Reject the current candidate and record its edits in the buffer."""
        if not self.versions:
            return self

        version = self.versions[self.current_version]
        rejected = [
            SkillEditApplied(
                op=e.op,
                target=e.target,
                content=e.content,
                support_count=e.support_count,
                source_type=e.source_type,
                accepted=False,
                score_delta=-score_drop,
            )
            for e in version.edit_history
        ]

        new_buffer = list(self.rejected_edit_buffer) + rejected
        # Keep buffer bounded
        if len(new_buffer) > 32:
            new_buffer = new_buffer[-32:]

        return self.model_copy(
            update={
                "rejected_edit_buffer": new_buffer,
            }
        )

    def apply_slow_update(self, guidance: str) -> Skill:
        """Rewrite the protected SLOW_UPDATE section with epoch guidance.

        This is only called at epoch boundaries by the slow-update process.
        """
        new_content = self.content
        # Remove existing slow-update section if present
        start = self.content.find(SLOW_UPDATE_START)
        end = self.content.find(SLOW_UPDATE_END)
        if start != -1 and end != -1:
            before = self.content[:start]
            after = self.content[end + len(SLOW_UPDATE_END):]
            new_content = (before.rstrip() + "\n\n" + after.lstrip()).strip()
        else:
            new_content = self.content

        # Prepend (not append) so it's visible to the optimizer
        section = f"{SLOW_UPDATE_START}\n{guidance}\n{SLOW_UPDATE_END}"
        new_content = section + "\n\n" + new_content

        return self.model_copy(
            update={
                "content": new_content,
                "slow_update_content": guidance,
            }
        )

    def export_best(self) -> str:
        """Return the best validated skill content as a deployable markdown string.

        Strips the meta_skill (optimizer-side coaching) and slow-update
        guidance from the deployed artifact.  The exported file is what
        gets used at inference time.
        """
        content = self.best.content
        # Strip slow-update section from deployed artifact
        start = content.find(SLOW_UPDATE_START)
        end = content.find(SLOW_UPDATE_END)
        if start != -1 and end != -1:
            before = content[:start]
            after = content[end + len(SLOW_UPDATE_END):]
            content = (before.rstrip() + "\n\n" + after.lstrip()).strip()

        lines = [
            f"# {self.name}",
            "",
            f"<!-- Auto-generated by SkillOpt. Best skill v{self.best.version}. -->",
            "",
            content,
        ]
        return "\n".join(lines)

    def add_to_rejected_buffer(self, history: list[SkillEditApplied]) -> Skill:
        """Append rejected edit records to the buffer."""
        new_buffer = list(self.rejected_edit_buffer) + list(history)
        if len(new_buffer) > 32:
            new_buffer = new_buffer[-32:]
        return self.model_copy(update={"rejected_edit_buffer": new_buffer})

    def add_evolution_entry(self, entry: EvolutionEntry, max_entries: int = 20) -> Skill:
        """Append an epoch narrative to the evolution log, capped at *max_entries*."""
        updated = list(self.evolution_log) + [entry]
        return self.model_copy(update={"evolution_log": updated[-max_entries:]})


class SkillMatch(BaseModel):
    """A skill retrieved by the Procedural Skill Layer (Tier 1.2).

    Returned by BM25SkillRetriever; injected into the executor's system
    prompt to provide relevant procedural guidance for the current task.
    """
    skill_name: str = Field(default="")
    description: str = Field(default="")
    content_preview: str = Field(default="")
    score: float = Field(default=0.0, ge=0.0, le=1.0)
