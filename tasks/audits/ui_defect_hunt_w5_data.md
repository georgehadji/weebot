---
status: reference
date: 2026-10-31
---

# Wave 5 — Data Surfaces & Polling

Execution record for W5 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threats **T2** (silent wrong state), **T5** (liveness); classes **C1, C3, C4, C8, C10** (C9 for the
page-conformance exit criterion). Structure follows [`ui_defect_hunt_w1_transport.md`](ui_defect_hunt_w1_transport.md).

Every `[VF]` below came from running code. Commands: §11. Backend contracts were read, not changed
(`weebot/interfaces/web/routers/{behavior_router,ops_router,health}.py`).

Context carried into this wave: decision **D-BEH** (backend behavior API): session routes 404 for
sessions the caller does not own, `/behavior/recent` is filtered to the caller's sessions,
`/behavior/watch/start` answers 400 for a folder outside the workspace without echoing the path.

---

## Phase 0-WAVE — scope, budget

| | |
|---|---|
| **Baseline** | `tsc` 0, `lint` 0/0; `vitest` had 3 files transiently red while W4 was mid-edit on `lib/api.ts` (syntax error in the working tree), green once it settled |
| **Budget** | ≤15 generated · ≤10 investigated · ≤5 fixed |
| **Spent** | 15 generated · 10 investigated · **5 fixed** · 3 verified and unfixed (R6b, R4 by fix budget; D10 escalated) · 3 cleared · 5 not investigated |
| **Surface read** | all files of the wave (§1). One file outside the listed surface was edited, see §6. |

---

## Phase 1 — region map

| R | Region | Layer | Classes | Reachability | Blast | Invariant owner |
|---|---|---|---|---|---|---|
| R1 | `useRemote` (:17-56) | hooks | C3 | REACHABLE: every poll on `/sessions` (5 s), rail seed, role panel | SYSTEM (3 consumers) | hook (newest wins) |
| R2 | `/ops` live socket + caption (:65-83, :326) | app | C10, C2 | REACHABLE: Live Events tab | LOCAL | page (own socket) |
| R3 | `/ops` health/status vocabulary (:43-49) | app | C8, C10 | REACHABLE: Overview | LOCAL | `health.py` |
| R4 | `/ops` fetch loop (:93-129) | app | C3, C4, C10 | REACHABLE: 10 s interval | MODULE | page (no `Remote`) |
| R5 | `CostChart` / `MetricsPanel` inputs | components | C1 | REACHABLE: Cost tab, Overview | LOCAL | page passes `\|\| 0` |
| R6 | `PlanVizTab` (:372-438) | app | C4, C10 | REACHABLE: Plan tab | LOCAL | page |
| R7 | `/models` page + `RoleModelsPanel` | app, components | C4, C9 | REACHABLE: `/models` | LOCAL | `Remote`/`StateView` |
| R8 | `BehaviorPanel` data merge (:28-36) | components | C8, C10 | REACHABLE: `/behavior` Monitor tab | MODULE | panel |
| R9 | `useBehaviorREST` (`hooks/useBehavior.ts:178-269`) | hooks | C8, C3 | REACHABLE: same | MODULE | hook |
| R10 | `RecentActions` override POST | components | C4, C9 | REACHABLE: click a row | EXTERNALLY-VISIBLE (writes to the ledger) | component |
| R11 | `sessions` page and rail convergence | app, hooks | C9, C7 | REACHABLE: delete on `/sessions` | MODULE | `useSessionList` |
| R12 | `settings`, `debug`, `settings/behavior` pages | app | C4, C9 | REACHABLE / GUARDED (`debug`: `NODE_ENV !== production`; `settings/behavior`: a `redirect()`) | LOCAL | page |

### Atomic assertions about the map

1. **[VF]** `useRemote` is shared by three call sites with a poll or reload trigger (`sessions` 5 s,
   `useSessionList` reload-on-unknown-id, `RoleModelsPanel` reload-after-write), so an ordering defect there
   is SYSTEM scope, not a `/sessions` quirk.
