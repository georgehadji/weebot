---
type: object
name: Browser adapter and session pool
code: PlaywrightAdapter, BrowserSessionPool, BrowserSessionManager, ContentExtractor, SomRenderer
cluster: infrastructure
universe: live
status: stale
verified: 2026-10-24
commit: eeb0e80e
---

# Browser adapter and session pool

The Playwright side of web browsing: `PlaywrightAdapter` owns one browser, one context and one page; `BrowserSessionPool` is a pool of warm sessions; `BrowserSessionManager` saves and restores cookies and storage as JSON; `ContentExtractor` turns HTML into markdown; `SomRenderer` draws numbered boxes on a screenshot. Only the adapter, the session manager and the two helpers are on a live path. Nothing builds or acquires from the pool.

## Why this shape
`PlaywrightAdapter` implements `BrowserPort` (`weebot/application/ports/browser_port.py:151`) so the application layer can name a browser without importing Playwright. In practice the tools skip the port: they read the raw page through the `page` property (`weebot/infrastructure/browser/playwright_adapter.py:57-60`) and call Playwright on it directly (see `tools/BrowserTools.md`). The port methods (`navigate`, `click`, `fill`, ... `reload`, `:204-616`) have no production caller. Only the docstring examples call them (`browser_port.py:161-163`, `playwright_adapter.py:38-41`).

## Shape
- **`PlaywrightAdapter`** (`playwright_adapter.py:25`). `__init__` only sets fields to `None` and makes two `asyncio.Lock`s (`:46-55`); no process starts until `start()`.
  - `start(config)` takes `_start_lock` and returns if a browser is already up, so two tools sharing the adapter launch one browser (F73, `:78-89`). `_start()` starts the Playwright driver, then `_launch()`. If launch fails it calls `close()` best-effort and re-raises (`:91-109`).
  - `_launch()` picks Chromium, Firefox or WebKit (`:114-120`) and applies `headless` and `proxy_server` (`:123-128`). It sets viewport, user agent, locale, timezone, geolocation and permissions on the context (`:131-156`). `record_video` writes to `./videos` (`:158-159`). `record_har` writes to `./har/<uuid>.har` (`:168-171`). `BrowserConfig.downloads_path` (`browser_port.py:141`) is never read.
  - `close()` closes context, browser and driver in that order, under the lock. Each step runs even if an earlier one raised (`:176-202`).
  - Timeouts: none of its own. `navigate` defaults to `wait_until="networkidle"` (`:204`). `wait_for_selector` defaults to 30 s (`:506-507`).
  - The lock guards only the read of `_page` (for example `:214-215`). The Playwright call after it runs unlocked.
- **`BrowserSessionPool`** (`session_pool.py:57`).
  - Defaults: `min_sessions=1`, `max_sessions=5`, `session_ttl=300`, `idle_timeout=60` (`:82-90`).
  - `start()` pre-warms `min_sessions` and starts a 30 s maintenance loop (`:125-154`, `:287-330`).
  - `acquire()` waits 1 s for a free session, else launches a new one (`:177-196`). It ignores its own `timeout` argument (`:157`).
  - On release it clears cookies only (`:211-215`), then puts the session back (`:217-219`).
  - `close()` stops the loop and closes free and in-use sessions, then the driver (`:332-372`).
  - `reset()` re-runs `__init__()` with default arguments, then `start()` (`:394-401`).
  - DI: fixed 2026-10-23 (F72): the container no longer registers `browser_pool`; no code ever called `start()` or `acquire()` on it. An unstarted `acquire()` raises (`session_pool.py:168-169`).
  - The deprecated module-global path `get_browser_pool` / `close_global_pool` / `reset_global_pool` remains (`:404-452`).
- **`BrowserSessionManager`** (`session_manager.py:15`).
  - Files go in `<repo>/data/browser_sessions/<name>.json`, and the constructor creates the folder (`:32-35`). Names are reduced to `[A-Za-z0-9_-]` (`:37-45`).
  - `save_session` writes `context.storage_state()` (cookies and origins) as plain JSON; the file write and read run in `asyncio.to_thread` (`:47-71`, `:93`).
  - `load_session` adds the cookies. For each saved origin that has storage, it opens the origin with `page.goto(origin, timeout=10000)` and replays `localStorage`/`sessionStorage` (`:97-151`).
  - Every method returns `False` or skips an item on error rather than raising (`:73-75`, `:156-158`, `:173-174`).
- **`ContentExtractor`** (`content_extractor.py:13`).
  - It drops noise tags (`:17-34`), picks `main`/`article`/... or else `body` (`:79-101`), and converts to markdown (`:103-205`).
  - It truncates at `max_tokens * 4` characters (`:44`, `:282-295`). Its only caller is `web_scraper` in `extract_type="markdown"` mode (`weebot/tools/advanced_browser.py:501-505`).
