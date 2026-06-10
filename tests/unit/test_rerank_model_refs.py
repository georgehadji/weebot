"""Tests for rerank model reference constants and routing."""
import pytest
from weebot.config.model_refs import (
    RERANK_MODEL_FREE,
    RERANK_MODEL_PRO,
    RERANK_MODEL_FAST,
    RERANK_MODEL_V35,
    get_rerank_model_for,
)


def test_rerank_model_free_is_nvidia_nemotron():
    """RERANK_MODEL_FREE points to the NVIDIA Nemotron 1B free model."""
    assert RERANK_MODEL_FREE == "nvidia/llama-nemotron-rerank-vl-1b-v2:free"


def test_rerank_model_free_is_distinct():
    """RERANK_MODEL_FREE is distinct from the paid Cohere models."""
    assert RERANK_MODEL_FREE != RERANK_MODEL_PRO
    assert RERANK_MODEL_FREE != RERANK_MODEL_FAST
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


def test_model_is_in_registry():
    """The free model is registered in the model registry."""
    from weebot.config.model_registry import get_model_info
    info = get_model_info(RERANK_MODEL_FREE)
    assert info is not None
    assert info.model_name == "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    assert info.input_cost_per_token == 0.0
    assert info.output_cost_per_token == 0.0
