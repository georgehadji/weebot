"""The sessions router turns a Session into SessionResponse (found in plan B2c).

`POST /api/sessions` returned 500 for every new session from the web UI:
`_session_to_response` passed the `SessionContext` model where
`SessionResponse.context` is a dict. `GET /api/sessions` hits the same code
for every listed session, so it fails as soon as one session exists.
"""

from __future__ import annotations

from weebot.domain.models.session import Session
from weebot.interfaces.web.routers.sessions import _session_to_response


def test_a_session_with_context_converts():
    session = Session(id="s1", user_id="u", agent_id="a", context={"last_prompt": "hi"})
    response = _session_to_response(session)
    assert response.id == "s1"
    assert isinstance(response.context, dict)
    assert "hi" in str(response.context)
