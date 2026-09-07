"""Structured output models for reliable agent communication.

This module provides Pydantic models for enforcing structured JSON output
from the agent, enabling programmatic handling of responses and improving
reliability.

Based on patterns from The Dev Squad analysis.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class TaskStatus(str, Enum):
    """Agent task completion status."""

    SUCCESS = "success"  # All tasks completed successfully
    PARTIAL = "partial"  # Some tasks done, need retry or user input
    FAILED = "failed"  # Critical failure, should stop
    NEEDS_CLARIFICATION = "needs_clarification"  # Ask user for more info


class CodeChange(BaseModel):
    """A single code change proposed by the agent."""

    file_path: str = Field(..., description="Path to the file to modify (relative to project root)")
    change_type: Literal["create", "modify", "delete"] = Field(
        ..., description="Type of change to make"
    )
    description: str = Field(..., description="Human-readable description of what changed")
    reasoning: str = Field(..., description="Why this change is needed")
    code: str | None = Field(None, description="Actual code content (for create/modify operations)")

    @field_validator("file_path")
    @classmethod
    def no_path_traversal(cls, v: str) -> str:
        """Prevent directory traversal attacks."""
        if ".." in v:
            raise ValueError(f"Path cannot contain '..': {v}")
        if v.startswith("/"):
            raise ValueError(f"Path must be relative, not absolute: {v}")
        if v.startswith("\\"):
            raise ValueError(f"Path must be relative, not absolute: {v}")
        return v


class BashCommand(BaseModel):
    """A shell command the agent wants to execute."""

    command: str = Field(..., description="The command to execute")
    purpose: str = Field(..., description="Why this command is needed")
    expected_output: str | None = Field(
        None, description="What output is expected (for verification)"
    )
    fallback_command: str | None = Field(None, description="Alternative command if primary fails")
    requires_approval: bool = Field(
        False, description="Whether user approval is required before execution"
    )
    timeout_seconds: int = Field(60, ge=1, le=3600, description="Command timeout in seconds")


class ValidationResult(BaseModel):
    """Result of a validation check performed by the agent."""

    check_name: str = Field(..., description="Name of the validation check")
    passed: bool = Field(..., description="Whether the check passed")
    message: str = Field(..., description="Human-readable result message")
    severity: Literal["info", "warning", "error", "critical"] = Field(
        "info", description="Severity of the result"
    )
    details: dict[str, Any] | None = Field(None, description="Additional details")


class WeebotOutput(BaseModel):
    """Root structured output from the weebot agent.

    This is the standard output format that the agent must produce.
    It includes work products (code changes, commands), metadata,
    and user interaction fields.
    """

    # Core fields (required)
    status: TaskStatus = Field(..., description="Overall task status indicating completion level")
    message: str = Field(..., description="Human-readable summary of what was done")
    reasoning: str = Field(..., description="Agent's step-by-step thought process")

    # Work products
    code_changes: list[CodeChange] = Field(
        default_factory=list, description="Code changes to apply"
    )
    bash_commands: list[BashCommand] = Field(
        default_factory=list, description="Shell commands to execute"
    )
    validation_results: list[ValidationResult] = Field(
        default_factory=list, description="Results of validation checks"
    )

    # User interaction
    requires_user_input: bool = Field(False, description="Whether user input is needed to proceed")
    suggested_questions: list[str] = Field(
        default_factory=list, description="Questions the user could ask to clarify"
    )
    next_action: str | None = Field(None, description="Recommended next action for the user")

    # Metadata
    confidence: float = Field(
        0.5, ge=0.0, le=1.0, description="Agent's confidence in the result (0-1)"
    )
    estimated_complexity: int = Field(
        5, ge=1, le=10, description="Estimated task complexity (1-10)"
    )

    # Cost tracking (from Hyperagent analysis)
    tokens_used: int = Field(0, description="Total tokens consumed")
    prompt_tokens: int = Field(0, description="Tokens in the prompt")
    completion_tokens: int = Field(0, description="Tokens in the completion")
    estimated_cost: float = Field(0.0, description="Estimated cost in USD")
    model_used: str = Field("unknown", description="Model used for this response")
    cache_hit: bool = Field(False, description="Whether this was a cache hit")

    # Timing
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this output was created"
    )
    processing_time_ms: int = Field(0, description="Time taken to process in milliseconds")


class OutputParseError(BaseModel):
    """Error information when parsing fails."""

    raw_text: str = Field(..., description="The raw text that failed to parse")
    error_message: str = Field(..., description="Explanation of why parsing failed")
    partial_output: WeebotOutput | None = Field(
        None, description="Partially parsed output if available"
    )


# ── Agent payload schemas (CLAUDE.md rule 2) ──────────────────────────
#
# One model per agent payload, all in this module, because rule 2 names this
# module as where they live. They are NOT `WeebotOutput` subclasses: an idea
# list and a goal decomposition do not have a status/message/reasoning shape,
# and forcing them into one would be worse code rather than more compliant.
#
# What they replace is four hand-rolled parsers doing fieldwise
# `.get(key, default)`, which substitutes the default only when a key is
# ABSENT. Measured on `GoalAgent.decompose` before this existed — three of five
# malformed responses ESCAPED the `except json.JSONDecodeError` written to
# absorb them:
#
#     priority is a word      -> ValueError: invalid literal for int()
#     goals is a string       -> AttributeError: 'str' object has no attribute 'get'
#     max_concurrency is word -> ValueError: invalid literal for int()
#     tools is a string       -> accepted silently, one goal built from characters
#     unparseable             -> fallback (the only case that worked)


class GoalSpec(BaseModel):
    """One sub-goal in a `GoalAgent` decomposition."""

    description: str = ""
    role: str = "researcher"
    tools: list[str] = Field(default_factory=lambda: ["web_search"])
    priority: int = 0


class GoalDecomposition(BaseModel):
    """`GoalAgent`'s response payload."""

    goals: list[GoalSpec] = Field(default_factory=list)
    max_concurrency: int = 4
    synthesis_strategy: str = "cluster"


