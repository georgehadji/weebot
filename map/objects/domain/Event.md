---
type: object
name: Event
code: BaseEvent, AgentEvent, DomainEvent (and subclasses)
cluster: domain
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# Event

Two separate event families in one file. `BaseEvent` subclasses joined in the `AgentEvent` union are what a flow yields, what `Session.events` stores and what the UI renders. `DomainEvent` subclasses are internal facts published on the event bus (skill edits, costs, constraints) and are never stored in a session.

## Why this shape
One union type gives one deserialiser: `TypeAdapter(AgentEvent)` picks the subclass by its `type` literal (`weebot/application/cqrs/event_reconstructor.py:23-28`, the same adapter in `infrastructure/persistence/sqlite_state_repo.py:532-538`). Each subclass fixes `type` as a `Literal`, so the JSON `type` key selects the class. `session_id` on `BaseEvent` is a transport routing id stamped by `SessionScopedEventBus`, not the subject of the event (`weebot/domain/models/event.py:38-45`, `weebot/domain/models/event.py:310-321`).

## Shape
- `BaseEvent` (`weebot/domain/models/event.py:34-45`): `type`, `id` (uuid4), `timestamp` (UTC), `session_id`.
- `AgentEvent` union (`weebot/domain/models/event.py:334-361`), 24 members: `ErrorEvent` (`event.py:48`), `PlanEvent` (`event.py:54`, `plan` is an untyped dict), `StepEvent` (`event.py:61`), `ToolEvent` (`event.py:68`), `MessageEvent` (`event.py:80`), `TitleEvent`, `DoneEvent`, `WaitForUserEvent` (`event.py:98`), `NotificationEvent`, `ThoughtEvent` (`event.py:139`), `SteeringEvent`, `CanonicalizationEvent`, `TrajectoryDiagnosisEvent` (`event.py:203`), `VerificationEvent`, `TodoEvent`, `PlanReviewEvent` (`event.py:103`), `ToolApprovalEvent` (`event.py:115`, carries `fingerprint` and `allow_always` for ADR-013), `ProductGateReviewEvent` (`event.py:216`), `ProductDecisionEvent` (`event.py:236`), `SessionPresenceEvent` (`event.py:310`), and the four scheduler/health events below.
- Scheduler/health `BaseEvent` subclasses (`event.py:273-308`) were once outside the union and now sit at its tail (`event.py:357-360`) so a journaled copy can be rebuilt: `SessionStalenessEvent`, `MemoryPressureEvent`, `ScheduledJobEvent`, `LLMHealthEvent`. `SessionStalenessEvent` and `ScheduledJobEvent` are emitted by the scheduler (`weebot/scheduling/default_jobs.py`); `MemoryPressureEvent` and `LLMHealthEvent` have had no emitter since the unwired heartbeat monitors were deleted (no construction outside `event.py`, grep 2026-10-31).
- `DomainEvent` (`event.py:364-369`) and 17 subclasses (`event.py:372-586`): `FactDiscovered`, `MemoryCompacted`, `PlanStepCompleted`, `TrajectoryScored`, `SkillEdit{Proposed,Accepted,Rejected}`, `EpochCompleted`, `SkillGapDetected`, `LLMCallCompleted` (the cost fact, F23), `InjectionSuspected`, `SessionBudgetSoftLimit`, `SkillDistilled`, `SkillPromoted`, `CorrectionPatternDetected`, `SessionConstraint{Recorded,Revoked}`.
- Enums: `FailureSeverity` (`event.py:13-24`), `ToolStatus` (`event.py:29-31`).

Consequences (read from source, not run):
- Never constructed in `weebot/` or `cli/` (grep 2026-10-24): `TrajectoryDiagnosisEvent`, `SkillEditProposed`, `MemoryCompacted`. `MemoryCompacted` has a subscriber branch (`infrastructure/events/subscriber.py:26`) that cannot fire.
- `ErrorEvent.failure_severity` (`event.py:51`) is never set by a constructor or read; the executing state classifies severity as a plain string instead (`application/agents/executor/_error_handler.py:162`, `weebot/application/flows/states/_step_outcome.py:120-122`). The `FailureSeverity` docstring says "3-tier" over four members (`event.py:14, 21-24`).
- `PlanStepCompleted` is published for every `StepEvent`, including STARTED and FAILED (`application/flows/event_publisher.py:156-159`: the check is only `event.type == "step"`).
- `_emit_domain_event` has one home: `event_publisher.py:149`, called at `event_publisher.py:81`.
- `reconstruct_events` logs and drops a dict it cannot parse (`event_reconstructor.py:49-57`); `_row_to_session` turns it into a `MessageEvent(**e)` instead (`sqlite_state_repo.py:557-561`). Two policies for the same failure.
- The web UI declares 11 event types (`weebot-ui/src/types/events.ts`); `tool_approval`, `product_gate_review`, `thought` and the other backend members have no type in `weebot-ui/src` (grep 2026-10-24). Whether the UI renders them some other way was not checked.

## Connected to
- **Stored in** `Session.events` (Session card). **Published on** `EventBusPort` (`application/ports/event_bus_port.py:15`); domain events through `publish_domain_event` (`application/ports/event_bus_port.py:24`). **Journaled by** the event store (EventStore card); `LLMCallCompleted` feeds its cost columns (`infrastructure/event_bus.py:263-271`).
- **Yielded by** `PlannerAgent` (`PlanEvent`, `application/agents/planner.py:283, 313`), `ExecutorAgent` (`StepEvent`, `ToolEvent`, `weebot/application/agents/executor/_base.py:473, 644, 647`; `weebot/application/agents/executor/_tool_batch.py:82, 174`), flow states (`WaitForUserEvent`, `PlanReviewEvent`, `ToolApprovalEvent`).
- **Rebuilt by** `reconstruct_events` (CQRS results back into events, `planning.py:266`) and `SQLiteStateRepository._row_to_session`.
- **Looks like but is not:** `EventPublisher` Protocol in `weebot/domain/ports.py:60` vs `EventPublisherPort` ABC in `application/ports/event_publisher_port.py:16`; legacy `Message`/`Checkpoint` (`domain/legacy_models.py:105, 206`).

## If you change this
**Hits:** every stored session row (the `type` literal and field names are the JSON), the UI event types, WebSocket/SSE routing on `session_id`, the event store, the CLI event logger (`interfaces/cli/event_logger.py`). Tests: `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/application/services/test_approval_journal.py`, `tests/unit/test_task_runner_presence.py`, `tests/unit/interfaces/web/test_d50_event_scope_routing.py`, `tests/unit/test_session_replace_events.py`; 103 test files import `weebot.domain.models.event` (grep 2026-10-31).
**Does not hit:** the event bus implementation (EventBus card).

## Surfaces
Web UI stream, CLI event logger, MCP server, event store queries.

## See
`weebot/domain/models/event.py`
