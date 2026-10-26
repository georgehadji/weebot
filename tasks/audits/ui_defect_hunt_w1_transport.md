---
status: reference
date: 2026-10-25
---

# Wave 1 — Transport & Live-State Integrity

Execution record for W1 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threats **T2** (silent wrong state), **T3** (event loss), **T5** (liveness), **T6** (resource
lifecycle); classes **C2**, **C3**, **C7**, **C8**, **C10**.

Every `[VF]` below came from running code. Commands: §10.

---

## Phase 0-WAVE — scope, budget

| | |
|---|---|
| **Baseline** | `main` @ working tree with W0 harness; `tsc` 0, `lint` 0/0, `vitest` 14 files/85 tests, `next build` OK |
| **Budget** | ≤15 candidates generated · ≤10 investigated · ≤5 fixed |
| **Spent** | 6 generated · 5 investigated · **3 fixed** · 1 cleared · 1 deferred · 1 observation |
| **W0 dependency** | Satisfied. Without the fake socket + fake SSE stream, *no* candidate here is triggerable: `setupFiles: []` had no transport at all. |

---

## Phase 1 — region map

| R | Region | Layer | Classes | Reachability | Blast radius | Invariant owner |
|---|---|---|---|---|---|---|
| R1 | `EventStreamProvider.startSessionSSE` (:107-173) | providers | C2, C3, C6, C10 | REACHABLE: `GET /sessions/[id]` → 5 failed WS reconnects → fallback | SYSTEM | provider (mode + pool) |
| R2 | per-session lifecycle: `subscribeSession` (:215-243), `closeSessionConnection` (:95-105), teardown effect (:302-315) | providers | C2, C3 | REACHABLE: every route change, every unmount, StrictMode double mount | SYSTEM | provider |
| R3 | presence connection (:244-291) | providers | C2, C10 | REACHABLE: any rail mount | MODULE | provider |
| R4 | `useSessionEvents` connection reporting (:36-51) | hooks | C10 | REACHABLE: AppBar `Live`/`Offline` dot | LOCAL (display) | provider (mode) + hook (poll) |
| R5 | `useSessionList` presence merge (:15-71) | hooks | C6, C8 | REACHABLE: rail | MODULE | `types/events.ts` union |
| R6 | `useBehavior` (:48-160) | hooks | C2, C10 | GUARDED (behaviour routes only) | MODULE | its own socket |
| R7 | `useWebSocketDebug` (:22-105) | hooks | C2 | GUARDED (`/debug`, dev) | LOCAL | its own socket |

### Atomic assertions about the map

1. **`[VF]`** R1 is reachable in normal operation without any misconfiguration: the fallback fires
   after five failed reconnects, and a backend restart, a proxy that blocks `Upgrade`, or a
   sleeping laptop all produce that. It is not a rare branch.
2. **`[VF]`** The transport the fallback talks to has exactly one producer in this repo:
   `sse_starlette.sse.EventSourceResponse` in `weebot/interfaces/web/routers/sse.py`. Its wire
   format is therefore a *fact*, not an assumption — §3.2 quotes it.
3. **`[VF]`** `getSessionMode` is the **only** source of the AppBar's `Live` claim
   (`useSessionEvents.ts:40-46` polls it into `isConnected`), so any mode left stale is a C10
   defect by construction.
4. **`[HYP]`** R6 (behaviour socket) shares R2's teardown shape but was not triggered in this
   wave — budget.

---

## Phase 2 — candidates

| ID | Location | Claimed violated property | Class | Prior · severity | Innocence path |
|---|---|---|---|---|---|
| D1 | `EventStreamProvider.tsx:109,145-148` | a connection mode asserts a *live* subscription | C10, C2 | HIGH · HIGH | another consumer re-subscribes on mode change (it does not: effect deps are stable) |
| D12 | `EventStreamProvider.tsx:130-137` | SSE frames are parsed per the wire format the producer emits | C8, C6 | HIGH · HIGH | the producer emits LF (measurable — §3.2) |
| D15 *(new)* | `EventStreamProvider.tsx:302-315` + `:95-105` | a connection torn down by its owner must not reconnect | C2 | MEDIUM · MEDIUM | `closeSessionConnection` clears listeners first (it does not) |
| D2 | `EventStreamProvider.tsx:257-262` | a permanently degraded live path is visible to its consumer | C10, C2 | MEDIUM · MEDIUM | giving up is a documented policy (it is not documented) |
| D9 | `useSessionList.ts:23` | a session status is a member of the documental union | C6, C8 | MEDIUM · MEDIUM | the backend provably emits only five values |
| D13 | `:177-188` + `ConversationPane.tsx:72-90` | a reconnect does not silently skip events | C7 | MEDIUM · MEDIUM | gapless delivery is explicitly out of contract |

