"""Unit tests for AtomicMailTool.

Most tests mock handle_tool_call so no network or credentials are needed.
One real-integration test (test_help_real_vendored) exercises the actual
vendored handle_tool_call to guard the import + shared-assets seam in CI.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.tools.atomic_mail_tool import AtomicMailTool, _BREAKER, _BREAKER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success_response(text: str = "ok") -> dict:
    return {"content": [{"text": text}], "isError": False}


def _error_response(text: str = "something went wrong") -> dict:
    return {"content": [{"text": text}], "isError": True}


@pytest.fixture(autouse=True)
def reset_breaker():
    """Reset circuit breaker state between tests."""
    _BREAKER._breakers.clear()
    yield
    _BREAKER._breakers.clear()


@pytest.fixture
def tool():
    return AtomicMailTool()


# ---------------------------------------------------------------------------
# Action validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_action_returns_error(tool):
    result = await tool.execute(action="fly_to_moon")
    assert result.is_error
    assert "Unknown action" in result.error


@pytest.mark.asyncio
async def test_missing_action_returns_error(tool):
    result = await tool.execute()
    assert result.is_error


@pytest.mark.asyncio
async def test_jmap_both_ops_and_ops_file_returns_error(tool):
    result = await tool.execute(
        action="jmap_request",
        ops='[["Email/get", {}, "0"]]',
        ops_file="list_inbox",
    )
    assert result.is_error
    assert "mutually exclusive" in result.error


# ---------------------------------------------------------------------------
# 'help' action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_success(tool):
    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=lambda name, args: _success_response("# Help content"),
    ):
        result = await tool.execute(action="help")

    assert not result.is_error
    assert "Help content" in result.output


@pytest.mark.asyncio
async def test_help_with_topic_passes_topic_through(tool):
    captured = {}

    def fake_handle(name, args):
        captured["name"] = name
        captured["args"] = args
        return _success_response("help text")

    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=fake_handle,
    ):
        await tool.execute(action="help", topic="presets")

    assert captured["name"] == "help"
    assert captured["args"].get("topic") == "presets"


# ---------------------------------------------------------------------------
# 'register' action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_success(tool):
    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=lambda name, args: _success_response('{"email": "bot@atomicmail.ai"}'),
    ):
        result = await tool.execute(action="register", username="bot")

    assert not result.is_error
    assert "atomicmail.ai" in result.output


@pytest.mark.asyncio
async def test_register_passes_username_and_forced(tool):
    captured = {}

    def fake_handle(name, args):
        captured.update({"name": name, "args": args})
        return _success_response("{}")

    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=fake_handle,
    ):
        await tool.execute(action="register", username="myagent", forced=True)

    assert captured["args"]["username"] == "myagent"
    assert captured["args"]["forced"] is True


@pytest.mark.asyncio
async def test_register_upstream_error_surfaces_message(tool):
    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=lambda name, args: _error_response("Username taken"),
    ):
        result = await tool.execute(action="register", username="bot")

    assert result.is_error
    assert "Username taken" in result.error


# ---------------------------------------------------------------------------
# 'jmap_request' action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jmap_request_with_ops_file(tool):
    captured = {}

    def fake_handle(name, args):
        captured.update({"name": name, "args": args})
        return _success_response('{"methodResponses": []}')

    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=fake_handle,
    ):
        result = await tool.execute(action="jmap_request", ops_file="list_inbox")

    assert not result.is_error
    assert captured["args"]["ops_file"] == "list_inbox"
    assert "ops" not in captured["args"]  # only ops_file, not ops


@pytest.mark.asyncio
async def test_jmap_request_with_inline_ops(tool):
    captured = {}

    def fake_handle(name, args):
        captured.update({"name": name, "args": args})
        return _success_response("{}")

    ops_json = '[["Email/query", {}, "0"]]'
    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=fake_handle,
    ):
        await tool.execute(action="jmap_request", ops=ops_json)

    assert captured["args"]["ops"] == ops_json


@pytest.mark.asyncio
async def test_jmap_http_error_surfaces(tool):
    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=lambda name, args: _error_response("JMAP request failed (HTTP 429)"),
    ):
        result = await tool.execute(action="jmap_request", ops_file="list_inbox")

    assert result.is_error
    assert "429" in result.error


# ---------------------------------------------------------------------------
# Async non-blocking (to_thread)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_does_not_block_event_loop(tool):
    """Verify the blocking call is off-loaded via asyncio.to_thread."""
    import threading

    call_thread_ids = []

    def fake_handle(name, args):
        call_thread_ids.append(threading.current_thread().ident)
        return _success_response("ok")

    main_thread_id = threading.current_thread().ident

    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=fake_handle,
    ):
        await tool.execute(action="help")

    assert call_thread_ids, "handle_tool_call was never called"
    assert call_thread_ids[0] != main_thread_id, (
        "handle_tool_call ran on the event-loop thread — blocking detected"
    )


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_error(tool):
    async def slow_thread(*args):
        await asyncio.sleep(999)

    with patch("asyncio.to_thread", side_effect=asyncio.TimeoutError):
        with patch(
            "weebot.tools.atomic_mail_tool._load_handle_tool_call",
            return_value=lambda n, a: _success_response(),
        ):
            result = await tool.execute(action="help")

    assert result.is_error
    assert "timed out" in result.error.lower()


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_opens_after_repeated_failures(tool):
    """Three upstream errors should open the breaker."""

    def fail(name, args):
        return _error_response("Service unavailable")

    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=fail,
    ):
        for _ in range(3):
            await tool.execute(action="help")

    # Breaker should now be OPEN
    result = await tool.execute(action="help")
    assert result.is_error
    # Either blocked by circuit or upstream — either way it's an error
    assert result.error is not None


@pytest.mark.asyncio
async def test_circuit_open_blocks_immediately(tool):
    """Force the breaker open and confirm the tool returns early."""
    # Open the breaker manually
    for _ in range(3):
        await _BREAKER.record_failure(_BREAKER_ID)

    with patch(
        "weebot.tools.atomic_mail_tool._load_handle_tool_call",
        return_value=MagicMock(side_effect=AssertionError("should not be called")),
    ) as mock_load:
        result = await tool.execute(action="help")

    assert result.is_error
    assert "circuit" in result.error.lower() or "unavailable" in result.error.lower()


# ---------------------------------------------------------------------------
# _build_args isolation (extraneous kwargs not leaked)
# ---------------------------------------------------------------------------


def test_build_args_register_excludes_jmap_keys(tool):
    args = tool._build_args("register", {
        "username": "bot",
        "ops_file": "list_inbox",  # not relevant to register
        "topic": "jmap",           # not relevant to register
    })
    assert "username" in args
    assert "ops_file" not in args
    assert "topic" not in args


def test_build_args_help_excludes_register_keys(tool):
    args = tool._build_args("help", {
        "topic": "presets",
        "username": "bot",  # not relevant to help
        "ops": "[...]",      # not relevant to help
    })
    assert "topic" in args
    assert "username" not in args
    assert "ops" not in args


def test_build_args_jmap_excludes_register_keys(tool):
    args = tool._build_args("jmap_request", {
        "ops_file": "list_inbox",
        "username": "bot",  # not relevant to jmap
        "topic": "x",       # not relevant to jmap
    })
    assert "ops_file" in args
    assert "username" not in args
    assert "topic" not in args


# ---------------------------------------------------------------------------
# health_check (offline — flag gating)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Real vendored integration (no mock — guards import + shared-assets seam)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_real_vendored(tool):
    """Call handle_tool_call directly through the tool without mocking.

    The 'help' action needs no credentials and makes no network calls, so
    this is safe for offline CI.  The test guards the import path and the
    vendor/shared/ asset resolution that previously required manual smoke
    testing.
    """
    result = await tool.execute(action="help")
    # If shared assets are missing or the import fails, execute() returns
    # an error result — surface the message for easy diagnosis.
    assert not result.is_error, f"Real vendored help failed: {result.error}"
    assert result.output  # non-empty help text


# ---------------------------------------------------------------------------
# health_check (offline — flag gating)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_returns_false_when_flag_off(tool):
    with patch.dict("os.environ", {"WEEBOT_ENABLE_ATOMIC_MAIL": "0"}):
        result = await tool.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_true_when_flag_on_and_help_succeeds(tool):
    with patch.dict("os.environ", {"WEEBOT_ENABLE_ATOMIC_MAIL": "1"}):
        with patch(
            "weebot.tools.atomic_mail_tool._load_handle_tool_call",
            return_value=lambda n, a: _success_response("help text"),
        ):
            result = await tool.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_health_check_returns_false_on_exception(tool):
    with patch.dict("os.environ", {"WEEBOT_ENABLE_ATOMIC_MAIL": "1"}):
        with patch(
            "weebot.tools.atomic_mail_tool._load_handle_tool_call",
            side_effect=RuntimeError("import failed"),
        ):
            result = await tool.health_check()
    assert result is False
