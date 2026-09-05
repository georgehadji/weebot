"""Wave 6 of the V7 defect hunt — external interfaces.

* ``/ws/sessions/{session_id}`` authenticated the caller and then never checked
  that the caller owns the session. The HTTP path for the same resource does
  (``routers/sessions.py:126``). Authentication is not authorisation: any
  authenticated caller could subscribe to any session's event stream.
* ``.env.example`` shipped ``WEEBOT_ENFORCE_SESSION_OWNERSHIP=false`` while the
  code defaults it to ``true`` -- so copying the template, which is the
  documented way to configure the app, silently disabled session isolation.
* Two ``@app.exception_handler(Exception)`` registrations existed. Starlette
  keys handlers by exception class, so the later one replaced the earlier
  outright and the two disagreed on the ``error_code`` they returned.
"""

from __future__ import annotations

import pathlib
import re

import pytest


class TestEnvTemplateDoesNotWeakenDefaults:
    """A template that ships a weaker default than the code is a deployment defect."""

    @staticmethod
    def _repo_root() -> pathlib.Path:
        return pathlib.Path(__file__).resolve().parents[3]

    def test_session_ownership_enforcement_is_not_disabled_by_the_template(self):
        env = (self._repo_root() / ".env.example").read_text(encoding="utf-8")
        match = re.search(r"^WEEBOT_ENFORCE_SESSION_OWNERSHIP=(\S*)", env, re.MULTILINE)

        assert match is not None, "the template no longer documents this setting"
        assert match.group(1).lower() not in ("false", "0", "no"), (
            "the shipped template disables session-ownership enforcement that "
            "weebot/interfaces/web/auth.py:223 defaults to on"
        )

    def test_the_code_default_is_still_on(self):
        """If this flips, the template check above stops meaning anything."""
        source = (
            self._repo_root() / "weebot" / "interfaces" / "web" / "auth.py"
        ).read_text(encoding="utf-8")

        assert 'os.environ.get("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true")' in source


class TestOnlyOneCatchAllExceptionHandler:
    def test_exception_is_registered_exactly_once(self):
        """Starlette keeps one handler per exception class; a duplicate is dead code."""
        source = (
            pathlib.Path(__file__).resolve().parents[3]
            / "weebot" / "interfaces" / "web" / "main.py"
        ).read_text(encoding="utf-8")

        # Anchored to the start of a line so prose mentioning the decorator --
        # including the comment left where the duplicate used to be -- is not
        # counted as a registration.
        registrations = re.findall(
            r"^\s*@app\.exception_handler\(Exception\)\s*$", source, re.MULTILINE
        )

        assert len(registrations) == 1, (
            f"{len(registrations)} catch-all handlers registered; all but the last "
            "are silently replaced"
        )


class TestWebSocketChecksOwnership:
    """The endpoint must consult verify_session_ownership, as the HTTP path does."""

    @staticmethod
    def _ws_endpoint_source() -> str:
        source = (
            pathlib.Path(__file__).resolve().parents[3]
            / "weebot" / "interfaces" / "web" / "main.py"
        ).read_text(encoding="utf-8")
        start = source.index('@app.websocket("/ws/sessions/{session_id}")')
        end = source.index("# Serve static files", start)
        return source[start:end]

    def test_endpoint_verifies_ownership(self):
        body = self._ws_endpoint_source()

        assert "verify_session_ownership" in body, (
            "the session WebSocket authenticates but never authorises"
        )

    def test_ownership_failure_closes_the_socket(self):
        body = self._ws_endpoint_source()

        assert "4003" in body, "a denied subscription must close, not proceed"
        # The close must happen before the connection is registered with the
        # manager, or events are delivered to an unauthorised subscriber.
        assert body.index("verify_session_ownership") < body.index("manager.connect")

    def test_authentication_check_is_still_first(self):
        """No-regression: authorisation is additional to authentication."""
        body = self._ws_endpoint_source()

        assert body.index("_websocket_auth") < body.index("verify_session_ownership")
        assert "4001" in body