2. **[VF]** The REST and socket behavior channels return *different shapes for the same noun*:
   REST `BehaviorEventResponse.event_type`, socket `recent.actions[].action`; REST trust has `status`,
   the socket's on-connect `trust.update` has none (`behavior_router.py:340-348`). `BehaviorPanel` merged
   them with socket priority.
3. **[VF]** The backend never answers a plan-viz/active-sessions failure with `200 {ok:false}`:
   `ops_router.py` returns `{"ok": True, ...}` or raises `HTTPException`. The page's `if (result.ok)` with
   no `else` is therefore unreachable on its false side.
4. **[HYP→VF]** `/ops` is the only data page that does not use `Remote<T>`; the §2.2 invariant row
   "every loaded surface is a `Remote<T>` rendered by `StateView`" was `[HYP]` for it. Confirmed below.
5. **[VF]** The UI has **no caller** of `/behavior/watch/start` or `/watch/stop` (grep over `src/`), so the
   third D-BEH change (400 without echoing the path) cannot reach any component today.

---

## Phase 2 — candidates (15 generated)

| ID | Location | Claimed violated property | Class | Innocence path named at generation |
|---|---|---|---|---|
| D8 | `useRemote.ts:17-56` | the newest response wins | C3 | load is serialised (it is not: `setInterval` fires with a request in flight) |
| D3 | `ops/page.tsx:326` | a status caption is derived from state | C10 | an outer provider guarantees the socket (the page opens its own) |
| R4 | `ops/page.tsx:93-129` | a failed poll is visible; one endpoint failing does not discard another | C4, C10 | zeros are acceptable placeholders |
| R6 | `ops/page.tsx:380-401` | `ok:false` is surfaced; the title names the loaded plan | C4, C10 | backend never returns `ok:false`; title tracks the loaded id |
| R5 | `CostChart.tsx` | zero rows / zero total render sanely | C1 | `\|\| 0` guards upstream |
| D4b | `ops/page.tsx:43-49` | status vocabulary matches `/health` | C8 | overall status is healthy/degraded/unhealthy only |
| D10 | `sessions/page.tsx` + `useSessionList` | one source for the session list | C9, C7 | duplicates are a documented design |
| B1 | `BehaviorPanel.tsx:28-36` | displayed trust/actions are the freshest, complete data | C8, C10 | the socket pushes updates (it does not: one frame on connect) |
| B2 | `useBehavior.ts` `fetchRecent` | REST rows match `RecentAction` | C8 | the backend names the field `action` (it names it `event_type`) |
| B3 | `RecentActions.tsx:53-75` | a refused override is reported | C4 | non-OK is rare (D-BEH makes 404 normal) |
| R7a | `models/page.tsx` | page is `Remote<T>` + `StateView` with Retry | C9, C4 | written justification |
| R7b | `RoleModelsPanel` write path | a role write converges | C3 | n/a |
| N1 | `app/behavior/page.tsx:96` self-knowledge download | an error response is not saved as the file | C4 | n/a |
| N2 | `useBehaviorREST` on `sessionId` change | rows of session A are not shown under session B; late responses are dropped | C3 | n/a |
| N3 | `settings/page.tsx:27-32` | Save without editing leaves the proxy default | C9 | n/a |

---

## Phase 3/4 — inventory (10 investigated)

`user-visible consequence` is what the person at the console sees.

