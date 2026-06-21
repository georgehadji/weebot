"""External (live-network) atomicmail tests — skipped unless ATOMICMAIL_TEST_LIVE=1.

These are stubs for the 6 network-dependent upstream test modules:
  test_auth_http, test_jmap_request, test_session_register,
  test_mcp_adapter, test_cli_adapter, test_langchain_atomicmail.

When a live-Alpha CI stage with valid credentials is available, port the
upstream tests here and remove the skip guard.  Until then they are registered
so the test suite stays aware of the coverage gap without requiring a network.

Usage:
  ATOMICMAIL_TEST_LIVE=1 pytest -m external tests/unit/atomicmail/test_external_network.py
"""
from __future__ import annotations

import os

import pytest

_LIVE = os.environ.get("ATOMICMAIL_TEST_LIVE", "").strip().lower() in ("1", "true", "yes")
_SKIP = pytest.mark.skipif(not _LIVE, reason="Set ATOMICMAIL_TEST_LIVE=1 to run live-network tests")


@pytest.mark.external
@_SKIP
def test_auth_http_stub() -> None:
    """Port upstream test_auth_http — JWT acquisition and refresh over HTTP."""
    raise NotImplementedError("Port from atomic-mail-agentic-main/py/tests/test_auth_http.py")


@pytest.mark.external
@_SKIP
def test_jmap_request_stub() -> None:
    """Port upstream test_jmap_request — live JMAP round-trip (send + list)."""
    raise NotImplementedError("Port from atomic-mail-agentic-main/py/tests/test_jmap_request.py")


@pytest.mark.external
@_SKIP
def test_session_register_stub() -> None:
    """Port upstream test_session_register — full PoW registration flow."""
    raise NotImplementedError("Port from atomic-mail-agentic-main/py/tests/test_session_register.py")


@pytest.mark.external
@_SKIP
def test_mcp_adapter_stub() -> None:
    """Port upstream test_mcp_adapter — MCP tool-call round-trip over network."""
    raise NotImplementedError("Port from atomic-mail-agentic-main/py/tests/test_mcp_adapter.py")


@pytest.mark.external
@_SKIP
def test_cli_adapter_stub() -> None:
    """Port upstream test_cli_adapter — CLI wrapper integration test."""
    raise NotImplementedError("Port from atomic-mail-agentic-main/py/tests/test_cli_adapter.py")


@pytest.mark.external
@_SKIP
def test_langchain_atomicmail_stub() -> None:
    """Port upstream test_langchain_atomicmail — LangChain tool integration."""
    raise NotImplementedError("Port from atomic-mail-agentic-main/py/tests/test_langchain_atomicmail.py")
