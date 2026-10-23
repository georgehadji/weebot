---
type: object
name: WebTools
code: WebSearchTool, ScraperTool, MoliFetchTool, VaneSearchTool, AgentReachTool, ImageSearchTool, KnowledgeTool, SearchHistoryTool, WeatherTool, OCRTool, StructuredOCRTool
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# WebTools

The read tools: web search, page fetch, scraping, image search, weather, OCR, and the two local lookups (`knowledge` notes, `search_history`). Browser tools have their own card (Browser).

## Why this shape
Each tool owns its backend and its fallback, and returns an error `ToolResult` rather than raising, so a missing key or binary costs one failed call, not a crashed step. Third-party text is not trusted: tools in `UNTRUSTED_OUTPUT_TOOLS` (`weebot/core/trust_boundary.py:49-79`) are fenced before the model sees them (`weebot/application/agents/executor/_base.py:1005-1007`). Binary-backed tools (`moli_fetch`, `agent_reach`) run a fixed argument list, never a shell (`weebot/tools/moli_fetch.py:7-15`, `weebot/tools/agent_reach.py:12-16`).

## Shape
| Tool (`name`) | Class | Backend | Needs | Fallback / when missing | Fenced |
|---|---|---|---|---|---|
| `web_search` | `weebot/tools/web_search.py:28` | Perplexity Sonar via OpenRouter (`:120-194`), DuckDuckGo HTML (`:196-223`), Bing API (`:225-248`) | `OPENROUTER_API_KEY` (`:128`); `BING_API_KEY` (`:226`); optional `RerankPort` (`:52-58`) | DDG, then Bing, only while results are short (`:72-94`); all fail: one error with every reason (`:96-97`) | yes |
| `spacescraper` | `weebot/tools/scraper.py:19` | local CLI `submit_url.py` (`:76-96`), REST `POST /jobs` (`:99-106`), `docker-compose up -d` then REST again (`:109-131, 171-174`) | `SCRAPER_DIR`, `SCRAPER_API_URL` (default `http://localhost:8000`), `SCRAPER_API_KEY` via `ToolConfig` or env (`:62-66`) | the three methods in order; error lists all three (`:134-199`) | yes |
| `moli_fetch` | `weebot/tools/moli_fetch.py:62` | Moli binary `fetch --dump`, `--block-private-networks`, 10 MB cap (`:120-128`) | `MOLI_PATH`, else PATH, else `%LOCALAPPDATA%\Moli\bin\moli.exe` (`:50-59`) | none; 403/429 adds a camofox hint (`:41-45, 145-146`); `health_check` false without the binary (`:152-153`) | yes |
| `vane_search` | `weebot/tools/vane_search.py:7` | `POST {VANE_BASE_URL}/api/search` (`:38-51`) | `VANE_BASE_URL`, default `https://api.vane.ai` (`:38`) | none; HTTP and request errors returned (`:72-84`) | yes |
| `agent_reach` | `weebot/tools/agent_reach.py:239` | allowlisted `agent-reach`, `curl`, `gh`, `yt-dlp`, `bili`, `mcporter call exa.*` (`:59-148`); `action=guide` reads the skill files (`:316-328`) | `AGENT_REACH_PATH`, else PATH, else `~/.agent-reach-venv` (`:172-184`) | none; child env is an allowlist, so Weebot keys are not inherited (`:48-53, 230-236`) | yes |
| `search_images` | `weebot/tools/image_search.py:36` | `ddgs.DDGS().images`, else `duckduckgo_search` (`:22-33, 130-131`) | package only, no key | error when neither package is installed (`:114-121`) | yes |
| `knowledge` | `weebot/tools/knowledge_tool.py:21` | `ToolRepositoryPort` notes: add/search/get/list/delete (`:83-98`) | the repo, from `Container.tool_wiring` (`weebot/application/di/_factories.py:452`); no repo raises at construction (`:70-77`) | registry skips it when the repo does not resolve (`_factories.py:458-469`) | no, by design (`trust_boundary.py:71-73`) |
| `search_history` | `weebot/tools/search_history.py:18` | FTS5 `search_events` over the sessions DB (`:47-58`) | `DB_SESSIONS_PATH` pool, built lazily (`:50-55`) | error result on search failure (`:59-60`) | no |
| `weather` | `weebot/tools/weather_tool.py:15` | `https://wttr.in/<location>?format=j1/j2` (`:56-76`; URL `weebot/config/api_endpoints.py:24`) | none | error result on HTTP or parse failure (`:70-80`) | yes, fence only (`trust_boundary.py:132`) |
| `ocr` | `weebot/tools/ocr.py:19` | `pytesseract` (`:67-73`); vision model when pytesseract or the binary is missing (`:74-78, 85-114`) | Tesseract, or `vision_llm` from `tool_wiring` (`_factories.py:451`) | vision fallback; error when neither (`:87-88`) | yes |
| `ocr_structured` | `weebot/tools/ocr.py:117` | `pytesseract.image_to_data` (`:154-156`) | Tesseract | error (`:214-217`) | yes |

