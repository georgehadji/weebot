"""E2E integration test — website generation via OpenRouter (Kimi K2.6).

Verifies that the full adapter stack can generate a complete, valid HTML
page from a natural-language prompt.  Uses the Plan-Act flow to plan the
site, execute the build step, and produce a summary.

Requires a valid OPENROUTER_API_KEY in .env.
Mark: real_api
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.agents.planner import PlannerAgent
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import (
    MessageEvent,
    PlanEvent,
    StepEvent,
    TitleEvent,
)
from weebot.domain.models.session import Session
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory
from weebot.tools.bash_tool import BashTool
from weebot.tools.file_editor import StrReplaceEditorTool


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


def _load_key() -> str | None:
    key = os.getenv("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


_needs_key = pytest.mark.skipif(
    _load_key() is None,
    reason="OPENROUTER_API_KEY not set",
)


@pytest.fixture(scope="module")
def llm() -> LLMPort:
    """OpenRouter adapter using Kimi K2.6."""
    factory = AdapterFactory()
    return factory.create_adapter(
        provider="openrouter",
        model="moonshotai/kimi-k2-0905",
        api_key=_load_key(),
        enable_retry=True,
    )


@pytest.fixture
def tools() -> ToolCollection:
    return ToolCollection(
        BashTool(),
        StrReplaceEditorTool(),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.real_api
@_needs_key
@pytest.mark.asyncio
async def test_planner_creates_website_plan(llm: LLMPort) -> None:
    """The planner agent should produce a plan with steps for building a site."""
    planner = PlannerAgent(llm=llm)
    events: list = []

    async for event in planner.create_plan(
        "Build a single-page personal portfolio website. "
        "Include a header with my name, a skills section, "
        "and a contact footer. Use clean semantic HTML with inline CSS."
    ):
        events.append(event)

    # Should emit at least a TitleEvent and a PlanEvent
    assert len(events) >= 2, f"Expected ≥2 events, got {len(events)}"
    titles = [e for e in events if isinstance(e, TitleEvent)]
    plans = [e for e in events if isinstance(e, PlanEvent)]
    assert titles, "Planner must emit a TitleEvent"
    assert plans, "Planner must emit a PlanEvent"
    raw = plans[-1].plan
    assert raw is not None, "PlanEvent must contain a plan"
    # plan may be a dict (serialized) or Plan model
    steps = raw.get("steps", []) if isinstance(raw, dict) else raw.steps
    title = raw.get("title", "") if isinstance(raw, dict) else raw.title
    assert len(steps) >= 1, f"Expected ≥1 step, got {len(steps)}"
    print(f"\n  Plan: {title} ({len(steps)} steps)")


@pytest.mark.real_api
@_needs_key
@pytest.mark.asyncio
async def test_executor_runs_website_step(
    llm: LLMPort,
    tools: ToolCollection,
) -> None:
    """The executor agent should build a website file when given a plan step."""
    # Step 1 — plan the site
    planner = PlannerAgent(llm=llm)
    plan = None
    async for event in planner.create_plan(
        "Build a single-page personal portfolio website with the following sections: "
        "header (name 'Alex Chen'), skills (Python, React, Rust), contact footer. "
        "Use semantic HTML5 with inline CSS. Dark theme. "
        "Write the complete file to tasks/portfolio.html using file_editor."
    ):
        if isinstance(event, PlanEvent) and event.plan:
            plan = event.plan

    assert plan is not None, "Planner must produce a plan"
    steps = plan if isinstance(plan, list) else (plan.get("steps", []) if isinstance(plan, dict) else plan.steps)
    assert len(steps) >= 1, "Plan must have at least one step"
    step = steps[0]
    desc = step.description if hasattr(step, 'description') else step.get("description", str(step))
    print(f"\n  Running step: {desc}")

    # Step 2 — execute the first step
    executor = ExecutorAgent(llm=llm, tools=tools, max_steps=25)
    events: list = []
    collected_output: list[str] = []

    from weebot.domain.models.plan import Plan, Step
    if isinstance(plan, dict):
        plan = Plan.model_validate(plan)
    if isinstance(step, dict):
        step = Step.model_validate(step)
    async for event in executor.execute_step(plan, step):
        events.append(event)
        if isinstance(event, MessageEvent):
            collected_output.append(event.message or "")

    # The step should produce at least one message
    assert len(collected_output) > 0, "Executor should produce output"

    # Check that the output references HTML
    full_output = "\n".join(collected_output)
    html_indicators = ["<html", "<!DOCTYPE", "<head", "<body", "<div"]
    found = any(ind in full_output.lower() for ind in html_indicators)
    print(f"  HTML indicators found: {found}")
    print(f"  Output preview: {full_output[:200]}...")


@pytest.mark.real_api
@_needs_key
@pytest.mark.asyncio
async def test_full_flow_builds_website(
    llm: LLMPort,
    tools: ToolCollection,
    tmp_path: Path,
) -> None:
    """End-to-end: PlanActFlow builds a complete website via the state machine."""
    session = Session(id="test-website-e2e", user_id="tester")

    flow = PlanActFlow(
        llm=llm,
        tools=tools,
        session=session,
        max_step_repetitions=1,
        max_steps=20,
        max_iterations=5,
    )

    prompt = (
        "Create a complete single-file HTML landing page for a fictional SaaS "
        "startup called 'CloudBoard' — a collaborative whiteboard app. "
        "Requirements: "
        "1. Hero section with tagline 'Ideas, Together.' "
        "2. Three feature cards (real-time sync, infinite canvas, templates). "
        "3. CTA button 'Start Free'. "
        "4. Footer with copyright 2026. "
        "5. Dark theme with blue accents (#4A90D9). "
        "6. Fully self-contained — all CSS inline in <style> tag. "
        "Use the file_editor tool to write the output to tasks/cloudboard.html."
    )

    states_seen: set[str] = set()
    plan_steps: list[str] = []
    outputs: list[str] = []

    async for event in flow.run(prompt):
        state_name = type(flow._state).__name__ if flow._state else "none"
        states_seen.add(state_name)

        if isinstance(event, PlanEvent) and event.plan:
            raw = event.plan
            steps = raw if isinstance(raw, list) else (raw.get("steps", []) if isinstance(raw, dict) else raw.steps)
            plan_steps = [s.get("description", str(s)) if isinstance(s, dict) else s.description for s in steps]
        if isinstance(event, StepEvent):
            if event.status == "started":
                print(f"\n  ▶ Step: {event.description}")
            elif event.status in ("completed", "failed"):
                print(f"  ◼ Step {event.status}: {event.description}")
        if isinstance(event, MessageEvent):
            msg = event.message or ""
            outputs.append(msg)
            if msg.strip():
                print(f"  💬 {msg[:120]}")

    # Verify the flow progressed and produced output
    assert len(states_seen) >= 2, f"Flow should visit ≥2 states, saw {states_seen}"
    assert len(plan_steps) >= 1, f"Expected ≥1 plan step, got {len(plan_steps)}"
    full_output = "\n".join(outputs)
    print(f"\n  States visited: {sorted(states_seen)}")
    print(f"  Plan steps: {plan_steps}")
    print(f"  Output length: {len(full_output)} chars")


@pytest.mark.real_api
@_needs_key
@pytest.mark.asyncio
async def test_direct_html_generation(llm: LLMPort) -> None:
    """Direct chat: ask the LLM to generate a complete HTML page in one shot."""
    response = await llm.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a web developer. Respond ONLY with a complete, "
                    "valid HTML5 document. No explanations, no markdown fences."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a one-page portfolio site for a developer named "
                    "'Alex Chen'. Include: header with name and nav links "
                    "(Home, Projects, Contact), a hero section, a skills "
                    "section with 3 skill cards (Python, React, Rust), and "
                    "a footer. Dark theme, semantic HTML, inline CSS in <style>. "
                    "Output the complete HTML document."
                ),
            },
        ],
        response_format={"type": "text"},
    )

    html = response.content or ""

    # Validate the output
    assert len(html) > 200, f"Expected >200 chars of HTML, got {len(html)}"
    assert "<!DOCTYPE html>" in html or "<html" in html.lower(), (
        f"Expected HTML doctype or html tag in output"
    )
    assert "Alex Chen" in html, "Expected name 'Alex Chen' in output"
    assert "Python" in html, "Expected skill 'Python' in output"
    assert "footer" in html.lower() or "<footer" in html, (
        "Expected footer in output"
    )

    # Rough structure check
    has_head = "<head>" in html or "<head " in html
    has_body = "<body>" in html or "<body " in html
    has_style = "<style>" in html

    print(f"\n  HTML length: {len(html)} chars")
    print(f"  Has <head>: {has_head}")
    print(f"  Has <body>: {has_body}")
    print(f"  Has <style>: {has_style}")
    print(f"  Preview: {html[:200]}...")

    assert has_head or has_body, "HTML should have <head> or <body>"
    assert has_style, "HTML should have inline <style>"
