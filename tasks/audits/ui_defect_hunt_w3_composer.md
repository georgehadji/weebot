---
status: reference
date: 2026-10-31
---

# Wave 3 — Composer & Send Path

Execution record for W3 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threats **T2** (silent wrong state), **T4** (silent non-execution); classes **C3, C4, C7**.
Structure follows [`ui_defect_hunt_w2_timeline.md`](ui_defect_hunt_w2_timeline.md). Every `[VF]` came from running code (commands in §9).

## Phase 0-WAVE — scope, budget

| | |
|---|---|
| **Surface** | `lib/composer.ts` (+test), `hooks/useComposer.ts`, `components/conversation/Composer.tsx`, `MessageRow.tsx`, `ConversationPane` retry plumbing (`retryRef`/`registerRetry`, read only) |
| **Baseline** | W2 tree; vitest green; `tsc` 0; `lint` 0/0 apart from one W6 file in flight (see §9) |
| **Budget** | ≤15 generated · ≤10 investigated · ≤5 fixed |
| **Spent** | 13 generated · 10 investigated · **3 fixed** · 4 cleared · 3 observations (1 GUARDED, 1 deferred, 1 design) |

## Phase 1 — region map

| R | Region | Layer | Classes | Reachability | Blast | Invariant owner |
|---|---|---|---|---|---|---|
| R1 | `useComposer.deliver` create→run→input split | hooks | C4, C7 | REACHABLE: `/` first message; `/sessions/[id]` every message | MODULE | hook |
| R2 | `useComposer` draft read/write effects | hooks | C3, C7 | REACHABLE: every mount | LOCAL | hook |
| R3 | `useComposer.retry` + `composerReducer` | hooks/lib | C3, C7 | REACHABLE: Retry button on a failed row | MODULE | reducer (phase), hook (send) |
| R4 | `submit` optimistic row vs server echo | hooks/lib | C7 | REACHABLE: echo arrives on the socket | MODULE | session-reducer (W2) |
| R5 | `Composer.handleKeyDown` | components | C7 | REACHABLE: every Enter | LOCAL | view |
| R6 | `MessageRow` delivery chrome | components | C7 | REACHABLE | LOCAL | row |
| R7 | `ConversationPane` `retryRef`/`registerRetry` | components | C3 | REACHABLE | LOCAL | pane |

Atomic assertions: (1) **[VF]** the composer is mounted only by `ConversationPane`, which `/` renders with `sessionId={null}` and `/sessions/[id]` renders `key={sessionId}`; (2) **[VF]** `useToast` throws without a provider, and the sibling `RunControls` already requires it, so the app tree has one; (3) **[VF]** `lib/composer.ts` is pure; the hook is its only caller.

## Phase 2 — candidates

| ID | Location | Claimed violated property | Class | Innocence path |
|---|---|---|---|---|
| W3-1 *(seed D7)* | `useComposer.ts:75-84` | a task that did not start is not shown as sent | C4, T4 | opening the session is a designed, sufficient recovery |
| W3-2 | `useComposer.retry` | a retry is a send: the composer enters `sending`, the old error goes | C7, C3 | reducer sets phase elsewhere (it does not) |
| W3-3 | `Composer.handleKeyDown` / `submit` | double Enter sends once | C3 | React flushes discrete events between keydowns |
| W3-4 | draft effects :44-52 | a saved draft is restored, also under StrictMode and a throwing storage | C3 | read effect declared first |
| W3-5 | draft effects on a `key` change | a draft belongs to its session | C3 | callers remount the composer |
| W3-6 | `markDelivery` vs `failed` | row and composer agree on whether a message was delivered | C7, C3 | HTTP error means not delivered |
| W3-7 | `submit` after a failed send | resending via the box does not leave a second "Not sent" row | C7 | one recovery path only |
| W3-8 | `handleKeyDown` | Enter that confirms an IME candidate never sends | C7 | `isComposing` covers it |
| W3-9 | `MessageRow`, `registerRetry` | Retry hands back the row's event; no Retry while sending or without a handler | C3 | — |
| W3-10 | `retry` → `deliver(event.id)` | a retry reuses the row's id so the echo settles the same row | C3 | server needs a fresh id (it dedupes by id) |
| W3-11 | `retry` model | a retry sends with the model the row was sent with | C7 | — (not investigated) |
| W3-12 | composer error line | the "Not sent" alert clears when the user edits | C7 | — (not investigated) |
| W3-13 | draft effects | a message in flight survives a reload | C3 | — (not investigated) |

## Phase 3/4 — proof, innocence, inventory

