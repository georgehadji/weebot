"""Every text model weebot can route to must exist in the model catalog.

The catalog is generated from OpenRouter's live list, so "not in the catalog"
means "OpenRouter will 404 it". On 2026-09-26 that was true of the cascade's
last-resort tier (`qwen/qwen3.8-max`, kept alive only by a hand-written catalog
override), a budget model (`nex-agi/nex-n2-pro`), and eight of the eighteen
models in core/model_cascade_config.py -- whose `get_cascade_for_task` sorts the
free tier first, so every cascade built from it opened with dead models.

Image, video and rerank models are out of scope: the generated catalog covers
OpenRouter's default text listing only.
"""

from __future__ import annotations

import pytest

from weebot.config import model_refs
from weebot.config.model_catalog import MODELS
from weebot.config.model_registry import strip_routing_suffix
from weebot.core.model_cascade_config import MODEL_CASCADE
from weebot.domain.models.agent_capability import AGENT_CAPABILITIES


def _routed() -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {
        "model_refs.MODEL_CASCADE_TIER1-4": {
            model_refs.MODEL_CASCADE_TIER1,
            model_refs.MODEL_CASCADE_TIER2,
            model_refs.MODEL_CASCADE_TIER3,
            model_refs.MODEL_CASCADE_TIER4,
        },
        "model_refs._ROLE_MODEL_CASCADE": {
            m for ms in model_refs._ROLE_MODEL_CASCADE.values() for m in ms
        },
        "model_refs.ROLE_MODEL_CONFIG": {
            m for ms in model_refs.ROLE_MODEL_CONFIG.values() for m in ms
        },
        "model_refs.get_free_models()": set(model_refs.get_free_models()),
        "core.model_cascade_config.MODEL_CASCADE": {
            m.id for ms in MODEL_CASCADE.values() for m in ms
        },
        "agent_capability.AGENT_CAPABILITIES": {
            m for cap in AGENT_CAPABILITIES.values() for m in cap.preferred_models
        },
    }
    return sources


@pytest.mark.parametrize("source", sorted(_routed()))
def test_every_routed_model_is_in_the_catalog(source: str) -> None:
    missing = sorted(
        m for m in _routed()[source] if m not in MODELS and strip_routing_suffix(m) not in MODELS
    )
    assert missing == [], (
        f"{source} routes to models OpenRouter does not list (per the generated "
        f"catalog). Replace or remove them, or regenerate the catalog if they are "
        f"new: {missing}"
    )
