"""Advanced browser automation tools using Playwright."""
from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from typing import Optional

from weebot.tools.base import BaseTool, ToolResult

# Module-level browser state (persists across tool calls)
_browser = None
_page = None
_context = None
_playwright_instance = None


class AdvancedBrowserTool(BaseTool):
    """Full browser automation using Playwright."""

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
                "description": "Type of wait condition",
            },
        },
        "required": ["action"],
    }

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
        **_,
    ) -> ToolResult:
        """Execute browser action."""
        global _page

        try:
            from playwright.async_api import async_playwright

            if action == "launch":
                await self._launch_browser(headless)
                return ToolResult(output="Browser launched successfully")

            elif action == "close":
                await self._close_browser()
                return ToolResult(output="Browser closed")

            elif action == "goto":
                if not url:
                    return ToolResult(output="", error="url required for goto action")
                if not _page:
                    await self._launch_browser(headless)
                await _page.goto(url, wait_until="networkidle", timeout=timeout)
                return ToolResult(output=f"Navigated to {url}")

            elif action == "back":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.go_back(timeout=timeout)
                return ToolResult(output="Navigated back")

            elif action == "forward":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.go_forward(timeout=timeout)
                return ToolResult(output="Navigated forward")

            elif action == "reload":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.reload(timeout=timeout)
                return ToolResult(output="Page reloaded")

            elif action == "click":
                if not selector:
                    return ToolResult(output="", error="selector required for click")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.click(selector, timeout=timeout)
                return ToolResult(output=f"Clicked element: {selector}")

            elif action == "fill":
                if not selector or value is None:
                    return ToolResult(output="", error="selector and value required for fill")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.fill(selector, value, timeout=timeout)
                return ToolResult(output=f"Filled field: {selector}")

            elif action == "select":
                if not selector or value is None:
                    return ToolResult(output="", error="selector and value required for select")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.select_option(selector, value, timeout=timeout)
                return ToolResult(output=f"Selected option: {value} in {selector}")

            elif action == "type":
                if not text:
                    return ToolResult(output="", error="text required for type")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.keyboard.type(text)
                return ToolResult(output=f"Typed text: {text[:50]}...")

            elif action == "evaluate":
                if not script:
                    return ToolResult(output="", error="script required for evaluate")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                result = await _page.evaluate(script)
                return ToolResult(output=f"JavaScript result: {result}")

            elif action == "screenshot":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                screenshot_bytes = await _page.screenshot()
                img_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                return ToolResult(
                    output="Screenshot captured",
                    base64_image=img_base64,
                )

            elif action == "get_content":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                content = await _page.content()
                return ToolResult(output=f"HTML content: {content[:500]}...")

            elif action == "get_title":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                title = await _page.title()
                return ToolResult(output=f"Page title: {title}")

            elif action == "wait_for_selector":
                if not selector:
                    return ToolResult(output="", error="selector required for wait_for_selector")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                await _page.wait_for_selector(selector, timeout=timeout)
                return ToolResult(output=f"Element appeared: {selector}")

            elif action == "get_cookies":
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                cookies = await _page.context.cookies()
                return ToolResult(output=f"Cookies: {cookies}")

            elif action == "set_cookies":
                if not value:
                    return ToolResult(output="", error="value (JSON string) required for set_cookies")
                if not _page:
                    return ToolResult(output="", error="Browser not launched")
                import json

                cookies = json.loads(value)
                await _page.context.add_cookies(cookies)
                return ToolResult(output=f"Set {len(cookies)} cookies")

            else:
                return ToolResult(output="", error=f"Unknown action: {action}")

        except ImportError:
            return ToolResult(output="", error="playwright not installed")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    async def _launch_browser(self, headless: bool = True) -> None:
        """Launch browser if not already running."""
        global _browser, _page, _context, _playwright_instance

        if _page is not None:
            return  # Already launched

        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        _playwright_instance = pw
        b = await pw.chromium.launch(headless=headless)
        _browser = b
        c = await b.new_context()
        _context = c
        p = await c.new_page()
        _page = p

    async def _close_browser(self) -> None:
        """Close browser."""
        global _browser, _page, _context, _playwright_instance

        if _page:
            await _page.close()
            _page = None
        if _context:
            await _context.close()
            _context = None
        if _browser:
            await _browser.close()
            _browser = None


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
                "enum": ["text", "html", "attribute", "all"],
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
        **_,
    ) -> ToolResult:
        """Scrape web page and extract data."""
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
