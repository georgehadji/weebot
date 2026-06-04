"""Configuration adapter — wraps WeebotSettings behind a ConfigPort.

Created during architecture remediation (step-10).  Register in DI as:
    container.register(ConfigPort, lambda: ConfigAdapter())
"""
from __future__ import annotations

from typing import Any, Optional

from weebot.application.ports.config_port import ConfigPort


class ConfigAdapter(ConfigPort):
    """Adapter that reads from weebot.config.settings.WeebotSettings."""

    def __init__(self) -> None:
        from weebot.config.settings import WeebotSettings
        self._settings = WeebotSettings()

    def _resolve(self, key: str) -> Any:
        """Resolve a config key from settings or fall back to constants."""
        # First try the pydantic-settings model
        if hasattr(self._settings, key):
            return getattr(self._settings, key)

        # Then try constants
        try:
            from weebot.config import constants as C
            return getattr(C, key)
        except AttributeError:
            return None

        # Then try model_refs
        try:
            from weebot.config import model_refs as M
            return getattr(M, key)
        except AttributeError:
            return None

    def get(self, key: str, default: Any = None) -> Any:
        value = self._resolve(key)
        return value if value is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        value = self._resolve(key)
        if isinstance(value, int):
            return value
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self._resolve(key)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self._resolve(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value) if value is not None else default

    def get_str(self, key: str, default: str = "") -> str:
        value = self._resolve(key)
        return str(value) if value is not None else default

    @property
    def workspace_root(self) -> str:
        from weebot.config.constants import WORKSPACE_ROOT
        return str(WORKSPACE_ROOT)

    @property
    def logs_dir(self) -> str:
        from weebot.config.constants import LOGS_DIR
        return str(LOGS_DIR)

    @property
    def default_model(self) -> Optional[str]:
        return getattr(self._settings, "MODEL_NAME", None)

    @property
    def sandbox_mode(self) -> str:
        return getattr(self._settings, "sandbox_mode", "auto")
