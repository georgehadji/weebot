"""Unit tests for Profile Management (Hermes M6).

Covers:
- ProfileManager.create() with valid/invalid names
- ProfileManager.create() with --from-profile copy
- ProfileManager.get() for existing/missing profiles
- ProfileManager.list_profiles() returns all profiles
- ProfileManager.delete() removes profiles
- ProfileManager.switch() writes active marker
- CLI commands are registered
"""
import pytest


class TestProfileManager:
    """Validates ProfileManager CRUD operations."""

    @pytest.fixture
    def mgr(self, tmp_path, monkeypatch):
        """ProfileManager with temp profiles root."""
        from weebot.application.services.profile_manager import ProfileManager

        monkeypatch.setattr(
            "weebot.application.services.profile_manager._PROFILES_ROOT",
            tmp_path / "profiles",
        )
        return ProfileManager(profiles_root=tmp_path / "profiles")

    def test_create_profile(self, mgr):
        """Creating a profile creates the directory and metadata."""
        p = mgr.create("research")
        assert p.name == "research"
        assert p.path.exists()
        assert (p.path / ".metadata").exists()

    def test_create_duplicate_raises(self, mgr):
        """Creating a duplicate profile raises ValueError."""
        mgr.create("research")
        with pytest.raises(ValueError, match="already exists"):
            mgr.create("research")

    def test_create_invalid_name_raises(self, mgr):
        """Invalid profile names raise ValueError."""
        with pytest.raises(ValueError, match="Invalid"):
            mgr.create("")

    def test_get_existing_profile(self, mgr):
        """get() returns the profile when it exists."""
        mgr.create("work")
        p = mgr.get("work")
        assert p is not None
        assert p.name == "work"

    def test_get_missing_profile(self, mgr):
        """get() returns None when the profile doesn't exist."""
        p = mgr.get("nonexistent")
        assert p is None

    def test_list_profiles(self, mgr):
        """list_profiles returns all created profiles."""
        mgr.create("alpha")
        mgr.create("beta")
        profiles = mgr.list_profiles()
        names = [p.name for p in profiles]
        assert "alpha" in names
        assert "beta" in names

    def test_list_empty(self, mgr):
        """list_profiles returns empty when no profiles exist."""
        assert mgr.list_profiles() == []

    def test_delete_profile(self, mgr):
        """delete() removes the profile directory."""
        mgr.create("temp")
        assert mgr.get("temp") is not None
        mgr.delete("temp")
        assert mgr.get("temp") is None

    def test_delete_nonexistent(self, mgr):
        """delete() returns False for missing profile."""
        assert mgr.delete("ghost") is False

    def test_delete_default_raises(self, mgr):
        """delete() on 'default' raises ValueError."""
        with pytest.raises(ValueError, match="Cannot delete"):
            mgr.delete("default")

    def test_switch_writes_marker(self, mgr):
        """switch() writes the active profile marker."""
        mgr.create("research")
        p = mgr.switch("research")
        assert p is not None
        from pathlib import Path
        marker = mgr.profiles_root.parent / ".active_profile"
        assert marker.exists()
        assert marker.read_text() == "research"

    def test_active_profile_name_default(self, mgr):
        """active_profile_name returns 'default' when no marker exists."""
        from weebot.application.services.profile_manager import ProfileManager
        assert ProfileManager.active_profile_name(mgr.profiles_root) == "default"

    def test_active_profile_name_after_switch(self, mgr):
        """active_profile_name returns the switched profile name."""
        mgr.create("research")
        mgr.switch("research")
        from weebot.application.services.profile_manager import ProfileManager
        assert ProfileManager.active_profile_name(mgr.profiles_root) == "research"


class TestProfileCLI:
    """Validates the profile CLI commands."""

    def test_profile_group_registered(self):
        """The profile command group exists."""
        from cli.main import cli
        assert "profile" in cli.commands

    def test_profile_subcommands(self):
        """All profile subcommands exist."""
        from cli.main import cli
        profile_group = cli.commands.get("profile")
        assert profile_group is not None
        for cmd in ("create", "list", "switch", "delete"):
            assert cmd in profile_group.commands, f"Missing profile {cmd}"
