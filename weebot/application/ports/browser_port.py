"""BrowserPort — abstraction for browser automation.

This port defines the interface for browser automation operations,
enabling different browser backends (Playwright, Selenium, etc.).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional


class BrowserType(Enum):
    """Types of browser engines available."""
    CHROMIUM = auto()
    FIREFOX = auto()
    WEBKIT = auto()
    CHROME = auto()
    EDGE = auto()


class BrowserAction(Enum):
    """Types of browser actions that can be performed."""
    NAVIGATE = auto()
    CLICK = auto()
    FILL = auto()
    SCREENSHOT = auto()
    SCROLL = auto()
    HOVER = auto()
    SELECT = auto()
    UPLOAD = auto()
    EVALUATE = auto()


@dataclass(frozen=True)
class BrowserState:
    """Current state of the browser.
    
    Attributes:
        url: Current page URL.
        title: Current page title.
        ready_state: Document ready state (loading, interactive, complete).
        viewport: Viewport dimensions (width, height).
    """
    url: str
    title: str
    ready_state: str
    viewport: tuple[int, int]


@dataclass(frozen=True)
class ElementInfo:
    """Information about a DOM element.
    
    Attributes:
        tag_name: HTML tag name.
        text: Element text content.
        attributes: Dictionary of element attributes.
        bounding_box: Element position and size (x, y, width, height).
        is_visible: Whether element is visible.
        is_enabled: Whether element is enabled.
    """
    tag_name: str
    text: str
    attributes: dict[str, str]
    bounding_box: tuple[float, float, float, float] | None
    is_visible: bool
    is_enabled: bool


@dataclass(frozen=True)
class NavigationResult:
    """Result of a navigation operation.
    
    Attributes:
        success: Whether navigation succeeded.
        url: Final URL after navigation.
        status_code: HTTP status code.
        error: Error message if navigation failed.
        load_time_ms: Page load time in milliseconds.
    """
    success: bool
    url: str
    status_code: int
    error: str | None
    load_time_ms: float


@dataclass(frozen=True)
class ActionResult:
    """Result of a browser action.
    
    Attributes:
        success: Whether action succeeded.
        error: Error message if action failed.
        data: Additional data from the action.
    """
    success: bool
    error: str | None = None
    data: dict[str, Any] | None = None


@dataclass
class BrowserConfig:
    """Configuration for browser automation.
    
    Attributes:
        browser_type: Type of browser to use.
        headless: Whether to run in headless mode.
        viewport_width: Viewport width in pixels.
        viewport_height: Viewport height in pixels.
        user_agent: Custom user agent string.
        locale: Browser locale.
        timezone: Browser timezone.
        geolocation: Geolocation (latitude, longitude).
        permissions: List of permissions to grant.
        downloads_path: Path for downloaded files.
        record_video: Whether to record video of session.
        record_har: Whether to record HAR file.
        proxy_server: Proxy server URL.
    """
    browser_type: BrowserType = BrowserType.CHROMIUM
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str | None = None
    locale: str | None = None
    timezone: str | None = None
    geolocation: tuple[float, float] | None = None
    permissions: list[str] | None = None
    downloads_path: Path | None = None
    record_video: bool = False
    record_har: bool = False
    proxy_server: str | None = None
    
    def __post_init__(self):
        if self.permissions is None:
            self.permissions = []


class BrowserPort(ABC):
    """Abstract base class for browser automation.
    
    Implementations provide browser automation capabilities for
    web scraping, testing, and interaction.
    
    Example:
        browser = PlaywrightAdapter()
        await browser.start()
        try:
            nav_result = await browser.navigate("https://example.com")
            screenshot = await browser.screenshot()
            text = await browser.get_text("h1")
        finally:
            await browser.close()
    """
    
    @property
    @abstractmethod
    def browser_type(self) -> BrowserType:
        """Return the type of browser being used."""
        ...
    
    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the browser automation is available.
        
        Returns:
            True if the browser can be used (e.g., Playwright is installed).
        """
        ...
    
    @abstractmethod
    async def start(self, config: BrowserConfig | None = None) -> None:
        """Start the browser session.
        
        Args:
            config: Browser configuration. Uses defaults if None.
        """
        ...
    
    @abstractmethod
    async def close(self) -> None:
        """Close the browser session and cleanup resources."""
        ...
    
    @abstractmethod
    async def navigate(self, url: str, wait_until: str = "networkidle") -> NavigationResult:
        """Navigate to a URL.
        
        Args:
            url: URL to navigate to.
            wait_until: When to consider navigation complete
                       (load, domcontentloaded, networkidle, commit).
        
        Returns:
            NavigationResult with navigation details.
        """
        ...
    
    @abstractmethod
    async def get_state(self) -> BrowserState:
        """Get current browser state.
        
        Returns:
            Current browser state.
        """
        ...
    
    @abstractmethod
    async def screenshot(self, selector: str | None = None, full_page: bool = False) -> bytes:
        """Take a screenshot.
        
        Args:
            selector: If specified, screenshot only this element.
            full_page: Whether to capture full page or just viewport.
        
        Returns:
            Screenshot image data as PNG bytes.
        """
        ...
    
    @abstractmethod
    async def click(self, selector: str, button: str = "left", click_count: int = 1) -> ActionResult:
        """Click an element.
        
        Args:
            selector: CSS or XPath selector for element.
            button: Mouse button (left, right, middle).
            click_count: Number of clicks.
        
        Returns:
            ActionResult with operation details.
        """
        ...
    
    @abstractmethod
    async def fill(self, selector: str, value: str, clear_first: bool = True) -> ActionResult:
        """Fill an input field.
        
        Args:
            selector: CSS or XPath selector for input element.
            value: Value to fill.
            clear_first: Whether to clear field before filling.
        
        Returns:
            ActionResult with operation details.
        """
        ...
    
    @abstractmethod
    async def type_text(self, selector: str, text: str, delay_ms: int = 0) -> ActionResult:
        """Type text into an element (simulating keypresses).
        
        Args:
            selector: CSS or XPath selector for element.
            text: Text to type.
            delay_ms: Delay between keystrokes in milliseconds.
        
        Returns:
            ActionResult with operation details.
        """
        ...
    
    @abstractmethod
    async def get_text(self, selector: str | None = None) -> str:
        """Get text content from page or element.
        
        Args:
            selector: If specified, get text from this element only.
                     If None, get all visible text from page.
        
        Returns:
            Text content.
        """
        ...
    
    @abstractmethod
    async def get_element_info(self, selector: str) -> ElementInfo | None:
        """Get information about an element.
        
        Args:
            selector: CSS or XPath selector for element.
        
        Returns:
            ElementInfo if element found, None otherwise.
        """
        ...
    
    @abstractmethod
    async def get_elements(self, selector: str) -> list[ElementInfo]:
        """Get information about all matching elements.
        
        Args:
            selector: CSS or XPath selector for elements.
        
        Returns:
            List of ElementInfo for matching elements.
        """
        ...
    
    @abstractmethod
    async def scroll(self, x: int, y: int, selector: str | None = None) -> ActionResult:
        """Scroll the page or element.
        
        Args:
            x: Horizontal scroll amount.
            y: Vertical scroll amount.
            selector: If specified, scroll this element. Otherwise scroll page.
        
        Returns:
            ActionResult with operation details.
        """
        ...
    
    @abstractmethod
    async def hover(self, selector: str) -> ActionResult:
        """Hover over an element.
        
        Args:
            selector: CSS or XPath selector for element.
        
        Returns:
            ActionResult with operation details.
        """
        ...
    
    @abstractmethod
    async def select_option(self, selector: str, value: str | list[str]) -> ActionResult:
        """Select option(s) in a select element.
        
        Args:
            selector: CSS or XPath selector for select element.
            value: Value(s) to select.
        
        Returns:
            ActionResult with operation details.
        """
        ...
    
    @abstractmethod
    async def evaluate(self, script: str, selector: str | None = None) -> Any:
        """Execute JavaScript in the browser.
        
        Args:
            script: JavaScript code to execute.
            selector: If specified, execute in context of this element.
        
        Returns:
            Result of script execution.
        """
        ...
    
    @abstractmethod
    async def wait_for_selector(self, selector: str, timeout: float = 30.0, state: str = "visible") -> bool:
        """Wait for an element to match selector criteria.
        
        Args:
            selector: CSS or XPath selector to wait for.
            timeout: Maximum time to wait in seconds.
            state: State to wait for (attached, detached, visible, hidden).
        
        Returns:
            True if element found within timeout, False otherwise.
        """
        ...
    
    @abstractmethod
    async def go_back(self) -> NavigationResult:
        """Navigate back in browser history.
        
        Returns:
            NavigationResult with navigation details.
        """
        ...
    
    @abstractmethod
    async def go_forward(self) -> NavigationResult:
        """Navigate forward in browser history.
        
        Returns:
            NavigationResult with navigation details.
        """
        ...
    
    @abstractmethod
    async def reload(self) -> NavigationResult:
        """Reload current page.
        
        Returns:
            NavigationResult with navigation details.
        """
        ...
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
