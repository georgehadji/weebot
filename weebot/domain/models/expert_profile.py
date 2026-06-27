"""Expert profiles — typed specialization profiles for agent roles.

Based on the paper "Fundamentals of Building Autonomous LLM Agents"
(arXiv:2510.09244v1), §4.5–4.6: "A single agent can be made up of
different specialized experts, each focusing on a distinct aspect of
interaction or reasoning."

Each expert profile defines:
- specialization: what the expert does
- system_prompt_hint: how the LLM should behave
- allowed_tools: which tools the expert can call
- input_schema: what information the expert expects
- output_schema: what the expert produces
- boundary_rules: when to delegate to other experts
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExpertProfile:
    """Formal specialization profile for an agent role.

    Attributes:
        role_name: The role identifier (e.g., "planner", "executor").
        specialization: One-line description of the expert's domain.
        system_prompt_hint: Behavioral instruction injected into the LLM
                            system prompt.
        allowed_tools: List of tool names this expert is authorized to use.
        input_description: What information this expert acts on.
        output_description: What this expert produces.
        boundary_rules: Conditions under which this expert delegates to
                        another expert or raises a hand-off signal.
        tier: Capability access level ("public", "controlled", "restricted",
              "privileged").
    """
    role_name: str = ""
    specialization: str = ""
    system_prompt_hint: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    input_description: str = ""
    output_description: str = ""
    boundary_rules: list[str] = field(default_factory=list)
    tier: str = "public"


# ── Built-in expert profiles (mapped from task-oriented roles) ──────────

BUILTIN_EXPERTS: dict[str, ExpertProfile] = {
    "planner": ExpertProfile(
        role_name="planner",
        specialization="Strategic planning and task decomposition",
        system_prompt_hint=(
            "You are a planning expert. Break complex tasks into clear, "
            "executable steps. Think about dependencies and order."
        ),
        allowed_tools=["web_search", "vane_search", "knowledge", "product"],
        input_description="User task description, optional skill prompt, optional facts",
        output_description="Structured JSON plan with ordered steps",
        boundary_rules=[
            "If the task requires code generation, hand off to coder expert",
            "If the task requires visual design, hand off to designer expert",
        ],
        tier="public",
    ),
    "executor": ExpertProfile(
        role_name="executor",
        specialization="Step-by-step task execution with tools",
        system_prompt_hint=(
            "You are an execution expert. Complete each step methodically "
            "using the available tools. Verify your results before moving on."
        ),
        allowed_tools=[],  # All tools allowed — set dynamically per role
        input_description="Current plan step, previous step results, tool set",
        output_description="Completed step results or error/failure signal",
        boundary_rules=[
            "If a step fails, classify severity and route to reflection expert",
            "If all tools fail, signal FULL_REPLAN to planner expert",
        ],
        tier="controlled",
    ),
    "reviewer": ExpertProfile(
        role_name="reviewer",
        specialization="Code and result quality review",
        system_prompt_hint=(
            "You are a review expert. Check completed work for correctness, "
            "completeness, over-engineering, and security issues."
        ),
        allowed_tools=["web_search", "file_editor"],
        input_description="Completed step code or output, original step description",
        output_description="Review verdict: approve, revise (with hint), or reject (with reason)",
        boundary_rules=[
            "If security concerns found, route to admin expert",
            "If output is incomplete, return 'revise' with specific hint",
        ],
        tier="public",
    ),
    "dreamer": ExpertProfile(
        role_name="dreamer",
        specialization="Proactive ideation and opportunity discovery",
        system_prompt_hint=(
            "You are a dreamer expert. Identify gaps, improvement opportunities, "
            "and new feature ideas from session outcomes and failure signals."
        ),
        allowed_tools=["web_search", "knowledge", "persistent_memory"],
        input_description="Session failure signals, audit violations, completed task summary",
        output_description="Idea contracts with priority scores",
        boundary_rules=[
            "Route ideas through IntentReview before MainReview",
            "Defer high-cost ideas to separate planning session",
        ],
        tier="public",
    ),
    "coder": ExpertProfile(
        role_name="coder",
        specialization="Code generation and debugging",
        system_prompt_hint=(
            "You are a coding expert. Write clean, well-structured code. "
            "Use the file_editor and bash tools for all file operations."
        ),
        allowed_tools=["bash", "python_execute", "file_editor", "web_search"],
        input_description="Coding task specification, existing project context",
        output_description="Working code, test output, or error diagnosis",
        boundary_rules=[
            "If deployment is needed, hand off to automation expert",
            "If code review fails twice, escalate to architect",
        ],
        tier="restricted",
    ),
    "designer": ExpertProfile(
        role_name="designer",
        specialization="Visual design and image generation",
        system_prompt_hint=(
            "You are a design expert. Create visually appealing layouts, "
            "icons, logos, and images using the available tools."
        ),
        allowed_tools=["image_gen", "video_gen", "file_editor", "web_search"],
        input_description="Design brief, brand colors, image specifications",
        output_description="SVG, image files, or design system tokens",
        boundary_rules=[
            "If design requires user approval, pause and ask",
            "If complex animation needed, hand off to animation specialist",
        ],
        tier="public",
    ),
}


def get_expert_profile(role_name: str) -> Optional[ExpertProfile]:
    """Return the expert profile for a given role, or None if unknown."""
    return BUILTIN_EXPERTS.get(role_name)


def list_expert_profiles() -> list[ExpertProfile]:
    """Return all registered expert profiles."""
    return list(BUILTIN_EXPERTS.values())
