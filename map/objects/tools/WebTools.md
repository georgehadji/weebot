---
type: object
name: WebTools
code: WebSearchTool, ScraperTool, MoliFetchTool, VaneSearchTool, AgentReachTool, ImageSearchTool, KnowledgeTool, SearchHistoryTool, WeatherTool, OCRTool, StructuredOCRTool
cluster: tools
universe: live
status: verified
verified: 2026-10-30
commit: 8e6d1cca
---

# WebTools

The read tools: web search, page fetch, scraping, image search, weather, OCR, and the two local lookups (`knowledge` notes, `search_history`). Browser tools have their own card (Browser).

## Why this shape
Each tool owns its backend and its fallback, and returns an error `ToolResult` rather than raising, so a missing key or binary costs one failed call, not a crashed step. Third-party text is not trusted: each tool declares an `OutputTrust` (`weebot/domain/models/output_trust.py:18-33`), and output of anything but a `LOCAL` tool is fenced before the model sees it (`weebot/core/trust_boundary.py:58-90`, `weebot/application/agents/executor/_base.py:252-274`). Binary-backed tools (`moli_fetch`, `agent_reach`) run a fixed argument list, never a shell (`weebot/tools/moli_fetch.py:7-15`, `weebot/tools/agent_reach.py:12-16`).

