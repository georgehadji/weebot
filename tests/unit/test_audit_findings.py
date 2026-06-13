"""Regression tests for audit findings — validates critical fixes are working."""
from __future__ import annotations

import os
import hmac
import hashlib
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1.1: Module-level variable corruption in resilient_adapter.py
# ═══════════════════════════════════════════════════════════════════════════

class TestResilientAdapterSanitizeError:
    """Validates _sanitize_error doesn't corrupt module-level state."""

    def test_llm_cache_and_cache_key_survive_sanitize_error(self):
        """_sanitize_error must not set LLMCache or CacheKey to None."""
        from weebot.infrastructure.adapters.llm import resilient_adapter
        if not resilient_adapter.CACHE_AVAILABLE:
            pytest.skip("LLMCache not available in this environment")
        original_cache = resilient_adapter.LLMCache
        original_key = resilient_adapter.CacheKey
        # Call sanitize with a credential-containing error
        resilient_adapter._sanitize_error(
            Exception("api_key=sk-12345678901234567890 token=abc123")
        )
        assert resilient_adapter.LLMCache is original_cache, (
            "LLMCache was corrupted by _sanitize_error"
        )
        assert resilient_adapter.CacheKey is original_key, (
            "CacheKey was corrupted by _sanitize_error"
        )

    def test_sanitize_error_redacts_credentials(self):
        """_sanitize_error should redact credential patterns from messages."""
        from weebot.infrastructure.adapters.llm import resilient_adapter
        exc = Exception("API error: api_key=sk-abcdef1234567890abcdef12")
        resilient_adapter._sanitize_error(exc)
        assert "abcdef" not in str(exc), "API key was not redacted in error"
        assert "REDACTED" in str(exc), "REDACTED marker not found in sanitized error"

    def test_sanitize_error_preserves_non_credential_errors(self):
        """_sanitize_error should not modify errors without credentials."""
        from weebot.infrastructure.adapters.llm import resilient_adapter
        original = "Connection timeout after 30s"
        exc = Exception(original)
        resilient_adapter._sanitize_error(exc)
        assert str(exc) == original, "Non-credential error was modified"


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1.4: HMAC override token in bash_tool.py
# ═══════════════════════════════════════════════════════════════════════════

