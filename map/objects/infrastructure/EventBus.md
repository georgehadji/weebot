---
type: object
name: Event bus (AsyncEventBus, DurableEventBus, ValkeyEventBus)
code: AsyncEventBus, DurableEventBus, ValkeyEventBus
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# Event bus

How agent and domain events reach listeners (WebSocket, SSE, CLI printer, toast notifications). `EventBusPort` is the interface; the container builds one bus per process: a `DurableEventBus` that journals to the event store and then hands off to an inner bus (`AsyncEventBus`, or `ValkeyEventBus` when a Valkey/Redis URL is configured).

## Why this shape
Publishers must never be slowed or broken by listeners. Each subscriber call is isolated and time-limited; a slow or failing handler is logged and skipped (`weebot/infrastructure/event_bus.py:43-89`). Durability is a decorator so persistence is optional and best-effort (`:180-199`). Components that only publish depend on the narrower `EventPublisherPort`; `EventBusPort` adds subscribe/unsubscribe (`application/ports/event_bus_port.py`). Domain events use a separate subscriber list so they do not reach SSE/UI streams (`event_bus.py:135-141`).

## Shape
- **AsyncEventBus** (`event_bus.py:43`): in-process. `publish` increments a Prometheus counter, copies the handler list under a lock and runs all handlers with `asyncio.gather`, each with `handler_timeout` (default 30 s); a timed-out handler drops that event for that subscriber only (`:56-89`). `subscribe_by_type(type, handler)` wraps a handler with an exact-match filter and records the original so `unsubscribe` can find it (`:96-132`). `publish_domain_event` is the same for domain handlers (`:135-178`).
- **DurableEventBus** (`:180`): `publish` first writes the event to `EventStorePort.log_event(session_id, event_type, data)`, then to the inner bus. A journal failure is logged and delivery continues (`:201-205, 227-262`). It passes no cost, model or token data (see Event store card). Subscriber calls are delegated to the inner bus (`:212-225`).
- **ValkeyEventBus** (`infrastructure/events/redis_event_bus.py:24`): on first publish it connects with a 3 s timeout and `ping`; on any failure or missing URL it switches to an in-memory `AsyncEventBus` for the life of the object (`:47-95`). When connected, `publish` serialises the event to JSON and publishes it to the Valkey channels `weebot:events` / `weebot:domain_events` (`:106-129`).
- **Selection** in `FactoriesMixin._create_event_bus`: `WEEBOT_VALKEY_URL` or `WEEBOT_REDIS_URL` set → `ValkeyEventBus`, else `AsyncEventBus`; always wrapped in `DurableEventBus` (`application/di/_factories.py:45-60`).

**Sharp edge (read from source, not run):** `ValkeyEventBus.subscribe` only stores the handler and forwards it to the in-memory fallback if that exists (`:131-139`). No code in the repo subscribes to or reads the `weebot:events` channels (grep for `weebot:events`, `pubsub`, `.listen(`, 2026-10-21). So when Valkey is configured **and reachable**, events go out to Valkey and local subscribers (WebSocket broadcaster, SSE) receive nothing. With no URL or an unreachable server the in-memory bus is used and subscribers work. `docker-compose.yml` sets only `VALKEY_PASSWORD`, not `WEEBOT_VALKEY_URL` (`:78`), so this path is off by default. No test mentions `ValkeyEventBus`.

## Connected to
- **Subscribers (real code):** `WebSocketEventBroadcaster.publish` at app start (`interfaces/web/main.py:194`); SSE route handler per connection (`interfaces/web/routers/sse.py:63`); `interfaces/cli/event_logger.py:74` (CLI printer); `interfaces/sse_event_subscriber.py:36`; `infrastructure/notifications/windows_toast.py:261` and `interfaces/windows_toast_subscriber.py:88`; `SessionScopedEventBus` wraps another bus to filter by session (`application/services/session_scoped_event_bus.py:39-42`); `PlanActFlow` subscribes a domain handler for `SkillGapDetected` when a misalignment journal is wired (`plan_act_flow.py:278-283`).
- **Publishers:** `PlanActFlow._emit` and the executor (`ExecutorAgent._emit`), plus anything given an `EventBusPort`/`EventPublisherPort`.
- **Looks like but is not:** the Mediator (commands to one handler); the event store (history, not live fan-out); `swarm_event_bus.py` (a separate topic bus for sub-agents); `EventBrokerAdapter` (`events/broker_adapter.py`, kept for old `EventBroker` callers, not covered).

## If you change this
**Hits:** every UI and CLI live view (WebSocket, SSE, toast, CLI printer); the event store journal; `PlanActFlow` event emission; the DI selection logic; `SessionScopedEventBus`. Tests: `DurableEventBus` is named in one test file; `AsyncEventBus` behaviour is exercised through flow tests (not enumerated).
**Does not hit:** state persistence; the Mediator; LLM adapters.

## Surfaces
The browser UI (WebSocket and SSE), the CLI event printer, Windows toasts.

## See
`weebot/infrastructure/event_bus.py`, `weebot/infrastructure/events/redis_event_bus.py`
