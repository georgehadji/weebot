"""Tests for rerank model reference constants and routing."""
import pytest
from weebot.config.model_refs import (
    RERANK_MODEL_FREE,
    RERANK_MODEL_PRO,
    RERANK_MODEL_FAST,
    RERANK_MODEL_V35,
    get_rerank_model_for,
)


def test_rerank_model_free_is_cheapest_paid_cohere():
    """RERANK_MODEL_FREE points to Cohere Rerank 4 Fast (cheapest paid tier).

    Was previously nvidia/llama-nemotron-rerank-vl-1b-v2:free, but that
    endpoint was unconfirmed against the Cohere-compatible rerank API and
    RERANK_MODEL_FREE now aliases RERANK_MODEL_FAST directly — see the
    constant's docstring in weebot/config/model_refs.py.
    """
    assert RERANK_MODEL_FREE == "cohere/rerank-4-fast"
    assert RERANK_MODEL_FREE == RERANK_MODEL_FAST


def test_rerank_model_free_is_distinct_from_pro_and_v35():
    """RERANK_MODEL_FREE is distinct from the higher/lower Cohere tiers."""
    assert RERANK_MODEL_FREE != RERANK_MODEL_PRO
    assert RERANK_MODEL_FREE != RERANK_MODEL_V35


def test_quality_cases_use_pro():
    """Quality-sensitive use cases still use RERANK_MODEL_PRO."""
    for case in ("research", "skills", "evaluation"):
        assert get_rerank_model_for(case) == RERANK_MODEL_PRO, (
            f"Expected {case} to use PRO model, got {get_rerank_model_for(case)}"
        )


def test_throughput_cases_use_free():
    """High-throughput, low-criticality cases use RERANK_MODEL_FREE."""
    for case in ("search", "compressor", "memory", "knowledge"):
        assert get_rerank_model_for(case) == RERANK_MODEL_FREE, (
            f"Expected {case} to use FREE model, got {get_rerank_model_for(case)}"
        )


def test_unknown_case_defaults_to_free():
    """Unknown/unmapped use case defaults to free model (failsafe = cheapest)."""
    assert get_rerank_model_for("nonexistent") == RERANK_MODEL_FREE


def test_free_model_matches_fast_tier():
    """RERANK_MODEL_FREE is priced per-search (Cohere), not per-token — it
    isn't expected to appear in the token-cost model registry the way the
    old free-tier nvidia model was. It should just track RERANK_MODEL_FAST.
    """
    assert RERANK_MODEL_FREE == RERANK_MODEL_FAST
