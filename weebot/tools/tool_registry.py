"""Re-export of ``weebot.application.services.tool_registry``.

``RoleBasedToolRegistry`` is authorization policy over the domain ``BaseTool``, so it
moved to the application layer (plan 3.2, pattern Q5). This path keeps outside scripts
and skills that import the old location working; new code imports the new one.
"""

from weebot.application.services.tool_registry import *  # noqa: F401,F403
from weebot.application.services.tool_registry import RoleBasedToolRegistry  # noqa: F401
