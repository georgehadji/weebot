---
type: object
name: Event bus (AsyncEventBus, DurableEventBus, ValkeyEventBus)
code: AsyncEventBus, DurableEventBus, ValkeyEventBus
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-29
commit: 340794f3
---

# Event bus

How agent and domain events reach listeners (WebSocket, SSE, CLI printer, toast notifications). `EventBusPort` is the interface; the container builds one bus per process: a `DurableEventBus` that journals to the event store and then hands off to an inner `AsyncEventBus`. `ValkeyEventBus` exists but the container never builds it; a Valkey/Redis URL makes the container refuse to start.

## Why this shape
Publishers must never be slowed or broken by listeners. Each subscriber call is isolated and time-limited; a slow or failing handler is logged and skipped (`weebot/infrastructure/event_bus.py:43-91`). Durability is a decorator so persistence is optional and best-effort (`:180-199`). Components that only publish depend on the narrower `EventPublisherPort`; `EventBusPort` adds subscribe/unsubscribe (`application/ports/event_bus_port.py`). Domain events use a separate subscriber list so they do not reach SSE/UI streams (`event_bus.py:135-141`).

## Shape
- **AsyncEventBus** (`event_bus.py:43`): in-process. `publish` increments a Prometheus counter, copies the handler list under a lock and runs all handlers with `asyncio.gather`, each with `handler_timeout` (default 30 s); a timed-out handler drops that event for that subscriber only (`:58-91`). `subscribe_by_type(type, handler)` wraps a handler with an exact-match filter and records the original so `unsubscribe` can find it (`:96-132`). `publish_domain_event` is the same for domain handlers (`:135-178`).
- **DurableEventBus** (`:180`): `publish` first writes the event to `EventStorePort.log_event(session_id, event_type, data)`, then to the inner bus. A journal failure is logged and delivery continues (`:201-209, 227-281`). Agent events carry no cost columns; a `LLMCallCompleted` domain event fills `cost`, `model` and `tokens_used` (`:261-274`; see Event store card). Subscriber calls are delegated to the inner bus (`:213-223`).
- **ValkeyEventBus** (`infrastructure/events/redis_event_bus.py:32`): on first publish it connects with a 3 s timeout and `ping`; on any failure or missing URL it switches to an in-memory `AsyncEventBus` for the life of the object (`:55-103`). When connected, `publish` and `publish_domain_event` raise `RuntimeError` instead of sending, because nothing delivers Valkey channels back to local subscribers (F24, `:26-29, 114-128`).
- **Selection** in `FactoriesMixin._create_event_bus`: `WEEBOT_VALKEY_URL` or `WEEBOT_REDIS_URL` set → `RuntimeError` (W4.3, F24); else `DurableEventBus(inner=AsyncEventBus())` (`application/di/_factories.py:45-60`).

**Valkey is off by design (read from source, not run):** `ValkeyEventBus.subscribe` only stores the handler and forwards it to the in-memory fallback if that exists (`redis_event_bus.py:130-138`), and no code reads the Valkey channels back. Rather than drop events silently, the DI factory refuses a configured URL and a connected bus refuses to publish. `docker-compose.yml` sets only `VALKEY_PASSWORD`, not `WEEBOT_VALKEY_URL` (`docker-compose.yml:78`). Pinned by `tests/unit/fixes/test_f24_valkey_drops_local_events.py` and `tests/unit/fixes/test_w43_valkey_fail_fast.py`.

## Connected to
- **Subscribers (real code):** `WebSocketEventBroadcaster.publish` at app start (`interfaces/web/main.py:218`); SSE route handler per connection (`interfaces/web/routers/sse.py:85`); `interfaces/cli/event_logger.py:88` (CLI printer); `interfaces/sse_event_subscriber.py:36`; `infrastructure/notifications/windows_toast.py:261` and `interfaces/windows_toast_subscriber.py:97`; `SessionScopedEventBus` wraps another bus, stamps `session_id` on publish and delegates subscriptions (`application/services/session_scoped_event_bus.py:28-32, 37-41`); `PlanActFlow` subscribes a domain handler for `SkillGapDetected` when a misalignment journal is wired (`weebot/application/flows/_plan_act_wiring.py:278`, in the flow composition step).
- **Publishers:** `PlanActFlow._emit` and the executor (`ExecutorAgent._emit`), plus anything given an `EventBusPort`/`EventPublisherPort`.
- **Looks like but is not:** the Mediator (commands to one handler); the event store (history, not live fan-out); `swarm_event_bus.py` (a separate topic bus for sub-agents); `EventBrokerAdapter` (`events/broker_adapter.py`, kept for old `EventBroker` callers, not covered).

## If you change this
**Hits:** every UI and CLI live view (WebSocket, SSE, toast, CLI printer); the event store journal; `PlanActFlow` event emission; the DI selection logic; `SessionScopedEventBus`. Tests: `tests/unit/infrastructure/test_durable_event_bus_journal.py`, `tests/unit/fixes/test_w41_llm_call_completed.py`, `tests/unit/fixes/test_w43_valkey_fail_fast.py`, `tests/unit/fixes/test_f24_valkey_drops_local_events.py`; `AsyncEventBus` behaviour is exercised through flow tests (not enumerated).
**Does not hit:** state persistence; the Mediator; LLM adapters.

## Surfaces
The browser UI (WebSocket and SSE), the CLI event printer, Windows toasts.

## See
`weebot/infrastructure/event_bus.py`, `weebot/infrastructure/events/redis_event_bus.py`
