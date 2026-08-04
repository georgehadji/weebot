# Weebot Mission Center — Implementation Plan

**Status:** proposed
**Date:** 2026-08-03
**Scope:** `weebot-ui/` (Next.js 16 / React 19) + the web interface + transport layers of `weebot/`
**Goal:** turn the current session-log viewer into a professional, contemporary mission
center — a persistent operations console with real, always-available conversation.

---

## 0. Objective

Today the UI is a set of centered pages that render a stored event list. The target is a
single persistent console where a session is a *conversation you can steer*, with plan,
tools, cost and trust visible beside it.

Three things must become true:

1. **Events arrive live, per session.** (Today they do not arrive at all — see RC-1.)
2. **The composer is always usable.** Chat, task-start, mid-run steering and answer-a-question
   all funnel through one input.
3. **The shell is a console**, not a document: three panes, dense, dark, semantic status colour.

This plan is ordered so that each phase is independently shippable and independently
revertible. Phase 0 and 1 are backend; nothing in the UI can feel live until they land.

---

## 1. Root-cause findings (verified against source)

| ID | Finding | Evidence | Impact |
|----|---------|----------|--------|
| **RC-1** | **The WebSocket event transport is not connected at either end.** `WebSocketEventBroadcaster` is defined but never instantiated or subscribed anywhere; `main.py` only ever calls `manager.connect/disconnect`. Nothing publishes to `ConnectionManager`. | [event_broadcaster.py:15](../../weebot/interfaces/web/event_broadcaster.py); no construction site in repo; [main.py:520-566](../../weebot/interfaces/web/main.py) | Session page shows "Waiting for events…" forever. Dashboard "Live Events" tab is permanently empty. |
| **RC-2** | **`BaseEvent` has no `session_id`.** Only 10 later event classes declare one. The broadcaster routes on `getattr(event, "session_id", None)`, so `message` / `step` / `tool` / `done` would fan out **globally** even once wired — never to `/ws/sessions/{id}`. | [event.py:31-35](../../weebot/domain/models/event.py) vs [event_broadcaster.py:37-43](../../weebot/interfaces/web/event_broadcaster.py) | Per-session streaming is structurally impossible without a correlation id. |
| **RC-3** | **The only working transport is unused by the UI.** `/api/events/stream` (SSE) genuinely subscribes to the bus. `useEventSource` / `useEvents` exist in the frontend and are imported by no page. | [sse.py:62](../../weebot/interfaces/web/routers/sse.py); `useEvents.ts`, `useEventSource.ts` have zero page consumers | A working pipe sits idle while the UI listens on a dead one. |
| **RC-4** | **Chat backend is fully built and never called.** `POST /api/chat`, `/api/chat/history`, `/api/chat/{id}` + `Container.build_chat_flow` + `ChatFlow` all exist. `lib/api.ts` has no chat client. | [chat_router.py](../../weebot/interfaces/web/routers/chat_router.py), [di/__init__.py:342](../../weebot/application/di/__init__.py), [chat_flow.py](../../weebot/application/flows/chat_flow.py) | The product's headline capability is dark. |
| **RC-5** | **Steering exists end-to-end except for the HTTP hop.** `SteeringPort` + `InMemorySteeringAdapter` are implemented and `PlanActFlow` polls steering between steps. But `create_plan_act_factory` takes no `steering` argument, `run_session` passes none, and no route exposes `send()`. | [steering_port.py](../../weebot/application/ports/steering_port.py), [plan_act_flow.py:91,122,148](../../weebot/application/flows/plan_act_flow.py), [task_runner.py:339-346](../../weebot/application/services/task_runner.py) | "Interject mid-run" is ~60 lines from working. |
| **RC-6** | **Composer is gated.** `if (!input.trim() \|\| !waitingForInput) return;` | [sessions/[id]/page.tsx:164](../../weebot-ui/src/app/sessions/[id]/page.tsx) | Cannot talk to the agent except when it asks. |
| **RC-7** | **Auto-scroll writes to a non-scrolling node.** `ref` lands on the Radix `ScrollArea` root; the scroller is the inner Viewport. | [sessions/[id]/page.tsx:220](../../weebot-ui/src/app/sessions/[id]/page.tsx) | Long sessions never follow. |
| **RC-8** | **Dark theme has no elevation and no brand.** `--card` == `--background`; dark `--primary` is near-white; `.dark` hardcoded on `<html>` so the whole light palette is unreachable. | [globals.css:36-42](../../weebot-ui/src/app/globals.css), [layout.tsx:20](../../weebot-ui/src/app/layout.tsx) | Cards invisible, buttons are white slabs, status colour is ad-hoc Tailwind. |
| **RC-9** | Light-only error surfaces inside forced dark mode (`bg-red-50`). | [sessions/page.tsx:94](../../weebot-ui/src/app/sessions/page.tsx), [sessions/[id]/page.tsx:80](../../weebot-ui/src/app/sessions/[id]/page.tsx) | Contrast failure on the most important messages. |
| **RC-10** | `alert()` used as the error channel (5 sites); `key={i}` on events; no dedupe of WS events against loaded history; 5s/10s polling despite a live bus; `BehaviorPanel` is inline-styled with hardcoded hex + emoji icon. | multiple | Cumulative "prototype" feel. |

