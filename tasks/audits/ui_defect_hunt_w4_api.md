---
status: reference
date: 2026-10-31
---

# Wave 4 — API client, proxy & credentials

Execution record for W4 of [`tasks/specs/ui_defect_hunt_v71_execution_plan.md`](../specs/ui_defect_hunt_v71_execution_plan.md).
Threats **T1** (credential exposure), **T2** (silent wrong state); classes **C4, C5, C6, C8** (+ C9 for the duplicated readers).
Structure follows [`ui_defect_hunt_w1_transport.md`](ui_defect_hunt_w1_transport.md). Every `[VF]` came from a run (commands in §9).

## Phase 0-WAVE

| | |
|---|---|
| Baseline | `fix/ui-defect-hunt`, W0 harness present; `tsc` 0, `lint` clean |
| Budget | <=15 generated, <=10 investigated, <=5 fixed |
| Spent | **15 generated, 10 investigated, 4 fixed** (D4 incl. its Safari half, 422 detail, D5, openSocket) |
| `?token=` check (decision D2) | `grep -rn "?token\|token="` over `src/`: **no producer left** in the UI; the only mention is the explanatory comment in `lib/api.ts`. All five socket sites (`EventStreamProvider` x2, `ops/page`, `useBehavior`, `useWebSocketDebug`) go through `openSocket`. The SSE fallback sends the key as `X-API-Key`. |

## Phase 1 — region map

| R | Region | Layer | Classes | Reachability | Blast |
|---|---|---|---|---|---|
| R1 | `api.ts` `fetchApi` error mapping | lib | C4, C6 | REACHABLE: every REST call | SYSTEM |
| R2 | `route.ts` proxy body/status/header relay | app | C8, C6 | REACHABLE: every `/api/*` call when `weebot_backend_url` is unset | SYSTEM |
| R3 | key storage + transmission (`api.ts`, `ConnectionStatus`, `EventStreamProvider.getWsToken`) | lib/components | C5 | `api.ts` REACHABLE; **`ConnectionStatus` DEAD** | EXTERNALLY-VISIBLE |
| R4 | base-URL precedence (5 readers) | lib/providers/app | C9, C8 | REACHABLE | MODULE |
| R5 | `endpointsFrom` `/ws` stripping | lib | C8 | REACHABLE | LOCAL |

Atomic assertions: (1) **[VF]** `ConnectionStatus` is imported nowhere (`grep -rn ConnectionStatus` hits only its own file and one comment in `api.ts`), so nothing in the shipped UI ever *writes* `weebot_api_key`; the key can only be set by hand in devtools. (2) **[VF]** the backend takes the `bearer.<key>` subprotocol verbatim, with no decoding (`weebot/interfaces/web/auth.py:94-95`). (3) **[VF]** no backend route under `/api` returns 204 (`DELETE /sessions/{id}` returns a JSON body, `sessions.py:227`); `health.py:286` returns `PlainTextResponse` (metrics) and `chat_router.py:146` an `EventSourceResponse`, both non-JSON.

## Exit-criterion table: storage key -> readers -> precedence

