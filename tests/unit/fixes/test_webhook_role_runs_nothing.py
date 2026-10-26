"""The webhook role is admin minus anything that runs processes (F66, F67).

Its own comment says webhooks should not exec arbitrary code, yet it held
`spacescraper` (runs `docker-compose up -d`), `computer_use` (types into any
window) and `design_system` (runs `npm install -g`). `search_history` returns
old content from every session, web pages included, and was not fenced.
"""

from __future__ import annotations

from weebot.core.trust_boundary import must_fence, must_taint, trust_of
from weebot.tools.search_history import SearchHistoryTool
from weebot.application.services.tool_registry import RoleBasedToolRegistry

_RUNS_THINGS = {
    "bash", "powershell", "python_execute", "terminate",
    "spacescraper", "computer_use", "design_system",
}


def test_the_webhook_role_holds_no_process_or_desktop_tool():
    webhook = set(RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS["webhook"])
    assert webhook & _RUNS_THINGS == set()


def test_search_history_output_is_untrusted():
    trust = trust_of(SearchHistoryTool)
    assert must_fence(trust) and must_taint(trust, False)
