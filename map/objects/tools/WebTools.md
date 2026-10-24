---
type: object
name: WebTools
code: WebSearchTool, ScraperTool, MoliFetchTool, VaneSearchTool, AgentReachTool, ImageSearchTool, KnowledgeTool, SearchHistoryTool, WeatherTool, OCRTool, StructuredOCRTool
cluster: tools
universe: live
status: stale
stale_reason: 2026-10-24 remediation moved code these citations point at (tool registry, trust boundary, flow builder, DI); re-verify against source
verified: 2026-10-24
commit: d4ffb555
---

# WebTools

The read tools: web search, page fetch, scraping, image search, weather, OCR, and the two local lookups (`knowledge` notes, `search_history`). Browser tools have their own card (Browser).

## Why this shape
Each tool owns its backend and its fallback, and returns an error `ToolResult` rather than raising, so a missing key or binary costs one failed call, not a crashed step. Third-party text is not trusted: tools in `UNTRUSTED_OUTPUT_TOOLS` (`weebot/core/trust_boundary.py:49-95`) are fenced before the model sees them (`weebot/application/agents/executor/_base.py:1041-1043`). Binary-backed tools (`moli_fetch`, `agent_reach`) run a fixed argument list, never a shell (`weebot/tools/moli_fetch.py:7-15`, `weebot/tools/agent_reach.py:12-16`).