| Storage key (store) | Writers | Readers | Precedence / fallback |
|---|---|---|---|
| `weebot_backend_url` (localStorage) | `settings/page.tsx:28` (no trim; **initial state is `ENDPOINTS.origin`, so any Save pins `http://localhost:8000`**) | `api.ts getApiBase` (trim) · `ConnectionStatus.healthUrl` (trim, **dead, unguarded `getItem`**) · `EventStreamProvider.getStreamUrls` (SSE fallback) · `settings/page.tsx:17` (display) | REST (`api.ts`): stored -> **`/api` (same-origin proxy)**. SSE fallback (`EventStreamProvider:90`): stored -> **`ENDPOINTS.api` (direct, absolute)**. Different fallbacks: with nothing stored, REST rides the proxy (and its CSRF guard) while SSE goes straight to `localhost:8000`, which on a LAN-opened console is the viewer's own machine. Owner of the SSE reader is W1/W6: **deferred**. |
| `weebot_ws_url` (localStorage) | `settings/page.tsx:29` | `EventStreamProvider.getStreamUrls` · `ops/page.tsx getWsBase` · `settings/page.tsx:22` | stored (trim) -> `ENDPOINTS.ws` (`NEXT_PUBLIC_WS_URL` -> `ws://localhost:8000/ws`). The two socket readers agree. **`useBehavior` ignores it**: it uses `ENDPOINTS.behaviorWs` (env/default only), so a configured WS URL moves the event sockets but not the behavior socket. Owner `hooks/useBehavior.ts`: **deferred (W5)**. |
| `weebot_api_key` (sessionStorage) | `ConnectionStatus` only (**dead**) | `api.ts _getApiKey` (REST header, `openSocket` default, `authHeaders`) · `EventStreamProvider.getWsToken` (inline copy; feeds `openSocket` and the SSE `X-API-Key`) · `ConnectionStatus.probeBackend` (dead) | One key, one store, no fallback. Transport: REST/SSE `X-API-Key`; sockets `Sec-WebSocket-Protocol: weebot.v1, bearer.<key>`. Never in a URL. A key saved after sockets opened does not reach them until they reconnect (W1 note). |
| env `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` (build) | build | `endpoints.ts` (only reader) | env -> `http://localhost:8000/api` / `ws://localhost:8000/ws`; `behaviorWs` and `origin` derived from these two. |
| env `BACKEND_URL` (server) | deploy | `route.ts:5` | `BACKEND_URL` (**must include `/api`**, per `audit_2026_10_27_fix_plan.md` W1.4) -> `ENDPOINTS.api`. `next.config.mjs` also rewrites `/api/:path*` to `localhost:8000`; the route handler matches first, so the rewrite is dead for `/api` today (observation, config owner). |
| `weebot_theme`, `weebot_draft:*` | out of W4 | - | not credentials or URLs |

## Phase 2/3/4 — candidates and inventory