## Shape
| Tool (`name`) | Class | Backend | Needs | Fallback / when missing | Fenced |
|---|---|---|---|---|---|
| `web_search` | `weebot/tools/web_search.py:29` | Perplexity Sonar via OpenRouter (`weebot/tools/web_search.py:123-197`), DuckDuckGo HTML (`weebot/tools/web_search.py:199-226`), Bing API (`weebot/tools/web_search.py:228-251`) | `OPENROUTER_API_KEY` (`weebot/tools/web_search.py:131`); `BING_API_KEY` (`weebot/tools/web_search.py:229`); optional `RerankPort` (`weebot/tools/web_search.py:52-61`) | DDG, then Bing, only while results are short (`weebot/tools/web_search.py:75-97`); all fail: one error with every reason (`weebot/tools/web_search.py:99-100`) | yes (`:31`) |
| `spacescraper` | `weebot/tools/scraper.py:20` | local CLI `submit_url.py` (`weebot/tools/scraper.py:79-99`), REST `POST /jobs` (`weebot/tools/scraper.py:102-109`), `docker-compose up -d` then REST again (`weebot/tools/scraper.py:112-134, 174-177`) | `SCRAPER_DIR`, `SCRAPER_API_URL` (default `http://localhost:8000`), `SCRAPER_API_KEY` via `ToolConfig` or env (`weebot/tools/scraper.py:65-69`) | the three methods in order; error lists all three (`weebot/tools/scraper.py:136-206`) | yes (`:27`) |
| `moli_fetch` | `weebot/tools/moli_fetch.py:63` | Moli binary `fetch --dump`, `--block-private-networks`, 10 MB cap (`weebot/tools/moli_fetch.py:123-131`) | `MOLI_PATH`, else PATH, else `%LOCALAPPDATA%\Moli\bin\moli.exe` (`weebot/tools/moli_fetch.py:51-60`) | none; 403/429 adds a camofox hint (`weebot/tools/moli_fetch.py:40-46, 148-149`); `health_check` false without the binary (`weebot/tools/moli_fetch.py:155-156`) | yes (`:66`) |
| `vane_search` | `weebot/tools/vane_search.py:8` | `POST {VANE_BASE_URL}/api/search` (`weebot/tools/vane_search.py:41-54`) | `VANE_BASE_URL`, default `https://api.vane.ai` (`weebot/tools/vane_search.py:41`) | none; HTTP and request errors returned (`weebot/tools/vane_search.py:79-91`) | yes (`:10`) |
| `agent_reach` | `weebot/tools/agent_reach.py:240` | allowlisted `agent-reach`, `curl`, `gh`, `yt-dlp`, `bili`, `mcporter call exa.*` (`weebot/tools/agent_reach.py:57-149`); `action=guide` reads the skill files (`weebot/tools/agent_reach.py:319-331`) | `AGENT_REACH_PATH`, else PATH, else `~/.agent-reach-venv` (`weebot/tools/agent_reach.py:173-185`) | none; child env is an allowlist, so Weebot keys are not inherited (`weebot/tools/agent_reach.py:48-54, 231-237`) | yes (`:243`) |
| `search_images` | `weebot/tools/image_search.py:37` | `ddgs.DDGS().images`, else `duckduckgo_search` (`weebot/tools/image_search.py:23-34, 133-134`) | package only, no key | error when neither package is installed (`weebot/tools/image_search.py:117-124`) | yes (`:49`) |
| `knowledge` | `weebot/tools/knowledge_tool.py:22` | `ToolRepositoryPort` notes: add/search/get/list/delete (`weebot/tools/knowledge_tool.py:86-101`) | the repo, from `Container.tool_wiring` (`weebot/application/di/_factories.py:540-587`); no repo raises at construction (`weebot/tools/knowledge_tool.py:73-80`) | registry skips it when the repo does not resolve (`weebot/application/di/_factories.py:584-587`, `weebot/application/services/tool_registry.py:514-524`) | no: `LOCAL`, a reviewed decision (`weebot/tools/knowledge_tool.py:37`) |
| `search_history` | `weebot/tools/search_history.py:19` | FTS5 `search_events` over the sessions DB (`weebot/tools/search_history.py:50-61`) | `DB_SESSIONS_PATH` pool, built lazily (`weebot/tools/search_history.py:53-58`) | error result on search failure (`weebot/tools/search_history.py:62-63`) | yes (`:22`) |
| `weather` | `weebot/tools/weather_tool.py:16` | `https://wttr.in/<location>?format=j1/j2` (`weebot/tools/weather_tool.py:58-79`; URL `weebot/config/api_endpoints.py:24`) | none | error result on HTTP or parse failure (`weebot/tools/weather_tool.py:73-83`) | yes, fence only: `FIXED_SCHEMA` (`weebot/tools/weather_tool.py:18`) |
| `ocr` | `weebot/tools/ocr.py:35` | `pytesseract`, decode and OCR in `asyncio.to_thread` (`weebot/tools/ocr.py:87-93`); vision model when pytesseract or the binary is missing (`weebot/tools/ocr.py:94-98, 105-134`) | Tesseract, or `vision_llm` from `tool_wiring` (`weebot/application/di/_factories.py:545`) | vision fallback; error when neither (`weebot/tools/ocr.py:107-108`) | yes (`:38`) |
| `ocr_structured` | `weebot/tools/ocr.py:137` | `pytesseract.image_to_data` in `asyncio.to_thread` (`weebot/tools/ocr.py:176-178`) | Tesseract | error (`weebot/tools/ocr.py:236-239`) | yes (`:140`) |

Roles (from `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS`, `weebot/application/services/tool_registry.py:26-185`, checked by importing it): `web_search` in 8 roles; `spacescraper` in researcher, analyst, admin; `moli_fetch`, `vane_search`, `agent_reach`, `weather` in researcher, admin, webhook; `search_images` in 6; `knowledge` in 8; `search_history` and `ocr` in admin and webhook only; `ocr_structured` in researcher and admin.

