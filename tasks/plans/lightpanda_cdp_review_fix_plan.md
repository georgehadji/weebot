---
status: done
date: 2026-10-31
---

# Lightpanda CDP browser: fixes for the 7 review findings on PR 126

## Context

PR 126 (merged as `04085242`) added `WEEBOT_BROWSER_CDP_URL`. When it is set, the three Chromium launch sites (`PlaywrightAdapter._launch`, `BrowserSessionPool._create_session` and `WebScraperTool` in `advanced_browser.py`) connect to a running CDP browser such as Lightpanda instead of launching one. The work all goes through `open_chromium` (`weebot/infrastructure/browser/playwright_adapter.py:25-39`).

A `/code-review` at high effort found seven problems:

| # | Finding | Kind |
|---|---------|------|
| 1 | A failed connect silently launches host Chromium, which defeats container isolation | security |
| 2 | `connect_over_cdp` has no timeout (Playwright defaults to 30s) and nothing remembers a failure | efficiency |
| 3 | The fallback warning logs the raw URL, which can carry a token | security |
| 4 | Every pooled session opens its own CDP connection, with no cap tied to Lightpanda's limit | correctness |
| 5 | `headless=False` is silently ignored under CDP | correctness |
| 6 | The Chromium-or-other branch is copied in the adapter and the pool | simplification |
| 7 | The launch-site test greps source text instead of running code | test-coverage |

Two facts shape the design:

- **Fail closed.** `docs/SECURITY_MODEL.md` requires fail-closed defaults, so a security-relevant setting must not degrade silently.
- **The agent controls `headless`.** The browser tool exposes a `headless` argument (`weebot/tools/advanced_browser.py:106`, which reaches `BrowserConfig(headless=headless)` at `:382`). So "a launch-only option forces a local launch" must never be the rule in CDP mode. An agent could pass `headless: false` and escape the container.

## Design

### Shape: a functional core with an imperative shell

All the launch decisions move into one new infrastructure module, `weebot/infrastructure/browser/browser_launcher.py`. Clean Architecture places it in infrastructure, next to the Playwright code it drives. Nothing in domain or application changes, and `BrowserPort` stays as it is.

- **Pure core.** `plan_launch(browser_name, launch_options, cdp, breaker_open) -> LaunchPlan` is a pure function over values. It makes no I/O calls and does not read settings.
  - `LaunchPlan` is a frozen dataclass whose `mode` is `"connect"`, `"launch"` or `"refuse"`, plus a `reason: str`.
  - `CdpSettings` is a frozen dataclass with `url`, `fallback`, `connect_timeout_ms` and `max_connections`, built once per call from `get_settings()`.
  - The core is table-testable with no mocks. That is the right paradigm for policy that will grow, such as a Firefox CDP path or more launch-only options.
- **Imperative shell.** `async def open_browser(browser_type, launch_options) -> Browser` reads the settings, calls `plan_launch`, and carries out the plan: connect, launch or raise. It also handles the breaker and the logging. This is the only function the three call sites use.
- **Strategy by data, not classes.** The two strategies are just `connect_over_cdp` and `launch`. One `match plan.mode` in the shell is enough. A `LaunchStrategy` class hierarchy would be one interface with two trivial implementations, which is YAGNI.

`open_chromium` is removed. `playwright_adapter.py` keeps no launch policy.

### Decision table (`plan_launch`)

| CDP url | Browser | Launch-only option asked for (`proxy`, or `headless=False`) | Breaker open | Result |
|---|---|---|---|---|
| unset | any | any | – | launch |
| set | firefox or webkit | any | – | launch, since CDP applies to Chromium only (unchanged behavior) |
| set | chromium | no | no | connect |
| set | chromium | yes | – | `fallback` on: launch. `fallback` off: refuse, with a reason naming the option |
| set | chromium | no | yes | `fallback` on: launch. `fallback` off: refuse ("CDP endpoint unavailable") |

A connect failure at run time (the shell catches it, records it in the breaker, then re-applies the "breaker open" row) follows the same `fallback` rule. So there is exactly one rule for when a host launch is allowed: the operator opted in.

`proxy` used to force a launch silently. Under the new rule a proxied Chromium config with CDP set and `fallback` off is refused. That is a deliberate behavior change. It closes the same isolation hole as `headless`, and a test pins it.

## Fixes, finding by finding

### 1. Fail closed instead of a silent host launch