- **`SomRenderer`** (`som_renderer.py:33`). `render()` keeps elements larger than 5x5 px, at most 50 (`:70-78`). It draws the overlay with Pillow when available, else returns the raw screenshot (`:91-105`). Its only caller is `browser_inspector` action `som` (`weebot/tools/browser_inspector.py:371-406`).

## Lifecycle (who opens and closes the browser)
- **Open.** A `PlaywrightAdapter` is constructed with no browser in three places.
  - Per tool collection: `create_tool_collection_from_names` builds one through the `browser_factory` the container wires (`weebot/application/di/_factories.py:514, 503-509`) and shares it between `advanced_browser` and `browser_inspector` (`weebot/application/services/tool_registry.py:498-506`). The variable is local to the call (`:464`), so every collection gets its own adapter. With no factory wired, both tools are skipped (`:503-505`).
  - By the tool itself when nothing was injected (`advanced_browser.py:374-377`, `browser_inspector.py:285-288`).
  - In the health check, which only calls `is_available()` (`weebot/infrastructure/observability/health_checks.py:327-330`).
  - The browser process starts on the first `advanced_browser` `launch`/`goto` or `browser_inspector` `navigate` (`advanced_browser.py:176-177, 192-193, 372-383`, `browser_inspector.py:280-291`).
- **Close.** Two paths:
  - `advanced_browser(action="close")` closes the adapter (`advanced_browser.py:184-185, 407-408`).
  - `ToolCollection.teardown()` calls `BaseTool.close()` on every tool, and both browser tools override it to close the shared adapter (`weebot/application/models/tool_collection.py:147-154`; `advanced_browser.py:132-135`, `browser_inspector.py:196-199`). Flows call it at `application/flows/plan_act_flow.py:291` and `application/flows/agent_session_manager.py:43-45`. Pinned by `tests/unit/fixes/test_teardown_closes_browser.py`.
  - The `advanced_browser` atexit hook stops a module global that no code assigns (`advanced_browser.py:16-42`); its owner is documented at `:18-20`.
- **Pool.** Nothing closes it because nothing opens it.

## Guards on navigation
None in this layer. `PlaywrightAdapter.navigate` (`playwright_adapter.py:237`) and `BrowserSessionManager.load_session` (`session_manager.py:116`) call `page.goto` with no host check. The tool-level gate is `EgressGuard`, run by `ToolExecutor` before each call (`application/agents/executor/_tool_executor.py:397-418`). It treats a browser call as egress for form-submit action names or POST-data arguments (`weebot/core/egress_guard.py:161-174, 412-422`), for a URL that holds a secret, and for page writes once the session is tainted (`:176-182, 348-360`); see `tools/BrowserTools.md`.

## Connected to
- **Implements** `BrowserPort` (`application/ports/browser_port.py:151`); config `BrowserConfig` (`:113-144`).
- **Used by** `AdvancedBrowserTool` and `BrowserInspectorTool` through `.page`, wired by `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`). Both declare `OutputTrust.EXTERNAL` (`advanced_browser.py:59`, `browser_inspector.py:189`). `BrowserSessionManager` is used by `advanced_browser` (`advanced_browser.py:12, 180, 331, 386`).
- **Health:** the metrics endpoint `/api/health/metrics` reads the deprecated `_global_pool`, never a DI pool (`weebot/interfaces/web/routers/health.py:409-431`). `/api/health/status` reports `browser_pooling: True` as a constant (`:478`).
- **Looks like but is not:** `browser_navigator` (`weebot/tools/browser_tool.py`), which drives its own `browser_use.Browser` and never touches this layer (`browser_tool.py:91-96`); `camofox_browser`, a Node server it starts itself (`weebot/tools/camofox_browser.py:125-161`).

## If you change this
**Hits:**
- Every `advanced_browser` and `browser_inspector` call, through `.page`.
- The session files under `data/browser_sessions/`.
- `web_scraper` markdown output.
- `browser_inspector` `som`.
- Tests: `tests/unit/infrastructure/test_child_process_and_browser_teardown.py` (adapter start/close/HAR, `:222-286`), `tests/unit/fixes/test_teardown_closes_browser.py`, `tests/unit/infrastructure/test_som_renderer.py`, `tests/unit/tools/test_browser_inspector.py`, `tests/unit/test_architecture_fitness.py:1383-1397` (where `_global_pool` may live), `tests/unit/conftest.py:106` (imports `reset_global_pool`, errors swallowed).

**Does not hit:**
- `browser_navigator` (browser-use).
- `camofox_browser`.
- `computer_use` / `screen_capture` / `desktop_a11y`, which drive the desktop, not Playwright.
- `EgressGuard` rules.

## Surfaces
- Agents, through the browser tools.
- The web app's health routes.
- Humans: the JSON session files and the `./videos` and `./har` folders, all relative to the process's working directory except the session files.

## See
`weebot/infrastructure/browser/`
