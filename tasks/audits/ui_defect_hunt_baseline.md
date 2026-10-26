---
status: reference
date: 2026-10-25
---

# Frontend Defect Hunt — Wave 0 Baseline & Test Harness

**Executed:** 2026-10-25
**Plan:** [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md) — W0
**Protocol:** V7.1 (proactive). W0 is a *precondition*, not a hunt: it makes the transport
observable so waves W1–W8 inherit trustworthy evidence. **No production behaviour in scope for
W0 changed** except where a wave later fixed a verified defect (that is W1's record, not this one).

Every number below was produced by running the command beside it. Commands: §4.

---

## 1. Measured gates

### 1.1 At HEAD, before W0

| Gate | Command (`weebot-ui/`) | Result |
|---|---|---|
| install | `npm ci` | clean, 579 package dirs |
| typecheck | `npx tsc --noEmit` | 0 errors |
| lint | `npm run lint` | 0 errors, 0 warnings |
| unit + component | `npx vitest run` | **12 files, 75 tests**, all pass |
| build | `npx next build` | OK, 11 routes |
| UI debt ratchet | `python3 scripts/lint_ui_debt.py` | 6 counters at ceiling |
| contrast | `python3 scripts/check_ui_contrast.py` | 58 token pairs ≥ 4.5:1, both themes |
| browser suite | `npx playwright test` | **[BLOCKED]** — 76/76 fail at `browserType.launch` (`libnspr4.so` missing, no root) |

### 1.2 After W0 (harness added, no production change)

| Gate | Result |
|---|---|
| `npx tsc --noEmit` | 0 errors |
| `npm run lint` | 0 errors, 0 warnings |
| `npx vitest run` | **14 files, 85 tests**, all pass (12/75 at HEAD + 4 harness self-tests + 6 W1 proof tests) |
| `npx next build` | OK, 11 routes |
| `python3 scripts/lint_ui_debt.py` | `ui_orientation_selectors: 0`, `ui_tiny_text: 0`, `ui_viewport_height: 0`, `ui_main_landmarks: 1`, `ui_click_on_static: 0`, `ui_layer_violations: 0` — all at ceiling |
| `python3 scripts/check_ui_contrast.py` | 58 pairs ≥ 4.5:1 |
| `npx playwright test` | still **[BLOCKED]** (§3) |

**No ceiling was raised, no exemption added, no dependency added.**

---

## 2. Instrument readiness after W0

| # | Instrument | Before | After |
|---|---|---|---|
| I1 | `eslint` layer rules | 2 import contracts, 0 warnings | unchanged; still the only enforced dependency rule |
| I2 | `lint_ui_debt.py` | 6 regex counters, exact equality | unchanged |
| I5 | unit harness | `setupFiles: []`, no `WebSocket`, no fake-timer convention — **a socket could not be tested at all** | `tests/harness/fake-transport.ts`: fake `WebSocket` (accept/emit/server-close/client-close, with close dispatched as a microtask like a browser), fake streaming `fetch` for SSE (push/end/fail, records `X-API-Key` and abort state), `flushStream()` microtask pump, `sseFrame()` that encodes exactly as `sse_starlette` does. Installed per test, never globally. |
| I6 | type boundary | payloads `as`-cast after `JSON.parse` | unchanged — the boundary is still unvalidated; W1's D12 is precisely the case where the *wire format*, not the payload type, was wrong |
| I8 | `make lint-map` | red: 143 pre-existing `map/*.md` citation drifts | unchanged; not this surface's debt, and not touched |

**Deliberate non-change:** the harness is *not* in `vitest.config.ts` `setupFiles`. It must stay
inert unless a test asks for it, so no existing test can silently start talking to a fake socket.

---

## 3. Environment blockers (unchanged)

| Capability | Status | Consequence |
|---|---|---|
| `tsc`, `eslint`, `vitest`, `next build` | ✅ | all static and jsdom triggers work |
| Playwright browser launch | ❌ `libnspr4.so` missing; `sudo` blocked by *no-new-privileges*; apt index empty; `playwright install-deps` cannot run | every DOM-level trigger, axe suite, perf budgets stay `[BLOCKED]` |
| Backend on `:8000` | ❌ not running | not required — `e2e/fixtures.ts` stubs it; socket/SSE behaviour is now covered by the harness instead |

W0/H3 (browser baseline) therefore remains **open**. It is not reported as passing anywhere.
W0/H4: `npm run test:e2e` is wired in `package.json` but the repository's CI does not run it in
this environment — instrument finding, recorded, not a wave deliverable.

---

## 4. Commands

```bash
cd weebot-ui
npx tsc --noEmit
npm run lint
npx vitest run tests/harness/fake-transport.test.ts   # harness only
npx vitest run                                        # 14 files, 85 tests
npx next build

cd ..
python3 scripts/lint_ui_debt.py
python3 scripts/check_ui_contrast.py
```
