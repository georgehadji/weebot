"""Persona router for selecting the best agent profile."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from weebot.agents.models import AgentPersona


@dataclass
class PersonaScore:
    persona: AgentPersona
    score: float


class PersonaRouter:
    """Select the best persona for a task description."""

    def score(self, persona: AgentPersona, task_description: str) -> float:
        profile = persona.to_profile()
        score = profile.match_score(task_description)

        task_lower = task_description.lower()
        tag_hits = sum(1 for t in persona.tags if t.lower() in task_lower)
        score += tag_hits * 0.5
        return score

    def route(self, personas: List[AgentPersona], task_description: str, top_n: int = 3) -> List[PersonaScore]:
        scored = [
            PersonaScore(persona=p, score=self.score(p, task_description))
            for p in personas
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_n]
