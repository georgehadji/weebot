"""Advanced browser automation tools using Playwright."""
from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import Optional

from weebot.tools.base import BaseTool, ToolResult
from weebot.infrastructure.browser.session_manager import BrowserSessionManager

logger = logging.getLogger(__name__)

# Module-level Playwright instance — set when the browser is launched so
# _close_browser() can call stop() to avoid zombie Chromium processes.
_playwright_instance = None

# ── wait_type → Playwright wait_until mapping ──
_WAIT_TYPE_MAP: dict[str, str] = {
    "navigation": "domcontentloaded",
    "function": "load",
    "selector": "domcontentloaded",  # navigate fast, then wait for selector
}


class AdvancedBrowserTool(BaseTool):
    """Full browser automation using Playwright.

    Receives a shared PlaywrightAdapter via DI (injected by tool_registry)
    so BrowserInspectorTool and other tools share the same browser session.
    """

    max_concurrent: int = 1
    default_timeout_seconds: int = 120
    name: str = "advanced_browser"
    description: str = (
        "Full browser automation: navigate, interact, extract data, execute JavaScript. "
        "Supports form filling, screenshots, JavaScript execution, and more."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "launch",
                    "close",
                    "goto",
                    "back",
                    "forward",
                    "reload",
                    "click",
                    "fill",
                    "select",
                    "type",
                    "evaluate",
                    "screenshot",
                    "get_content",
                    "get_title",
                    "wait_for_selector",
                    "get_cookies",
                    "set_cookies",
                    "save_session",
                    "list_sessions",
                    "delete_session",
                ],
                "description": "Action to perform",
            },
            "url": {
                "type": "string",
                "description": "URL to navigate to (for goto action)",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for element interaction",
            },
            "text": {
                "type": "string",
                "description": "Text to type or button text to click",
            },
            "value": {
                "type": "string",
                "description": "Value to fill in form field or select",
            },
            "script": {
                "type": "string",
                "description": "JavaScript code to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds (default: 30000)",
            },
            "headless": {
                "type": "boolean",
                "description": "Launch browser in headless mode (default: true)",
            },
            "wait_type": {
                "type": "string",
                "enum": ["selector", "navigation", "function"],
                "description": "Type of wait condition for goto (selector waits for selector after navigation)",
            },
            "session_name": {
                "type": "string",
                "description": "Session name to persist/restore cookies and storage (optional)",
            },
            "save_session": {
                "type": "boolean",
                "description": "Save session after this action (default: false)",
            },
        },
        "required": ["action"],
    }

    max_concurrent: int = 1

    # Injected by tool_registry via DI
    browser: object | None = None  # PlaywrightAdapter

    def _page(self):
        """Return the current Playwright page, or None if not launched."""
        if self.browser is None:
            return None
        return self.browser.page

    def _context(self):
        """Return the current browser context, or None."""
        p = self._page()
        return p.context if p else None

    async def health_check(self) -> bool:
        """Check if Playwright is available on this system."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                _ = p.chromium
            return True
        except Exception:
            return False

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        value: Optional[str] = None,
        script: Optional[str] = None,
        timeout: int = 30000,
        headless: bool = True,
        wait_type: str = "selector",
        session_name: Optional[str] = None,
        save_session: bool = False,
        **_,
    ) -> ToolResult:
        """Execute browser action."""
        try:
            if action == "launch":
                await self._launch_browser(headless, session_name=session_name)
                ctx = self._context()
                if save_session and session_name and ctx:
                    session_manager = BrowserSessionManager()
                    await session_manager.save_session(session_name, ctx)
                return ToolResult(output="Browser launched successfully")

            elif action == "close":
                await self._close_browser()
                return ToolResult(output="Browser closed")

            elif action == "goto":
                if not url:
                    return ToolResult(output="", error="url required for goto action")
                page = self._page()
                if not page:
                    await self._launch_browser(headless, session_name=session_name)
                    page = self._page()
                # Map wait_type to Playwright wait_until
                wait_until = _WAIT_TYPE_MAP.get(wait_type, "domcontentloaded")
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                # If wait_type is "selector", additionally wait for the selector
                if wait_type == "selector" and selector:
                    await page.wait_for_selector(selector, timeout=timeout)
                ctx = self._context()
                if save_session and session_name and ctx:
                    session_manager = BrowserSessionManager()
                    await session_manager.save_session(session_name, ctx)
                return ToolResult(output=f"Navigated to {url}")

            elif action == "back":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.go_back(timeout=timeout)
                return ToolResult(output="Navigated back")

            elif action == "forward":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.go_forward(timeout=timeout)
                return ToolResult(output="Navigated forward")

            elif action == "reload":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.reload(timeout=timeout)
                return ToolResult(output="Page reloaded")

            elif action == "click":
                if not selector:
                    return ToolResult(output="", error="selector required for click")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.click(selector, timeout=timeout)
                return ToolResult(output=f"Clicked element: {selector}")

            elif action == "fill":
                if not selector or value is None:
                    return ToolResult(output="", error="selector and value required for fill")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.fill(selector, value, timeout=timeout)
                return ToolResult(output=f"Filled field: {selector}")

            elif action == "select":
                if not selector or value is None:
                    return ToolResult(output="", error="selector and value required for select")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.select_option(selector, value, timeout=timeout)
                return ToolResult(output=f"Selected option: {value} in {selector}")

            elif action == "type":
                if not text:
                    return ToolResult(output="", error="text required for type")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.keyboard.type(text)
                return ToolResult(output=f"Typed text: {text[:50]}...")

            elif action == "evaluate":
                if not script:
                    return ToolResult(output="", error="script required for evaluate")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                result = await page.evaluate(script)
                return ToolResult(output=f"JavaScript result: {result}")

            elif action == "screenshot":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                screenshot_bytes = await page.screenshot()
                img_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                return ToolResult(
                    output="Screenshot captured",
                    base64_image=img_base64,
                )

            elif action == "get_content":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                content = await page.content()
                return ToolResult(output=f"HTML content: {content[:500]}...")

            elif action == "get_title":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                title = await page.title()
                return ToolResult(output=f"Page title: {title}")

            elif action == "wait_for_selector":
                if not selector:
                    return ToolResult(output="", error="selector required for wait_for_selector")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                await page.wait_for_selector(selector, timeout=timeout)
                return ToolResult(output=f"Element appeared: {selector}")

            elif action == "get_cookies":
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                cookies = await page.context.cookies()
                return ToolResult(output=f"Cookies: {cookies}")

            elif action == "set_cookies":
                if not value:
                    return ToolResult(output="", error="value (JSON string) required for set_cookies")
                page = self._page()
                if not page:
                    return ToolResult(output="", error="Browser not launched")
                import json
                cookies = json.loads(value)
                await page.context.add_cookies(cookies)
                return ToolResult(output=f"Set {len(cookies)} cookies")

            elif action == "save_session":
                if not session_name:
                    return ToolResult(output="", error="session_name required for save_session")
                ctx = self._context()
                if not ctx:
                    return ToolResult(output="", error="Browser not launched")
                session_manager = BrowserSessionManager()
                success = await session_manager.save_session(session_name, ctx)
                return ToolResult(
                    output=f"Session '{session_name}' saved" if success else f"Failed to save session '{session_name}'"
                )

            elif action == "list_sessions":
                session_manager = BrowserSessionManager()
                sessions = session_manager.list_sessions()
                if not sessions:
                    return ToolResult(output="No saved sessions found")
                output = f"Saved sessions ({len(sessions)}):\n"
                for s in sessions:
                    output += f"  - {s['name']} (saved: {s['saved_at']})\n"
                return ToolResult(output=output)

            elif action == "delete_session":
                if not session_name:
                    return ToolResult(output="", error="session_name required for delete_session")
                session_manager = BrowserSessionManager()
                success = session_manager.delete_session(session_name)
                return ToolResult(
                    output=f"Session '{session_name}' deleted" if success else f"Session '{session_name}' not found"
                )

            else:
                return ToolResult(output="", error=f"Unknown action: {action}")

        except ImportError:
            return ToolResult(output="", error="playwright not installed")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    async def _launch_browser(self, headless: bool = True, session_name: Optional[str] = None) -> None:
        """Launch browser via the injected PlaywrightAdapter."""
        if self.browser is None:
            from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
            self.browser = PlaywrightAdapter()
        if self._page() is not None:
            return  # Already launched
        from weebot.application.ports.browser_port import BrowserConfig
        config = BrowserConfig(headless=headless)
        await self.browser.start(config)
        # Load session if specified
        if session_name:
            session_manager = BrowserSessionManager()
            ctx = self._context()
            if ctx:
                loaded = await session_manager.load_session(session_name, ctx)
                if loaded:
                    logger.info("Restored session '%s'", session_name)

    async def _close_browser(self) -> None:
        """Close browser and stop the Playwright instance to avoid zombie processes."""
        global _playwright_instance
        if self.browser is not None:
            await self.browser.close()
        if _playwright_instance is not None:
            pw = _playwright_instance
            _playwright_instance = None
            await pw.stop()


class WebScraperTool(BaseTool):
    """Advanced web scraping with data extraction patterns."""

    name: str = "web_scraper"
    description: str = (
        "Advanced web scraping: extract structured data from websites. "
        "Supports CSS selectors, XPath, and pattern-based extraction."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to scrape",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for elements to extract",
            },
            "extract_type": {
                "type": "string",
                "enum": ["text", "html", "attribute", "all", "markdown"],
                "description": "What to extract from matching elements",
            },
            "attribute": {
                "type": "string",
                "description": "Attribute to extract (for extract_type='attribute')",
            },
            "wait_for": {
                "type": "string",
                "description": "CSS selector to wait for before scraping",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds (default: 30000)",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum tokens for markdown extraction (default: 4000)",
                "default": 4000,
            },
        },
        "required": ["url", "selector"],
    }

    async def execute(
        self,
        url: str,
        selector: str,
        extract_type: str = "text",
        attribute: Optional[str] = None,
        wait_for: Optional[str] = None,
        timeout: int = 30000,
        max_tokens: int = 4000,
        **_,
    ) -> ToolResult:
        """Scrape web page and extract data."""
        # Validate input before launching external browser processes.
        if not url or not url.strip():
            return ToolResult(output="", error="url required for scraping")
        if not selector or not selector.strip():
            return ToolResult(output="", error="selector required for scraping")
        if extract_type == "attribute" and not attribute:
            return ToolResult(
                output="",
                error="attribute required when extract_type='attribute'",
            )
        if timeout <= 0:
            return ToolResult(output="", error="timeout must be > 0")

        try:
            from playwright.async_api import async_playwright
            from bs4 import BeautifulSoup

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page()

                # Navigate to URL
                await page.goto(url, wait_until="networkidle", timeout=timeout)

                # Wait for selector if specified
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=timeout)

                # Get page content
                content = await page.content()

                # Handle markdown extraction directly
                if extract_type == "markdown":
                    from weebot.infrastructure.browser.content_extractor import ContentExtractor

                    extractor = ContentExtractor(max_tokens=max_tokens, preserve_links=True)
                    markdown = extractor.extract_markdown(content, url=url)

                    await browser.close()

                    output = f"Extracted markdown from {url}\n\n{markdown[:800]}"
                    if len(markdown) > 800:
                        output += f"...\n\n[Full content: {len(markdown)} chars, ~{extractor.estimate_tokens(markdown)} tokens]"

                    return ToolResult(
                        output=output,
                        data={
                            "url": url,
                            "markdown": markdown,
                            "truncated": len(markdown) >= max_tokens * 4,
                            "char_count": len(markdown),
                            "estimated_tokens": extractor.estimate_tokens(markdown),
                        }
                    )

                await browser.close()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            elements = soup.select(selector)

            if not elements:
                return ToolResult(output=f"No elements found matching selector: {selector}")

            # Extract data based on type
            extracted = []
            for elem in elements[:20]:  # Limit to first 20
                if extract_type == "text":
                    extracted.append(elem.get_text(strip=True))
                elif extract_type == "html":
                    extracted.append(str(elem))
                elif extract_type == "attribute" and attribute:
                    value = elem.get(attribute)
                    if value:
                        extracted.append(value)
                elif extract_type == "all":
                    extracted.append({
                        "text": elem.get_text(strip=True),
                        "html": str(elem),
                        "attributes": elem.attrs,
                    })

            output = f"Extracted {len(extracted)} items from {url}\n\n"
            for i, item in enumerate(extracted[:5], 1):
                if isinstance(item, dict):
                    output += f"{i}. Text: {item['text'][:50]}...\n"
                else:
                    output += f"{i}. {str(item)[:100]}...\n"

            if len(extracted) > 5:
                output += f"\n... and {len(extracted) - 5} more items"

            return ToolResult(output=output)

        except ImportError:
            return ToolResult(output="", error="playwright or beautifulsoup4 not installed")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))
