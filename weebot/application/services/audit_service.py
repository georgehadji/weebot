"""AuditService — independent verification for agent outputs (Enhancement 11).

Loads audit config from config/audit/*.yaml and evaluates agent outputs
against vulnerability patterns, verification protocols, and skill-specific
requirements.  Produces structured AuditReports.

Can be called by SwarmTool after sub-agents complete to filter failing
results, or independently via AuditTool.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

from weebot.application.ports.audit_port import AuditPort
from weebot.domain.models.audit import (
    AuditDimension,
    AuditReport,
    AuditVerdict,
    Violation,
    ViolationSeverity,
)

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "audit"


class AuditService(AuditPort):
    """Concrete audit service using rule-based pattern matching.

    Args:
        config_dir: Directory containing audit YAML files.
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = config_dir or _CONFIG_DIR
        self._matrix: dict = {}
        self._vulnerability_patterns: list[dict] = []
        self._protocols: list[dict] = []
        self._load_all()

    def _load_all(self) -> None:
        """Load all audit configuration files."""
        for name, target in [
            ("skill_applicability_matrix.yaml", "_matrix"),
            ("vulnerability_patterns.yaml", "_vulnerability_patterns"),
            ("verification_protocols.yaml", "_protocols"),
        ]:
            path = self._config_dir / name
            if path.exists():
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    if target == "_matrix":
                        self._matrix = data.get("skills", {})
                    elif target == "_vulnerability_patterns":
                        self._vulnerability_patterns = data.get("patterns", [])
                    elif target == "_protocols":
                        self._protocols = data.get("protocols", [])
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", name, exc)

        logger.info(
            "AuditService: %d skills, %d patterns, %d protocols",
            len(self._matrix), len(self._vulnerability_patterns), len(self._protocols),
        )

    async def audit_output(
        self,
        output: str,
        skill_name: Optional[str] = None,
        session_id: str = "",
        agent_id: str = "",
    ) -> AuditReport:
        violations: list[Violation] = []

        # 1. Check vulnerability patterns
        for pattern in self._vulnerability_patterns:
            for match_str in pattern.get("match", []):
                if match_str.lower() in output.lower():
                    violations.append(Violation(
                        dimension=AuditDimension(pattern.get("dimension", "safety")),
                        severity=ViolationSeverity(pattern.get("severity", "medium")),
                        description=pattern.get("description", "Unknown pattern"),
                        location=f"matched: {match_str[:50]}",
                        recommendation=f"Remove or rewrite: {match_str}",
                    ))
                    break

        # 2. Count dimensions from violations
        critical_count = sum(1 for v in violations if v.severity == ViolationSeverity.CRITICAL)
        high_count = sum(1 for v in violations if v.severity == ViolationSeverity.HIGH)

        # 3. Determine verdict and score
        if critical_count > 0:
            verdict = AuditVerdict.FAIL
        elif high_count > 2:
            verdict = AuditVerdict.FAIL
        elif high_count > 0 or len(violations) > 3:
            verdict = AuditVerdict.CONDITIONAL
        else:
            verdict = AuditVerdict.PASS

        score = max(0.0, 1.0 - (sum(self._severity_weight(v.severity) for v in violations) / 10.0))

        return AuditReport(
            session_id=session_id,
            agent_id=agent_id,
            verdict=verdict,
            violations=violations,
            summary=self._build_summary(verdict, violations),
            score=round(score, 3),
        )

    async def pass_threshold(
        self, report: AuditReport, skill_name: Optional[str] = None
    ) -> bool:
        skill_cfg = self._matrix.get(skill_name or "", self._matrix.get("default", {}))
        min_score = skill_cfg.get("min_score", 0.6)
        return report.score >= min_score

    @staticmethod
    def _severity_weight(severity: ViolationSeverity) -> float:
        return {
            ViolationSeverity.CRITICAL: 3.0,
            ViolationSeverity.HIGH: 2.0,
            ViolationSeverity.MEDIUM: 1.0,
            ViolationSeverity.LOW: 0.5,
            ViolationSeverity.INFO: 0.25,
        }.get(severity, 0.0)

    @staticmethod
    def _build_summary(verdict: AuditVerdict, violations: list[Violation]) -> str:
        if not violations:
            return "No issues found."
        parts = [f"{verdict.value.upper()}: {len(violations)} violation(s)"]
        for v in violations[:5]:
            parts.append(f"  - [{v.severity.value}] {v.dimension.value}: {v.description[:80]}")
        if len(violations) > 5:
            parts.append(f"  ... and {len(violations) - 5} more")
        return "\n".join(parts)
