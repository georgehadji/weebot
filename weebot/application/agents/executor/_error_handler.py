"""ErrorHandler — error classification, stuck-loop detection, tool error parsing.

Extracted from the original ExecutorAgent god class to isolate error
classification and recovery routing from step orchestration.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Optional
from dataclasses import dataclass, field

from weebot.core.error_classifier import ErrorClassifier, ErrorCategory

logger = logging.getLogger(__name__)


# Module-level helpers (no self or instance state needed)
# These were originally static methods on ExecutorAgent.

def normalize_text(text: str) -> str:
    """Collapse whitespace and lowercase for comparison."""
    return " ".join(text.lower().split())


_FILE_TOOLS: frozenset = frozenset({
    "file_editor", "write_file", "create_file", "edit_file",
})


def tool_signature(tool_name: str, raw_arguments: str) -> str:
    """Normalize tool call to a stable signature for loop detection.

    Transient keys (vary per invocation without changing tool behaviour)
    are stripped.  However, for file tools, ``path`` is *structural* —
    two file_editor calls on different files are NOT the same operation,
    so ``path`` is preserved for those tools.
    """
    import json
    try:
        args = json.loads(raw_arguments) if raw_arguments else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    # Keys that are always transient
    _transient = {"query", "content", "text", "file_text", "path", "url", "timeout"}
    # For file tools, 'path' is structural — don't strip it
    if tool_name in _FILE_TOOLS:
        _transient.discard("path")
    stable = {k: args[k] for k in sorted(args) if k not in _transient}
    return f"{tool_name}({stable})"


def follow_up_like(text: str) -> bool:
    """Detect non-answer assistant text — empty, confirmation, or meta-responses."""
    t = text.strip().lower()
    if not t:
        return True
    if any(t.startswith(p) for p in ("i don", "i do not", "i cannot", "i'm not", "i am not")):
        return True
    if any(t.startswith(p) for p in ("ok", "okay", "sure", "got it", "understood", "let me", "i'll", "i will")):
        return True
    if len(t) < 20:
        return True
    return False


def parse_args_for_event(raw_arguments: str) -> dict[str, Any]:
    """Parse tool arguments dict for event emission (safe)."""
    import json
    try:
        args = json.loads(raw_arguments) if raw_arguments else {}
        if isinstance(args, dict):
            return {"arg_keys": list(args.keys()), "arg_count": len(args)}
        return {"arg_keys": [], "arg_count": 0}
    except (json.JSONDecodeError, TypeError):
        return {"arg_keys": [], "arg_count": 0}


# TDD/RED/GREEN phase markers that indicate tool failure is expected.
# GREEN phases are included because the planner may create deliberate
# test bugs (the test should fail on first run, then be fixed).
_TDD_EXPECTED_FAILURE_MARKERS: frozenset = frozenset({
    "RED-VERIFY", "red-verify",
    "[RED]", "[RED-VERIFY]",
    "[GREEN]", "[GREEN-VERIFY]",
    "tests fail", "confirm all tests FAIL",
    "tests should fail", "expected failure",
    "ImportError expected", "NameError expected",
    "deliberate", "DELIBERATELY",
})


def is_expected_failure(step_description: str) -> bool:
    """Return True if tool failure is expected for this TDD/RED phase step.

    The planner signals TDD phases with ``[RED-VERIFY]`` or ``[RED]``
    prefixes and instructions like "confirm all tests FAIL".  When
    the executor runs ``pytest`` during these phases, a non-zero exit
    code is the DESIRED outcome — not an error.
    """
    if not step_description:
        return False
    desc_lower = step_description.lower()
    for marker in _TDD_EXPECTED_FAILURE_MARKERS:
        if marker.lower() in desc_lower:
            return True
    return False


def classify_tool_error(error_output: str) -> Optional[str]:
    """Classify a tool error into a stable error-class key, or None if no match.

    Uses exact same logic as the original ExecutorAgent._classify_tool_error
    to preserve test compatibility.
    """
    if not error_output:
        return None
    lo = error_output.lower()
    if "requires user confirmation" in lo:
        return "confirmation_required"
    if "denied by policy" in lo or "command blocked" in lo:
        return "policy_denied"
    if "security error" in lo or ("layer" in lo and "triggered" in lo):
        return "security_blocked"
    if "timed out" in lo:
        return "timeout"
    if "access denied" in lo or "permission" in lo:
        return "permission_denied"
    return None


# ── Instance-based error state for stuck-loop detection ─────────────────

@dataclass
class ExecutionLoopState:
    """Tracks the current step's execution loop state for stuck detection."""
    last_tool_signature: Optional[str] = None
    recent_tool_signatures: deque[str] = field(default_factory=lambda: deque(maxlen=6))
    same_tool_repeat_count: int = 0
    follow_up_count: int = 0
    loop_error: Optional[str] = None

    def record_tool_call(self, tool_name: str, raw_arguments: str) -> str:
        """Record a tool call and return its stable signature."""
        sig = tool_signature(tool_name, raw_arguments)
        self.recent_tool_signatures.append(sig)
        if sig == self.last_tool_signature:
            self.same_tool_repeat_count += 1
        else:
            self.same_tool_repeat_count = 0
        self.last_tool_signature = sig
        return sig

    def record_follow_up(self) -> None:
        """Increment the follow-up (non-answer) counter."""
        self.follow_up_count += 1


# ── Stuck-error builder ────────────────────────────────────────────────

def build_stuck_error(
    step: Any,
    reason: str,
    recent_signatures: list[str],
    max_steps: int,
) -> str:
    """Build a human-readable stuck-loop error message."""
    recent = list(recent_signatures)[-3:]
    recent_block = " | ".join(recent) if recent else "none"
    return (
        f"Step '{step.id}' ('{step.description}') got stuck: {reason}. "
        f"Recent tool calls: {recent_block}. "
        f"Guardrails triggered before/at max step budget ({max_steps}). "
        "Recovery: flow should replan this step or request missing user input."
    )