> **Consequence:** RC-1 → RC-3 mean *nothing currently streams*. Any UI work done before
> fixing the transport is decoration on a dead wire. Hence Phase 0.

---

## 2. Architectural ground rules (non-negotiable)

Inherited from `CLAUDE.md` and enforced by `tests/unit/test_architecture_fitness.py`:

1. **Dependency rule** — `interfaces → infrastructure → application → domain`. The domain
   stays pure: no FastAPI, no asyncio primitives beyond stdlib types, no transport concepts.
2. **Ports & adapters** — every new capability enters through a port in
   `application/ports/`, with the adapter in `infrastructure/` (or `interfaces/` for
   transport-bound adapters, as the fitness test already whitelists for
   `WebSocketEventBroadcaster`).
3. **Immutability** — `Session`/`AgentEvent` are frozen Pydantic models mutated by
   `add_event` / `set_status` returning copies. No in-place mutation, front or back.
4. **Structured output** — agent-facing payloads validated via `weebot/models/structured_output.py`.
5. **Bash safety** — anything the UI can trigger that reaches a shell still routes through
   `weebot/core/bash_guard.py`. The Dashboard "code editor" must either honour this or be removed.
6. **File size** — 200-400 lines typical, 800 hard cap. Many small files over few large ones.
   The current `sessions/[id]/page.tsx` and `dashboard/page.tsx` both get decomposed.
7. **Frontend mirrors the same layering** — `types/` (domain) → `lib/` + `hooks/` (application)
   → `components/` (interface). No `fetch` inside a component.

---

## 3. Target architecture

### 3.1 Backend — the event spine

```
   PlanActFlow / ChatFlow
        │  publish(AgentEvent)
        ▼
   SessionScopedEventBus ......... Decorator: stamps session_id (correlation id)
        │
        ▼
   InMemoryEventBus (EventBusPort) ......... Observer registry
        ├──────────────► SSEStreamAdapter        (/api/events/stream, /api/chat/stream)
        ├──────────────► WebSocketEventBroadcaster ──► ConnectionManager
        │                                                ├─ /ws/sessions/{id}   (session fan-out)
        │                                                └─ /ws                 (global fan-out)
        └──────────────► EventStore / analytics sinks (unchanged)
```

**Design decisions**

| Concern | Choice | Why |
|---|---|---|
| Correlation | `session_id: str = ""` on `BaseEvent` | One field, inherited by all ~25 event classes. The alternative (per-class additions) is already half-done and inconsistent. Default `""` keeps every existing constructor call valid. |
| Stamping | **Decorator** `SessionScopedEventBus(EventBusPort)` in `application/services/` | Flows should not be responsible for tagging transport metadata. The decorator wraps the real bus with a bound `session_id` and `model_copy(update=...)`-stamps on publish. Domain purity preserved; no flow signature churn. |
| Wiring | **Composition root** — instantiate + subscribe the broadcaster in `main.py` lifespan | Adapters are wired once, at the edge. Nothing in application/ learns about WebSockets. |
| Backpressure | Bounded `asyncio.Queue(maxsize=N)` per subscriber, **drop-oldest** + a `dropped_count` counter surfaced on the wire | SSE today silently drops on full ([sse.py:57-59](../../weebot/interfaces/web/routers/sse.py)). Silent loss in an ops console is worse than a visible gap marker. |
| Absent transport | **Null Object** publisher | Keeps CLI/test paths free of `if broadcaster is not None`. |

### 3.2 Backend — conversational core

