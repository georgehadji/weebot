---
status: open
date: 2026-10-25
note: V7.1 defect-hunt program for the whole frontend (weebot-ui). Phase 0 executed and measured on 2026-10-25; W0 (harness + baseline) and W1 (transport) executed the same day — see tasks/audits/ui_defect_hunt_baseline.md and ui_defect_hunt_w1_transport.md. W2–W8 not started.
outcome: build (2026-10-31, owner decision D-F): the frontend was never audited past W1; W2-W8 are the next audit work
---

# Autonomous Defect-Hunt V7.1 — the whole frontend (`weebot-ui`)

**Protocol applied:** `AUTONOMOUS DEFECT-HUNT PROTOCOL — V7.1 (PROACTIVE, ARCHITECTURE-AWARE)`
(EGFV · RAR · MRADO · PCST)
**Scope:** `weebot-ui/` — 106 TypeScript files (8,540 lines, tests included), 9 user-facing routes.
**Predecessor:** [`defect_hunt_v7_execution_plan.md`](defect_hunt_v7_execution_plan.md) ran V7 over the
Python surface and excluded `weebot-ui/` in §2.6 — *"different runtime, toolchain, and defect
taxonomy … warrants a separate V7 run with a JS-instantiated taxonomy"*. This is that run.
**Recon executed:** 2026-10-25, branch `main`, working tree as shipped after
[`ui_ux_remediation_plan.md`](ui_ux_remediation_plan.md).

Evidence tags are the protocol's own: **[VF]** verified fact (observed, or demonstrated by an
executed command), **[HYP]** hypothesis, **[UNK]** undecidable without runtime, **[FALSE]**
contradicted by evidence. Everything tagged [VF] below came from a command in Appendix A.

---

## 0. What this document is

The attached protocol is a **single-target** loop (Phases 0→8). Applying it "to the whole frontend"
taken literally is self-contradicting, for the reason the protocol itself gives: *"a proactive hunt
over an unbounded codebase never terminates, so Phase 0 bounds the hunt before any code is read for
suspicion."*

This plan does the three things the protocol demands but cannot do for you:

1. **Executes Phase 0 once, globally** — environment, architecture, invariants, threat model,
   taxonomy, scope and budget. Results are in §2 and are already evidence-classified.
2. **Decomposes the frontend into nine bounded hunt units ("waves", W0–W8)**, each of which runs
   the *full* Phase 1→8 loop with its own hunt queue, budget, fixes, tests and coverage statement.
3. **Fixes the operating procedure** (§5–§6): the commands, harnesses, gates and adapted
   self-review vectors an executor needs so every wave produces comparable evidence.

**This is a plan, not a hunt.** No candidate in §7 is a confirmed defect: each is a falsifiable
`[HYP]` with the observation that would clear it. The protocol's own rule applies — *"flagging
correct code as defective is a defect of this protocol"* — so §7 states the innocence path for
every seed.

---

## 1. Why the frontend cannot be one V7.1 pass

Surface, measured [VF]:

| Measure | Value |
|---|---|
| `.ts`/`.tsx` files under `src/` | 106 (63 of them carry `"use client"`) |
| Lines under `src/` | 8,540, of which 631 are tests |
| Routes built | 11 (`next build`): `/`, `/sessions`, `/sessions/[id]`, `/ops`, `/models`, `/behavior`, `/settings`, `/settings/behavior`, `/debug`, `_not-found`, `/api/[[...path]]` |
| Test files | 12 (11 colocated in `src/`, 1 in `tests/`) for 95 production source files |
| Distinct socket owners | 5 `new WebSocket(` sites in 4 modules |
| Timer sites | 6 `setInterval`, 9 `setTimeout` |
| `JSON.parse` sites | 5, all followed by an unchecked `as` cast |

A single pass over that surface would (a) never reach Phase 8, (b) yield an unfalsifiable coverage
claim, and (c) break Phase 5's fix-interaction check — transport, reducer, API client and shell
fixes interact through the same `SessionViewState` and the same connection pool. **Therefore: nine
bounded runs**, each independently shippable, each with its own inventory. Completing W0–W4 and
stopping is an explicitly valid PARTIAL outcome under the protocol.

### 1.1 How to invoke a wave

Each wave is executed by handing an agent the V7.1 protocol text plus: this section §2 (Phase 0
census, verbatim), the wave's own block in §4, the wave's pre-seeded candidates from §7, and §5
(operating procedure). The wave's output goes to `tasks/audits/ui_defect_hunt_w<N>_<surface>.md`
(§8.1). Nothing else from this document changes between waves.

---

## ══════════════════════════════════════════ PHASE 0: ENVIRONMENT, ARCHITECTURE & SCOPE CENSUS ══════════════════════════════════════════

### 2.1 Static census [VF]

```
Language:        TypeScript 5.9.3 (strict), TSX; one PostCSS/Tailwind CSS file (src/app/globals.css)
Runtime:         Node v24.21.0 (dev/build host), npm 11.19.0
Framework(s):    Next.js 16.3.6 (App Router, Turbopack build), React 19.3.0, React DOM 19.3.0,
                 Tailwind CSS 4.3.3, @base-ui/react 1.8.0 via shadcn primitives, recharts 3.10.1,
                 date-fns 4.4.0, lucide-react, @monaco-editor/react, reactflow 11
Test framework:  vitest 3.2.7 + @testing-library/react 16 (jsdom 25, globals on, setupFiles: []);
                 @playwright/test 1.63.0 + @axe-core/playwright for browser tests
Entry point(s):  Next App Router. Route files: src/app/{page,layout,error}.tsx, src/app/(console)/layout.tsx,
                 src/app/(console)/sessions/[id]/page.tsx, src/app/{sessions,ops,models,behavior,settings,
                 settings/behavior,debug}/page.tsx, src/app/api/[[...path]]/route.ts (the API proxy)
Backend contract: http://localhost:8000 — REST /api/*, WS /ws/sessions/{id} (per session) and /ws
                 (global presence), SSE /api/events/stream (fallback), behavior socket /api/behavior/ws
Invariants:      PARTIALLY DOCUMENTED — weebot-ui/README.md §Source layout + §Conventions; eslint layer
                 rules; the six counters in tasks/quality/ceilings.toml; e2e specs assert one <main>,
                 one <h1>, no horizontal overflow, 44 px touch targets, axe AA
Build/lockfile:  weebot-ui/package.json + weebot-ui/package-lock.json (lockfileVersion 3); `npm ci`
                 installs 579 top-level package dirs cleanly
```

### 2.2 Architecture census

**Style:** layered frontend, unidirectional imports, React 19 function components [VF — source:
`weebot-ui/README.md` §Source layout + §Conventions, and the enforcement config below; not inferred
from layout].

**Layer map** [VF, same source]:

```
app/                     routes; compose only, own no logic
components/{shell,conversation,dock,command,dashboard,models,plan,code,common,behavior}
                         Weebot-specific composition
components/ui/           primitives (shadcn over base-ui); know nothing about Weebot
hooks/                   React bindings over lib/ and providers/
providers/               process-wide services: EventStream, Toast, Theme, Shell slots, Announcer
lib/                     pure TypeScript, no React
types/                   pure types (backend event mirror, Remote<T>)
```

**Dependency rule** [VF]: `components/ui/**` may import only `@/lib/utils`; `lib/**` may not import
`react`/`react-dom`; everything else points downward (routes → composition → hooks/providers →
lib/types).

**Enforcement tooling** [VF, three independent mechanisms]:

| Tool | Contract it enforces | Where |
|---|---|---|
| `eslint` + `no-restricted-imports` | the two layer rules above | `weebot-ui/eslint.config.mjs` (two config blocks) |
| `scripts/lint_ui_debt.py` | 6 structural counters, exact-equality ceilings | `tasks/quality/ceilings.toml:352-360`; run by `make lint-ui` |
| `scripts/check_ui_contrast.py` | 58 token pairs ≥ 4.5:1 in both themes | `make lint-ui` |
| `tsc --noEmit` (`strict: true`) | type-level consistency | `weebot-ui/tsconfig.json` |
| e2e (`shell`, `conversation`, `lists`, `a11y`, `perf`) | one `<main>`, one `<h1>`, reflow, focus, axe AA, JS budgets | `weebot-ui/e2e/*.spec.ts` |

