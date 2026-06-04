"""AuditTool — independent audit of agent outputs (Enhancement 11).

Allows the agent to verify its own outputs for safety, accuracy, and
compliance.  Runs the AuditService on a given output text and returns
the violation report with pass/fail verdict and score.
"""
from __future__ import annotations

from typing import Any, Optional

from weebot.application.ports.audit_port import AuditPort
from weebot.tools.base import BaseTool, ToolResult


class AuditTool(BaseTool):
    """Audit agent outputs for safety, accuracy, and compliance."""

    name: str = "audit_session"
    description: str = (
        "Audit an agent output for safety violations, accuracy, and "
        "instruction compliance.  Returns a structured report with "
        "violations, pass/fail verdict, and a 0-1 score. "
        "Use before presenting results to verify quality."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "output": {
                "type": "string",
                "description": "The output text to audit.",
            },
            "skill_name": {
                "type": "string",
                "description": "Optional skill name for threshold lookup.",
            },
        },
        "required": ["output"],
    }

    _service: Optional[AuditPort] = None

    def __init__(self, service: Optional[AuditPort] = None, **data: Any) -> None:
        super().__init__(**data)
        if service is None:
            from weebot.application.di import Container
            container = Container()
            container.configure_defaults()
            service = container.get(AuditPort)
        object.__setattr__(self, "_service", service)

    async def execute(self, output: str, skill_name: str = "", **_: Any) -> ToolResult:

        report = await self._service.audit_output(
            output=output,
            skill_name=skill_name or None,
        )

        passed = await self._service.pass_threshold(report, skill_name or None)

        lines = [
            f"## Audit Result: {report.verdict.value.upper()}",
            f"**Score:** {report.score:.2f}  **Violations:** {len(report.violations)}",
            "",
        ]
        if report.violations:
            lines.append("### Violations")
            for v in report.violations[:10]:
                lines.append(f"- [{v.severity.value}] {v.description}")
            if len(report.violations) > 10:
                lines.append(f"  (... {len(report.violations) - 10} more)")
        else:
            lines.append("No violations found.")

        return ToolResult.success_result(
            output="\n".join(lines),
            data={
                "verdict": report.verdict.value,
                "score": report.score,
                "violations": [v.model_dump() for v in report.violations],
                "passed": passed,
            },
        )