| Candidate | Trigger | Innocence attempt | Evidence | Status | User-visible consequence |
|---|---|---|---|---|---|
| **D8** | `useRemote.ordering.test.ts` (2 of 4 failed at HEAD) | guard: none; reachability: a 5 s poll against a slow backend overlaps; owner: the hook owns ordering and does not enforce it | executed, deterministic (fake timers, hand-settled promises) | **VERIFIED, FIXED (F1)** | `/sessions` list, rail seed or role list jumps backwards, or a good list is replaced by an error banner |
| **D3** | `ops/page.test.tsx` D3 (3 of 4 failed at HEAD) | no provider owns the socket; the page opens its own at :69 | executed | **VERIFIED, FIXED (F2)** | "WebSocket connected" with a pulsing green dot before the socket opens and after it dropped, forever |
| **B1** | `behavior.test.tsx` B1 (2 of 4 failed) | contract owner: the backend sends one trust frame on connect, `{score,total_actions,overrides}` with no `status` and no `score_percentage` (`behavior_router.py:340-348`), never broadcasts `trust.update` afterwards, and `recent.actions` only answers `get_recent`, sent once on open | executed + contract read | **VERIFIED, FIXED (F3)** | while the socket is up (the normal state) the trust bar says **Unknown** instead of Trusted/Review; an override just marked never appears in the list (the socket snapshot wins forever) |
| **B2** | `behavior.test.tsx` B2 (1 of 2 failed) | contract: `BehaviorEventResponse.event_type` (`behavior_router.py:49-56`) vs UI `RecentAction.action` | executed + contract read | **VERIFIED, FIXED (F4)** | REST rows render a generic icon, and the override dialog reads "**undefined** /path" |
| **B3** | `behavior.test.tsx` B3 (3 of 4 failed) | D-BEH makes 404 (`Action not found`, `behavior_router.py:174`) and other 4xx normal; the `else` branch did not exist | executed | **VERIFIED, FIXED (F5)** | clicking "Mark Override" on a refused action does nothing: dialog stays, no message, button re-enables |
| **R6** | `ops/page.test.tsx` R6 | (a) `ok:false`: **CODE-INNOCENT**, unreachable (`ops_router.py:57-80`; the 404 test passes at HEAD and shows the message). (b) title and stale plan: guard none, reachable by typing | executed | (a) **CLEARED**; (b) **VERIFIED, UNFIXED (fix budget)**, two `it.fails` | the plan card is titled "Plan for <what you are typing>"; after a failed load for session B the card still shows session A's plan under "Plan for B" |
| **R4** | `ops/page.test.tsx` R4 | the page has no `Remote`; the swallowed `catch` is deliberate (comment "backend may not be running") | executed | **VERIFIED, UNFIXED (fix budget)**, two `it.fails`; the 10 s loop itself is bounded and unmount-cleared (that test passes) | with the backend down the metrics card shows **0 sessions, 0% CPU, 0 MB, $0.00** as if measured; if `/dashboard/metrics` fails while `/health` is fine, the health card says "Failed to load health status" (`Promise.all` discards both); a poll that fails after a success shows stale data with no marker |
| **D10** | `sessions/page.test.tsx` | the backend emits no presence frame on delete (`sessions.py:227` returns, no broadcast); the rail's only reload trigger is an unknown presence id | executed | **VERIFIED, ESCALATED** `[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`, one `it.fails` | a session deleted on `/sessions` stays in the rail until reload |
| **D4b** | `ops/page.test.tsx` D4b | overall `status` is `healthy`/`degraded`/`unhealthy` (`health.py:56,88,116,207,211`); all three have a colour | executed | **CLEARED (CODE-INNOCENT)** at the overall level. Residual **observation O-W5-1**: a *component* row with `warning`/`unknown`/`critical` (`health.py:154-179`) takes the error colour; the text is printed verbatim, nothing is lost | colour only |
| **R5** | `ops/page.test.tsx` R5 | `ops` passes `\|\| 0`, `CostChart` guards `totalTokens > 0`, the Pie label guards `percent` | executed (one row, zero totals, no models: no `NaN`/`Infinity`) | **CLEARED** | none |

**Not investigated (budget `≤10`), still `[HYP]`:**

- R7b: the `RoleModelsPanel` select snaps back to the old value until the reload resolves.
- N1: `app/behavior/page.tsx:96` has no `res.ok` check, so a 4xx body is saved as a file whose content
  is the text `undefined`; the `fetch` has no `catch`.
