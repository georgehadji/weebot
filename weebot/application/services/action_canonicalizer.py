"""ActionCanonicalizer — rule-based tool-call validator (Tier 1.1).

Loads per-tool contract YAML files from weebot/config/contracts/.
Each contract defines type coercions, safe defaults, and block patterns.
Canonicalization applies in this order:

1. BLOCK on empty/syntactically-invalid required args
2. COERCE types (str → int for timeout, etc.)
3. FILL missing optional args with safe defaults
4. PASS with corrected args

Every canonicalization is logged as a CanonicalizationEvent for audit
and downstream harness evolution.

Maps to LIFE-HARNESS "Action Realization Layer" (Section 4.3.3).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from weebot.application.ports.canonicalizer_port import CanonicalizerPort
from weebot.domain.models.canonical import (
    CanonicalizationResult,
    CanonicalizationVerdict,
)

logger = logging.getLogger(__name__)

_CONTRACTS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "contracts"


class ActionCanonicalizer(CanonicalizerPort):
    """Rule-based tool-call validator using per-tool contract YAML files.

    Args:
        contracts_dir: Directory containing *.yaml contract files.
                       Defaults to weebot/config/contracts/.
        harness_config: Optional HarnessConfig for cross-model settings.
    """

    def __init__(
        self,
        contracts_dir: Optional[Path] = None,
        harness_config=None,
    ) -> None:
        self._contracts_dir = contracts_dir or _CONTRACTS_DIR
        self._contracts: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all contract YAML files from the contracts directory."""
        if not self._contracts_dir.exists():
            logger.warning("Contracts dir %s not found — canonicalizer disabled", self._contracts_dir)
            return
        for path in sorted(self._contracts_dir.glob("*.yaml")):
            try:
                with open(path, encoding="utf-8") as f:
                    contract = yaml.safe_load(f)
                if contract and isinstance(contract, dict):
                    tool = contract.get("tool")
                    if tool:
                        self._contracts[tool] = contract
                        logger.debug("Loaded contract for %s", tool)
            except Exception as exc:
                logger.warning("Failed to load contract %s: %s", path, exc)
        logger.info("Loaded %d tool contracts", len(self._contracts))

    def canonicalize(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> CanonicalizationResult:
        """Validate and canonicalize *arguments* for *tool_name*."""
        contract = self._contracts.get(tool_name)
        if contract is None:
            return CanonicalizationResult(
                verdict=CanonicalizationVerdict.PASS,
                original_args=arguments,
                corrected_args=dict(arguments),
            )

        corrected = dict(arguments)
        changes: list[str] = []

        # 1. BLOCK on empty required args
        required = [k for k, v in (contract.get("coercions", {})).items()
                    if isinstance(v, dict) and v.get("required")]
        for arg in required:
            if arg not in corrected or corrected[arg] is None or str(corrected[arg]).strip() == "":
                return CanonicalizationResult(
                    verdict=CanonicalizationVerdict.BLOCK,
                    original_args=arguments,
                    block_reason=f"Required argument '{arg}' is missing or empty for '{tool_name}'",
                )

        # 2. Coerce types + apply defaults
        coercions = contract.get("coercions", {})
        for arg_name, rules in coercions.items():
            if not isinstance(rules, dict):
                continue
            # Fill safe defaults for missing optional args
            if arg_name not in corrected or corrected[arg_name] is None:
                if "default" in rules:
                    corrected[arg_name] = rules["default"]
                    changes.append(f"Filled missing '{arg_name}' = {rules['default']!r}")
                continue

            val = corrected[arg_name]
            target_type = rules.get("type", "str")

            try:
                if target_type == "float":
                    corrected[arg_name] = float(val)
                elif target_type == "int":
                    corrected[arg_name] = int(val)
                elif target_type == "str":
                    corrected[arg_name] = str(val)
                elif target_type == "bool":
                    if isinstance(val, str):
                        corrected[arg_name] = val.lower() in ("true", "1", "yes")
                    else:
                        corrected[arg_name] = bool(val)
            except (TypeError, ValueError) as exc:
                return CanonicalizationResult(
                    verdict=CanonicalizationVerdict.BLOCK,
                    original_args=arguments,
                    block_reason=(
                        f"Cannot coerce '{arg_name}'={val!r} to {target_type} "
                        f"for '{tool_name}': {exc}"
                    ),
                )

            # Clamp to [min, max] if specified
            if target_type in ("float", "int"):
                min_val = rules.get("min")
                max_val = rules.get("max")
                val = corrected[arg_name]
                if min_val is not None and val < min_val:
                    corrected[arg_name] = min_val
                    changes.append(f"Clamped '{arg_name}' from {val} to min {min_val}")
                if max_val is not None and val > max_val:
                    corrected[arg_name] = max_val
                    changes.append(f"Clamped '{arg_name}' from {val} to max {max_val}")

        # 3. Apply static defaults for any remaining missing keys
        for arg_name, default_val in (contract.get("defaults", {})).items():
            if arg_name not in corrected or corrected[arg_name] is None:
                corrected[arg_name] = default_val
                changes.append(f"Applied default '{arg_name}' = {default_val!r}")

        # 4. Block patterns
        for pattern_def in contract.get("block_patterns", []):
            arg = pattern_def.get("argument")
            pattern = pattern_def.get("pattern")
            reason = pattern_def.get("reason", "Blocked by pattern")
            if arg in corrected and corrected[arg] is not None:
                import re
                if re.search(pattern, str(corrected[arg])):
                    return CanonicalizationResult(
                        verdict=CanonicalizationVerdict.BLOCK,
                        original_args=arguments,
                        block_reason=f"Blocked by contract for '{tool_name}': {reason}",
                    )

        return CanonicalizationResult(
            verdict=CanonicalizationVerdict.PASS if not changes else CanonicalizationVerdict.FILL_DEFAULT,
            original_args=arguments,
            corrected_args=corrected,
            changes=changes,
        )
