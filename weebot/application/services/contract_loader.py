"""ContractLoader — loads tool contract YAML files and injects them into descriptions.

The Environment Contract Layer (LIFE-HARNESS Section 4.3.1) makes stable
environment constraints explicit before interaction.  This loader reads
per-tool YAML contracts and appends their `pitfalls` and `constraints` to
the tool description visible to the LLM.

Contract pitfalls are injected into ToolCollection.to_params() so the LLM
sees them as part of the function spec.  No separate injection mechanism
is needed — this reuses the existing tool description pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class ContractLoader:
    """Load and merge tool contract YAML files.

    Args:
        contracts_dir: Directory containing *.yaml contract files.
                       Defaults to weebot/config/contracts/.
    """

    def __init__(self, contracts_dir: Optional[Path] = None) -> None:
        if contracts_dir is None:
            contracts_dir = (
                Path(__file__).resolve().parent.parent.parent / "config" / "contracts"
            )
        self._contracts: dict[str, dict] = {}
        self._load_all(contracts_dir)

    def _load_all(self, contracts_dir: Path) -> None:
        if not contracts_dir.exists():
            logger.warning("Contracts dir %s not found", contracts_dir)
            return
        for path in sorted(contracts_dir.glob("*.yaml")):
            try:
                with open(path, encoding="utf-8") as f:
                    contract = yaml.safe_load(f)
                if contract and isinstance(contract, dict):
                    tool = contract.get("tool")
                    if tool:
                        self._contracts[tool] = contract
            except Exception as exc:
                logger.warning("Failed to load contract %s: %s", path, exc)
        logger.info("Loaded %d tool contracts", len(self._contracts))

    def enhance_description(self, tool_name: str, description: str) -> str:
        """Append contract pitfalls and constraints to a tool description.

        Called by ToolCollection.to_params() for each tool.
        """
        contract = self._contracts.get(tool_name)
        if contract is None:
            return description

        parts = [description]

        constraints = contract.get("constraints", [])
        if constraints:
            parts.append("")
            parts.append("CRITICAL:")
            for c in constraints:
                parts.append(f"  - {c}")

        pitfalls = contract.get("pitfalls", [])
        if pitfalls:
            parts.append("")
            parts.append("PITFALLS (avoid these):")
            for p in pitfalls:
                parts.append(f"  - {p}")

        return "\n".join(parts)

    def get_contract(self, tool_name: str) -> Optional[dict]:
        """Return the raw contract dict for *tool_name*, or None."""
        return self._contracts.get(tool_name)
