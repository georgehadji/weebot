"""ProfileManager — named profile management with isolated config.

Profiles are stored under ``~/.weebot/profiles/<name>/`` and contain
isolated config, skill overrides, and environment settings.

Inspired by Hermes Agent's ``hermes profile`` system.
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

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

    Profiles store their own:
    - Config overrides (env vars, model selection)
    - Skill preferences (active/inactive skills)
    - Memory and session search scope

    Args:
        profiles_root: Root directory for profiles. Defaults to
            ``~/.weebot/profiles/``.
    """

    def __init__(self, profiles_root: Optional[Path] = None) -> None:
        self._root = (profiles_root or _PROFILES_ROOT).resolve()

    # ── CRUD ───────────────────────────────────────────────────────

    def create(self, name: str, from_profile: Optional[str] = None) -> Profile:
        """Create a new profile.

        Args:
            name: Profile name (alphanumeric + hyphens).
            from_profile: Optional existing profile to copy from.

        Returns:
            The created Profile.

        Raises:
            ValueError: If the name is invalid or the profile already exists.
        """
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Invalid profile name: {name!r}. "
                "Use letters, digits, hyphens, and underscores."
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
        from datetime import datetime, timezone
        (profile_path / ".metadata").write_text(
            f"name: {name}\ncreated_at: {datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )

        logger.info("Created profile '%s' at %s", name, profile_path)
        return Profile(name=name, path=profile_path)

    def get(self, name: str) -> Optional[Profile]:
        """Get a profile by name.

        Returns ``None`` if the profile does not exist.
        """
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

        Returns ``True`` if the profile was deleted, ``False`` if it
        did not exist.  Refuses to delete the ``default`` profile.
        """
        if name == _DEFAULT_PROFILE:
            raise ValueError("Cannot delete the default profile.")

        profile_path = self._root / name
        if not profile_path.is_dir():
            return False

        shutil.rmtree(str(profile_path))
        logger.info("Deleted profile '%s'", name)
        return True

    def switch(self, name: str) -> Optional[Profile]:
        """Switch to an existing profile.

        Returns the profile, or ``None`` if it does not exist.
        """
        profile = self.get(name)
        if profile is None:
            return None

        # Write the active profile marker
        self._root.parent.mkdir(parents=True, exist_ok=True)
        (self._root.parent / ".active_profile").write_text(name, encoding="utf-8")
        logger.info("Switched to profile '%s'", name)
        return profile

    @staticmethod
    def active_profile_name(profiles_root: Optional[Path] = None) -> str:
        """Return the name of the currently active profile.

        Reads the marker from the ``.active_profile`` file next to the
        profiles root directory.  Returns ``"default"`` if no active
        profile is set.

        Args:
            profiles_root: Optional explicit root.  Uses the default
                ``~/.weebot/profiles/`` if not provided.
        """
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
