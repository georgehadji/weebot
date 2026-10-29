---
type: object
name: Event
code: BaseEvent, AgentEvent, DomainEvent (and subclasses)
cluster: domain
universe: live
status: verified
verified: 2026-10-29
commit: 83c1f712
---

# Event

Two separate event families in one file. `BaseEvent` subclasses joined in the `AgentEvent` union are what a flow yields, what `Session.events` stores and what the UI renders. `DomainEvent` subclasses are internal facts published on the event bus (skill edits, costs, constraints) and are never stored in a session.

## Why this shape
One union type gives one deserialiser: `TypeAdapter(AgentEvent)` picks the subclass by its `type` literal (`weebot/application/cqrs/event_reconstructor.py:23-28`, the same adapter in `infrastructure/persistence/sqlite_state_repo.py:520-526`). Each subclass fixes `type` as a `Literal`, so the JSON `type` key selects the class. `session_id` on `BaseEvent` is a transport routing id stamped by `SessionScopedEventBus`, not the subject of the event (`weebot/domain/models/event.py:38-45`, `:309-316`).

## Shape
- `BaseEvent` (`:34-45`): `type`, `id` (uuid4), `timestamp` (UTC), `session_id`.
- `AgentEvent` union (`:328-349`), 20 members: `ErrorEvent` (`:48`), `PlanEvent` (`:54`, `plan` is an untyped dict), `StepEvent` (`:61`), `ToolEvent` (`:68`), `MessageEvent` (`:79`), `TitleEvent`, `DoneEvent`, `WaitForUserEvent` (`:94`), `NotificationEvent`, `ThoughtEvent` (`:135`), `SteeringEvent`, `CanonicalizationEvent`, `TrajectoryDiagnosisEvent` (`:199`), `VerificationEvent`, `TodoEvent`, `PlanReviewEvent` (`:99`), `ToolApprovalEvent` (`:111`, carries `fingerprint` and `allow_always` for ADR-013), `ProductGateReviewEvent` (`:212`), `ProductDecisionEvent` (`:232`), `SessionPresenceEvent` (`:306`).
- `BaseEvent` subclasses **outside** the union (`:269-303`): `SessionStalenessEvent`, `MemoryPressureEvent`, `ScheduledJobEvent`, `LLMHealthEvent`. `SessionStalenessEvent` and `ScheduledJobEvent` are emitted by the scheduler (`weebot/scheduling/default_jobs.py`); `MemoryPressureEvent` and `LLMHealthEvent` have had no emitter since the unwired heartbeat monitors were deleted; they cannot round-trip through `Session.events`.
- `DomainEvent` (`:352-357`) and 17 subclasses (`:360-547`): `FactDiscovered`, `MemoryCompacted`, `PlanStepCompleted`, `TrajectoryScored`, `SkillEdit{Proposed,Accepted,Rejected}`, `EpochCompleted`, `SkillGapDetected`, `LLMCallCompleted` (the cost fact, F23), `SkillDistilled`, `SkillPromoted`, `CorrectionPatternDetected`, `SessionConstraint{Recorded,Revoked}`.
- Enums: `FailureSeverity` (`:13-23`), `ToolStatus` (`:29-31`).

Consequences (read from source, not run):
- Never constructed in `weebot/` or `cli/` (grep 2026-10-24): `TrajectoryDiagnosisEvent`, `SkillEditProposed`, `MemoryCompacted`. `MemoryCompacted` has a subscriber branch (`infrastructure/events/subscriber.py:26`) that cannot fire.
- `ErrorEvent.failure_severity` (`:51`) is never set by a constructor or read; the executing state classifies severity as a plain string instead (`application/agents/executor/_error_handler.py:162`, `weebot/application/flows/states/_step_outcome.py:120-122`). The `FailureSeverity` docstring says "3-tier" over four members (`:14, 20-23`).
- `PlanStepCompleted` is published for every `StepEvent`, including STARTED and FAILED (`application/flows/event_publisher.py:156-158`: the check is only `event.type == "step"`).
- `_emit_domain_event` has one home: `event_publisher.py:149`, called at `:76`.
- `reconstruct_events` logs and drops a dict it cannot parse (`event_reconstructor.py:49-57`); `_row_to_session` turns it into a `MessageEvent(**e)` instead (`sqlite_state_repo.py:545-549`). Two policies for the same failure.
- The web UI declares 11 event types (`weebot-ui/src/types/events.ts`); `tool_approval`, `product_gate_review`, `thought` and the other backend members have no type in `weebot-ui/src` (grep 2026-10-24). Whether the UI renders them some other way was not checked.

## Connected to
- **Stored in** `Session.events` (Session card). **Published on** `EventBusPort` (`application/ports/event_bus_port.py:15`); domain events through `publish_domain_event` (`:24`). **Journaled by** the event store (EventStore card); `LLMCallCompleted` feeds its cost columns (`:467-479`).
- **Yielded by** `PlannerAgent` (`PlanEvent`, `application/agents/planner.py:279, 309`), `ExecutorAgent` (`StepEvent`, `ToolEvent`, `weebot/application/agents/executor/_base.py:554, 725, 714`; `weebot/application/agents/executor/_tool_batch.py:82, 174`; `weebot/application/agents/executor/_turn.py:63, 79`), flow states (`WaitForUserEvent`, `PlanReviewEvent`, `ToolApprovalEvent`).
- **Rebuilt by** `reconstruct_events` (CQRS results back into events, `planning.py:266`) and `SQLiteStateRepository._row_to_session`.
- **Looks like but is not:** `EventPublisher` Protocol in `weebot/domain/ports.py:60` vs `EventPublisherPort` ABC in `application/ports/event_publisher_port.py:16`; legacy `Message`/`Checkpoint` (`domain/legacy_models.py:105, 206`).

## If you change this
**Hits:** every stored session row (the `type` literal and field names are the JSON), the UI event types, WebSocket/SSE routing on `session_id`, the event store, the CLI event logger (`interfaces/cli/event_logger.py`). Tests: `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/application/services/test_approval_journal.py`, `tests/unit/test_task_runner_presence.py`, `tests/unit/interfaces/web/test_d50_event_scope_routing.py`, `tests/unit/test_session_replace_events.py`; 73 test files import `weebot.domain.models.event` (grep 2026-10-24).
**Does not hit:** the event bus implementation (EventBus card).

## Surfaces
Web UI stream, CLI event logger, MCP server, event store queries.

## See
`weebot/domain/models/event.py`