```
   POST /api/sessions/{id}/input          ← ONE endpoint, polymorphic
        │
        ▼
   InputDispatcher (application use case)  ← Strategy, selected by SessionStatus
        ├─ IDLE / FAILED  → StartTaskStrategy   → TaskRunner.start_session
        ├─ WAITING        → ResumeStrategy      → existing resume semantics
        ├─ RUNNING        → SteerStrategy       → SteeringPort.send
        └─ COMPLETED      → ChatStrategy        → ChatFlow (new turn)
```

One endpoint means the frontend composer never has to know which of four verbs applies —
it posts text and the backend resolves intent from state. Registered as a **CQRS command**
through the existing `Mediator` so it inherits the established handler pipeline.

**Streaming** is added by **interface segregation**, not by widening `LLMPort`:

```python
# application/ports/streaming_llm_port.py
@runtime_checkable
class StreamingLLMPort(Protocol):
    def stream(self, messages, **kw) -> AsyncIterator[LLMChunk]: ...
```

A structural `Protocol` (not an ABC) means the ~20 existing adapters need **no changes**.
Adapters that can stream opt in by implementing `stream`. A `NonStreamingLLMAdapter`
wrapper (**Adapter + Null Object**) yields the completed response as a single chunk, so
callers have exactly one code path.

### 3.3 Frontend — shell and state ownership

```
app/layout.tsx
└─ <Providers>                      Theme · Toast · CommandRegistry · EventStream
   └─ <ConsoleShell>                CSS Grid: rail | main | dock
      ├─ <TopBar/>                  breadcrumb · model · connection · cost · ⌘K
      ├─ <SessionRail/>             live list (WS-driven, no polling)
      ├─ <ConversationPane/>        virtualized timeline + <Composer/>
      └─ <MissionDock/>             compound: Dock.Plan | Tools | Cost | Trust
```

| State | Owner | Pattern |
|---|---|---|
| Transport connection | `EventStreamProvider` (one per app) | **Facade** over WS with SSE fallback (**Strategy**); multiplexed by `session_id` so N open sessions ≠ N sockets |
| Event log → view model | `sessionReducer(state, event)` | **Pure reducer / event-sourcing projection** — no DOM, no fetch; unit-testable in isolation |
| Dedupe + keys | `Map<event.id, Event>` | `BaseEvent.id` is already a uuid — fixes duplicate-on-reconnect *and* `key={i}` in one move |
| Server data (sessions, models, metrics) | `lib/api.ts` clients + hooks | **Repository** pattern, already the shape of `api.ts`; keep `fetch` out of components |
| Optimistic user message | reducer + `client_msg_id` reconcile | echo from the server replaces the optimistic row; no flicker |
| Commands | `CommandRegistry` | **Command** objects reused by palette, buttons and keybindings — one definition, three surfaces |
| Theme tokens | CSS custom properties | three-layer: primitive → semantic → component |

---

## 4. Design system contract

Derived from `ui-ux-pro-max` (`Real-Time / Operations` pattern, `Modern Dark` style, density 8/10,
motion 4/10). The tool's suggested palette returned a light background against a dark style —
rejected; using its *Developer Tool / IDE* dark palette plus a violet agent identity.

```css
/* layer 1 — primitives */
--slate-950:#0B1120; --slate-900:#0F172A; --slate-850:#1B2336; --slate-800:#272F42;
--slate-700:#2A3347; --slate-600:#475569; --slate-400:#94A3B8; --slate-50:#F8FAFC;
--violet-600:#7C3AED; --green-500:#22C55E; --amber-500:#F59E0B; --red-500:#EF4444;

/* layer 2 — semantic  (fixes RC-8: card must differ from background) */
--bg:var(--slate-950);        --surface-1:var(--slate-900);
--surface-2:var(--slate-850); --surface-3:var(--slate-800);
--border:var(--slate-700);    --border-strong:var(--slate-600);
--fg:var(--slate-50);         --fg-muted:var(--slate-400);
--agent:var(--violet-600);    --user:#334155;
--status-live:var(--green-500);   --status-waiting:var(--amber-500);
--status-error:var(--red-500);    --status-idle:#64748B;

/* layer 3 — component */
--composer-bg:var(--surface-2); --dock-bg:var(--surface-1);
--topbar-h:48px; --rail-w:240px; --dock-w:340px;

--font-sans:Inter; --font-mono:'JetBrains Mono';   /* mono token absent today */
--dur-fast:150ms; --dur-base:220ms; --ease:cubic-bezier(0.16,1,0.3,1);
```

