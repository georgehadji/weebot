# Cron & Heartbeat Integration Plan
**Project**: weebot
**Scope**: Wire the existing but unstarted `SchedulingManager`, add 4 default cron jobs,
introduce a `HeartbeatManager` with 3 initial monitors, and add the domain events and
Prometheus gauges each requires. All code respects the Dependency Rule:
Domain ← Application ← Infrastructure ← Interfaces.

---

## Context: What Already Exists

| Component | File | State |
|-----------|------|-------|
| `SchedulingManager` (APScheduler + SQLite) | `weebot/scheduling/scheduler.py` | Built, never started |
| `MemoryMonitor` (RSS + heap, `check_memory()`, `start()`) | `weebot/core/memory_monitor.py` | Built, never started |
| `MemoryCompactor.compact_session()` | `weebot/application/services/memory_compactor.py` | Built |
| `SkillCurator.run_curation()` | `weebot/application/services/skill_curator.py` | Built |
| `HealthCheckService` (on-demand checks only) | `weebot/infrastructure/observability/health_checks.py` | Built, on-demand only |
| `session_active` + `events_pending` Prometheus Gauges | `weebot/infrastructure/observability/metrics.py` | Built |
| `Session.updated_at`, `.context.archived`, `.context.archive_ttl_days` | `weebot/domain/models/session.py` | Built |
| FastAPI `lifespan()` — scheduler hookup point | `weebot/interfaces/web/main.py:129` | Empty — Container only |
| `Container.configure_defaults()` | `weebot/application/di/__init__.py:104` | No scheduler registered |

The key gap is not missing code — it is **orchestration**: nothing calls
`scheduler.start()`, nothing registers default jobs, nothing runs monitors
continuously.

---

## Issue Index

| # | Phase | Category | Action |
|---|-------|----------|--------|
| 1 | 1 | Wiring | Register `SchedulingManager` in DI and start/stop in FastAPI lifespan |
| 2 | 2 | Domain | Add `SessionStalenessEvent`, `MemoryPressureEvent`, `ScheduledJobEvent` |
| 3 | 2 | Metrics | Add 5 missing Prometheus gauges/counters |
| 4 | 3 | Jobs | `default_jobs.py` — session-health + memory-compaction + skill-curation jobs |
| 5 | 4 | Heartbeat | `Monitor` ABC + `HeartbeatManager` in `weebot/infrastructure/monitors/` |
| 6 | 4 | Heartbeat | `SessionStalenessMonitor` and `MemoryPressureMonitor` implementations |
| 7 | 5 | Jobs | `SessionArchiver` service + nightly archive job |
| 8 | 6 | Heartbeat | `LLMHealthMonitor` wrapping existing `HealthCheckService` |

---

## Architectural Compliance

| Fix | Layer modified | Import direction |
|-----|---------------|-----------------|
| 1 | Interfaces → Infrastructure | Interfaces imports scheduling — correct |
| 2 | Domain | No new imports — domain is pure |
| 3 | Infrastructure | No cross-layer imports |
| 4 | Application (default_jobs) | Imports domain models + Application ports |
| 5-6 | Infrastructure/monitors | Imports domain events + Application ports |
| 7 | Application/services | Imports domain models + Application ports |
| 8 | Infrastructure/monitors | Imports infrastructure health service only |

---

## Phase 1 — Wire the Scheduler

**Goal**: `SchedulingManager` becomes a DI-managed singleton that starts and stops
cleanly with the FastAPI server. No new logic — purely wiring.

**Estimated effort**: 1–2 hours

### 1a. Register in DI Container

**File**: `weebot/application/di/__init__.py`

Add to `configure_defaults()`:

```python
from weebot.scheduling.scheduler import SchedulingManager
self.register("scheduler", lambda: SchedulingManager())
```

Add a convenience getter so the lifespan hook and future routers can resolve it:

```python
def build_scheduler(self) -> "SchedulingManager":
    from weebot.scheduling.scheduler import SchedulingManager
    return self.get("scheduler")
```

