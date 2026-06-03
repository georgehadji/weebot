"""RuleSelector — injects only the rule modules relevant to the current step.

Shares the task_classification.yaml keyword config with KeywordTaskRouter
(Enhancement 6).  Given a step description, determines which tool and
domain rules are relevant and returns their content for injection.

Pulls mandatory_rules from the task_classification.yaml category config,
and also matches step descriptions against category keywords for dynamic
rule injection.

Maps to Enhancement 2 — Domain-Specific Rule Injection.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "rules"
_CLASSIFICATION_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "task_classification.yaml"

# Always-injected rules for safety
_ALWAYS_RULES = ["error_handling.md"]


class RuleSelector:
    """Select rule modules relevant to a step description.

    Args:
        rules_dir: Directory containing *.md rule files.
        classification_path: Path to task_classification.yaml.
    """

    def __init__(
        self,
        rules_dir: Optional[Path] = None,
        classification_path: Optional[Path] = None,
    ) -> None:
        self._rules_dir = rules_dir or _RULES_DIR
        self._categories: dict = {}
        self._load_classification(classification_path or _CLASSIFICATION_PATH)

    def _load_classification(self, path: Path) -> None:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                self._categories = data.get("categories", {})
            except Exception as exc:
                logger.warning("Failed to load classification: %s", exc)

    def select_rules(
        self, step_description: str, mandatory: Optional[list[str]] = None,
    ) -> list[str]:
        """Return the content of rule modules relevant to *step_description*.

        Args:
            step_description: The current step's description text.
            mandatory: Rule files required by the current task category
                       (from task_classification.yaml).

        Returns:
            List of markdown rule block strings.
        """
        selected_files = set(_ALWAYS_RULES)

        # Add mandatory rules from classification config
        if mandatory:
            for rule in mandatory:
                selected_files.add(rule)

        # Match step description against category keywords
        step_lower = step_description.lower()
        for cat_name, cat_cfg in self._categories.items():
            keywords = cat_cfg.get("keywords", [])
            hits = sum(1 for kw in keywords if kw in step_lower)
            if hits > 0:
                for rule in cat_cfg.get("mandatory_rules", []):
                    selected_files.add(rule)

        # Load rule content
        rules_content: list[str] = []
        for rule_file in selected_files:
            path = self._rules_dir / rule_file
            if path.exists():
                content = path.read_text(encoding="utf-8")
                if content.strip():
                    rules_content.append(content.strip())

        return rules_content

    def available_rules(self) -> list[str]:
        """Return all available rule file names."""
        if not self._rules_dir.exists():
            return []
        return sorted(p.name for p in self._rules_dir.glob("*.md"))
