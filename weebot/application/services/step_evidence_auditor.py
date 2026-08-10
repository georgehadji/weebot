"""StepEvidenceAuditor — mechanical, environment-grounded step evidence check.

Extracted from VerifyingState._gate_artifact_verification (LongHorizon-Harness
enhancement E1 — see tasks/specs/longhorizon_harness_implementation_plan.md).
Was terminal (ran once, after every step was already COMPLETED, checking
existence rather than acceptance); now callable per-step, before completion.

Three gates, zero model calls:
  A. Files written by file/edit tools must still exist on disk.
  B. Test commands with failure markers in their output fail the step.
  C. image_gen outputs must not be undersized SVG placeholders.

All filesystem access goes through FileStoragePort (C1 in the plan — the
Application layer must not touch Path/open() directly).
"""
from __future__ import annotations

import logging
from typing import Sequence

from weebot.application.ports.file_storage_port import FileStoragePort
from weebot.application.ports.step_audit_port import StepAuditPort
from weebot.domain.models.audit import AuditDimension, AuditReport, AuditVerdict, Violation, ViolationSeverity
from weebot.domain.models.event import ToolEvent
from weebot.domain.models.plan import Step

_log = logging.getLogger(__name__)

_WRITE_TOOLS = frozenset({"file_editor", "edit_file", "write_file", "create_file"})
_SHELL_TOOLS = frozenset({"bash", "shell_exec", "powershell"})
_TEST_KEYWORDS = ("pytest", "npm test", "jest", "cargo test", "go test", "python -m pytest")
_TEST_FAILURE_MARKERS = ("failed", "error", "assertion error", "test failed")
_IMAGE_TOOLS = frozenset({"image_gen", "image_generator", "generate_image"})
_IMAGE_QUALITY_MIN_BYTES = 10_000  # real photos are typically 50 KB+


class StepEvidenceAuditor(StepAuditPort):
    """Checks a step's ToolEvents against the real environment.

    Args:
        file_storage: Port for all filesystem access (never Path/open() directly).
    """

    def __init__(self, file_storage: FileStoragePort) -> None:
        self._files = file_storage

    async def audit_step(
        self,
        step: Step | None,
        events: Sequence[ToolEvent],
        session_id: str = "",
    ) -> AuditReport:
        violations: list[Violation] = []
        violations += await self._gate_written_files(events)
        violations += self._gate_test_output(events)
        violations += await self._gate_image_quality(events)

        if not violations:
            return AuditReport(
                session_id=session_id,
                verdict=AuditVerdict.PASS,
                summary="Evidence supports completion.",
                score=1.0,
            )

        critical = sum(1 for v in violations if v.severity == ViolationSeverity.CRITICAL)
        verdict = AuditVerdict.FAIL if critical else AuditVerdict.CONDITIONAL
        return AuditReport(
            session_id=session_id,
            verdict=verdict,
            violations=violations,
            summary="; ".join(v.description for v in violations),
            score=0.0 if critical else 0.5,
        )

    async def _gate_written_files(self, events: Sequence[ToolEvent]) -> list[Violation]:
        """Gate A: files written by write tools must still exist on disk."""
        written_paths: list[str] = []
        for event in events:
            if event.tool_name not in _WRITE_TOOLS:
                continue
            args = event.function_args or {}
            path = args.get("path") or args.get("file_path") or args.get("target_file", "")
            if path:
                written_paths.append(str(path))

        violations: list[Violation] = []
        for p in written_paths:
            try:
                exists = await self._files.exists(p)
            except (OSError, ValueError):
                _log.debug("Invalid path in step audit — skipping without blocking: %s", p, exc_info=True)
                continue
            if not exists:
                violations.append(Violation(
                    dimension=AuditDimension.COMPLETENESS,
                    severity=ViolationSeverity.HIGH,
                    description=f"written file missing on disk: {p}",
                    location=p,
                    recommendation="Re-write the file, or correct the claimed path.",
                ))
        return violations

    def _gate_test_output(self, events: Sequence[ToolEvent]) -> list[Violation]:
        """Gate B: test commands with failure markers in their output."""
        for event in events:
            if event.tool_name not in _SHELL_TOOLS:
                continue
            cmd = str((event.function_args or {}).get("command", "")).lower()
            if not any(kw in cmd for kw in _TEST_KEYWORDS):
                continue
            result = (event.result or "").lower()
            # NOTE: a prior version of this gate (verifying.py) skipped
            # whenever "passed" appeared anywhere in the output — but real
            # pytest summaries read "N passed, M failed" together, which
            # made the gate inert for the mixed-result case it exists to
            # catch. Only "0 failed" (or no failure marker at all) should
            # skip; any nonzero failure count must trip the gate.
            if "0 failed" in result:
                continue
            if any(marker in result for marker in _TEST_FAILURE_MARKERS):
                return [Violation(
                    dimension=AuditDimension.ACCURACY,
                    severity=ViolationSeverity.CRITICAL,
                    description="test run reported failure",
                    location=cmd[:80],
                    recommendation="Fix the failing test(s) before marking this step complete.",
                )]
        return []

    async def _gate_image_quality(self, events: Sequence[ToolEvent]) -> list[Violation]:
        """Gate C: image_gen outputs must not be undersized SVG placeholders."""
        violations: list[Violation] = []
        for event in events:
            if event.tool_name not in _IMAGE_TOOLS:
                continue

            result_text = (event.result or "").lower()
            if "svg fallback" in result_text or "placeholder" in result_text:
                violations.append(Violation(
                    dimension=AuditDimension.COMPLETENESS,
                    severity=ViolationSeverity.MEDIUM,
                    description="image_gen returned an SVG fallback, not a real photo",
                    recommendation="Use search_images for stock photos.",
                ))
                continue

            out_path = (event.function_args or {}).get("output_path", "")
            if not out_path:
                continue

            fsize = await self._files.size(out_path)
            if fsize is None or not (0 < fsize < _IMAGE_QUALITY_MIN_BYTES):
                continue

            try:
                head = (await self._files.read_text(out_path))[:200]
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if "<?xml" in head or "<svg" in head[:100]:
                violations.append(Violation(
                    dimension=AuditDimension.COMPLETENESS,
                    severity=ViolationSeverity.MEDIUM,
                    description=f"{out_path} is {fsize} bytes with SVG markup — likely a placeholder disguise",
                    location=out_path,
                    recommendation="Regenerate with search_images or a real image_gen call.",
                ))
        return violations
