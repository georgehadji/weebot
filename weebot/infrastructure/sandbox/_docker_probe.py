"""Synchronous Docker readiness probe for ``create_default_sandbox`` (ADR-014).

Kept out of ``factory.py``, which also holds async code: the architecture
fitness test bans blocking calls in modules with async functions, and this
check runs once, synchronously, while the default sandbox is chosen.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def docker_ready(image: str) -> bool:
    """True when the Docker daemon answers and *image* is built locally."""
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [docker, "image", "inspect", image],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("docker readiness check failed: %r", exc)
        return False
    return proc.returncode == 0
