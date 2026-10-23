"""One version number (SSOT audit row 15).

`VERSION` feeds `weebot.__version__` and the FastAPI app, while `/health/status`
said 2.6.0, the behavior tracker stamped events 2.7.0 and the MCP health tool
said 1.0.0.
"""

from __future__ import annotations

import inspect

import weebot


def test_the_behavior_tracker_stamps_the_package_version():
    from weebot.core import behavior_tracker

    source = inspect.getsource(behavior_tracker)
    assert '"2.7.0"' not in source and "__version__" in source


def test_the_health_status_reports_the_package_version():
    from weebot.interfaces.web.routers import health

    source = inspect.getsource(health)
    assert '"2.6.0"' not in source and "__version__" in source


def test_the_mcp_health_tool_reports_the_package_version():
    from weebot.mcp import server

    source = inspect.getsource(server)
    assert '"version": "1.0.0"' not in source


def test_the_package_version_is_the_version_file():
    from pathlib import Path

    root = Path(weebot.__file__).resolve().parents[1]
    assert weebot.__version__ == (root / "VERSION").read_text().strip()
