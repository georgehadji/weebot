"""Every discoverable tool has a role, and every role names a real tool (F53).

`youtube_download` and `desktop_a11y` were in no role, though built-in skills
tell the agent to use them; `detect_elements`, `screenshot_ocr`,
`ocr_structured` and `web_scraper` likewise. `browser_navigator` was listed in
`admin` and `webhook` but is not a BaseTool, so every build logged "not found".
"""

from __future__ import annotations

from weebot.tools.tool_registry import RoleBasedToolRegistry


def test_every_tool_has_a_role_and_every_role_entry_exists():
    tools = set(RoleBasedToolRegistry.build_tool_class_map())
    in_roles = {n for names in RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS.values() for n in names}
    assert sorted(tools - in_roles) == []
    assert sorted(in_roles - tools) == []