### 1b. Start/stop in FastAPI lifespan

**File**: `weebot/interfaces/web/main.py` — `lifespan()` at line 129

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting Weebot Web Server...")
    container = Container()
    container.configure_defaults()
    app.state.container = container

    # Wire and start scheduler
    scheduler = container.build_scheduler()
    from weebot.scheduling.default_jobs import register_default_jobs
    register_default_jobs(scheduler, container)
    await scheduler.start()
    app.state.scheduler = scheduler

    yield

    # Graceful shutdown — heartbeat first (fast), scheduler second (waits for jobs)
    if hasattr(app.state, "heartbeat"):
        await app.state.heartbeat.stop()
    await scheduler.stop()
    logger.info("Shutting down Weebot Web Server...")
```

### Tests

**New file**: `tests/unit/test_scheduler_wiring.py`

- `test_scheduler_starts_on_app_startup` — use `AsyncClient` + lifespan; mock `scheduler.start()`; assert it's called
- `test_scheduler_stops_on_app_shutdown` — mock `scheduler.stop()`; assert it's called in teardown
- `test_default_jobs_registered_on_startup` — mock `register_default_jobs`; assert it receives scheduler + container

---

## Phase 2 — Domain Events & Prometheus Metrics

**Goal**: Add typed domain events that cron jobs and monitors publish, and the
Prometheus gauges that give real-time visibility into scheduler and monitor state.

**Estimated effort**: 1–2 hours

### 2a. New domain events

**File**: `weebot/domain/models/event.py`

Append three new event classes after existing definitions. All inherit `BaseEvent`
(already in the file) which provides `id` and `timestamp` via Pydantic.

```python
class SessionStalenessEvent(BaseEvent):
    """Emitted when a RUNNING session has had no update for > threshold minutes."""
    type: Literal["session_staleness"] = "session_staleness"
    session_id: str
    staleness_minutes: float
    status: str          # SessionStatus value as string

class MemoryPressureEvent(BaseEvent):
    """Emitted when process memory crosses warning or critical threshold."""
    type: Literal["memory_pressure"] = "memory_pressure"
    level: str           # "warning" | "critical"
    rss_mb: float
    percent: float       # fraction of configured max_mb

class ScheduledJobEvent(BaseEvent):
    """Emitted on scheduled job completion (success or failure)."""
    type: Literal["scheduled_job"] = "scheduled_job"
    job_id: str
    job_name: str
    outcome: str         # "success" | "failure"
    duration_seconds: float
    error: str | None = None
```

No imports are added into the domain layer. `BaseEvent` is already domain-pure.

### 2b. New Prometheus gauges

**File**: `weebot/infrastructure/observability/metrics.py`

Append after the existing `session_persistence_failures_total` counter:

```python
# -- Scheduling --
scheduled_jobs_active = Gauge(
    "weebot_scheduled_jobs_active",
    "Number of scheduled jobs currently executing",
)
scheduled_jobs_runs_total = Counter(
    "weebot_scheduled_jobs_runs_total",
    "Scheduled job run completions",
    ["job_id", "outcome"],   # outcome: "success" | "failure"
)

