"""
⚠️ LEGACY STUB — This module has been replaced.

All functionality moved to:
  - ActivityStream → core/activity_stream.py
  - ResponseCache → infrastructure/persistence/response_cache.py
  - StateRepositoryPort → application/ports/state_repo_port.py

Use Container.get() from weebot.application.di for any of these.
Target sunset: 2026-09-01
"""
from __future__ import annotations

import warnings

warnings.warn(
    "weebot.state_coordinator is deprecated and will be removed. "
    "Use Container.get() for ActivityStream, ResponseCache, or StateRepositoryPort directly.",
    DeprecationWarning,
    stacklevel=2,
)

# All original implementation removed — no remaining callers in the codebase.