| ID | Property violated | Class | Trigger | Innocence attempt | Status | User-visible consequence |
|---|---|---|---|---|---|---|
| **D4** | the surfaced error names the real failure | C4, C6 | **FIRED** (3 tests: detail containing "connect", detail containing "fetch", `TypeError("Load failed")`) | Guard: none. Reachability: a 409/502 detail such as "Failed to fetch model list" is ordinary. Owner is `fetchApi`, which classified by `message.includes`. Safari's network error ("Load failed") has neither word, so it was not classified either. | **VERIFIED, MEDIUM, FIXED** | "Cannot connect to backend" for a reachable backend (wrong remediation); raw "Load failed" on Safari |
| **422** *(new)* | a validation error is readable | C6, C8 | **FIRED**: `detail:[{msg}]` -> `Error("[object Object]")` | Contract owner: FastAPI's default `RequestValidationError` handler returns `detail` as a list; only `HTTPException` is rewritten (`main.py:569`). No defence. | **VERIFIED, MEDIUM, FIXED** | any 422 reads `[object Object]` |
| **D5** | the proxy preserves upstream semantics | C8, C6 | **FIRED**: 204 makes `NextResponse.json(null,{status:204})` throw, so the handler answers **503 "Failed to connect"** for a successful call; text/plain becomes JSON `null`; a 502 text body becomes `null` | The seed's innocence ("all routes JSON, none 204") is half true: no 204 route exists today, but `health.py:286` (metrics, text/plain) is under `/api` and is mangled. The proxy is generic, so the property is the proxy's. | **VERIFIED, MEDIUM, FIXED** | metrics endpoint returns `null`; any future 204 reads as an outage |
| **O-key** | a key can always be sent on a socket | C5, C8 | **FIRED**: key `a/b==` makes `new WebSocket(url,[..., "bearer.a/b=="])` throw `SyntaxError` (also reproduced against jsdom's real `WebSocket`) | The backend does not decode, so the UI cannot encode; the contract is "key is a token". Reachability: the key is an arbitrary operator string (`WEEBOT_API_KEY`); base64 with `/` or `=` is common. Thrown inside effects (provider, `/ops`, `useBehavior`), so it reaches the error boundary. | **VERIFIED, MEDIUM, FIXED (containment)** | the page crashes at mount for such a key |
| ConnectionStatus `healthUrl` | a storage read cannot misreport state | C4, C9 | `localStorage.getItem` is unguarded and a second copy of `getApiBase`; throwing storage makes the probe say "Cannot connect" | **DEAD**: the component is mounted nowhere | **CODE-INNOCENT by reachability (DEAD)**; recorded, not fixed | none today |
| ConnectionStatus has no caller | the UI offers a way to set the key | C9, T1 | grep | - | **OBSERVATION** (owner decision: mount or delete; today an authed backend is unusable from the UI without devtools) | users with `WEEBOT_API_KEY` get 401 and no input |
| `behaviorWs` ignores the stored WS URL | one source for the socket URL | C8, C9 | read, grep | not triggered | **DEFERRED -> W5** (fix is in `useBehavior`) | the behavior page talks to a different host than the rest |
| SSE fallback base differs from REST base | one base-URL rule | C9 | table above | not triggered | **DEFERRED -> W1/W6** (`EventStreamProvider:90`) | on a LAN the SSE fallback targets `localhost:8000` |
| proxy `..` / `%3F` in decoded segments | the proxy stays under `/api` | C5 | not triggered. WHATWG URL parsing collapses `%2e%2e` before Next sees it; Next's own parser may not (**[UNK]**, needs a running Next, and `next build` is off limits this wave) | still the same host and backend auth | **UNKNOWN**; hardening candidate: reject `.`/`..` segments | none proven |
| `endpointsFrom` `/ws` strip | `behaviorWs` is right for any WS URL | C8 | a WS URL not ending in `/ws` yields `.../<x>/api/behavior/ws` | documented contract: the env value ends in `/ws` (test and comment) | **CLEARED** (contract owner) | - |
| `fetchApi` success on 204 | `json()` of an empty body | C4 | would throw `SyntaxError` | no `/api` route returns 204; the proxy now relays 204 honestly | **CLEARED** (no such route) | - |
| proxy drops upstream headers (`Retry-After` ...) | headers survive | C8 | read | nothing in the UI reads them | **OBSERVATION** | - |
| `sessions.list` + `URLSearchParams(undefined)` | no `status=undefined` | C6 | read | the only callers pass `{limit}` | **OBSERVATION** (latent) | - |
| ConnectionStatus 401 text after a wrong key | message matches cause | C10 | read | dead component | **OBSERVATION** | - |
| `?token=` remnant in the UI | nothing relies on the query string | C5 | grep | none found | **CLEARED** | - |

Counts: generated 15; investigated 10 (D4, 422, D5, O-key, healthUrl, behaviorWs, SSE base, `..`, endpointsFrom, 204).

## Phase 5 — fixes (owning layer, no new dependency, no ceiling change)

| Defect | Placement | Change |
|---|---|---|
| D4 + Safari | `lib/api.ts fetchApi` (owner of error mapping) | wrap only the `fetch()` call; its rejection is the connection error. The HTTP-error branch is no longer inside the classifying `catch`; the string match and the outer `try` are gone |
| 422 | same function | `detail` array -> its `msg` values joined by `; ` |
| D5 | `app/api/[[...path]]/route.ts handler` | relay `arrayBuffer()` and the upstream `content-type`; `null` body for 204/205/304 |
| O-key | `lib/api.ts openSocket` | `try/catch` the constructor; `console.warn` and open without the subprotocol. The server closes the anonymous socket, the provider falls back to SSE, which carries the key as a header |

Not shipped: refusing such keys at entry (`ConnectionStatus`) is dead code; encoding the key needs a backend change, `[REQUIRES HUMAN REVIEW: contract]` (the backend would have to decode, `auth.py:94`).

`fetchApi` is one function carrying two defects (D4, 422); the fixes interact, so they ship as one change. Public signatures of `api.*`, `openSocket`, `getApiBase`, `authHeaders` are unchanged. `lib/` stays React-free.

## Phase 6 — self-review

| Vector | Verdict |
|---|---|
| Boundary | HOLDS [VF]: `{}` body -> `HTTP 500`; 204 relayed with an empty body |
| Invalid input | HOLDS [VF]: non-JSON error body -> `statusText`; non-JSON upstream passes through untouched |
| State | HOLDS [HYP]: the `openSocket` fallback yields a socket the server closes; the reconnect ladder and SSE fallback (W1) take over |
| Regression | HOLDS [VF]: Chrome's "Failed to fetch" still classified; JSON passthrough and 503-on-unreachable tests; the existing proxy tests (CSRF, header forwarding) stay green |
| Concurrency | n/a (stateless) |
| New defect | watch-item: the proxy now buffers via `arrayBuffer()`; fine for the JSON/text routes that exist, not for streaming (SSE through the proxy was already broken; the UI uses the direct URL) |
| Architecture | HOLDS [VF]: no new `fetch`, no React in `lib/`, `eslint` clean |
| Paradigm | HOLDS: still the single adapter and a plain handler |

## Phase 7 — tests

`src/lib/api.test.ts` (new, 7), `src/lib/open-socket.test.ts` (+2), `src/app/api/[[...path]]/route.test.ts` (+5). Seen **failing before the fix** (8 failures: D4 x3, 422, openSocket, D5 x3), passing after. The proxy test required by the exit criteria is `D5: a 204 stays a 204 with no body` (before the fix: `expected 503 to be 204`).

## Phase 8 — verdict and coverage

Routing: ACCEPT for D4, 422, D5, O-key. PARTIAL for the wave (`ConnectionStatus` unaudited beyond mapping because it is dead; the behavior and SSE base readers deferred).

```
Surface audited:            R1 fetchApi, R2 proxy, R3 key transmission (api.ts, openSocket), R4 mapped
                            across all five readers, R5 endpointsFrom
Surface NOT audited:        ConnectionStatus behaviour (DEAD), proxy path traversal (needs a running
                            Next), e2e/DOM (browser blocked)
Defect classes covered:     C4, C5, C6, C8 (C9 for reader duplication)
Architecture census basis:  VF (eslint layer rules, tsc strict)
Confirmed defects:          CRITICAL 0 / HIGH 0 / MEDIUM 4 / LOW 0   (all fixed)
Cleared (innocent):         4 (healthUrl via DEAD, endpointsFrom, 204 on the success path, ?token= remnant)
Re-attributed to owner:     2 deferred (behaviorWs -> useBehavior, SSE base -> EventStreamProvider)
Observations:               5
Residual UNKNOWN:           `..` / encoded-segment behaviour of the proxy under a live Next
Clean-claim scope:          "R1, R2, R5 and the key-transmission path in api.ts were audited for C4,
                            C5, C6, C8 and no VERIFIED defect remains unfixed there."
Highest-value next hunt:    the base-URL readers outside this surface (behaviorWs, SSE base, the
                            settings page pinning the default origin on Save)
```

## Deferred / needs a decision

1. `hooks/useBehavior.ts`: honour `weebot_ws_url` (W5).
2. `providers/EventStreamProvider.tsx:90`: the SSE base falls back to absolute `ENDPOINTS.api` while REST falls back to `/api`; `getWsToken` is a second copy of `_getApiKey` (W1/W6). `ops/page.tsx:40` reads `weebot_ws_url` inline (W5).
3. `settings/page.tsx`: initial state is `ENDPOINTS.origin`, so any Save pins `weebot_backend_url` to the default and silently moves REST off the proxy (W5).
4. `ConnectionStatus`: mount it (it is the only way to set `weebot_api_key`) or delete it and add an entry point for the key. Owner decision.
5. Backend contract: percent-decode `bearer.<key>` so any key is expressible; then the UI can `encodeURIComponent` it.
6. Proxy hardening: reject `.`/`..` segments once reachability is proven with a live Next.

## 9. Commands

```bash
cd weebot-ui
npx vitest run src/lib/api.test.ts src/lib/open-socket.test.ts src/app/api   # 19 passed (8 failed before the fix)
npx vitest run
npx tsc --noEmit
npm run lint
```

Uncertainty: the finding most likely to be a false positive is O-key (severity depends on how operators pick keys); the most likely miss is the proxy's encoded-path handling.