# -- Monitors / Heartbeat --
session_stale_count = Gauge(
    "weebot_sessions_stale_count",
    "RUNNING sessions with no update beyond the staleness threshold",
)
memory_rss_mb = Gauge(
    "weebot_memory_rss_mb",
    "Process RSS memory in megabytes",
)
memory_percent = Gauge(
    "weebot_memory_percent",
    "Process memory as a percentage of the configured limit",
)
```

### Tests

**New file**: `tests/unit/test_event_types.py`

- `test_session_staleness_event_type_literal` — assert `SessionStalenessEvent().type == "session_staleness"`
- `test_memory_pressure_event_fields`
- `test_scheduled_job_event_optional_error`
- `test_all_new_event_type_literals_are_unique`

---

## Phase 3 — Default Cron Jobs

**Goal**: Three high-value jobs registered at startup using existing services.
All jobs are registered via `scheduler.register_callable()` and created with
`scheduler.create_job()`. Registration is idempotent: if the job already exists
in the persisted SQLite store it is not re-created.

**Estimated effort**: 3–4 hours

### New file: `weebot/scheduling/default_jobs.py`

```python
"""Default scheduled jobs registered at application startup.

All jobs are plain async callables registered with SchedulingManager via
register_callable(). Each job is created idempotently: if it already
exists in the persisted job store it is skipped.

Layer: this module sits at the boundary of Application and Infrastructure.
It imports Application ports (via container) and Infrastructure (scheduler).
It does NOT import from Interfaces.
"""
```

#### Job 1: Session Health Snapshot

```
Job ID:    weebot_session_health
Trigger:   interval, every 12 hours
Callable:  _session_health_job(state_repo, event_bus)
```

Logic:
1. `sessions = await state_repo.list_sessions()`
2. For each session with `status == RUNNING`:
   - `staleness = (now - session.updated_at).total_seconds() / 60`
   - If `staleness > STALE_THRESHOLD_MINUTES` (default: 60):
     - Publish `SessionStalenessEvent(session_id, staleness_minutes, status)` to `event_bus`
3. Update `metrics.session_stale_count.set(stale_count)`
4. Log: `N sessions checked, M stale`

`state_repo: StateRepositoryPort` and `event_bus: EventBusPort` are injected via
closure from `register_default_jobs(scheduler, container)`.

#### Job 2: Memory Compaction

```
Job ID:    weebot_memory_compact
Trigger:   interval, every 4 hours
Callable:  _memory_compact_job(state_repo)
```

Logic:
1. `sessions = await state_repo.list_sessions()` — filter `status == RUNNING`
2. For each: `compacted = MemoryCompactor().compact_session(session)`
3. `await state_repo.save_session(compacted)`
4. Log: `N sessions compacted`

`compact_session()` returns a new immutable `Session` — no mutation.

#### Job 3: Skill Curation

```
Job ID:    weebot_skill_curation
Trigger:   cron, daily at 02:00
Callable:  _skill_curation_job(llm_port)
```

Logic:
1. `curator = SkillCurator(llm=llm_port)`
2. `await curator.run_curation()`
3. Log outcome

`SkillCurator` already uses `MODEL_BUDGET` internally — cost is negligible.

#### Shared: `ScheduledJobEvent` wrapper

Wrap each callable in a decorator that:
1. Sets `scheduled_jobs_active` gauge (`+1` on entry, `-1` on exit)
2. Records start time
3. On success: publishes `ScheduledJobEvent(outcome="success", duration_seconds=...)`
   and increments `scheduled_jobs_runs_total` with `outcome="success"`
4. On exception: publishes `ScheduledJobEvent(outcome="failure", error=str(exc))`
   and increments counter with `outcome="failure"`; re-raises so APScheduler
   records the error in its own job log

This wrapper is applied in `register_default_jobs()` before `register_callable()`.

#### Idempotent registration helper

```python
async def _create_if_absent(scheduler, job_id, **kwargs) -> None:
    if scheduler.get_job(job_id) is None:
        await scheduler.create_job(job_id=job_id, **kwargs)
```

### Tests

**New file**: `tests/unit/test_default_jobs.py`

- `test_session_health_job_detects_stale_session` — mock sessions with old `updated_at`; assert `SessionStalenessEvent` published
- `test_session_health_job_silent_when_all_fresh` — no event published when all sessions recently updated
- `test_memory_compact_job_saves_compacted_sessions` — mock `state_repo.save_session`; assert called with compacted result
- `test_skill_curation_job_calls_run_curation` — mock `SkillCurator`; assert `run_curation()` called
- `test_jobs_registered_idempotently` — call `register_default_jobs` twice; assert `create_job` called once per job
- `test_scheduled_job_event_emitted_on_success`
- `test_scheduled_job_event_emitted_on_failure`

---

## Phase 4 — HeartbeatManager

**Goal**: A background asyncio loop running lightweight monitors at configurable
intervals, publishing domain events only on state *transitions* (not every pulse).

**Estimated effort**: 4–5 hours

### New files

#### `weebot/infrastructure/monitors/__init__.py`

```python
from .base import Monitor, MonitorReport, MonitorState
from .heartbeat_manager import HeartbeatManager