---

## Phase 3 — proof of defect (dual)

### 3.1 D12 — SSE frames are dropped: the fallback delivered **zero** events, ever

**Trigger** (`src/providers/EventStreamProvider.test.tsx` › "D12"):
force the fallback, push one frame encoded by the real producer, assert delivery.

```
AssertionError: expected [] to deeply equal [ 'e1' ]
```

**DID-NOT-FIRE on the LF boundary case** — the same test with `\n\n` separators passes at HEAD,
which isolates the cause to the separator, not to the parser's logic or the fallback plumbing.

**Innocence attempt — adversarial.** The only defence that would clear this is "the producer emits
LF". The producer is `sse_starlette`, so it is measurable:

```python
>>> ServerSentEvent(data='{"a":1}', event='message').encode()
b'event: message\r\ndata: {"a":1}\r\n\r\n'
```

The client split on `"\n\n"`, which does **not** occur in `"\r\n\r\n"` (the bytes are
`\n`,`\r`,`\n`). So `buffer` grows forever, the frame list stays empty, and no `data:` line is ever
read. The defence fails.

**Net verdict: CONFIRMED.** C8 — an assumption about a dependency's output that its own encoder
contradicts — compounded by C10, because the mode stays `"sse"` while this happens.

*Why this ranks where it does:* it is not an edge case. Every user who reaches the fallback (i.e.
every deployment where a proxy blocks WebSocket upgrades — the exact scenario the fallback exists
for) got a console that showed **Live** and received **nothing**.

### 3.2 D1 — the mode never leaves `"sse"` when the body ends

**Trigger** (› "D1: stops reporting a live subscription once the stream is over"):
drive the fallback, end the body cleanly (backend restart), advance the 1 s mode poll.

```
AssertionError: expected 'sse' not to be 'sse'
```

Boundary variant (stream *errors* instead of ending) fires identically.

**Innocence attempt.** Guard defence: none — `conn.mode` is written at :109 and never again on any
terminal path. Reachability defence: fails, the body ending is the ordinary end of a backend
restart. Contract-owner defence: the *provider* owns `mode`; it is the owner and does not enforce
it. The `catch` comment claims "the consumer's next `subscribe()` call will retry from WS" — false
while mounted: `subscribeSession` only opens a connection when no entry exists, and the entry is
never removed on this path.

**Net verdict: CONFIRMED** (C10, and it is what made D12 invisible rather than noisy).

### 3.3 D15 *(found in this wave, not pre-seeded)* — teardown reconnects

**Trigger** (› "D15: unmounting the provider does not open a replacement socket"):
render the provider with one session subscriber, accept the socket, unmount, advance 30 s.

```
AssertionError: expected 2 to be 1
```

**Mechanism** [VF]: `closeSessionConnection` calls `ws.close()`; the browser dispatches `close`
**after** the cleanup returns; `onclose` guards with `conn.listeners.size === 0`, but teardown never
clears the listener set (only the *last unsubscribe* path does, and that path empties it before
closing). So the provider schedules `setTimeout(open, 1000)` — 1 s after unmount a fresh socket
opens, then repeats up to five times and finally starts an **SSE fetch that lives as long as the
page**. The presence socket has the same shape (`presenceListeners` is not cleared).

**Innocence attempt.** Guard defence: none. Reachability: unmount of the root provider is page
teardown, but the *same* path runs on every StrictMode double mount in development, and the
conn-sequence is the one `ConsoleShell` remounts on. Contract-owner: the provider owns teardown.
No defence found.

**Net verdict: CONFIRMED** (C2).

### 3.4 D9 — CLEARED (code-innocent, contract-owner defence)

The unsound cast `update.status as Session["status"]` (`useSessionList.ts:23`) is real, and the
type `SessionPresenceEvent["status"]` is `… | string`, so the compiler cannot help. But the
violated precondition — "the status is one of five" — is owned by the backend, and the backend
enforces it at the type level:

