"""Tests for ComputerUseTool DPI scaling logic."""
import pytest
import sys
from unittest.mock import patch, MagicMock

# Mock pyautogui before importing the tool
if "pyautogui" not in sys.modules:
    sys.modules["pyautogui"] = MagicMock()

from weebot.tools.computer_use import ComputerUseTool


@pytest.fixture
def tool():
    return ComputerUseTool()


class TestDPIScaling:
    """DPI coordinate scaling (_scale method)."""

    def test_scale_noop_default(self, tool):
        """dpi_scale=1.0 returns coordinates unchanged."""
        x, y = tool._scale(100, 200, dpi_scale=1.0)
        assert x == 100
        assert y == 200

    def test_scale_125_percent(self, tool):
        """dpi_scale=1.25 (125% scaling) divides coordinates."""
        x, y = tool._scale(125, 250, dpi_scale=1.25)
        assert x == 100  # 125 / 1.25 = 100
        assert y == 200  # 250 / 1.25 = 200

    def test_scale_150_percent_rounds(self, tool):
        """dpi_scale=1.5 rounds to nearest integer."""
        x, y = tool._scale(100, 200, dpi_scale=1.5)
        assert x == 67  # 100/1.5 = 66.67 → round = 67
        assert y == 133  # 200/1.5 = 133.33 → round = 133

    def test_scale_200_percent(self, tool):
        """dpi_scale=2.0 (200% HiDPI) halves coordinates."""
        x, y = tool._scale(3840, 2160, dpi_scale=2.0)
        assert x == 1920
        assert y == 1080

    def test_scale_none_passthrough(self, tool):
        """None coordinates pass through unscaled."""
        x, y = tool._scale(None, None, dpi_scale=1.5)
        assert x is None
        assert y is None

    def test_scale_mixed_none(self, tool):
        """Mixed None/Some preserves None for missing axis."""
        x, y = tool._scale(None, 200, dpi_scale=2.0)
        assert x is None
        assert y == 100

    def test_scale_zero_coords(self, tool):
        """Zero coordinates stay zero regardless of DPI."""
        x, y = tool._scale(0, 0, dpi_scale=3.0)
        assert x == 0
        assert y == 0

    def test_scale_extreme_dpi(self, tool):
        """Maximum DPI (4.0) still produces valid coordinates."""
        x, y = tool._scale(400, 400, dpi_scale=4.0)
        assert x == 100
        assert y == 100

    @pytest.mark.parametrize("dpi,in_x,in_y,exp_x,exp_y", [
        (1.0, 1920, 1080, 1920, 1080),
        (1.25, 125, 250, 100, 200),
        (1.5, 150, 300, 100, 200),
        (2.0, 200, 400, 100, 200),
        (0.5, 50, 100, 100, 200),  # DPI < 1 scales up
    ])
    def test_scale_parametrized(self, tool, dpi, in_x, in_y, exp_x, exp_y):
        """Parametrized DPI scaling across common values."""
        x, y = tool._scale(in_x, in_y, dpi_scale=dpi)
        assert x == exp_x, f"Expected x={exp_x}, got {x} at DPI {dpi}"
        assert y == exp_y, f"Expected y={exp_y}, got {y} at DPI {dpi}"
