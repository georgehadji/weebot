"""Tests for agent persona parsing and routing."""
from pathlib import Path

from weebot.agents.parser import AgentPersonaParser
from weebot.agents.router import PersonaRouter


def test_persona_parser_extracts_sections():
    fixture = Path("tests/fixtures/agents/engineering-frontend-developer.md")
    parser = AgentPersonaParser()
    persona = parser.parse_file(fixture)

    assert persona.name == "Frontend Developer"
    assert persona.role == "Frontend Developer"
    assert "Performance-focused" in persona.identity
    assert "Avoid regressions" in persona.critical_rules
    assert "Performance audit" in persona.deliverables
    assert "Optimize" in persona.workflow
    assert "Summary" in persona.deliverable_template
    assert "frontend" in persona.domain_expertise


def test_persona_router_scores():
    fixture = Path("tests/fixtures/agents/engineering-frontend-developer.md")
    parser = AgentPersonaParser()
    persona = parser.parse_file(fixture)

    router = PersonaRouter()
    scored = router.route([persona], "Improve frontend performance and accessibility", top_n=1)
    assert scored[0].score > 0