There is **no** dependency-cruiser / import-linter / ArchUnit equivalent for TS, and **no** runtime
schema validation (zod is not a dependency) [VF]. Architecture conformance claims are therefore
enforced-or-[HYP] per line, exactly as the protocol requires.

**Dominant paradigms** [VF, one example each]:

| Paradigm | Example |
|---|---|
| Function components + hooks | `components/conversation/ConversationPane.tsx:54` |
| Pure reducer / event-sourcing projection | `lib/session-reducer.ts:41` |
| Facade + reference-counted resource pool | `providers/EventStreamProvider.tsx:126-231` |
| Discriminated union + one renderer for load state | `types/remote.ts`, `components/common/StateView.tsx:27` |
| Finite state machine for a UI flow | `lib/composer.ts:29-47` |
| Mediator (a11y announcements) | `providers/AnnouncerProvider.tsx:23` |
| Registries (rows, commands) | `components/conversation/EventRenderer.tsx:24`, `lib/commands/registry.ts:18` |
| Adapter (single API client) | `lib/api.ts:99-205` |

**Conventions** [VF]:

- **Errors:** thrown `Error` from the API client; `Remote<T>` error state on load paths;
  `console.warn`/`console.error` for non-fatal; no Result type; one route-level boundary
  (`src/app/error.tsx`).
- **Validation:** type-level only. Payloads are `JSON.parse`d and cast — 5 sites, no runtime checks.
- **Logging:** `console.*` only — 16 sites, no logger abstraction.
- **Async:** promises inside effects; no AbortController on REST calls; the only abort signal is the
  SSE fallback's.
- **Immutability:** reducers copy maps per event; `SessionViewState` fields are `Readonly`.
- **DI:** React context (5 providers) + one module singleton (`commandRegistry`).
- **Config:** storage keys are read inline in 5 modules (`weebot_backend_url`, `weebot_ws_url`,
  `weebot_api_key`, `weebot_theme`, `weebot_draft:*`). No accessor module.
- **Typing:** `strict: true`; one `any`; one non-null assertion (`lib/session-reducer.ts:137`).

**Invariant ownership** (protocol Phase 0 requirement — used by Phase 3b/5a):

| Invariant | Owner | Actually enforced? |
|---|---|---|
| one `<main>` per page, one `<h1>` per page | `AppShell` + each page | [VF] ratchet `ui_main_landmarks = 1`; e2e asserts both |
| every id in `displayOrder` resolves to a row | `lib/session-reducer.ts` | [VF] by construction, asserted with `!` at :137, not proven |
| a "Live"/"connected" indicator reflects the transport | `EventStreamProvider.getSessionMode`, ops caption | [HYP] two of three indicators never measure state (§7 D3) |
| every loaded surface is a `Remote<T>` rendered by `StateView` | hooks + `StateView` | [VF] for sessions/models; [HYP] for `/ops` (§7 D4) |
| the API key never leaves the tab | `lib/api.ts` | [VF] sessionStorage only; also sent as `?token=` on sockets (§7 O4) |
| the session list has one live source | `useSessionList` (rail) | [HYP] `/sessions` polls every 5 s in parallel (§7 D10) |
| layout survives navigation (rail does not remount) | `(console)/layout.tsx` | [VF] e2e `shell.spec.ts:113` |

### 2.3 Baseline — the hunt's control group

#### 2.3.1 Measured gates [VF], 2026-10-25

| Gate | Command | Result |
|---|---|---|
| install | `npm ci` (in `weebot-ui/`) | clean, 579 package dirs |
| typecheck | `npx tsc --noEmit` | **0 errors** |
| lint | `npm run lint` (`eslint src`) | **0 errors, 0 warnings** |
| unit + component | `npm test` (`vitest run`) | **12 files, 75 tests, all pass** (10.3 s) |
| build | `npx next build` | **OK**, 11 routes, compiled 21.8 s |
| UI debt ratchet | `python3 scripts/lint_ui_debt.py` | 6 counters at ceiling (`ui_main_landmarks` 1, rest 0) |
| contrast | `python3 scripts/check_ui_contrast.py` | 58 token pairs ≥ 4.5:1 in both themes |
| browser suite | `npx playwright test` | **BLOCKED — 76/76 failed at `browserType.launch`** |

**The browser failure is environmental, not a defect [VF].** Every one of the 76 tests fails before
navigating:

```
[pid=…][err] …/chrome-headless-shell: error while loading shared libraries: libnspr4.so:
             cannot open shared object file: No such file or directory
```

`npx playwright install chromium` succeeds (114 MB), but the binary cannot run: there is no root
(`sudo` is blocked by the container's *no-new-privileges* flag), `apt-get install` cannot take the
dpkg lock, and `apt-get download libnspr4` reports the package is not in any configured index. The
a11y, perf and interaction baselines are therefore **[BLOCKED]**, not red — see §8.2 for what must
happen on a host that has the libraries. No wave may report a browser check as passing until that
baseline exists.

#### 2.3.2 Test coverage by module [VF]

| Module group | Direct tests |
|---|---|
| `lib/session-reducer.ts` | 14 |
| `components/ui/*` (contract) | 21 |
| `components/common/*` | 8 |
| `lib/composer.ts` 6 · `lib/sessions.ts` 5 · `lib/scroll.ts` 5 · `lib/announce.ts` 3 · `lib/endpoints.ts` 2 | 21 |
| `providers/ToastProvider.tsx` 4 · `hooks/useRemote.ts` 3 · `hooks/useSessionEvents.ts` 2 · `tests/smoke.test.tsx` 2 | 11 |
| **`providers/EventStreamProvider.tsx`** | **0** (mocked out in `useSessionEvents.test.ts:11-20`) |
| **`lib/api.ts`**, **`app/api/[[...path]]/route.ts`**, **`components/ConnectionStatus.tsx`** | **0** |
| **`hooks/useSessionList.ts`, `useSessionPresence.ts`, `useBehavior.ts`, `useWebSocketDebug.ts`, `useStickToBottom.ts`, `useRegisterCommands.ts`, `useShellSlots.ts`** | **0** |
| **all page components** (`app/**/page.tsx`, including `ops`, `models`, `settings`, `debug`) | **0** |
| **`components/conversation/*`, `components/shell/*`, `components/dock/*`, `components/dashboard/*`** | **0** (only via e2e, which is [BLOCKED] here) |

**This is Phase 0's most important finding [VF].** The pure layer is well covered; the classes with
the highest threat — transport lifecycle, live-state truthfulness, error mapping — sit almost
entirely in the zero-test column, and their only independent check (e2e) cannot run in this
environment. Node-level `smoke.test.tsx` covers 2 assertions. Wave order in §4 follows from this,
not from file size.

### 2.4 Instrument audit

A hunt inherits the reliability of its detectors. Measured behaviour:

| # | Instrument | Measures | Blind spot it creates |
|---|---|---|---|
| **I1** | `eslint` layer rules | two import patterns (`@/hooks|@/lib|@/providers` from `ui/`; `react` from `lib/`) | Nothing about behaviour. Hook-dependency enforcement is whatever `eslint-config-next` leaves; today 0 warnings, with one file exempted by `eslint-disable-next-line react-hooks/exhaustive-deps` (`hooks/useRegisterCommands.ts:11`). |
| **I2** | `scripts/lint_ui_debt.py` | 6 **regex counts** over `src/`, test files excluded | Counts, not behaviour. `ui_main_landmarks = 1` is a ceiling over the *whole tree*, not per page, so it cannot detect a second `<main>` on one route. Comments are blanked before matching, so it cannot see intent. |
| **I3** | axe e2e | 7 routes × 2 themes × 2 widths, `wcag2a/2aa/21aa/22aa` | Filters to `serious`/`critical` only — `moderate` violations pass. `/debug` and `/settings/behavior` are not in `ROUTES` (`e2e/a11y.spec.ts:5`). Cannot run here [BLOCKED]. |
| **I4** | perf e2e | first-load JS per route, scripting per live event | Budgets encode 2026-10-24 numbers in a comment; cannot re-measure here [BLOCKED]. |
| **I5** | Unit harness | jsdom + testing-library | `setupFiles: []` — no `WebSocket`, no `IntersectionObserver`, no fake-timer convention. Nothing can currently test a socket or a reconnect. |
| **I6** | Type boundary | `tsc --strict` | Payloads are `as`-cast after `JSON.parse`, so shape drift from the Python models is invisible to the compiler. e2e `fixtures.ts` encodes the contract by hand and is not derived from `weebot/domain/models`. |
| **I7** | Ratchets | `ceilings.toml` exact equality both ways | Correct by construction; **no wave may raise a ceiling** (same rule as the Python plan). |
| **I8** | `make lint-map` | map/ + tasks/ index freshness, card citations | **Red on a clean checkout** [VF]: `scripts/check_map_citations.py --drift` reports **143 pre-existing drifted citations** in `map/*.md` (Python line numbers that moved). `gen_map_index --check` and `gen_tasks_index --check` pass. Unrelated to this frontend and to any wave — do not attribute it to a fix, and do not "repair" it inside a UI change. |

### 2.5 Threat model, ranked

T2 and T3 rank above a naive reading of blast radius because this is an **operations console**: its
entire value is that what it shows is true.

| Rank | Threat | Why it ranks here |
|---|---|---|
| **T1** | **Credential exposure** — the API key lives in `sessionStorage` and is also appended as `?token=` to three socket URLs; the Next proxy logs `console.error` on failure paths | Externally visible; the console is often bound to a LAN address |
| **T2** | **Silent wrong state** — the UI asserts "Live", "connected", "sent", "healthy" while the underlying path is dead | The failure mode the Python hunt found dominant ("wired up, looks present, reports success, does nothing") |
| **T3** | **Event loss / duplication / ordering** — reconnect replay, SSE fallback, history refetch, dedupe by id | A lost event is indistinguishable from a step that never happened |
| **T4** | **Silent non-execution** — a task that never starts, shown as sent or complete | Money-adjacent: the user waits for work that is not running |
| **T5** | **Liveness** — stuck spinner, permanently dead socket, poll storms, double submit | An ops console that hangs reads as "the agent is busy" |
| **T6** | **Resource lifecycle** — sockets, timers and listeners across StrictMode double-mount, route change, session switch | Long-lived console sessions are the normal usage |
| **T7** | **Interaction data loss / a11y** — drafts, deletes that do not converge, keyboard traps, reflow at 375 px | The user's only control surface |

### 2.6 Defect taxonomy, instantiated for this frontend

C1–C10 are the protocol's default catalogue, re-worded, plus **C10**, which this codebase earns (see
T2 and §2.3.2). Waves declare which classes they hunt; the union is the program's coverage claim.

