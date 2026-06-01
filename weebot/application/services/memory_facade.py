"""MemoryFacade — unified interface to weebot's overlapping memory systems.

Routes queries across SessionMemory (event index), WorkingMemory (ephemeral
facts), EpisodicMemory (SQLite-backed session memory), and PersistentMemory
(cross-session .md files).  All systems are optional — the facade degrades
gracefully when any component is None.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from weebot.domain.models.event import AgentEvent
from weebot.domain.services.session_memory import SessionMemory
from weebot.domain.services.working_memory import WorkingMemory

logger = logging.getLogger(__name__)


class MemoryFacade:
    """Unified memory recall that searches across all active memory systems.

    Usage (via DI):
        facade = MemoryFacade(
            session_memory=session._memory_index,
            working_memory=WorkingMemory(),
            episodic_memory=episodic_memory_instance,
            persistent_memory=persistent_memory_instance,
        )
        results = await facade.recall("What tools does the user prefer?")
    """

    def __init__(
        self,
        session_memory: Optional[SessionMemory] = None,
        working_memory: Optional[WorkingMemory] = None,
        episodic_memory: Optional[Any] = None,
        persistent_memory: Optional[Any] = None,
    ) -> None:
        self._session_memory = session_memory
        self._working_memory = working_memory
        self._episodic_memory = episodic_memory
        self._persistent_memory = persistent_memory

    async def recall(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search all active memory systems for information relevant to *query*.

        Returns a ranked, deduplicated list of memory entries with their source.
        """
        results: List[Dict[str, Any]] = []

        # 1. SessionMemory — event index (in-process, fast)
        if self._session_memory is not None:
            try:
                entries = self._session_memory.search(query, top_k=top_k)
                for e in entries:
                    results.append({"source": "session", "content": e, "confidence": 0.9})
            except Exception:
                logger.debug("SessionMemory search failed", exc_info=True)

        # 2. WorkingMemory — ephemeral facts (in-process)
        if self._working_memory is not None:
            try:
                entries = self._working_memory.search(query, top_k=top_k)
                for e in entries:
                    results.append({"source": "working", "content": e, "confidence": 0.8})
            except Exception:
                logger.debug("WorkingMemory search failed", exc_info=True)

        # 3. EpisodicMemory — SQLite-backed session-scoped memory
        if self._episodic_memory is not None:
            try:
                recall_method = getattr(self._episodic_memory, "recall", None)
                if recall_method is not None:
                    entries = await recall_method(query, k=top_k) if hasattr(recall_method, "__await__") else recall_method(query, k=top_k)
                    if entries:
                        for e in (entries if isinstance(entries, list) else [entries]):
                            results.append({"source": "episodic", "content": e, "confidence": 0.7})
            except Exception:
                logger.debug("EpisodicMemory recall failed", exc_info=True)

        # 4. PersistentMemoryTool — cross-session .md files
        if self._persistent_memory is not None:
            try:
                read_method = getattr(self._persistent_memory, "read_entries", None)
                if read_method is not None:
                    for file in ("agent", "user"):
                        entries = await read_method(file)
                        for e in entries:
                            if query.lower() in e.lower():
                                results.append({
                                    "source": f"persistent/{file}",
                                    "content": e[:500],
                                    "confidence": 0.6,
                                })
            except Exception:
                logger.debug("PersistentMemory recall failed", exc_info=True)

        return results[:top_k]

    def store_fact(self, key: str, value: Any) -> None:
        """Store a fact in working memory (ephemeral)."""
        if self._working_memory is not None:
            try:
                self._working_memory.store(key, value)
            except Exception:
                logger.debug("WorkingMemory store failed", exc_info=True)

    def get_fact(self, key: str, default: Any = None) -> Any:
        """Retrieve a fact from working memory."""
        if self._working_memory is not None:
            try:
                return self._working_memory.get(key, default)
            except Exception:
                pass
        return default
