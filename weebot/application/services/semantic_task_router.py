"""SemanticTaskRouter — embedding-based task category classifier.

Uses ``LocalEmbeddings`` (all-MiniLM-L6-v2, 384-dim) from
``weebot/qmd_integration/embeddings.py`` — the same embedding model
already loaded for skill retrieval.  Classifies step descriptions by
nearest-centroid cosine similarity against labeled examples per
``TaskCategory``.

Expected accuracy: >85% on the 25-case benchmark, compared to 72%
for the keyword-based ``task_model_router.py``.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.application.services.task_model_router import TaskCategory
from weebot.domain.models.task_route import TaskRoute

logger = logging.getLogger(__name__)

# Labeled examples per category — 8 each for stable centroids.
# These are natural-language sentences, NOT keywords, so the embedding
# model captures semantic context rather than lexical overlap.
_EXAMPLES: dict[TaskCategory, list[str]] = {
    TaskCategory.CODING: [
        "refactor the database module to use async queries",
        "implement a login endpoint with JWT authentication",
        "write a Python function that computes fibonacci numbers",
        "fix the TypeError bug in the authentication middleware",
        "build a REST API endpoint for user profile management",
        "create a unit test for the merge sort function",
        "debug the memory leak in the XML parser module",
        "convert the synchronous HTTP client to use asyncio",
    ],
    TaskCategory.FILE_OPS: [
        "list all Python files in the directory recursively",
        "create a new output directory for the generated reports",
        "read the configuration file and parse its YAML contents",
        "rename the old deployment manifest to archive backup",
        "scan every Python file under the project and count lines",
        "check if the application log file exists and is not empty",
        "copy the compiled build artifacts to the deploy folder",
        "delete all temporary cache files from the output directory",
    ],
    TaskCategory.RESEARCH: [
        "search for the latest academic papers on transformer models",
        "web_search for LLM agent frameworks and tool-use patterns",
        "investigate the root cause of the production database crash",
        "gather requirements from stakeholders for the new feature",
        "browse the competitor pricing page and extract structured data",
        "find information about climate change policy impacts on infrastructure",
        "look into the git history of this bug across previous releases",
        "explore the entire codebase for similar anti-patterns",
    ],
    TaskCategory.REVIEW: [
        "audit the security of the authentication and authorization module",
        "review this pull request for code quality and style issues",
        "inspect the Kubernetes deployment configuration for misconfigurations",
        "evaluate the test coverage report and identify critical gaps",
        "find bugs and security vulnerabilities in the payment processing module",
        "assess whether the new feature implementation follows best practices",
        "critique the system architecture design document for flaws",
        "verify that the error handling follows the project conventions",
    ],
    TaskCategory.SECURITY: [
        "scan for SQL injection vulnerabilities in user-facing input fields",
        "detect cross-site scripting vectors in the HTML template rendering",
        "find hardcoded API keys and secrets committed to source control",
        "check for insecure deserialization in the pickle data loading path",
        "audit the sandbox escape vectors in the bash command execution tool",
        "verify that all file paths are sanitized against directory traversal",
    ],
    TaskCategory.SUMMARIZATION: [
        "summarize the meeting notes into a concise bullet-point list",
        "write a summary of the project status for the executive stakeholders",
        "provide a recap of what was accomplished during this development sprint",
        "wrap up the debugging session and list all completed tasks",
        "generate a comprehensive report of all findings from the audit",
        "produce a final summary of the changes made in this release",
    ],
    TaskCategory.PLANNING: [
        "design the system architecture for the new microservice platform",
        "create a detailed plan for migrating the legacy database schema",
        "outline the step-by-step procedure to deploy the application to production",
        "define the OpenAPI specification for the new REST endpoint",
        "structure the entire project into Clean Architecture layers",
        "draft a blueprint for the event-driven communication between services",
    ],
    TaskCategory.GENERAL: [
        "say hello",
        "what time is it",
        "thank you for your help",
        "how are you doing today",
    ],
}


class SemanticTaskRouter(TaskRouterPort):
    """Classify step descriptions by nearest-centroid cosine similarity.

    Uses the same ``LocalEmbeddings`` singleton already loaded by the
    QMD integration module.  Centroid vectors are precomputed at
    construction time from labeled examples.

    Args:
        embeddings: Optional ``LocalEmbeddings`` instance.  When ``None``,
            uses the shared singleton from ``get_local_embeddings()``.
    """

    def __init__(self, embeddings=None) -> None:
        self._embeddings = embeddings
        self._centroids: dict[TaskCategory, np.ndarray] = {}
        self._build_centroids()

    def _get_embeddings(self):
        """Lazy-load the LocalEmbeddings singleton."""
        if self._embeddings is None:
            from weebot.qmd_integration.embeddings import get_local_embeddings

            self._embeddings = get_local_embeddings()
        return self._embeddings

    def _build_centroids(self) -> None:
        """Precompute L2-normalized centroid vectors for each category."""
        emb = self._get_embeddings()
        for cat, examples in _EXAMPLES.items():
            vecs = []
            for ex in examples:
                try:
                    result = emb.embed_query(ex)
                    vecs.append(np.array(result.embedding, dtype=np.float32))
                except Exception as exc:
                    logger.warning(
                        "SemanticTaskRouter: failed to embed example for %s: %s",
                        cat.value, exc,
                    )
            if vecs:
                centroid = np.mean(vecs, axis=0)
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid = centroid / norm
                self._centroids[cat] = centroid

        logger.info(
            "SemanticTaskRouter: built centroids for %d categories",
            len(self._centroids),
        )

    async def route(self, query: str) -> TaskRoute:
        """Classify *query* into the best-matching TaskCategory.

        Args:
            query: Step description to classify.

        Returns:
            ``TaskRoute`` with the predicted category and confidence score.
        """
        if not self._centroids:
            # Centroids failed to build — fall back to GENERAL
            return TaskRoute(category=TaskCategory.GENERAL, confidence=0.5)

        emb = self._get_embeddings()
        try:
            result = await emb.embed_query(query)
            qvec = np.array(result.embedding, dtype=np.float32)
        except Exception as exc:
            logger.warning("SemanticTaskRouter: query embedding failed — %s", exc)
            return TaskRoute(category=TaskCategory.GENERAL, confidence=0.0)

        # Cosine similarity = dot product of L2-normalized vectors
        scores: dict[TaskCategory, float] = {}
        for cat, centroid in self._centroids.items():
            scores[cat] = float(np.dot(qvec, centroid))

        best = max(scores, key=scores.get)
        best_score = scores[best]
        # Map [-1, 1] cosine to [0, 1] confidence
        confidence = round((best_score + 1.0) / 2.0, 3)

        return TaskRoute(
            category=best,
            confidence=confidence,
        )

    async def refresh(self) -> None:
        """Rebuild centroids (called when examples change)."""
        self._centroids.clear()
        self._build_centroids()
