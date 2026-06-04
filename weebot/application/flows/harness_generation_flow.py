"""HarnessGenerationFlow — generates agent teams and skills from domain input.

State machine that takes a domain description and produces:
1. Agent definitions (.claude/agents/*.md)
2. Skill files (.claude/skills/*/SKILL.md)
3. An orchestrator skill that wires the team together

Follows the 6-phase approach from revfactory/harness.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from weebot.domain.models.team_architecture import (
    AgentDefinition,
    SkillBlueprint,
    TeamArchitecture,
    TeamPattern,
)

logger = logging.getLogger(__name__)


class HarnessGenerationFlow:
    """Generates a team harness from a domain description.

    Args:
        llm: Optional LLM port for AI-powered generation. When None,
            uses template-based generation (deterministic).
        output_dir: Base output directory. Defaults to current directory.
    """

    # Template mappings for pattern descriptions
    PATTERN_DESCRIPTIONS = {
        TeamPattern.PIPELINE: (
            "Sequential pipeline: each agent's output feeds the next. "
            "Best when stages strongly depend on previous stage outputs."
        ),
        TeamPattern.FAN_OUT_FAN_IN: (
            "Fan-out/fan-in: parallel independent tasks merged by a synthesizer. "
            "Best for multi-perspective research or parallel investigations."
        ),
        TeamPattern.EXPERT_POOL: (
            "Expert pool: a router dispatches tasks to the appropriate specialist. "
            "Best when different inputs require different handling."
        ),
        TeamPattern.PRODUCER_REVIEWER: (
            "Producer-reviewer: generation followed by quality review with "
            "iterative refinement. Best for quality-critical outputs."
        ),
        TeamPattern.SUPERVISOR: (
            "Supervisor: central agent dynamically distributes work. "
            "Best for variable workloads requiring runtime reallocation."
        ),
        TeamPattern.HIERARCHICAL_DELEGATION: (
            "Hierarchical delegation: top-down recursive delegation "
            "with team leads and specialists. Best for naturally hierarchical problems."
        ),
    }

    def __init__(
        self,
        llm: Optional[object] = None,
        output_dir: str = ".",
    ) -> None:
        self._llm = llm
        self._output_dir = Path(output_dir)

    async def generate(self, domain: str) -> TeamArchitecture:
        """Generate a complete team architecture from *domain*.

        Args:
            domain: Natural language description of the domain/project.

        Returns:
            ``TeamArchitecture`` with agents, skills, and orchestrator.
        """
        # Phase 1: Domain analysis — identify work types
        work_types = self._analyze_domain(domain)

        # Phase 2: Team architecture selection
        pattern = self._select_pattern(work_types, domain)
        agents = self._design_agents(domain, pattern)
        skills = self._design_skills(domain, agents, pattern)

        rationale = self._build_rationale(domain, pattern, agents)

        return TeamArchitecture(
            domain=domain,
            pattern=pattern,
            agents=agents,
            skills=skills,
            orchestrator_description=self._build_orchestrator_description(domain, pattern),
            rationale=rationale,
        )

    async def generate_and_write(self, domain: str) -> TeamArchitecture:
        """Generate a harness and write all files to disk.

        Creates:
        - ``.claude/agents/{name}.md`` for each agent
        - ``.claude/skills/{name}/SKILL.md`` for each skill
        - Updates ``CLAUDE.md`` with harness pointer

        Args:
            domain: Natural language domain description.

        Returns:
            The generated ``TeamArchitecture``.
        """
        arch = await self.generate(domain)

        agents_dir = self._output_dir / ".claude" / "agents"
        skills_dir = self._output_dir / ".claude" / "skills"

        # Write agent definitions
        for agent in arch.agents:
            agent_path = agents_dir / f"{agent.name}.md"
            agent_path.parent.mkdir(parents=True, exist_ok=True)
            agent_path.write_text(
                self._render_agent(agent), encoding="utf-8",
            )
            logger.info("Wrote agent: %s", agent_path)

        # Write skill files
        for skill in arch.skills:
            skill_path = skills_dir / skill.name / "SKILL.md"
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(
                self._render_skill(skill), encoding="utf-8",
            )
            logger.info("Wrote skill: %s", skill_path)

        # Write orchestrator skill
        orch_path = skills_dir / f"{arch.pattern.value}-orchestrator" / "SKILL.md"
        orch_path.parent.mkdir(parents=True, exist_ok=True)
        orch_path.write_text(
            self._render_orchestrator(arch), encoding="utf-8",
        )
        logger.info("Wrote orchestrator: %s", orch_path)

        # Update CLAUDE.md pointer
        await self._update_claude_md(arch)

        return arch

    # ── Phase 1: Domain analysis ───────────────────────────────────

    def _analyze_domain(self, domain: str) -> list[str]:
        """Extract work types from the domain description.

        Returns a list of action types: research, design, implement, review, etc.
        """
        domain_lower = domain.lower()
        work_types = []

        type_keywords = {
            "research": ["research", "analyze", "investigate", "study", "survey"],
            "design": ["design", "plan", "architect", "blueprint"],
            "implement": ["implement", "build", "develop", "create", "write", "code"],
            "review": ["review", "validate", "verify", "test", "check", "qa"],
            "collect": ["collect", "gather", "scrape", "fetch", "extract"],
            "synthesize": ["synthesize", "summarize", "consolidate", "report"],
        }

        for work_type, keywords in type_keywords.items():
            if any(kw in domain_lower for kw in keywords):
                work_types.append(work_type)

        if not work_types:
            work_types = ["research", "implement", "review"]

        return work_types

    # ── Phase 2: Pattern selection ─────────────────────────────────

    def _select_pattern(self, work_types: list[str], domain: str) -> TeamPattern:
        """Select the best team pattern based on work types."""
        domain_lower = domain.lower()

        # Producer-reviewer for quality-critical domains
        if "review" in work_types and "implement" not in work_types:
            return TeamPattern.PRODUCER_REVIEWER

        # Hierarchical delegation for large-scale projects
        if any(kw in domain_lower for kw in ["large", "complex", "enterprise", "full-stack"]):
            return TeamPattern.HIERARCHICAL_DELEGATION

        # Fan-out/fan-in for research-heavy domains
        if "research" in work_types and "collect" in work_types:
            return TeamPattern.FAN_OUT_FAN_IN

        # Expert pool for multi-faceted domains
        if len(work_types) >= 3:
            return TeamPattern.SUPERVISOR

        # Default: pipeline for sequential workflows
        return TeamPattern.PIPELINE

    # ── Agent design ───────────────────────────────────────────────

    def _design_agents(
        self,
        domain: str,
        pattern: TeamPattern,
    ) -> list[AgentDefinition]:
        """Design agents for the given domain and pattern."""
        domain_lower = domain.lower()

        # Pattern-specific agent designs
        pattern_agents = {
            TeamPattern.PIPELINE: [
                AgentDefinition(
                    name="analyst",
                    role="Domain analysis and requirements gathering",
                    persona="Thorough analyst who researches the domain",
                    skills=["research"],
                ),
                AgentDefinition(
                    name="designer",
                    role="Solution design and architecture",
                    persona="Creative designer who plans the approach",
                    skills=["plan"],
                ),
                AgentDefinition(
                    name="builder",
                    role="Implementation and development",
                    persona="Skilled builder who produces the output",
                    skills=["implement"],
                ),
                AgentDefinition(
                    name="reviewer",
                    role="Quality assurance and review",
                    persona="Detail-oriented reviewer who catches issues",
                    skills=["review"],
                ),
            ],
            TeamPattern.FAN_OUT_FAN_IN: [
                AgentDefinition(
                    name="coordinator",
                    role="Task distribution and result synthesis",
                    persona="Organised coordinator who manages parallel work",
                    skills=["coordinate"],
                ),
                AgentDefinition(
                    name="researcher-a",
                    role="Primary research from one perspective",
                    persona="Focused researcher exploring one angle",
                    skills=["research"],
                ),
                AgentDefinition(
                    name="researcher-b",
                    role="Secondary research from another perspective",
                    persona="Independent researcher covering a different angle",
                    skills=["research"],
                ),
                AgentDefinition(
                    name="synthesizer",
                    role="Merge findings into unified report",
                    persona="Integrative thinker who combines perspectives",
                    skills=["synthesize"],
                ),
            ],
            TeamPattern.EXPERT_POOL: [
                AgentDefinition(
                    name="router",
                    role="Classify inputs and dispatch to experts",
                    persona="Swift classifier who routes to the right expert",
                    skills=["route"],
                ),
                AgentDefinition(
                    name="domain-expert",
                    role="Execute domain-specific tasks",
                    persona="Deep specialist in the target domain",
                    skills=["execute"],
                ),
                AgentDefinition(
                    name="quality-expert",
                    role="Review and validate outputs",
                    persona="Quality-focused validator",
                    skills=["review"],
                ),
            ],
            TeamPattern.PRODUCER_REVIEWER: [
                AgentDefinition(
                    name="producer",
                    role="Create initial output from requirements",
                    persona="Creative producer who generates first drafts",
                    skills=["produce"],
                ),
                AgentDefinition(
                    name="reviewer",
                    role="Review and provide improvement feedback",
                    persona="Constructive critic who suggests improvements",
                    skills=["review"],
                ),
            ],
            TeamPattern.SUPERVISOR: [
                AgentDefinition(
                    name="supervisor",
                    role="Monitor progress and dynamically assign work",
                    persona="Strategic supervisor who keeps work flowing",
                    skills=["supervise"],
                ),
                AgentDefinition(
                    name="worker-a",
                    role="Execute assigned tasks",
                    persona="Reliable worker who completes tasks",
                    skills=["execute"],
                ),
                AgentDefinition(
                    name="worker-b",
                    role="Execute assigned tasks",
                    persona="Reliable worker who completes tasks",
                    skills=["execute"],
                ),
            ],
            TeamPattern.HIERARCHICAL_DELEGATION: [
                AgentDefinition(
                    name="orchestrator",
                    role="Top-level decomposition and final integration",
                    persona="Strategic orchestrator who sees the big picture",
                    skills=["orchestrate"],
                ),
                AgentDefinition(
                    name="lead-a",
                    role="Lead one sub-domain team",
                    persona="Team lead managing one area",
                    skills=["lead", "review"],
                ),
                AgentDefinition(
                    name="lead-b",
                    role="Lead another sub-domain team",
                    persona="Team lead managing a different area",
                    skills=["lead", "review"],
                ),
                AgentDefinition(
                    name="specialist-a1",
                    role="Execute tasks under lead-a",
                    persona="Focused specialist producing output",
                    skills=[f"{domain_lower[:20]}-execute"],
                ),
                AgentDefinition(
                    name="specialist-b1",
                    role="Execute tasks under lead-b",
                    persona="Focused specialist producing output",
                    skills=[f"{domain_lower[:20]}-execute"],
                ),
            ],
        }

        return pattern_agents.get(pattern, pattern_agents[TeamPattern.PIPELINE])

    # ── Skill design ───────────────────────────────────────────────

    def _design_skills(
        self,
        domain: str,
        agents: list[AgentDefinition],
        pattern: TeamPattern,
    ) -> list[SkillBlueprint]:
        """Design skills that agents will use."""
        skills = []

        # Create a skill for each unique skill name across agents
        all_skill_names = set()
        for agent in agents:
            for skill_name in agent.skills:
                if skill_name not in all_skill_names:
                    all_skill_names.add(skill_name)
                    skills.append(SkillBlueprint(
                        name=f"{domain[:20].replace(' ', '-')}-{skill_name}".lower(),
                        description=f"Execute {skill_name} tasks for {domain} domain",
                        content=f"# {skill_name.capitalize()} for {domain}\n\n"
                                f"Follow these steps when asked to perform "
                                f"{skill_name} tasks in the {domain} domain.\n",
                    ))

        if not skills:
            skills.append(SkillBlueprint(
                name=f"{domain[:20].replace(' ', '-')}-default".lower(),
                description=f"Default skill for {domain} tasks",
                content=f"# {domain} Tasks\n\nHandle tasks in the {domain} domain.\n",
            ))

        return skills

    # ── Rendering ──────────────────────────────────────────────────

    def _render_agent(self, agent: AgentDefinition) -> str:
        """Render an agent definition file (.md)."""
        skills_list = "\n".join(f"  - {s}" for s in agent.skills)
        return (
            f"---\n"
            f"name: {agent.name}\n"
            f"description: \"{agent.role}\"\n"
            f"---\n"
            f"\n"
            f"# {agent.name.capitalize()} — {agent.role}\n"
            f"\n"
            f"{agent.persona}\n"
            f"\n"
            f"## 핵심 역할\n"
            f"1. {agent.role}\n"
            f"\n"
            f"## 스킬\n"
            f"{skills_list}\n"
            f"\n"
            f"## 협업\n"
            f"- 다른 에이전트와 협력하여 {agent.role} 작업을 수행합니다.\n"
            f"- 결과는 파일로 저장하고 오케스트레이터가 통합합니다.\n"
        )

    def _render_skill(self, skill: SkillBlueprint) -> str:
        """Render a skill file (SKILL.md)."""
        return (
            f"---\n"
            f"name: {skill.name}\n"
            f"description: \"{skill.description}\"\n"
            f"---\n"
            f"\n"
            f"{skill.content}\n"
        )

    def _render_orchestrator(self, arch: TeamArchitecture) -> str:
        """Render the orchestrator skill."""
        agent_table = "\n".join(
            f"| {a.name} | {a.agent_type} | {a.role} |"
            for a in arch.agents
        )
        return (
            f"---\n"
            f"name: {arch.pattern.value}-orchestrator\n"
            f"description: \"{arch.orchestrator_description}\"\n"
            f"---\n"
            f"\n"
            f"# {arch.domain} Orchestrator ({arch.pattern.value})\n"
            f"\n"
            f"{self.PATTERN_DESCRIPTIONS.get(arch.pattern, '')}\n"
            f"\n"
            f"## Team Composition\n"
            f"\n"
            f"| Agent | Type | Role |\n"
            f"|-------|------|------|\n"
            f"{agent_table}\n"
            f"\n"
            f"## Rationale\n"
            f"{arch.rationale}\n"
            f"\n"
            f"## Data Flow\n"
            f"See references/{arch.pattern.value}-data-flow.md for detailed orchestration.\n"
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _build_rationale(
        self,
        domain: str,
        pattern: TeamPattern,
        agents: list[AgentDefinition],
    ) -> str:
        """Build a rationale explaining the architecture choices."""
        return (
            f"Domain '{domain}' requires {len(agents)} agents using the "
            f"{pattern.value} pattern. This pattern was selected because "
            f"{self.PATTERN_DESCRIPTIONS.get(pattern, 'it fits the domain requirements.')}"
        )

    def _build_orchestrator_description(
        self,
        domain: str,
        pattern: TeamPattern,
    ) -> str:
        """Build the orchestrator skill's description field."""
        return (
            f"Orchestrate the {domain} agent team using {pattern.value} pattern. "
            f"Use this skill when asked about {domain} tasks, team coordination, "
            f"or multi-agent workflows in this domain."
        )

    async def _update_claude_md(self, arch: TeamArchitecture) -> None:
        """Append a harness pointer to CLAUDE.md."""
        claude_path = self._output_dir / "CLAUDE.md"
        existing = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""

        pointer = (
            f"\n## Harness: {arch.domain}\n\n"
            f"**Pattern:** {arch.pattern.value}\n"
            f"**Agents:** {', '.join(a.name for a in arch.agents)}\n"
            f"**Trigger:** {arch.domain} tasks → use `{arch.pattern.value}-orchestrator` skill.\n"
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        )

        if "## Harness:" in existing:
            # Update existing pointer
            lines = existing.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if line.startswith("## Harness:"):
                    skip = True
                elif skip and line.startswith("## "):
                    skip = False
                if not skip:
                    new_lines.append(line)
            existing = "\n".join(new_lines).strip()

        claude_path.write_text(existing + "\n" + pointer, encoding="utf-8")
        logger.info("Updated CLAUDE.md with harness pointer")
