"""SessionConstraintExtractor — extracts side constraints from user turns.

Implements the extraction half of Wang et al., "Lost in Compaction"
(arXiv:2608.11242) for weebot: a user-issued directive that should govern
*how* the agent works for the rest of the session, distinct from the current
task's content. See weebot.domain.models.session_constraint and
tasks/specs/side_constraint_integrity_plan.md Phase 2.

Tiering mirrors CorrectionTracker's LLM-with-heuristic-fallback strategy: an
LLM call when available (accurate, understands generic-vs-episodic intent),
a regex lexicon otherwise (free, coarse, recall-oriented). Never raises —
extraction failure must never block the agentic loop.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from re import Pattern

from weebot.config.constants import MAX_TOKENS_TINY, TEMPERATURE_PRECISE
from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraint,
    SessionConstraintRegistry,
)

logger = logging.getLogger(__name__)

# Cheapest tier: does this turn even plausibly contain a constraint? A quick
# reject on ordinary task text avoids running the (still cheap, but not
# free) pattern list on every turn.
_TRIGGER_WORDS = re.compile(
    r"(?i)\b(don'?t|never|always|must|should|please\s+don'?t|not|"
    r"from\s+now\s+on|for\s+the\s+rest\s+of|going\s+forward|"
    r"prefer|rather\s+than|instead\s+of|no\s+need\s+to|go\s+ahead|"
    r"before\s+you|wait\s+for|reply\s+in|respond\s+in|end\s+every)\b"
)

# Phrases signalling the constraint WIDENS latitude rather than narrowing it
# (D7 in the plan) — these must never compile into an enforcement gate.
# Deliberately narrow: an ambiguous phrase like "without asking" also shows
# up inside TIGHTEN prohibitions ("never delete files without asking me
# first"), so only unambiguous permission-granting phrasing counts here —
# disambiguating the rest is the LLM tier's job (plan D3).
_LOOSEN_MARKERS = re.compile(
    r"(?i)\b(don'?t\s+(?:need\s+to|have\s+to)\s+ask|"
    r"don'?t\s+ask\s+(?:me\s+)?to\s+confirm|"
    r"no\s+need\s+to\s+(?:ask|confirm)|just\s+do\s+(?:it|them|that)|"
    r"go\s+ahead\s+and|you\s+can\s+just|skip\s+(?:the\s+)?confirmation)\b"
)

# (pattern, kind, default direction). Checked in order; first match per
# sentence wins so more specific patterns should precede general ones.
_HEURISTIC_PATTERNS: list[tuple[Pattern, ConstraintKind, ConstraintDirection]] = [
    # Output — verifiable surface properties of the response.
    (
        re.compile(r"(?i)(?:reply|respond)\s+in\s+([^\n.]+)"),
        ConstraintKind.OUTPUT,
        ConstraintDirection.TIGHTEN,
    ),
    (
        re.compile(r"(?i)end\s+every\s+repl(?:y|ies)\s+with\s+([^\n.]+)"),
        ConstraintKind.OUTPUT,
        ConstraintDirection.TIGHTEN,
    ),
    (
        re.compile(r"(?i)write\s+(?:every\s+)?[\w\s]+\s+as\s+([^\n.]+)"),
        ConstraintKind.OUTPUT,
        ConstraintDirection.TIGHTEN,
    ),
    # Preference — which of several task-equivalent answers to pick.
    (
        re.compile(r"(?i)prefer\s+([^\n.]+?)\s+over\s+([^\n.]+)"),
        ConstraintKind.PREFERENCE,
        ConstraintDirection.TIGHTEN,
    ),
    (
        re.compile(r"(?i)use\s+([^\n.]+?)\s+(?:rather\s+than|not|instead\s+of)\s+([^\n.]+)"),
        ConstraintKind.PREFERENCE,
        ConstraintDirection.TIGHTEN,
    ),
    # Process — how the agent must reach an answer.
    (
        re.compile(r"(?i)always\s+([^\n.]+?)\s+before\s+([^\n.]+)"),
        ConstraintKind.PROCESS,
        ConstraintDirection.TIGHTEN,
    ),
    (
        re.compile(r"(?i)before\s+you\s+answer,?\s+([^\n.]+)"),
        ConstraintKind.PROCESS,
        ConstraintDirection.TIGHTEN,
    ),
    # Action — positively-framed ("show me before you send").
    (
        re.compile(r"(?i)before\s+you\s+(?:run|send|make|do)\s+([^\n.]+)"),
        ConstraintKind.ACTION,
        ConstraintDirection.TIGHTEN,
    ),
    (
        re.compile(r"(?i)wait\s+for\s+my\s+([^\n.]+)"),
        ConstraintKind.ACTION,
        ConstraintDirection.TIGHTEN,
    ),
    # Information — what may be emitted or passed to tools. Checked before
    # the generic Action-negative catch-all below: both would match e.g.
    # "never include my name...", and the first match in this list wins the
    # dedup race, so the more specific kind must come first.
    (
        re.compile(r"(?i)(?:never|don'?t)\s+(?:include|share|expose|write|put)\s+([^\n.]+)"),
        ConstraintKind.INFORMATION,
        ConstraintDirection.TIGHTEN,
    ),
    # Action — negative ("don't/never/forbid ...").
    (
        re.compile(r"(?i)(?:do\s+not|don'?t|never|forbid|prohibit|avoid)\s+([^\n.]+)"),
        ConstraintKind.ACTION,
        ConstraintDirection.TIGHTEN,
    ),
]

_VALID_KINDS = frozenset(k.value for k in ConstraintKind)
_VALID_DIRECTIONS = frozenset(d.value for d in ConstraintDirection)


@dataclass
class ExtractionResult:
    added: list[SessionConstraint]
    revoked_texts: list[str]


class SessionConstraintExtractor:
    """Extracts session-scoped side constraints from a single user turn.

    Args:
        llm: Optional LLMPort for constraint extraction. Falls back to a
            regex lexicon when omitted or when the call fails.
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    async def extract(
        self,
        user_text: str,
        *,
        registry: SessionConstraintRegistry,
        prior_assistant_text: str = "",
        turn_index: int = 0,
    ) -> ExtractionResult:
        """Extract new constraints (and revocations) from *user_text*.

        Never raises — a failure degrades to the heuristic tier, and a
        heuristic failure degrades to no-op, so extraction can never block
        the agentic loop.
        """
        if not user_text or not _TRIGGER_WORDS.search(user_text):
            return ExtractionResult(added=[], revoked_texts=[])

        if self._llm is not None:
            try:
                return await self._extract_with_llm(
                    user_text,
                    registry=registry,
                    prior_assistant_text=prior_assistant_text,
                    turn_index=turn_index,
                )
            except Exception as exc:
                logger.warning("LLM constraint extraction failed: %s", exc)
        return self._extract_heuristic(user_text, turn_index=turn_index)

    # ── Heuristic tier ──────────────────────────────────────────────

    def _extract_heuristic(self, user_text: str, *, turn_index: int) -> ExtractionResult:
        added: list[SessionConstraint] = []
        seen: set[str] = set()
        direction = (
            ConstraintDirection.LOOSEN
            if _LOOSEN_MARKERS.search(user_text)
            else ConstraintDirection.TIGHTEN
        )
        for pattern, kind, default_direction in _HEURISTIC_PATTERNS:
            for match in pattern.finditer(user_text):
                text = match.group(0).strip().rstrip(".!;")
                normalized = text.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                added.append(
                    SessionConstraint(
                        text=text,
                        evidence_span=text,
                        kind=kind,
                        direction=(
                            direction
                            if direction == ConstraintDirection.LOOSEN
                            else default_direction
                        ),
                        turn_index=turn_index,
                    )
                )
        return ExtractionResult(added=added, revoked_texts=[])

    # ── LLM tier ─────────────────────────────────────────────────────

    async def _extract_with_llm(
        self,
        user_text: str,
        *,
        registry: SessionConstraintRegistry,
        prior_assistant_text: str,
        turn_index: int,
    ) -> ExtractionResult:
        active_texts = [c.text for c in registry.active()]
        prompt = (
            "Prior assistant turn (for reference resolution only — do not "
            f"extract constraints from it):\n{prior_assistant_text[:300]}\n\n"
            f"Current user turn:\n{user_text[:600]}\n\n"
            f"Constraints already tracked (for dedup only):\n{active_texts}\n\n"
            "A side constraint governs HOW the agent works for the REST of "
            "the session, not what the current task is. Ask: would this "
            "still apply if the user asked an unrelated question several "
            "turns later? Extract only on a clear yes.\n\n"
            "Exclude: current-task instructions, one-off corrections, "
            "local formatting requests, politeness, background facts.\n\n"
            'Respond with JSON only: {"add": [{"text": "...", '
            '"evidence_span": "...", "kind": "action|information|process|'
            'preference|output", "direction": "tighten|loosen"}], '
            '"revoke": ["<canonical text of a tracked constraint the user '
            'just withdrew>"]}. Most turns produce {"add": [], "revoke": []}.\n'
            "Answer:"
        )
        response = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract generic, session-scoped side constraints "
                        "from a user's message. Most messages contain none."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=MAX_TOKENS_TINY,
            temperature=TEMPERATURE_PRECISE,
        )
        return self._parse_llm_response(response.content, turn_index=turn_index)

    @staticmethod
    def _parse_llm_response(raw: str, *, turn_index: int) -> ExtractionResult:
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            data = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            return ExtractionResult(added=[], revoked_texts=[])

        added: list[SessionConstraint] = []
        for item in data.get("add", []):
            if not isinstance(item, dict) or not item.get("text"):
                continue
            kind = item.get("kind", "").lower()
            direction = item.get("direction", "").lower()
            if kind not in _VALID_KINDS or direction not in _VALID_DIRECTIONS:
                continue
            added.append(
                SessionConstraint(
                    text=str(item["text"]).strip(),
                    evidence_span=str(item.get("evidence_span", item["text"])).strip(),
                    kind=ConstraintKind(kind),
                    direction=ConstraintDirection(direction),
                    turn_index=turn_index,
                )
            )
        revoked = [str(t).strip() for t in data.get("revoke", []) if t]
        return ExtractionResult(added=added, revoked_texts=revoked)
