"""ToolConfig — configuration dataclass for tool adapters.

Allows tools to receive configuration via constructor injection instead of
importing WeebotSettings directly, decoupling the tools layer from the
config/settings module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolConfig:
    """Configuration values consumed by tool adapters.

    Created once by the DI container from WeebotSettings and injected
    into tool constructors. Injecting this (rather than importing
    WeebotSettings inside a tool) keeps the tools layer decoupled from the
    config/settings module.
    """

    bash_timeout: int = 30
    python_timeout: int = 30
    sandbox_max_output_bytes: int = 65_536
    max_tool_timeout: int = 300  # env: MAX_TOOL_TIMEOUT — ceiling for tool timeout params

    # External research-tool endpoints (Berb / Reasoner / Spacescraper).
    # Defaults mirror WeebotSettings; a value of None means "unset — fall back
    # to the corresponding environment variable at call time".
    berb_api_url: str | None = None  # env: BERB_API_URL
    berb_api_key: str | None = None  # env: BERB_API_KEY
    berb_dir: str | None = None  # env: BERB_DIR
    reasoner_api_url: str | None = None  # env: REASONER_API_URL
    reasoner_api_key: str | None = None  # env: REASONER_API_KEY
    reasoner_dir: str | None = None  # env: REASONER_DIR
    scraper_api_url: str | None = None  # env: SCRAPER_API_URL
    scraper_api_key: str | None = None  # env: SCRAPER_API_KEY
    scraper_dir: str | None = None  # env: SCRAPER_DIR
    moli_path: str | None = None  # env: MOLI_PATH — moli.exe for the moli_fetch tool
    agent_reach_path: str | None = None  # env: AGENT_REACH_PATH — agent-reach.exe
    camofox_path: str | None = None  # env: CAMOFOX_PATH — camofox-browser package folder
    remotion_host: str | None = None  # env: REMOTION_HOST — folder with Remotion installed

    def __post_init__(self):
        if not (30 <= self.max_tool_timeout <= 3600):
            raise ValueError("max_tool_timeout must be between 30 and 3600")
        if self.bash_timeout < 1:
            raise ValueError("bash_timeout must be >= 1")
        if self.python_timeout < 1:
            raise ValueError("python_timeout must be >= 1")


# Default config matching WeebotSettings defaults
DEFAULT_TOOL_CONFIG = ToolConfig()


def tool_config_from_settings(settings) -> ToolConfig:
    """The ToolConfig for *settings*: every field WeebotSettings also has.

    The rest (tool binary paths, ``max_tool_timeout``) stay at their defaults,
    which for the paths means "read the environment at call time".
    """
    from dataclasses import fields

    return ToolConfig(
        **{
            f.name: getattr(settings, f.name)
            for f in fields(ToolConfig)
            if f.name in type(settings).model_fields
        }
    )


def resolve_setting(
    config: ToolConfig | None, attr: str, env_var: str, default: str | None = None
) -> str | None:
    """Resolve a tool setting: injected ToolConfig first, then the environment.

    Lets a tool read configuration without importing WeebotSettings — the
    injected ``config`` takes priority, otherwise the environment variable is
    read at call time (matching WeebotSettings' env-driven behavior).
    """
    if config is not None:
        value = getattr(config, attr, None)
        if value is not None:
            return value
    return os.getenv(env_var, default)


def require_setting(value: str | None, env_var: str, purpose: str) -> str:
    """Return *value*, or raise a clear error naming *env_var* when it is unset."""
    if not value:
        raise RuntimeError(f"{env_var} is not set; {purpose} needs it")
    return value
