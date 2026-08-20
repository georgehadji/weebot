"""Agent persona models and output contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from weebot.core.agent_profile import AgentProfile


@dataclass
class DeliverableContract:
    """Output contract derived from a deliverable template."""

    required_headings: list[str] = field(default_factory=list)

    @classmethod
    def from_template(cls, template: str) -> DeliverableContract:
        headings: list[str] = []
        for line in template.splitlines():
            line = line.strip()
            if line.startswith("#"):
                text = line.lstrip("#").strip()
                if text:
                    headings.append(text)
        # Fallback: if no headings, treat any non-empty line as a required cue
        if not headings:
            for line in template.splitlines():
                line = line.strip()
                if line:
                    headings.append(line)
        return cls(required_headings=headings)

    def validate(self, output: str) -> list[str]:
        """Return missing headings from output."""
        missing: list[str] = []
        output_lower = output.lower()
        for heading in self.required_headings:
            if heading.lower() not in output_lower:
                missing.append(heading)
        return missing


@dataclass
class AgentPersona:
    """Structured agent persona imported from markdown."""

    persona_id: str
    name: str
    role: str
    division: str = ""
    description: str = ""
    identity: str = ""
    mission: str = ""
    critical_rules: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    workflow: list[str] = field(default_factory=list)
    deliverable_template: str = ""
    domain_expertise: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_path: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_profile(self) -> AgentProfile:
        """Convert persona to AgentProfile for scoring/routing."""
        system_parts = []
        if self.identity:
            system_parts.append(self.identity)
        if self.mission:
            system_parts.append(self.mission)
        if self.critical_rules:
            system_parts.append("Critical rules:\n- " + "\n- ".join(self.critical_rules))
        system_prompt = "\n\n".join(system_parts).strip()

        return AgentProfile(
            role=self.role,
            domain_expertise=self.domain_expertise,
            system_prompt_override=system_prompt,
        )

    def contract(self) -> DeliverableContract | None:
        if not self.deliverable_template:
            return None
        return DeliverableContract.from_template(self.deliverable_template)

    def validate_output(self, output: str) -> list[str]:
        contract = self.contract()
        if not contract:
            return []
        return contract.validate(output)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
