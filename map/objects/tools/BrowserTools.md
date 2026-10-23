---
type: object
name: Browser and desktop tools
code: AdvancedBrowserTool, WebScraperTool, BrowserInspectorTool, BrowserTool, CamofoxBrowserTool, ComputerUseTool, ScreenCaptureBaseTool, DesktopA11yTool
cluster: tools
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# Browser and desktop tools

These are the tools an agent uses to open web pages or drive the desktop. Each one uses a different backend. Only `advanced_browser` and `browser_inspector` go through the shared `PlaywrightAdapter` (card `infrastructure/Browser.md`).

## Why this shape
The tools grew as separate backends, not as one browser with several front ends:
- **Playwright**: navigation, design inspection and scraping.
- **browser-use**: an LLM-driven agent.
- **Camoufox**: pages that block bots.
- **pyautogui / mss / pywinauto**: the desktop.

The registry shares one adapter between the two Playwright tools so that `browser_inspector` reads the page that `advanced_browser` opened (`weebot/tools/browser_inspector.py:8-9, 182-185`, `weebot/tools/tool_registry.py:462-463, 487-493`).

## Shape
Roles come from `DEFAULT_ROLE_MAPPINGS` (`weebot/tools/tool_registry.py:26-185`).

| Tool name | Defined | Backend | Roles |
|---|---|---|---|
| `advanced_browser` | `weebot/tools/advanced_browser.py:55` | shared `PlaywrightAdapter`, raw `.page` calls (`weebot/tools/advanced_browser.py:129-138`) | researcher, admin, webhook |
| `web_scraper` | `weebot/tools/advanced_browser.py:414` | its own `async_playwright()` Chromium per call (`weebot/tools/advanced_browser.py:476-478`), `ContentExtractor` (`weebot/tools/advanced_browser.py:491-495`) | researcher, admin |
| `browser_inspector` | `weebot/tools/browser_inspector.py:188` | shared `PlaywrightAdapter` (`weebot/tools/browser_inspector.py:191, 249`), `SomRenderer` (`weebot/tools/browser_inspector.py:373`) | researcher, admin, webhook, designer |
| `browser_navigator` | `weebot/tools/browser_tool.py:46` | `browser_use.Browser(headless=False)` and `browser_use.Agent` (`weebot/tools/browser_tool.py:24, 34, 93, 167-171`) | none (and never built, see below) |
| `camofox_browser` | `weebot/tools/camofox_browser.py:200` | its own Node camofox server on 127.0.0.1, over HTTP (`weebot/tools/camofox_browser.py:124-160, 309-331`) | researcher, admin, webhook |
| `computer_use` | `weebot/tools/computer_use.py:36` | pyautogui, pygetwindow (`weebot/tools/computer_use.py:12, 210`) | automation, admin |
| `screen_capture` | `weebot/tools/screen_tool.py:101` | mss and Pillow, wrapped by `ScreenCaptureTool` (`weebot/tools/screen_tool.py:25, 124-127`) | researcher, automation, admin, webhook |
| `desktop_a11y` | `weebot/tools/desktop_a11y.py:54` | pywinauto, with a ctypes UIA fallback (`weebot/tools/desktop_a11y.py:91-112, 170`) | admin |

**Wiring.**
- `advanced_browser` and `browser_inspector` get `browser=<one PlaywrightAdapter>` (`weebot/tools/tool_registry.py:487-493`). Each `close()` closes that adapter, idempotently (`weebot/tools/advanced_browser.py:124-127`, `weebot/tools/browser_inspector.py:193-197`); `ToolCollection.teardown` calls it (see the BaseTool card).
- `browser_navigator` is in the LLM-port set (`weebot/tools/tool_registry.py:456`) but in no role.
- `BrowserTool` (`weebot/tools/browser_tool.py:37`) does not subclass `BaseTool`, and discovery keeps only `BaseTool` subclasses (`weebot/tools/tool_registry.py:352-356`). So `browser_navigator` never enters the class map; a name list that asks for it logs "not found in class map" and skips it (`weebot/tools/tool_registry.py:513-514`). It is live only through `weebot/core/agent.py:53-56`.
- `computer_use` with `require_window` refuses to type when it cannot confirm the active window (`weebot/tools/computer_use.py:208-234`).

**Timeouts.**
- `ToolExecutor` uses the tool's `default_timeout_seconds`. If the call passes `timeout`, it uses `min(timeout + 5, 305)` seconds instead (`weebot/application/agents/executor/_tool_executor.py:311-315`).
- `advanced_browser` (120 s, `weebot/tools/advanced_browser.py:54`) documents `timeout` in milliseconds, default 30000 (`weebot/tools/advanced_browser.py:94-97, 159`). Any explicit `timeout` therefore becomes the 305 s cap.
- Other tools:
  - `browser_inspector` navigates with 30000 ms (`weebot/tools/browser_inspector.py:289`) under the 60 s default (`weebot/domain/models/base_tool.py:42`).
  - `camofox_browser`: 90 s per request, 120 s per tool call, 30 s startup (`weebot/tools/camofox_browser.py:53-54, 229`).
  - `browser_navigator`: 60 s (`weebot/tools/browser_tool.py:44`).
  - `computer_use`: 30 s (`weebot/tools/computer_use.py:35`), with its own typing timeout (`weebot/tools/computer_use.py:269-280`).
  - `screen_capture`: 30 s (`weebot/tools/screen_tool.py:100`).