- N2: `useBehaviorREST` does not guard late responses or clear rows when `sessionId` changes; a D-BEH 404 for
  a foreign session reports "Unavailable" while the previous session's rows stay on screen.
- N3: `settings` Save writes the displayed *default* backend URL into storage, which switches
  `getApiBase()` from the same-origin proxy to a direct cross-origin call; `localStorage.setItem` is unguarded.
- `useBehavior` `console.log` x4 (observation O5 of the plan).

---

## Phase 5 — fixes (5)

All five are placed at the invariant owner; no pattern introduced, no `fetch` added outside existing
sites, no ceiling change, no exported prop or return-shape change.

### F1 — D8: `hooks/useRemote.ts` (one effect)

`started`/`applied` counters local to the effect: a response is applied unless a *newer* one already was.
In-order responses behave as before; an older response that arrives first still applies (it is the newest
known). `FIX HOLDS [VF]` (4 new tests plus the 3 existing `useRemote` tests).

### F2 — D3: `app/ops/page.tsx` (one effect and 3 JSX lines)

`wsLive` state set by `onopen`/`onclose`; caption `WebSocket connected` / `Connecting…`; dot green and
pulsing only when live; one fixed 3 s reconnect after a drop, cleared on unmount through a `disposed`
flag. Size note: the diff is ~51 lines because the effect moved its `onmessage` body inside `connect()`
(re-indentation); net new logic is ~14 lines. `FIX HOLDS [VF]`. The fixed 3 s delay is a **shortcut**: no
backoff ceiling, to be revisited when `/ops` joins the transport pool (W1 report §9.3).

### F3 — B1: `components/behavior/BehaviorPanel.tsx` (one component)

`rest.trustScore || ws.trustScore` and `rest.recentActions.length > 0 ? rest.recentActions : ws.recentActions`.
`FIX HOLDS [VF]`; boundary: REST unavailable falls back to the socket's partial data (header still says
Live); REST-only still works.

### F4 — B2: `hooks/useBehavior.ts` `fetchRecent` (one callback), a file outside the literal surface list

Maps `event_type` to `action` at the boundary that receives the payload (§5a rung 2). The file is
re-exported by `components/behavior/index.ts`, no other wave owns it, and W1 mapped it (R6) without
auditing it. `FIX HOLDS [VF]`.

### F5 — B3: `components/behavior/RecentActions.tsx` (one component)

On a non-OK answer: `error` state from `detail` (when a string) or `HTTP <status>`, rendered as
`role="alert"` in the open dialog; on a thrown fetch: "Could not reach the backend". The POST now goes
through `getApiBase()` instead of `ENDPOINTS.api` (the same call previously bypassed the proxy and
`weebot_backend_url` that every sibling call honours; C9, same function). `FIX HOLDS [VF]`.

### Not a defect fix: `/models` migrated to `Remote<T>` + `StateView` (exit criterion)

`app/models/page.tsx` had a hand-rolled loading/error pair with no Retry (a failed load was a dead end
until reload) and duplicated what `StateView` renders. Migrated, with the page body split into
`ModelCatalog`; behaviour otherwise identical. Counted as conformance work (C9), not against the five
defect fixes. Three tests: Retry recovers, loading status, empty catalogue.

---

## Phase 6 — RAR self-review (changed code only)

| # | Vector | Result |
|---|---|---|
| 1 Boundary | empty list, zero rows | `pollMs` undefined, REST `[]`, `/models` `[]` tested. A `detail` that is a validation array falls to `HTTP <status>` by construction `[HYP]` |
| 2 Invalid input | non-JSON error body | `res.json().catch(() => null)` in F5. F4 assumes the documented array; a non-array throws into the existing `catch` and reports "Unavailable" |
| 3 State | StrictMode double mount | F2: the second mount re-runs the effect; cleanup sets `disposed`, clears the timer, closes the socket. Unmount case `[VF]`; real StrictMode `[HYP]` |
| 4 Regression | existing suites | full run green (§11). `make lint-ui` counters not run here (`[UNK]`) |
| 5 Concurrency | out-of-order | F1 is the fix; F3 and F5 add none |
| 6 New defect | C1-C10 over changed files | none beyond those in §3 |
| 7 Architecture | layers | no `react` in `lib/`, no `fetch` added, no ceiling change; F4 is owner-placed in a hook |
| 8 Paradigm | | `Remote<T>` and `StateView` extended to `/models`; no new pattern |

