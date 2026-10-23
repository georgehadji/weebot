---
type: object
name: Browser adapter and session pool
code: PlaywrightAdapter, BrowserSessionPool, BrowserSessionManager, ContentExtractor, SomRenderer
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-23
commit: c2f39937
---

# Browser adapter and session pool

The Playwright side of web browsing: `PlaywrightAdapter` owns one browser, one context and one page; `BrowserSessionPool` is a pool of warm sessions; `BrowserSessionManager` saves and restores cookies and storage as JSON; `ContentExtractor` turns HTML into markdown; `SomRenderer` draws numbered boxes on a screenshot. Only the adapter, the session manager and the two helpers are on a live path. The pool is built by DI but nothing acquires from it.

## Why this shape
`PlaywrightAdapter` implements `BrowserPort` (`weebot/application/ports/browser_port.py:151`) so the application layer can name a browser without importing Playwright. In practice the tools skip the port: they read the raw page through the `page` property (`weebot/infrastructure/browser/playwright_adapter.py:55-58`) and call Playwright on it directly (see `tools/BrowserTools.md`). The port methods (`navigate`, `click`, `fill`, ... `reload`, `:194-606`) have no production caller. Only the docstring examples call them (`browser_port.py:161-163`, `playwright_adapter.py:38-41`).

## Shape
- **`PlaywrightAdapter`** (`playwright_adapter.py:25`). `__init__` only sets fields to `None` and makes an `asyncio.Lock` (`:46-53`); no process starts until `start()`.
  - `start(config)` starts the Playwright driver, then `_launch()` (`:76-99`). If launch fails it calls `close()` best-effort and re-raises (`:87-99`). `start()` does not take the lock and does not check for a running browser. A second `start()` overwrites `_playwright`, `_browser` and `_context` with no close (`:86-88`).
  - `_launch()` picks Chromium, Firefox or WebKit (`:104-110`) and applies `headless` and `proxy_server` (`:113-118`). It sets viewport, user agent, locale, timezone, geolocation and permissions on the context (`:121-146`). `record_video` writes to `./videos` (`:148-149`). `record_har` writes to `./har/<uuid>.har` (`:158-161`). `BrowserConfig.downloads_path` (`browser_port.py:141`) is never read.
  - `close()` closes context, browser and driver in that order, under the lock. Each step runs even if an earlier one raised (`:166-192`).
  - Timeouts: none of its own. `navigate` defaults to `wait_until="networkidle"` (`:194`). `wait_for_selector` defaults to 30 s (`:497`).
  - The lock guards only the read of `_page` (for example `:204-213`). The Playwright call after it runs unlocked.
- **`BrowserSessionPool`** (`session_pool.py:57`).
  - Defaults: `min_sessions=1`, `max_sessions=5`, `session_ttl=300`, `idle_timeout=60` (`:82-90`).
  - `start()` pre-warms `min_sessions` and starts a 30 s maintenance loop (`:125-154`, `:287-330`).
  - `acquire()` waits 1 s for a free session, else launches a new one (`:177-196`). It ignores its own `timeout` argument (`:157`).
  - On release it clears cookies only (`:212-215`), then puts the session back (`:218-219`).
  - `close()` stops the loop and closes free and in-use sessions, then the driver (`:332-372`).
  - `reset()` re-runs `__init__()` with default arguments (`:394-401`).
  - DI: fixed 2026-10-23 (F72): the container no longer registers `browser_pool`. Its registration and `_create_browser_pool` factory were removed because no code ever called `start()` or `acquire()` on it. An unstarted `acquire()` raises (`session_pool.py:168-169`).
  - The deprecated module-global path `get_browser_pool` / `close_global_pool` / `reset_global_pool` remains (`:405-452`).
- **`BrowserSessionManager`** (`session_manager.py:15`).
  - Files go in `<repo>/data/browser_sessions/<name>.json`, and the constructor creates the folder (`:32-35`). Names are reduced to `[A-Za-z0-9_-]` (`:40-45`).
  - `save_session` writes `context.storage_state()` (cookies and origins) as plain JSON (`:57-71`).
  - `load_session` adds the cookies. For each saved origin that has storage, it opens the origin with `page.goto(origin, timeout=10000)` and replays `localStorage`/`sessionStorage` (`:97-151`).
  - Every method returns `False` or skips an item on error rather than raising (`:73-75`, `:156-158`, `:173-174`).
- **`ContentExtractor`** (`content_extractor.py:13`).
  - It drops noise tags (`:17-32`), picks `main`/`article`/... or else `body` (`:79-101`), and converts to markdown (`:103-205`).
  - It truncates at `max_tokens * 4` characters (`:44`, `:282-295`). Its only caller is `web_scraper` in `extract_type="markdown"` mode (`weebot/tools/advanced_browser.py:486-490`).
