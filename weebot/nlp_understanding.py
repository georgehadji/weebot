"""Compatibility stub for legacy agent_core_v2.py.

The original ``weebot.nlp_understanding`` module was moved to
``weebot.application.services.nlp_understanding`` during the
Clean Architecture reorganisation.  This stub re-exports the
symbols that ``agent_core_v2.WeebotAgent`` expects.

Target sunset: 2027-03-01 (per agent_core_v2.py header).
"""
from __future__ import annotations

import warnings

from weebot.application.services.nlp_understanding import (
    IntentRecognitionResult,
    NaturalLanguageProcessor,
)

warnings.warn(
    "weebot.nlp_understanding is deprecated. "
    "Import from weebot.application.services.nlp_understanding instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["NaturalLanguageProcessor", "IntentRecognitionResult"]
