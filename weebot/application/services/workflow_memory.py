"""Agent Workflow Memory (AWM) — induces reusable workflow templates from completed sessions.

Based on the paper "Fundamentals of Building Autonomous LLM Agents" (arXiv:2510.09244v1),
§5.3 — Agent Workflow Memory (AWM): "induces commonly reused routines (workflows) from
training examples and then selectively provides these workflows to the agent to guide
subsequent generations."

Usage:
    awm = AgentWorkflowMemory(llm=llm_port)

    # After a session completes, induce a workflow template
    template = await awm.induce(session)
    await awm.store(template)

    # When planning a new task, query for relevant templates
    templates = await awm.query(task_description="build a hero banner website")
    # templates[0].generalized_steps -> list of abstract step descriptions
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.models.event import AgentEvent, StepEvent, PlanEvent
from weebot.domain.models.plan import Plan, Step
from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

# ── Data model ───────────────────────────────────────────────────────────

class WorkflowTemplate:
    """A generalized workflow induced from one or more similar sessions.

    Attributes:
        task_summary: Short human-readable description of the task type.
        generalized_steps: List of abstract step descriptions (no file paths,
                           no specific URLs — just the action pattern).
        source_session_ids: Session IDs that contributed to this template.
        success_rate: Fraction (0.0–1.0) of sessions using this template
                      that completed successfully.
        use_count: Number of times this template has been applied.
        created_at: ISO-8601 timestamp.
        last_used_at: ISO-8601 timestamp of most recent application.
    """
    def __init__(
        self,
        task_summary: str,
        generalized_steps: list[str],
        source_session_ids: Optional[list[str]] = None,
        success_rate: float = 0.0,
        use_count: int = 0,
        created_at: Optional[str] = None,
        last_used_at: Optional[str] = None,
    ) -> None:
        self.task_summary = task_summary
        self.generalized_steps = generalized_steps
        self.source_session_ids = source_session_ids or []
        self.success_rate = success_rate
        self.use_count = use_count
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.last_used_at = last_used_at or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_summary": self.task_summary,
            "generalized_steps": self.generalized_steps,
            "source_session_ids": self.source_session_ids,
            "success_rate": self.success_rate,
            "use_count": self.use_count,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowTemplate":
        return cls(**data)

    def __repr__(self) -> str:
        return (
            f"WorkflowTemplate(summary={self.task_summary!r}, "
            f"steps={len(self.generalized_steps)}, "
            f"success_rate={self.success_rate:.0%}, "
            f"uses={self.use_count})"
        )


# ── Agent Workflow Memory ─────────────────────────────────────────────────

class AgentWorkflowMemory:
    """Induces, stores, and retrieves reusable workflow templates.

    This is an in-memory store (T1 implementation).  In a production
    deployment it would back onto a vector DB or SQLite with embedding
    search — see T2.
    """

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm
        self._templates: list[WorkflowTemplate] = []

    # ── Induction ─────────────────────────────────────────────────────────

    async def induce(self, session: Session) -> Optional[WorkflowTemplate]:
        """Extract a generalized workflow template from a completed session.

        Uses an LLM call to generalize the session's plan + events into
        reusable step descriptions.  Returns None if the session has no
        plan or has too few completed steps to generalize.

        Args:
            session: A completed or failed Session with at least one plan.

        Returns:
            WorkflowTemplate or None if induction is not possible.
        """
        if session.status == SessionStatus.PENDING or session.status == SessionStatus.RUNNING:
            return None

        plan = session.get_last_plan()
        if plan is None or not plan.steps:
            logger.debug("AWM: no plan in session %s — skipping", session.id)
            return None

        # Count completed vs failed steps
        completed = sum(1 for s in plan.steps if s.status and s.status.name == "COMPLETED")
        if completed < 2:
            logger.debug("AWM: only %d completed steps in session %s — skipping", completed, session.id)
            return None

        # Build a compact task description for the LLM
        task = self._build_task_context(session, plan)
        success_rate = completed / max(len(plan.steps), 1)

        # LLM call to generalize
        generalized = await self._generalize_steps(task, plan)
        if not generalized:
            return None

        template = WorkflowTemplate(
            task_summary=generalized["summary"],
            generalized_steps=generalized["steps"],
            source_session_ids=[session.id],
            success_rate=success_rate,
            use_count=0,
        )
        logger.info("AWM: induced workflow from session %s: %s", session.id, template)
        return template

    @staticmethod
    def _build_task_context(session: Session, plan: Plan) -> str:
        """Build a compact task description for LLM context."""
        # Prefer the original task from session context, fall back to plan title
        task_text = session.context.original_task or session.title or plan.title or ""
        if len(task_text) > 500:
            task_text = task_text[:500] + "…"
        return task_text

    async def _generalize_steps(self, task: str, plan: Plan) -> Optional[dict[str, Any]]:
        """LLM call: generalize concrete plan steps into abstract workflow steps.

        Returns dict with keys "summary" and "steps", or None on failure.
        """
        steps_text = "\n".join(
            f"  {i+1}. {s.description or '(no description)'}"
            for i, s in enumerate(plan.steps)
        )

        prompt = (
            "You are a workflow analyst. Given a task description and concrete steps, "
            "generalize them into reusable abstract steps.\n\n"
            f"Task: {task}\n\n"
            f"Concrete steps:\n{steps_text}\n\n"
            "Respond with JSON: {\"summary\": \"short task type summary (max 10 words)\", "
            "\"steps\": [\"generalized step 1\", \"generalized step 2\", ...]}\n\n"
            "Rules:\n"
            "- Remove file paths, URLs, and specific values.\n"
            "- Keep the action pattern (e.g. 'implement the feature' → 'implement feature').\n"
            "- At most 8 steps.\n"
            "- Each step is 3-10 words, imperative mood."
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            text = response.content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ValueError("response is not a dict")
            summary = str(result.get("summary", ""))[:80]
            steps = [str(s)[:100] for s in result.get("steps", [])]
            if not summary or len(steps) < 2:
                raise ValueError("insufficient summary or steps")
            return {"summary": summary, "steps": steps}
        except Exception as exc:
            logger.warning("AWM: LLM generalization failed for task %s: %s", task[:60], exc)
            return None

    # ── Storage ───────────────────────────────────────────────────────────

    async def store(self, template: WorkflowTemplate) -> None:
        """Store a workflow template.

        If a template with the same task_summary already exists (fuzzy match,
        first 60 chars), merge by:
        - Extending the generalized steps list with LLM consolidation
        - Averaging success_rate
        - Incrementing use_count
        - Appending source_session_ids
        """
        existing = self._find_similar(template.task_summary, threshold=0.7)
        if existing:
            await self._merge(existing, template)
            logger.debug("AWM: merged into existing template: %s", existing)
        else:
            self._templates.append(template)
            logger.debug("AWM: stored new template: %s", template)

    async def query(
        self,
        task_description: str,
        max_results: int = 3,
    ) -> list[WorkflowTemplate]:
        """Find the most relevant workflow templates for a task description.

        Uses simple keyword overlap as a lightweight retrieval strategy.
        A production version would use embedding similarity (T2).

        Args:
            task_description: The user's task description or the plan prompt.
            max_results: Maximum number of templates to return.

        Returns:
            List of WorkflowTemplate, sorted by relevance descending.
        """
        if not self._templates:
            return []

        query_tokens = self._tokenize(task_description)
        scored: list[tuple[float, WorkflowTemplate]] = []

        for template in self._templates:
            summary_tokens = self._tokenize(template.task_summary)
            steps_tokens = self._tokenize(" ".join(template.generalized_steps))
            all_tokens = summary_tokens | steps_tokens

            if not all_tokens:
                continue

            overlap = len(query_tokens & all_tokens)
            score = overlap / max(len(all_tokens), 1)

            # Boost by success_rate and recency
            score *= 0.5 + 0.5 * template.success_rate
            scored.append((score, template))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:max_results] if _ > 0]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Tokenize text into lowercase word stems."""
        words = re.findall(r"[a-z]+", text.lower())
        # Remove very common English stop words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "has", "have", "had", "do", "does", "did", "will", "would",
            "can", "could", "to", "of", "in", "on", "at", "for", "with",
            "by", "from", "this", "that", "and", "or", "but", "not",
            "it", "its", "you", "your", "they", "their", "we", "our",
        }
        return {w for w in words if w not in stop_words and len(w) > 2}

    def _find_similar(self, summary: str, threshold: float = 0.7) -> Optional[WorkflowTemplate]:
        """Find an existing template with similar summary."""
        tokens = self._tokenize(summary)
        for template in self._templates:
            existing_tokens = self._tokenize(template.task_summary)
            if not tokens or not existing_tokens:
                continue
            overlap = len(tokens & existing_tokens)
            union = len(tokens | existing_tokens)
            if union > 0 and overlap / union >= threshold:
                return template
        return None

    async def _merge(self, target: WorkflowTemplate, incoming: WorkflowTemplate) -> None:
        """Merge an incoming template into an existing one."""
        # Append new source sessions
        for sid in incoming.source_session_ids:
            if sid not in target.source_session_ids:
                target.source_session_ids.append(sid)

        # Weighted-average success rate
        total = target.use_count + incoming.use_count + 1
        target.success_rate = (
            target.success_rate * (target.use_count + 1) +
            incoming.success_rate * (incoming.use_count + 1)
        ) / total

        target.use_count += 1
        target.last_used_at = datetime.now(timezone.utc).isoformat()

        # Extend steps with any new ones from incoming
        existing_set = set(s.strip().lower() for s in target.generalized_steps)
        for step in incoming.generalized_steps:
            if step.strip().lower() not in existing_set:
                target.generalized_steps.append(step)

    def get_all(self) -> list[WorkflowTemplate]:
        """Return all stored templates (for inspection/debugging)."""
        return list(self._templates)

    def count(self) -> int:
        return len(self._templates)