__all__ = ["Monitor", "MonitorReport", "MonitorState", "HeartbeatManager"]
```

#### `weebot/infrastructure/monitors/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

class MonitorState(str, Enum):
    HEALTHY  = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"

@dataclass
class MonitorReport:
    state: MonitorState
    message: str
    metadata: dict = field(default_factory=dict)

class Monitor(ABC):
    """One lightweight periodic check.

    - check() must be non-blocking (async def).
    - HeartbeatManager cancels checks that exceed 2 x interval_seconds.
    """
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def interval_seconds(self) -> int: ...

    @abstractmethod
    async def check(self) -> MonitorReport: ...
```

#### `weebot/infrastructure/monitors/heartbeat_manager.py`

Key design decisions:
- One `asyncio.Task` per monitor — isolation; one crash does not kill others
- Events published only on state transition (`prev_state != report.state`)
- `stop()` cancels all tasks and awaits them within `cancel_timeout`

```python
class HeartbeatManager:
    def __init__(
        self,
        monitors: list[Monitor],
        event_bus: EventBusPort,
        cancel_timeout: float = 5.0,
    ) -> None:
        self._monitors = monitors
        self._event_bus = event_bus
        self._cancel_timeout = cancel_timeout
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        for monitor in self._monitors:
            task = asyncio.create_task(
                self._run_monitor_loop(monitor),
                name=f"monitor.{monitor.name}",
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run_monitor_loop(self, monitor: Monitor) -> None:
        prev_state: MonitorState | None = None
        while True:
            await asyncio.sleep(monitor.interval_seconds)
            try:
                report = await asyncio.wait_for(
                    monitor.check(),
                    timeout=monitor.interval_seconds * 2,
                )
            except asyncio.CancelledError:
                raise   # propagate cancellation
            except asyncio.TimeoutError:
                logger.warning("Monitor %s timed out", monitor.name)
                continue
            except Exception:
                logger.exception("Monitor %s check raised", monitor.name)
                continue

            if report.state != prev_state:
                await self._publish_transition(monitor.name, prev_state, report)
                prev_state = report.state

    async def _publish_transition(
        self, name: str, prev: MonitorState | None, report: MonitorReport
    ) -> None:
        # Publish the appropriate domain event based on the monitor name.
        # Each monitor subclass registers a factory or the manager uses
        # a dispatch table to map monitor name -> event constructor.
        ...
```

#### `weebot/infrastructure/monitors/session_staleness_monitor.py`

```python
class SessionStalenessMonitor(Monitor):
    name = "session_staleness"
    interval_seconds = 30

    STALE_THRESHOLD_MINUTES = 60   # configurable via constructor

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        stale_threshold_minutes: int = STALE_THRESHOLD_MINUTES,
    ) -> None: ...

    async def check(self) -> MonitorReport:
        sessions = await self._state_repo.list_sessions()
        running  = [s for s in sessions if s.status == SessionStatus.RUNNING]
        stale    = [
            s for s in running
            if (datetime.now(timezone.utc) - s.updated_at).total_seconds() / 60
               > self._threshold
        ]
        metrics.session_stale_count.set(len(stale))

        if not stale:
            return MonitorReport(MonitorState.HEALTHY, "No stale sessions")
        if len(stale) <= 3:
            return MonitorReport(
                MonitorState.DEGRADED,
                f"{len(stale)} stale session(s)",
                metadata={"stale_ids": [s.id for s in stale]},
            )
        return MonitorReport(
            MonitorState.CRITICAL,
            f"{len(stale)} stale sessions — possible deadlock",
            metadata={"stale_ids": [s.id for s in stale]},
        )