**Concurrency.**
- `advanced_browser`, `browser_navigator` and `computer_use` set `max_concurrent = 1` (`weebot/tools/advanced_browser.py:53, 119`, `weebot/tools/browser_tool.py:43`, `weebot/tools/computer_use.py:34`).
- The semaphore is per tool name (`weebot/application/models/tool_collection.py:222-229`). `advanced_browser` and `browser_inspector` can therefore drive the same page at the same time.

## Guards
- **Fence and taint.** `advanced_browser`, `browser_navigator`, `browser_inspector`, `web_scraper` and `camofox_browser` are in `UNTRUSTED_OUTPUT_TOOLS` (`weebot/core/trust_boundary.py:49-61`). Their output is fenced (`weebot/application/agents/executor/_base.py:1042`). A successful call taints the session for egress (`weebot/application/agents/executor/_tool_executor.py:440-445`). `computer_use`, `screen_capture` and `desktop_a11y` are not in the list.
- **Egress.** `EgressGuard.classify` runs before each call (`weebot/application/agents/executor/_tool_executor.py:350-352`).
  - Browser tools: `advanced_browser`, `browser_navigator`, `browser_tool` and `computer_use` count as egress only when `action` is one of `submit`, `click_submit`, `navigate_post`, `fill_and_submit`, `form_submit`, `post`, `send_form`, or when the args carry `data`/`body`/`post_data` (`weebot/core/egress_guard.py:161-174, 412-422`). None of these is an action in the `advanced_browser` enum (`weebot/tools/advanced_browser.py:65-86`). `browser_navigator` takes only `task` (`weebot/tools/browser_tool.py:53-62`), and `computer_use` takes none of them (`weebot/tools/computer_use.py:50-63`).
  - `camofox_browser` is egress on `type` only, with an unknown recipient (`weebot/core/egress_guard.py:407-410`). It also refuses private and loopback URLs itself, including names that resolve private after a redirect (`weebot/tools/camofox_browser.py:166-194, 301-307`).
  - Without a guard, the browser family is refused under enforcement (`weebot/application/agents/executor/_tool_executor.py:228-246, 332-346`).

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`).
- **Backend** `infrastructure/Browser.md`.
- `BrowserSessionManager` stores `advanced_browser` sessions (`weebot/tools/advanced_browser.py:171-173, 317-354, 377-383`).
- **Mentioned by** the browser audit in `weebot/application/flows/states/executing.py:136-194`, the per-step model router regex (`weebot/application/services/task_model_router.py:95`), and `MultiSourceResearchEngine.browser_tool`, which is stored and never read (`weebot/application/services/multi_source_research.py:313-319`).
- **Looks like but is not:** `moli_fetch`, `agent_reach`, `spacescraper` (other fetchers in the same role lists); the MCP server's own tool list.

## If you change this
**Hits:**
- Which roles can browse or drive the desktop.
- Egress and taint behaviour keyed on these names.
- Tests:
  - Tool tests: `tests/unit/tools/test_advanced_browser.py`, `tests/unit/tools/test_browser_inspector.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_computer_use.py`, `tests/unit/tools/test_computer_use_scaling.py`, `tests/unit/tools/test_screen_tool.py`, `tests/unit/tools/test_desktop_a11y.py`, `tests/unit/tools/test_tool_wrappers.py`.
  - `tests/unit/test_cove_regressions.py:207-281` (`_close_browser` globals).
  - `tests/unit/test_architecture_fitness.py:1514-1521` (`BrowserTool` attributes).
  - Name-keyed guard tests: `tests/unit/test_egress_guard.py:237-240`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/security/test_security_gates_fail_closed.py:64`, `tests/unit/fixes/test_outbound_tools_ask.py:75`.
  - `tests/unit/test_executor_vision_injection.py`, `tests/unit/test_vision_reflection.py`.

**Does not hit:** the Playwright launch and teardown code (`infrastructure/Browser.md`); `RoleBasedToolRegistry` discovery rules.

## Surfaces
- Agents in the roles above.
- The legacy agent in `weebot/core/agent.py:53-108`, the only place `browser_navigator` is built.
- A visible desktop window for `browser_navigator` (`HEADLESS = False`, `browser_tool.py:34`) and for `computer_use`.

## See
`weebot/tools/advanced_browser.py`, `weebot/tools/browser_inspector.py`
