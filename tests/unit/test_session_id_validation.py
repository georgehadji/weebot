"""Tests for M10 session ID validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from weebot.domain.models.session import Session
from weebot.interfaces.web.schemas.requests import CreateSessionRequest


class TestSessionIdValidation:
    def test_valid_session_id(self):
        session = Session(id="abc123", user_id="u", agent_id="a")
        assert session.id == "abc123"

    def test_invalid_session_id_traversal(self):
        with pytest.raises((ValueError, ValidationError)):
            Session(id="../../etc/passwd", user_id="u", agent_id="a")

    def test_invalid_session_id_empty(self):
        session = Session(id="", user_id="u", agent_id="a")
        assert session.id == ""

    def test_invalid_session_id_backslash(self):
        with pytest.raises((ValueError, ValidationError)):
            Session(id="a\\b", user_id="u", agent_id="a")

    def test_create_session_request_pattern(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest(prompt="hello", session_id="../../x")