| Candidate | Trigger | Innocence attempt | Basis | Status | User-visible consequence |
|---|---|---|---|---|---|
| **W3-1** | `useComposer.test` "create ok + run fails…": `toast` called 0 times at HEAD | the comment is right that opening is a recovery, but the session opens `pending`, empty ("Waiting for events…"), the optimistic row is gone with the old pane, and nothing says the run failed; the only trace is `console.warn`. Opening stays correct (a retry would create a second session) | VERIFIED | **VERIFIED — MEDIUM — FIXED** | the message looks sent, the task never starts, no error shown |
| **W3-2** | `useComposer.test` x3 + `composer.test` x3: after a successful retry `phase` stays `failed` (`expected 'failed' to be 'idle'`); during a retry `phase` is `failed` not `sending`; a retry started during another send ran a second concurrent send (`input` called 2 times) | the reducer's `sent` only leaves `sending`, so nothing else clears it | VERIFIED | **VERIFIED — MEDIUM — FIXED** | after Retry works, the red "Not sent: … Your message is back in the box." stays and `aria-invalid` stays on a box that is now empty; two sends can be in flight with one phase flag |
| W3-3 | `Composer.test` "two Enters…" and hook "second submit is ignored": one `input` call | reachability: React flushes a discrete event's updates before the next keydown, and `submit` is guarded by `phase` | VERIFIED | **CLEARED** (tests kept) | none |
| W3-4 | hook tests: restore, StrictMode, per-session key, removal on send, throwing storage | read effect runs before the write; both wrapped in try/catch | VERIFIED | **CLEARED** | none |
| W3-5 | `it.fails` "GUARDED…": at HEAD the old draft `for s1` is still in the box after `sessionId` changes in place, and is written to the new key | reachability: `/` never changes `sessionId`; `/sessions/[id]` is keyed by `sessionId` (W2 verified) so the composer always remounts | VERIFIED (hook level) | **OBSERVATION (GUARDED)** | none today |
| W3-6 | `it.fails` "an HTTP error after the server echoed…": the row stays `sent` (reducer, by design) while the composer shows "Not sent" and gives the text back | the reducer comment says an echo proves delivery; but the hook cannot see the row | VERIFIED | **OBSERVATION — deferred** (fix crosses hook + pane + reducer) | a delivered message shown with an alert; re-sending it duplicates it |
| W3-7 | read: `submit` mints a new id while the failed row keeps its own | two recovery paths (Retry on the row, resend from the box) are both offered | HYPOTHESIS (static) | **OBSERVATION — `[REQUIRES HUMAN REVIEW: product decision]`** | a failed row can sit above an identical sent one |
| **W3-8** | `Composer.test` "keyCode 229": `input` called 1 time at HEAD for an Enter with `isComposing: false, keyCode: 229` | Chrome/Firefox set `isComposing`; only Safari/WebKit reports this shape. The event shape is simulated, real Safari not available here | VERIFIED on a simulated event; real browser **[UNK]** | **VERIFIED — LOW — FIXED** | on Safari, confirming a Greek/CJK candidate with Enter sends the half-typed message |
| W3-9 | `Composer.test` MessageRow x3 + real Retry click through pane → `registerRetry` → hook | none found | VERIFIED | **CLEARED** | none |
| W3-10 | hook test "a retry reuses the row's id as client_msg_id" and the pane retry test (same wire id, one row after the echo) | the reuse is what lets the echo settle the original row; the server persists with that id and the reducer dedupes by id | VERIFIED | **CLEARED** | none |
| W3-11/12/13 | not run | — | HYPOTHESIS | not investigated (budget) | — |

## Phase 5 — fixes

Owner placement: the phase machine is `lib/composer.ts`; the send and its errors are `useComposer`. Ladder rung 1/2; no dependency, lint rule or ceiling.

| Defect | Owner | Change | Lines |
|---|---|---|---|
| W3-1 | `useComposer.deliver` | in the existing run `catch`, `toast({ error })` via `useToast` (as `RunControls` does); the session still opens and the row still settles | +1 import, +1 hook call, +5 |
| W3-2 | reducer + `retry` | new `retry` action (`phase -> sending`, error cleared, no-op while sending); `retry` ignores a call while a send is in flight and dispatches it otherwise | +4 reducer, +3 hook |
| W3-8 | `Composer.handleKeyDown` | add `e.keyCode !== 229` to the Enter test | +2 (one is a comment) |

**Deviation (W3-2).** The fix touches two functions in two files (reducer + `retry`), one over the "≤1 function" rule: the state machine and the sender own the property jointly. Marked `[REQUIRES HUMAN REVIEW: cross-file mechanism]`. Interface note: `ComposerAction` gained a member (internal; only `useComposer` dispatches it). `useComposer` now requires `ToastProvider` in the tree, which the app layout already provides and `RunControls` already relies on.

**Behaviour note.** A Retry press while another send is in flight is now ignored, so the row keeps its "Not sent" and Retry for the few seconds the other send takes. The alternative (two sends sharing one phase flag) was the defect.

## Phase 6 — self-review (8 vectors)

