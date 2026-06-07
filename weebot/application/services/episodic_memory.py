"""Episodic memory — long-term semantic retrieval of past session summaries."""
from __future__ import annotations

from typing import Any, Callable, Coroutine, List, Optional, Tuple

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.summary_repo_port import SummaryRepositoryPort
from weebot.domain.models.session import Session


Embedder = Callable[[str], List[float]] | Callable[[str], Coroutine[Any, Any, List[float]]]


class EpisodicMemory:
    """Generates session summaries, stores embeddings, and retrieves similar past sessions."""

    def __init__(
        self,
        summary_repo: SummaryRepositoryPort,
        llm: Optional[LLMPort] = None,
        embedder: Optional[Embedder] = None,
        model: Optional[str] = None,
    ) -> None:
        self._repo = summary_repo
        self._llm = llm
        self._embedder = embedder
        self._model = model

    async def summarize_session(self, session: Session) -> str:
        """Generate a concise summary of the session using the LLM."""
        if not session.events:
            return "Empty session."
        if self._llm is None:
            # Fallback: concatenate event types
            types = [ev.type for ev in session.events]
            return f"Session contained events: {', '.join(types)}."

        prompt = (
            "Summarize the following session events in one concise paragraph. "
            "Focus on the goal, key actions taken, and final outcome.\n\n"
        )
        for ev in session.events:
            prompt += f"- {ev.type}: {getattr(ev, 'message', getattr(ev, 'description', str(ev)))}\n"

        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model=self._model,
            temperature=TEMPERATURE_BALANCED,
        )
        return response.content or "Session summary unavailable."

    async def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for the given text."""
        if self._embedder is None:
            # Fallback: simple character-frequency hash vector (deterministic, 64-dim)
            vec = [0.0] * 64
            for i, ch in enumerate(text):
                vec[i % 64] += ord(ch)
            norm = sum(x * x for x in vec) ** 0.5
            if norm > 0:
                vec = [x / norm for x in vec]
            return vec

        result = self._embedder(text)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def store_session(self, session: Session) -> str:
        """Summarize, embed, and persist a session. Returns the summary."""
        summary = await self.summarize_session(session)
        embedding = await self.embed(summary)
        await self._repo.save_summary(session.id, summary, embedding)
        return summary

    async def find_similar_sessions(
        self,
        query: str,
        k: int = 3,
    ) -> List[Tuple[str, str, float]]:
        """Find top-k sessions similar to the query text."""
        embedding = await self.embed(query)
        return await self._repo.find_similar(embedding, k=k)

    async def get_few_shot_examples(self, query: str, k: int = 3) -> str:
        """Return a formatted block of few-shot examples from similar sessions."""
        similar = await self.find_similar_sessions(query, k=k)
        if not similar:
            return ""
        lines = ["### Relevant Past Sessions"]
        for _session_id, summary, score in similar:
            lines.append(f"- (similarity {score:.2f}) {summary}")
        return "\n".join(lines)
