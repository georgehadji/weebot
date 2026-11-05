"""The entry points' hook for secret references (H19), kept in the composition root.

Interfaces may import the DI package but not infrastructure.
"""

from __future__ import annotations


def install_secret_sources() -> None:
    """Resolve ``op://`` and ``bws://`` references in the environment, after ``load_dotenv``."""
    from weebot.infrastructure.secrets.resolver import install_secret_sources as install

    install()
