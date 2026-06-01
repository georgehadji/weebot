# ADR 005: In-Process Event Bus over Message Queue

**Status:** Accepted  
**Date:** 2026-06-01  
**Deciders:** Architecture Team  

## Context

weebot needs event distribution for:
- Publishing `AgentEvent` subtypes from flows to subscribers
- Broadcasting events to WebSocket clients
- Logging events to the event store
- Notifying external channels (Windows toast, SSE, Telegram)

Options include an in-process event bus (`asyncio`-based pub/sub) or
an external message queue (RabbitMQ, Kafka, Redis Pub/Sub).

## Decision

Use an in-process `AsyncEventBus` (asyncio pub/sub) as the primary
event distribution mechanism. Do not introduce a message queue.

## Rationale

- **Single-process deployment** — weebot runs as one process. A message
  queue adds operational complexity (install, configure, monitor) for
  zero benefit.
- **Zero serialization overhead** — Events are Python objects passed by
  reference within the process. No serialization/deserialization needed
  between publisher and subscriber.
- **Sub-millisecond latency** — `asyncio.gather()` dispatches events to
  all subscribers concurrently with minimal overhead.
- **Sufficient for current scale** — The bus handles ~100 events/second
  in typical usage; well within asyncio's capacity.
- **EventBrokerAdapter bridge** — The old `EventBroker` (ContextEvent
  pub/sub in agent_context.py) is bridged to `AsyncEventBus` via
  `EventBrokerAdapter`, allowing gradual migration.

## Consequences

- Events are lost on process restart — no durable message queue backing.
  The `EventStore` in `infrastructure/event_logging.py` provides
  persistence by subscribing to the bus and writing events to SQLite.
- No horizontal scaling — the bus cannot distribute events across
  multiple processes or machines.
- Subscriber failures are isolated — `_safe_call` wraps each handler,
  so one failed subscriber doesn't block others.
- If multi-process deployment is ever needed, the `EventBusPort`
  abstraction allows swapping the in-process bus for a message queue
  adapter without changing application code.
