"""HarnessConfig — versioned, model-agnostic harness configuration (Tier 2.1 / 3.3).

Aggregates all harness layers into a single versioned artifact:
- Environment Contract Layer → paths to per-tool YAML contracts
- Procedural Skill Layer → BM25 index path, top_k
- Action Realization Layer → canonicalizer settings
- Trajectory Regulation Layer → detection thresholds

The key property: *model-agnostic*.  A harness evolved on one model backbone
can be reused on any other without retraining (LIFE-HARNESS paper finding).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


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


class HarnessConfig(BaseModel):
    """Top-level harness configuration — one versioned artifact.

    Loaded from a YAML file at startup.  The entire harness is swapped
    by changing the file path — no code changes needed.
    """

    version: str = Field(default="0.0.0")
    description: str = Field(default="")
    evolved_from: Optional[str] = Field(
        default=None,
        description="Model backbone this harness was evolved from, if any",
    )
    canonicalizer: CanonicalizerConfig = Field(default_factory=CanonicalizerConfig)
    skill_retrieval: SkillRetrievalConfig = Field(default_factory=SkillRetrievalConfig)
    trajectory: TrajectoryConfig = Field(default_factory=TrajectoryConfig)

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
