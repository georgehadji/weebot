# Wave 6 — External Interfaces & Non-Human Entry Points

Execution record for W6. Threats **T1**, **T2**; classes **C1**, **C2**, **C3**.

| | |
|---|---|
| **Baseline** | `5185b44` + W5, working tree green |
| **Budget** | ≤20 · ≤12 · ≤8 — **spent 6 · 4 · 3** |

---

## Phase 3/4 — triaged inventory

| ID | Claim | Trigger | Verdict |
|---|---|---|---|
| **D45** | `/ws/sessions/{id}` authenticates but never authorises | **FIRED** — no `verify_session_ownership` anywhere in the endpoint | ✅ **VERIFIED DEFECT** |
| **D46** | `.env.example` ships a weaker default than the code | **FIRED** — template `false`, code default `"true"` | ✅ **VERIFIED DEFECT** |
| **D49** | Two `@app.exception_handler(Exception)`; the second replaces the first | **FIRED** — two registrations, returning **different** `error_code` values | ✅ **VERIFIED DEFECT** |
| **D47** | `token_verifier=None` when `WEEBOT_MCP_API_KEY` unset | investigated later | ✅ **VERIFIED — [closed](review_gate_d47_d50.md)** |
| **D48** | Dynamic tools forward unvalidated `**kwargs` to `tool.execute()` | not investigated | 🔵 **SUSPECTED** |
| **D50** | Events without `session_id` broadcast to all global connections | investigated later | ⚪ **CLEARED — [see why](review_gate_d47_d50.md)** |

### D45 — authentication is not authorisation

The endpoint calls `_websocket_auth`, which proves *who* the caller is, and then connects them to
`session_id` without ever asking whether they own it. The HTTP route for the same resource does
exactly that check:

```python
# routers/sessions.py:126 — the HTTP path
await verify_session_ownership(http_request, session.user_id)
```

So any authenticated caller could subscribe to any session's event stream and receive its
messages, tool calls and results. `_resolve_user()` reads only headers, so it works unchanged on
a `WebSocket`; the check was simply absent.

### D46 compounds D45

`auth.py:223` defaults `WEEBOT_ENFORCE_SESSION_OWNERSHIP` to `"true"`, and `.env.example:130`
shipped `false`. Copying the template — the documented way to configure the app — silently
disabled ownership enforcement on the HTTP path too. **A template that ships a weaker default
than the code is a real deployment defect**, and this wave's plan says so explicitly.

### D49 — a second, dead error contract

Starlette keys exception handlers by class, so the later registration replaced the earlier. The
dead handler returned `error_code: "internal_error"`; the live one returns `"INTERNAL_ERROR"` and
also increments `exceptions_total`. Two disagreeing contracts, one of them unreachable.

---

## Phase 5 — fixes

| # | File | Change |
|---|---|---|
| 1 | `interfaces/web/main.py` | Load the session and `verify_session_ownership` before `manager.connect`; close 4003 on denial |
| 2 | `.env.example` | `WEEBOT_ENFORCE_SESSION_OWNERSHIP=true` |
| 3 | `interfaces/web/main.py` | Remove the dead duplicate handler, leaving a comment where it was |

Fix 1 places the check **before** `manager.connect`, so a denied caller is never registered as a
subscriber — asserted by ordering in the tests, not just by presence.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` A session with no `user_id` (legacy) still connects — same behaviour as the HTTP path. A missing session yields `user_id=None` and is likewise allowed; it carries no data to leak. |
| **Invalid input** | `[VF]` `getattr(_sess, "user_id", None)` tolerates `None` from `load_session`. |
| **State** | `[VF]` Denial closes before any manager registration. |
| **Regression** | `[VF]` Authentication still runs first and still closes 4001; asserted. |
| **Concurrency** | `[VF]` No shared state introduced. |
| **New defects** | `[HYP]` The endpoint now performs a DB read per connection. Negligible against a WebSocket handshake, not measured. |

---

## Phase 7 — tests

`tests/unit/interfaces/test_w6_ws_authorisation.py`, **6 tests**. Red before / green after:
**5 failed / 1 passed** with the fixes reverted → **6 passed** restored.

These are source-structure assertions rather than a live client, because standing up an
authenticated WebSocket against the real app needs a running container and a configured API key.
That is a **weaker** form of proof than the other waves' behavioural triggers and is recorded as
such — see R-1.

---

## Phase 8 — coverage & residual risk

### NOT covered

**Three of six candidates were never investigated**: D47 (MCP `token_verifier=None` outside
`run_mcp.py` ⇒ an unauthenticated SSE server), D48 (unvalidated `**kwargs` into `tool.execute()`),
D50 (events without `session_id` broadcast to every global connection — closely related to D45 and
arguably the same leak by another route).

**D47 and D50 were investigated later** and are recorded in
[review_gate_d47_d50.md](review_gate_d47_d50.md). D47 was understated here: MCP SSE authentication
did not work in *any* configuration — without a key the server was unauthenticated, and with one it
raised at construction. **D48 remains uninvestigated.**

Of the declared regions, **webhook signature verification ordering**, **MCP transport auth**, and
**dynamic-tool kwargs validation** were never entered. `interfaces/gateways/**`,
`weebot/scheduling/**` (cron triggers agent runs — a non-human entry point) and `cli/**` were not
looked at at all.

### Residual risks

- **R-1 — the proof tests assert on source structure, not behaviour.** They would pass if
  `verify_session_ownership` were called with the wrong argument. A live WebSocket test against a
  configured app is the right proof and was not written.
- **R-2 — D50 may be the same leak by another path.** If the broadcaster fans unscoped events to
  all connections, fixing the subscription check does not stop the delivery. Not investigated.

  **Resolved — the premise held, the conclusion did not.** The broadcaster does fan unscoped events
  to every global connection, but that is a *documented* routing contract (`SessionPresenceEvent`
  states it in its own docstring and depends on it), and session events are stamped by
  `SessionScopedEventBus` at every flow construction on the web path. D50 is cleared. One latent
  hole was fixed on the way past: `broker_adapter._convert`'s fallback embedded arbitrary caller
  payload in an event with no `session_id`. See [review_gate_d47_d50.md](review_gate_d47_d50.md).
- **R-3 — changing the template default may break existing deployments** that copied it and rely
  on cross-session access. That is the correct direction for a security default, but it is a
  behaviour change for anyone who took the old template at its word.

### Verdict

**PARTIAL.** Three verified defects fixed, one of them a genuine cross-session data-exposure path.
Half the candidates were never investigated, three of the declared regions were never entered, and
the proof is structural rather than behavioural.