| # | Class | Frontend instantiation | Threats |
|---|---|---|---|
| C1 | Boundary & arithmetic | empty/singleton collections, index/slice, `NaN`/`0` into charts and percentages, `toFixed`, `parseInt`, unseen-count arithmetic, `activeIndex` bounds | T5 |
| C2 | Resource lifecycle | WebSocket / SSE reader / timer / listener acquire-without-release; reconnect timers; StrictMode double mount; route-change teardown | T6 |
| C3 | Concurrency | stale closures, out-of-order async resolution, check-then-act on connection state, double submit, socket + poll racing on the same state | T3, T5 |
| C4 | Error & exception paths | swallowed `catch`, catch that returns a success-shaped value, an error path that itself throws, partial state on failure | T2, T4 |
| C5 | Trust-boundary / input | key storage and transmission, `dangerouslySetInnerHTML`, storage-driven URLs, unvalidated payloads, clipboard | T1 |
| C6 | Type & serialization | `as`-casts on `JSON.parse`, union drift with the backend event model, `as Session["status"]`, `undefined` inside a render union | T2, T3 |
| C7 | State machine | composer phases, connection modes, session status transitions, illegal combinations | T4, T5 |
| C8 | Contract / dependency | backend payload shapes (`SessionResponse`, health, plan-viz, cost summary), base-ui emitted attributes, recharts edge inputs, Next proxy semantics, hand-written fixtures drifting from Python models | T2, T3 |
| C9 | Architecture-conformance | layer rule violation, abstraction bypass (`fetch` outside `lib/api.ts`, raw colour instead of a token), a page owning logic, two sources of truth, the `<main>`/`<h1>` invariant | T2, T7 |
| **C10** | **Fail-open signalling** *(added)* | any indicator that asserts a state the code never measures: a hard-coded "WebSocket connected", a mode that is never reset, `isConnected` set true by the first event and never cleared, a health/status vocabulary that does not match the endpoint's | **T2** |

### 2.7 Scope, budget, blocking check

**In scope:** all of `weebot-ui/src/**` (106 files), `weebot-ui/e2e/**`, `weebot-ui/next.config.mjs`,
`weebot-ui/eslint.config.mjs`, `weebot-ui/tsconfig.json`, and — as *instruments* — 
`scripts/lint_ui_debt.py`, `scripts/check_ui_contrast.py`, `tasks/quality/ceilings.toml`.

**Out of scope, with reasons:**

| Excluded | Reason |
|---|---|
| `weebot/`, `cli/` (Python) | Already hunted by `defect_hunt_v7_execution_plan.md`. Read **only** as contract evidence for C8 (e.g. what `/health` really returns). A defect found there is `[REQUIRES HUMAN REVIEW: owner is the backend]`, never a UI fix. |
| `weebot-ui/node_modules/`, `.next*`, `test-results/`, `playwright-report/` | Generated |
| `weebot-ui/public/` | Static assets, no logic |
| root `package.json` (`@openrouter/*`) | Unrelated to the frontend; `next.config.mjs` pins the Turbopack root to `weebot-ui` [VF] |
| `website_copy/`, `Output/`, `Useful Github Projects/`, `_archive/` | Not the product frontend |

**Budget — three independent counters, per the protocol:**

- `budget_spent` — per wave: **≤ 15 candidates generated, ≤ 10 investigated to verdict, ≤ 5 verified
  defects fixed**. Program ceiling: 135 / 90 / 45. A wave that hits its ceiling emits its coverage
  statement and stops; the rest of the surface becomes an explicit `UNKNOWN` remainder.
- `hunt_iterations` — cap **3** per region tier (Phase 4 → Phase 2 expansion). Exhausting it advances
  the queue; it does not abort the wave.
- `fix_revisions` — cap **1** per defect. Exceeding ⇒ `[REQUIRES HUMAN REVIEW]`.

**Blocking condition check:** runtime ✅ (Node 24.21.0), entry points ✅ (11 routes), scope ✅
bounded, source ✅ present, architecture ✅ documented-and-enforced. **No Phase 0 blocker.** One
capability blocker exists for Phase 3's browser triggers (§8.2) — it narrows *how* a defect can be
proven, it does not stop the hunt.

---

## 3. Approach selection

Three materially different organisations were considered.

**A — Risk-ranked surface waves** (bound each wave to one subsystem; full V7.1 loop per wave).
*Assumes* defects cluster by mechanism. *Strength:* each wave is one reviewable PR; the fix-interaction
check stays tractable because interacting fixes are co-located. *Weakness:* cross-cutting defects
(the same key storage read in five modules) fall between waves — mitigated by W8.

**B — Taxonomy-horizontal sweeps** (all resource-lifecycle everywhere, then all state machines…).
*Strength:* the strongest possible per-class coverage statement. *Weakness:* 8.5k lines makes it
tempting, but its PR shape still violates the ≤15-line/≤1-function fix constraint at aggregate scale,
and re-running the same surface 10 times multiplies cost without a stronger claim, because most
classes here are behavioural, not syntactic.

**C — Instrument-first / signal-only** (repair and extend the detectors, hunt where they fire).
*Strength:* every candidate is pre-grounded, and it terminates. *Weakness:* **structurally blind to
C10** — no linter detects "this indicator never measures what it claims" — which §2.5 ranks second.
It is also blind to all socket behaviour while the e2e suite is unrunnable here.

**Recommendation: A as the engine, C as W0, B inside each wave.** C cannot lead (it would miss every
C10 and C3 candidate in §7); it must go first, because §2.3.2 shows the tests that could have caught
those candidates do not exist. B is excellent *within* a bounded wave: walking C1→C10 over one wave's
files is what makes its coverage statement defensible per class rather than anecdotal.