---

## Phase 7 — tests

| File | Tests | Role |
|---|---|---|
| `src/hooks/useRemote.ordering.test.ts` | 4 | D8 proof (2 failed at HEAD), in-order regression, no-poll boundary |
| `src/app/ops/page.test.tsx` | 12 | D3 proof x3 + regression; R6 cleared + 2 `it.fails`; R4 2 `it.fails` + loop-bounded; D4b cleared; R5 cleared |
| `src/components/behavior/behavior.test.tsx` | 10 | B1 x4, B2 x2, B3 x4 (6 failed at HEAD) |
| `src/app/models/page.test.tsx` | 3 | `/models` Retry, loading status, empty catalogue |
| `src/app/sessions/page.test.tsx` | 1 | D10 `it.fails` |

**`it.fails` convention (new to this repo, deliberate).** Five verified-but-unfixed defects are pinned as
`it.fails("KNOWN DEFECT …")`: the suite stays green, and each test turns red the day its defect is fixed,
which is the prompt to flip it to `it(...)`. Each was run once as a plain `it` to confirm it fails for the
stated reason (for example `expected 'Plan for ab' to be 'Plan for a'`), not for a setup error. One such
setup error was caught that way: a stub answering every URL with a plan body crashed `/ops` on
`result.data.sessions`. That is a contract-violating stub, not a defect (the backend always returns
`sessions`).

Environment note: Node 24 exposes a broken global `localStorage` unless `--localstorage-file` is set, so
`ops/page.test.tsx` stubs it (`ops` reads `weebot_ws_url` unguarded; `api.ts` guards its own reads).

---

## Exit criterion — every page in the wave

| Page / component | Load state | Polling / live loop | Verdict |
|---|---|---|---|
| `/sessions` | `Remote<T>` + `StateView` | `useRemote(…, 5000)`; newest-wins (F1); unmount-cancelled | meets |
| `/models` | **`Remote<T>` + `StateView` (migrated)** | none | meets |
| `RoleModelsPanel` | `Remote<T>` + `StateView` | reload after write | meets; R7b not investigated |
| `/ops` | **hand-rolled `useState` x4**, errors swallowed | 10 s interval, bounded and unmount-cleared `[VF]`; live socket now state-derived (F2) | **does not meet; carries this justification:** migrating five sources (health, metrics, active, plan, socket) to `Remote<T>` is a page refactor beyond the 15-line/1-function fix limit. Its consequences are pinned as `it.fails` (R4, R6b). `[REQUIRES HUMAN REVIEW: refactor]` |
| `/behavior` (`BehaviorPanel`) | two hooks, null until loaded; header is `Live`/`Loading`/`Unavailable`/`Polling` from state | REST 5 s poll (`useBehaviorREST`; its unmount flag only guards `isLoading`) plus socket | partial: header state-derived `[VF]`; `TrustBar` shows "Loading trust score…" forever when REST is unavailable and the socket sent no frame (observation); N2 open |
| `/settings` | none (reads storage in a `useState` initializer, writes on Save) | none | **justified: not a data surface** (a form over `localStorage`). Open: N3, and the SSR/hydration read of `localStorage` in the initializer `[UNK]` (needs a browser) |
| `/settings/behavior` | none | none | **justified:** a server `redirect()` |
| `/debug` | none | one socket via `useWebSocketDebug` (W1 R7) | **justified:** dev-only tool, `notFound()` in production, no polling |
| `MetricsPanel`, `CostChart` | props only | none | pure; R5 cleared |