Rules:
- **Density 8/10** — spacing scale 8/12/16/24/32; rows 32-40px; chrome text 13-14px.
- **Chat body** 15-16px, `max-w-[70ch]` (line-length guideline: 65-75 characters).
- **Status is never colour alone** — colour + icon + label.
- **Motion**: transform/opacity only, 150-250ms, list stagger 60ms, `prefers-reduced-motion` honoured.
- **Icons**: `lucide-react` only. No emoji as icon (removes 🛡️ from `BehaviorPanel`).
- Light mode is re-enabled as a real theme (class on `<html>` driven by a `ThemeProvider`),
  not left as unreachable dead CSS.

---

## 5. Phased plan

Each task lists **files · paradigm/pattern · acceptance**.

### Phase 0 — Transport spine (backend) · unblocks everything

**T0.1 — Add `session_id` to `BaseEvent`**
- Files: `weebot/domain/models/event.py`
- Paradigm: immutable value object; additive field with safe default
- Add `session_id: str = Field(default="")` to `BaseEvent`; remove the now-redundant
  redeclarations on the 10 subclasses that already carry it (keep field order stable).
- Acceptance: existing event tests pass unchanged; `MessageEvent().session_id == ""`.

**T0.2 — `SessionScopedEventBus` decorator**
- Files: `weebot/application/services/session_scoped_event_bus.py` (new)
- Pattern: **Decorator** + **Correlation ID**
- Wraps an `EventBusPort`, holds a `session_id`, and on `publish` returns
  `event.model_copy(update={"session_id": self._sid})` when the event's id is empty.
  Never overwrites an explicitly-set id.
- Acceptance: unit test — publishing through the decorator stamps the id; publishing an
  already-stamped event leaves it untouched; `subscribe`/`unsubscribe` delegate.

**T0.3 — Flows receive the scoped bus**
- Files: `weebot/application/services/task_runner.py`, `weebot/application/di/__init__.py`
- The factory that builds a flow wraps the injected bus in `SessionScopedEventBus(bus, session.id)`.
- Acceptance: integration test — run a stub flow, assert every published event carries the session id.

**T0.4 — Wire `WebSocketEventBroadcaster` at the composition root**
- Files: `weebot/interfaces/web/main.py` (lifespan), `weebot/interfaces/web/event_broadcaster.py`
- Pattern: **Adapter** wired once at the edge; **Observer** subscription
- In lifespan startup: `bus.subscribe(WebSocketEventBroadcaster(manager).publish)`;
  unsubscribe on shutdown. Add `mode="json"` to `model_dump` so datetimes serialise
  (current call would raise on `datetime` under the stdlib JSON encoder).
- Acceptance: integration test with a `TestClient` websocket — connect to
  `/ws/sessions/{id}`, publish a `MessageEvent(session_id=id)`, assert receipt;
  assert a *different* session's socket does **not** receive it.

**T0.5 — Bounded fan-out with visible loss**
- Files: `event_broadcaster.py`, `routers/sse.py`
- Pattern: bounded queue, **drop-oldest**, `dropped` counter emitted as a synthetic
  `notification` event so the UI can render a gap marker.
- Acceptance: unit test — flood 1000 events into a size-100 queue; consumer sees a
  gap marker and no unbounded memory growth.

**T0.6 — Architecture fitness update**
- Files: `tests/unit/test_architecture_fitness.py`
- Register the new port/adapter pairing so the layering test keeps its teeth.

---

### Phase 1 — Conversational core (backend)

**T1.1 — `StreamingLLMPort` protocol + fallback adapter**
- Files: `weebot/application/ports/streaming_llm_port.py` (new),
  `weebot/infrastructure/adapters/non_streaming_llm_adapter.py` (new)
- Pattern: **Interface Segregation** via `typing.Protocol` (structural, zero churn on
  existing adapters) + **Null Object/Adapter** fallback yielding one chunk.
- Acceptance: `isinstance(adapter, StreamingLLMPort)` is `True` only for adapters that
  implement `stream`; the fallback yields exactly one chunk equal to the full response.

**T1.2 — Implement `stream()` on the primary adapter(s)**
- Files: `weebot/infrastructure/adapters/` (OpenRouter/primary provider first; others later)
- Keep the resilience stack (circuit breaker, retry, cache) applied to the *stream open*,
  not per-chunk. Cache is bypassed for streamed calls; cached hits replay via the fallback.
