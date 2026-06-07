"""BehavioralLearner — automatic rule extraction from user corrections.

Monitors WaitForUserEvent answers and SteeringEvent messages for
correction patterns. Extracts persistent rules via a cheap LLM call
and stores them for injection into future executor prompts.

Correction keywords: "don't", "never", "instead", "stop", "wrong",
"shouldn't", "incorrect", "next time"
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from weebot.application.ports.behavioral_learner_port import BehavioralLearnerPort
from weebot.domain.models.behavioral_rule import BehavioralRule

logger = logging.getLogger(__name__)

# Correction keywords that trigger rule extraction
_CORRECTION_PATTERNS = [
    re.compile(r"\b(?:don'?t|do not|never|shouldn'?t|stop)\b", re.IGNORECASE),
    re.compile(r"\binstead\b", re.IGNORECASE),
    re.compile(r"\b(?:wrong|incorrect|incorrectly)\b", re.IGNORECASE),
    re.compile(r"\bnext time\b", re.IGNORECASE),
    re.compile(r"\b(?:avoid|refrain)\b", re.IGNORECASE),
]


class BehavioralLearner(BehavioralLearnerPort):
    """Automatic behavioral rule extraction service.

    Detects correction patterns in user messages, extracts rules via
    a lightweight LLM call, and stores them for future prompt injection.

    Uses a simple keyword heuristic as pre-filter before calling the LLM
    to minimize cost.
    """

    def __init__(
        self,
        llm: Any = None,  # Optional LLMPort for rule extraction
        min_corrections_for_rule: int = 1,
        store: Optional[list[BehavioralRule]] = None,
        state_repo: Optional[Any] = None,
    ) -> None:
        """Initialize the learner.

        Args:
            llm: Optional LLMPort for rule extraction. If None, uses
                 simple keyword-based extraction (less accurate).
            min_corrections_for_rule: Minimum corrections on the same
                topic before auto-extracting a rule. Default 1.
            store: In-memory rule store (used when state_repo is None).
            state_repo: Optional SQLiteStateRepository for persistent storage.
        """
        self._llm = llm
        self._min_corrections = min_corrections_for_rule
        self._store = store or []
        self._state_repo = state_repo
        self._recent_corrections: dict[str, int] = {}  # topic -> count

    # ── Public API ──────────────────────────────────────────────────

    async def learn_from_correction(
        self, user_message: str, context: dict[str, Any]
    ) -> Optional[BehavioralRule]:
        """Extract a behavioral rule from a user correction.

        Args:
            user_message: The user's message text.
            context: Dict with 'step_description' and 'tool_name'.

        Returns:
            BehavioralRule if a correction was detected, None otherwise.
        """
        if not self._is_correction(user_message):
            return None

        # Check for minimum correction count on this topic
        topic = self._classify_topic(user_message, context)
        current_count = self._recent_corrections.get(topic, 0) + 1
        self._recent_corrections[topic] = current_count

        if current_count < self._min_corrections:
            logger.info(
                "Correction detected on topic '%s' (%d/%d needed for rule)",
                topic, current_count, self._min_corrections,
            )
            return None

        # Extract the rule
        rule_text = await self._extract_rule(user_message, context)
        if not rule_text:
            return None

        rule = BehavioralRule(
            id=str(uuid4()),
            rule_text=rule_text,
            source_session_id=context.get("session_id", ""),
            source_message=user_message,
            scope=self._determine_scope(rule_text, context),
        )

        self._store.append(rule)
        # Persist to SQLite if available
        if self._state_repo is not None:
            try:
                await self._state_repo.save_behavioral_rule(rule)
            except Exception as save_exc:
                logger.warning("Failed to persist behavioral rule: %s", save_exc)
        logger.info("Learned behavioral rule: %s", rule_text[:80])
        return rule

    async def get_active_rules(self) -> list[BehavioralRule]:
        """Get all active behavioral rules."""
        return list(self._store)

    async def record_application(self, rule: BehavioralRule) -> None:
        """Record that a rule was injected into a system prompt."""
        updated = rule.model_copy(update={
            "applied_count": rule.applied_count + 1,
            "last_applied_at": datetime.now(timezone.utc),
        })
        # Update in store
        for i, r in enumerate(self._store):
            if r.id == rule.id:
                self._store[i] = updated
                break

    def get_rules_for_prompt(self) -> str:
        """Format active rules for injection into a system prompt.

        Returns:
            A string like '# Behavioral Rules\n- Never use ...\n' or empty string.
        """
        if not self._store:
            return ""
        lines = ["# Behavioral Rules"]
        for rule in self._store:
            lines.append(f"- {rule.rule_text}")
        return "\n".join(lines)

    # ── Internal methods ────────────────────────────────────────────

    @staticmethod
    def _is_correction(message: str) -> bool:
        """Quick keyword check — is this message likely a correction?"""
        return any(p.search(message) for p in _CORRECTION_PATTERNS)

    @staticmethod
    def _classify_topic(message: str, context: dict[str, Any]) -> str:
        """Classify the topic of a correction.

        Uses the current step description or tool name as the topic.

        Args:
            message: The user's correction text.
            context: Execution context.

        Returns:
            Topic string for counting corrections.
        """
        step_desc = context.get("step_description", "")
        tool_name = context.get("tool_name", "")
        return tool_name or step_desc or message[:40]

    async def _extract_rule(
        self, user_message: str, context: dict[str, Any]
    ) -> Optional[str]:
        """Extract a one-sentence rule from a correction.

        Uses LLM if available, otherwise falls back to simple extraction.

        Args:
            user_message: The user's correction message.
            context: Execution context.

        Returns:
            Rule text string, or None if extraction failed.
        """
        if self._llm is not None:
            return await self._extract_rule_with_llm(user_message, context)
        return self._extract_rule_heuristic(user_message, context)

    async def _extract_rule_with_llm(
        self, user_message: str, context: dict[str, Any]
    ) -> Optional[str]:
        """Extract rule using an LLM call."""
        step_desc = context.get("step_description", "")
        tool_name = context.get("tool_name", "")

        prompt = (
            f"User said: \"{user_message}\"\n"
            f"Context: agent was executing step \"{step_desc}\" "
            f"and had just called \"{tool_name}\"\n\n"
            "Extract a behavioral rule from this correction. "
            "The rule should be a one-sentence imperative.\n"
            "If the correction is not rule-like (just a normal answer), "
            "respond with 'null'.\n\n"
            "Rule:"
        )

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "You extract concise behavioral rules from user corrections."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=MAX_TOKENS_TINY,
                temperature=TEMPERATURE_PRECISE,
            )
            rule = response.content.strip().strip('"').strip("'")
            return rule if rule.lower() != "null" else None
        except Exception as exc:
            logger.warning("LLM rule extraction failed: %s", exc)
            return self._extract_rule_heuristic(user_message, context)

    @staticmethod
    def _extract_rule_heuristic(
        user_message: str, context: dict[str, Any]
    ) -> Optional[str]:
        """Fallback heuristic rule extraction without LLM.

        Simple keyword-based extraction for when no LLM is available.
        """
        tool_name = context.get("tool_name", "")

        # Check for "don't use X" patterns
        dont_pattern = re.search(
            r"(?:don'?t|never|stop)\s+(?:using\s+|use\s+)?(\w+)",
            user_message, re.IGNORECASE,
        )
        if dont_pattern:
            target = dont_pattern.group(1)
            if tool_name and target.lower() in tool_name.lower():
                return f"Never use {tool_name} for this type of task"
            return f"Never use {target} for this task"

        # Check for "use X instead" patterns
        instead_pattern = re.search(
            r"use\s+(.+?)\s+instead",
            user_message, re.IGNORECASE,
        )
        if instead_pattern:
            alternative = instead_pattern.group(1).strip()
            return f"Use {alternative} instead of {tool_name or 'the current tool'}"

        # Check for "next time" patterns
        next_time_pattern = re.search(
            r"next time[,.].*?(don'?t|do|use|try)\s+(.+?)(?:[.!,]|$)",
            user_message, re.IGNORECASE,
        )
        if next_time_pattern:
            return next_time_pattern.group(0).strip()

        return None

    @staticmethod
    def _determine_scope(rule_text: str, context: dict[str, Any]) -> str:
        """Determine the appropriate scope for a rule.

        Args:
            rule_text: The extracted rule text.
            context: Execution context.

        Returns:
            'global', 'per_skill', or 'per_tool'.
        """
        tool_name = context.get("tool_name", "")
        if tool_name and tool_name in rule_text:
            return "per_tool"
        return "global"
