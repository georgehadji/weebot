"""UserModelConsolidator — periodic 'what we know about the user' pass.

Loads behavioral rules and user memory entries, calls an LLM to distill
a concise user profile, and stores it for injection into the executor
system prompt alongside the raw behavioral rules.

Replaces the stub ``behavioral_rule_consolidation`` cron callback with
real logic.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class UserModelConsolidator:
    """Periodic user-model consolidation.

    Args:
        state_repo: Repository with ``list_behavioral_rules()``,
            ``upsert_memory_metadata()`` methods.
        llm: Optional LLMPort-like object with async ``chat()``.
            When None, consolidation does a simple text merge (no LLM).
    """

    def __init__(self, state_repo: Any, llm: Optional[Any] = None) -> None:
        self._repo = state_repo
        self._llm = llm

    async def consolidate(self) -> str:
        """Run one consolidation pass: load data, distill profile, store it.

        Returns:
            The condensed user profile string.
        """
        # 1. Load behavioral rules
        rules: list[str] = []
        try:
            raw_rules = await self._repo.list_behavioral_rules()
            rules = [r.rule_text for r in raw_rules if r.rule_text]
        except Exception as exc:
            logger.debug("UserModelConsolidator: failed to load rules: %s", exc)

        # 2. Load user memory entries
        memories: list[str] = []
        try:
            low = await self._repo.get_low_salience_entries(threshold=1.0, limit=50)
            for row in low:
                if row.get("source") == "user":
                    txt = row.get("entry_text", "")
                    if txt:
                        memories.append(txt)
        except Exception as exc:
            logger.debug("UserModelConsolidator: failed to load memories: %s", exc)

        # 3. Distill into a profile
        profile = await self._distill(rules, memories)

        # 4. Store the profile as a pinned memory entry
        try:
            import hashlib
            key = hashlib.sha256(b"user_model_profile").hexdigest()[:16]
            await self._repo.upsert_memory_metadata(
                entry_hash=key,
                entry_text=profile[:1000],
                source="user",
                salience=1.0,  # pinned — never evicted
            )
            logger.info("UserModelConsolidator: stored profile (%d chars)", len(profile))
        except Exception as exc:
            logger.debug("UserModelConsolidator: failed to store profile: %s", exc)

        return profile

    async def _distill(self, rules: list[str], memories: list[str]) -> str:
        """Distill rules + memories into a condensed profile string.

        Uses LLM when available; otherwise builds a simple text summary.
        """
        if not rules and not memories:
            return "No user data collected yet."

        input_text = ""
        if rules:
            input_text += "## Behavioral Rules\n" + "\n".join(f"- {r}" for r in rules)
        if memories:
            input_text += "\n## User Memory\n" + "\n".join(f"- {m[:200]}" for m in memories)

        if self._llm is None:
            # Simple merge without LLM
            lines = ["## User Profile", ""]
            if rules:
                lines.append(f"The user has {len(rules)} learned preference(s):")
                lines.extend(f"- {r}" for r in rules)
            if memories:
                lines.append(f"\n{len(memories)} user memory entr(y/ies) recorded.")
            return "\n".join(lines)

        # LLM-backed distillation
        try:
            response = await self._llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a user-modeling assistant. Given behavioral rules "
                                    "and memory entries about a user, produce a 3-5 sentence "
                                    "concise profile summarizing their preferences, work habits, "
                                    "and patterns. Be specific and actionable.",
                    },
                    {"role": "user", "content": input_text[:3000]},
                ],
                temperature=0.3,
                max_tokens=300,
            )
            return (response.content or "").strip()[:1000] or "Profile distillation unavailable."
        except Exception as exc:
            logger.warning("UserModelConsolidator: LLM distillation failed: %s", exc)
            return input_text[:1000]