**Rejected outright:** one V7.1 pass over the whole frontend — it cannot terminate and cannot produce
an honest coverage statement (§1).

---

## 4. The wave plan

Execution order is the table order. `hunt_priority ≈ likelihood × blast_radius × reachability`, with
one deviation from pure scoring: **W0 is a precondition, not a hunt** (§2.4), and W1 goes first among
hunts because T2/T3 sit on the product's core promise and on the largest zero-test surface.

| Wave | Surface | Classes | Threats | Seed candidates |
|---|---|---|---|---|
| **W0** | Instruments & baseline | — (repair, not hunt) | precondition | none |
| **W1** | Transport & live-state integrity | C2, C3, C7, C10 | T2, T3, T5, T6 | D1, D2, D9, D12, D13 |
| **W2** | Conversation timeline & projection | C1, C6, C7, C8 | T3, T5 | D11 |
| **W3** | Composer & send path | C4, C7, C3 | T2, T4 | D7 |
| **W4** | API client, proxy & credentials | C4, C5, C6, C8 | T1, T2 | D4, D5 |
| **W5** | Data surfaces & polling | C1, C3, C4, C10 | T2, T5 | D3, D8, D10 |
| **W6** | Shell, providers & navigation | C2, C3, C7, C9, C10 | T5, T6, T7 | D6, D14 |
| **W7** | Primitives & design contracts | C8, C9 | T7 | none (structural) |
| **W8** | Seams & fix-interaction | cross-cutting | all | none |

**Re-ranking rule:** if a W4 candidate (credentials/proxy) confirms at HIGH or CRITICAL, execute W4
immediately after the defect is verified rather than at its table position — the protocol ranks by
severity × reachability, not by this table. Record the re-rank in the wave report.

---

### W0 — Instruments & baseline *(precondition, not a hunt)*

**Why first:** six of the ten classes below are behavioural, and §2.3.2 shows the harness cannot
express them: no WebSocket stub, no fake-timer convention, `setupFiles: []`, and the one suite that
could catch them cannot launch a browser here.

