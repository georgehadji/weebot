"""KeywordTaskRouter — rule-based task classification using keyword matching.

Always available (no ML dependencies).  Loads category definitions from
config/task_classification.yaml and matches user queries against keyword
lists.  The highest keyword-hit count category wins.

Maps to Enhancement 6 — Neural Task Router (always-available fallback).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.domain.models.task_route import TaskCategory, TaskComplexity, TaskRoute

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "task_classification.yaml"


class KeywordTaskRouter(TaskRouterPort):
    """Rule-based task classifier using keyword matching from YAML config.

    For each category, counts how many keywords appear in the query.
    Whichever category has the most hits wins.  Ties are broken by
    the priority order in the YAML file (casual → code → research → ...).

    Args:
        config_path: Path to task_classification.yaml.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._config_path = config_path or _CONFIG_PATH
        self._categories: list[dict] = []
        self._fallback: dict = {}
        self._refresh()

    def _refresh(self) -> None:
        """Load classification data from YAML."""
        if not self._config_path.exists():
            logger.warning("Task classification config not found: %s", self._config_path)
            self._categories = []
            self._fallback = {"flow_type": "plan_act", "tool_restriction": "admin_role"}
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            self._categories = []
            for cat_name, cfg in data.get("categories", {}).items():
                cat_enum = getattr(TaskCategory, cat_name.upper(), None)
                if cat_enum:
                    self._categories.append({
                        "category": cat_enum,
                        "keywords": [k.lower() for k in cfg.get("keywords", [])],
                        "flow_type": cfg.get("flow_type", "plan_act"),
                        "tool_restriction": cfg.get("tool_restriction", "admin_role"),
                        "mandatory_rules": cfg.get("mandatory_rules", []),
                        "complexity": TaskComplexity(cfg.get("complexity", "high")),
                    })

            self._fallback = data.get("fallback", {
                "flow_type": "plan_act",
                "tool_restriction": "admin_role",
                "mandatory_rules": ["error_handling.md"],
            })

            logger.info(
                "KeywordTaskRouter: loaded %d categories, %d total keywords",
                len(self._categories),
                sum(len(c["keywords"]) for c in self._categories),
            )
        except Exception as exc:
            logger.error("Failed to load task classification: %s", exc)
            self._categories = []
            self._fallback = {"flow_type": "plan_act", "tool_restriction": "admin_role"}

    async def route(self, query: str) -> TaskRoute:
        """Classify *query* and return a TaskRoute."""
        stripped = query.strip()
        # Short-circuit: empty or trivially short input is conversational, not a
        # task.  Routing it to a heavyweight plan_act/COMPLEX flow is wrong.
        if len(stripped) <= 2:
            return self._casual_route()

        query_lower = query.lower()

        best_category = None
        best_hits = 0
        matched_count = 0

        for cat_cfg in self._categories:
            hits = sum(1 for kw in cat_cfg["keywords"] if kw in query_lower)
            if hits:
                matched_count += 1
            if hits > best_hits:
                best_hits = hits
                best_category = cat_cfg

        if best_category is None or best_hits == 0:
            return self._fallback_route()

        confidence = min(best_hits / max(len(best_category["keywords"]), 1) * 5, 1.0)

        return TaskRoute(
            category=best_category["category"],
            complexity=self._estimate_complexity(query_lower, matched_count),
            flow_type=best_category["flow_type"],
            tool_restriction=best_category["tool_restriction"],
            mandatory_rules=best_category["mandatory_rules"],
            confidence=round(confidence, 3),
        )

    @staticmethod
    def _estimate_complexity(query_lower: str, matched_count: int) -> TaskComplexity:
        """Estimate task complexity from scope signals.

        Multi-category queries or those naming build-scale work (build an app,
        design a system, deploy a pipeline …) are HIGH; a single focused
        request (write a function, fix a bug) is LOW.
        """
        if matched_count >= 2:
            return TaskComplexity.HIGH
        high_signals = (
            "build", "create", "develop", "design", "architect", "end-to-end",
            "full ", "system", "application", "app", "pipeline", "deploy",
            "integrate", "website", "platform", "microservice",
        )
        if any(sig in query_lower for sig in high_signals):
            return TaskComplexity.HIGH
        return TaskComplexity.LOW

    def _casual_route(self) -> TaskRoute:
        """A conversational route for trivial/empty input."""
        return TaskRoute(
            category=TaskCategory.CASUAL,
            complexity=TaskComplexity.LOW,
            flow_type="chat",
            tool_restriction="none",
            mandatory_rules=[],
            confidence=0.0,
        )

    async def refresh(self) -> None:
        self._refresh()

    def _fallback_route(self) -> TaskRoute:
        return TaskRoute(
            category=TaskCategory.COMPLEX,
            complexity=TaskComplexity.HIGH,
            flow_type=self._fallback.get("flow_type", "plan_act"),
            tool_restriction=self._fallback.get("tool_restriction", "admin_role"),
            mandatory_rules=self._fallback.get("mandatory_rules", []),
            confidence=0.0,
        )