- one emitter: `weebot/application/services/task_runner.py:141-145`;
- `status=session.status.value`, where `Session.status: SessionStatus`, a `str, Enum` with exactly
  `pending | running | waiting | completed | failed` (`weebot/domain/models/session.py:17-22`);
- Pydantic validates the model, so no other string can reach `.value`.

**CLEARED.** Recorded as a type-tightening opportunity (`status: SessionStatus` in the presence
event would remove the cast), not a defect. A future status added on the backend without the union
is a *new* candidate, not this one.

### 3.5 D2 — investigated, deferred (fix exceeds the wave's constraints)

Mechanism `[VF]` by inspection and reachable, but not triggered to a failing test in this wave: the
presence socket stops reconnecting after `MAX_RECONNECT_ATTEMPTS`, `presenceReconnectRef` resets
only in `onopen`, and no consumer-visible state changes when it gives up. Proving it needs only the
W0 harness (close the presence socket six times), so it is triggerable — but every causal fix
changes the public context shape (`EventStreamProvider`'s exposed value) or adds unbounded retry
policy. That is `[REQUIRES HUMAN REVIEW: public interface change]` under §5c, i.e. a decision for
the owner, not a defect a wave may settle. Carried to W8 with the recommendation in §9.

### 3.6 D13 — OBSERVATION (owner: backend contract)

No resume cursor on either transport (`Last-Event-ID` / sequence). Both transports are lossless
*while connected*; across a reconnect, events published during the gap are not re-fetched until
`ConversationPane`'s history refetch. The reducer renders queue-overflow gaps, so the seam exists
in the UI but cannot be closed there — it needs a backend cursor. Recorded, not fixed.

---

## Phase 4 — inventory

| Candidate | Trigger | Innocence | Evidence basis | Status | User-visible consequence |
|---|---|---|---|---|---|
| **D12** | **FIRED** | NO-DEFENCE | VERIFIED | **VERIFIED DEFECT — HIGH — FIXED** | fallback console receives nothing while showing Live |
| **D1** | **FIRED** | NO-DEFENCE | VERIFIED | **VERIFIED DEFECT — HIGH — FIXED** | `Live` dot stays lit over a dead feed, indefinitely |
| **D15** | **FIRED** | NO-DEFENCE | VERIFIED | **VERIFIED DEFECT — MEDIUM — FIXED** | a socket (then a permanent SSE stream) survives unmount; StrictMode double mount leaks in dev |
| D9 | — | CODE-INNOCENT (owner: backend enum) | VERIFIED | **CLEARED** | none |
| D2 | not run | — | HYPOTHESIS | **DEFERRED → W8** (needs a public-interface decision) | rail silently stops updating |
| D13 | — | — | OBSERVATION | **OBSERVATION** (owner: backend) | a long `running` session can miss rows across a reconnect |

`D1` and `D12` interact (both in `startSessionSSE`), so their fixes are merged into a single
function-level change: fixing the parser alone would still leave the mode lying whenever the
stream is idle, and fixing the mode alone would turn "Live, silent" into "Offline, silent".

---

## Phase 5 — fix design

### 5a Placement

| Defect | Owner of the violated property | Placement |
|---|---|---|
| D12 | the provider that reads the stream | `providers/EventStreamProvider.tsx` — owner-justified |
| D1 | the provider that writes `mode` | same function — owner-justified |
| D15 | the provider that tears connections down | its teardown effect — owner-justified |

No `DEFENSE-IN-DEPTH` guard was added anywhere, no lower layer was patched to mask an upper
contract failure, and nothing was moved across a module boundary.

### 5b Mechanism

Rung 1 (reuse the existing idiom) for all three: the SSE pump stays a plain async reader, the pool
keeps owning connection state, teardown keeps closing through `closeSessionConnection`.
`[PATTERN-NOT-WARRANTED]` everywhere — no new pattern, no new dependency, no new hook.

### 5c Conformance

- no new import; `lib/` untouched (no React there); no `fetch` added outside `lib/api.ts`
  (the existing one is unchanged)
- no new global mutable state; no ceiling touched; `tasks/quality/ceilings.toml` unchanged
- public interfaces unchanged: `EventStreamContextValue`, exported hook shapes, `types/events.ts`
  unions all identical
- `npm run lint` 0/0, `npx tsc --noEmit` 0, `npx vitest run` 14/85, `npx next build` OK,
  `lint_ui_debt` all six at ceiling — all re-run *after* the change (§10)

### Diff

```diff
--- a/weebot-ui/src/providers/EventStreamProvider.tsx
+++ b/weebot-ui/src/providers/EventStreamProvider.tsx
@@ -127,13 +127,21 @@
           const { done, value } = await reader.read();
           if (done) break;
           buffer += decoder.decode(value, { stream: true });
-          const lines = buffer.split("\n\n");
-          buffer = lines.pop() ?? "";
-          for (const chunk of lines) {
-            const dataLine = chunk.split("\n").find((l) => l.startsWith("data:"));
-            if (!dataLine) continue;
+          // Frames end at a blank line, which the producer (sse_starlette) writes as
+          // CRLF; bare LF is legal SSE too. Splitting on "\n\n" alone dropped every
+          // frame the backend actually sends.
+          const frames = buffer.split(/\r?\n\r?\n/);
+          buffer = frames.pop() ?? "";
+          for (const frame of frames) {
+            // A frame may carry several `data:` lines; the payload is their join.
+            const data = frame
+              .split(/\r?\n/)
+              .filter((line) => line.startsWith("data:"))
+              .map((line) => line.slice(5).replace(/^ /, ""))
+              .join("\n");
+            if (!data) continue;
             try {
-              const event = JSON.parse(dataLine.slice(5).trim()) as AgentEvent;
+              const event = JSON.parse(data) as AgentEvent;
@@ -143,8 +151,15 @@
       } catch {
-        // aborted or network error — connection just stays closed;
-        // the consumer's next subscribe() call will retry from WS.
+        // Aborted (teardown) or the stream died — settled in `finally`.
+      } finally {
+        // The stream is over. Leaving mode at "sse" kept the AppBar claiming "Live"
+        // over a feed that delivered nothing, forever.
+        if (!controller.signal.aborted) {
+          conn.sseController = null;
+          conn.mode = "closed";
+          forceRender((n) => n + 1);
+        }
       }
@@ -286,8 +301,15 @@
     const connections = sessionConnections.current;
+    const presence = presenceListeners.current;
     return () => {
-      connections.forEach((conn, id) => closeSessionConnection(id, conn));
+      connections.forEach((conn, id) => {
+        // Clear first: the close event would otherwise see a non-empty listener set
+        // and schedule a reconnect for a provider that no longer exists.
+        conn.listeners.clear();
+        closeSessionConnection(id, conn);
+      });
+      presence.clear();
       presenceWsRef.current?.close();
     };
```

**Causal justification.** D12's mechanism was "the parser's frame boundary does not occur in the
producer's bytes"; the fix splits on the separator the producer actually emits, and joins multi-line
`data:` fields, which is what the SSE format defines. D1's mechanism was "no terminal path writes
`mode`"; the fix writes it once, on the only two terminal paths, and skips the abort case because
teardown already owns that transition. D15's mechanism was "the close handler reads a listener set
that teardown never empties"; the fix empties it before closing.

**Risk.** Scope LOCAL → MODULE (provider only) · Side effects: one extra render on stream end · Regression risk LOW · Reversibility TRIVIAL (revert the hunk).

### Residual of D1: the fallback is now honest, not immortal

After the fix, a dead fallback reads `closed` and the dot turns Offline, but nothing re-opens it
while the page stays mounted — `subscribeSession` only connects when no pool entry exists. Fixing
*that* means calling the WS connector from inside the SSE pump, which is a cross-boundary mechanism
(`> 1 function`, and a callback cycle) → `[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`.

- **MINIMAL (shipped):** truthful mode. Removes the lie; the user can act (reload/navigate), which
  is strictly better than a silent dead feed. Masks: no automatic recovery.
- **ARCHITECTURAL (not shipped):** on terminal SSE failure, delete the pool entry and re-enter
  `connectSessionWs` for the surviving listeners, resetting `reconnectAttempts` — a bounded
  retry ladder that alternates transports. Recommend it as the next transport change, with the
  caveat that alternating forever needs a backoff ceiling and a visible "reconnecting" state.

---

## Phase 6 — self-review (RAR), eight vectors

| # | Vector | Verdict | Evidence / reasoning |
|---|---|---|---|
| 1 | Boundary | FIX HOLDS `[VF]` | tests: CRLF frame, bare-LF frame, frame split across two reads, `data:`-less frame skipped (`if (!data) continue`), empty body end |
| 2 | Invalid input | FIX HOLDS `[VF]` | malformed JSON still contained in the inner `try`; a frame with no `data:` line is skipped rather than throwing; `JSON.parse("")` is unreachable because `!data` returns first |
| 3 | State | FIX HOLDS `[VF]` | abort during the pump skips the terminal write (`signal.aborted`), so teardown keeps ownership; unmount path proven by D15's test |
| 4 | Regression | FIX HOLDS `[VF]` | 85/85 tests, `next build` 11 routes, six debt counters unchanged, contrast unchanged |
| 5 | Concurrency | FIX HOLDS `[HYP]` | single pump per connection, `forceRender` is monotonic; a second subscriber shares the same `conn`, so `listeners.forEach` during a frame is unchanged. Real interleavings still need a browser (residual risk) |
| 6 | New defect | FIX HOLDS `[VF]` | re-ran C1–C10 over the changed file: no new timer, no new fetch, no new listener; the only added state write is on a terminal path |
| 7 | Architecture conformance | FIX HOLDS `[VF]` | `eslint` 0/0 (both layer blocks), `lib/` untouched, no `fetch` outside `lib/api.ts`, no ceiling change |
| 8 | Paradigm consistency | FIX HOLDS `[VF]` | provider stays the single mediator of connection state; the pump remains a plain async reader; no state library, no pattern introduced |

No `FIX BREAKS`; `fix_revisions` = 0.

---

## Phase 7 — tests

`src/providers/EventStreamProvider.test.tsx` (new, 6 tests) + `tests/harness/fake-transport.test.ts`
(harness self-test, 4).

| Test | Role |
|---|---|
| `D12: delivers a frame encoded the way sse_starlette encodes it` | proof-of-defect (failed at HEAD) |
| `D12 boundary: … separators are bare LF` | regression — LF parsing still works |
| `D12 boundary: a frame split across two reads` | boundary — buffer reassembly |
| `D1: stops reporting a live subscription once the stream is over` | proof-of-defect (failed at HEAD) |
| `D1 boundary: a failed stream is not reported as live either` | boundary — error path |
| `D15: unmounting the provider does not open a replacement socket` | proof-of-defect (failed at HEAD) |
| `fake transport harness` ×4 | instrument: fake socket lifecycle, deterministic reconnect delay, SSE push/end, abort tracking |

Convention followed: colocated `*.test.tsx` under the module's directory, `tests/harness/` for
shared, non-test helpers — same split the repo already uses (`src/**/*.test.ts(x)` +
`tests/smoke.test.tsx`).

---

## Phase 8 — verdict

### Process checks

| Check | Status |
|---|---|
| Defect is VERIFIED (trigger fired + no innocence defence) | ✅ ×3 |
| Fix ≤15 lines and ≤1 function (D12: 1 function; D1: 1 function; D15: 1 effect) | ✅ |
| Proof + boundary + no-regression tests (≥3) | ✅ (6) |
| Phase 0 census complete | ✅ |
| Fix in the invariant-owning layer | ✅ provider owns mode, pool and teardown |

### Engineering checks

| Check | Status |
|---|---|
| All self-review vectors FIX HOLDS or CANNOT DETERMINE | ✅ (one `[HYP]`) |
| Regression risk LOW/MEDIUM | ✅ LOW |
| Fix is causal, not symptomatic | ✅ |
| No unresolved fix interaction | ✅ D1+D12 merged deliberately |
| No dependency-rule violation / abstraction bypass | ✅ |
| No pattern introduced | ✅ |

**Routing: ACCEPT** for D12, D1, D15. **ESCALATE** D2 (public-interface decision). **PARTIAL** for
the wave: R3 (presence), R4 (`useSessionEvents` polling — 1 timer per subscriber, O3), R5
(`useSessionList` merge beyond D9), R6 (`useBehavior`) and R7 (`useWebSocketDebug`) were not
triaged beyond the map.

### Coverage statement

```
Surface audited:            R1 (SSE pump + fallback), R2 (per-session lifecycle + teardown),
                            R5 partially (status vocabulary); R3/R4/R6/R7 mapped only
Surface NOT audited:        R3 presence reconnect policy, R4 polling arity, R6 useBehavior
                            (second socket stack), R7 useWebSocketDebug; e2e/DOM behaviour
                            (browser blocked)
Defect classes covered:     C2, C6, C8, C10 (C3 partially, by review only)
Architecture census basis:  VF (README §Source layout, two eslint layer blocks, ceilings.toml,
                            tsc --strict); the provider-as-owner placement is [VF]
Confirmed defects:          CRITICAL 0 / HIGH 2 / MEDIUM 1 / LOW 0   (all fixed)
Cleared (innocent):         1 (D9)      Re-attributed to owner: 1 (D13 → backend contract)
Observations:               2 (D1-residual, D2 deferred)
Residual UNKNOWN:           D2, D13, and every C3 interleaving that needs a real browser
Clean-claim scope:          "R1 and R2 were audited for C2/C6/C8/C10 and no VERIFIED defect
                            remains unfixed there."  ← not "the transport is bug-free".
Highest-value next hunt:    R3 + R6 — the two other socket stacks, which duplicate R2's
                            teardown/reconnect shape and share none of its tests.
```

---

## 9. Recommendation carried to W8 (not implemented)

1. **D2:** give the context a `presenceState` (`connecting | live | degraded`) and set it to
   `degraded` when the retry ladder is exhausted; the rail then shows a "not updating" hint instead
   of freezing silently. Public interface change → owner decision.
2. **D1-residual:** alternate WS↔SSE with a backoff ceiling and a visible `reconnecting` mode.
3. **Single transport owner:** `ops/page.tsx` and `useBehavior` each open their own socket with
   their own retry policy; fold them into the pool, then delete their bespoke reconnect code. This
   is a refactor, not a fix — it belongs in its own change with the e2e suite runnable.
4. **Type tightening (D9):** `SessionPresenceEvent.status: SessionStatus` on the TS side once the
   backend field is typed as the enum in the OpenAPI/pydantic surface. Removes the cast; no
   behaviour change.

## 10. Uncertainty acknowledgment

**Finding most likely to be a false positive.** D15. The mechanism is verified in the harness, but
in production the provider unmounts only with the page, so the leak's real-world exposure is
development (StrictMode) rather than user-facing. It is filed MEDIUM for that reason.

**Real defect most likely missed.** `useBehavior` (R6): a second socket stack, 252 lines, four
`console.log`s, its own reconnect loop and no tests — the same shape as the three defects found
here, unaudited for budget.

**Architectural claim most likely wrong.** "The provider owns connection state" is `[VF]` for
`mode`, but the *observable* `Live` dot is derived in `useSessionEvents` by polling a
non-reactive ref every second — so between a state change and the next tick the display is stale by
design. Any C10 fix placed in the provider inherits that 1 s lag.

**What requires runtime validation.** D2's exhaustion (needs a policy decision, not more evidence);
real proxy behaviour for SSE (some middleboxes do re-frame to LF, which is why the fix accepts
both); every C3 interleaving across the three socket stacks.

**What static analysis cannot determine.** StrictMode's double-mount consequences in production
mode; whether a deployment's proxy blocks WS (which decides how often R1 is even reached); real
reconnect timings.

**What additional input would most increase confidence.** A browser-capable runner for
`npm run test:e2e` (W0/H3, still open); one recorded session's socket trace as a golden fixture; an
ADR stating the intended policy when a transport gives up — which is exactly the decision D2 needs.

## 11. Commands

```bash
cd weebot-ui
npx vitest run src/providers/EventStreamProvider.test.tsx   # 6 passed (5 failed before the fix)
npx vitest run                                              # 14 files, 85 tests
npx tsc --noEmit                                            # 0
npm run lint                                                # 0 errors, 0 warnings
npx next build                                              # OK, 11 routes

cd ..
python3 scripts/lint_ui_debt.py                             # 6 counters at ceiling
python3 scripts/check_ui_contrast.py                        # 58 pairs >= 4.5:1

# the producer's actual wire format (this is what D12 was measured against)
python3 -c "from sse_starlette.event import ServerSentEvent as S; print(repr(S(data='{\"a\":1}', event='message').encode()))"
```
