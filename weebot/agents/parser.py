"""Parse agency-style agent markdown into structured personas."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from weebot.agents.models import AgentPersona

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:-|\*|\d+\.)\s+(.*)$")


def _normalize_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


_SECTION_MAP = {
    "identity": "identity",
    "identity & personality": "identity",
    "personality": "identity",
    "core mission": "mission",
    "mission": "mission",
    "critical rules": "critical_rules",
    "rules": "critical_rules",
    "technical deliverables": "deliverables",
    "deliverables": "deliverables",
    "workflow process": "workflow",
    "workflow": "workflow",
    "deliverable template": "deliverable_template",
    "output template": "deliverable_template",
    "skills": "domain_expertise",
    "expertise": "domain_expertise",
    "tools": "tools",
    "tooling": "tools",
    "tags": "tags",
}


def _extract_bullets(lines: List[str]) -> List[str]:
    items: List[str] = []
    for line in lines:
        m = _BULLET_RE.match(line)
        if m:
            items.append(m.group(1).strip())
    if items:
        return items
    # Fallback: non-empty lines as items
    return [line.strip() for line in lines if line.strip()]


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return text[:64] if text else "persona"


class AgentPersonaParser:
    """Parse markdown agent files into AgentPersona."""

    def parse_file(self, path: Path) -> AgentPersona:
        content = Path(path).read_text(encoding="utf-8")
        return self.parse(content, source_path=str(path), filename=Path(path).name, division_hint=Path(path).parent.name)

    def parse(
        self,
        content: str,
        source_path: str | None = None,
        filename: str | None = None,
        division_hint: str | None = None,
    ) -> AgentPersona:
        sections = self._split_sections(content)
        first_heading = self._first_heading(content)
        name = self._extract_name(sections, filename, first_heading)
        role = self._derive_role(name, filename)
        division = division_hint or ""

        identity = sections.get("identity", "")
        mission = sections.get("mission", "")
        critical_rules = _extract_bullets(sections.get("critical_rules", "").splitlines())
        deliverables = _extract_bullets(sections.get("deliverables", "").splitlines())
        workflow = _extract_bullets(sections.get("workflow", "").splitlines())
        deliverable_template = sections.get("deliverable_template", "").strip()
        domain_expertise = _extract_bullets(sections.get("domain_expertise", "").splitlines())
        tools = _extract_bullets(sections.get("tools", "").splitlines())
        tags = _extract_bullets(sections.get("tags", "").splitlines())

        if not domain_expertise:
            domain_expertise = self._derive_expertise_from_name(name, division)

        persona_id = _slugify(f"{division}-{name}" if division else name)

        return AgentPersona(
            persona_id=persona_id,
            name=name,
            role=role,
            division=division,
            description=sections.get("description", ""),
            identity=identity.strip(),
            mission=mission.strip(),
            critical_rules=[r for r in critical_rules if r],
            deliverables=[d for d in deliverables if d],
            workflow=[w for w in workflow if w],
            deliverable_template=deliverable_template,
            domain_expertise=domain_expertise,
            tools=[t for t in tools if t],
            tags=[t for t in tags if t],
            source_path=source_path,
        )

    def _split_sections(self, content: str) -> Dict[str, str]:
        current_key = "description"
        sections: Dict[str, List[str]] = {current_key: []}

        for line in content.splitlines():
            heading = _HEADING_RE.match(line)
            if heading:
                title = _normalize_heading(heading.group(1))
                current_key = _SECTION_MAP.get(title, title)
                if current_key not in sections:
                    sections[current_key] = []
                continue
            sections.setdefault(current_key, []).append(line)

        return {k: "\n".join(v).strip() for k, v in sections.items()}

    def _extract_name(
        self,
        sections: Dict[str, str],
        filename: str | None,
        first_heading: str | None,
    ) -> str:
        if sections.get("description"):
            first_line = sections["description"].splitlines()[0].strip()
            if first_line:
                return first_line.strip("# ").strip()
        if first_heading:
            return first_heading.strip()
        if filename:
            return filename.replace(".md", "").replace("_", " ").replace("-", " ").title()
        return "Agent Persona"

    def _first_heading(self, content: str) -> str | None:
        for line in content.splitlines():
            heading = _HEADING_RE.match(line)
            if heading:
                return heading.group(1).strip()
        return None

    def _derive_role(self, name: str, filename: str | None) -> str:
        if name:
            return name
        if filename:
            return filename.replace(".md", "").replace("_", " ").replace("-", " ").title()
        return "Agent"

    def _derive_expertise_from_name(self, name: str, division: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z]+", f"{division} {name}")
        return [t.lower() for t in tokens if t]