class IdeaProposal(BaseModel):
    """One idea from `DreamerAgent`. Bounds live here, not at the call site."""

    title: str = "Untitled"
    prompt: str = ""
    source: str = "opportunity_proposal"
    evidence: list[str] = Field(default_factory=list)
    heat_score: float = 0.0
    estimated_effort: str = "medium"

    @field_validator("heat_score")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return min(1.0, max(0.0, v))


class IdeaProposalList(BaseModel):
    """`DreamerAgent` is prompted for a bare array; some models wrap it.

    The old code handled that with `data.get("ideas", data.get("contracts", []))`
    after an `isinstance(data, dict)` check. Both shapes are declared here
    instead, and `from_payload` is the one place that knows about it.
    """

    ideas: list[IdeaProposal] = Field(default_factory=list)

    @classmethod
    def from_payload(cls, data: Any) -> IdeaProposalList:
        if isinstance(data, list):
            return cls.model_validate({"ideas": data})
        if isinstance(data, dict):
            for key in ("ideas", "contracts"):
                if key in data:
                    return cls.model_validate({"ideas": data[key]})
        return cls.model_validate(data)


class HarnessEditProposal(BaseModel):
    """`LayerEditorAgent`'s response payload."""

    target: str = ""
    change: str = ""
    rationale: str = ""
    estimated_impact: str = "medium"


class EvaluatorPromptImprovement(BaseModel):
    """`OptimizerAgent`'s evaluator-reflection payload."""

    new_prompt: str = ""
    rationale: str = "Evaluator prompt improvement"


class EditSelection(BaseModel):
    """`OptimizerAgent`'s edit-ranking payload."""

    selected_indices: list[int] = Field(default_factory=list)


class SubtaskSpec(BaseModel):
    """One subtask from a DPPM decomposition."""

    title: str
    description: str


class SubtaskDecomposition(BaseModel):
    """`ParallelPlanner._decompose` — `{"subtasks": [...]}`."""

    subtasks: list[SubtaskSpec] = Field(default_factory=list)


class SubtaskPlan(BaseModel):
    """`ParallelPlanner._plan_subtask` — `{"steps": [...]}`.

    The declared return type there was `list[dict[str, str]] | None` and the
    code returned `data.get("steps", [])` straight out. Measured: `{"steps":
    "just do it"}` returned a **str**, `{"steps": {"1": "do"}}` a **dict**, and
    `{"steps": [1, 2, 3]}` a list of ints — all three escaped into
    `_assemble_candidates`, because `.get` substitutes its default only when
    the key is absent.
    """

    steps: list[dict[str, str]] = Field(default_factory=list)


