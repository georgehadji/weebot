---
status: reference
date: 2026-10-31
---

# Wave 2 — Conversation Timeline & Projection

Execution record for W2 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threats **T3** (loss / duplication / ordering), **T5** (liveness); classes **C1, C6, C7, C8**.
Structure follows [`ui_defect_hunt_w1_transport.md`](ui_defect_hunt_w1_transport.md). Every `[VF]` came from running code (commands in §9).

## Phase 0-WAVE — scope, budget

| | |
|---|---|
| **Baseline** | W1 tree + W0 harness; `tsc` 0, `lint` 0/0, vitest green apart from a W7 test in flight (see §9) |
| **Budget** | ≤15 generated · ≤10 investigated · ≤5 fixed |
| **Spent** | 12 generated · 10 investigated · **5 fixed** (one is two symptoms of one root cause) · 3 cleared · 2 observations |

## Phase 1 — region map

| R | Region | Layer | Classes | Reachability | Blast | Invariant owner |
|---|---|---|---|---|---|---|
| R1 | `lib/session-reducer.ts` (dedupe, order, tool pair, gaps, optimistic) | lib | C6, C7, C8 | REACHABLE: every socket/SSE frame and every history load | SYSTEM | reducer |
| R2 | `ConversationPane` history-refetch effect (:72-90) | components | C3, C7 | REACHABLE: `/sessions/[id]` when status leaves pending/running | MODULE | pane |
| R3 | `getDisplayItems` `event!` | lib | C1 | GUARDED (no path makes a dangling key) | LOCAL | reducer |
| R4 | `EventRenderer` registry silent drops | components | C6, C8, C9 | REACHABLE: any event type without an entry | MODULE | registry |
| R5 | `ToolCallRow` truncation / copy | components | C1 | REACHABLE: any tool result >4000 chars | LOCAL | row |
| R6 | `useStickToBottom` / `lib/scroll.ts` | hooks | C1, C7 | REACHABLE: every timeline | LOCAL | hook |
| R7 | `announce.ts`, `StepRow`, `StatusEventRow`, `MessageRow`, `GapMarkerRow` | lib/components | C6 | REACHABLE | LOCAL | rows |
| R8 | `PlanReviewCard`, `components/plan/*` | components | C3, C8 | REACHABLE: timeline `plan_review`, `/ops`, dock Plan tab | LOCAL | visualizer |

Atomic assertions: (1) **[VF]** the reducer is pure and the only writer of `displayOrder`; (2) **[VF]** `ConversationPane` is keyed by `sessionId` in `sessions/[id]/page.tsx:102`, so cross-session state bleed cannot happen (candidate cleared); (3) **[VF]** the backend emits event types the TS union and the registry do not know (`thought`, `steering`, `todo`, `verification`, `canonicalization`, `tool_approval`, `plan`, `title`) — they reach the reducer and render nothing; (4) **[VF]** `routers/sse.py:96-100` builds the "N event(s) dropped" notice as `{type, text}` only — **no `id`**.

## Phase 2 — candidates

| ID | Location | Claimed violated property | Class | Innocence path |
|---|---|---|---|---|
| W2-1 | `ConversationPane.tsx:72-90` | history merged into the timeline keeps server order | C7, C3 | reducer is order-insensitive (it is not: arrival order) |
| W2-2 | same + `session-reducer.ts:83-86` | a settled tool row never reverts to "running" | C7 | replay always in order (not on this path) |
| W2-3 *(seed D11 + R4)* | `EventRenderer.tsx:24-33` | a row-less event is not a timeline row | C6, C9 | intent documented (partly) |
| W2-4 | `session-reducer.ts` gap branch vs `sse.py:96` | every drop notice surfaces | C8 | backend sends an id (it does not) |
| W2-5 | `ToolCallRow.tsx` preview | a truncated preview is valid text | C1 | no astral chars in results |
| W2-6 | `PlanVisualizer.tsx:130` | the graph draws the plan it is given | C3, C8 | steps never change while mounted |
| W2-7 | `getDisplayItems` `event!` (R3/O2) | every key resolves | C1 | no dangling key reachable |
| W2-8 | `useStickToBottom` arithmetic | unseen = rows since leaving; 0 at bottom | C1, C7 | observer ordering |
| W2-9 | `ConversationPane` state init | state resets on session switch | C7 | page keys the pane |
| W2-10 | `announce.ts` / `doneLabel` | failed/ended states announce truthfully | C6 | — |
| W2-11 | `PlanVisualizer` dependency-edge ids | edge ids unique | C8 | deps never equal previous step |
| W2-12 | `ToolCallRow` repeated `tool_call_id` | distinct calls stay distinct | C8 | provider ids unique |

## Phase 3/4 — proof, innocence, inventory

