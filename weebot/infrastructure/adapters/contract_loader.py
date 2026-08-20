"""ContractLoader — loads per-tool Environment Contracts (Tier 3.2).

Reads every ``*.yaml`` file under ``contracts_dir`` (default
``config/contracts/``) at construction time into ``ToolContract`` models,
then exposes ``enhance_description()`` — the hook
``ToolCollection.execute()``/``to_params()`` calls to append known pitfalls
to a tool's description before it reaches the LLM.

A missing or empty contracts directory is not an error: tools without a
contract file simply get their description back unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from weebot.domain.models.tool_contract import ToolContract

logger = logging.getLogger(__name__)


class ContractLoader:
    """Loads and serves per-tool Environment Contracts from YAML."""

    def __init__(self, contracts_dir: str | Path = "config/contracts/") -> None:
        self._contracts: dict[str, ToolContract] = {}
        self._load(_resolve_contracts_dir(contracts_dir))

    def _load(self, directory: Path) -> None:
        if not directory.is_dir():
            logger.debug("ContractLoader: %s does not exist — no contracts loaded", directory)
            return
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                contract = ToolContract.model_validate(data)
            except Exception:
                logger.warning("ContractLoader: failed to load %s", path, exc_info=True)
                continue
            self._contracts[contract.tool] = contract

    def get(self, tool_name: str) -> ToolContract | None:
        """Return the contract for *tool_name*, or None if none was loaded."""
        return self._contracts.get(tool_name)

    def enhance_description(self, tool_name: str, description: str) -> str:
        """Append known pitfalls for *tool_name* to *description*.

        Returns *description* unchanged when no contract (or no pitfalls)
        is registered for the tool.
        """
        contract = self._contracts.get(tool_name)
        if contract is None or not contract.pitfalls:
            return description
        pitfalls_block = "\n".join(f"- {p}" for p in contract.pitfalls)
        return f"{description}\n\nKnown pitfalls:\n{pitfalls_block}"

    def __len__(self) -> int:
        return len(self._contracts)


def _resolve_contracts_dir(contracts_dir: str | Path) -> Path:
    """Resolve *contracts_dir* relative to the ``weebot`` package root.

    Mirrors ``FactoriesMixin._create_harness_config()``'s resolution of
    ``config/harness/`` so both stay CWD-independent.
    """
    path = Path(contracts_dir)
    if path.is_absolute():
        return path
    package_root = Path(__file__).resolve().parents[2]
    return package_root / path
