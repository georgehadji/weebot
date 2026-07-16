"""HarnessConfig — versioned, model-agnostic harness configuration (Tier 2.1 / 3.3).

Aggregates all harness layers into a single versioned artifact:
- Environment Contract Layer → paths to per-tool YAML contracts
- Procedural Skill Layer → BM25 index path, top_k
- Action Realization Layer → canonicalizer settings
- Trajectory Regulation Layer → detection thresholds
- Behavioural Instruction Layer → model-specific prompts (Self-Harness)
- Runtime Control Layer → safety-relevant policy knobs
- Subagent Layer → parallel agent delegation
- Skill Selection Layer → active skills

The key property: *model-agnostic*.  A harness evolved on one model backbone
can be reused on any other without retraining (LIFE-HARNESS paper finding).
Behavioural instructions (the ``instructions`` field) are the Self-Harness
optimiser's primary edit target.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from weebot.domain.models.harness_instructions import (
    InstructionConfig,
    RuntimeControlConfig,
    SubagentConfig,
    SkillSelectionConfig,
)


class CanonicalizerConfig(BaseModel):
    """Action Canonicalizer settings (Tier 1.1)."""
    strict_mode: bool = Field(default=False)
    coerce_types: bool = Field(default=True)
    contracts_dir: str = Field(default="config/contracts/")


class SkillRetrievalConfig(BaseModel):
    """Procedural Skill Layer settings (Tier 1.2)."""
    enabled: bool = Field(default=True)
    retriever: str = Field(default="bm25")
    top_k: int = Field(default=3, ge=1, le=10)
    index_path: Optional[str] = Field(default=None)


class TrajectoryConfig(BaseModel):
    """Trajectory Regulation Layer thresholds (Tier 1.3)."""
    repetition_threshold: int = Field(default=4, ge=2)
    stagnation_window: int = Field(default=3, ge=2)
    budget_hotspot_ratio: float = Field(default=0.4, ge=0.0, le=1.0)
    exhaustion_ratio: float = Field(default=0.9, ge=0.0, le=1.0)


class MiddlewareRule(BaseModel):
    """A named middleware rule — intercepts tool execution based on a trigger.

    Middleware rules are structural harness components that the Self-Harness
    proposer can suggest to address recurring failure patterns.  Gated by
    ``HarnessSafetyGate`` (human approval required for auto-promotion).

    Example from the Self-Harness paper:
      - ``tool_error_handler`` — redirect when consecutive tool errors exceed threshold
      - ``loop_breaker`` — force summarisation after N identical tool calls
      - ``artifact_ensurer`` — verify required artifacts exist before concluding
    """

    name: str = Field(description="Unique middleware rule name")
    description: str = Field(default="", description="What this rule does")
    trigger: str = Field(description="Trigger condition (e.g. tool_error_after:3, loop_detected)")
    action: str = Field(description="Action when triggered (e.g. redirect_to_recovery, force_replan)")
    enabled: bool = Field(default=True, description="Whether this rule is active")


class HarnessConfig(BaseModel):
    """Top-level harness configuration — one versioned artifact.

    Loaded from a YAML file at startup.  The entire harness is swapped
    by changing the file path — no code changes needed.

    .. versionchanged:: 0.2.0
       Added ``instructions``, ``runtime_control``, ``subagents``,
       and ``skill_selection`` behavioural surfaces for Self-Harness.
    """

    version: str = Field(default="0.0.0")
    description: str = Field(default="")
    evolved_from: Optional[str] = Field(
        default=None,
        description="Prior harness version this was evolved from",
    )

    # ── Structural layers (Tier 1.1–1.3) ──────────────────────────
    canonicalizer: CanonicalizerConfig = Field(default_factory=CanonicalizerConfig)
    skill_retrieval: SkillRetrievalConfig = Field(default_factory=SkillRetrievalConfig)
    trajectory: TrajectoryConfig = Field(default_factory=TrajectoryConfig)

    # ── Behavioural / Self-Harness layers (v0.2.0+) ──────────────
    instructions: InstructionConfig = Field(
        default_factory=InstructionConfig,
        description="Behavioural instruction surfaces — primary Self-Harness edit target",
    )
    runtime_control: RuntimeControlConfig = Field(
        default_factory=RuntimeControlConfig,
        description="Runtime policy knobs — safety-gated, not auto-evolvable",
    )
    subagents: SubagentConfig = Field(
        default_factory=SubagentConfig,
        description="Subagent declarations for parallel delegation",
    )
    middleware: list[MiddlewareRule] = Field(
        default_factory=list,
        description="Middleware rules — tool-execution interceptors. "
                    "Safety-gated (human approval required for auto-promotion).",
    )
    skill_selection: SkillSelectionConfig = Field(
        default_factory=SkillSelectionConfig,
        description="Active skill names to load into executor context",
    )

    @classmethod
    def load(cls, path: Path | str) -> "HarnessConfig":
        """Load harness config from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Harness config not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "HarnessConfig":
        """Return default (un-evolved) harness configuration."""
        return cls(
            version="0.0.0",
            description="Default harness — no evolution applied",
        )