```

**Transition event emitted**: `SessionStalenessEvent` with `session_id="__batch__"` and
count in metadata. On DEGRADED → HEALTHY, a recovery event is logged (no domain event
needed for recovery — just a log line).

#### `weebot/infrastructure/monitors/memory_pressure_monitor.py`

```python
class MemoryPressureMonitor(Monitor):
    name = "memory_pressure"
    interval_seconds = 10

    def __init__(
        self,
        thresholds: MemoryThresholds | None = None,
    ) -> None:
        # Instantiate MemoryMonitor but do NOT call .start() on it.
        # We drive the polling loop ourselves from HeartbeatManager.
        self._inner = MemoryMonitor(thresholds=thresholds or MemoryThresholds())

    async def check(self) -> MonitorReport:
        # check_memory() uses psutil (sync). Wrap in asyncio.to_thread() if
        # benchmarking shows it blocks the event loop for > 1ms.
        stats: MemoryStats = self._inner.check_memory()
        metrics.memory_rss_mb.set(stats.rss_mb)
        metrics.memory_percent.set(stats.percent)

        if stats.percent >= self._inner.thresholds.critical_percent:
            return MonitorReport(
                MonitorState.CRITICAL,
                f"Memory critical: {stats.rss_mb:.0f} MB ({stats.percent:.0f}%)",
                metadata={"rss_mb": stats.rss_mb, "percent": stats.percent},
            )
        if stats.percent >= self._inner.thresholds.warning_percent:
            return MonitorReport(
                MonitorState.DEGRADED,
                f"Memory warning: {stats.rss_mb:.0f} MB ({stats.percent:.0f}%)",
                metadata={"rss_mb": stats.rss_mb, "percent": stats.percent},
            )
        return MonitorReport(MonitorState.HEALTHY, f"Memory OK: {stats.rss_mb:.0f} MB")
```

**Transition event emitted**: `MemoryPressureEvent(level, rss_mb, percent)`.

### Wire HeartbeatManager in lifespan

**File**: `weebot/interfaces/web/main.py` — inside `lifespan()`, after `scheduler.start()`

```python
from weebot.infrastructure.monitors import HeartbeatManager
from weebot.infrastructure.monitors.session_staleness_monitor import SessionStalenessMonitor
from weebot.infrastructure.monitors.memory_pressure_monitor import MemoryPressureMonitor

monitors = [
    SessionStalenessMonitor(state_repo=container.get(StateRepositoryPort)),
    MemoryPressureMonitor(),
]
heartbeat = HeartbeatManager(monitors=monitors, event_bus=container.get(EventBusPort))
app.state.heartbeat = heartbeat
await heartbeat.start()
```

### Tests

**New file**: `tests/unit/infrastructure/test_heartbeat_manager.py`

- `test_publishes_event_on_state_transition` — mock monitor returning HEALTHY then DEGRADED; assert event published once
- `test_silent_on_steady_state` — same state twice; assert no event published
- `test_monitor_crash_does_not_kill_sibling` — first monitor raises; second monitor continues running
- `test_timeout_does_not_kill_loop` — monitor exceeds 2x interval; assert loop continues

**New file**: `tests/unit/infrastructure/test_session_staleness_monitor.py`

- `test_healthy_when_no_running_sessions`
- `test_healthy_when_sessions_recently_updated`
- `test_degraded_when_one_session_stale`
- `test_critical_when_more_than_three_stale`

**New file**: `tests/unit/infrastructure/test_memory_pressure_monitor.py`

- `test_healthy_below_warning_threshold`
- `test_degraded_at_warning_threshold`
- `test_critical_at_critical_threshold`
- `test_prometheus_gauges_updated_on_every_check`

---

## Phase 5 — Session Archiver Job

**Goal**: Completed sessions past their `archive_ttl_days` are marked archived
automatically. No session is ever deleted; `archived=True` excludes them from
active-session listings while keeping them queryable for audit.

**Estimated effort**: 2–3 hours

### New file: `weebot/application/services/session_archiver.py`

```python
class SessionArchiver:
    """Marks completed/failed sessions as archived when they exceed their TTL.

    Application layer — imports only Domain models and Application ports.
    Never deletes sessions; sets context.archived=True so they are
    excluded from active-session lists but remain queryable.
    """

    def __init__(self, state_repo: StateRepositoryPort) -> None:
        self._state_repo = state_repo

    async def run_archival(self) -> int:
        """Archive eligible sessions. Returns count archived."""
        sessions = await self._state_repo.list_sessions()
        now = datetime.now(timezone.utc)
        archived = 0
        for session in sessions:
            if not self._should_archive(session, now):
                continue
            updated = session.model_copy(update={
                "context": session.context.model_copy(update={
                    "archived": True,
                    "archived_at": now.isoformat(),
                })
            })
            await self._state_repo.save_session(updated)
            archived += 1
        logger.info("Session archival complete: %d archived", archived)
        return archived

    @staticmethod
    def _should_archive(session: Session, now: datetime) -> bool:
        if session.context.archived:
            return False                              # already done
        if session.status not in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            return False                              # don't touch RUNNING/WAITING
        ttl = timedelta(days=session.context.archive_ttl_days)
        # updated_at may be naive; normalise to UTC before comparison
        updated = session.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated) > ttl