class SkillEditSpec(BaseModel):
    """One entry of `{"edits": [...]}` from OptimizerAgent.

    Mirrors `weebot.domain.models.skill_edit.SkillEdit`'s wire shape rather
    than importing it, so this module stays a leaf with no application or
    domain imports. The caller builds the domain object from a validated spec.
    """

    op: Literal["append", "insert_after", "replace", "delete"]
    target: str | None = None
    content: str = ""
    support_count: int = 1
    source_type: str = "failure"


class SkillEditList(BaseModel):
    """`OptimizerAgent._parse_edits` — `{"edits": [...]}`."""

    edits: list[SkillEditSpec] = Field(default_factory=list)


class GuidanceContent(BaseModel):
    """`OptimizerAgent._produce_guidance` — one of three content keys.

    The old code did `data.get("slow_update_content") or ... or ""` and then
    `str(field)`, so a dict or a list under any of those keys became its repr.
    """

    slow_update_content: str | None = None
    meta_skill_content: str | None = None
    content: str | None = None

    def text(self) -> str:
        return self.slow_update_content or self.meta_skill_content or self.content or ""


class RetentionVerdictPayload(BaseModel):
    """`RetentionAgent.review` — `{"verdict", "reasoning", "improvement_notes"}`.

    `verdict` stays a plain string here: the domain's `RetentionVerdict` enum
    is what the caller coerces it into, and a value outside the enum should
    produce a named failure there rather than a validation error this module
    cannot explain.
    """

    verdict: str = "park"
    reasoning: str = ""
    improvement_notes: list[str] = Field(default_factory=list)


class SynthesisPayload(BaseModel):
    """`SynthesizerAgent.synthesize` — `{"clusters", "synthesis"}`.

    `SwarmResult` was constructed OUTSIDE the agent's try block from
    `data.get(...)`, so a wrong-typed field raised ValidationError out of
    `synthesize()` and lost the whole swarm's work — where the surrounding code
    plainly intends a fallback. Measured for both `clusters` and `synthesis`.
    """

    clusters: list[dict] = Field(default_factory=list)
    synthesis: str = ""


