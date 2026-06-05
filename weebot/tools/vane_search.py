import os
from typing import Any, Dict, List, Optional
import httpx
from weebot.config.settings import WeebotSettings
from weebot.tools.base import BaseTool, ToolResult


class VaneSearchTool(BaseTool):
    name: str = "vane_search"
    description: str = (
        "AI-powered search that returns cited answers. Use for deep research, "
        "academic queries, or when citations are required. "
        "Focus modes: webSearch, academicSearch, redditSearch, youtubeSearch. "
        "Optimization modes: speed, balanced, quality."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The research question or search query.",
            },
            "focus_mode": {
                "type": "string",
                "description": "The search universe (e.g., 'webSearch', 'academicSearch'). Defaults to 'webSearch'.",
                "enum": ["webSearch", "academicSearch", "redditSearch", "youtubeSearch"],
                "default": "webSearch",
            },
            "optimization": {
                "type": "string",
                "description": "Prioritize speed, balance, or quality. Defaults to 'balanced'.",
                "enum": ["speed", "balanced", "quality"],
                "default": "balanced",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        focus_mode: str = "webSearch",
        optimization: str = "balanced",
        **_: Any
    ) -> ToolResult:
        base_url = os.environ.get("VANE_BASE_URL", "https://api.vane.ai")
        
        payload = {
            "query": query,
            "focusMode": focus_mode,
            "optimizationMode": optimization,
            "stream": False # Weebot expects a single response, not a stream
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{base_url}/api/search", json=payload)
                resp.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                data = resp.json()

                message = data.get("message", "No message provided by Vane.")
                sources = data.get("sources", [])

                # Format sources for metadata
                formatted_sources = []
                for source in sources:
                    formatted_sources.append({
                        "title": source.get("metadata", {}).get("title", "N/A"),
                        "url": source.get("metadata", {}).get("url", "N/A"),
                        "content": source.get("content", "N/A")
                    })

                return ToolResult(
                    output=message,
                    metadata={"sources": formatted_sources, "vane_response_raw": data},
                )

        except httpx.RequestError as exc:
            return ToolResult(
                output="",
                error=f"Vane API request failed for {exc.request.url!r}: {exc}",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                output="",
                error=f"Vane API returned an error {exc.response.status_code} for {exc.request.url!r}: {exc.response.text}",
            )
        except Exception as e:
            return ToolResult(
                output="",
                error=f"An unexpected error occurred during Vane search: {e}",
            )

