"""WebSearchTool — multi-engine web search with DuckDuckGo primary, Bing fallback."""
from __future__ import annotations
import os
import re
from typing import Any

import aiohttp

from weebot.tools.base import BaseTool, ToolResult

_DDG_URL = "https://html.duckduckgo.com/html/"
_BING_URL = "https://api.bing.microsoft.com/v7.0/search"


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the web for current information. "
        "Returns titles, URLs, and snippets from top results."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, num_results: int = 5, **kwargs: Any) -> ToolResult:
        num_results = min(max(1, num_results), 10)
        errors: list[str] = []

        # Primary: DuckDuckGo (no API key required)
        try:
            results = await self._search_duckduckgo(query, num_results)
            return ToolResult(output=self._format(results))
        except Exception as e:
            errors.append(f"DuckDuckGo: {e}")

        # Fallback: Bing Web Search API (requires BING_API_KEY)
        try:
            results = await self._search_bing(query, num_results)
            return ToolResult(output=self._format(results))
        except Exception as e:
            errors.append(f"Bing: {e}")

        return ToolResult(
            output="",
            error=f"All search engines failed: {'; '.join(errors)}",
        )

    async def _search_duckduckgo(
        self, query: str, num_results: int
    ) -> list[dict[str, str]]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                _DDG_URL,
                data={"q": query},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                html = await resp.text()

        results: list[dict[str, str]] = []
        link_pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="result__snippet"[^>]*>([^<]+)</a>'
        )
        links = link_pattern.findall(html)
        snippets = [m.strip() for m in snippet_pattern.findall(html)]

        for i, (url, title) in enumerate(links[:num_results]):
            results.append({
                "title": title.strip(),
                "url": url,
                "snippet": snippets[i] if i < len(snippets) else "",
            })

        if not results:
            raise ValueError("No results parsed from DuckDuckGo HTML")
        return results

    async def _search_bing(
        self, query: str, num_results: int
    ) -> list[dict[str, str]]:
        key = os.getenv("BING_API_KEY")
        if not key:
            raise ValueError("BING_API_KEY not set")
        headers = {"Ocp-Apim-Subscription-Key": key}
        params = {"q": query, "count": num_results, "mkt": "en-US"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                _BING_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", [])[:num_results]:
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
            })
        if not results:
            raise ValueError("No results from Bing")
        return results

    def _format(self, results: list[dict[str, str]]) -> str:
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines).strip()