def extract_json_text(text: str) -> str:
    """Pull the JSON payload out of a model response.

    Handles a ```json fence, a bare object, and plain JSON — in that order.
    Returns *text* unchanged when it finds no delimiters, so the caller's
    `json.loads` produces the real error rather than one about extraction.

    Shared on purpose. Before this, FOUR modules each had their own version and
    no two agreed: `dreamer` split the fence on a newline, `goal_agent` tried a
    direct parse and then scanned for braces, `layer_editor_agent` scanned only
    when the text started with a fence, and `parse_agent_output` used these
    regexes. A model that wraps its answer differently succeeded in some and
    failed in others, for no reason a reader could see.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    # Decode from the first delimiter and stop at the end of that value.
    # `PlannerAgent._parse_json_content` had this step and this module did not,
    # and it is the difference on real model output: measured, the greedy regex
    # below fails on `{"a": 1} and also {"b": 2}` and on a nested object
    # followed by a stray brace, while raw_decode returns the first complete
    # value in both. The planner's copy was deleted in favour of this one, so
    # the stronger behaviour had to move here first.
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start != -1:
        try:
            _, end = json.JSONDecoder().raw_decode(text[start:])
            return text[start : start + end]
        except json.JSONDecodeError:
            pass

    braced = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if braced:
        return braced.group(0)
    return text


def parse_structured(
    raw_text: str | None,
    model: type[_ModelT],
    *,
    context: str = "",
) -> _ModelT | None:
    """Validate a model response against *model*, or return None.

    This is what CLAUDE.md rule 2 asks for — "structured JSON validated via
    Pydantic models in weebot/models/structured_output.py" — for agents whose
    payload is not `WeebotOutput`. Forcing an idea list or a goal decomposition
    into `WeebotOutput`'s status/message/reasoning shape would be worse code,
    not more compliant.

    Returns None rather than raising, because every caller already has a
    defined fallback (`_fallback_spec`, an empty list, a support-count sort)
    and a `None` they must handle is more honest than an exception they will
    wrap in a bare `except`. The failure is logged at WARNING, so a model that
    starts returning garbage is visible rather than silently degrading.

    What this replaces is not just four extractors but four fieldwise
    `.get(key, default)` readings, which substitute the default only when a key
    is ABSENT — never when it is present and wrong. `{"goals": "oops"}` reached
    the domain model as a string in the old code; here it fails validation.
    """
    if not raw_text or not raw_text.strip():
        logger.warning("Structured parse got an empty response%s.", f" ({context})" if context else "")
        return None
    try:
        data = json.loads(extract_json_text(raw_text.strip()))
    except json.JSONDecodeError as exc:
        logger.warning(
            "Structured parse found no valid JSON%s: %s",
            f" ({context})" if context else "",
            exc,
        )
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        logger.warning(
            "Structured parse failed validation against %s%s: %s",
            model.__name__,
            f" ({context})" if context else "",
            exc,
        )
        return None


def parse_agent_output(raw_text: str) -> WeebotOutput:
    """Parse agent output into structured format.

    Handles multiple input formats:
    - Valid JSON in markdown code blocks (```json ... ```)
    - Valid JSON without markdown
    - Invalid JSON (returns PARTIAL status with raw text)
    - Empty/whitespace input (returns FAILED status)

    Args:
        raw_text: The raw text output from the agent

    Returns:
        WeebotOutput: Structured output, or a default output indicating
        parse failure with status=PARTIAL or FAILED

    Examples:
        >>> output = parse_agent_output('{"status": "success", "message": "Done"}')
        >>> output.status
        <TaskStatus.SUCCESS: 'success'>

        >>> output = parse_agent_output("not json")
        >>> output.status
        <TaskStatus.PARTIAL: 'partial'>
    """
    # Clean the input
    text = raw_text.strip() if raw_text else ""
    if not text:
        return WeebotOutput(
            status=TaskStatus.FAILED,
            message="Empty response from agent",
            reasoning="Agent produced no output",
            confidence=0.0,
        )

    json_str = extract_json_text(text)

    # Try to parse as JSON
    try:
        data = json.loads(json_str)
        return WeebotOutput.model_validate(data)
    except json.JSONDecodeError as e:
        # JSON parsing failed
        return WeebotOutput(
            status=TaskStatus.PARTIAL,
            message=text[:500],  # Include first 500 chars for context
            reasoning=f"Failed to parse JSON: {e}. Raw text preserved in message.",
            confidence=0.3,
            requires_user_input=True,
            suggested_questions=[
                "Please rephrase your request more specifically",
                "Can you break this down into smaller steps?",
            ],
        )
    except Exception as e:
        # Pydantic validation failed
        return WeebotOutput(
            status=TaskStatus.PARTIAL,
            message=text[:500],
            reasoning=f"Validation error: {e}. The output structure was invalid.",
            confidence=0.3,
            requires_user_input=True,
            suggested_questions=["The response format was invalid. Please try again."],
        )


def create_system_prompt() -> str:
    """Create the system prompt that mandates structured output.

    Returns:
        str: System prompt with schema documentation and examples
    """
    schema_example = {
        "status": "success",
        "message": "Created hello.py with a greeting function",
        "reasoning": "The user requested a simple greeting function. I created a clean implementation with docstring and type hints.",
        "code_changes": [
            {
                "file_path": "hello.py",
                "change_type": "create",
                "description": "Created greeting function",
                "reasoning": "User needs a way to print greetings",
                "code": "def greet(name: str) -> None:\n    '''Print a greeting.'''\n    print(f'Hello, {name}!')",
            }
        ],
        "bash_commands": [],
        "validation_results": [],
        "confidence": 0.95,
        "estimated_complexity": 2,
    }

    return f"""You are Weebot, an AI coding assistant. You MUST respond with valid JSON wrapped in a markdown code block.

Your response format MUST be:
```json
{json.dumps(schema_example, indent=2)}
```

Field descriptions:

REQUIRED FIELDS:
- status: One of "success" (all done), "partial" (needs more work), "failed" (critical error), "needs_clarification" (ask user)
- message: Human-readable summary of what you did (1-2 sentences)
- reasoning: Your step-by-step thought process (be specific)

