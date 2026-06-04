"""Configuration port — abstract interface for application config access.

Created during architecture remediation (step-10) to replace direct
``from weebot.config.settings import WeebotSettings`` across all layers.
Injected via the DI container.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class ConfigPort(ABC):
    """Abstract interface for reading application configuration."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        ...

    @abstractmethod
    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer configuration value."""
        ...

    @abstractmethod
    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float configuration value."""
        ...

    @abstractmethod
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean configuration value."""
        ...

    @abstractmethod
    def get_str(self, key: str, default: str = "") -> str:
        """Get a string configuration value."""
        ...

    @property
    @abstractmethod
    def workspace_root(self) -> str:
        """Return the workspace root path."""
        ...

    @property
    @abstractmethod
    def logs_dir(self) -> str:
        """Return the logs directory path."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> Optional[str]:
        """Return the default model identifier."""
        ...

    @property
    @abstractmethod
    def sandbox_mode(self) -> str:
        """Return the sandbox mode ('auto', 'native', 'docker', 'wsl2')."""
        ...
