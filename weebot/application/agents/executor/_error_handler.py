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


def tool_signature(tool_name: str, raw_arguments: str) -> str:
    """Normalize tool call to a stable signature for loop detection."""
    import json
    try:
        args = json.loads(raw_arguments) if raw_arguments else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    # Keep only the keys that affect tool behaviour, not transient values
    stable = {k: args[k] for k in sorted(args) if k not in ("query", "content", "path", "url", "timeout")}
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