WORK PRODUCTS (include when applicable):
- code_changes: List of file changes. Each change needs:
  - file_path: Relative path from project root (e.g., "src/main.py")
  - change_type: "create", "modify", or "delete"
  - description: What changed
  - reasoning: Why this change
  - code: Complete file content for "create", or specific changes for "modify"
- bash_commands: Shell commands to run. Each needs:
  - command: The actual command
  - purpose: Why it's needed
  - requires_approval: true for risky commands (deletions, system changes)
- validation_results: Checks you performed

METADATA:
- confidence: 0.0-1.0, how sure you are this is correct
- estimated_complexity: 1-10, how complex was this task

USER INTERACTION:
- requires_user_input: true if you need the user to clarify
- suggested_questions: List of questions the user could answer to help
- next_action: What should happen next

RULES:
1. ALWAYS wrap your JSON in ```json ... ```
2. NEVER include explanatory text outside the JSON block
3. If unsure, use status "needs_clarification" and explain what you need
4. Use relative paths only (e.g., "src/main.py" not "/home/user/project/src/main.py")
5. For code changes, include COMPLETE file content for "create", specific diff for "modify"
6. Set requires_approval=true for any command that could be destructive
"""


# Global constant for easy import
STRUCTURED_OUTPUT_PROMPT = create_system_prompt()


# ═══════════════════════════════════════════════════════════════════════
# Verbalized Sampling — Phase 0 models
# ═══════════════════════════════════════════════════════════════════════


class SampledResponse(BaseModel):
    """One candidate from a verbalized distribution (VS paper).

    Attributes:
        text: Candidate response text or JSON payload.
        probability: Verbalized probability.  Steering signal only —
            never surfaced as calibrated confidence.  Accepted formats:
            0.12 (float), "0.12" (string), "12%" (string percent),
            12 (bare integer, read as percent).
    """

    text: str = Field(..., description="Candidate response text or JSON payload")
    probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Verbalized probability — steering signal only, not confidence",
    )

    @field_validator("probability", mode="before")
    @classmethod
    def _coerce_prob(cls, v: Any) -> float:
        """Coerce string/percent/integer formats to 0..1 float.

        Supports: 0.12 (float), "0.12" (string), "12%" (percent), and a bare
        integer > 1, which can only have been meant as a percentage since the
        field is bounded to 0..1.
        """
        if isinstance(v, (int, float)):
            if isinstance(v, int) and v > 1:
                return float(v) / 100.0
            return float(v)
        if isinstance(v, str):
            v = v.strip()
            if v.endswith("%"):
                return float(v.rstrip("%")) / 100.0
            return float(v)
        raise ValueError(f"Cannot coerce {v!r} to probability")


class SampledDistribution(BaseModel):
    """A verbalized distribution over candidate responses."""

    responses: list[SampledResponse] = Field(default_factory=list)

    def mode(self) -> SampledResponse | None:
        """Return the response with the highest probability (argmax)."""
        if not self.responses:
            return None
        return max(self.responses, key=lambda r: r.probability)

    def weighted_sample(self, rng: random.Random | None = None) -> SampledResponse | None:
        """Sample a response proportional to its probability.

        Args:
            rng: Optional seeded RNG for deterministic tests.

        Returns:
            SampledResponse or None if empty.
        """
        if not self.responses:
            return None
        if rng is None:
            rng = random.Random()
        probs = [r.probability for r in self.responses]
        total = sum(probs)
        if total == 0:
            return self.responses[0]  # uniform fallback
        normalized = [p / total for p in probs]
        return rng.choices(self.responses, weights=normalized, k=1)[0]

    def tail(self, threshold: float = 0.1) -> list[SampledResponse]:
        """Return responses with probability below *threshold* (low-typicality tail).

        The tail represents the most novel / diverse candidates.
        """
        return [r for r in self.responses if r.probability < threshold]

    def texts(self) -> list[str]:
        """Return the text of all responses."""
        return [r.text for r in self.responses]

    def __bool__(self) -> bool:
        return len(self.responses) > 0


# Re-export prompt template path (loaded via load_prompt_with_fallback)
VS_PROMPT_FILENAME: str = "verbalized_sampling.txt"
VS_FALLBACK_PROMPT: str = (
    "You are a helpful assistant. For the given task, generate a set of {k} DISTINCT "
    "candidate responses that together approximate the full distribution of good answers.\n\n"
    "Return ONLY valid JSON, no markdown:\n"
    '{{"responses": [{{"text": "<candidate>", "probability": <0..1>}}, ...]}}\n\n'
    "- Each candidate must be meaningfully different from the others.\n"
    '"probability" is your estimate of how typical/likely each candidate is.\n'
    "{threshold_clause}"
)


def parse_sampled_distribution(raw_text: str) -> SampledDistribution:
    """Parse an LLM response into a SampledDistribution.

    Handles the same formats as ``parse_agent_output``: fenced JSON
    (```json ... ```), bare JSON, or raw braces.  Never raises —
    returns an empty distribution on any parse failure for fail-open.

    Args:
        raw_text: Raw LLM response text.

    Returns:
        SampledDistribution — empty on failure, never None/raises.
    """
    text = raw_text.strip() if raw_text else ""
    if not text:
        return SampledDistribution()

    # Try markdown code block first
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try bare JSON object
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0)
        else:
            return SampledDistribution()

    try:
        data = json.loads(json_str)
        if isinstance(data, dict) and "responses" in data:
            return SampledDistribution(**data)
        return SampledDistribution()
    except (json.JSONDecodeError, ValueError):
        return SampledDistribution()


# ── Phase 2: Vision reflection models (PicoAgents audit) ────────────────────


class PageObservation(BaseModel):
    """Structured description of the current screen state, produced by a vision LLM.

    Used in the vision-in-the-loop reflection step so the agent can articulate
    what it sees before deciding on the next action.
    """

    summary: str = Field(..., description="One-sentence description of the current screen state")
    key_elements: list[str] = Field(
        default_factory=list,
        description="Salient UI elements visible (buttons, text fields, dialogs, icons)",
    )
    is_task_complete: bool = Field(
        False, description="Whether the overall task appears to be complete based on this screen"
    )
    confidence: float = Field(
        0.5, ge=0.0, le=1.0, description="Model confidence in this observation (0-1)"
    )


class NextActionPlan(BaseModel):
    """The model's plan for the next UI action, derived from PageObservation.

    Captures the selector-with-coordinate fallback pattern: prefer a CSS/text
    selector; fall back to pixel coordinates for unlabeled/visual elements
    (the primary win over OCR-only navigation).
    """

    action_type: Literal["click", "type", "scroll", "navigate", "wait", "none"] = Field(
        ..., description="Category of the next action"
    )
    selector: str | None = Field(
        None, description="CSS selector or visible text label for the target element"
    )
    value: str | None = Field(
        None, description="Text to type or URL to navigate to (if applicable)"
    )
    coordinates: dict[str, int] | None = Field(
        None,
        description="Pixel coordinates {x, y} — used when no selector is available (visual targets)",
    )
    reasoning: str = Field(..., description="Why this action is the correct next step")
    expected_outcome: str = Field(
        ...,
        description="What the screen should look like after this action (used for self-correction)",
    )
    confidence: float = Field(
        0.5, ge=0.0, le=1.0, description="Model confidence in this plan (0-1)"
    )


class VisionReflection(BaseModel):
    """Combined observation + plan produced by the structured reflection step."""

    observation: PageObservation
    plan: NextActionPlan


# Export all public symbols
__all__ = [
    "TaskStatus",
    "CodeChange",
    "BashCommand",
    "ValidationResult",
    "WeebotOutput",
    "OutputParseError",
    "parse_agent_output",
    "GoalSpec",
    "GoalDecomposition",
    "IdeaProposal",
    "IdeaProposalList",
    "HarnessEditProposal",
    "EvaluatorPromptImprovement",
    "EditSelection",
    "SubtaskSpec",
    "SubtaskDecomposition",
    "SubtaskPlan",
    "SkillEditSpec",
    "SkillEditList",
    "GuidanceContent",
    "RetentionVerdictPayload",
    "SynthesisPayload",
    "parse_structured",
    "extract_json_text",
    "create_system_prompt",
    "STRUCTURED_OUTPUT_PROMPT",
    # Verbalized Sampling
    "SampledResponse",
    "SampledDistribution",
    "parse_sampled_distribution",
    "VS_PROMPT_FILENAME",
    "VS_FALLBACK_PROMPT",
    # Vision reflection (Phase 2)
    "PageObservation",
    "NextActionPlan",
    "VisionReflection",
]