| Candidate | Trigger | Innocence attempt | Basis | Status | User-visible consequence |
|---|---|---|---|---|---|
| **W2-1** | `ConversationPane.test` "events missed before the socket subscribed land before the later live ones": `expected 10 to be less than 0` at HEAD | guard: none; reachability: the refetch fires when status settles, so any live event before that is passed | VERIFIED | **VERIFIED — MEDIUM — FIXED** | rows missed pre-subscribe appear *after* the final live rows (e.g. after "Session completed") |
| **W2-2** | "a tool row whose `called` arrived live is not reverted by a replayed `calling`": spinner `Running` still present at HEAD | a `calling` published before subscribe plus a live `called` is the ordinary late-join case | VERIFIED | **VERIFIED — MEDIUM — FIXED** (same root cause as W2-1) | a finished tool shows a spinner forever and its result is gone |
| **W2-3** | "only title/plan events still says it is waiting" (only `Agent is working…`, no empty state) and "does not count as a new row for the jump pill" (`· 2 new` at HEAD) | dropping is intentional, but then `displayOrder` and the count must exclude them — neither does | VERIFIED | **VERIFIED — LOW — FIXED** | blank timeline with no hint; "N new" pill counts invisible events |
| **W2-4** | `guarantees` G4 SSE test: `expected [3] to deeply equal [3, 5]` at HEAD | contract-owner defence: the backend should send an id — **true; owner defect deferred (below)**; the frontend must still not discard | VERIFIED (C8, owner = `sse.py`) | **VERIFIED — MEDIUM — FIXED (defense-in-depth) + OWNER DEFERRED** | every drop notice after the first is silently discarded, so overflow reads as one seam |
| **W2-5** | `ToolCallRow.test` "never cuts an emoji in half": preview ended in a lone high surrogate at HEAD | none | VERIFIED | **VERIFIED — LOW — FIXED** | tail of a long preview renders U+FFFD |
| **W2-6** | `PlanVisualizer.test` x2: edge stroke `#9ca3af` not `#22c55e` after statuses change; 2 edges after the plan shrank to 2 steps (expected 1, to vanished nodes) | `useEdgesState(initial)` seeds once; nodes have an update effect, edges do not | VERIFIED | **VERIFIED — MEDIUM — FIXED** | edges stay as drawn for the first plan: wrong colours, edges to nodes that no longer exist |
| W2-7 | `guarantees` G5 | no code path adds a key without its entry (both writes are one return) | VERIFIED | **CLEARED** (property test kept) | none |
| W2-8 | `useStickToBottom.test` x4 (fake IntersectionObserver) | — | VERIFIED | **CLEARED** — arithmetic holds | none |
| W2-9 | read | `key={sessionId}` in `sessions/[id]/page.tsx:102` | VERIFIED | **CLEARED** | none |
| W2-10 | read + existing tests | `doneLabel` covers failed/absent status | VERIFIED | not counted as a defect (covered by existing tests) | none |
| W2-11 | not run | `PlanVisualizer.tsx:111,118`: a dependency on the previous step yields an edge with the same id as the sequential edge | HYPOTHESIS | **OBSERVATION** (React duplicate key; not triggered) | possible duplicate edge |
| W2-12 | not run | provider tool-call ids repeating across turns would collapse distinct calls into one row | HYPOTHESIS | **OBSERVATION** (owner: backend/provider) | possible overwritten tool row |

## Phase 5 — fixes

All at the owner, ladder rung 1/2; no new dependency, lint rule or ceiling.

| Defect | Owner | Change | Lines |
|---|---|---|---|
| W2-1 + W2-2 | reducer owns order; pane owns the refetch | new pure `mergeHistory(state, history)` in `lib/session-reducer.ts` folds the server history first, then replays rows only the client has (optimistic messages, gaps); the pane calls it instead of appending `missed` | +9 reducer, 1 changed in pane |
| W2-3 | registry owns "what is drawn" | `isRendered(event)` exported from `EventRenderer.tsx`; pane filters `getDisplayItems` with it | +2 / +3 |
| W2-4 | reducer (defense-in-depth) | an event without a string `id` gets a synthetic `anon:<n>` id so it cannot collide on `undefined` | +3 |
| W2-5 | `ToolCallRow` | preview cut backs off one char when it would split a surrogate pair | +3 |
| W2-6 | `PlanVisualizer` | edges are derived (`const edges = initialEdges`), `useEdgesState` import dropped | -1 / +2 |

**Deviation.** W2-1/2 touches two functions in two files (reducer + pane call site), one over the "≤1 function" rule. Both are inside W2's surface; the alternative (a pane-local rebuild) would put reducer logic in a component. Marked `[REQUIRES HUMAN REVIEW: cross-file mechanism]`. Side effects: the timeline rebuilds once on refetch (one re-render), and the history copy of a message wins over a stale optimistic one with the same id, which is right since the server has it.

**W2-4 residual.** The reducer fix hides the symptom, not the owner defect: `weebot/interfaces/web/routers/sse.py:96-100` should emit `id`, `session_id` and `timestamp` on the gap notice. Outside W2's edit surface, so **deferred**. The synthetic id is not stable across a replay (`anon:<size>`); acceptable only because drop notices are never stored.

