---
type: object
name: Browser and desktop tools
code: AdvancedBrowserTool, WebScraperTool, BrowserInspectorTool, BrowserTool, CamofoxBrowserTool, ComputerUseTool, ScreenCaptureBaseTool, DesktopA11yTool
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# Browser and desktop tools

These are the tools an agent uses to open web pages or drive the desktop. Each one uses a different backend. Only `advanced_browser` and `browser_inspector` go through the shared `PlaywrightAdapter` (card `infrastructure/Browser.md`).

## Why this shape
The tools grew as separate backends, not as one browser with several front ends:
- **Playwright**: navigation, design inspection and scraping.
- **browser-use**: an LLM-driven agent.
- **Camoufox**: pages that block bots.
- **pyautogui / mss / pywinauto**: the desktop.

The registry shares one adapter between the two Playwright tools so that `browser_inspector` reads the page that `advanced_browser` opened (`weebot/tools/browser_inspector.py:8-9, 182-185`, `weebot/tools/tool_registry.py:454-486`).

## Shape
Roles come from `DEFAULT_ROLE_MAPPINGS` (`weebot/tools/tool_registry.py:26-178`).

| Tool name | Defined | Backend | Roles |
|---|---|---|---|
| `advanced_browser` | `weebot/tools/advanced_browser.py:55` | shared `PlaywrightAdapter`, raw `.page` calls (`:124-133`) | researcher, admin, webhook |
| `web_scraper` | `weebot/tools/advanced_browser.py:409` | its own `async_playwright()` Chromium per call (`:471-473`), `ContentExtractor` (`:486-490`) | none |
| `browser_inspector` | `weebot/tools/browser_inspector.py:188` | shared `PlaywrightAdapter` (`:191, 244`), `SomRenderer` (`:368`) | researcher, admin, webhook, designer |
| `browser_navigator` | `weebot/tools/browser_tool.py:46` | `browser_use.Browser(headless=False)` and `browser_use.Agent` (`:24, 34, 93, 167-171`) | admin, webhook (never built, see below) |
| `camofox_browser` | `weebot/tools/camofox_browser.py:200` | its own Node camofox server on 127.0.0.1, over HTTP (`:124-160, 308-330`) | researcher, admin, webhook |
| `computer_use` | `weebot/tools/computer_use.py:33` | pyautogui, pygetwindow (`:11, 207`) | automation, admin, webhook |
| `screen_capture` | `weebot/tools/screen_tool.py:101` | mss and Pillow, wrapped by `ScreenCaptureTool` (`:25, 124-127`) | researcher, automation, admin, webhook |
| `desktop_a11y` | `weebot/tools/desktop_a11y.py:54` | pywinauto, with a ctypes UIA fallback (`:91-112, 170`) | none |

**Wiring.**
- `advanced_browser` and `browser_inspector` get `browser=<one PlaywrightAdapter>` (`tool_registry.py:479-486`).
- `browser_navigator` is in the LLM-port set (`:449`).
- `BrowserTool` (`browser_tool.py:37`) does not subclass `BaseTool`, and discovery keeps only `BaseTool` subclasses (`tool_registry.py:345-349`). So `browser_navigator` never enters the class map, and `admin` and `webhook` collections log "not found in class map" and skip it (`:506-507`). It is live only through `weebot/core/agent.py:53-56`.

**Timeouts.**
- `ToolExecutor` uses the tool's `default_timeout_seconds`. If the call passes `timeout`, it uses `min(timeout + 5, 305)` seconds instead (`application/agents/executor/_tool_executor.py:284-288`).
- `advanced_browser` (120 s, `advanced_browser.py:54`) documents `timeout` in milliseconds, default 30000 (`:94-97, 154`). Any explicit `timeout` therefore becomes the 305 s cap.
- Other tools:
  - `browser_inspector` navigates with 30000 ms (`browser_inspector.py:284`) under the 60 s default (`weebot/domain/models/base_tool.py:42`).
  - `camofox_browser`: 90 s per request, 120 s per tool call, 30 s startup (`camofox_browser.py:53-54, 229`).
  - `browser_navigator`: 60 s (`browser_tool.py:44`).
  - `computer_use`: 30 s (`computer_use.py:32`), with its own typing timeout (`:257-268`).
  - `screen_capture`: 30 s (`screen_tool.py:100`).

