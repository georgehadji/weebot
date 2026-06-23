"""Integration tests for ImageGenTool Ideogram cascade and logger.

Covers:
- F1:  `_execute_ideogram_direct` exception path must not raise NameError
- F1b: `_execute_openrouter` cascade must continue past ideogram/* model failures

These tests verify the bug discovered in the proactive audit:
    weebot/tools/image_gen_tool.py:490 — ``logger.info(...)`` references
    an undefined ``logger`` name, causing ``NameError`` on the Ideogram
    failure path.  The cascade then crashes instead of trying the next model.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════════════════
# F1: _execute_ideogram_direct must not raise NameError on failure
# ══════════════════════════════════════════════════════════════════════

def test_ideogram_direct_failure_does_not_nameerror():
    """_execute_ideogram_direct with an invalid key must return None, not raise NameError.

    This is the definitive regression test for F1.  The bug: ``logger.info(...)``
    at image_gen_tool.py:493 references an undefined name (no ``import logging``
    or ``logger = logging.getLogger(...)`` at module scope), so ANY exception
    caught at line 492 raises ``NameError`` instead of returning None.

    The test patches the HTTP layer so we hit the exception path without
    making a real network call.
    """
    from weebot.tools.image_gen_tool import ImageGenTool

    t = ImageGenTool()

    # Patch aiohttp to raise an exception that triggers except Exception at :492
    with patch("aiohttp.ClientSession.post", side_effect=OSError("connection refused")):
        result = asyncio.run(
            t._execute_ideogram_direct(
                prompt="a test prompt",
                output_path="/tmp/_test_ideogram_nameerror.png",
                ideogram_key="INVALID_KEY_SHOULD_FAIL",
            )
        )

    # The expected behavior is graceful failure — return None,
    # so the cascade continues to the next model.
    assert result is None, (
        f"Expected None (cascade fall-through), got {result!r}.  "
        "If a NameError was raised, the cascade crashed instead of continuing."
    )


def test_ideogram_direct_http_failure_returns_none():
    """_execute_ideogram_direct with a non-200 response must return None.

    Verifies the non-200 path (line 443-447) also doesn't crash.
    """
    from weebot.tools.image_gen_tool import ImageGenTool

    t = ImageGenTool()

    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.text = AsyncMock(return_value='{"error":"unauthorized"}')
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(return_value=mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = asyncio.run(
            t._execute_ideogram_direct(
                prompt="a test prompt",
                output_path="/tmp/_test_ideogram_httpfail.png",
                ideogram_key="BAD_KEY",
            )
        )

    assert result is None, (
        f"Expected None for HTTP 401, got {result!r}.  "
        "NameError on the logger.info call at :444 would crash here."
    )


# ══════════════════════════════════════════════════════════════════════
# F1b: _execute_openrouter cascade must survive ideogram/* model failures
# ══════════════════════════════════════════════════════════════════════

def test_openrouter_cascade_survives_ideogram_failure():
    """When an ideogram/* model fails, the cascade must NOT crash.

    The cascade loop in _execute_openrouter (:662) calls _try_ideogram_direct
    OUTSIDE the try/except block that wraps the OpenRouter call.  If
    _execute_ideogram_direct raises NameError, it propagates out of the
    entire _execute_openrouter method — no SVG fallback, no error message.

    This test patches image generation to fail deterministically and
    verifies the cascade reaches the next model (or the SVG fallback).
    """
    from weebot.tools.image_gen_tool import ImageGenTool, ImageGenParams

    t = ImageGenTool()

    # Directly patch _execute_ideogram_direct to simulate a failure
    # that returns None (as it should) — this isolates the cascade
    # logic from the logger bug.
    async def _mock_ideogram_fail(*args, **kwargs):
        return None

    with patch.object(t, "_execute_ideogram_direct", side_effect=_mock_ideogram_fail):
        # Also mock the OpenRouter HTTP call to avoid real network
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "choices": [{"message": {"images": [{"image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}}]
        })
        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)
        mock_session.get = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            params = ImageGenParams(
                prompt="test cascade survival",
                model="ideogram/ideogram-v3-turbo",  # force ideogram path
                output_path="/tmp/_test_cascade.png",
                use_case="general",
            )
            result = asyncio.run(t._execute_openrouter(params))

    # Cascade should either succeed via OpenRouter or fall back to SVG.
    # The key assertion: we got a ToolResult (not an exception).
    assert result is not None, (
        "Cascade returned None — the _execute_openrouter method may have crashed.  "
        "If NameError propagated, this line is unreachable."
    )
    # If the cascade worked, result.output should reference the model or fallback
    # (since we mocked a 200 response with a data:image, it should succeed)
    assert not result.is_error, (
        f"Cascade produced an error result: {result.error}.  "
        "Expected successful image generation via fallback or OpenRouter."
    )


# ══════════════════════════════════════════════════════════════════════
# F1 regression: verify logger exists in the module
# ══════════════════════════════════════════════════════════════════════

def test_image_gen_tool_module_has_logger():
    """The image_gen_tool module must have a callable logger.info."""
    import weebot.tools.image_gen_tool as igt

    assert hasattr(igt, "logger"), (
        "image_gen_tool module has no 'logger'.  "
        "Add: import logging; logger = logging.getLogger(__name__)"
    )
    logger = getattr(igt, "logger")
    assert callable(logger.info), (
        "image_gen_tool.logger is not a valid logger (no .info method)"
    )
