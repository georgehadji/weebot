"""TruthBinder — deterministic response-layer guard service.

Five checks, all deterministic (no LLM):

1. URL Substitution      — links match actual navigation trace
2. Action Announcer      — claims match ToolEvent history
3. Response Grounder     — success claims include concrete outputs
4. Schedule Honesty      — no phantom follow-up promises
5. Prompt-Leak Redaction — system prompt fragments in user-facing text
"""
from __future__ import annotations

import logging
import re
from typing import Any

from weebot.domain.models.event import (
    AgentEvent,
    MessageEvent,
    ToolEvent,
    ToolStatus,
)
from weebot.domain.models.truth_binding import (
    TruthBindingResult,
    TruthCheck,
    TruthViolation,
)

logger = logging.getLogger(__name__)

# ── Known system prompt fragments that must never appear in user output ──
_KNOWN_PROMPT_FRAGMENTS: list[re.Pattern] = [
    re.compile(r"<identity>.*?</identity>", re.DOTALL),
    re.compile(r"You are Reasonix Code", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"# System Prompt", re.IGNORECASE),
    re.compile(r"## Constraints", re.IGNORECASE),
    re.compile(r"You are an AI assistant", re.IGNORECASE),
]

# ── Phrases indicating concrete output ──
_CONCRETE_OUTPUT_PATTERNS = [
    re.compile(r"(?:saved|wrote|created|updated)\s+(?:to\s+)?`?[\w./\\_-]+`?"),
    re.compile(r"(?:result|output|findings?)\s*:?\s*\S+"),
    re.compile(r"https?://\S+"),
    re.compile(r"`[\w./\\_-]+`"),
    re.compile(r"\d+\.\s+\S+"),  # Numbered list items
]

# ── Schedule-promise phrases ──
_SCHEDULE_PROMISE_PATTERNS = [
    re.compile(r"I['']ll\s+(?:check|monitor|watch|follow\s+up)", re.IGNORECASE),
    re.compile(r"(?:let me|I will)\s+(?:check|monitor)\s+(?:back|in|again)", re.IGNORECASE),
    re.compile(r"(?:keep\s+(?:an?\s+)?eye|stay\s+tuned)", re.IGNORECASE),
]


