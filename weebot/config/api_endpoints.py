"""API endpoint URLs — single source of truth for all external service URLs.

All modules import base URLs from here instead of hardcoding them.
"""
from __future__ import annotations

# ── LLM Provider Base URLs ─────────────────────────────────────────

DEEPSEEK_API_BASE: str = "https://api.deepseek.com"
MOONSHOT_API_BASE: str = "https://api.moonshot.ai/v1"
MINIMAX_API_BASE: str = "https://api.minimax.io"
MINIMAX_API_BASE_ANTHROPIC: str = "https://api.minimax.io/anthropic"  # for Anthropic SDK path
OPENROUTER_API_BASE: str = "https://openrouter.ai/api/v1"
OPENAI_API_BASE: str = "https://api.openai.com/v1"
XAI_API_BASE: str = "https://api.x.ai/v1"
XAI_IMAGE_GENERATION_URL: str = "https://api.x.ai/v1/images/generations"
IDEOGRAM_GENERATION_URL: str = "https://api.ideogram.ai/v1/ideogram-v3/generate"

# ── Search / External API URLs ─────────────────────────────────────

SEARCH_DDG_URL: str = "https://html.duckduckgo.com/html/"
SEARCH_BING_URL: str = "https://api.bing.microsoft.com/v7.0/search"
WEATHER_WTTR_URL: str = "https://wttr.in"
