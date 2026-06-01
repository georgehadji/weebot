# Event Catalog — Weebot v3.0

> All event types flowing through the system, with their publishers, subscribers, and bridge mappings.

---

## Primary Event System: `AsyncEventBus`

### AgentEvent Subtypes (defined in `weebot/domain/models/event.py`)

| Event Type | `type` discriminator | Fields | Publisher(s) | Subscriber(s) |
|------------|---------------------|--------|-------------|---------------|
| `MessageEvent` | `"message"` | `role`, `message`, `timestamp` | ChatAgent, ExecutorAgent | CLI event logger, WebSocket broadcaster, EventStore |
| `PlanEvent` | `"plan_created"`, `"plan_updated"`, `"plan_completed"` | `plan`, `status` | PlannerAgent, PlanActFlow | EventStore, Web UI |
| `StepEvent` | `"step_completed"` | `step_id`, `status`, `result` | ExecutorAgent | EventStore |
| `ToolEvent` | `"tool_call"`, `"tool_result"` | `tool_name`, `function_args`, `status`, `result` | ExecutorAgent, StructuredExecutorAgent | EventStore, cost tracker |
| `DoneEvent` | `"done"` | — | Flow states (CompletedState) | Flow caller |
| `ErrorEvent` | `"error"` | `error`, `error_code` | All agents, flow states | CLI, WebSocket, EventStore |
| `WaitForUserEvent` | `"wait_for_user"` | `question`, `options` | Flow states (ExecutingState) | CLI (HITL), Web UI |
| `FactDiscovered` | `"fact_discovered"` | `session_id`, `key`, `value` | EventBrokerAdapter (bridge) | WorkingMemory |
| `NotificationEvent` | `"notification"` | `text` | EventBrokerAdapter (catch-all) | Notification channels |
| `TrajectoryScored` | `"trajectory_scored"` | `session_id`, `score`, `failure_modes` | ScoringPort implementations | TrajectoryBuilder |
| `EpochCompleted` | `"epoch_completed"` | `epoch`, `score`, `accept_count` | SkillOptFlow | Skill registry |
| `SkillEditAccepted` | `"skill_edit_accepted"` | `skill_name`, `edits`, `score_delta` | SkillOptFlow | Skill store |
| `SkillEditRejected` | `"skill_edit_rejected"` | `skill_name`, `edits`, `reason` | SkillOptFlow | Skill store |
| `SkillEditProposed` | `"skill_edit_proposed"` | `skill_name`, `edits`, `score` | SkillOptFlow | — |
| `MemoryCompacted` | `"memory_compacted"` | `session_id`, `events_before`, `events_after` | MemoryCompactor | EventStore |
| `PlanStepCompleted` | `"plan_step_completed"` | `session_id`, `step_id` | ExecutorAgent | EventStore |

### Event Flow Diagram

```
Agent / Flow
  │
  ├─→ context._emit(event)
  │     │
  │     ├─→ self._session.add_event(event)      # In-memory append
  │     ├─→ event_bus.publish(event)             # AsyncEventBus
  │     └─→ state_repo.save_session(session)     # Persist (Phase A.1 fix)
  │
  ▼
AsyncEventBus
  │
  ├─→ CLIEventSubscriber      → console output
  ├─→ WebSocketBroadcaster    → real-time UI updates
  ├─→ EventStore              → SQLite event log
  └─→ WindowsToastSubscriber  → desktop notifications
```

---

## Legacy Event System: `EventBroker` (in `weebot/core/agent_context.py`)

| Event Type | Fields | Publisher(s) | Subscriber(s) |
|------------|--------|-------------|---------------|
| `ContextEvent` | `event_type`, `agent_id`, `data`, `timestamp` | AgentContext.publish_event() | AgentContext.subscribe_to_events() |

**Bridge:** `EventBrokerAdapter` (`infrastructure/events/broker_adapter.py`) converts `EventBroker` publish calls to `AsyncEventBus`:

```
ContextEvent(fact_discovered, agent-1, data)
  → EventBrokerAdapter.publish("fact_discovered", "agent-1", data)
    → _convert → FactDiscovered(session_id, key, value)
      → AsyncEventBus.publish(FactDiscovered(...))
```

---

## CQRS Events (commands/queries)

These are not `AgentEvent` subtypes, but flow through the mediator pipeline:

### Commands (14 total)

| Command | Handler | Pipeline Behaviors |
|---------|---------|-------------------|
| `CreatePlanCommand` | `CreatePlanHandler` | Logging, Validation |
| `ExecuteStepCommand` | `ExecuteStepHandler` | Logging, Validation |
| `UpdatePlanCommand` | `UpdatePlanHandler` | Logging, Validation |
| `ProcessMessageCommand` | `ProcessMessageHandler` | Logging, Validation |
| `CompactMemoryCommand` | `CompactMemoryHandler` | Logging |
| `CancelSessionCommand` | `CancelSessionHandler` | Logging |
| `ArchiveSessionCommand` | `ArchiveSessionHandler` | Logging |
| `SummarizeCommand` | `SummarizeHandler` | Logging, Validation (new in v3.0) |
| `ApplySkillEditsCommand` | `ApplySkillEditsHandler` | Logging, ValidationGate |
| `ScoreTrajectoryCommand` | `ScoreTrajectoryHandler` | Logging |
| `BuildOptimizationBatchCommand` | `BuildOptimizationBatchHandler` | Logging |
| `ValidateTransferCommand` | `ValidateTransferHandler` | Logging |
| `ValidateSkillCommand` | `ValidateSkillHandler` | Logging |
| `AskUserCommand` | *(none — orphan)* | — |
| `AnswerUserCommand` | *(none — orphan)* | — |

### Queries (8 total)

| Query | Handler |
|-------|---------|
| `GetSessionQuery` | `GetSessionHandler` |
| `ListSessionsQuery` | `ListSessionsHandler` |
| `GetSessionStatusQuery` | `GetSessionStatusHandler` |
| `GetSessionHistoryQuery` | `GetSessionHistoryHandler` |
| `GetPlanQuery` | `GetPlanHandler` |
| `SearchSessionsQuery` | `SearchSessionsHandler` |
| `GetSimilarSessionsQuery` | `GetSimilarSessionsHandler` |
| `GetActiveTasksQuery` | `GetActiveTasksHandler` |

---

## Dual System Sunset Plan

**Goal:** Eliminate the `EventBroker` (legacy) and route everything through `AsyncEventBus`.

| Step | Description | Target Date |
|------|-------------|-------------|
| 1 | Complete `_convert()` mapping for all known event type strings | 2026-Q3 |
| 2 | Migrate `AgentContext.subscribe_to_events()` callers to `AsyncEventBus.subscribe_by_type()` | 2026-Q3 |
| 3 | Replace `ContextEvent` with `AgentEvent` subtypes in agent_context.py | 2026-Q3 |
| 4 | Remove `EventBroker` class from `agent_context.py` | 2026-Q4 |
| 5 | Remove `EventBrokerAdapter`; route `EventPublisher` directly to `AsyncEventBus` | 2026-Q4 |
| 6 | Clean up `get_event_bus()` deprecation shim | 2026-Q4 |
