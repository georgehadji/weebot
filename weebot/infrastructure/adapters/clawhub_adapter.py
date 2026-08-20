"""ClawHub git operations adapter — wraps subprocess calls for git clone/pull.

This adapter is owned by the infrastructure layer so that the application
layer (clawhub_importer.py) does not import ``subprocess`` directly.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_URL = "https://github.com/VoltAgent/awesome-openclaw-skills.git"


class ClawHubGitAdapter:
    """Handle git operations for the awesome-openclaw-skills repository.

    Encapsulates subprocess calls so that application code does not
    depend on ``subprocess`` directly.
    """

    def __init__(self, repo_path: Path | None = None):
        self._repo_path = repo_path

    @property
    def repo_path(self) -> Path:
        if self._repo_path is None:
            import tempfile

            self._repo_path = Path(tempfile.gettempdir()) / "awesome-openclaw-skills"
        return self._repo_path

    def clone_or_update(self) -> None:
        """Clone the repo if not present, otherwise pull latest."""
        if self.repo_path.exists():
            logger.info("Updating repo at %s", self.repo_path)
            subprocess.run(
                ["git", "-C", str(self.repo_path), "pull", "--ff-only"],
                capture_output=True,
                text=True,
            )
        else:
            logger.info("Cloning repo to %s", self.repo_path)
            subprocess.run(
                ["git", "clone", "--depth", "1", _REPO_URL, str(self.repo_path)],
                capture_output=True,
                text=True,
            )
