"""ImageSearchTool — free web image search via DuckDuckGo.

Provides agents with a search_images capability that returns structured
image results (URLs, dimensions, source pages) before falling back to
AI image generation. Uses DuckDuckGo Images — free, no API key required.

The tool degrades gracefully when the optional ``duckduckgo_search``
package is not installed (returns a clear error message).
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Use ddgs (v9+, httpx-based) for DuckDuckGo image search with
# duckduckgo_search (v8, primp-based) as legacy fallback.
try:
    from ddgs import DDGS

    _DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS

        _DDGS_AVAILABLE = True
    except ImportError:
        _DDGS_AVAILABLE = False
        DDGS = None  # type: ignore[assignment]


class ImageSearchTool(BaseTool):
    """Search the public web for images matching a query.

    Returns structured results with image URLs, dimensions, thumbnails,
    and source pages. Designed as the primary image source for
    website-building and asset-design workflows.

    The tool's ``execute`` method is safe for concurrency — DDGS
    creates a fresh session per invocation.  The ``duckduckgo_search``
    library handles rate-limiting transparently.
    """

    name: str = "search_images"
    description: str = (
        "Search the web for images matching a query. "
        "Returns image URLs, dimensions, thumbnail URLs, and source pages. "
        "Use this FIRST when you need real images for a website or project. "
        "Only fall back to image_gen if search_images returns insufficient results."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The image search query. Be specific and descriptive — "
                    "include subject, style, mood, and composition cues."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum images to return (default 10, max 30).",
                "default": 10,
            },
            "size_filter": {
                "type": "string",
                "description": "Size filter: 'large', 'medium', 'small', 'wallpaper'.",
                "enum": ["large", "medium", "small", "wallpaper"],
                "default": "large",
            },
            "layout": {
                "type": "string",
                "description": "Image aspect ratio: 'Square', 'Tall', 'Wide'.",
                "enum": ["Square", "Tall", "Wide"],
                "default": None,
            },
        },
        "required": ["query"],
    }

    default_timeout_seconds: int = 30
    allowed_roles: list[str] = [
        "designer",
        "builder",
        "creative",
        "researcher",
        "automation",
        "architect",
        "planner",
        "executor",
    ]

    async def execute(
        self,
        query: str,
        max_results: int = 10,
        size_filter: str | None = "large",
        layout: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute an image search.

        Args:
            query: The image search query.
            max_results: Maximum number of results (capped at 30).
            size_filter: Image size: 'large', 'medium', 'small', 'wallpaper',
                or None for any size.
            layout: Aspect ratio: 'Square', 'Tall', 'Wide', or None for any.
            **kwargs: Ignored — allows forwarding extra kwargs from the
                executor.

        Returns:
            ToolResult with ``data["images"]`` containing a list of image
            result dicts.  On error, returns an error result with
            ``data["images"]`` set to an empty list.
        """
        max_results = min(max(1, max_results), 30)

        if not _DDGS_AVAILABLE:
            return ToolResult.error_result(
                error=(
                    "duckduckgo_search package not installed. "
                    "Install with: pip install duckduckgo-search"
                ),
                data={"images": [], "query": query, "count": 0},
            )

        try:
            ddgs_kwargs: dict[str, Any] = {"max_results": max_results}
            if size_filter:
                ddgs_kwargs["size"] = size_filter
            if layout:
                ddgs_kwargs["layout"] = layout

            with DDGS() as ddgs:
                raw_results = list(ddgs.images(query, **ddgs_kwargs))

            images = []
            for r in raw_results:
                images.append({
                    "title": r.get("title", ""),
                    "image_url": r.get("image", ""),
                    "thumbnail_url": r.get("thumbnail", ""),
                    "source_url": r.get("url", ""),
                    "width": r.get("width", 0),
                    "height": r.get("height", 0),
                })

            logger.info(
                "Image search returned %d results for query=%r",
                len(images), query,
            )

            return ToolResult.success_result(
                output=f"Found {len(images)} images for '{query}'.",
                data={
                    "images": images,
                    "query": query,
                    "count": len(images),
                },
                execution_time_ms=0,
            )

        except Exception as exc:
            logger.warning("Image search failed for query=%r: %s", query, exc)
            return ToolResult.error_result(
                error=f"Image search failed: {exc}",
                data={"images": [], "query": query, "count": 0},
            )

    async def health_check(self) -> bool:
        """Return True if the ddgs library is available.

        The tool also checks for the legacy ``duckduckgo_search`` package
        as a fallback.
        """
        return _DDGS_AVAILABLE