Roles (from `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS`, `weebot/tools/tool_registry.py:26-165`, checked by importing it): `web_search` in 8 roles; `spacescraper` in researcher, analyst, admin, webhook; `moli_fetch`, `vane_search`, `agent_reach`, `weather` in researcher, admin, webhook; `search_images` in 6; `knowledge` in 8; `search_history` and `ocr` in admin and webhook only; `ocr_structured` in none.

Consequences (read from source, not run):
- `search_images` puts every URL in `data["images"]` and returns only `"Found N images for '<query>'."` as `output` (`image_search.py:148-152`). The model sees `str(result)`, which is `output` (`weebot/domain/models/tool_result.py:57-60`, `_base.py:1005`); `data` goes to `_facts` only (`_base.py:971-972`). The agent is told to use this tool first for real images (`image_search.py:49-54`) and cannot see one.
- `search_images` runs the synchronous `DDGS().images` inside `async execute` (`image_search.py:130-131`), blocking the event loop for the request.
- `search_images` passes `data=` to `error_result`, which has no `data` parameter, so the empty list lands in `metadata["data"]` (`image_search.py:115-121, 156-158`; `tool_result.py:96-108`).
- `vane_search` returns only the answer text; the sources go to `metadata` (`vane_search.py:67-70`), so the model gets no citations.
- `spacescraper` can run `docker-compose up -d` in `SCRAPER_DIR` (`scraper.py:113-120`). It is not a guarded tool (`weebot/application/services/tool_guards.py:43`) and stays in the `webhook` role, which drops the exec tools (`tool_registry.py:107-144`).
- `ocr` reads any `image_path` with no workspace check (`ocr.py:58-59`), unlike `file_editor`. When pytesseract is not installed the bytes go to the vision model before any image decode (`:67-75, 91-92`), so a non-image file is sent to the LLM provider as a data URL.
- `search_history` searches every past session (`search_history.py:22-26, 58`) and is not in `UNTRUSTED_OUTPUT_TOOLS`, so stored event text, which can come from earlier web results, comes back unfenced; it is in the `webhook` role.
- `agent_reach`'s `curl` accepts any http(s) URL (`agent_reach.py:80-81`); unlike `moli_fetch` nothing blocks private or loopback hosts.
- `weather` puts `location` into the URL path unescaped (`weather_tool.py:57`).
- `web_search` and `vane_search` read keys with `os.getenv` / `os.environ.get` (`web_search.py:128, 226`, `vane_search.py:38`), as `resolve_setting` does (`weebot/config/tool_config.py:76-89`). Every entry point runs `load_dotenv(override=True)` first (`cli/main.py:59-61`, `run.py:17`, `run_mcp.py:21`, `weebot/interfaces/web/main.py:28-30`), so a key in `.env` is seen. `BING_API_KEY`, `VANE_BASE_URL` and the `SCRAPER_*` keys are not in `.env.example`; `MOLI_PATH` and `AGENT_REACH_PATH` are, commented (`.env.example:117, 120`).
- The MCP server builds `WebSearchTool()` unwrapped (`weebot/mcp/server.py:393`).

## Connected to
- **Built by** `RoleBasedToolRegistry`: `set_config` for `spacescraper`, `moli_fetch`, `agent_reach`; `set_rerank` for `web_search`; collaborators for `knowledge` and `ocr` (`tool_registry.py:463-504`, `_factories.py:430-469`).
- **Fenced and tainted by** `weebot/core/trust_boundary.py` (`wrap_untrusted` `:97`, `taints_egress_context` `:155`) through the executor (`_tool_executor.py:398-399`).
- **Related:** the BaseTool card (call path), the EgressGuard card, the Browser card (`advanced_browser`, `camofox_browser`).
- **Looks like but is not:** `web_scraper`, `screenshot_ocr`, `youtube_download`: other tool names in `trust_boundary.py` and other modules, not covered here.

## If you change this
**Hits:** researcher, admin and webhook roles mostly; MCP `web_search`. Tests: `tests/unit/tools/test_web_search.py`, `tests/unit/test_scraper_tool.py`, `tests/unit/fixes/test_f15_tool_dirs_unset.py`, `tests/unit/tools/test_moli_fetch.py`, `tests/unit/tools/test_vane_search.py`, `tests/integration/test_vane_integration.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_knowledge_tool.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/tools/test_ocr.py`, `tests/unit/tools/test_ocr_vision_fallback.py`, `tests/unit/tools/test_computer_use.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/interfaces/test_mcp_server.py`. No test imports `ImageSearchTool`, `SearchHistoryTool` or `WeatherTool`.
**Does not hit:** the shell guards (none of these is a guarded tool); browser tools.

## Surfaces
Agent tool calls; MCP `web_search`.

## See
`weebot/tools/web_search.py`, `weebot/tools/agent_reach.py`, `weebot/core/trust_boundary.py`