## Shape
| Tool (`name`) | Class | Backend | Needs | Fallback / when missing | Fenced |
|---|---|---|---|---|---|
| `web_search` | `weebot/tools/web_search.py:28` | Perplexity Sonar via OpenRouter (`weebot/tools/web_search.py:120-194`), DuckDuckGo HTML (`weebot/tools/web_search.py:196-223`), Bing API (`weebot/tools/web_search.py:225-248`) | `OPENROUTER_API_KEY` (`weebot/tools/web_search.py:128`); `BING_API_KEY` (`weebot/tools/web_search.py:226`); optional `RerankPort` (`weebot/tools/web_search.py:52-58`) | DDG, then Bing, only while results are short (`weebot/tools/web_search.py:72-94`); all fail: one error with every reason (`weebot/tools/web_search.py:96-97`) | yes |
| `spacescraper` | `weebot/tools/scraper.py:19` | local CLI `submit_url.py` (`weebot/tools/scraper.py:76-96`), REST `POST /jobs` (`weebot/tools/scraper.py:99-106`), `docker-compose up -d` then REST again (`weebot/tools/scraper.py:109-131, 171-174`) | `SCRAPER_DIR`, `SCRAPER_API_URL` (default `http://localhost:8000`), `SCRAPER_API_KEY` via `ToolConfig` or env (`weebot/tools/scraper.py:62-66`) | the three methods in order; error lists all three (`weebot/tools/scraper.py:134-199`) | yes |
| `moli_fetch` | `weebot/tools/moli_fetch.py:62` | Moli binary `fetch --dump`, `--block-private-networks`, 10 MB cap (`weebot/tools/moli_fetch.py:120-128`) | `MOLI_PATH`, else PATH, else `%LOCALAPPDATA%\Moli\bin\moli.exe` (`weebot/tools/moli_fetch.py:50-59`) | none; 403/429 adds a camofox hint (`weebot/tools/moli_fetch.py:41-45, 145-146`); `health_check` false without the binary (`weebot/tools/moli_fetch.py:152-153`) | yes |
| `vane_search` | `weebot/tools/vane_search.py:7` | `POST {VANE_BASE_URL}/api/search` (`weebot/tools/vane_search.py:38-51`) | `VANE_BASE_URL`, default `https://api.vane.ai` (`weebot/tools/vane_search.py:38`) | none; HTTP and request errors returned (`weebot/tools/vane_search.py:76-88`) | yes |
| `agent_reach` | `weebot/tools/agent_reach.py:239` | allowlisted `agent-reach`, `curl`, `gh`, `yt-dlp`, `bili`, `mcporter call exa.*` (`weebot/tools/agent_reach.py:59-148`); `action=guide` reads the skill files (`weebot/tools/agent_reach.py:316-328`) | `AGENT_REACH_PATH`, else PATH, else `~/.agent-reach-venv` (`weebot/tools/agent_reach.py:172-184`) | none; child env is an allowlist, so Weebot keys are not inherited (`weebot/tools/agent_reach.py:48-53, 230-236`) | yes |
| `search_images` | `weebot/tools/image_search.py:36` | `ddgs.DDGS().images`, else `duckduckgo_search` (`weebot/tools/image_search.py:22-33, 130-131`) | package only, no key | error when neither package is installed (`weebot/tools/image_search.py:114-121`) | yes |
| `knowledge` | `weebot/tools/knowledge_tool.py:21` | `ToolRepositoryPort` notes: add/search/get/list/delete (`weebot/tools/knowledge_tool.py:83-98`) | the repo, from `Container.tool_wiring` (`weebot/application/di/_factories.py:457`); no repo raises at construction (`weebot/tools/knowledge_tool.py:70-77`) | registry skips it when the repo does not resolve (`weebot/application/di/_factories.py:464-475`) | no, by design (`weebot/core/trust_boundary.py:72-75`) |
| `search_history` | `weebot/tools/search_history.py:18` | FTS5 `search_events` over the sessions DB (`weebot/tools/search_history.py:47-58`) | `DB_SESSIONS_PATH` pool, built lazily (`weebot/tools/search_history.py:50-55`) | error result on search failure (`weebot/tools/search_history.py:59-60`) | yes (`weebot/core/trust_boundary.py:64`) |
| `weather` | `weebot/tools/weather_tool.py:15` | `https://wttr.in/<location>?format=j1/j2` (`weebot/tools/weather_tool.py:56-76`; URL `weebot/config/api_endpoints.py:24`) | none | error result on HTTP or parse failure (`weebot/tools/weather_tool.py:70-80`) | yes, fence only (`weebot/core/trust_boundary.py:133`) |
| `ocr` | `weebot/tools/ocr.py:34` | `pytesseract` (`weebot/tools/ocr.py:84-90`); vision model when pytesseract or the binary is missing (`weebot/tools/ocr.py:91-95, 102-131`) | Tesseract, or `vision_llm` from `tool_wiring` (`weebot/application/di/_factories.py:455`) | vision fallback; error when neither (`weebot/tools/ocr.py:104-105`) | yes |
| `ocr_structured` | `weebot/tools/ocr.py:134` | `pytesseract.image_to_data` (`weebot/tools/ocr.py:171-173`) | Tesseract | error (`weebot/tools/ocr.py:231-232`) | yes |

Roles (from `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS`, `weebot/tools/tool_registry.py:26-185`, checked by importing it): `web_search` in 8 roles; `spacescraper` in researcher, analyst, admin; `moli_fetch`, `vane_search`, `agent_reach`, `weather` in researcher, admin, webhook; `search_images` in 6; `knowledge` in 8; `search_history` and `ocr` in admin and webhook only; `ocr_structured` in researcher and admin.