| # | Vector | Verdict |
|---|---|---|
| 1 Boundary | empty / whitespace draft, retry from idle, retry while sending, retry that fails again | FIX HOLDS `[VF]` |
| 2 Invalid input | run rejects with a non-`Error`: description falls back to "Unknown error" | FIX HOLDS `[HYP]` (code path read, not run) |
| 3 State | StrictMode mount, throwing storage, failed -> retry -> sent | FIX HOLDS `[VF]` |
| 4 Regression | 6 original composer tests, `ConversationPane` and primitives tests unchanged and green | FIX HOLDS `[VF]` |
| 5 Concurrency | retry during a send; echo before the HTTP answer; double Enter | FIX HOLDS `[VF]` |
| 6 New defect | re-read the three changed files for C1-C10 | none found |
| 7 Architecture | `lib/composer.ts` still pure; no `fetch`; no new global state; lint clean on W3 files | FIX HOLDS `[VF]` |
| 8 Paradigm | state is a reducer action, not a flag; error surfaces through the existing toast | FIX HOLDS `[VF]` |

## Phase 7 — the phase × delivery matrix (exit criterion)

Rows: the composer's `phase`. Columns: the delivery state of the timeline row involved.

| phase \ row | **sending** | **sent** | **failed** |
|---|---|---|---|
| **idle** | impossible after the W3-2 fix (a retry used to leave `idle` with a `sending` row); `composer.test` "a retry from idle also enters sending" | normal terminal state: `Composer.test` "idle x sent"; hook "stored per session and removed when sent" | possible and legitimate: an old failed row after a later send succeeded: hook "idle x failed" |
| **sending** | normal in-flight: `Composer.test` "sending x sending" (row and composer both show *Sending…*, box enabled) | echo beats the HTTP answer: `Composer.test` "sending x sent" (one row, settles) | possible: an older failed row while a newer send is in flight; not a defect (different message). Same message is impossible: the hook dispatches `failed` together with the row |
| **failed** | impossible after the fix (retry enters `sending`): hook "while a retry is in flight the composer says sending" and "a retry while another send is in flight does not start a second send" | same message: the contradictory cell, **W3-6 observation** (`it.fails` test). Different message: trivially fine | normal: `Composer.test` "failed x failed" (alert + text back + row Not sent); hook "a retry that fails again keeps the text" |

Every cell is covered or marked impossible; one cell (failed × sent, same message) is a verified observation, deferred.

Other new tests: `composer.test.ts` +3 (retry action), IME and double-Enter cases, 3 `MessageRow` cases. Mutation check, by reasoning from the failing-at-HEAD runs rather than a separate restore pass: the retry tests fail without `dispatch({ type: "retry" })`, the D7 test fails without the toast, the IME test fails without `keyCode !== 229`.

## Phase 8 — verdict

Process checks: defects verified ✅ x3 · fix size ✅ (one deviation noted) · proof + boundary + no-regression ✅ · census ✅ · owner placement ✅. Engineering checks: vectors ✅ (one `[HYP]`), regression risk LOW, causal fixes ✅, no unresolved interaction ✅ (W3-1 and W3-2 touch the same hook; both sets pass together).

**Routing: ACCEPT** W3-1/2/8; `[REQUIRES HUMAN REVIEW: cross-file mechanism]` on W3-2; W3-6 and W3-7 escalated as design observations.

### Coverage statement

```
Surface audited:            R1-R7 (deliver, drafts, retry, optimistic/echo, Enter handling, MessageRow,
                            retry plumbing)
Surface NOT audited:        DOM behaviour in a real browser (IME events in Safari, focus after send,
                            reflow, axe) — environment blocked; W3-11/12/13 (budget)
Defect classes covered:     C3, C4, C7
Architecture census basis:  VF (eslint layer blocks, tsc strict)
Confirmed defects:          CRITICAL 0 / HIGH 0 / MEDIUM 2 (W3-1, W3-2) / LOW 1 (W3-8), all fixed
Cleared (innocent):         4 (W3-3, W3-4, W3-9, W3-10)
Re-attributed to owner:     0     Observations: 3 (W3-5 GUARDED, W3-6 deferred, W3-7 design)
Residual UNKNOWN:           W3-8 on real Safari; whether the backend /input can persist + echo and
                            still return an error (decides how often W3-6 is reachable)
Clean-claim scope:          "Regions R2 and R7 were audited for classes C3 and C7 and no VERIFIED
                             defect was found."
Highest-value next hunt:    W3-6: let deliver learn from the timeline whether the echo already
                            arrived (cross-file), and W3-7 the double recovery path
```

## 9. Commands (from `weebot-ui/`)

```
npx vitest run     -> 35 files / 267 tests green
npx tsc --noEmit   -> exit 0
npm run lint       -> 1 error, not in W3: src/components/shell/shell.invariants.test.tsx:43
                      (@next/next/no-html-link-for-pages; W6's file, in flight)
```

At HEAD (before the fixes) the new tests failed as recorded in §3/4: D7 toast 0 calls; `failed` not `idle`; `failed` not `sending`; `input` 2 calls; IME `input` 1 call. `next build`, `make lint-ui` and the browser suite were **not run** (shared checkout / blocked environment).

## Deferred

- W3-6: composer/row disagreement when an echo precedes an HTTP error (cross-file).
- W3-7: stale failed row after resending from the box (product decision: one recovery path).
- W3-5: `useComposer` does not reset on an in-place `sessionId` change; safe only while callers key the pane.
- Backend `sse.py` id (W2-4) unchanged.