- **New setting.** `browser_cdp_fallback: bool = Field(default=False, alias="WEEBOT_BROWSER_CDP_FALLBACK")` goes in `weebot/config/settings.py`, next to `browser_cdp_url`, and in `scripts/generate_config_reference.py`. Its description says that turning it on lets pages render on the host when the CDP browser is down. Regenerate `.env.example` and `docs/CONFIGURATION.md`.
- **New error.** `CdpBrowserUnavailable(RuntimeError)` lives in `browser_launcher.py`. Its message carries the plan reason and the redacted URL.
- **Callers need no new handling.** `PlaywrightAdapter._start` already cleans up and re-raises. The pool counts the error and re-raises. `WebScraperTool` already turns exceptions into `ToolResult(error=...)`. The agent sees a clear tool error and can fall back to `web_search`, which is the documented fallback in CLAUDE.md.
- **Logging.** When a fallback launch does happen, log it at `warning` once per breaker trip, not once per call.

### 2. Timeout and failure memory

- **Connect timeout.** Pass `timeout=cdp.connect_timeout_ms` to `connect_over_cdp`. It comes from a new setting, `browser_cdp_connect_timeout_ms: int = 5000` (`WEEBOT_BROWSER_CDP_CONNECT_TIMEOUT_MS`), and is added to the config reference.
- **Failure memory.** Reuse `weebot/core/circuit_breaker.py::CircuitBreaker` rather than adding a new memo. Infrastructure may import core, so no new `ignore_imports` entry is needed.
  - The breaker is a module-level instance keyed by the redacted endpoint, with `failure_threshold=1`, `cooldown_seconds=30` and `enable_stagger=False`.
  - Call `evaluate()` before connecting, `record_failure()` on an exception, and `record_success()` on a connect.
  - Within the cooldown, calls go straight to refuse or launch with no network wait. After the cooldown, the breaker's HALF_OPEN state lets one probe through.
- **Why the core breaker.** It is already asyncio-safe and has the open, half-open and closed state machine. Writing a second "last failure at" timestamp would duplicate it.

### 3. No secrets in logs

- Add `redact_endpoint(url) -> str` to `browser_launcher.py`. It uses only `urllib.parse`: it keeps the scheme, host and port, drops userinfo, the query and the fragment, and returns `"<invalid CDP url>"` if parsing fails.
- Every log line, error message and breaker key uses the redacted form. The raw URL is passed only to `connect_over_cdp`.
- The exception text is logged with `type(exc).__name__` only. Playwright's message can echo the WebSocket URL.
- **Why not `SecretRedactor`.** `weebot/core/secret_redaction.py` relies on pattern and entropy heuristics and can miss a short token in a query string. A structural strip is exact for URLs, and it is about five lines.

### 4. Cap CDP connections from the pool

- **Step 0: verify.** Start a Lightpanda container (the user approves the Docker pull first) and check its documented connection and context limits. Record the numbers in the Browser card.
- **Fix.** Add a setting, `browser_cdp_max_connections: int = 0` (`WEEBOT_BROWSER_CDP_MAX_CONNECTIONS`, where 0 means unlimited). When CDP is active, `BrowserSessionPool.__init__` clamps `self.max_sessions` (and `min_sessions`) to it, and the existing `asyncio.Semaphore(self.max_sessions)` enforces the cap with no new mechanism. It logs once at `info` when it clamps.
- **Scope.** Only the pool holds long-lived connections. `PlaywrightAdapter` holds one, and `WebScraperTool` opens and closes one per call, so they need no cap.
- **If Step 0 shows the limit is at least the pool default (5) and the context model fits,** keep the setting anyway, since it costs one line and Lightpanda versions change. Record the finding as `no_change_needed` for behavior and add the clamp test only.

### 5. `headless=False` under CDP

- Handled by the decision table. `headless=False` counts as a launch-only option, so with `fallback` off it is refused with the reason "headless=False needs a local browser; WEEBOT_BROWSER_CDP_URL is set". With `fallback` on, it launches locally and the user gets the window they asked for.
- Both paths are explicit, so nothing is silently ignored.
- `BrowserSessionPool._config_matches` keeps comparing `headless`. It is meaningful again, because a `headless=False` session is either a real local window or never created.

### 6. One dispatch point

