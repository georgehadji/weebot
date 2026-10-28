"""Profile manager: named workspace profiles under ``~/.weebot/profiles/``."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filesystem profile management (named workspace profiles)
#
# The CLI (`cli/commands/profile.py`) and tests import ``ProfileManager`` /
# ``Profile`` from here. It manages isolated ``~/.weebot/profiles/<name>/``
# workspaces.
# ---------------------------------------------------------------------------

_PROFILES_ROOT = Path.home() / ".weebot" / "profiles"
_DEFAULT_PROFILE = "default"


@dataclass
class Profile:
    """A named profile with isolated configuration."""

    name: str
    path: Path
    created_at: str = ""


class ProfileManager:
    """Manage named profiles for isolated agent configuration.

    Profiles store their own config overrides, skill preferences, and
    memory/session search scope under ``~/.weebot/profiles/<name>/``.

    Args:
        profiles_root: Root directory for profiles. Defaults to
            ``~/.weebot/profiles/``.
    """

    def __init__(self, profiles_root: Path | None = None) -> None:
        self._root = (profiles_root or _PROFILES_ROOT).resolve()

    # ── CRUD ───────────────────────────────────────────────────────

    def create(self, name: str, from_profile: str | None = None) -> Profile:
        """Create a new profile.

        Args:
            name: Profile name (alphanumeric + hyphens/underscores).
            from_profile: Optional existing profile to copy from.

        Returns:
            The created Profile.

        Raises:
            ValueError: If the name is invalid or the profile already exists.
        """
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Invalid profile name: {name!r}. " "Use letters, digits, hyphens, and underscores."
            )

        profile_path = self._root / name
        if profile_path.exists():
            raise ValueError(f"Profile '{name}' already exists.")

        profile_path.mkdir(parents=True, exist_ok=True)

        # Copy from existing profile if specified
        if from_profile:
            src = self._root / from_profile
            if src.exists() and src.is_dir():
                for item in src.iterdir():
                    if item.is_file():
                        shutil.copy2(str(item), str(profile_path / item.name))

        # Write profile metadata

        (profile_path / ".metadata").write_text(
            f"name: {name}\ncreated_at: {datetime.now(UTC).isoformat()}\n", encoding="utf-8"
        )

        logger.info("Created profile '%s' at %s", name, profile_path)
        return Profile(name=name, path=profile_path)

    def get(self, name: str) -> Profile | None:
        """Get a profile by name, or ``None`` if it does not exist."""
        profile_path = self._root / name
        if not profile_path.is_dir():
            return None

        created_at = ""
        meta_file = profile_path / ".metadata"
        if meta_file.exists():
            for line in meta_file.read_text(encoding="utf-8").split("\n"):
                if line.startswith("created_at:"):
                    created_at = line.split(":", 1)[1].strip()

        return Profile(name=name, path=profile_path, created_at=created_at)

    def list_profiles(self) -> list[Profile]:
        """List all available profiles."""
        if not self._root.is_dir():
            return []

        profiles = []
        for entry in sorted(self._root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                profile = self.get(entry.name)
                if profile:
                    profiles.append(profile)
        return profiles

    def delete(self, name: str) -> bool:
        """Delete a profile and its directory.

        Returns ``True`` if deleted, ``False`` if it did not exist.
        Refuses to delete the ``default`` profile.
        """
        if name == _DEFAULT_PROFILE:
            raise ValueError("Cannot delete the default profile.")

        profile_path = self._root / name
        if not profile_path.is_dir():
            return False

        shutil.rmtree(str(profile_path))
        logger.info("Deleted profile '%s'", name)
        return True

    def switch(self, name: str) -> Profile | None:
        """Switch to an existing profile, writing the active marker."""
        profile = self.get(name)
        if profile is None:
            return None

        self._root.parent.mkdir(parents=True, exist_ok=True)
        (self._root.parent / ".active_profile").write_text(name, encoding="utf-8")
        logger.info("Switched to profile '%s'", name)
        return profile

    @staticmethod
    def active_profile_name(profiles_root: Path | None = None) -> str:
        """Return the currently active profile name (``default`` if unset)."""
        root = profiles_root or _PROFILES_ROOT
        marker = root.parent / ".active_profile"
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()
        return _DEFAULT_PROFILE

    def profile_path(self, name: str) -> Path:
        """Return the filesystem path for a profile's directory."""
        return self._root / name

    @property
    def profiles_root(self) -> Path:
        """Return the profiles root directory."""
        return self._root
