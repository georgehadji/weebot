"""BrowserInspectorTool — structured, read-only inspection of live web pages.

Complements AdvancedBrowserTool (navigation/interaction) with analysis-focused
actions: extract design tokens, computed CSS, asset inventory, and page structure.
All actions return structured data in ToolResult.data for use by the ExecutorAgent
facts dict.

Shares the Playwright browser session started by AdvancedBrowserTool so only one
browser process is ever launched.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# JS snippets injected into the page
_JS_DESIGN_TOKENS = """
() => {
    const style = getComputedStyle(document.documentElement);
    const tokens = {};
    // Collect all CSS custom properties from :root
    for (const sheet of document.styleSheets) {
        try {
            for (const rule of sheet.cssRules) {
                if (rule.selectorText === ':root' || rule.selectorText === 'html') {
                    for (const prop of rule.style) {
                        if (prop.startsWith('--')) {
                            tokens[prop] = rule.style.getPropertyValue(prop).trim();
                        }
                    }
                }
            }
        } catch (e) { /* cross-origin stylesheet */ }
    }
    // Also capture computed values for the common token names
    const computed = {
        'font-family': style.fontFamily,
        'font-size': style.fontSize,
        'line-height': style.lineHeight,
        'color': style.color,
        'background-color': style.backgroundColor,
    };
    return { custom_properties: tokens, computed_root: computed };
}
"""

_JS_INSPECT_ELEMENT = """
(selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const props = [
        'display','position','width','height','margin','marginTop','marginBottom',
        'marginLeft','marginRight','padding','paddingTop','paddingBottom',
        'paddingLeft','paddingRight','color','backgroundColor','backgroundImage',
        'backgroundSize','backgroundPosition','fontFamily','fontSize','fontWeight',
        'lineHeight','letterSpacing','textAlign','border','borderRadius',
        'boxShadow','opacity','transform','transition','animation',
        'flexDirection','justifyContent','alignItems','gap','gridTemplateColumns',
        'overflow','zIndex','top','left','right','bottom',
    ];
    const css = {};
    for (const p of props) css[p] = style[p];
    // Hover / focus states via pseudo-element inspection (static representation)
    const text = el.innerText ? el.innerText.trim().slice(0, 200) : '';
    const tagName = el.tagName.toLowerCase();
    const classList = Array.from(el.classList);
    return {
        tag: tagName,
        classes: classList,
        text_content: text,
        bounding_box: {
            x: Math.round(rect.x), y: Math.round(rect.y),
            width: Math.round(rect.width), height: Math.round(rect.height),
        },
        computed_css: css,
    };
}
"""

_JS_ENUMERATE_ASSETS = """
() => {
    const assets = [];
    // <img> elements
    for (const img of document.querySelectorAll('img')) {
        const rect = img.getBoundingClientRect();
        assets.push({
            type: 'img',
            src: img.src,
            alt: img.alt || '',
            width: img.naturalWidth || Math.round(rect.width),
            height: img.naturalHeight || Math.round(rect.height),
            position: { x: Math.round(rect.x), y: Math.round(rect.y) },
        });
    }
    // Elements with background-image
    for (const el of document.querySelectorAll('*')) {
        const bg = getComputedStyle(el).backgroundImage;
        if (bg && bg !== 'none') {
            const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
            if (match) {
                const rect = el.getBoundingClientRect();
                assets.push({
                    type: 'background-image',
                    src: match[1],
                    tag: el.tagName.toLowerCase(),
                    selector: el.id ? '#' + el.id : (el.className ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase()),
                    position: { x: Math.round(rect.x), y: Math.round(rect.y) },
                });
            }
        }
    }
    // Inline SVGs
    let svgIdx = 0;
    for (const svg of document.querySelectorAll('svg')) {
        const rect = svg.getBoundingClientRect();
        assets.push({
            type: 'inline-svg',
            id: svg.id || `svg-${svgIdx++}`,
            viewBox: svg.getAttribute('viewBox') || '',
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            position: { x: Math.round(rect.x), y: Math.round(rect.y) },
        });
    }
    // Video sources
    for (const video of document.querySelectorAll('video')) {
        const src = video.src || (video.querySelector('source') ? video.querySelector('source').src : '');
        if (src) {
            assets.push({ type: 'video', src });
        }
    }
    return assets;
}
"""

_JS_GET_STRUCTURE = """
() => {
    const SEMANTIC = ['header','nav','main','footer','section','article','aside','h1','h2','h3'];
    function extractNode(el, depth) {
        if (depth > 4) return null;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return null;
        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || '').trim().slice(0, 150);
        const children = [];
        for (const child of el.children) {
            const childTag = child.tagName.toLowerCase();
            if (SEMANTIC.includes(childTag) || depth < 2) {
                const node = extractNode(child, depth + 1);
                if (node) children.push(node);
            }
        }
        return {
            tag,
            id: el.id || null,
            classes: Array.from(el.classList).slice(0, 5),
            text_preview: text,
            bounding_box: {
                x: Math.round(rect.x), y: Math.round(rect.y),
                width: Math.round(rect.width), height: Math.round(rect.height),
            },
            children,
        };
    }
    return extractNode(document.body, 0);
}
"""


class BrowserInspectorTool(BaseTool):
    """Read-only structured inspection of live web pages via Playwright.

    Shares the browser session with AdvancedBrowserTool via a DI-injected
    PlaywrightAdapter — call advanced_browser(action='launch') or
    advanced_browser(action='goto') first.
    All results are returned in ToolResult.data for downstream consumption.
    """

    name: str = "browser_inspector"

    # Injected by tool_registry via DI — shared with AdvancedBrowserTool
    browser: object | None = None  # PlaywrightAdapter
    description: str = (
        "Inspect a live page: extract design tokens (CSS custom properties), "
        "computed CSS for any element, full asset inventory (images/SVG/video), "
        "semantic page structure, or take a full-page screenshot. "
        "Use after navigating with advanced_browser. All data returned in structured form."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "extract_design_tokens",
                    "inspect_element",
                    "enumerate_assets",
                    "get_structure",
                    "screenshot",
                    "som",
                    "navigate",
                ],
                "description": (
                    "extract_design_tokens: CSS custom properties + computed root styles. "
                    "inspect_element: full computed CSS for a CSS selector. "
                    "enumerate_assets: all img/svg/bg-image/video URLs and dimensions. "
                    "get_structure: semantic HTML hierarchy with bounding boxes. "
                    "screenshot: full-page base64 PNG. "
                    "som: Set-of-Mark annotated screenshot with numbered bounding boxes. "
                    "navigate: go to url and wait for network idle."
                ),
            },
            "url": {
                "type": "string",
                "description": "URL to navigate to (for 'navigate' action).",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for 'inspect_element' action.",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        **_,
    ) -> ToolResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ToolResult.error_result("playwright is not installed; run: pip install playwright && playwright install chromium")

        if action == "navigate":
            return await self._navigate(url)

        page = self.browser.page if self.browser else None
        if page is None:
            return ToolResult.error_result(
                "No browser session active. Call advanced_browser(action='launch') first, "
                "or use action='navigate' to launch and go to a URL."
            )

        try:
            if action == "extract_design_tokens":
                return await self._extract_design_tokens(page)
            elif action == "inspect_element":
                return await self._inspect_element(page, selector)
            elif action == "enumerate_assets":
                return await self._enumerate_assets(page, url)
            elif action == "get_structure":
                return await self._get_structure(page)
            elif action == "screenshot":
                return await self._screenshot(page)
            elif action == "som":
                return await self._som(page)
            else:
                return ToolResult.error_result(f"Unknown action: {action!r}")
        except Exception as exc:
            logger.exception("BrowserInspectorTool error during action=%s", action)
            return ToolResult.error_result(str(exc))

    # ── action implementations ───────────────────────────────────────

    async def _navigate(self, url: Optional[str]) -> ToolResult:
        """Launch browser via shared adapter if needed and navigate to url."""
        if not url:
            return ToolResult.error_result("url is required for 'navigate' action")
        if self.browser is None or self.browser.page is None:
            if self.browser is None:
                from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
                self.browser = PlaywrightAdapter()
            from weebot.application.ports.browser_port import BrowserConfig
            await self.browser.start(BrowserConfig(headless=True))
        await self.browser.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return ToolResult.success_result(
            output=f"Navigated to {url}",
            data={"url": url, "action": "navigate"},
        )

    async def _extract_design_tokens(self, page) -> ToolResult:
        tokens: Dict[str, Any] = await page.evaluate(_JS_DESIGN_TOKENS)
        custom = tokens.get("custom_properties", {})
        computed = tokens.get("computed_root", {})
        summary_lines = [f"Found {len(custom)} CSS custom properties (design tokens)"]
        if custom:
            sample = list(custom.items())[:8]
            summary_lines.append("Sample tokens: " + ", ".join(f"{k}: {v}" for k, v in sample))
        return ToolResult.success_result(
            output="\n".join(summary_lines),
            data={"custom_properties": custom, "computed_root": computed},
        )

    async def _inspect_element(self, page, selector: Optional[str]) -> ToolResult:
        if not selector:
            return ToolResult.error_result("'selector' is required for inspect_element")
        result: Optional[Dict] = await page.evaluate(_JS_INSPECT_ELEMENT, selector)
        if result is None:
            return ToolResult.error_result(f"No element found matching selector: {selector!r}")
        css = result.get("computed_css", {})
        box = result.get("bounding_box", {})
        summary = (
            f"<{result['tag']}> at ({box.get('x')}, {box.get('y')}) "
            f"{box.get('width')}x{box.get('height')}px | "
            f"font: {css.get('fontFamily','?')} {css.get('fontSize','?')} | "
            f"color: {css.get('color','?')} | bg: {css.get('backgroundColor','?')}"
        )
        return ToolResult.success_result(output=summary, data=result)

    async def _enumerate_assets(self, page, base_url: Optional[str]) -> ToolResult:
        assets: List[Dict] = await page.evaluate(_JS_ENUMERATE_ASSETS)
        # Resolve relative URLs if we have a base
        current_url = page.url if hasattr(page, "url") else base_url
        if current_url:
            for a in assets:
                src = a.get("src", "")
                if src and not src.startswith(("http://", "https://", "data:")):
                    a["src"] = urljoin(current_url, src)

        by_type: Dict[str, int] = {}
        for a in assets:
            t = a.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        summary = f"Found {len(assets)} assets: " + ", ".join(f"{v} {k}" for k, v in by_type.items())
        return ToolResult.success_result(output=summary, data={"assets": assets, "counts": by_type})

    async def _get_structure(self, page) -> ToolResult:
        structure = await page.evaluate(_JS_GET_STRUCTURE)
        title = await page.title()

        def _count_nodes(node: Optional[Dict], depth=0) -> int:
            if not node:
                return 0
            return 1 + sum(_count_nodes(c, depth + 1) for c in node.get("children", []))

        n = _count_nodes(structure)
        summary = f"Page: '{title}' — {n} structural nodes extracted"
        return ToolResult.success_result(
            output=summary,
            data={"title": title, "url": page.url, "structure": structure},
        )

    async def _screenshot(self, page) -> ToolResult:
        screenshot_bytes: bytes = await page.screenshot(full_page=True)
        img_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        return ToolResult(
            output="Full-page screenshot captured",
            success=True,
            base64_image=img_b64,
            data={"format": "png", "size_bytes": len(screenshot_bytes)},
        )

    async def _som(self, page) -> ToolResult:
        """Set-of-Mark annotated screenshot with numbered bounding boxes."""
        # Get all interactive elements via Playwright's built-in selectors
        elements = []
        try:
            from weebot.infrastructure.browser.som_renderer import SomRenderer

            # Collect all clickable/interactive elements
            raw_elements = await page.query_selector_all(
                "button, a, input, select, textarea, [role=button], [role=link], "
                "[role=checkbox], [role=radio], [tabindex]:not([tabindex=-1])"
            )
            for el in raw_elements:
                try:
                    bbox = await el.bounding_box()
                    if bbox and bbox["width"] > 5 and bbox["height"] > 5:
                        tag = await el.evaluate("el => el.tagName.toLowerCase()")
                        text = (await el.inner_text() or "").strip()[:60]
                        elements.append({
                            "bounding_box": {
                                "x": round(bbox["x"]),
                                "y": round(bbox["y"]),
                                "width": round(bbox["width"]),
                                "height": round(bbox["height"]),
                            },
                            "tag": tag,
                            "text": text,
                        })
                except Exception:
                    continue

            # Take screenshot and render overlays
            screenshot_bytes = await page.screenshot(full_page=True)
            renderer = SomRenderer()
            viewport = page.viewport_size or {"width": 1920, "height": 1080}
            result = await renderer.render(
                screenshot_bytes, elements,
                page_width=viewport.get("width", 1920),
                page_height=viewport.get("height", 1080),
            )

            return ToolResult(
                output=(
                    f"Set-of-Mark screenshot: {result['mark_count']} elements marked. "
                    f"Pillow rendering: {result.get('overlay_rendered', False)}."
                ),
                success=True,
                base64_image=result.get("image", ""),
                data={
                    "marks": result["marks"],
                    "mark_count": result["mark_count"],
                    "pillow_available": result["pillow_available"],
                    "overlay_rendered": result.get("overlay_rendered", False),
                },
            )
        except Exception as exc:
            logger.warning("SoM rendering failed: %s", exc)
            return ToolResult.error_result(f"Set-of-Mark failed: {exc}")
