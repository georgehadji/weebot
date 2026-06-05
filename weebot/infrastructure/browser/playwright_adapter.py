"""PlaywrightAdapter — Browser automation using Playwright."""
from __future__ import annotations

import time
from typing import Any, Optional

from weebot.application.ports.browser_port import (
    ActionResult,
    BrowserConfig,
    BrowserPort,
    BrowserState,
    BrowserType,
    ElementInfo,
    NavigationResult,
)


class PlaywrightAdapter(BrowserPort):
    """Browser automation implementation using Playwright.
    
    This adapter provides full browser automation capabilities using
    Microsoft's Playwright library. Supports Chromium, Firefox, and WebKit.
    
    Requires: pip install playwright
              playwright install
    
    Example:
        browser = PlaywrightAdapter()
        await browser.start(BrowserConfig(headless=False))
        try:
            result = await browser.navigate("https://example.com")
            if result.success:
                text = await browser.get_text("h1")
                screenshot = await browser.screenshot()
        finally:
            await browser.close()
    """
    
    def __init__(self) -> None:
        """Initialize the Playwright adapter."""
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._config: BrowserConfig | None = None
    
    @property
    def page(self):
        """Raw Playwright page for direct tool access."""
        return self._page

    @property
    def browser_type(self) -> BrowserType:
        """Return the type of browser being used."""
        if self._config is None:
            return BrowserType.CHROMIUM
        return self._config.browser_type
    
    async def is_available(self) -> bool:
        """Check if Playwright is installed."""
        try:
            import playwright
            return True
        except ImportError:
            return False
    
    async def start(self, config: BrowserConfig | None = None) -> None:
        """Start the browser session.
        
        Args:
            config: Browser configuration. Uses defaults if None.
        """
        from playwright.async_api import async_playwright
        
        self._config = config or BrowserConfig()
        
        self._playwright = await async_playwright().start()
        
        # Launch browser based on type
        if self._config.browser_type == BrowserType.FIREFOX:
            browser_type = self._playwright.firefox
        elif self._config.browser_type == BrowserType.WEBKIT:
            browser_type = self._playwright.webkit
        else:
            # Default to Chromium
            browser_type = self._playwright.chromium
        
        # Build launch options
        launch_options: dict[str, Any] = {"headless": self._config.headless}
        
        if self._config.proxy_server:
            launch_options["proxy"] = {"server": self._config.proxy_server}
        
        self._browser = await browser_type.launch(**launch_options)
        
        # Build context options
        context_options: dict[str, Any] = {
            "viewport": {
                "width": self._config.viewport_width,
                "height": self._config.viewport_height,
            },
        }
        
        if self._config.user_agent:
            context_options["user_agent"] = self._config.user_agent
        
        if self._config.locale:
            context_options["locale"] = self._config.locale
        
        if self._config.timezone:
            context_options["timezone_id"] = self._config.timezone
        
        if self._config.geolocation:
            context_options["geolocation"] = {
                "latitude": self._config.geolocation[0],
                "longitude": self._config.geolocation[1],
            }
            context_options["permissions"] = ["geolocation"]
        
        if self._config.permissions:
            context_options.setdefault("permissions", [])
            context_options["permissions"].extend(self._config.permissions)
        
        if self._config.record_video:
            context_options["record_video_dir"] = "./videos"
        
        self._context = await self._browser.new_context(**context_options)
        
        # Start HAR recording if requested
        if self._config.record_har:
            await self._context.new_page()
            # HAR recording is set up at context level in Playwright
        
        self._page = await self._context.new_page()
    
    async def close(self) -> None:
        """Close the browser session and cleanup resources."""
        if self._context:
            await self._context.close()
            self._context = None
        
        if self._browser:
            await self._browser.close()
            self._browser = None
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        
        self._page = None
    
    async def navigate(self, url: str, wait_until: str = "networkidle") -> NavigationResult:
        """Navigate to a URL.
        
        Args:
            url: URL to navigate to.
            wait_until: When to consider navigation complete.
        
        Returns:
            NavigationResult with navigation details.
        """
        if not self._page:
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error="Browser not started",
                load_time_ms=0.0,
            )
        
        # Map wait_until values
        wait_until_map = {
            "load": "load",
            "domcontentloaded": "domcontentloaded",
            "networkidle": "networkidle",
            "commit": "commit",
        }
        playwright_wait = wait_until_map.get(wait_until, "networkidle")
        
        t_start = time.monotonic()
        
        try:
            response = await self._page.goto(url, wait_until=playwright_wait)
            elapsed_ms = (time.monotonic() - t_start) * 1000
            
            if response:
                return NavigationResult(
                    success=response.ok,
                    url=response.url,
                    status_code=response.status,
                    error=None if response.ok else f"HTTP {response.status}",
                    load_time_ms=elapsed_ms,
                )
            else:
                return NavigationResult(
                    success=True,
                    url=self._page.url,
                    status_code=0,
                    error=None,
                    load_time_ms=elapsed_ms,
                )
        except Exception as e:
            elapsed_ms = (time.monotonic() - t_start) * 1000
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error=str(e),
                load_time_ms=elapsed_ms,
            )
    
    async def get_state(self) -> BrowserState:
        """Get current browser state."""
        if not self._page:
            return BrowserState(
                url="",
                title="",
                ready_state="",
                viewport=(0, 0),
            )
        
        viewport = self._page.viewport_size or {"width": 0, "height": 0}
        
        return BrowserState(
            url=self._page.url,
            title=await self._page.title(),
            ready_state=await self._page.evaluate("document.readyState"),
            viewport=(viewport["width"], viewport["height"]),
        )
    
    async def screenshot(self, selector: str | None = None, full_page: bool = False) -> bytes:
        """Take a screenshot.
        
        Args:
            selector: If specified, screenshot only this element.
            full_page: Whether to capture full page or just viewport.
        
        Returns:
            Screenshot image data as PNG bytes.
        """
        if not self._page:
            return b""
        
        if selector:
            element = await self._page.query_selector(selector)
            if element:
                return await element.screenshot()
            return b""
        
        return await self._page.screenshot(full_page=full_page)
    
    async def click(self, selector: str, button: str = "left", click_count: int = 1) -> ActionResult:
        """Click an element."""
        if not self._page:
            return ActionResult(success=False, error="Browser not started")
        
        try:
            await self._page.click(
                selector,
                button=button,
                click_count=click_count,
            )
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def fill(self, selector: str, value: str, clear_first: bool = True) -> ActionResult:
        """Fill an input field."""
        if not self._page:
            return ActionResult(success=False, error="Browser not started")
        
        try:
            if clear_first:
                await self._page.fill(selector, value)
            else:
                # Get current value and append
                element = await self._page.query_selector(selector)
                if element:
                    current = await element.input_value()
                    await self._page.fill(selector, current + value)
                else:
                    await self._page.fill(selector, value)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def type_text(self, selector: str, text: str, delay_ms: int = 0) -> ActionResult:
        """Type text into an element (simulating keypresses)."""
        if not self._page:
            return ActionResult(success=False, error="Browser not started")
        
        try:
            delay = delay_ms / 1000.0  # Convert to seconds
            await self._page.type(selector, text, delay=delay)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def get_text(self, selector: str | None = None) -> str:
        """Get text content from page or element."""
        if not self._page:
            return ""
        
        try:
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    return await element.inner_text() or ""
                return ""
            else:
                # Get all visible text
                return await self._page.inner_text("body") or ""
        except Exception:
            return ""
    
    async def get_element_info(self, selector: str) -> ElementInfo | None:
        """Get information about an element."""
        if not self._page:
            return None
        
        try:
            element = await self._page.query_selector(selector)
            if not element:
                return None
            
            # Get bounding box
            bbox = await element.bounding_box()
            bounding_box = None
            if bbox:
                bounding_box = (bbox["x"], bbox["y"], bbox["width"], bbox["height"])
            
            # Get attributes
            attrs = await element.evaluate("el => Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))")
            
            return ElementInfo(
                tag_name=await element.evaluate("el => el.tagName.toLowerCase()"),
                text=await element.inner_text() or "",
                attributes=attrs or {},
                bounding_box=bounding_box,
                is_visible=await element.is_visible(),
                is_enabled=await element.is_enabled(),
            )
        except Exception:
            return None
    
    async def get_elements(self, selector: str) -> list[ElementInfo]:
        """Get information about all matching elements."""
        if not self._page:
            return []
        
        try:
            elements = await self._page.query_selector_all(selector)
            results = []
            
            for element in elements:
                try:
                    bbox = await element.bounding_box()
                    bounding_box = None
                    if bbox:
                        bounding_box = (bbox["x"], bbox["y"], bbox["width"], bbox["height"])
                    
                    attrs = await element.evaluate("el => Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))")
                    
                    info = ElementInfo(
                        tag_name=await element.evaluate("el => el.tagName.toLowerCase()"),
                        text=await element.inner_text() or "",
                        attributes=attrs or {},
                        bounding_box=bounding_box,
                        is_visible=await element.is_visible(),
                        is_enabled=await element.is_enabled(),
                    )
                    results.append(info)
                except Exception:
                    pass  # Skip elements that can't be processed
            
            return results
        except Exception:
            return []
    
    async def scroll(self, x: int, y: int, selector: str | None = None) -> ActionResult:
        """Scroll the page or element."""
        if not self._page:
            return ActionResult(success=False, error="Browser not started")
        
        try:
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    await element.evaluate(f"el => el.scrollBy({x}, {y})")
                else:
                    return ActionResult(success=False, error=f"Element not found: {selector}")
            else:
                await self._page.evaluate(f"window.scrollBy({x}, {y})")
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def hover(self, selector: str) -> ActionResult:
        """Hover over an element."""
        if not self._page:
            return ActionResult(success=False, error="Browser not started")
        
        try:
            await self._page.hover(selector)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def select_option(self, selector: str, value: str | list[str]) -> ActionResult:
        """Select option(s) in a select element."""
        if not self._page:
            return ActionResult(success=False, error="Browser not started")
        
        try:
            if isinstance(value, list):
                await self._page.select_option(selector, value)
            else:
                await self._page.select_option(selector, value)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    async def evaluate(self, script: str, selector: str | None = None) -> Any:
        """Execute JavaScript in the browser."""
        if not self._page:
            return None
        
        try:
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    return await element.evaluate(script)
                return None
            else:
                return await self._page.evaluate(script)
        except Exception as e:
            return {"error": str(e)}
    
    async def wait_for_selector(self, selector: str, timeout: float = 30.0, state: str = "visible") -> bool:
        """Wait for an element to match selector criteria."""
        if not self._page:
            return False
        
        try:
            timeout_ms = timeout * 1000
            await self._page.wait_for_selector(selector, state=state, timeout=timeout_ms)
            return True
        except Exception:
            return False
    
    async def go_back(self) -> NavigationResult:
        """Navigate back in browser history."""
        if not self._page:
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error="Browser not started",
                load_time_ms=0.0,
            )
        
        t_start = time.monotonic()
        
        try:
            response = await self._page.go_back()
            elapsed_ms = (time.monotonic() - t_start) * 1000
            
            return NavigationResult(
                success=True,
                url=self._page.url,
                status_code=response.status if response else 0,
                error=None,
                load_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - t_start) * 1000
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error=str(e),
                load_time_ms=elapsed_ms,
            )
    
    async def go_forward(self) -> NavigationResult:
        """Navigate forward in browser history."""
        if not self._page:
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error="Browser not started",
                load_time_ms=0.0,
            )
        
        t_start = time.monotonic()
        
        try:
            response = await self._page.go_forward()
            elapsed_ms = (time.monotonic() - t_start) * 1000
            
            return NavigationResult(
                success=True,
                url=self._page.url,
                status_code=response.status if response else 0,
                error=None,
                load_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - t_start) * 1000
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error=str(e),
                load_time_ms=elapsed_ms,
            )
    
    async def reload(self) -> NavigationResult:
        """Reload current page."""
        if not self._page:
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error="Browser not started",
                load_time_ms=0.0,
            )
        
        t_start = time.monotonic()
        
        try:
            response = await self._page.reload()
            elapsed_ms = (time.monotonic() - t_start) * 1000
            
            return NavigationResult(
                success=True,
                url=self._page.url,
                status_code=response.status if response else 0,
                error=None,
                load_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - t_start) * 1000
            return NavigationResult(
                success=False,
                url="",
                status_code=0,
                error=str(e),
                load_time_ms=elapsed_ms,
            )
