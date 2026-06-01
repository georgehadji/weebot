"""ToolConfig — configuration dataclass for tool adapters.

Allows tools to receive configuration via constructor injection instead of
importing WeebotSettings directly, decoupling the tools layer from the
config/settings module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolConfig:
    """Configuration values consumed by tool adapters.

    Created once by the DI container from WeebotSettings and injected
    into tool constructors.
    """

    def __post_init__(self):
        if not (30 <= self.max_tool_timeout <= 3600):
            raise ValueError("max_tool_timeout must be between 30 and 3600")
        if self.bash_timeout < 1:
            raise ValueError("bash_timeout must be >= 1")
        if self.python_timeout < 1:
            raise ValueError("python_timeout must be >= 1")
    """Configuration values consumed by tool adapters.

    Created once by the DI container from WeebotSettings and injected
    into tool constructors.
    """
    bash_timeout: int = 30
    python_timeout: int = 30
    sandbox_max_output_bytes: int = 65_536
    max_tool_timeout: int = 300   # env: MAX_TOOL_TIMEOUT — ceiling for tool timeout params


# Default config matching WeebotSettings defaults
DEFAULT_TOOL_CONFIG = ToolConfig()
