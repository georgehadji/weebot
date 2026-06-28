"""CatalogValidator — startup cross-validation of cascade models against the catalog.

Ensures every model referenced in ``_ROLE_MODEL_CASCADE`` exists in the
model catalog with a matching ``provider`` field. Runs at DI container
initialization and on demand via ``cli.main doctor --validate-catalog``.

Design:
    - Purely additive — never blocks startup (fail-open by design)
    - Warnings only, even for missing models
    - Standalone module with zero weebot imports beyond its types
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.services.model_registry._models import ModelConfig

_log = logging.getLogger(__name__)


@dataclass
class ValidationWarning:
    """One issue found during catalog validation."""

    model_id: str
    cascade_role: str
    field: str  # "missing", "provider_mismatch", "unknown_role"
    expected: str
    actual: Optional[str]

    def __str__(self) -> str:
        if self.field == "missing":
            return (
                f"[CatalogValidator] Model '{self.model_id}' in role "
                f"'{self.cascade_role}' does not exist in model catalog"
            )
        if self.field == "provider_mismatch":
            return (
                f"[CatalogValidator] Model '{self.model_id}' in role "
                f"'{self.cascade_role}': expected provider '{self.expected}', "
                f"found '{self.actual or '<None>'}'"
            )
        if self.field == "unknown_role":
            return (
                f"[CatalogValidator] Cascade role '{self.cascade_role}' not found — "
                f"models list for this role will be skipped"
            )
        return f"[CatalogValidator] Unknown warning type '{self.field}' for '{self.model_id}'"


@dataclass
class ValidationReport:
    """Aggregated result from a validation run."""

    total_models_checked: int = 0
    warnings: List[ValidationWarning] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def log_summary(self) -> None:
        """Emit structured log at the appropriate level."""
        if self.warning_count == 0:
            _log.info(
                "CatalogValidator: %d models validated, 0 warnings — catalog is clean",
                self.total_models_checked,
            )
        else:
            _log.warning(
                "CatalogValidator: %d models validated, %d warning(s)",
                self.total_models_checked,
                self.warning_count,
            )
            for w in self.warnings:
                _log.warning(str(w))


class CatalogValidator:
    """Cross-validates cascade model lists against the model catalog.

    Usage::

        validator = CatalogValidator()
        report = validator.validate(role_cascades=<dict>, catalog=<dict>)
        report.log_summary()

    For the standard validation against the built-in catalog and cascade
    definitions, use the convenience method::

        report = CatalogValidator.run_default_validation()
    """

    @staticmethod
    def run_default_validation() -> ValidationReport:
        """Run validation against the built-in catalog and role cascades.

        This is the single entry point used by both the DI container
        startup and the ``doctor --validate-catalog`` CLI flag.
        """
        import weebot.config.model_refs as _mr
        from weebot.application.services.model_registry._catalog import MODELS as _CATALOG

        _validator = CatalogValidator()
        return _validator.validate(
            role_cascades=_mr._ROLE_MODEL_CASCADE,
            catalog=_CATALOG,
        )

    def validate(
        self,
        role_cascades: Dict[str, List[str]],
        catalog: Dict[str, "ModelConfig"],
    ) -> ValidationReport:
        """Run validation across all roles and their cascade tiers.

        Args:
            role_cascades: ``{role_name: [model_id, ...]}`` — the
                ``_ROLE_MODEL_CASCADE`` from ``model_refs.py``.
            catalog: ``{model_id: ModelConfig}`` — the ``MODELS`` dict
                from ``_catalog.py``.

        Returns:
            ValidationReport with per-model warnings.
        """
        import time as _t

        t0 = _t.monotonic()
        report = ValidationReport()

        for role, model_ids in role_cascades.items():
            if not isinstance(model_ids, (list, tuple)):
                _log.debug(
                    "CatalogValidator: role '%s' doesn't have a model list — skipping",
                    role,
                )
                continue

            for model_id in model_ids:
                report.total_models_checked += 1
                self._check_model(report, model_id, role, catalog)

        report.elapsed_ms = (_t.monotonic() - t0) * 1000
        return report

    # Suffixes that are routing variants, not separate model IDs
    _ROUTING_SUFFIXES = (":thinking", ":free", ":nitro")

    @staticmethod
    def _strip_routing_suffix(model_id: str) -> str:
        """Strip routing variant suffixes to get the base model ID.

        ``z-ai/glm-5.2:thinking`` → ``z-ai/glm-5.2``
        ``qwen/qwen3-coder:free`` → ``qwen/qwen3-coder``
        """
        for suffix in CatalogValidator._ROUTING_SUFFIXES:
            if model_id.endswith(suffix):
                return model_id[: -len(suffix)]
        return model_id

    def _check_model(
        self,
        report: ValidationReport,
        model_id: str,
        role: str,
        catalog: Dict[str, "ModelConfig"],
    ) -> None:
        """Validate a single model entry."""
        # Extract the expected provider from the model prefix
        # e.g. "x-ai/grok-build-0.1" -> prefix "x-ai" -> provider "xai"
        expected_provider = self._model_prefix_to_provider(model_id)

        # Strip routing suffixes (:thinking, :free, :nitro) for catalog lookup —
        # these are runtime variants, not separate model IDs in the catalog.
        base_id = self._strip_routing_suffix(model_id)

        if base_id not in catalog and model_id not in catalog:
            report.warnings.append(
                ValidationWarning(
                    model_id=model_id,
                    cascade_role=role,
                    field="missing",
                    expected=expected_provider,
                    actual=None,
                )
            )
            return

        # Look up using the base ID (stripped of routing suffix) first,
        # fall back to the original model_id for backward compatibility.
        config = catalog.get(base_id) or catalog[model_id]
        try:
            actual_provider = config.provider
        except AttributeError:
            actual_provider = None

        if expected_provider and actual_provider and expected_provider != actual_provider:
            report.warnings.append(
                ValidationWarning(
                    model_id=model_id,
                    cascade_role=role,
                    field="provider_mismatch",
                    expected=expected_provider,
                    actual=actual_provider,
                )
            )

    @staticmethod
    def _model_prefix_to_provider(model_id: str) -> str:
        """Map an OpenRouter-qualified model ID prefix to a provider name.

        ``x-ai/grok-build-0.1`` → ``xai``
        ``deepseek/deepseek-v4-flash`` → ``deepseek``
        ``moonshotai/kimi-k2.6`` → ``moonshotai``
        """
        prefix = model_id.split("/")[0] if "/" in model_id else model_id

        # Map known OpenRouter prefixes to the provider names used in the catalog
        prefix_map = {
            "x-ai": "xai",
            "z-ai": "openrouter",   # z-ai models go through OpenRouter
            "moonshotai": "moonshot",  # moonshotai prefix → "moonshot" provider
            "minimax": "openrouter",  # MiniMax models route through OpenRouter
            "qwen": "openrouter",   # Qwen models go through OpenRouter
            "kimi": "openrouter",   # Kimi models go through OpenRouter
            "nex-agi": "openrouter",
            "sourceful": "openrouter",
            "black-forest-labs": "openrouter",
            "ideogram": "openrouter",
            "google": "openrouter",
            "meta-llama": "openrouter",
            "mistralai": "openrouter",
            "anthropic": "openrouter",
            "openai": "openrouter",
            "cohere": "openrouter",
        }

        # Models whose prefix matches the provider name directly
        direct_providers = {
            "deepseek",
            "recraft",
        }

        if prefix in prefix_map:
            return prefix_map[prefix]
        if prefix in direct_providers:
            return prefix
        # Fallback: return the prefix as-is
        return prefix