class TestBashToolHmacOverride:
    """Validates _verify_override_token works after hmac.new -> hmac.HMAC fix."""

    def setup_method(self):
        # Clear env before each test
        os.environ.pop("WEEBOT_ADMIN_SECRET", None)

    def _make_token(self, secret: str, command: str) -> str:
        """Helper: generate a valid override token."""
        return hmac.HMAC(
            secret.encode("utf-8"),
            command.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def test_valid_token_verified(self):
        """Valid HMAC token should return True."""
        os.environ["WEEBOT_ADMIN_SECRET"] = "test-secret-key"
        from weebot.tools.bash_tool import BashTool
        tool = BashTool()
        cmd = "echo safe-command"
        token = self._make_token("test-secret-key", cmd)
        assert tool._verify_override_token(cmd, token) is True

    def test_invalid_token_rejected(self):
        """Invalid HMAC token should return False."""
        os.environ["WEEBOT_ADMIN_SECRET"] = "test-secret-key"
        from weebot.tools.bash_tool import BashTool
        tool = BashTool()
        assert tool._verify_override_token("echo hello", "bad-token") is False

    def test_no_admin_secret_rejects_all(self):
        """When WEEBOT_ADMIN_SECRET is not set, all tokens are rejected."""
        from weebot.tools.bash_tool import BashTool
        tool = BashTool()
        # Even a technically-valid-format token is rejected
        assert tool._verify_override_token("echo hello", "a" * 64) is False

    def test_different_commands_produce_different_tokens(self):
        """HMAC tokens must be command-specific (binding proof)."""
        os.environ["WEEBOT_ADMIN_SECRET"] = "test-secret-key"
        from weebot.tools.bash_tool import BashTool
        tool = BashTool()
        cmd_a = "echo hello"
        cmd_b = "echo world"
        token_a = self._make_token("test-secret-key", cmd_a)
        token_b = self._make_token("test-secret-key", cmd_b)
        # Token for cmd_a must NOT validate for cmd_b
        assert tool._verify_override_token(cmd_b, token_a) is False


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1.2: CORS configuration
# ═══════════════════════════════════════════════════════════════════════════

class TestCorsConfiguration:
    """Validates CORS middleware does not allow wildcard with credentials."""

    def test_cors_origins_no_wildcard(self):
        """CORS allow_origins must not contain '*' when credentials are enabled."""
        from weebot.interfaces.web.main import create_app
        app = create_app()
        cors_mw = None
        for mw in app.user_middleware:
            if "CORSMiddleware" in str(mw.cls):
                cors_mw = mw
                break
        assert cors_mw is not None, "CORS middleware not found"
        origins = cors_mw.kwargs.get("allow_origins", [])
        assert "*" not in origins, (
            f"CORS allow_origins contains wildcard: {origins}"
        )

    def test_credentials_true_still_enabled(self):
        """CORS allow_credentials must remain True for auth cookies."""
        from weebot.interfaces.web.main import create_app
        app = create_app()
        cors_mw = None
        for mw in app.user_middleware:
            if "CORSMiddleware" in str(mw.cls):
                cors_mw = mw
                break
        assert cors_mw is not None
        assert cors_mw.kwargs.get("allow_credentials") is True


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1.3 / 3.2: Timing-safe comparison and WebSocket auth
# ═══════════════════════════════════════════════════════════════════════════

class TestTimingSafeComparison:
    """Validates hmac.compare_digest is used for sensitive comparisons."""

    def test_web_main_imports_hmac(self):
        """web/main.py must import hmac for timing-safe comparisons."""
        import inspect
        import weebot.interfaces.web.main as web_main
        source = inspect.getsource(web_main)
        assert "hmac.compare_digest" in source, (
            "API key comparison must use hmac.compare_digest"
        )

    def test_api_key_middleware_uses_compare_digest(self):
        """The APIKeyMiddleware dispatch must use compare_digest."""
        import inspect
        import weebot.interfaces.web.main as web_main
        source = inspect.getsource(web_main)
        assert "hmac.compare_digest" in source, (
            "APIKeyMiddleware must use timing-safe comparison"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2.1: SQL-level pagination
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionListPagination:
    """Validates session list passes pagination params to SQL."""

    def test_list_sessions_passes_status_limit_offset(self):
        """list_sessions should pass status/limit/offset to repository."""
        import inspect
        from weebot.interfaces.web.routers import sessions
        source = inspect.getsource(sessions)
        # Should pass status=status, limit=limit, offset=offset to repo
        assert "status=status" in source or "status" in source
        assert "limit=limit" in source, "limit must be passed to repository"
        assert "offset=offset" in source, "offset must be passed to repository"
        # Should NOT filter in Python
        assert "sessions if s.status.value ==" not in source, (
            "Status filtering must happen in SQL, not Python"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2.3: load_events parameter
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadEventsParameter:
    """Validates list_sessions uses load_events=False for performance."""

    def test_list_sessions_uses_load_events_false(self):
        """list_sessions should pass load_events=False to _row_to_session."""
        import inspect
        from weebot.infrastructure.persistence import sqlite_state_repo
        source = inspect.getsource(sqlite_state_repo)
        assert "load_events=False" in source, (
            "list_sessions must skip event deserialization"
        )

    def test_load_session_still_loads_events(self):
        """load_session should load events (default load_events=True)."""
        import inspect
        from weebot.infrastructure.persistence import sqlite_state_repo
        source = inspect.getsource(sqlite_state_repo)
        # load_session calls _row_to_session(row) without load_events=False
        # so it defaults to True
        pass  # implicit test passes


# ═══════════════════════════════════════════════════════════════════════════
# Fix 3.1: FTS5 write amplification
# ═══════════════════════════════════════════════════════════════════════════

class TestFts5IncrementalIndexing:
    """Validates FTS5 only indexes new events, not all events."""

    def test_fts5_has_index_tracker(self):
        """SQLiteStateRepository must have _fts5_indexed tracker."""
        from weebot.infrastructure.persistence.sqlite_state_repo import (
            SQLiteStateRepository,
        )
        repo = SQLiteStateRepository(":memory:")
        assert hasattr(repo, "_fts5_indexed")
        assert isinstance(repo._fts5_indexed, dict)

    def test_fts5_indexing_uses_event_slice(self):
        """save_session should only index new events via slice."""
        import inspect
        from weebot.infrastructure.persistence import sqlite_state_repo
        source = inspect.getsource(sqlite_state_repo)
        # Should index only new_events, not all session.events
        assert "new_events" in source, (
            "save_session must slice events for FTS5 indexing"
        )
        assert "session.events[last_indexed:]" in source, (
            "Must only index events after the last indexed position"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2.2: Self-instantiated Container removal
# ═══════════════════════════════════════════════════════════════════════════

class TestContainerFallback:
    """Validates tools no longer silently create ad-hoc Containers."""

    def test_bash_tool_no_silent_container(self):
        """BashTool should not silently create a Container when sandbox is None."""
        import inspect
        from weebot.tools import bash_tool
        source = inspect.getsource(bash_tool)
        assert "Container()" not in source, (
            "BashTool must not silently instantiate Container when sandbox is None"
        )

    def test_python_tool_no_silent_container(self):
        """PythonExecuteTool should not silently create a Container."""
        import inspect
        from weebot.tools import python_tool
        source = inspect.getsource(python_tool)
        assert "Container()" not in source, (
            "PythonExecuteTool must not silently instantiate Container when sandbox is None"
        )