- Acceptance: chunk sequence concatenates to the same text a non-streaming call returns.

**T1.3 — SSE chat stream endpoint**
- Files: `weebot/interfaces/web/routers/chat_router.py`
- `ChatFlow.run()` is already an `AsyncGenerator[AgentEvent]` — add
  `POST /api/chat/stream` returning `EventSourceResponse` over it, instead of the current
  drain-then-return loop ([chat_router.py:72-88](../../weebot/interfaces/web/routers/chat_router.py)).
  Keep the existing non-stream `POST /api/chat` for API clients (no breaking change).
- Acceptance: contract test — first byte arrives before the flow completes.

**T1.4 — Expose steering**
- Files: `weebot/application/services/task_runner.py` (add `steering` param to
  `create_plan_act_factory`, forward into `PlanActFlowConfig`),
  `weebot/interfaces/web/routers/sessions.py` (`run_session` resolves + passes it),
  `weebot/application/di/__init__.py` (register under `SteeringPort`, not the concrete class —
  current registration at line 124 binds the implementation type, a DIP violation)
- Acceptance: integration test — start a long flow, `send()` a steering message,
  assert the flow observes it at the next step boundary.

**T1.5 — Unified input endpoint**
- Files: `weebot/application/use_cases/dispatch_session_input.py` (new),
  `weebot/interfaces/web/routers/sessions.py`
- Pattern: **Strategy** selected by `SessionStatus`, dispatched via the existing **Mediator**
  (CQRS command), so it inherits logging/metrics/handler registration.
- `POST /api/sessions/{id}/input {text, client_msg_id}` → start | resume | steer | chat.
- Acceptance: table-driven test, one row per `SessionStatus`, asserting the chosen strategy.

**T1.6 — Session-list deltas on the global socket**
- Files: `weebot/interfaces/web/main.py` or a small `session_presence` service
- Emit a `session_presence` event (id, status, title, step counts) on status transitions.
- Acceptance: status change produces exactly one presence event on `/ws`.

---

### Phase 2 — Conversation surface (frontend P0)

**T2.1 — Transport provider**
- Files: `src/providers/EventStreamProvider.tsx`, `src/hooks/useSessionEvents.ts`,
  delete/retire `useWebSocketDebug` duplication
- Pattern: **Facade** over one shared connection; **Strategy** for WS→SSE fallback;
  subscription by `session_id`. Replaces per-page socket creation (currently
  `useWebSocket` in the session page *and* a raw `new WebSocket` in the dashboard).
- Acceptance: opening three sessions creates one socket; unmount unsubscribes; a dropped
  socket falls back to SSE and re-syncs history without duplicates.

**T2.2 — Pure session reducer**
- Files: `src/lib/session-reducer.ts`, `src/lib/session-reducer.test.ts`
- Pattern: **event-sourcing projection**; pure function `(state, event) => state`
- Handles: dedupe by `event.id`, ordering by timestamp, tool-call pairing
  (`calling` → `called` collapse into one row), step→plan rollup, gap markers.
- Acceptance: unit tests only, no DOM. Replaying the same event twice is a no-op.

**T2.3 — `<Composer/>` — always enabled**
- Files: `src/components/conversation/Composer.tsx`
- Removes the `waitingForInput` gate (RC-6). Posts to `/api/sessions/{id}/input`.
  Enter sends, Shift+Enter newline (today only ⌘+Enter works). Mode chip reflects what
  the backend will do — *Start task* / *Reply* / *Steer* / *Chat* — derived from status.
  Optimistic user bubble with `client_msg_id`.
- Acceptance: Playwright — type + Enter in each of the four session states produces the
  right call and an immediate optimistic row.

**T2.4 — `<ConversationPane/>` decomposition**
- Files: `src/components/conversation/` — `MessageRow`, `ToolCallRow`, `StepRow`,
  `PlanReviewRow`, `ErrorRow`, `GapMarker`, `EventRenderer`
- Pattern: **presentational components** + a small **registry** mapping `event.type` →
  renderer (replaces the growing `switch` in `EventCard`, currently at
  [sessions/[id]/page.tsx:31-109](../../weebot-ui/src/app/sessions/[id]/page.tsx)).
  New event types register instead of editing a switch (open/closed).