Polling inventory, nothing left unexamined: `useRemote` (`/sessions` 5 s: examined, F1) · `/ops`
`setInterval` 10 s (examined, bounded) · `useBehaviorREST` `setInterval` 5 s (examined, N2 open) ·
`useSessionList` reload-on-unknown-id (W1 R5, one reload per id) · `settings` `setTimeout` 2.5 s "Saved"
badge (not cleared on unmount; a harmless `setState` after unmount, **observation**).

---

## Phase 8 — verdict

### Process checks

| Check | Status |
|---|---|
| Each fixed defect VERIFIED (trigger fired, no innocence defence held) | ✅ x5 |
| Fix ≤15 lines and ≤1 function | ✅ F1, F3, F4, F5; F2 ~14 net-new logic lines, 51 diff lines from re-indentation (stated above) |
| Proof + boundary + no-regression tests | ✅ every fix |
| Phase 0 census complete | ✅ (reused) |
| Fix in the invariant-owning layer | ✅ (F4's owner is a hook outside the listed surface, §6) |

### Engineering checks

| Check | Status |
|---|---|
| Self-review vectors FIX HOLDS or CANNOT DETERMINE | ✅ (StrictMode `[HYP]`) |
| Regression risk LOW/MEDIUM | ✅ LOW; F3 changes which source wins, and REST is the complete one |
| Fix causal, not symptomatic | ✅ |
| No unresolved fix interaction | ✅ F3 and F4 are a pair on purpose: F3 alone would expose B2 on every load |
| No dependency-rule violation / abstraction bypass | ✅ (F5 removes one) |
| No pattern introduced | ✅ (`it.fails` is a test convention, not a runtime pattern) |

**Routing:** ACCEPT F1-F5. ESCALATE D10 (cross-boundary) and R4 (page refactor). **PARTIAL** for the wave:
the fix budget was reached with R6b and R4 verified and unfixed; five candidates were not investigated.

### Coverage statement

```
Surface audited:            R1-R6, R8-R11, R7a; polling inventory complete (5 loops)
Surface NOT audited:        R7b (role write path), N1 self-knowledge download, N2 sessionId-switch
                            race in useBehaviorREST, N3 settings Save, settings hydration read;
                            browser-only behaviour (Playwright launch blocked on the CI VM)
Defect classes covered:     C1, C3, C4, C8, C10 (C9 for page conformance)
Architecture census basis:  VF (README layers, eslint rules, ceilings, tsc --strict); backend
                            contracts read from source
Confirmed defects:          CRITICAL 0 / HIGH 1 / MEDIUM 7 / LOW 0
                            HIGH: B1 (trust "Unknown" in the normal connected state)
                            fixed 5 (D8, D3, B1, B2, B3); unfixed 3 (R6b, R4; D10 escalated)
Cleared (innocent):         3 (R6a ok:false, D4b top level, R5)   Re-attributed to owner: 1 (D10)
Observations:               3 (O-W5-1 component status colours; TrustBar "Loading…" when REST is
                            unavailable; "Saved" timer not cleared)
Residual UNKNOWN:           N1-N3, R7b; settings-form hydration; StrictMode in production
Clean-claim scope:          "Regions R1-R6, R8-R11 were audited for the listed classes and no VERIFIED
                            defect remains that is neither fixed nor recorded above." Not "the data
                            surfaces are bug-free".
Highest-value next hunt:    N1 + N2 (behavior data layer, each one read from verified) and the
                            /ops -> Remote<T> migration, which clears R4 and R6b in one change.
```

---

## 6. Changed outside the listed surface, and why

| File | Change | Reason |
|---|---|---|
| `src/hooks/useBehavior.ts` | F4: `event_type` to `action` in `fetchRecent` | owner of the REST boundary for `components/behavior/*` (re-exported by its `index.ts`); no other wave owns it |
| `src/app/behavior/page.tsx` | **not edited** | N1 recorded, not fixed: not on the surface list (the list names `settings/behavior/page.tsx`, a redirect) and the fix budget was spent |

Nothing deferred into W2/W4/W7 files. The D10 mechanism (a delete must reach the rail's
`useSessionList`) needs either a backend presence frame on delete or a shared reload signal between
`useSessionList` and the sessions page: an owner decision.

## 9. Recommendations carried to W8

1. **`/ops` to `Remote<T>`**: one `useRemote` per source (health, metrics, active), `allSettled`
   semantics for the overview, and the plan tab holding `{loadedId, plan}` together. Clears R4 and R6b.
2. **D10**: emit a presence frame on session delete (backend); the rail then converges with no UI change.
3. **Behavior channel**: one normaliser for REST and socket rows (and trust) instead of per-consumer
   precedence rules; or drop the socket's recent/trust snapshots, which F3 made redundant.
4. Flip the five `it.fails` pins as each defect is fixed.

## 10. Uncertainty acknowledgment

**Finding most likely to be a false positive.** B3's severity. The dialog staying open on a refused
override is visible, but the operator impact of a missing message depends on how often `mark_override`
404s; D-BEH makes it plausible and no log was consulted.

**Real defect most likely missed.** N2: `useBehaviorREST` keeps `recentActions` of the previous session
after a `sessionId` change and its fetches are not cancelled; with D-BEH 404s it can show session A's rows
under session B's header. Static read only.

**Architectural claim most likely wrong.** "The panel owns source precedence" (F3). If the behavior
WebSocket later broadcasts `trust.update`/`recent.actions` on change, REST-first would hide fresher socket
data for up to 5 s; the right owner would then be a single normaliser (§9.3).

**What requires runtime validation.** `settings` hydration (the server renders defaults, the client reads
`localStorage` in a state initializer), real StrictMode behaviour of F2, and every DOM-level check
(browser launch is blocked on the CI VM).

**What additional input would most increase confidence.** A browser-capable runner for
`npm run test:e2e`, and one recorded `/behavior/ws` session (frames and timings).

## 11. Commands

```bash
cd weebot-ui
npx vitest run src/hooks/useRemote.ordering.test.ts src/app src/components/behavior   # all pass
npx vitest run                                                                       # 30 files, 208 tests
npx tsc --noEmit                                                                     # 0
npm run lint                                                                         # 0 errors, 0 warnings

# contract evidence read for this wave
sed -n '85,260p' weebot/interfaces/web/routers/behavior_router.py   # D-BEH routes, BehaviorEventResponse, WS frames
sed -n '39,100p' weebot/interfaces/web/routers/ops_router.py        # {"ok": True} or HTTPException
grep -n "status" weebot/interfaces/web/routers/health.py            # healthy/degraded/unhealthy/warning/critical/unknown
```

Not run: `next build` (reserved by the caller), `make lint-ui` and `scripts/lint_ui_debt.py` (no Python
run this wave).

## Follow-up (2026-10-31)

D10 is fixed: the delete route publishes a `session_presence` frame with status `deleted` (`weebot/interfaces/web/routers/sessions.py`, `tests/unit/fixes/test_d10_delete_tells_the_rail.py`), and `useSessionList` drops that row. The `it.fails` pin in `src/app/sessions/page.test.tsx` is now a plain test.

## Follow-up: R4 and R6b fixed

`/ops` health and metrics now load through `useRemote` + `StateView` (one hook per source, so one failing
endpoint no longer discards the other; metrics and health show a skeleton, an error banner with Retry, or the
data, never measured zeros). The plan tab holds `{id, nodes}` together, so the title names the loaded
session, and a load clears the previous plan first, so a failed load leaves none on screen. The four
`it.fails("KNOWN DEFECT (budget)")` tests are now plain `it(...)`; the active-sessions poll and the live socket
are unchanged. Not done: active sessions still use `useState` (swallowed errors), outside R4/R6b.