Consequences (read from source, not run):
- `search_images` lists every title and URL in `output` and keeps them in `data["images"]` too (`weebot/tools/image_search.py:149-160`); the model sees only `output` (see the BaseTool card).
- `search_images` runs the synchronous `DDGS().images` inside `async execute`, not in a thread (`weebot/tools/image_search.py:133-134`), blocking the event loop for the request.
- `search_images` passes `data=` to `error_result`, which has no `data` parameter, so the empty list lands in `metadata["data"]` (`weebot/tools/image_search.py:117-124, 164-167`; `weebot/domain/models/tool_result.py:96-108`).
- `vane_search` appends source titles and URLs to the answer (`weebot/tools/vane_search.py:70-73`) and keeps the full sources in `metadata` (`weebot/tools/vane_search.py:74-77`).
- `spacescraper` can run `docker-compose up -d` in `SCRAPER_DIR` (`weebot/tools/scraper.py:116-123`). It is not a guarded tool (`weebot/application/services/tool_guards.py:43`); the `webhook` role drops it (`weebot/application/services/tool_registry.py:124-127`).
- `ocr` refuses an `image_path` outside the workspace (`WORKSPACE_ROOT`, resolved absolute, `weebot/config/settings.py:19`) or denied by the filesystem policy, as `file_editor` does (`weebot/tools/ocr.py:18-30, 77-78`). When pytesseract is not installed the bytes go to the vision model before any image decode (`weebot/tools/ocr.py:87-95, 111-112`), so a non-image file inside the workspace is sent to the LLM provider as a data URL.
- `search_history` searches every past session (`weebot/tools/search_history.py:25-30, 61`); its output is fenced and taints egress; it is in the `webhook` role.
- `agent_reach`'s `curl` accepts any http(s) URL (`weebot/tools/agent_reach.py:81-82`); unlike `moli_fetch` nothing blocks private or loopback hosts.
- `weather` puts `location` into the URL path unescaped (`weebot/tools/weather_tool.py:60`).
- `web_search` and `vane_search` read keys with `os.getenv` / `os.environ.get` (`weebot/tools/web_search.py:131, 229`, `weebot/tools/vane_search.py:41`), as `resolve_setting` does (`weebot/config/tool_config.py:76-89`). Every entry point runs `load_dotenv(override=True)` first (`cli/main.py:58-61`, `run.py:17`, `run_mcp.py:21`, `weebot/interfaces/web/main.py:29-31`), so a key in `.env` is seen. `BING_API_KEY`, `VANE_BASE_URL` and the `SCRAPER_*` keys are not in `.env.example`; `MOLI_PATH` and `AGENT_REACH_PATH` are, commented (`.env.example:147, 150`).
- The MCP server builds `WebSearchTool()` unwrapped (`weebot/mcp/server.py:393`).

## Connected to
- **Built by** `RoleBasedToolRegistry`: `set_config` for `spacescraper`, `moli_fetch`, `agent_reach`; `set_rerank` for `web_search`; collaborators for `knowledge` and `ocr` (`weebot/application/services/tool_registry.py:446-527`, `weebot/application/di/_factories.py:540-587`).
- **Fenced and tainted by** `weebot/core/trust_boundary.py` (`must_fence` `:74`, `must_taint` `:79`, `wrap_untrusted` `:107`) through the executor (`weebot/application/agents/executor/_base.py:252-274`, `weebot/application/agents/executor/_tool_executor.py:584-618`). A tool that declares nothing is `EXTERNAL`.
- **Related:** the BaseTool card (call path), the EgressGuard card, the Browser card (`advanced_browser`, `camofox_browser`).
- **Looks like but is not:** `web_scraper`, `screenshot_ocr`, `youtube_download`: other tools, each declaring its own `output_trust` in its module, not covered here.

## If you change this
**Hits:** researcher, admin and webhook roles mostly; MCP `web_search`. Tests: `tests/unit/tools/test_web_search.py`, `tests/unit/test_scraper_tool.py`, `tests/unit/fixes/test_f15_tool_dirs_unset.py`, `tests/unit/tools/test_moli_fetch.py`, `tests/unit/tools/test_vane_search.py`, `tests/integration/test_vane_integration.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_knowledge_tool.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/tools/test_ocr.py`, `tests/unit/tools/test_ocr_vision_fallback.py`, `tests/unit/tools/test_computer_use.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/interfaces/test_mcp_server.py`, `tests/unit/fixes/test_search_results_reach_the_model.py` (`search_images`, `vane_search`). Only `tests/unit/fixes/test_webhook_role_runs_nothing.py` imports `SearchHistoryTool` (for its trust only); no test runs it or `WeatherTool`.
**Does not hit:** the shell guards (none of these is a guarded tool); browser tools.

## Surfaces
Agent tool calls; MCP `web_search`.

## See
`weebot/tools/web_search.py`, `weebot/tools/agent_reach.py`, `weebot/core/trust_boundary.py`
