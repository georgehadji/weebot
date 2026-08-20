"""WebSearchTool — multi-engine web search with Perplexity Sonar primary,
DuckDuckGo and Bing fallbacks.

Supports optional cross-encoder reranking via ``RerankPort``.  When a reranker
is injected, search results from all engines are deduplicated and reranked
against the original query before being returned.
"""

from __future__ import annotations
import logging
import os
import re
from typing import Any

import aiohttp
from pydantic import PrivateAttr

from weebot.config.api_endpoints import OPENROUTER_API_BASE, SEARCH_DDG_URL, SEARCH_BING_URL
from weebot.config.model_refs import MODEL_SEARCH_PERPLEXITY_SONAR
from weebot.tools.base import BaseTool, ToolResult

_DDG_URL = SEARCH_DDG_URL
_BING_URL = SEARCH_BING_URL

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    default_timeout_seconds: int = 25
    truncation_strategy: str = "boundary"
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

    # Optional reranker — injected by DI after construction.
    _rerank: Any = PrivateAttr(default=None)

    def set_rerank(self, rerank: Any) -> None:
        """Inject a ``RerankPort`` instance for cross-encoder reranking.

        Called by the DI container after tool construction.
        Pass ``None`` to disable reranking.
        """
        self._rerank = rerank

    async def execute(self, query: str, num_results: int = 5, **kwargs: Any) -> ToolResult:
        num_results = min(max(1, num_results), 10)
        errors: list[str] = []
        all_results: list[dict[str, str]] = []

        # Primary: Perplexity Sonar via OpenRouter (search-grounded, citations)
        try:
            pp_results = await self._search_perplexity(query, num_results)
            all_results.extend(pp_results)
        except Exception as e:
            errors.append(f"Perplexity: {e}")

        # Fallback 1: DuckDuckGo (no API key required)
        try:
            ddg_results = await self._search_duckduckgo(query, num_results * 2)
            seen_urls = {r.get("url", "") for r in all_results}
            for r in ddg_results:
                if r.get("url", "") not in seen_urls:
                    all_results.append(r)
        except Exception as e:
            errors.append(f"DuckDuckGo: {e}")

        # Fallback 2: Bing Web Search API (requires BING_API_KEY)
        try:
            bing_results = await self._search_bing(query, num_results)
            seen_urls = {r.get("url", "") for r in all_results}
            for r in bing_results:
                if r.get("url", "") not in seen_urls:
                    all_results.append(r)
        except Exception as e:
            errors.append(f"Bing: {e}")

        if not all_results:
            return ToolResult(output="", error=f"All search engines failed: {'; '.join(errors)}")

        # ── Rerank against the query (or keep engine order) ─────
        if self._rerank is not None and len(all_results) > num_results:
            try:
                from weebot.config.model_refs import RERANK_MODEL_FAST

                documents = [
                    f"{r.get('title', '')}: {r.get('snippet', '')[:300]}" for r in all_results
                ]
                reranked = await self._rerank.rerank(
                    query=query, documents=documents, model=RERANK_MODEL_FAST, top_n=num_results
                )
                results = [all_results[rr.index] for rr in reranked if rr.index < len(all_results)][
                    :num_results
                ]
                logger.debug("Search reranked: %d results → top %d", len(all_results), len(results))
                return ToolResult(output=self._format(results))
            except Exception as exc:
                logger.warning("Search rerank failed, using engine order: %s", exc)

        return ToolResult(output=self._format(all_results[:num_results]))

    async def _search_perplexity(self, query: str, num_results: int) -> list[dict[str, str]]:
        """Search via Perplexity Sonar on OpenRouter.

        Calls the OpenRouter chat completions API with ``perplexity/sonar``,
        which returns both a prose answer and structured ``search_results``
        (title / url / snippet / date).  We keep ``max_tokens`` low because
        we only need the search results, not the prose synthesis.
        """
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY not set — cannot use Perplexity Sonar")

        url = f"{OPENROUTER_API_BASE}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": MODEL_SEARCH_PERPLEXITY_SONAR,
            "messages": [{"role": "user", "content": query}],
            "max_tokens": 512,
        }

        async with (
            aiohttp.ClientSession(headers=headers) as session,
            session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp,
        ):
            data = await resp.json()

        if resp.status != 200:
            raise ValueError(
                f"OpenRouter returned {resp.status}: {data.get('error', {}).get('message', str(data))}"
            )

        results: list[dict[str, str]] = []

        # ── Try structured search_results first ──────────────────
        search_results = data.get("search_results")
        if isinstance(search_results, list):
            for sr in search_results[:num_results]:
                results.append(
                    {
                        "title": sr.get("title", ""),
                        "url": sr.get("url", ""),
                        "snippet": sr.get("snippet", ""),
                    }
                )

        # ── Fallback: parse citations array ──────────────────────
        if not results:
            citations = data.get("citations")
            choices = data.get("choices", [])
            content = ""
            if choices:
                content = choices[0].get("message", {}).get("content", "")

            if isinstance(citations, list) and citations:
                for i, url in enumerate(citations[:num_results]):
                    # Try to extract a title/snippet from the content
                    snippet = ""
                    if content:
                        # Look for bracketed citation references like [1], [2]
                        snippet_match = re.search(rf"\[{i + 1}\][^\n]{{0,200}}", content)
                        if snippet_match:
                            snippet = snippet_match.group(0).strip()
                    results.append(
                        {
                            "title": url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title(),
                            "url": url,
                            "snippet": snippet,
                        }
                    )

        if not results:
            raise ValueError("No search results or citations returned from Perplexity Sonar")

        logger.debug("Perplexity Sonar: %d results for query %r", len(results), query[:80])
        return results[:num_results]

    async def _search_duckduckgo(self, query: str, num_results: int) -> list[dict[str, str]]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with (
            aiohttp.ClientSession(headers=headers) as session,
            session.post(
                _DDG_URL, data={"q": query}, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp,
        ):
            html = await resp.text()

        results: list[dict[str, str]] = []
        link_pattern = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>')
        snippet_pattern = re.compile(r'<a[^>]+class="result__snippet"[^>]*>([^<]+)</a>')
        links = link_pattern.findall(html)
        snippets = [m.strip() for m in snippet_pattern.findall(html)]

        for i, (url, title) in enumerate(links[:num_results]):
            results.append(
                {
                    "title": title.strip(),
                    "url": url,
                    "snippet": snippets[i] if i < len(snippets) else "",
                }
            )

        if not results:
            raise ValueError("No results parsed from DuckDuckGo HTML")
        return results

    async def _search_bing(self, query: str, num_results: int) -> list[dict[str, str]]:
        key = os.getenv("BING_API_KEY")
        if not key:
            raise ValueError("BING_API_KEY not set")
        headers = {"Ocp-Apim-Subscription-Key": key}
        params = {"q": query, "count": num_results, "mkt": "en-US"}
        async with (
            aiohttp.ClientSession(headers=headers) as session,
            session.get(_BING_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            data = await resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", [])[:num_results]:
            results.append(
                {
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
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