- **`SomRenderer`** (`som_renderer.py:32`). `render()` keeps elements larger than 5x5 px, at most 50 (`:69-77`). It draws the overlay with Pillow when available, else returns the raw screenshot (`:90-98`). Its only caller is `browser_inspector` action `som` (`weebot/tools/browser_inspector.py:368-405`).

## Lifecycle (who opens and closes the browser)
- **Open.** A `PlaywrightAdapter` is constructed with no browser in three places.
  - Per tool collection, by `create_tool_collection_from_names`, shared by `advanced_browser` and `browser_inspector` in that one collection (`weebot/tools/tool_registry.py:454-486`). The variable is local to the call (`:456`), so every collection gets its own adapter.
  - By the tool itself when nothing was injected (`advanced_browser.py:361-364`, `browser_inspector.py:276-280`).
  - In the health check, which only calls `is_available()` (`weebot/infrastructure/observability/health_checks.py:327-330`).
  - The browser process starts on the first `advanced_browser` `launch`/`goto` or `browser_inspector` `navigate` (`advanced_browser.py:163-164, 178-181`, `browser_inspector.py:282-283`).
- **Close.** Only `advanced_browser(action="close")` closes it (`advanced_browser.py:171-173, 394-395`). Nothing else does:
  - `ToolCollection.teardown()` shuts down only `apify_service` (`weebot/application/models/tool_collection.py:112-127`). Flows call it at `application/flows/plan_act_flow.py:530` and `application/flows/agent_session_manager.py:45`.
  - It never calls `BaseTool.close()` (`weebot/domain/models/base_tool.py:60-70`). Neither browser tool overrides `close()`.
  - The `advanced_browser` atexit hook stops a module global that no code assigns (`advanced_browser.py:18-36`).
- **Pool.** The web app's shutdown calls `container.get("browser_pool").close()` inside `except Exception: pass` (`weebot/interfaces/web/main.py:364-370`).

## Guards on navigation
None in this layer. `PlaywrightAdapter.navigate` (`playwright_adapter.py:227`) and `BrowserSessionManager.load_session` (`session_manager.py:116`) call `page.goto` with no host check. The tool-level gate is `EgressGuard`, run by `ToolExecutor` before each call (`application/agents/executor/_tool_executor.py:322-325`). It treats a browser call as egress only for form-submit action names or POST-data arguments (`weebot/core/egress_guard.py:161-174, 388-398`); see `tools/BrowserTools.md`.

## Connected to
- **Implements** `BrowserPort` (`application/ports/browser_port.py:151`); config `BrowserConfig` (`:113-144`).
- **Used by** `AdvancedBrowserTool` and `BrowserInspectorTool` through `.page`, wired by `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`). `BrowserSessionManager` is used by `advanced_browser` (`advanced_browser.py:9, 167, 318, 373`).
- **Health:**
  - The `/health` component reports `browser_pool` healthy from an import flag only (`weebot/interfaces/web/routers/health.py:186-198`).
  - The metrics endpoint reads the deprecated `_global_pool`, never the DI pool (`health.py:453-463`).
- **Looks like but is not:** `browser_navigator` (`weebot/tools/browser_tool.py`), which drives its own `browser_use.Browser` and never touches this layer (`browser_tool.py:88-93`); `camofox_browser`, a Node server it starts itself (`weebot/tools/camofox_browser.py:124-160`).

## If you change this
**Hits:**
- Every `advanced_browser` and `browser_inspector` call, through `.page`.
- The session files under `data/browser_sessions/`.
- `web_scraper` markdown output.
- `browser_inspector` `som`.
- Tests: `tests/unit/infrastructure/test_child_process_and_browser_teardown.py` (adapter start/close/HAR, `:222-290`), `tests/unit/infrastructure/test_som_renderer.py`, `tests/unit/tools/test_browser_inspector.py`, `tests/unit/test_architecture_fitness.py:1355-1369` (where `_global_pool` may live), `tests/unit/conftest.py:92` (imports `reset_global_pool`, errors swallowed).

**Does not hit:**
- `browser_navigator` (browser-use).
- `camofox_browser`.
- `computer_use` / `screen_capture` / `desktop_a11y`, which drive the desktop, not Playwright.
- `EgressGuard` rules.

## Surfaces
- Agents, through the browser tools.
- The web app's shutdown hook and health routes.
- Humans: the JSON session files and the `./videos` and `./har` folders, all relative to the process's working directory except the session files.

## See
`weebot/infrastructure/browser/`
