"""Browser infrastructure adapters.

This module provides browser automation implementations:
- PlaywrightAdapter: Full-featured browser automation via Playwright
- BrowserSessionPool: Pooled browser sessions for fast reuse
"""
from weebot.application.ports.browser_port import (
    ActionResult,
    BrowserAction,
    BrowserConfig,
    BrowserPort,
    BrowserState,
    BrowserType,
    ElementInfo,
    NavigationResult,
)

try:
    from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from weebot.infrastructure.browser.session_pool import (
        BrowserSessionPool,
        BrowserSession,
        get_browser_pool,
        close_global_pool,
    )
    SESSION_POOL_AVAILABLE = True
except ImportError:
    SESSION_POOL_AVAILABLE = False

__all__ = [
    # Port types
    "ActionResult",
    "BrowserAction",
    "BrowserConfig",
    "BrowserPort",
    "BrowserState",
    "BrowserType",
    "ElementInfo",
    "NavigationResult",
    # Adapters
    "PlaywrightAdapter",
    "PLAYWRIGHT_AVAILABLE",
    # Session pool
    "BrowserSessionPool",
    "BrowserSession",
    "get_browser_pool",
    "close_global_pool",
    "SESSION_POOL_AVAILABLE",
]