class TruthBinder:
    """Deterministic response validator — no LLM in the policy path.

    Wraps 5 portable, auditable checks and applies them to every
    assistant response before it reaches the user.
    """

    # ── Check definitions (metadata only, logic is in bind()) ──
    CHECKS: list[TruthCheck] = [
        TruthCheck(
            name="url_substitution",
            description="Links that don't match actual navigation trace",
            severity="block",
        ),
        TruthCheck(
            name="action_announcer",
            description="LLM claiming it did X when no ToolEvent for X exists",
            severity="rewrite",
        ),
        TruthCheck(
            name="response_grounder",
            description="Vague success claims without concrete output",
            severity="warn",
        ),
        TruthCheck(
            name="schedule_honesty",
            description="LLM promising follow-up it can't deliver",
            severity="block",
        ),
        TruthCheck(
            name="prompt_leak_redaction",
            description="System prompt fragments leaking into user response",
            severity="block",
        ),
    ]

    def __init__(self, strictness: str = "normal") -> None:
        """Initialize the binder.

        Args:
            strictness: 'normal' (default) or 'strict' — controls whether
                        'warn' severity violations block or just log.
        """
        self._strictness = strictness

    # ── Public API ──────────────────────────────────────────────────

    async def bind(self, response: str, context: dict[str, Any]) -> TruthBindingResult:
        """Run all checks on *response*.

        Args:
            response: The agent's text response.
            context: Dict with at least:
                - 'session_events': list[AgentEvent] from the current session
                - 'step': current step dict/object (optional)
                - 'facts': extracted facts (optional)

        Returns:
            TruthBindingResult with all violations and potentially rewritten text.
        """
        violations: list[TruthViolation] = []
        bound = response

        # 1. URL Substitution
        url_violation = self._check_url_substitution(bound, context)
        if url_violation is not None:
            violations.append(url_violation)
            if url_violation.severity == "block":
                bound = self._redact_urls(bound)

        # 2. Action Announcer
        action_violation = self._check_action_announcer(bound, context)
        if action_violation is not None:
            violations.append(action_violation)
            if action_violation.severity == "rewrite":
                bound = self._rewrite_unsubstantiated_claims(bound, context)

        # 3. Response Grounder
        ground_violation = self._check_response_grounder(bound, context)
        if ground_violation is not None:
            violations.append(ground_violation)

        # 4. Schedule Honesty
        schedule_violation = self._check_schedule_honesty(bound, context)
        if schedule_violation is not None:
            violations.append(schedule_violation)
            if schedule_violation.severity == "block":
                bound = self._strip_schedule_promises(bound)

        # 5. Prompt-Leak Redaction
        leak_violation = self._check_prompt_leak(bound)
        if leak_violation is not None:
            violations.append(leak_violation)
            bound = self._redact_prompt_fragments(bound)

        passed = not any(
            v.severity == "block"
            or (v.severity == "warn" and self._strictness == "strict")
            for v in violations
        )

        return TruthBindingResult(
            passed=passed,
            original_text=response,
            bound_text=bound,
            violations=violations,
        )

    # ── Check 1: URL Substitution ───────────────────────────────────

    def _check_url_substitution(
        self, text: str, context: dict[str, Any]
    ) -> TruthViolation | None:
        """Verify URLs in the response match the actual navigation trace."""
        urls_in_response = re.findall(r"https?://\S+", text)
        if not urls_in_response:
            return None

        # Collect actually visited URLs from ToolEvents
        visited_urls = set()
        events = context.get("session_events", [])
        for event in events:
            if isinstance(event, ToolEvent) and event.tool_name in (
                "advanced_browser", "web_search", "browser_inspector"
            ):
                args = event.function_args or {}
                url = args.get("url") or args.get("query") or ""
                if url:
                    visited_urls.add(url)

        unvisited = [u for u in urls_in_response if not any(
            v in u for v in visited_urls
        )]
        if unvisited:
            return TruthViolation(
                check="url_substitution",
                message=f"Response contains URLs not in navigation trace: {unvisited}",
                severity="block",
            )
        return None

    # ── Check 2: Action Announcer ───────────────────────────────────

    def _check_action_announcer(
        self, text: str, context: dict[str, Any]
    ) -> TruthViolation | None:
        """Verify claimed actions match actual ToolEvent history."""
        # Action verbs that LLMs commonly over-claim
        action_verbs = [
            "searched", "researched", "browsed", "navigated", "visited",
            "downloaded", "extracted", "compiled", "generated", "created",
            "analyzed", "compared", "summarized", "reviewed", "inspected",
            "verified", "validated", "tested", "ran", "executed",
        ]

        actual_tools = set()
        events = context.get("session_events", [])
        for event in events:
            if isinstance(event, ToolEvent) and event.status == ToolStatus.CALLED:
                actual_tools.add(event.tool_name)

        # Map tool names to action verbs they support
        tool_verb_map: dict[str, set[str]] = {
            "web_search": {"searched", "researched", "looked"},
            "advanced_browser": {"browsed", "navigated", "visited"},
            "bash": {"ran", "executed", "downloaded"},
            "python_execute": {"ran", "executed", "generated"},
            "file_editor": {"created", "updated", "edited"},
        }

        claimed_actions: list[str] = []
        for verb in action_verbs:
            pattern = re.compile(rf"\b{verb}\b", re.IGNORECASE)
            if pattern.search(text):
                claimed_actions.append(verb)

        if not claimed_actions:
            return None

        # Check each claimed action against actual tools
        unsubstantiated: list[str] = []
        for claimed in claimed_actions:
            supported = False
            for tool, verbs in tool_verb_map.items():
                if claimed in verbs and tool in actual_tools:
                    supported = True
                    break
            if not supported:
                unsubstantiated.append(claimed)

        if unsubstantiated:
            return TruthViolation(
                check="action_announcer",
                message=f"Response claims actions without matching ToolEvents: {unsubstantiated}",
                severity="rewrite",
            )
        return None

    # ── Check 3: Response Grounder ──────────────────────────────────

    def _check_response_grounder(
        self, text: str, context: dict[str, Any]
    ) -> TruthViolation | None:
        """Check that success claims include concrete output."""
        # Only check sentences that start with success claims
        success_pattern = re.compile(
            r"(?:successfully|done|complete|finished|ready)\s*[:\.]",
            re.IGNORECASE,
        )
        if not success_pattern.search(text):
            return None

        # If no concrete output patterns found, flag it
        for pattern in _CONCRETE_OUTPUT_PATTERNS:
            if pattern.search(text):
                return None

        return TruthViolation(
            check="response_grounder",
            message="Success claim lacks concrete output (file paths, URLs, or values)",
            severity="warn",
        )

    # ── Check 4: Schedule Honesty ───────────────────────────────────

    def _check_schedule_honesty(
        self, text: str, context: dict[str, Any]
    ) -> TruthViolation | None:
        """Block promises the agent can't deliver without a schedule tool."""
        for pattern in _SCHEDULE_PROMISE_PATTERNS:
            if pattern.search(text):
                # Check if a schedule tool was actually called
                has_schedule = any(
                    isinstance(e, ToolEvent) and e.tool_name == "schedule"
                    for e in context.get("session_events", [])
                )
                if not has_schedule:
                    return TruthViolation(
                        check="schedule_honesty",
                        message="Response promises follow-up without a schedule tool call",
                        severity="block",
                    )
        return None

    # ── Check 5: Prompt-Leak Redaction ──────────────────────────────

    def _check_prompt_leak(self, text: str) -> TruthViolation | None:
        """Detect system prompt fragments leaking into the user response."""
        for pattern in _KNOWN_PROMPT_FRAGMENTS:
            if pattern.search(text):
                return TruthViolation(
                    check="prompt_leak_redaction",
                    message="System prompt fragment detected in user-facing response",
                    severity="block",
                )
        return None

    # ── Remediation helpers ─────────────────────────────────────────

    @staticmethod
    def _redact_urls(text: str) -> str:
        """Replace unverified URLs with a placeholder."""
        return re.sub(r"https?://\S+", "[URL REDACTED — not in navigation trace]", text)

    @staticmethod
    def _rewrite_unsubstantiated_claims(text: str, context: dict[str, Any]) -> str:
        """Strip or rephrase unsubstantiated action claims."""
        # Simple strategy: prefix with hedging language on specific claims
        lines = text.split("\n")
        rewritten: list[str] = []
        for line in lines:
            if re.search(r"\b(searched|researched|browsed|navigated)\b", line, re.IGNORECASE):
                rewritten.append(f"_Note: {line.strip()}")
            else:
                rewritten.append(line)
        return "\n".join(rewritten)

    @staticmethod
    def _strip_schedule_promises(text: str) -> str:
        """Remove or rewrite phantom schedule promises."""
        result = text
        for pattern in _SCHEDULE_PROMISE_PATTERNS:
            result = pattern.sub("[follow-up not scheduled]", result)
        return result

    @staticmethod
    def _redact_prompt_fragments(text: str) -> str:
        """Replace known prompt fragments with a safe marker."""
        result = text
        for pattern in _KNOWN_PROMPT_FRAGMENTS:
            result = pattern.sub("[REDACTED — internal prompt fragment]", result)
        return result