- Fixes RC-7 (scroll ref → Viewport, via `useStickToBottom` with an "at bottom" guard so
  the view doesn't yank while the user is reading) and the `key={i}` issue (uses `event.id`).
- Acceptance: appending 500 events keeps the view pinned only when already at the bottom.

**T2.5 — Interrupt control**
- Files: `src/components/conversation/RunControls.tsx`
- Surfaces the already-existing `POST /sessions/{id}/cancel` plus the new steer path.
- Acceptance: clicking Interrupt on a running session transitions status within one event.

**T2.6 — Toast system; delete every `alert()`**
- Files: `src/providers/ToastProvider.tsx`, `src/components/ui/toast.tsx`
- Pattern: context + reducer + portal; errors also render inline where they belong
  (failed send stays attached to the message row with a Retry action).
- Acceptance: grep for `alert(` in `weebot-ui/src` returns zero hits.

**T2.7 — Theme tokens**
- Files: `src/app/globals.css`, `tailwind.config.ts`, `src/providers/ThemeProvider.tsx`
- Implements §4. Fixes RC-8 (surface elevation, agent accent) and RC-9 (semantic error
  surfaces replace `bg-red-50`). `<html>` class driven by provider, light mode reachable.
- Acceptance: automated contrast check — every semantic fg/bg pair ≥ 4.5:1 in both themes;
  Card is visually distinct from page background.

---

### Phase 3 — Mission center shell

**T3.1 — `<ConsoleShell/>`**
- Files: `src/components/shell/ConsoleShell.tsx`, `TopBar.tsx`, `SessionRail.tsx`
- CSS Grid `[rail] [main] [dock]`; rail and dock collapsible with persisted widths.
  Replaces `container mx-auto` page-centering. Mobile: single pane, rail → drawer,
  dock → bottom sheet (min-width media queries, mobile-first per project standards).
- Acceptance: no horizontal overflow at 375/768/1024/1440/1920.

**T3.2 — Home becomes the console**
- Files: `src/app/page.tsx` (rewrite), `src/app/sessions/new/page.tsx` (retire — new
  session starts from the composer)
- The marketing brochure (RC: `/` currently sells "58+ models" to its own operator) is
  replaced by: last active session, or an empty-state composer.
- Acceptance: `/` renders a usable composer with zero clicks.

**T3.3 — Session rail, WS-driven**
- Files: `SessionRail.tsx`, `src/hooks/useSessionList.ts`
- Consumes `session_presence` (T1.6); removes the 5s and 10s polling intervals.
- Acceptance: network panel shows no repeating `/api/sessions` requests while idle.

**T3.4 — Command registry + ⌘K palette**
- Files: `src/lib/commands/registry.ts`, `src/components/command/CommandPalette.tsx`
- Pattern: **Command** objects (`id`, `title`, `run`, `when`) consumed by palette,
  toolbar buttons and keybindings alike.
- Acceptance: every palette action is reachable by keyboard; `when` predicates hide
  irrelevant commands.

---

### Phase 4 — Mission dock & observability

**T4.1 — `<MissionDock/>` compound component**
- Files: `src/components/dock/` — `Dock.tsx`, `PlanTab.tsx`, `ToolsTab.tsx`,
  `CostTab.tsx`, `TrustTab.tsx`
- Pattern: **compound components** (parent owns tab state, children consume context).
- **PlanTab binds to the current session automatically**, deleting the manual
  session-ID text box at [dashboard/page.tsx:423-437](../../weebot-ui/src/app/dashboard/page.tsx).
- Acceptance: selecting a session updates all four tabs without a page navigation.

**T4.2 — `BehaviorPanel` rewrite**
- Files: `src/components/behavior/*`
- Removes all inline styles and hardcoded hex; adopts tokens and `lucide-react`
  (drops the 🛡️ emoji icon). Same data hooks, new presentation.
- Acceptance: no `style={{` and no `#RRGGBB` literal remains under `components/behavior/`.

**T4.3 — `/ops` replaces `/dashboard`**
- Files: `src/app/ops/page.tsx`, delete `src/app/dashboard/page.tsx`
- Keeps metrics, health, cost, active sessions. **Removes the stub Monaco editor** whose
  execute/save are `alert()` calls — a code-execution surface must route through
  `bash_guard`, and a fake one is worse than none. Re-add later as a real, guarded feature.
- Acceptance: no route renders a control that does nothing.

**T4.4 — Route consolidation**
- Merge `/behavior` and `/settings/behavior`; fold `/debug` behind a dev-only flag.

---

### Phase 5 — Streaming, performance, accessibility

**T5.1 — Token streaming in the UI** — consume `/api/chat/stream`; render partial
assistant text with a caret; reducer gains a `message.delta` case. Depends on T1.2.
**T5.2 — Virtualized timeline** — windowing for sessions past ~200 events; keep the
sticky-bottom behaviour correct under virtualization.
**T5.3 — Message actions** — copy, retry, branch-from-here, jump-to-step.
**T5.4 — Accessibility pass** — `aria-label` on every icon-only control (header buttons
today carry only `title`), visible `:focus-visible` rings, live-region announcements for
status changes, full keyboard path to send/interrupt/switch session.
**T5.5 — Motion pass** — stagger reveals, `prefers-reduced-motion` short-circuit.

---

## 6. Testing strategy

| Layer | Tool | What |
|---|---|---|
| Domain / reducers | `pytest`, `vitest` | Pure functions: event stamping, session reducer, input-dispatch strategy table |
| Ports & adapters | `pytest` | Contract tests: `StreamingLLMPort` conformance (streamed text == non-streamed text); bounded-queue drop behaviour |
| Transport | `pytest` + `TestClient` websocket | Per-session isolation (session A never sees B); reconnect replay produces no duplicates |
| API | `pytest` | `/api/sessions/{id}/input` one row per `SessionStatus`; SSE first-byte-before-completion |
| Frontend unit | `vitest` + Testing Library | Composer state matrix, renderer registry, toast reducer |
| E2E | `playwright` | Golden flow: open console → type task → watch plan populate in dock → steer mid-run → interrupt → follow-up chat turn |
| Visual | `playwright` screenshots | 375/768/1024/1440, light + dark |
| A11y | `axe` in Playwright | Zero critical violations on console, ops, settings |

Coverage target stays 80% per project rules. Every phase must leave `pytest tests/ -v` and
`npm run test` green before the next begins.

---

## 7. Risks & rollback

| Risk | Mitigation |
|---|---|
| Adding `session_id` to `BaseEvent` breaks persisted event deserialisation | Default `""` + Pydantic ignores unknown/missing; add a migration test that loads a pre-change session fixture |
| Wiring the broadcaster floods slow clients | Bounded queue + drop-oldest + gap markers (T0.5); load test with 1k events/s |
| Streaming bypasses the resilience/caching stack | Streaming path keeps circuit breaker + retry on stream open; cache disabled for streams and documented |
| One shared socket becomes a single point of failure | SSE fallback strategy + exponential reconnect already present in `useWebSocket`, lifted into the provider |
| Shell rewrite lands as a big bang | Shell introduced behind a route group; old pages remain reachable until Phase 4 deletes them |
| Steering messages arrive after the flow ends | `SteeringPort.send` on a finished session returns a typed rejection the composer surfaces as "session finished — sent as a new chat turn" |

Rollback: every phase is a separate commit series on its own branch. Phase 0/1 are additive
(new files + additive fields) and revert cleanly. Phase 3's shell sits behind a route group
so reverting restores the prior pages.

---

## 8. Sequencing

```
T0.1 ─ T0.2 ─ T0.3 ─ T0.4 ─ T0.5 ─ T0.6        (Phase 0, strictly serial)
                 │
                 ├─► T1.1 ─ T1.2 ────────────► T5.1
                 ├─► T1.3
                 ├─► T1.4 ─┐
                 ├─► T1.5 ─┴─► T2.3            (composer needs the input endpoint)
                 └─► T1.6 ─────► T3.3
                                │
   T2.7 (tokens) ─┬─► T2.1 ─ T2.2 ─ T2.4 ─ T2.5 ─ T2.6
                  └─► T3.1 ─ T3.2 ─ T3.4 ─► T4.1 ─ T4.2 ─ T4.3 ─ T4.4 ─► T5.2…T5.5
```

T2.7 (design tokens) has no backend dependency and can start immediately in parallel with
Phase 0 — it is the cheapest visible improvement.

---

## 9. Deferred / out of scope

- Multi-user presence and collaborative sessions.
- A real in-browser execution surface for the code editor (needs a guarded, sandboxed
  backend path through `bash_guard` — a design task of its own).
- Mobile-native shell; the plan covers responsive web only.
- Trajectory/behaviour analytics visualisations beyond the existing trust bar.
- Replacing `reactflow` for plan visualisation — reused as-is, only rebound to the
  active session.
