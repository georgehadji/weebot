---
type: object
name: Browser and desktop tools
code: AdvancedBrowserTool, WebScraperTool, BrowserInspectorTool, BrowserTool, CamofoxBrowserTool, ComputerUseTool, ScreenCaptureBaseTool, DesktopA11yTool
cluster: tools
universe: live
status: verified
verified: 2026-10-30
commit: 8e6d1cca
---

# Browser and desktop tools

These are the tools an agent uses to open web pages or drive the desktop. Each one uses a different backend. Only `advanced_browser` and `browser_inspector` go through the shared `PlaywrightAdapter` (card `infrastructure/Browser.md`).

## Why this shape
The tools grew as separate backends, not as one browser with several front ends:
- **Playwright**: navigation, design inspection and scraping.
- **browser-use**: an LLM-driven agent.
- **Camoufox**: pages that block bots.
- **pyautogui / mss / pywinauto**: the desktop.

The registry shares one adapter between the two Playwright tools so that `browser_inspector` reads the page that `advanced_browser` opened (`weebot/tools/browser_inspector.py:8-9, 183-186`, `weebot/application/services/tool_registry.py:463-464, 505-513`).

## Shape
Roles come from `DEFAULT_ROLE_MAPPINGS` (`weebot/application/services/tool_registry.py:26-185`; `weebot/tools/tool_registry.py` only re-exports it).

| Tool name | Defined | Backend | Roles |
|---|---|---|---|
| `advanced_browser` | `weebot/tools/advanced_browser.py:52` | shared `PlaywrightAdapter`, raw `.page` calls (`weebot/tools/advanced_browser.py:130-141`) | researcher, admin, webhook |
| `web_scraper` | `weebot/tools/advanced_browser.py:419` | its own `async_playwright()` Chromium per call (`weebot/tools/advanced_browser.py:486-488`), `ContentExtractor` (`weebot/tools/advanced_browser.py:501-505`) | researcher, admin |
| `browser_inspector` | `weebot/tools/browser_inspector.py:180` | shared `PlaywrightAdapter` (`weebot/tools/browser_inspector.py:194, 252`), `SomRenderer` (`weebot/tools/browser_inspector.py:376, 406`) | researcher, admin, webhook, designer |
| `browser_navigator` | `weebot/tools/browser_tool.py:38` | `browser_use.Browser(headless=False)` and `browser_use.Agent` (`weebot/tools/browser_tool.py:25, 35, 96, 170-172`) | none (and never built, see below) |
| `camofox_browser` | `weebot/tools/camofox_browser.py:198` | its own Node camofox server on 127.0.0.1, over HTTP (`weebot/tools/camofox_browser.py:125-161, 312-334`) | researcher, admin, webhook |
| `computer_use` | `weebot/tools/computer_use.py:27` | pyautogui, pygetwindow (`weebot/tools/computer_use.py:12-13, 213`) | automation, admin |
| `screen_capture` | `weebot/tools/screen_tool.py:106` | mss and Pillow, wrapped by `ScreenCaptureTool` (`weebot/tools/screen_tool.py:27, 141`) | researcher, automation, admin, webhook |
| `desktop_a11y` | `weebot/tools/desktop_a11y.py:46` | pywinauto, with a ctypes UIA fallback (`weebot/tools/desktop_a11y.py:100-112, 177`) | admin |

**Wiring.**
- `advanced_browser` and `browser_inspector` get `browser=<one PlaywrightAdapter>` from the `browser_factory` the container wires (`weebot/application/services/tool_registry.py:505-513`, `weebot/application/di/_factories.py:581`); with no factory wired both are skipped. Each `close()` closes that adapter, idempotently (`weebot/tools/advanced_browser.py:132-135`, `weebot/tools/browser_inspector.py:196-199`); `ToolCollection.teardown` calls it (`weebot/application/models/tool_collection.py:147-154`; `tests/unit/fixes/test_teardown_closes_browser.py`).
- `browser_navigator` is in the LLM-port set (`weebot/application/services/tool_registry.py:458`) but in no role.
- `BrowserTool` (`weebot/tools/browser_tool.py:38`) does not subclass `BaseTool`, and discovery keeps only `BaseTool` subclasses (`weebot/application/services/tool_registry.py:352-356`). So `browser_navigator` never enters the class map; a name list that asks for it logs "not found in class map" and skips it (`:534`). It was live only through the legacy `RecursiveWeebotAgent`, retired in plan 3.5, so no flow builds it today.
- `computer_use` with `require_window` refuses to type when it cannot confirm the active window (`weebot/tools/computer_use.py:211-236`).

**Timeouts.**
- `ToolExecutor` uses the tool's `default_timeout_seconds`. If the call passes `timeout`, it uses `min(timeout + 5, 305)` seconds instead (`weebot/application/agents/executor/_tool_executor.py:424-428`).
- `advanced_browser` (120 s, `weebot/tools/advanced_browser.py:62`) documents `timeout` in milliseconds, default 30000 (`weebot/tools/advanced_browser.py:102-105, 167`). Any explicit `timeout` therefore becomes the 305 s cap.
- Other tools:
  - `browser_inspector` navigates with 30000 ms (`weebot/tools/browser_inspector.py:292`) under the 60 s default (`weebot/domain/models/base_tool.py:44`).
  - `camofox_browser`: 90 s per request, 120 s per tool call, 30 s startup (`weebot/tools/camofox_browser.py:54-55, 232`).
  - `browser_navigator`: 60 s (`weebot/tools/browser_tool.py:47`).
  - `computer_use`: 30 s (`weebot/tools/computer_use.py:38`), with its own typing timeout (`weebot/tools/computer_use.py:268-282`).
  - `screen_capture`: 30 s (`weebot/tools/screen_tool.py:114`).