| Item | Action | Exit evidence |
|---|---|---|
| B0 | Commit this plan's measured baseline (§2.3.1) to `tasks/audits/ui_defect_hunt_baseline.md`. | file exists, numbers match Appendix A |
| H1 | Add a **fake WebSocket + fake SSE stream** helper under `weebot-ui/src/test/` (or the existing `tests/` dir) usable by `renderHook`; add it to `vitest.config.ts` `setupFiles` only if it is inert by default. | one throwaway harness test passes; no production file touched |
| H2 | Adopt `vi.useFakeTimers()` for reconnect/backoff tests (document the pattern in the harness file's header). | one reconnect test advances time deterministically |
| H3 | Establish the **browser baseline** on a host that can run Playwright (CI job or local): `npx playwright install-deps chromium && npm run test:e2e`. Record pass/fail per spec, the axe findings and the two perf numbers. | baseline row filled in §2.3.1 in the audit file, or `[BLOCKED]` restated with the host used |
| H4 | Confirm `npm run test:e2e` is actually exercised in CI; if not, say so in the audit file (this is an instrument finding, not a wave deliverable). | one line of evidence |
| H5 | No new lint rule, no new dependency, unless H1–H2 provably need one. `next build` must stay green. | `npm test && npm run lint && npx tsc --noEmit && npx next build` |

**Budget:** no candidate budget; bounded by H1–H5. **No production behaviour may change in W0.**

---

### W1 — Transport & live-state integrity *(T2, T3, T5, T6 · C2, C3, C7, C10)*

**Surface:** `providers/EventStreamProvider.tsx` (307 lines) · `hooks/useSessionEvents.ts` ·
`hooks/useSessionPresence.ts` · `hooks/useSessionList.ts` · `hooks/useBehavior.ts` ·
`hooks/useWebSocketDebug.ts`.

**Phase 1 hunt queue** (highest priority first):

| R | Region | Why it ranks |
|---|---|---|
| R1 | `EventStreamProvider.startSessionSSE` (:107-190) and the WS→SSE fallback (:177-188) | The only path that ever runs when the backend is behind a proxy that blocks WS; end-of-stream is unhandled |
| R2 | per-session connection lifecycle: `subscribeSession` (:206-231), `closeSessionConnection` (:95-105), teardown effect (:287-293) | SYSTEM blast radius; C2/C3; StrictMode double-mount |
| R3 | global presence connection (:233-280) | Feeds the rail's only live update path; exhaustion is silent |
| R4 | `useSessionEvents` connection reporting (:36-51) | The AppBar "Live"/"Offline" dot is derived here — a C10 surface |
| R5 | `useSessionList` presence merge (:15-71) | Applies an open-string status (`:23`) into a closed union |
| R6 | `useBehavior` (:48-160) | Second socket stack with its own reconnect policy and four `console.log`s |
| R7 | `useWebSocketDebug` (:22-105) | Dev-only route; low blast radius, useful as a control case |

**Seeds:** D1, D2, D9, D12, D13. **Budget:** ≤15 / ≤10 / ≤5.
**Exit criteria:** at least one of D1/D2/D9/D12/D13 taken to a verdict with an executable trigger (fake
WebSocket, fake timers, or a Playwright stream fixture); the connection-mode vocabulary documented in
the wave report; `getSessionMode`'s observable states enumerated.

---

### W2 — Conversation timeline & projection *(T3, T5 · C1, C6, C7, C8)*

**Surface:** `lib/session-reducer.ts` (139) + its 14 tests · `lib/announce.ts` · `lib/scroll.ts` ·
`hooks/useStickToBottom.ts` · `components/conversation/{ConversationPane,EventRenderer,MessageRow,
ToolCallRow,StepRow,GapMarkerRow,StatusEventRow}.tsx` · `components/PlanReviewCard.tsx` ·
`components/plan/*`.

**Hunt queue:** the reducer's display-order/dedupe contract (R1); the history-refetch effect in
`ConversationPane.tsx:72-90` (R2); `getDisplayItems`'s `event!` (:126-138) (R3); the render registry's
silent drops (`EventRenderer.tsx:24-33`) (R4); truncation/copy in `ToolCallRow` (R5); the
`useStickToBottom` at-bottom/unseen arithmetic (R6).

**Seeds:** D11. **Budget:** ≤15 / ≤10 / ≤5.
**Exit criteria:** a property-level statement of what the reducer guarantees (dedupe, order, gap
markers) and a test per guarantee that would fail if the guarantee were removed.

---

### W3 — Composer & send path *(T2, T4 · C4, C7, C3)*

**Surface:** `lib/composer.ts` + 6 tests · `hooks/useComposer.ts` · `components/conversation/Composer.tsx`
· `components/conversation/MessageRow.tsx` · `ConversationPane`'s retry plumbing (`retryRef`/`registerRetry`).

**Hunt queue:** `deliver`'s create→run split (:72-99) (R1); draft persistence (:18-45) (R2); the
retry path reusing an event id as `client_msg_id` (:118-126) (R3); `submit`'s optimistic row vs. the
server echo (:103-116) (R4); the never-disabled box vs. double Enter (:140-147) (R5).

**Seeds:** D7. **Budget:** ≤15 / ≤10 / ≤5.
**Exit criteria:** the phase × delivery matrix (idle/sending/failed × sending/sent/failed) written out
and every cell either covered by a test or marked impossible.

---

### W4 — API client, proxy & credentials *(T1, T2 · C4, C5, C6, C8)*

**Surface:** `lib/api.ts` (205) · `app/api/[[...path]]/route.ts` · `lib/endpoints.ts` ·
`components/ConnectionStatus.tsx` · `hooks/useComposer.ts:31` (the guarded uuid) as a comparison point.

**Hunt queue:** error classification (`api.ts:56-67`) (R1); the server proxy's body/status/header
handling (`route.ts:27-38`) (R2); key storage and transmission (`api.ts:19-39`,
`ConnectionStatus.tsx:22-45, 66-88`) (R3); base-URL precedence across `api.ts:3-16`,
`EventStreamProvider.tsx:70-84`, `ops/page.tsx:38-42` (R4) — three readers of the same two storage
keys with different fallbacks; `endpointsFrom`'s `/ws` suffix stripping (R5).

**Seeds:** D4, D5. **Budget:** ≤15 / ≤10 / ≤5.
**Exit criteria:** a written table of {storage key → readers → precedence}; one test proving the proxy
preserves a non-JSON/204 upstream response *or* a `[HYP]`-cleared note that no such route exists.

---

### W5 — Data surfaces & polling *(T2, T5 · C1, C3, C4, C10)*

**Surface:** `hooks/useRemote.ts` · `app/sessions/page.tsx` · `app/ops/page.tsx` (437 — the largest
file) · `app/models/page.tsx` · `app/settings/{page,behavior/page}.tsx` · `app/debug/page.tsx` ·
`components/dashboard/{CostChart,MetricsPanel}.tsx` · `components/models/RoleModelsPanel.tsx` ·
`components/behavior/*`.

**Hunt queue:** `useRemote` request ordering (:17-56) (R1); `/ops` live-log socket and its hard-coded
caption (:65-83, :326) (R2); `/ops` health/status vocabulary (:43-49, :187-215) (R3);
`fetchData`/`fetchActiveSessions` interval with no cancellation (:93-129) (R4); chart inputs at zero
rows / one row / zero total (`CostChart`) (R5); `PlanVizTab`'s `if (result.ok)` with no else (:372-400)
(R6); `/models` role writes (:1-167) (R7).

**Seeds:** D3, D8, D10. **Budget:** ≤15 / ≤10 / ≤5.
**Exit criteria:** every page in the wave either uses `Remote<T>` + `StateView` or carries a written
justification in the report; no page left with an unexamined polling loop.

---

### W6 — Shell, providers & navigation *(T5, T6, T7 · C2, C3, C7, C9, C10)*

**Surface:** `components/shell/{AppShell,AppBar,ConsoleShell,SessionRail,ResponsivePanel}.tsx` ·
`providers/{Toast,Theme,Shell,Announcer}Provider.tsx` · `components/command/CommandPalette.tsx` ·
`lib/commands/registry.ts` · `hooks/{useShellSlots,useRegisterCommands}.ts` · `app/layout.tsx` ·
`app/error.tsx`.

**Hunt queue:** `useShellSlots`' set/clear ordering across concurrent pages (:9-16) (R1);
`useRegisterCommands`' id-only dependency (:9-13) (R2); `CommandPalette`'s `activeIndex` against a
shrinking list (:54, :80-93) (R3); `ToastProvider`'s id generation and timer (:55-70) (R4);
`ThemeProvider` vs. the pre-hydration init script (:22-45, `app/layout.tsx:24`) (R5); the rail's
mobile sheet + focus return (R6).

**Seeds:** D6, D14. **Budget:** ≤15 / ≤10 / ≤5.
**Exit criteria:** shell-level invariants (one `<main>`, one `<h1>`, skip link, focus return) restated
as properties with a test each, so W7 can treat them as parents rather than re-deriving them.

---

### W7 — Primitives & design contracts *(T7 · C8, C9)*

**Surface:** `components/ui/*` (18 files) · `components/ui/primitives.contract.test.tsx` ·
`app/globals.css` · instruments `scripts/lint_ui_debt.py`, `scripts/check_ui_contrast.py`.

**Hunt queue:** the primitive↔attribute contract (:24-67 in the contract test) (R1); `Dialog`
close/focus behaviour under nesting (R2); `Select`/`DropdownMenu` keyboard paths (R3); `ScrollArea`
viewport ref plumbing used by the timeline (R4); token coverage for states the contrast script does
not walk (disabled/placeholder) (R5).

**Budget:** ≤15 / ≤10 / ≤5. **No ceilings may change.**
**Exit criteria:** every primitive the composition layer relies on has either a contract assertion or
a written `[UNK]` (browser-only) note.

---

### W8 — Seams & fix-interaction *(+ program verdict)*

**Surface:** the seams W1–W7 do not own:

- three live-transport owners (`EventStreamProvider`, `ops/page.tsx`, `useBehavior`), each with a
  different reconnect policy and a different notion of "connected";
- five readers of the two backend URL keys with three different fallbacks;
- the session-status vocabulary in four places (`StatusBadge`, `SessionRail.isActive`, `Composer`'s
  `MODE_LABEL`, `applyPresence`'s cast);
- the two sources for the session list (rail via presence; `/sessions` page via 5 s poll).

**Work:** run the Phase 5 fix-interaction check across all waves; flag any two fixes touching shared
state; produce the program coverage statement (§8.3); propose (do not implement) consolidations that
are refactors rather than fixes.

**Budget:** no new candidates beyond interaction effects.

---

## 5. Per-wave operating procedure (Phases 1→8, adapted)

### Phase 1 — defect-surface map

For each file in the wave's surface, emit:

```
R[N]: [file:function or hook]
Layer: [app | components | components/ui | hooks | providers | lib | types]
Defect classes present: [C…]
Entry reachability: REACHABLE from [route] via [user action / socket frame] / GUARDED / UNKNOWN / DEAD
Blast radius: LOCAL / MODULE / SYSTEM / EXTERNALLY-VISIBLE  (EXTERNALLY-VISIBLE = data leaves the tab)
Invariant density: [count of preconditions the region assumes]
Invariant owner: [from §2.2 ownership table, or UNK]
```

Score `hunt_priority ≈ likelihood (static smell strength) × blast_radius × reachability`. Always state
≥3 atomic assertions about the map and classify them; record reachability honestly — a
`GUARDED`/`DEAD` region is deprioritised, never deleted from the report.

### Phase 2 — suspicion generation

Candidate format is the protocol's, with three frontend-specific requirements:

1. **Name the property**, not the code smell. "`mode` still reads `sse` after the stream ends, so the
   badge asserts a live subscription that does not exist" — not "SSE fallback looks fragile".
2. **Name the route or frame** that reaches it: `GET /sessions/sess-1` → provider fallback, or
   socket frame delivered to `subscribeSession`'s listener.
3. **Name the innocence path** at generation time (what would clear it: a guard, an upstream owner, an
   unreachable branch, a backend that never emits that shape).

### Phase 3 — proof of defect

Dual, per candidate. Trigger recipes, in order of preference for this stack:

| # | Trigger | Use for | Notes |
|---|---|---|---|
| 1 | `vitest` + `renderHook`/RTL, pure modules | C1, C4, C6, C7 in `lib/` | Fastest; no browser |
| 2 | `vitest` + fake timers + fake `WebSocket` (W0 H1/H2) | C2, C3, C10 in providers/hooks | Must assert the timer/close/listener ledger, not just the visible state |
| 3 | `vitest` + `vi.stubGlobal('fetch', …)` / mocked `Response` | C4, C5, C6, C8 in `lib/api.ts`, proxy route | The proxy route is a plain async function; call it directly with a `NextRequest` |
| 4 | Playwright spec against `e2e/fixtures.ts` `mockBackend` | C10, C3, C9 that only exist in the DOM (indicator labels, tab order, reflow) | **Requires a browser-capable host** (§8.2) |
| 5 | Playwright + `page.routeWebSocket` / a finite SSE route | reconnect, fallback, dead-stream | Currently blocked here |

Non-determinism (reconnect races, out-of-order responses, StrictMode double invoke): a single run
proves nothing. Use N ≥ 100 iterations or deterministic interleaving (fake timers + explicit resolve
order) and report a **rate**, labelled STATISTICAL, never deterministic [VF].

**Innocence attempt is mandatory and adversarial:** guard defence → reachability defence → invariant
defence → contract-owner defence. If the owning layer fails to enforce, the defect is re-homed to the
owner (usually: the Python route/response model, or a provider) and *this* site is recorded
CODE-INNOCENT. Two of the seeds in §7 (D4's health-vocabulary half, D9's cast) may legitimately clear
this way; that is a valid, expected outcome, not a failed hunt.

### Phase 4 — triage

Inventory table exactly as the protocol specifies (`Candidate | Trigger | Innocence | Evidence basis |
Status`), plus one frontend column: **`user-visible consequence`** (what the person at the console
sees). Only `VERIFIED DEFECT` rows continue to Phase 5.

### Phase 5 — fix design

**5a Placement.** The fix goes where the violated property is owned (§2.2 table). Common outcomes in
this codebase, in order:

1. **the provider/hook that owns the state** (`EventStreamProvider`, `useRemote`, `useSessionList`) —
   owner-justified;
2. **the boundary that receives the payload** (`lib/api.ts`, the proxy route) — for C6/C8, because
   runtime validation belongs at the boundary, not in a component;
3. **the component that asserts the fact** — only for C10 display fixes, and only when the state it
   needs is already exposed.

Never add a redundant guard lower down to mask an owner-layer contract failure. `DEFENSE-IN-DEPTH` is
permitted only when the owner fix is emitted or escalated in the same report.

**5b Mechanism — decision ladder, stop at the first rung that applies:**

1. Reuse an existing idiom: the pure reducer, `Remote<T>` + `StateView`, the connection pool, the
   command registry, base-ui `Dialog`.
2. Plain local fix matching the surrounding paradigm: `lib/` stays pure and React-free (I1 enforces);
   a component stays a component; no new side effects in `lib/`.
3. A new pattern only if (i) the defect class recurs ≥2× in the audited surface, (ii) the pattern is
   idiomatic to React/TS, (iii) no existing mechanism covers it, (iv) the diff still meets 5c.
   Otherwise `[PATTERN-NOT-WARRANTED]`.

Class → mechanism guidance: C2 → release in the same effect's cleanup (or the pool's existing
`closeSessionConnection`), never an ad-hoc `close()`; C3 → remove shared mutable state or derive from
a single source, prefer that over adding a lock/flag; C4 → narrow the `catch` and surface through the
existing error path (toast or `Remote`), never a new empty `catch`; C5/C6 → validate at `lib/api.ts`
or the proxy, not inside a component; C7 → guard the transition in the reducer; C8 → thin adapter in
`lib/api.ts`; C9 → route the call through the existing abstraction (`lib/api.ts`, `lib/utils`, the
token scale); C10 → make the indicator read the state (or delete the claim).

**5c Conformance gate (hard):** no layer-rule violation (`eslint` blocks 1–2); no new `fetch` outside
`lib/api.ts`; no `react` import in `lib/`; no new global mutable state; no ceiling change in
`tasks/quality/ceilings.toml`; public interfaces unchanged — for this codebase that means **exported
component props, exported hook return shapes, `lib/api.ts` method signatures, and the unions in
`types/events.ts`**. Widening/narrowing an event type is a public change →
`[REQUIRES HUMAN REVIEW: public interface change]`. Evidence: `npm run lint && npx tsc --noEmit &&
npm test` green on the changed tree.

**Hard constraints:** ≤ 15 changed lines and ≤ 1 function/component per defect. JSX churn counts
against the line budget; if a correct fix cannot fit, emit **both** a MINIMAL variant (labelled with
what it masks) and an ARCHITECTURAL variant marked `[REQUIRES HUMAN REVIEW]`, and recommend one with
reasons. Cross-file mechanism → `[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`. A defect in
Next/base-ui/recharts → `[REQUIRES HUMAN REVIEW: defect in dependency X@version]` plus an in-code
mitigation in this project's wrapper (`components/ui/*`, `lib/api.ts`).

### Phase 6 — RAR self-review, eight vectors adapted

| # | Vector | Frontend-specific question |
|---|---|---|
| 1 | Boundary | empty list, one row, 0/NaN in a chart or percentage, `event_count` 0, unseen-count 0 |
| 2 | Invalid input | `null`/`undefined` payload fields, malformed JSON frame, unknown event `type`, unknown status string, non-JSON response |
| 3 | State | provider partially initialised, socket mid-flight, **StrictMode double mount**, remount on session switch, tab backgrounded then foregrounded |
| 4 | Regression | the e2e suite (375/768/1280, axe, perf budgets) and `make lint-ui` exact-equality counters unchanged |
| 5 | Concurrency | two subscribers to one session, socket + poll updating the same state, out-of-order fetch resolution, double submit, retry while a send is in flight |
| 6 | New defect | re-run C1–C10 over the changed file only |
| 7 | Architecture conformance | layer rules, no new `fetch` outside the client, no React in `lib/`, no raw colour where a token exists, no second `<main>`/`<h1>`, no invariant ownership moved without saying so |
| 8 | Paradigm consistency | pure stays pure, providers stay mediators, loads stay `Remote<T>`, no state library, no pattern introduced without the 5b gate |

Tag the verdict: `FIX HOLDS [VF]` only with an executed test or a green gate run; `FIX HOLDS [HYP]`
when reasoned; `FIX BREAKS`; `CANNOT DETERMINE` (record as residual risk). One revision max, then
`[REQUIRES HUMAN REVIEW: attack vector unsolvable within constraints]`.

### Phase 7 — regression & proof tests

Conventions to follow exactly (they already exist; do not invent a new style): colocated
`*.test.ts(x)` beside the module for `lib/`, `hooks/`, `providers/`, `components/ui/`; `tests/` for
cross-module smoke; `e2e/*.spec.ts` with `mockBackend` from `e2e/fixtures.ts` for anything that needs
a real DOM/socket. Every verified defect emits:

1. **proof-of-defect** — fails at HEAD, passes with the fix (name the property in the docstring);
2. **≥2 boundary cases** from Phase 6 vector 1 or 2;
3. **a no-regression case** — an existing behaviour still passes;
4. **conformance evidence** — the exact command and its output (`eslint`, `tsc`, `vitest`, and where
   runnable `playwright`).

If the fixture is missing (C10/C3 in a provider), build it in W0's harness — not inside the fix.

### Phase 8 — verdict

Use the protocol's two checklists verbatim (five process checks, six engineering checks), then the
mandatory coverage statement (§8.3) and the uncertainty acknowledgment (§9). Routing: all ✅ →
ACCEPT; process ❌ → RE-ITERATE; engineering ❌ with written justification → ESCALATE; budget
exhausted with untriaged surface → PARTIAL.

---

## 6. Phase-1 region seed map (whole surface)

Complete inventory, so no wave has to rediscover it. `R` numbers are local to each wave (§4).

| Group | Files | LOC | Notes |
|---|---|---|---|
| Transport | `providers/EventStreamProvider.tsx` | 307 | 2 sockets per session + 1 global; WS→SSE fallback |
| | `hooks/useSessionEvents.ts` 57 · `useSessionPresence.ts` 26 · `useSessionList.ts` 63 · `useBehavior.ts` 252 · `useWebSocketDebug.ts` 107 | 505 | `useBehavior` is a second, independent socket stack |
| Projection | `lib/session-reducer.ts` (+14 tests) 139 · `lib/announce.ts` 26 · `lib/scroll.ts` 23 | 188 | pure, well covered |
| Conversation | `components/conversation/*` (9 files) | 673 | zero direct tests |
| Compose | `lib/composer.ts`, `hooks/useComposer.ts`, `components/conversation/Composer.tsx` | 47+130+157 | state machine is tested; the send path is not |
| API | `lib/api.ts`, `app/api/[[...path]]/route.ts`, `lib/endpoints.ts` | 205 + 50 + 33 | error mapping + proxy; zero tests |
| Pages | `app/**/page.tsx` (10 files) | 1,276 | `ops` 437 is the largest file in the repo's UI |
| Chrome | `components/shell/*` (5) 480 · `components/command/*` 125 · `providers/*` (5) 652 | 1,257 | shell invariants live here |
| Primitives | `components/ui/*` (18) + contract test | 1,356 | base-ui attribute contract |
| Visualisation | `components/dashboard/*` 269 · `components/plan/*` 199 · `components/code/*` 65 · `components/PlanReviewCard.tsx` 51 | 584 | recharts/Monaco edge inputs |
| Types | `types/events.ts`, `types/remote.ts` | 156 + 17 | the backend mirror; drift surfaces here |

---

## 7. Pre-seeded candidate register

**Status of every row: `[HYP]`.** These are seeds for Phase 2 — mechanisms that a static read of the
current code makes plausible, with the observation that would clear them. None has been triggered, so
none is a finding yet. The protocol's rule applies: inventing a defect from a smell is as much a
failure as missing one.

| ID | Location | Class | Claimed violated property | Prior · severity if real | Innocence path (what would clear it) |
|---|---|---|---|---|---|
| **D1** | `providers/EventStreamProvider.tsx:107-190` | C2, C10 | "the connection indicator reflects a live subscription": `startSessionSSE` sets `mode = "sse"` (:109) and nothing restores, retries or closes that mode when the stream ends (`done`) or throws (`catch {}` :145-148) — while `getSessionMode` keeps returning `"sse"` and `useSessionEvents.ts:44-48` polls it into `isConnected = true` | HIGH · **HIGH** — the console silently stops receiving events and still says Live | If some other consumer re-subscribes on a mode change (it does not: the effect deps are stable), or if the backend never ends an SSE stream (verify against the `/events/stream` implementation) |
| **D2** | `providers/EventStreamProvider.tsx:250-262` | C10, C2 | "a permanently degraded live path is visible": the presence socket stops reconnecting after `MAX_RECONNECT_ATTEMPTS` (:257) with no fallback and no state change, and `presenceReconnectRef` is only reset inside `onopen` (:246-249) | MEDIUM · MEDIUM — the rail silently stops updating for the life of the tab | If giving up is a deliberate, documented degradation (it is not documented) — then it is an OBSERVATION, not a defect |
| **D3** | `app/ops/page.tsx:65-83, 326` | C10 | "a status caption is derived from state": the Live Events tab renders the literal `WebSocket connected` with no `onopen`/`onclose`/`onerror` handler and no reconnect; the socket is never re-created after a drop, and failures are invisible | HIGH · MEDIUM — an ops console asserting connectivity it never checked | If an outer provider guarantees the socket (it does not — this page opens its own at :69) |
| **D4** | `lib/api.ts:56-67` | C4, C6 | "the error surfaced to the user names the actual failure": a server `detail` containing the substrings `fetch` or `connect` (:56-64) is reclassified as a connection failure and replaced with "Cannot connect to backend…", masking the real cause and giving the wrong remediation | MEDIUM · MEDIUM | If no backend `detail` can contain those substrings (unverified — `[UNK]`) |
| **D4b** | `app/ops/page.tsx:43-49` vs `weebot/interfaces/web/routers/health.py:56,74` | C8, C10 | "status vocabulary matches the endpoint's": `HEALTH_DOT`/`HEALTH_TEXT` key on `healthy`/`degraded`; `/health` indeed returns `healthy`/`degraded`, but a component row can carry `not initialized` / `no active caches` (`health.py:401,425`), which fall through to the error styling | LOW · LOW | **Likely CODE-INNOCENT**: overall status is `healthy`/`degraded`; only per-component rows mismatch. Verify with one request before filing |
| **D5** | `app/api/[[...path]]/route.ts:27-38` | C8, C6 | "the proxy preserves upstream semantics": `await response.json().catch(() => null)` (:35) then `NextResponse.json(null, {status})` (:37) rewrites any non-JSON body — and a 204/205 upstream cannot legally carry a body — while all headers except `content-type`/`x-api-key` are dropped and the body is fully buffered | MEDIUM · MEDIUM | If every proxied route returns JSON and none uses 204 (`[UNK]` — only `sessions` and `health` were checked) |
| **D6** | `providers/ToastProvider.tsx:60` | C5, C8 | "a toast cannot fail on a capability gap": `crypto.randomUUID()` is unguarded, unlike the identical call in `hooks/useComposer.ts:31` which guards it — in a non-secure context (`http://<lan-ip>:3000`, the normal way a self-hosted console is opened) `randomUUID` is undefined and every error toast throws | MEDIUM-HIGH · MEDIUM — error reporting crashes exactly when something is already wrong | If the app is contractually only served from `localhost`/HTTPS (not documented) |
| **D7** | `hooks/useComposer.ts:72-99` | C4, C7 | "a task that did not start is not shown as sent": when `api.sessions.create` succeeds but `run` fails (:79-84), delivery is settled `"sent"` and the session opens with only a `console.warn` — the row is marked sent, no toast, and the retry path is gone because the row is settled | MEDIUM · MEDIUM (recoverable: the opened session shows `pending` and accepts input) | If opening the session is a sufficient, designed recovery (the code comment claims so) — then severity drops, the silent `console.warn` stays an OBSERVATION |
| **D8** | `hooks/useRemote.ts:17-56` | C3 | "the newest response wins": every poll/`reload` starts a request with no generation counter or abort; two overlapping requests can resolve out of order and an older payload overwrites a newer one — visible as a list that jumps backwards | MEDIUM · MEDIUM | If `load` were effectively serialised (it is not — `setInterval` fires while a request is in flight) |
| **D9** | `hooks/useSessionList.ts:23` | C6, C8 | "the session status is a member of the documented union": `update.status as Session["status"]` casts from `SessionPresenceEvent["status"]` (`types/events.ts`, `… \| string`) — an unknown status from a newer backend enters the closed union, then `StatusBadge`/`SessionRail.isActive` (`components/shell/SessionRail.tsx:14-16`) mis-handle it silently | MEDIUM · MEDIUM | If the backend provably emits only the five documented values — verify in the Python event emitter; then CLEARED and the note belongs at the type boundary |
| **D10** | `app/sessions/page.tsx:24` + `hooks/useSessionList.ts:43-53` | C9, C7 | "one source of truth for the session list": the rail is presence-driven, the sessions page polls every 5 s, and a delete on the page does not converge in the rail until an unrelated reload (the rail's only reload trigger is an unknown presence id) | MEDIUM · MEDIUM | If duplicates are accepted as a documented design (README does not say so) |
| **D11** | `components/conversation/EventRenderer.tsx:24-33` | C6, C9 | "every event in display order is rendered or deliberately not rendered": the registry has no `plan` or `title` entry, so those events occupy `displayOrder` and render `null`; a `title` event therefore changes nothing in the timeline while the rail's title comes from another channel | MEDIUM · LOW | If dropping them is the documented intent (partly — `plan_review` is the rendered card) — then OBSERVATION |
| **D12** | `providers/EventStreamProvider.tsx:130-141` | C8, C6 | "SSE frames are parsed per the wire format": the reader splits on `\n\n` and takes the first line starting with `data:` (:131-136). SSE permits CRLF line endings and multi-line `data:` fields; a proxy that normalises to CRLF yields zero parsed events while the connection stays open — the mode stays `"sse"`, so this compounds with D1 | MEDIUM · MEDIUM | If the backend (uvicorn/Starlette `EventSourceResponse`) is the only possible producer and always emits LF (`weebot/interfaces/web/routers/sse.py:118`) — then this is a dependency-contract note, not a UI bug |
| **D13** | `providers/EventStreamProvider.tsx:177-188` + `components/conversation/ConversationPane.tsx:72-90` | C7, C2 | "a reconnect does not silently skip events": neither transport carries a resume cursor (`Last-Event-ID`/sequence); the reducer dedupes and renders queue-overflow gaps, but events published during a disconnect are never re-fetched until the session's status settles, so a long `running` session can lose rows with no seam | MEDIUM · MEDIUM | If gapless delivery during a live run is explicitly out of contract (the backend replays nothing by design — verify in `mission_center_ui_implementation_plan.md` T0.5) — then it is an OBSERVATION plus a docs note |
| **D14** | `components/command/CommandPalette.tsx:54, 80-93` | C1 | "the highlighted index addresses an existing option": `activeIndex` is clamped only on query change (ArrowDown clamps to `filtered.length - 1`, but a shrinking *registry* while the palette is open leaves it out of range) → `active` undefined, no highlighted option, Enter does nothing | LOW · LOW | If the command set cannot change while the palette is open (a page mounting under it can register commands — `AppShell` is the only registrar today) |

**Observations (not defects, not counted — Phase 8 list):**

| ID | Location | Observation |
|---|---|---|
| O1 | `hooks/useRegisterCommands.ts:9-13` | Dependency on `JSON.stringify(ids)` ignores closure identity. Today's only registrar passes stable callbacks (`router.push`, `useCallback` toggle), so it is **CODE-INNOCENT**; it is a latent contract hazard the executor should record, not fix. |
| O2 | `lib/session-reducer.ts:126-138` | `event!` asserts a non-null row. No known state can produce a dangling key; record as an assertion, not a defect. |
| O3 | `hooks/useSessionEvents.ts:44-48` | One 1 s `setInterval` per subscriber to poll a non-reactive ref; N subscribers ⇒ N timers. Cleanup is correct, so this is a design note. |
| O4 | `lib/api.ts:31-39` | `withToken` puts the API key in the socket URL's query string (3 call sites). Backend-mandated as far as the client knows → owner is the backend contract; security review, not a UI patch. |
| O5 | `hooks/useBehavior.ts` (4×), `app/api/[[...path]]/route.ts:41` | `console.*` in production paths (16 sites tree-wide); no logger. |
| O6 | `providers/ThemeProvider.tsx:22-45` + `app/layout.tsx:24` | Two writers of the theme class (`data-theme` and `.dark`), plus a pre-hydration script; `suppressHydrationWarning` hides any mismatch. |
| O7 | `app/ops/page.tsx:93-129` | Fetch loop has no cancellation; unmount leaves in-flight promises that call `setState`. |

**Seeds deliberately *not* filed:** anything requiring a backend change, anything that would raise a
ceiling, and the 2026-10-24 UX findings already implemented in `ui_ux_remediation_plan.md` (do not
re-open what Appendix C there records as closed).

---

## 8. Reporting, artifacts, definition of done

### 8.1 Artifacts

| Path | Content |
|---|---|
| `tasks/audits/ui_defect_hunt_baseline.md` | §2.3.1 measured baseline + every instrument number, so later waves cannot silently move the goalposts |
| `tasks/audits/ui_defect_hunt_w<N>_<surface>.md` | one per wave: Phase 1 map, Phase 3 verdicts, Phase 4 inventory, Phase 5 fixes, Phase 7 tests, Phase 8 coverage statement |
| `tasks/audits/ui_defect_hunt_summary.md` | program verdict, per-wave routing, aggregate counts, residual UNKNOWN set |

After adding any record under `tasks/`, run `python scripts/gen_tasks_index.py` (its `--check` is part of
`make lint-map`) and keep `make lint-ui` at its exact ceilings. Note the pre-existing map-citation
drift (§2.4 I8): `make lint-map` is red before any wave starts, for reasons that are not this
surface's.

### 8.2 Environment blockers an executor must satisfy

| Capability | Status here | Needed for |
|---|---|---|
| `tsc`, `eslint`, `vitest`, `next build` | ✅ working | all static and jsdom triggers |
| Playwright browser launch | ❌ **BLOCKED** — `libnspr4.so` missing, no root, apt index empty | every DOM-level trigger, the axe suite, the perf budgets |
| Real backend on `:8000` | ❌ not running (not needed: `e2e/fixtures.ts` stubs it) | end-to-end manual verification only |

A browser-capable host is required for W0/H3 and for any Phase 3 verdict that only exists in the DOM
(C10 indicators, tab order, reflow). Until then those candidates stay `[UNK]` and the wave report must
say so — **never** report an unrunnable check as passing.

### 8.3 Coverage statement template (mandatory per wave and for the program)

```
Surface audited:            [regions triaged]
Surface NOT audited:        [in-scope regions skipped for budget] + [out-of-scope]
Defect classes covered:     [C…]
Architecture census basis:  [VF from README + eslint + ceilings | HYP inferred | UNK]
Confirmed defects:          CRITICAL n / HIGH n / MEDIUM n / LOW n
Cleared (innocent):         n     Re-attributed to owner: n     Observations: n
Residual UNKNOWN:           [candidates needing runtime/instrumentation]
Clean-claim scope:          "Regions [R…] were audited for classes [C…] and no VERIFIED defect was
                             found."  ← NOT "the frontend is bug-free".
Highest-value next hunt:    [region/class most likely to yield the next defect]
```

### 8.4 Definition of done for the program

- Every wave has a report with a Phase 8 coverage statement, or is explicitly marked `PARTIAL`.
- Every `VERIFIED DEFECT` has a proof-of-defect test that fails at its parent commit.
- `npm run lint`, `npx tsc --noEmit`, `npm test`, `npx next build`, `make lint-ui` green.
- No ceiling raised; no `ignore_imports`-style exemption added; no dependency added for a fix.
- The browser gates (§8.2) run at least once on a capable host, with the result recorded.

---

## 9. Uncertainty acknowledgment (mandatory)

**Finding most likely to be a false positive.** D4b (health vocabulary). `HEALTH_DOT` keys match what
`/health` actually returns for the overall status; only per-component rows can carry free-text status
strings. It is seeded precisely to exercise the innocence rule, and should probably be cleared.

**Real defect most likely missed.** Anything that lives only in the browser at runtime: C3 interleavings
across the three socket stacks, real reconnect timing, and the a11y/perf regressions the blocked e2e
suite would surface. §2.3.2 already shows these modules have no tests at all — the thin regions are
`app/ops/page.tsx`, `components/shell/*`, and the `(console)` composition.

**Architectural claim most likely wrong.** The §2.2 dependency rule is [VF] only for the two
`eslint` blocks and the six ratchet counters. The claim that *everything else* points downward
(`hooks → providers → lib`, `app` owns no logic) is [HYP] inferred from layout and documentation, not
enforced by any tool. Fix placements that assume an owner (Phase 5a) depend on it: notably D7's
placement in `useComposer` (owner of the send state) and D10's in `useSessionList` (claimed owner of
the list).

**What requires runtime validation.** Every C2/C3/C10 candidate: D1, D2, D3, D8, D10, D13 — the
mechanisms are timing- and lifecycle-dependent.

**What static analysis cannot determine here.** StrictMode's double-mount consequences in production
mode; whether `crypto.randomUUID` is absent in the deployment's origin (secure-context policy);
whether the backend ever returns 204 or non-JSON through the proxy; whether `/events/stream` ever
ends; real reconnect intervals against a proxy that blocks WS; and every axe/perf number while the
browser cannot launch.

**What additional input would most increase confidence.** (1) The backend's response models and the
`/events/stream`, `/health`, `/ws` handlers, quoted side by side with `types/events.ts` — that turns
six C6/C8 candidates from [HYP] to [VF] or [FALSE]; (2) a browser-capable runner for
`npm run test:e2e`; (3) one recorded real session's socket trace (frames + timings) as a golden
fixture; (4) confirmation of the deployment origin (localhost vs LAN vs HTTPS), which decides D6 and
O4; (5) an ADR stating whether "give up and stay silent" is an accepted transport policy, which
decides D2.

---

## Appendix A — recon commands (reproducible)

```bash
# census
find weebot-ui/src -name '*.ts' -o -name '*.tsx' | wc -l
wc -l $(find weebot-ui/src -name '*.ts' -o -name '*.tsx')
grep -rl '"use client"' weebot-ui/src | wc -l
grep -rn 'new WebSocket\|setInterval\|setTimeout\|JSON.parse\|console\.' weebot-ui/src | wc -l

# baseline (all run in weebot-ui/)
npm ci
npx tsc --noEmit                                  # exit 0
npm run lint                                      # exit 0, 0 errors 0 warnings
npm test                                          # 12 files, 75 tests passed
npx next build                                    # OK, 11 routes

# ratchets (repo root)
python3 scripts/lint_ui_debt.py                   # 6 counters at ceiling
python3 scripts/check_ui_contrast.py              # 58 pairs >= 4.5:1

# browser suite (blocked in the cloud VM)
npx playwright install chromium                   # downloads 114 MB, succeeds
npx playwright test                               # 76 failed at browserType.launch: libnspr4.so

# contract evidence read (not modified)
sed -n '440,500p' weebot/interfaces/web/routers/health.py
sed -n '190,230p' weebot/interfaces/web/routers/sessions.py
```

## Appendix B — relationship to neighbouring plans

- **`weebot-ui` UI/UX remediation (2026-10-24, implemented).** Fixes appearance, a11y, layout and the
  transport-bug class it named. This program does **not** re-open its Appendix C closures; where a
  seed touches the same code (D1/D2 in `EventStreamProvider`, D10 in the rail), the wave report must
  cite what that plan changed and why the mechanism survives it.
- **`defect_hunt_v7_execution_plan.md` (Python, V7).** Shares the threat model's C2/"fail-open"
  lineage and the ratchet discipline. Its W0 instrument-audit habit is reproduced here as §2.4,
  because this surface has the same disease in a different organ: well-wired gates whose coverage
  stops exactly where the risk starts.