```

### Wire as Job 4 in `default_jobs.py`

```
Job ID:    weebot_session_archive
Trigger:   cron, daily at 03:00
Callable:  SessionArchiver(state_repo=state_repo).run_archival()
```

### Tests

**New file**: `tests/unit/test_session_archiver.py`

- `test_archives_completed_session_past_ttl`
- `test_archives_failed_session_past_ttl`
- `test_does_not_archive_running_session`
- `test_does_not_archive_waiting_session`
- `test_does_not_archive_session_within_ttl`
- `test_does_not_re_archive_already_archived_session`
- `test_returns_correct_archive_count`
- `test_handles_naive_updated_at_timestamps`

---

## Phase 6 — LLM Health Monitor

**Goal**: Detect LLM provider degradation within 2 minutes using the existing
`HealthCheckService`. No API quota is consumed — `HealthCheckService` does
lightweight connectivity checks, not generation calls.

**Estimated effort**: 2 hours

### New file: `weebot/infrastructure/monitors/llm_health_monitor.py`

```python
class LLMHealthMonitor(Monitor):
    name = "llm_health"
    interval_seconds = 120  # 2 minutes

    def __init__(self, health_service: HealthCheckService) -> None:
        self._health = health_service

    async def check(self) -> MonitorReport:
        report = await self._health.check_all()
        llm_components = [
            c for c in report.components
            if "llm" in c.name.lower() or "openrouter" in c.name.lower()
        ]
        if not llm_components:
            return MonitorReport(MonitorState.HEALTHY, "No LLM components registered")

        unhealthy = [c for c in llm_components if c.status == HealthStatus.UNHEALTHY]
        degraded  = [c for c in llm_components if c.status == HealthStatus.DEGRADED]

        if unhealthy:
            return MonitorReport(
                MonitorState.CRITICAL,
                f"{len(unhealthy)} LLM provider(s) UNHEALTHY",
                metadata={"unhealthy": [c.name for c in unhealthy]},
            )
        if degraded:
            return MonitorReport(
                MonitorState.DEGRADED,
                f"{len(degraded)} LLM provider(s) degraded",
                metadata={"degraded": [c.name for c in degraded]},
            )
        return MonitorReport(MonitorState.HEALTHY, "All LLM providers healthy")
```

Add a new domain event in `event.py`:

```python
class LLMHealthEvent(BaseEvent):
    """Emitted when LLM provider health transitions between states."""
    type: Literal["llm_health"] = "llm_health"
    state: str             # "healthy" | "degraded" | "critical"
    affected_providers: list[str]
    message: str