## Phase 6 — self-review (8 vectors)

| # | Vector | Verdict |
|---|---|---|
| 1 Boundary | empty history, empty live, one-char-over truncation, empty plan, single step | FIX HOLDS `[VF]` |
| 2 Invalid input | id-less event; event types with no row through the pane | FIX HOLDS `[VF]` |
| 3 State | refetch while an optimistic row is `failed` keeps its `failed` state | FIX HOLDS `[VF]` |
| 4 Regression | the 14 existing reducer tests and the done/plan row tests still pass | FIX HOLDS `[VF]` |
| 5 Concurrency | refetch resolving after more live events: live-only rows are replayed after history | FIX HOLDS `[HYP]` (one interleaving tested) |
| 6 New defect | re-read changed files for C1-C10 | none found |
| 7 Architecture | `lib/` stays React-free; no `fetch`; lint 0/0 | FIX HOLDS `[VF]` |
| 8 Paradigm | pure reducer extended with a pure function; no new pattern | FIX HOLDS `[VF]` |

## Phase 7 — the reducer's guarantees (exit criterion)

`src/lib/session-reducer.guarantees.test.ts`. Each guarantee was **mutation-checked**: the named code was broken, the listed test failed, the file restored.

| # | Property | Tests | Mutation that breaks it |
|---|---|---|---|
| G1 | **Dedupe**: a repeated id never adds a row or replaces the stored event; replaying a whole history is a no-op | 2 | disable the `known` early return: 3 fail |
| G2 | **Order**: rows appear in first-arrival order; an update never moves a row | 1 | prepend instead of append: fail |
| G3 | **Tool pair**: one row per `tool_call_id`, at its first position, showing the latest update | 1 | always append the tool key: fail |
| G4 | **Gaps**: every drop notice is its own gap row with its own count, id-less ones included | 2 | never create a gap: fail |
| G5 | **Total**: every `displayOrder` key resolves | 1 | drop the tool lookup: fail |
| G6 | **Purity**: the previous state is never mutated | 1 | write into the shared map: fail |
| — | **History merge**: server order first, client-only rows after, optimistic delivery kept | 3 | the W2-1/2 pane tests |

Optimistic echo/settle is covered by the 6 existing tests in `session-reducer.test.ts`, unchanged.

Other new tests: `ConversationPane.test.tsx` (5), `ToolCallRow.test.tsx` (3), `PlanVisualizer.test.tsx` (3), `useStickToBottom.test.tsx` (4).

## Phase 8 — verdict

Process checks: defects verified ✅ x5 · fix size ✅ (one deviation noted) · proof + boundary + no-regression ✅ · census ✅ · owner placement ✅ (W2-4 owner deferred). Engineering checks: vectors ✅ (one `[HYP]`), regression risk LOW, causal fixes ✅, no unresolved interaction ✅ (W2-1/2/4 meet in `mergeHistory`; its test uses an id-less gap), no layer violation ✅, no new pattern ✅.

**Routing: ACCEPT** W2-1/2/3/5/6; **ACCEPT + ESCALATE** W2-4 (backend `id`); `[REQUIRES HUMAN REVIEW: cross-file mechanism]` on W2-1/2.

### Coverage statement

```
Surface audited:            R1-R8 (reducer, refetch effect, registry, ToolCallRow, stick-to-bottom,
                            announce, status rows, PlanReviewCard, PlanVisualizer)
Surface NOT audited:        DOM behaviour in a real browser (scroll + IntersectionObserver timing,
                            reflow, axe) — environment blocked; StepRow/MessageRow visuals
Defect classes covered:     C1, C3, C6, C7, C8, C9
Architecture census basis:  VF (eslint layer blocks, tsc strict)
Confirmed defects:          CRITICAL 0 / HIGH 0 / MEDIUM 4 (W2-1, W2-2, W2-4, W2-6) / LOW 2 (W2-3, W2-5), all fixed
Cleared (innocent):         3 (W2-7, W2-8, W2-9)   Re-attributed to owner: 1 (W2-4 -> sse.py)   Observations: 2 (W2-11, W2-12)
Residual UNKNOWN:           real IntersectionObserver ordering when a tall row lands; whether any
                            provider reuses tool_call_ids across turns (W2-12)
Clean-claim scope:          "Regions R3 and R6 were audited for classes C1 and C7 and no VERIFIED defect was found."
Highest-value next hunt:    backend event vocabulary vs types/events.ts (8 emitted types are unknown
                            to the UI) — a contract diff, not a UI patch
```

## 9. Commands (from `weebot-ui/`)

```
npx vitest run     -> 28 files / 196 tests green (an earlier run had 1 failure in
                      components/ui/primitives.contract.test.tsx, a W7 test edited concurrently; not W2)
npx tsc --noEmit   -> exit 0
npm run lint       -> 0 errors, 0 warnings
```

`next build`, `make lint-ui` and the browser suite were **not run** (shared checkout / blocked environment).
