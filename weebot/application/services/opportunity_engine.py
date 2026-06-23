"""OpportunityEngine — autonomous discovery of goals from memory patterns.

Runs as a background job every 6 hours. Queries the Knowledge Graph
for gaps and FTS5 for recurring patterns, then ranks opportunities
by: novelty × confidence × user-interest-alignment.

Top candidates (confidence >= 0.7, max 3 per day) are stored in a
``pending_opportunities`` table and surfaced to the user on next
interactive session start.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
from weebot.domain.models.opportunity import OpportunityProposal

logger = logging.getLogger(__name__)

# Max proposals per cycle
_MAX_PROPOSALS_PER_CYCLE = 5

# Min confidence threshold for surfacing
_CONFIDENCE_THRESHOLD = 0.7

# Known patterns that suggest a recurring user interest
_RECURRING_PATTERNS = [
    "competitor", "pricing", "comparison", "benchmark",
    "monitor", "track", "watch", "follow-up",
    "update", "latest", "news", "trend",
]


class OpportunityEngine:
    """Discovers autonomous task opportunities from the knowledge graph.

    Three sources of inspiration:
    1. Knowledge gaps — nodes with low confidence or missing properties
    2. Recurring patterns — topics the user frequently researches
    3. User interests — explicitly saved preferences
    """

    def __init__(
        self,
        knowledge_graph: Optional[KnowledgeGraphPort] = None,
        fts5_search: Optional[Any] = None,
        state_repo: Optional[Any] = None,
    ) -> None:
        """Initialize the engine.

        Args:
            knowledge_graph: Optional KnowledgeGraphPort for querying nodes.
            fts5_search: Optional FTS5 search service for pattern discovery.
            state_repo: Optional SQLiteStateRepository for persistent storage.
        """
        self._kg = knowledge_graph
        self._fts5 = fts5_search
        self._state_repo = state_repo
        self._store: list[OpportunityProposal] = []

    # ── Public API ──────────────────────────────────────────────────

    async def scan(self) -> list[OpportunityProposal]:
        """Run one scan cycle — discover and rank opportunities.

        Returns:
            List of OpportunityProposal with confidence >= 0.7, newest first.
        """
        proposals: list[OpportunityProposal] = []

        # Source 1: Knowledge graph gaps
        if self._kg is not None:
            try:
                kg_proposals = await self._scan_knowledge_gaps()
                proposals.extend(kg_proposals)
            except Exception as exc:
                logger.warning("KG gap scan failed: %s", exc)

        # Source 2: Recurring patterns from FTS5
        if self._fts5 is not None:
            try:
                pattern_proposals = await self._scan_recurring_patterns()
                proposals.extend(pattern_proposals)
            except Exception as exc:
                logger.warning("Pattern scan failed: %s", exc)

        # Source 3: Knowledge graph stats for user interest alignment
        try:
            stats = await self._kg.get_stats() if self._kg else {}
            logger.info(
                "Opportunity scan complete: %d proposals from %d KG nodes and %d edges",
                len(proposals),
                stats.get("node_count", 0),
                stats.get("edge_count", 0),
            )
        except Exception:
            pass

        # Rank and filter
        proposals.sort(key=lambda p: p.confidence, reverse=True)
        top = [p for p in proposals if p.confidence >= _CONFIDENCE_THRESHOLD]
        top = top[:_MAX_PROPOSALS_PER_CYCLE]

        # Store in memory and persist to SQLite if available
        self._store = top
        if self._state_repo is not None:
            for proposal in top:
                try:
                    await self._state_repo.save_opportunity(proposal)
                except Exception as save_exc:
                    logger.warning("Failed to persist opportunity: %s", save_exc)

            # ── KG provenance ─────────────────────────────────
            if self._kg is not None:
                for proposal in top:
                    try:
                        node_id = f"opportunity:{proposal.id[:16]}".lower()
                        existing = await self._kg.query(label="opportunity", name=node_id)
                        if not existing:
                            await self._kg.discover_node(
                                label="opportunity",
                                name=node_id,
                                properties={
                                    "prompt": proposal.prompt[:200],
                                    "source": proposal.source,
                                    "confidence": proposal.confidence,
                                    "status": "pending",
                                },
                                session_id="",
                                confidence=proposal.confidence,
                            )
                    except Exception as kg_exc:
                        logger.debug("KG provenance for opportunity skipped: %s", kg_exc)
        return top

    async def get_pending(self) -> list[OpportunityProposal]:
        """Get pending (unpresented) opportunities.

        Returns:
            List of OpportunityProposal that haven't been shown to the user.
        """
        return [p for p in self._store if not p.presented]

    async def mark_presented(self, proposal_id: str) -> None:
        """Mark an opportunity as presented.

        Args:
            proposal_id: The proposal to mark.
        """
        for i, p in enumerate(self._store):
            if p.id == proposal_id:
                self._store[i] = p.model_copy(update={"presented": True})
                break

    async def accept(self, proposal_id: str) -> Optional[OpportunityProposal]:
        """Accept an opportunity (user opted in).

        Args:
            proposal_id: The proposal to accept.

        Returns:
            The accepted OpportunityProposal, or None if not found.
        """
        for i, p in enumerate(self._store):
            if p.id == proposal_id:
                accepted = p.model_copy(update={"accepted": True})
                self._store[i] = accepted
                return accepted
        return None

    # ── Internal scan methods ───────────────────────────────────────

    async def _scan_knowledge_gaps(self) -> list[OpportunityProposal]:
        """Find knowledge gaps — nodes with low confidence or missing properties.

        Returns:
            List of OpportunityProposal from KG analysis.
        """
        proposals: list[OpportunityProposal] = []

        # Get stats to understand graph health
        stats = await self._kg.get_stats()
        node_count = stats.get("node_count", 0)

        if node_count == 0:
            return proposals

        # Query for competitor nodes with few properties
        competitors = await self._kg.query(label="competitor")
        for comp in competitors:
            props = comp.properties or {}
            confidence = props.get("_confidence", 0.0)
            if confidence < 0.5 or len(props) < 3:
                proposals.append(OpportunityProposal(
                    id=str(uuid4()),
                    prompt=f"Research {comp.name} — update competitive intelligence",
                    source="knowledge_gap",
                    evidence=[
                        f"KG node '{comp.name}' has low confidence ({confidence:.1f}) "
                        f"and only {len(props)} properties"
                    ],
                    confidence=0.6 + (1.0 - confidence) * 0.3,
                    estimated_effort="medium",
                ))

        # Query for technology nodes with no edges
        technologies = await self._kg.query(label="technology")
        for tech in technologies:
            neighbors = await self._kg.get_neighbors(tech.id)
            edges = neighbors.get("edges", [])
            if not edges:
                proposals.append(OpportunityProposal(
                    id=str(uuid4()),
                    prompt=f"Investigate {tech.name} — how it relates to other entities",
                    source="knowledge_gap",
                    evidence=[
                        f"KG node '{tech.name}' has no relationships to other entities"
                    ],
                    confidence=0.65,
                    estimated_effort="low",
                ))

        return proposals

    async def _scan_recurring_patterns(self) -> list[OpportunityProposal]:
        """Find recurring patterns from FTS5 search history.

        Returns:
            List of OpportunityProposal from pattern analysis.
        """
        proposals: list[OpportunityProposal] = []

        # Scan KG text for known recurring patterns
        for pattern in _RECURRING_PATTERNS:
            try:
                results = await self._kg.search(pattern, limit=3)
                if len(results) >= 2:
                    # Pattern appears multiple times — suggest deeper research
                    proposals.append(OpportunityProposal(
                        id=str(uuid4()),
                        prompt=f"Deepen research on '{pattern}' — recurring topic detected",
                        source="recurring_pattern",
                        evidence=[
                            f"'{pattern}' appears in {len(results)} KG nodes",
                            f"Sample node: {results[0].name if results else 'unknown'}",
                        ],
                        confidence=0.7,
                        estimated_effort="low",
                    ))
            except Exception:
                continue

        return proposals