- `PlaywrightAdapter._launch` and `BrowserSessionPool._create_session` each replace their `if browser_type is self._playwright.chromium: ... else: ...` block with `browser = await open_browser(browser_type, launch_options)`.
- `open_browser` reads `browser_type.name` (Playwright's `BrowserType.name` returns `"chromium"`, `"firefox"` or `"webkit"`) and passes it to `plan_launch`.
- `WebScraperTool` calls `open_browser(playwright.chromium, {"headless": True})`.
- **Import contract.** `.importlinter` currently exempts `weebot.tools.advanced_browser -> weebot.infrastructure.browser.playwright_adapter`, and the scraper still imports `PlaywrightAdapter` at `weebot/tools/advanced_browser.py:375`. Add one sibling exemption for `weebot.infrastructure.browser.browser_launcher`, with the comment "same delegation as playwright_adapter". This is a moved edge, not a new cross-layer dependency. The cleaner end state is to route the scraper through `PlaywrightAdapter`/`BrowserPort` and drop both exemptions, but that is out of scope here and listed below.
- The pool's deferred import becomes a top-level import, since both modules are in the same package.

### 7. Behavioral tests, not source greps

The new `tests/unit/infrastructure/browser/test_browser_launcher.py` replaces `test_cdp_browser.py`. Each test is written first and seen to fail.

- **Core table (pure, parametrized).** One case per row of the decision table, including proxy plus CDP plus fallback off giving refuse, and `headless=False` plus fallback off giving refuse, with the reason text asserted.
- **Shell.** Using the existing fake-`chromium` style (`SimpleNamespace` plus `AsyncMock`, with a `name` attribute):
  - connect passes `timeout=5000`;
  - after one failure, a second call does not await `connect_over_cdp` (breaker open);
  - after the cooldown (the breaker's clock monkeypatched), it probes again;
  - fallback on launches, and fallback off raises `CdpBrowserUnavailable`;
  - a token URL never appears in `caplog` text or the exception message.
- **Call sites (behavioral).**
  - Drive `PlaywrightAdapter._launch` and `BrowserSessionPool._create_session` with a fake `_playwright` whose `chromium`, `firefox` and `webkit` are fakes. Assert that Chromium goes through connect when CDP is set, that Firefox launches, and that `proxy` reaches `plan_launch`.
  - Drive `WebScraperTool` with `async_playwright` monkeypatched, and assert it calls `open_browser`.
- **Pool clamp.** With CDP set and `max_connections=2`, a pool built with `max_sessions=5` has `max_sessions == 2`.
- **Isolation.** Every test sets the settings through monkeypatch on `get_settings()`, as the current fixture does, and resets the module breaker in an autouse fixture. No test touches real files or the network.

## Order of work (one branch, `fix/cdp-browser-review`)

1. Add the settings, then the config reference, then regenerate `.env.example` and `docs/CONFIGURATION.md`.
2. Write the `browser_launcher.py` core and its table tests (findings 1, 5).
3. Write the shell: timeout, breaker, redaction (findings 2, 3).
4. Move the three call sites to `open_browser`, delete `open_chromium`, and add the `.importlinter` sibling entry (finding 6).
5. Add the call-site behavioral tests and delete `test_cdp_browser.py` (finding 7).
6. Do the Lightpanda limit check with the user's OK for the Docker pull, then the pool clamp (finding 4).
7. Update the map cards Browser.md, BrowserTools.md and WeebotSettings.md with full-path citations, then run `scripts/check_map_citations.py --drift`.
8. Run the gates: `make lint-imports`, `ruff check .`, `scripts/prepush_gates.py` (ceilings may only go down), and the full suite with `-n auto`.

## Not in scope

- Routing `WebScraperTool` through `BrowserPort` to remove both `tools-no-infra` exemptions. It is worth a separate change.
- A Firefox or WebKit CDP path.
- Per-session context reuse over a single shared CDP connection. Revisit it only if Step 0 shows Lightpanda allows many contexts per connection.

## Outcome

All seven findings are implemented on `fix/cdp-browser-review`.

Step 0 result, measured on `lightpanda/browser:1.0.2`: `--cdp-max-connections` defaults to 16, and the 17th simultaneous connection gets `503 Too many connections`. A second browser context on one connection is refused. The pool default of 5 therefore fits, and finding 4 needed no behavior change beyond the optional `WEEBOT_BROWSER_CDP_MAX_CONNECTIONS` cap, which stays at 0 (no cap).

One deviation from the design: `web_scraper` imports `open_browser` through `playwright_adapter`, not from `browser_launcher`. A sibling `.importlinter` exemption raised `import_exemptions` above its ceiling, and ceilings do not go up.
