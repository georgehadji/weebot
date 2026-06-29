"""Tests for OSWorldSettings configuration."""
import pytest
from weebot.config.settings import OSWorldSettings


class TestOSWorldSettings:
    """OSWorldSettings validation tests."""

    def test_defaults(self):
        """All fields have correct default values."""
        s = OSWorldSettings()
        assert s.osworld_sandbox_type == "docker"
        assert s.osworld_host == "localhost"
        assert s.osworld_port == 8080
        assert s.osworld_vm_id == "osworld-ubuntu-1"
        assert s.osworld_api_token == ""
        assert s.osworld_connect_timeout == 30
        assert s.osworld_action_timeout == 15
        assert s.osworld_boot_timeout == 120
        assert s.osworld_max_retries == 3
        assert s.osworld_screen_width == 1920
        assert s.osworld_screen_height == 1080
        assert s.osworld_dpi_scale == 1.0

    def test_base_url(self):
        """base_url constructed from host and port."""
        s = OSWorldSettings()
        assert s.base_url == "http://localhost:8080"

        s2 = OSWorldSettings(osworld_host="192.168.1.100", osworld_port=9000)
        assert s2.base_url == "http://192.168.1.100:9000"

    def test_screen_resolution(self):
        """screen_resolution returns (width, height) tuple."""
        s = OSWorldSettings(osworld_screen_width=2560, osworld_screen_height=1440)
        assert s.screen_resolution == (2560, 1440)

    def test_dpi_bounds_valid(self):
        """DPI scale within bounds 0.5..4.0 is accepted."""
        OSWorldSettings(osworld_dpi_scale=1.0)
        OSWorldSettings(osworld_dpi_scale=0.5)
        OSWorldSettings(osworld_dpi_scale=4.0)
        OSWorldSettings(osworld_dpi_scale=2.5)

    def test_dpi_below_minimum_rejected(self):
        """DPI scale below 0.5 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OSWorldSettings(osworld_dpi_scale=0.4)

    def test_dpi_above_maximum_rejected(self):
        """DPI scale above 4.0 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OSWorldSettings(osworld_dpi_scale=4.1)

    def test_screen_width_below_minimum_rejected(self):
        """Screen width below 640 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OSWorldSettings(osworld_screen_width=320)

    def test_screen_height_below_minimum_rejected(self):
        """Screen height below 480 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OSWorldSettings(osworld_screen_height=240)

    def test_connect_timeout_below_1_rejected(self):
        """Connect timeout below 1 is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OSWorldSettings(osworld_connect_timeout=0)

    def test_custom_values(self):
        """All custom values are stored correctly."""
        s = OSWorldSettings(
            osworld_sandbox_type="kvm",
            osworld_host="osworld.internal",
            osworld_port=9090,
            osworld_vm_id="vm-test-42",
            osworld_api_token="secret-token",
            osworld_connect_timeout=60,
            osworld_screen_width=1280,
            osworld_screen_height=720,
            osworld_dpi_scale=1.5,
        )
        assert s.osworld_sandbox_type == "kvm"
        assert s.osworld_api_token == "secret-token"
        assert s.screen_resolution == (1280, 720)
        assert s.osworld_dpi_scale == 1.5