**Concurrency.**
- `advanced_browser`, `browser_navigator` and `computer_use` set `max_concurrent = 1` (`weebot/tools/advanced_browser.py:61, 127`, `weebot/tools/browser_tool.py:46`, `weebot/tools/computer_use.py:37`).
- The semaphore is per tool name (`weebot/application/models/tool_collection.py:234-253`). `advanced_browser` and `browser_inspector` can therefore drive the same page at the same time.

## Guards
- **Fence and taint.** Each tool declares `output_trust`. `advanced_browser` (`weebot/tools/advanced_browser.py:59`), `web_scraper` (`:422`), `browser_inspector` (`weebot/tools/browser_inspector.py:189`), `browser_navigator` (`weebot/tools/browser_tool.py:44`), `camofox_browser` (`weebot/tools/camofox_browser.py:201`) and `desktop_a11y` (`weebot/tools/desktop_a11y.py:59`) are `EXTERNAL`; `computer_use` (`weebot/tools/computer_use.py:35`) and `screen_capture` (`weebot/tools/screen_tool.py:111`) are `LOCAL`. The decisions are `trust_of`, `must_fence` and `must_taint` (`weebot/core/trust_boundary.py:58-90`). Output of a non-`LOCAL` tool is fenced, errors included (`weebot/application/agents/executor/_base.py:252-274`). A successful `EXTERNAL` call taints the session for egress, but an error does not and neither does an `advanced_browser` read of a `file://` or loopback page (`weebot/application/agents/executor/_tool_executor.py:584-618`). The reviewed set is pinned in `tests/unit/core/test_trust_boundary_registry.py`.
- **Egress.** `EgressGuard.classify` runs before each call (`weebot/application/agents/executor/_tool_executor.py:463-466`).
  - Browser tools: `advanced_browser`, `browser_navigator`, `browser_tool` and `computer_use` count as egress only when `action` is one of `submit`, `click_submit`, `navigate_post`, `fill_and_submit`, `form_submit`, `post`, `send_form`, or when the args carry `data`/`body`/`post_data` (`weebot/core/egress_guard.py:175-188, 532-539`). None of these is an action in the `advanced_browser` enum (`weebot/tools/advanced_browser.py:73-94`). `browser_navigator` takes only `task` (`weebot/tools/browser_tool.py:56-64`), and `computer_use` takes none of them (`weebot/tools/computer_use.py:51-67`). Separately, a URL that holds a secret is egress for `advanced_browser`, `browser_inspector` and `web_scraper`, and so are `fill`, `type`, `select` and `evaluate` on `advanced_browser` once the session is tainted (`weebot/core/egress_guard.py:193-196, 444-451`).
  - `camofox_browser` is egress on `type` only, with an unknown recipient (`weebot/core/egress_guard.py:526-530`). It also refuses private and loopback URLs itself, including names that resolve private after a redirect (`weebot/tools/camofox_browser.py:167-195, 304-310`).
  - Without a guard, the browser family is refused under enforcement (`weebot/application/agents/executor/_tool_executor.py:333-348, 445-458`).

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`).
- **Backend** `infrastructure/Browser.md`.
- `BrowserSessionManager` stores `advanced_browser` sessions (`weebot/tools/advanced_browser.py:12, 180, 331, 386`).
- **Mentioned by** the browser audit in `weebot/application/flows/states/executing.py:56-109` and the per-step model router regex (`weebot/application/services/task_model_router.py:82-83`).
- **Looks like but is not:** `moli_fetch`, `agent_reach`, `spacescraper` (other fetchers in the same role lists); the MCP server's own tool list.

## If you change this
**Hits:**
- Which roles can browse or drive the desktop.
- Egress and taint behaviour keyed on these names.
- Tests:
  - Tool tests: `tests/unit/tools/test_advanced_browser.py`, `tests/unit/tools/test_browser_inspector.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_computer_use.py`, `tests/unit/tools/test_computer_use_scaling.py`, `tests/unit/tools/test_screen_tool.py`, `tests/unit/tools/test_desktop_a11y.py`, `tests/unit/tools/test_tool_wrappers.py`.
  - `tests/unit/test_cove_regressions.py:204-322` (`_close_browser` globals), `tests/unit/fixes/test_teardown_closes_browser.py`.
  - `tests/unit/test_architecture_fitness.py:1539-1554` (`BrowserTool` attributes).
  - Name-keyed guard tests: `tests/unit/test_egress_guard.py:237-240`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/security/test_security_gates_fail_closed.py:64`, `tests/unit/fixes/test_outbound_tools_ask.py:75`.
  - `tests/unit/test_executor_vision_injection.py`, `tests/unit/test_vision_reflection.py`.

**Does not hit:** the Playwright launch and teardown code (`infrastructure/Browser.md`); `RoleBasedToolRegistry` discovery rules.

## Surfaces
- Agents in the roles above.
- The legacy agent (`RecursiveWeebotAgent`, retired in plan 3.5) was the only place `browser_navigator` was built; nothing builds it now.
- A visible desktop window for `browser_navigator` (`HEADLESS = False`, `browser_tool.py:35`) and for `computer_use`.

## See
`weebot/tools/advanced_browser.py`, `weebot/tools/browser_inspector.py`