Consequences (read from source, not run):
- `search_images` lists every title and URL in `output` and keeps them in `data["images"]` too (`weebot/tools/image_search.py:148-157`); the model sees only `output` (see the BaseTool card).
- `search_images` runs the synchronous `DDGS().images` inside `async execute` (`weebot/tools/image_search.py:130-131`), blocking the event loop for the request.
- `search_images` passes `data=` to `error_result`, which has no `data` parameter, so the empty list lands in `metadata["data"]` (`weebot/tools/image_search.py:115-121, 161-163`; `weebot/domain/models/tool_result.py:96-108`).
- `vane_search` appends source titles and URLs to the answer (`weebot/tools/vane_search.py:67-70`) and keeps the full sources in `metadata` (`weebot/tools/vane_search.py:71-74`).
- `spacescraper` can run `docker-compose up -d` in `SCRAPER_DIR` (`weebot/tools/scraper.py:113-120`). It is not a guarded tool (`weebot/application/services/tool_guards.py:43`); the `webhook` role drops it (`weebot/tools/tool_registry.py:125-126`).
- `ocr` refuses an `image_path` outside the workspace or denied by the filesystem policy, as `file_editor` does (`weebot/tools/ocr.py:17-31, 73-75`). When pytesseract is not installed the bytes go to the vision model before any image decode (`weebot/tools/ocr.py:84-92, 108`), so a non-image file inside the workspace is sent to the LLM provider as a data URL.
- `search_history` searches every past session (`weebot/tools/search_history.py:22-26, 58`); its output is fenced and taints egress; it is in the `webhook` role.
- `agent_reach`'s `curl` accepts any http(s) URL (`weebot/tools/agent_reach.py:80-81`); unlike `moli_fetch` nothing blocks private or loopback hosts.
- `weather` puts `location` into the URL path unescaped (`weebot/tools/weather_tool.py:57`).
- `web_search` and `vane_search` read keys with `os.getenv` / `os.environ.get` (`weebot/tools/web_search.py:128, 226`, `weebot/tools/vane_search.py:38`), as `resolve_setting` does (`weebot/config/tool_config.py:76-89`). Every entry point runs `load_dotenv(override=True)` first (`cli/main.py:59-61`, `run.py:17`, `run_mcp.py:21`, `weebot/interfaces/web/main.py:28-30`), so a key in `.env` is seen. `BING_API_KEY`, `VANE_BASE_URL` and the `SCRAPER_*` keys are not in `.env.example`; `MOLI_PATH` and `AGENT_REACH_PATH` are, commented (`.env.example:117, 120`).
- The MCP server builds `WebSearchTool()` unwrapped (`weebot/mcp/server.py:393`).

## Connected to
- **Built by** `RoleBasedToolRegistry`: `set_config` for `spacescraper`, `moli_fetch`, `agent_reach`; `set_rerank` for `web_search`; collaborators for `knowledge` and `ocr` (`weebot/tools/tool_registry.py:446-510`, `weebot/application/di/_factories.py:435-476`).
- **Fenced and tainted by** `weebot/core/trust_boundary.py` (`wrap_untrusted` `weebot/core/trust_boundary.py:98`, `taints_egress_context` `weebot/core/trust_boundary.py:160`) through the executor (`weebot/application/agents/executor/_tool_executor.py:440-445`).
- **Related:** the BaseTool card (call path), the EgressGuard card, the Browser card (`advanced_browser`, `camofox_browser`).
- **Looks like but is not:** `web_scraper`, `screenshot_ocr`, `youtube_download`: other tool names in `weebot/core/trust_boundary.py` and other modules, not covered here.

## If you change this
**Hits:** researcher, admin and webhook roles mostly; MCP `web_search`. Tests: `tests/unit/tools/test_web_search.py`, `tests/unit/test_scraper_tool.py`, `tests/unit/fixes/test_f15_tool_dirs_unset.py`, `tests/unit/tools/test_moli_fetch.py`, `tests/unit/tools/test_vane_search.py`, `tests/integration/test_vane_integration.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_knowledge_tool.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/tools/test_ocr.py`, `tests/unit/tools/test_ocr_vision_fallback.py`, `tests/unit/tools/test_computer_use.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/interfaces/test_mcp_server.py`, `tests/unit/fixes/test_search_results_reach_the_model.py` (`search_images`, `vane_search`). No test imports `SearchHistoryTool` or `WeatherTool`.
**Does not hit:** the shell guards (none of these is a guarded tool); browser tools.

## Surfaces
Agent tool calls; MCP `web_search`.

## See
`weebot/tools/web_search.py`, `weebot/tools/agent_reach.py`, `weebot/core/trust_boundary.py`