**Concurrency.**
- `advanced_browser`, `browser_navigator` and `computer_use` set `max_concurrent = 1` (`advanced_browser.py:53, 119`, `browser_tool.py:43`, `computer_use.py:31`).
- The semaphore is per tool name (`application/models/tool_collection.py:201-208`). `advanced_browser` and `browser_inspector` can therefore drive the same page at the same time.

## Guards
- **Fence and taint.** `advanced_browser`, `browser_navigator`, `browser_inspector`, `web_scraper` and `camofox_browser` are in `UNTRUSTED_OUTPUT_TOOLS` (`weebot/core/trust_boundary.py:49-61`). Their output is fenced (`application/agents/executor/_base.py:1006`). A successful call taints the session for egress (`_tool_executor.py:398-399`). `computer_use`, `screen_capture` and `desktop_a11y` are not in the list.
- **Egress.** `EgressGuard.classify` runs before each call (`_tool_executor.py:322-325`).
  - Browser tools: `advanced_browser`, `browser_navigator`, `browser_tool` and `computer_use` count as egress only when `action` is one of `submit`, `click_submit`, `navigate_post`, `fill_and_submit`, `form_submit`, `post`, `send_form`, or when the args carry `data`/`body`/`post_data` (`weebot/core/egress_guard.py:161-174, 388-398`). None of these is an action in the `advanced_browser` enum (`advanced_browser.py:65-86`). `browser_navigator` takes only `task` (`browser_tool.py:53-62`), and `computer_use` takes none of them (`computer_use.py:45-60`).
  - `camofox_browser` is egress on `type` only, with an unknown recipient (`egress_guard.py:385-386`). It also refuses private and loopback URLs itself (`camofox_browser.py:166-194, 301-306`).
  - Without a guard, the browser family is refused under enforcement (`_tool_executor.py:201-213, 311-319`).

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`).
- **Backend** `infrastructure/Browser.md`.
- `BrowserSessionManager` stores `advanced_browser` sessions (`advanced_browser.py:166-168, 312-349, 372-378`).
- **Mentioned by** the browser audit in `application/flows/states/executing.py:136-154`, the per-step model router regex (`application/services/task_model_router.py:95`), and `MultiSourceResearchEngine.browser_tool`, which is stored and never read (`application/services/multi_source_research.py:313-319`).
- **Looks like but is not:** `moli_fetch`, `agent_reach`, `spacescraper` (other fetchers in the same role lists); the MCP server's own tool list.

## If you change this
**Hits:**
- Which roles can browse or drive the desktop.
- Egress and taint behaviour keyed on these names.
- Tests:
  - Tool tests: `tests/unit/tools/test_advanced_browser.py`, `tests/unit/tools/test_browser_inspector.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_computer_use.py`, `tests/unit/tools/test_computer_use_scaling.py`, `tests/unit/tools/test_screen_tool.py`, `tests/unit/tools/test_desktop_a11y.py`, `tests/unit/tools/test_tool_wrappers.py`.
  - `tests/unit/test_cove_regressions.py:207-281` (`_close_browser` globals).
  - `tests/unit/test_architecture_fitness.py:1514-1521` (`BrowserTool` attributes).
  - Name-keyed guard tests: `tests/unit/test_egress_guard.py:237-240`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/security/test_security_gates_fail_closed.py:64`, `tests/unit/fixes/test_outbound_tools_ask.py:76`.
  - `tests/unit/test_executor_vision_injection.py`, `tests/unit/test_vision_reflection.py`.

**Does not hit:** the Playwright launch and teardown code (`infrastructure/Browser.md`); `RoleBasedToolRegistry` discovery rules.

## Surfaces
- Agents in the roles above.
- The legacy agent in `weebot/core/agent.py:53-108`, the only place `browser_navigator` is built.
- A visible desktop window for `browser_navigator` (`HEADLESS = False`, `browser_tool.py:34`) and for `computer_use`.

## See
`weebot/tools/advanced_browser.py`, `weebot/tools/browser_inspector.py`
