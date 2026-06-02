"""API endpoint URLs — single source of truth for all external service URLs.

All modules import base URLs from here instead of hardcoding them.
"""
from __future__ import annotations

# ── LLM Provider Base URLs ─────────────────────────────────────────

DEEPSEEK_API_BASE: str = "https://api.deepseek.com"
OPENROUTER_API_BASE: str = "https://openrouter.ai/api/v1"
OPENAI_API_BASE: str = "https://api.openai.com/v1"

# ── Search / External API URLs ─────────────────────────────────────

SEARCH_DDG_URL: str = "https://html.duckduckgo.com/html/"
SEARCH_BING_URL: str = "https://api.bing.microsoft.com/v7.0/search"
WEATHER_WTTR_URL: str = "https://wttr.in"