```

Wire into `HeartbeatManager` in lifespan alongside the Phase 4 monitors:

```python
from weebot.infrastructure.monitors.llm_health_monitor import LLMHealthMonitor

monitors = [
    SessionStalenessMonitor(...),
    MemoryPressureMonitor(),
    LLMHealthMonitor(health_service=HealthCheckService(...)),
]
```

---

## Implementation Order

```
Phase 1 (wiring, ~2h)     -> Scheduler starts + stops with server. Unblocks all jobs.
Phase 2 (domain, ~2h)     -> Events + metrics ready for all consumers.
Phase 3 (jobs, ~4h)       -> 3 default cron jobs running.
Phase 4 (heartbeat, ~5h)  -> SessionStaleness + MemoryPressure monitors running.
Phase 5 (archiver, ~3h)   -> Nightly archival job (can run after Phase 1 + 2).
Phase 6 (llm monitor, ~2h)-> LLM health continuous probe (can run after Phase 4).

Total:  ~18 hours of focused implementation
```

- Phases 1 and 2 are prerequisites for all others.
- Phases 3 and 4 are independent of each other after Phase 2.
- Phase 5 is independent of Phase 4; depends only on Phase 1 + 2.
- Phase 6 depends on Phase 4 (HeartbeatManager infrastructure).

---

## Full File Inventory

### New files

```
weebot/scheduling/default_jobs.py
weebot/application/services/session_archiver.py
weebot/infrastructure/monitors/__init__.py
weebot/infrastructure/monitors/base.py
weebot/infrastructure/monitors/heartbeat_manager.py
weebot/infrastructure/monitors/session_staleness_monitor.py
weebot/infrastructure/monitors/memory_pressure_monitor.py
weebot/infrastructure/monitors/llm_health_monitor.py
tests/unit/test_scheduler_wiring.py
tests/unit/test_default_jobs.py
tests/unit/test_session_archiver.py
tests/unit/test_event_types.py
tests/unit/infrastructure/test_heartbeat_manager.py
tests/unit/infrastructure/test_session_staleness_monitor.py
tests/unit/infrastructure/test_memory_pressure_monitor.py
```

### Modified files

```
weebot/application/di/__init__.py             register "scheduler" + build_scheduler()
weebot/interfaces/web/main.py                 lifespan: start/stop scheduler + heartbeat
weebot/domain/models/event.py                 4 new event types (+ LLMHealthEvent in Phase 6)
weebot/infrastructure/observability/metrics.py  5 new gauges/counters
weebot/scheduling/default_jobs.py             Phase 5 adds 4th job (session_archive)
```

---

## Invariants & Constraints

1. **No mutation** — `SessionArchiver` uses `model_copy()`. `MemoryCompactor` already returns a new `Session`. No in-place modification anywhere.
2. **No blocking in async loops** — all `Monitor.check()` methods are `async def`. `MemoryMonitor.check_memory()` calls `psutil` (sync); wrap with `asyncio.to_thread()` if benchmark shows > 1ms event-loop block.
3. **Transition-only events** — `HeartbeatManager._run_monitor_loop()` compares `report.state != prev_state` before publishing. Steady-state pulses are silent. No spam.
4. **Idempotent job registration** — `register_default_jobs()` calls `scheduler.get_job(job_id)` before `create_job()`. Safe across server restarts.
5. **Graceful shutdown ordering** — `lifespan()` teardown: stop heartbeat first (fast — just cancels tasks), then stop scheduler (APScheduler waits for in-progress jobs up to its own `wait` timeout).
6. **Cost discipline** — Skill curation uses `MODEL_BUDGET` (enforced inside `SkillCurator`). No Phase 3–6 code introduces new LLM calls that are not already gated by the existing cascade service.
7. **MemoryMonitor ownership** — `MemoryPressureMonitor` instantiates `MemoryMonitor` and calls `check_memory()` directly. It does NOT call `MemoryMonitor.start()`. Two competing polling loops for the same resource would be a bug.
