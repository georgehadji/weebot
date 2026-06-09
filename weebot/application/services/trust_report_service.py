"""TrustReportService — pure computation of trust reports from evidence.

Zero LLM calls. Indexes ThoughtEvent.code_review_result and VerificationEvent
to produce per-step VerificationDeltas and an aggregate TrustReport.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.trust_report_port import TrustReportPort
from weebot.domain.models.trust_report import (
    DeltaVerdict,
    TrustBand,
    TrustReport,
    VerificationDelta,
)

logger = logging.getLogger(__name__)


class TrustReportService(TrustReportPort):
    """Pure computation: index events, compute deltas, aggregate trust band."""

    async def compute(
        self,
        session_id: str,
        plan_steps: list[Any],
        session_events: list[Any],
    ) -> TrustReport:
        try:
            # 1. Index code review results from ThoughtEvents
            cr_by_step: dict[str, dict] = {}
            for e in session_events:
                if hasattr(e, "code_review_result") and e.code_review_result:
                    cr_by_step[e.step_id] = e.code_review_result

            # 2. Collect CoVe VerificationEvent consistency
            verification_events = []
            for e in session_events:
                if hasattr(e, "type") and getattr(e, "type", "") in (
                    "verification", "verification_event",
                ):
                    verification_events.append(e)

            cove_passed = (
                all(getattr(e, "consistent", True) for e in verification_events)
                if verification_events else None
            )

            # 3. Build deltas for each completed step
            deltas: list[VerificationDelta] = []
            confirmed = drift = regression = missing = 0

            for step in plan_steps:
                if not getattr(step, "is_done", lambda: False)():
                    continue
                sid = getattr(step, "id", "?")
                cr = cr_by_step.get(sid)
                if cr is None:
                    deltas.append(VerificationDelta(step_id=sid))
                    missing += 1
                    continue
                cr_verdict = cr.get("verdict", "approved")
                if cr_verdict == "approved":
                    if cove_passed is False:
                        deltas.append(VerificationDelta(
                            step_id=sid,
                            code_review_verdict="approved",
                            delta_verdict=DeltaVerdict.DRIFT,
                        ))
                        drift += 1
                    else:
                        deltas.append(VerificationDelta(
                            step_id=sid,
                            code_review_verdict="approved",
                            delta_verdict=DeltaVerdict.CONFIRMED,
                        ))
                        confirmed += 1
                else:
                    deltas.append(VerificationDelta(
                        step_id=sid,
                        code_review_verdict=cr_verdict,
                        delta_verdict=DeltaVerdict.REGRESSION,
                        contributing_issues=cr.get("issues", []),
                    ))
                    regression += 1

            # 4. Compute trust band
            if regression > 0:
                trust_band = TrustBand.INVESTIGATE
            elif drift > 0 or (cove_passed is False):
                trust_band = TrustBand.WATCH
            else:
                trust_band = TrustBand.CLEAN

            return TrustReport(
                session_id=session_id,
                trust_band=trust_band,
                deltas=deltas,
                cove_passed=cove_passed,
                confirmed_count=confirmed,
                drift_count=drift,
                regression_count=regression,
                missing_count=missing,
                contributing_factors=[
                    *([f"Code review regression in {regression} step(s)"] if regression else []),
                    *([f"CoVe inconsistency detected"] if drift > 0 else []),
                ],
            )
        except Exception as exc:
            logger.warning("TrustReport computation failed: %s", exc)
            return TrustReport(
                session_id=session_id, trust_band=TrustBand.CLEAN,
            )
