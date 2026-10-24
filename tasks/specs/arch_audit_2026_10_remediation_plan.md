---
status: open
date: 2026-10-24
note: from the 2026-10-24 EGFV audit (4/10); nothing executed; decisions D1-D6 resolved 2026-10-24; Phase 8 defers to the 2026-09 plan's Phase 5
---

# Architecture Remediation — 2026-10 audit

Follows the EGFV static audit of `feat/icm-a4-walk` at `25b72563` (2026-10-24). That audit
scored the code **4/10** on its five-dimension rubric:

| Dimension | Score |
|---|---|
| Separation of concerns | 1 |
| Consistency with baseline | 1 |
| Coupling and dependency health | 0 |
| Testability and observability | 1 |
| Failure resilience and scalability | 1 |

`ARCHITECTURE.md` still reports 9.0. The audit's ledger is reproduced in Appendix B, so this
file stands on its own.

**This is a plan, not an implementation.** Nothing here has been executed.

**Relation to open plans.**

- `tasks/specs/arch_audit_2026_09_remediation_plan.md` (the "Sep plan") stays the owner of
  four things:
  - its Phase 5 (Postgres, scheduler extraction, replica proof);
  - §4.3 (god methods);
  - §5.4 (narrow `FlowContext`);
  - pattern P2 (typed DI keys).

  This plan does not restate those. It adds inputs and acceptance numbers, and says where an
  item here unblocks one there. Where the two plans disagree, the Sep plan wins for its
  phases, and this plan wins for everything new in Appendix B.
- `tasks/remaining_fix_plan.md` waves are independent of this plan, except the overlaps in §12.

**Method caveat, carried from the audit.** The import graph came from an AST walk:
TYPE_CHECKING imports excluded, function-level imports included, cycles found with Tarjan SCC.
`lint-imports` and pytest were not run in that session. Phase 0 makes both reproducible
before any fix lands.

---

## 1. What this plan closes

| ID | Finding (one line) | Sev | Phase |
|---|---|---|---|
| SEC-1 | Untrusted-output fence and egress taint key off a hand-kept name list. Unlisted tools and error results enter the prompt unfenced. | HIGH | 1.1 |
| SCL-1 | Single replica: SQLite single writer, scheduler in the FastAPI lifespan, TaskRunner state in process dicts. | HIGH | 8 (Sep plan Phase 5) |
| LAY-4 | 18 `importlib.import_module("weebot.…")` calls hide edges from import-linter. 3 say so in a comment. | MED | 0.2 |
| LAY-1 | Layer cycles `tools↔application`, `tools↔infrastructure`, `core→tools/di`, covered by 73 exemptions | MED | 3.1–3.5 |
| LAY-2 | Module cycles: `flows/states/*` (8), `application.di↔interfaces` (3), `templates` (3) | MED | 3.6–3.8 |
| SEC-2 | `web/auth.py` builds `SQLiteApiKeyStore()` and calls its private hash helpers, twice, bypassing `ApiKeyPort` | MED | 1.2 |
| ORCH-1 | Global `LLMPool` bounds only the cascade path. 68 direct `.chat/.complete` calls bypass it. | MED | 2.1 |
| ORCH-2 | No idempotency anywhere. Session retry (`task_runner.py:270-286`) can replay sends. | MED | 2.2 |
| CON-1 | 8 fire-and-forget `create_task`/`ensure_future` calls with discarded results. `BackgroundTasks.spawn` exists and is unused there. | MED | 1.3 |
| CON-2 | 29 blocking calls in `async def` (ratchet). 4 are linter false positives. The scheduler's are on the web loop. | MED | 4 |
| CPL-1 | `_base.py` 1180 lines, `plan_act_flow.py` 985, `di/__init__.py` 700 | MED | 5 (Sep §4.3) |
| CPL-2 | String-keyed service locator (`di/__init__.py:459`) | MED | 5 (Sep P2) |
| DOC-1 | `ARCHITECTURE.md:61` says "remaining 10 entries". The actual count is 73. | MED | 7 |
| DOC-3 | ADR-007 says ~803 lines for `_base.py`. The actual count is 1180. | MED | 7 |
| DOC-2 | ADR-008 says `TaskQueuePort` was deleted. It still exists and is dead. | LOW | 7 (D4: keep, reserved) |
| DOC-4 | Self-score 9.0/10 is stale | LOW | 7 |
| DOC-5 | `trust_boundary.py:9` says output is "scanned by AgentMemorySanitizer". It is not. | LOW | 1.1b (D2: wire the scan) |
| LAY-3 | `config` imports `application.services` twice. Highest fan-in package. | LOW | 3.9 |
| ORCH-3 | Retry layers may multiply under a provider outage (unmeasured) | LOW | 2.3 |
| ORCH-4 | No per-session USD cap on the main flow. Resolved 2026-10-24: none exists (§2.4). | MED | 2.4 (D6) |
| OBS-1 | `correlation_id` appears in 4 files. No prompt versioning. | LOW | 6 |
| CI-1 | `lint-no-print` and `lint-map` run only in `make check`, not CI. Coverage floor 52%. ruff selects only F821 and E9. | LOW | 0.3 |
| OPS-1 | Valkey password falls back to `weebot_default` | LOW | 1.4 (D5: accepted, guard pinned) |
| UNK-1 | `docs/SECURITY_MODEL.md` behavior claims unverified (the doc says so) | — | 7 |

---

## 2. Design approach

### 2.1 Paradigm: functional core, imperative shell

Every defect above has one shape: a decision is made implicitly in the wrong place.

- A name list nobody updates decides trust.
- A semaphore only one caller acquires decides concurrency.
- A task nobody owns decides whether a webhook reply is sent.
- A comment decides that an import does not count.

So the rule for every change in this plan has three parts:

1. **Decisions are pure functions over immutable values.** Examples: trust classification,
   effect keys, state transition targets, the retry budget. They live in `domain` or `core`,
   take frozen dataclasses or enums, return values, and do no I/O. Each gets table-driven
   unit tests.
2. **Effects live at the edges.** Locks, tasks, files and network calls live in decorators
   around ports, or in the composition root. The domain keeps its Pydantic aggregates with
   behavior on the aggregate, as the Sep plan §2.3 already settled.
3. **Defaults fail closed.** Where a classification is missing, the safe answer is the
   default, not the exception.

OOP with constructor injection stays the shell. No paradigm migration.

### 2.2 Patterns to apply

| # | Pattern | Applied at | Replaces | Why this one |
|---|---|---|---|---|
| Q1 | **Secure-by-default type attribute** (default-deny) | `domain/models/base_tool.py` `output_trust` | Name sets in `core/trust_boundary.py` | Trust becomes a property of the tool, not of a list beside it. A new tool is fenced and tainted until someone declares it `LOCAL` in review. It removes the failure class (the list drifted 3 times: `trust_boundary.py:42-49`, F46, F67). |
| Q2 | **Bulkhead as a Decorator on the port, plus a ContextVar admission token** | `application/strategies/llm_pool.py` | Pool acquired only in `_cascade.py:302,676` | One bound for every caller of `LLMPort`, applied once in the composition root. The token lets the cascade keep acquiring *outside* its `wait_for`, so queue time never counts against a model's timeout (`llm_pool.py:23-30`). Without the token, a nested acquire could deadlock at saturation. |
| Q3 | **Idempotent Receiver (effect ledger)** keyed by canonical action | `_tool_executor.py` pre-hook | Nothing | Session retry re-runs flows. The key reuses `CanonicalizerPort` (already used for approval grants) and the store reuses session facts, which are already persisted per event (`task_runner.py:258`). |
| Q4 | **Owned task group** (existing `BackgroundTasks.spawn`) | 8 discarded-task sites | `asyncio.create_task(...)` dropped on the floor | The repo already built and documented the fix (`application/services/background_tasks.py`). Apply it. Do not invent a second one. |
| Q5 | **Move Class to its policy owner** | `tools/tool_registry.py` → application | Application importing the tools package in 7 places | `RoleBasedToolRegistry` is authorization policy over the domain `BaseTool`. It imports nothing from concrete tools except one lazy Playwright factory, which becomes an injected callable. |
| Q6 | **State pattern with a transition table** | `flows/states/*` | States lazily importing their successors (`executing.py:240,274,599,774`) | States return a `Transition(target: StateId, …)`. One registry maps `StateId → type[FlowState]`. That dissolves the 8-module SCC and prepares Sep §5.4. |
| Q7 | **Composition root at the edge** | `application/di` ↔ `interfaces` | `di/__init__.py:255,411` importing interfaces | Wiring that needs interface objects is registered by the entry point, or moves to the layer that owns it. |
| Q8 | **Value object to the innermost layer that uses it** | `TaskCategory` enum | `config → application.services` | Config becomes a leaf. A contract then keeps it one. |
| Q9 | **Fitness functions + bidirectional ratchets** | `scripts/`, `ceilings.toml`, CI | Prose targets | Every invariant ships with the check that pins it. This is the project's own idiom (`ceilings.toml:1-23`). Reuse it; build no new framework. |
| Q10 | **Numbers live with their instrument** | `ARCHITECTURE.md` | Hand-typed counts | DOC-1, DOC-3 and DOC-4 are all hand-copied numbers that rotted. Docs point at the ceiling key or script. They never restate the number. |

### 2.3 Patterns deliberately NOT applied

- **No new ports.** Each fix reuses an existing one: `ApiKeyPort`, `CanonicalizerPort`,
  `MemoryPort`, `FileStoragePort`, `StateRepositoryPort` (via session facts) and `LLMPort`.
  The Sep plan's port-deletion stance (§2.2) holds.
- **No outbox table or message queue for idempotency.** Session facts are already durable
  with the session. A separate store adds a second consistency problem.
- **No state-machine library or transition DSL.** A `Mapping[StateId, type]` and a frozen
  `Transition` are enough.
- **The injection scanner is a signal, never the control (D2).** Fence, taint and egress
  approval remain the control. The existing scanner (1.1b) only adds evidence: it escalates
  trust and records detections. It never removes, rewrites or blocks content, because a
  regex scanner is trivially bypassed and its noisy patterns would destroy real pages.
- **No async rewrite.** Blocking calls get `asyncio.to_thread` or the existing async
  `FileStoragePort`. Nothing more.
- **No tracing-framework swap.** OTel sink, Prometheus and the structured logger exist.
  OBS-1 is propagation, not tooling.

---

## 3. Phase 0 — Instruments (before any fix)

Every later phase is verified by these. Land them first, at today's counts, so each fix is
a visible ceiling drop.

### 0.1 Module-cycle ratchet

- **Add** `scripts/lint_module_cycles.py`. It does an AST import walk over `weebot/`:
  TYPE_CHECKING excluded, function-level imports included, plus the string targets that 0.2
  counts. It runs Tarjan SCC and reports each SCC with its members. The ceiling check goes
  through `scripts/quality_ceilings.py` like the other ratchets.
- **Ceiling:** `module_cycles = 3` in `tasks/quality/ceilings.toml`.
- **Wire:** a `make lint-module-cycles` target, a `check` prerequisite, and a step in
  `.github/workflows/architecture.yml` `lint-and-arch`.
- **Exit:** CI fails at 4. Phases 3.6, 3.7 and 3.8 take it to 0.
- **Effort:** S. **Risk:** low. It reads the tree and changes nothing.

### 0.2 Dynamic-import ratchet (LAY-4)

- **Problem.** 18 `importlib.import_module("weebot.…")` calls hide edges from import-linter
  and from `import_exemptions`. Three carry comments saying so:
  - `interfaces/factories.py:28`;
  - `interfaces/web/routers/health.py:409`;
  - `interfaces/web/routers/models.py:10`.

  Each such call is an exemption nobody reviewed.
- **Design.** Extend `scripts/lint_import_exemptions.py`, the same concern, so no new script:
  - count literal `import_module("weebot.…")` and `__import__("weebot.…")` targets;
  - ratchet `dynamic_weebot_imports = 18`;
  - classify each target with the same layer contracts, and fail if a dynamic import
    crosses a forbidden boundary without a matching `.importlinter` exemption.
- **Fix rule.** Every site either becomes a static import plus a reviewed exemption (visible),
  or stays dynamic because the target is an optional dependency, with that reason in an
  allowlist inside the script.
- **Exit:** `dynamic_weebot_imports` falls to the optional-dependency count. No comment in
  the tree says "avoid import-linter".
- **Effort:** S–M. **Risk:** `import_exemptions` rises briefly as hidden edges become visible.
  That is the point. The `--verify-not-raised` guard needs a one-commit, reviewed raise.
  Document it in the commit body.

### 0.3 CI parity (CI-1)

- Add `make lint-no-print` and `make lint-map` steps to `lint-and-arch`. They run in
  `make check` (`Makefile:130`) but not in CI.
- **Coverage.** Measure `pytest tests/unit --cov=weebot` on `main`. Set `--cov-fail-under`
  (`architecture.yml:171`) to the measured floor, rounded down. Move the floor into
  `ceilings.toml` as `unit_coverage_floor` with the inverse rule (it may only go up).
  `quality_ceilings.py` needs a direction flag.
- **Lint.** Measure `ruff check weebot cli --statistics` at the repo's configured rules
  (`ruff check .` per `CLAUDE.md`). Ratchet `ruff_violations` at the measured count. The CI
  selector stays `F821,E9` for the blocking step, and the ratchet catches growth.
- **Exit:** every gate in `make check` is also in CI. **Effort:** S.

### 0.4 Long-function ratchet (feeds Phase 5)

- **Add** `functions_over_150_lines` (AST, `weebot/`) to `ceilings.toml`, measured.
  Exact-equality line counts per file would fail on every edit. A count of long functions
  moves only when a god method is split or a new one is written.
- **Exit:** ratchet in CI. **Effort:** S.

---

## 4. Phase 1 — Security boundary

### 1.1 Default-deny trust classification (SEC-1, closes DOC-5)

**Current shape.**

- `core/trust_boundary.py` holds `UNTRUSTED_OUTPUT_TOOLS` and `FENCE_ONLY_TOOLS`, plus prefix
  rules for `mcp__` and `apify_`.
- `_base.py:1042` fences only when `not result.is_error and is_untrusted_tool(name)`.
- `_tool_executor.py:441` taints only for non-error results from listed names.
- `tests/unit/core/test_trust_boundary_registry.py` keeps a *second* hand list
  (`EXTERNAL_CONTENT_TOOLS`) and a grandfather list of 13 stale names.

So a new tool is trusted until someone remembers two lists.

**Design (Q1).**

1. **Domain value.** Add `domain/models/output_trust.py`:
   ```python
   class OutputTrust(StrEnum):
       EXTERNAL = "external"        # fence + taint (default)
       FIXED_SCHEMA = "fixed"       # fence only (today's FENCE_ONLY_TOOLS: weather)
       LOCAL = "local"              # neither
   ```
2. **Attribute on the type.** In `domain/models/base_tool.py` add
   `output_trust: ClassVar[OutputTrust] = OutputTrust.EXTERNAL`. MCP bridge tools and Apify
   presets inherit the default, so the prefix rules become redundant and are deleted.
3. **Pure decision functions** in `core/trust_boundary.py`. They replace `is_untrusted_tool`
   and `taints_egress_context`:
   ```python
   def trust_of(tool: BaseTool | None) -> OutputTrust:   # unknown or unregistered -> EXTERNAL
   def must_fence(trust: OutputTrust) -> bool             # EXTERNAL, FIXED_SCHEMA
   def must_taint(trust: OutputTrust, is_error: bool) -> bool  # EXTERNAL and not is_error (D1: errors never taint)
   ```
   `wrap_untrusted` stays as it is: delimiter escaping plus the fence.
4. **Call sites pass the tool object.** The executor already resolves it (`tool_obj`,
   `_tool_executor.py:312`). `_base.py:1042` fences on `must_fence(trust_of(tool))`,
   **including error results**. Fencing is free, and an error body can carry remote text
   (HTTP error pages, MCP server messages). The taint keeps today's decision that errors do
   not taint (comment at `_tool_executor.py:420`, confirmed by D1). It moves into
   `must_taint`, where a test pins it.
5. **Keep the special cases.** The per-session exceptions `_LOCAL_TAB` and `_WRITTEN_FILES`
   (`_tool_executor.py:429-437`) stay, as named arguments to `must_taint`. They are real
   refinements, not list drift.
6. **Migration.** Each of the 48 concrete tools under `weebot/tools` gets an explicit
   `output_trust`. The PR description lists every `LOCAL` and `FIXED_SCHEMA` assignment for
   review. That list is the security review.
7. **Delete** `UNTRUSTED_OUTPUT_TOOLS`, `FENCE_ONLY_TOOLS`, the `apify_` and `mcp__` branches,
   and `KNOWN_UNMATCHED_NAMES`. `egress_guard._BROWSER_EGRESS_TOOLS` is a different concern
   (what *sends*, not what *reads*) and stays.
8. **DOC-5.** The module docstring's claim becomes true in 1.1b. Rewrite the docstring then,
   to describe fence, taint, scan and egress approval in that order. It must say the scan is
   a signal, not the control.

**Tests.**

- Rewrite `test_trust_boundary_registry.py`. An AST pass asserts that every concrete
  `BaseTool` subclass under `weebot/tools` assigns `output_trust` explicitly. The parser
  already exists at lines 28-54. The hand list `EXTERNAL_CONTENT_TOOLS` is deleted.
- Table tests for `trust_of`, `must_fence` and `must_taint`:
  - unregistered name → fence and taint;
  - error from an EXTERNAL tool → fenced and not tainted;
  - `FIXED_SCHEMA` → fenced and not tainted;
  - `LOCAL` → neither;
  - an MCP bridge instance → EXTERNAL.
- Executor test: a fake EXTERNAL tool that returns an error produces a conversation-buffer
  entry containing the fence.

**Exit.**

- No list of tool names decides trust anywhere in `weebot/`.
- A new tool with no declaration is fenced and tainted.
- `silent_except_handlers` is unchanged.

**Effort:** M. **Blast radius:** SYSTEM.

**Risk.** A tool wrongly left EXTERNAL taints sessions and adds approval prompts. Mitigation:
the reviewed `LOCAL` list. Remember that over-prompting trains users to disable the guard
(`trust_boundary.py:119-131`).

### 1.1b Injection scan on fenced output (D2: yes; closes DOC-5)

**Current shape.** The scanner already exists and has no callers:

- `scan_for_injection` in `infrastructure/security/trust_boundary_scanner.py:27` runs
  `AgentMemorySanitizer.detect_contamination` (`agent_sanitizer.py:238`).
- It fails closed: it returns `SCANNER_UNAVAILABLE` (`trust_boundary_scanner.py:18`) when it
  cannot run.
- `detect_contamination` checks two pattern families: injection (`agent_sanitizer.py`
  `_INJECTION_PATTERNS`) and dangerous behavior (`_DANGEROUS_BEHAVIOR_PATTERNS`). It returns
  the highest-severity hit.

So this item wires an existing, tested component. It builds no scanner.

**Design.**

1. **Injection, not import.** The executor is in application and the scanner is in
   infrastructure. `ExecutorAgent` receives `scan: Callable[[str], dict | None]` by
   constructor, and `application/di` binds it to `scan_for_injection`. That is the same
   constructor-injection shape as `llm_pool`. There is no new port and no new exemption.
2. **Where it runs.** In `_base.py`, on the same path as the fence, for every result where
   `must_fence(trust)` is true, errors included. It runs on the content *after* the tool's
   truncation strategy, so the scan cost is bounded by the output cap.
3. **What a detection does.** A pure function in `core/trust_boundary.py` decides:
   ```python
   def escalate(trust: OutputTrust, detection: dict | None) -> OutputTrust
   ```
   - No detection: trust unchanged.
   - Any detection on `FIXED_SCHEMA`: escalate to `EXTERNAL`, so the session taints.
     A fixed-schema source that suddenly carries instruction text is no longer
     fixed-schema.
   - `SCANNER_UNAVAILABLE`: treat as a detection. It is fail-closed by design.
   - It never returns `LOCAL`, and the content is never edited.
4. **Visible to the model.** The fence header names the hit, for example
   `⟦UNTRUSTED_DATA source=web_search suspected=Instruction Override⟧`. That gives the
   model a reason to distrust the block that it can see.
5. **Recorded.** Emit an `InjectionSuspected` domain event with session, step, tool, pattern
   name and severity, and log it at WARNING. It is never the matched text in full: the
   sanitizer already caps `match` at 100 characters, and that cap stays.
6. **Measure precision before tuning.** Some patterns are broad. `(?:system|admin|root)\s*:\s*`
   and `\$\{.*\}` match ordinary pages and shell docs. Before enabling the escalation step,
   replay the scanner over stored tool outputs in the event store (`~/.weebot/events.db`,
   tool-result events) and record the hit rate per pattern in this file. A pattern whose hit
   rate on ordinary content makes escalation meaningless (for example, it fires on most
   pages) is demoted to log-only in the wiring, not deleted from the sanitizer, which other
   code may use.

**Tests.**

- A fixed-schema tool whose output contains "ignore previous instructions" taints the
  session.
- An EXTERNAL tool with a detection: fenced, header names the pattern, event emitted, content
  byte-identical inside the fence.
- The scanner raises: treated as a detection (fail closed).
- Clean content: no event, header unchanged.
- The executor is built with a fake `scan`, so no infrastructure import is needed in tests.

**Exit:** every fenced output is scanned. The docstring at `trust_boundary.py:9` is true.
**Effort:** S–M. **Sequence:** right after 1.1, same files.

**Risk.** False positives escalate `FIXED_SCHEMA` tools (today only `weather`) to tainting
sessions. That is bounded to one tool, and step 6 measures it before enabling.

### 1.2 Authentication through the port (SEC-2)

**Current shape.** `interfaces/web/auth.py:124-135` and `:223-234` are the same block twice.
Each one:

- imports `SQLiteApiKeyStore` plus the private helpers `_lookup_hash` and `_verify_key`;
- constructs a store per call;
- verifies.

`.importlinter` labels it "KNOWN SMELL" and defers it to "a dedicated, reviewed change with
security tests". This is that change.

**Design.**

1. **Pure crypto module.** Move `_lookup_hash`, `_hash_key`, `_verify_key` and
   `generate_raw_key` from `infrastructure/security/sqlite_api_key_store.py:41-70,206` to
   `weebot/core/api_key_crypto.py`. The module is stdlib only, with no I/O. It is public
   (no underscore), because two layers use it. `SQLiteApiKeyStore` imports from it.
2. **One resolver.** `auth.py` gets a single
   `async def _principal_from_key(api_key: str, keys: ApiKeyPort) -> Principal | None`.
   Both call sites use it.
3. **Injected port.** The port comes from the container on `request.app.state`, already
   built in `web/main.py`'s lifespan. No per-request `SQLiteApiKeyStore()`, which today also
   opens an aiosqlite connection per auth.
4. **Delete** the `weebot.interfaces.web.auth -> …sqlite_api_key_store` exemption.
   `import_exemptions` goes down by 1.

**Tests. Land these first, in their own commit, before moving any code.**

- Golden vectors: a fixed raw key with a known salt maps to the known lookup hash and the
  known `key_hash`. Stored keys must keep verifying after the move.
- `_verify_key` uses `hmac.compare_digest`. Assert it, or add it if it is absent.
- The resolver works against a fake `ApiKeyPort`, so no SQLite is needed.
- Existing: `tests/unit/interfaces/web/test_webhook_router_security.py` and
  `tests/integration/test_security_penetration.py` stay green.

**Exit:** `auth.py` imports nothing from `weebot.infrastructure`. **Effort:** S–M.
**Risk:** auth regression. The golden-vector commit is mandatory.

### 1.3 Owned background tasks (CON-1)

**Sites.** Each discards the task:

- `interfaces/web/routers/slack_webhook.py:67`
- `interfaces/web/routers/whatsapp_webhook.py:77`
- `application/agents/executor/_base.py:1177`
- `application/flows/flow_router.py:223`
- `core/activity_stream.py:78`
- `infrastructure/notifications/telegram_adapter.py:146`
- `infrastructure/notifications/_base.py:83`
- `tools/bash_tool.py:363`

`_cascade.py:519` returns its future to an awaiting caller and is excluded.

**Design (Q4).**

- Every site calls `get_background_tasks().spawn(coro, name=…)`
  (`application/services/background_tasks.py:100`).
- The FastAPI lifespan shutdown calls `drain()` before the connection pools close. That is
  the same ordering `cli/commands/flow.py::_run_async` already follows.
- `core/activity_stream.py` cannot import application (contract `core-no-app`). It receives
  a `spawn` callable by constructor injection, defaulting to the stdlib with a strong-ref
  set. That is the same shape as `tool_approval.py:45`.

**Gate.** Extend `scripts/lint_unawaited_coroutines.py` (same AST walk, same concern) to flag
`create_task` / `ensure_future` / `loop.create_task` whose result is discarded (a bare
expression statement). Blocking at zero, like the un-awaited check.

**Tests.** A spawned failing task logs through `logger`, not "Task exception was never
retrieved". A webhook handler task survives `gc.collect()` and completes. The lifespan
drains on shutdown.

**Exit:** the gate is at 0. **Effort:** S.

### 1.4 Valkey default credential: accepted, guard pinned (OPS-1, D5: no)

D5 keeps `${VALKEY_PASSWORD:-weebot_default}` (`docker-compose.yml:23,30,78`), so
`docker compose up` keeps working without a `.env`. The risk is acceptable only while the
thing that contains it holds: Valkey publishes no port (`ports: []`, `docker-compose.yml:20`)
and is reachable only on the compose network. So pin that, instead of changing the default.

- **Pin test.** Add a test in `tests/unit/` that parses `docker-compose.yml` and asserts
  `services.weebot-valkey.ports` is empty or absent. Its failure message must name OPS-1 and
  this section, so whoever publishes the port also sees they are publishing a default
  password.
- **Document it.** Add `VALKEY_PASSWORD=` to `.env.example` with one line: the default is for
  local compose only; set a value before exposing Valkey anywhere.
- **Effort:** S. **Risk:** none at runtime.

---

## 5. Phase 2 — Resilience

### 2.1 One LLM bulkhead for every caller (ORCH-1)

**Current shape.**

- `LLMPool` is registered at `di/__init__.py:321-330` and passed only into
  `ExecutorAgent → CascadeExecutor` (`di/__init__.py:459`, `_cascade.py:93,302,676`).
- Planner (3 calls), optimizer (7), chain-of-verification (3), critics, consolidators and
  ~20 more services call `LLMPort.chat/complete` directly: 68 call sites, all unbounded by
  the pool.
- Feature-level semaphores (`dispatch_agents.py:112`, `mixture_of_agents.py:121`,
  `sub_agent_factory.py:145`, `harness/runner.py:133`, `workflow_orchestrator.py:142,148`)
  bound fan-out width, not total load.

**Design (Q2).**

1. **Decorator.** Add `BoundedLLMAdapter(LLMPort)` to `application/strategies/llm_pool.py`,
   next to the pool. It wraps an `LLMPort` and acquires the pool around `chat`/`complete`.
   It raises `LLMCapacityExhaustedError` on acquire timeout, keeping today's saturation
   semantics (`llm_pool.py:18-22`).
2. **Admission token.** `_ADMITTED: ContextVar[bool]` in the same module. `CascadeExecutor`
   keeps acquiring the pool *outside* its `wait_for`, then sets `_ADMITTED`. The decorator
   passes through when the token is set. Result:
   - queue time stays outside model timeouts;
   - there is no double acquisition;
   - there is no nested-acquire deadlock at pool size 1.
3. **Composition.** Wrapping happens only in `application/di`: every factory that hands out
   an `LLMPort` wraps it once. Add a fitness test that resolves every container key whose
   value is an `LLMPort` and asserts `isinstance(…, BoundedLLMAdapter)`. Builders outside DI
   are grandfathered in `test_llm_clients_are_built_by_the_factory` (for example
   `osworld/agent_adapter.py`). Count them and leave them; they are benchmark harnesses.
4. **Keep feature semaphores.** They are bulkheads *inside* the global bulkhead: fan-out
   width versus total in-flight calls. Document this at `llm_pool.py` so the next audit does
   not log it as drift.

**Tests.**

- With pool size `k` and a fake adapter counting in-flight calls, `3k` concurrent callers
  mixed across a planner-style direct path and the cascade path never exceed `k`.
- At pool size 1, a cascade call (admitted) whose adapter is also bounded completes, with no
  deadlock.
- Saturation raises `LLMCapacityExhaustedError`, not `TimeoutError`.
- Add the concurrency test to `tests/stress/`, which CI already runs (`architecture.yml:227`).

**Exit:** no `LLMPort` leaves the container unbounded. **Effort:** M. **Blast radius:** SYSTEM.
**Risk:** a pool sized for cascade-only traffic is now shared by more callers. Re-measure
`llm_pool_max_concurrent` under the Phase 8 load test before changing its default. Do not
tighten it on a guess (`llm_pool.py:41-46`).

### 2.2 Effect ledger: retried flows do not re-send (ORCH-2)

**Current shape.**

- `TaskRunner._run_flow` retries a failed session by starting the flow again on the reloaded
  session (`task_runner.py:270-286`).
- States retry steps (`reviewing.py:28`, `executing.py:71`).
- Side-effecting tools have no replay protection. A grep for `idempot` returns 0 hits in
  `weebot/`.

**Design (Q3).**

1. **Scope.** Only calls that `EgressGuard.classify` marks `is_egress`, plus tools matching
   `WEEBOT_OUTBOUND_TOOL_PATTERNS`. One classifier, the existing one. Reads are not ledgered.
2. **Key, as a pure function** in `core/effect_key.py`:
   `effect_key(session_id, step_id, canonical: CanonicalizationResult) -> str`, a sha256 over
   a stable serialization. The canonical form comes from `CanonicalizerPort` (already
   injected for approval grants, `interfaces/factories.py:446`).
3. **Store.** Use the session fact `effect:<key>`, holding
   `{"at": iso, "summary": str, "ok": bool}`. It is persisted with the session per event
   (`task_runner.py:258`). No new port or table.
4. **Pre-hook in `ToolExecutor.execute_tool`.** If the key exists with `ok=True`, return a
   `ToolResult` built from the summary, marked `replayed=True`, and emit an
   `EffectReplayed` event. Otherwise execute, record on success, and emit
   `EffectRecorded`, so the runner persists the session before the next step.
5. **Guarantee, stated honestly.** This narrows at-least-once to one in-flight call. A crash
   between the provider accepting the send and the session save can still duplicate.
   Exactly-once needs provider idempotency keys. Pass `effect_key` through as an
   idempotency header where an adapter's API supports one, as a follow-up per adapter. It is
   not part of this item.
6. **Interaction with approvals.** A replayed call never reaches the approval gate, because
   the action is not repeated. This is correct, and gets a test.

**Tests.**

- A fake mail tool with a call counter. The flow fails after the send, then the session
  retry runs: the counter is 1, and an `EffectReplayed` event exists.
- Same tool with different arguments: executes.
- Non-egress tool: never ledgered.
- The key is stable across processes: golden value.

**Exit:** no egress call executes twice for the same session, step and canonical action.
**Effort:** M. **Risk:** a stale ledger entry suppresses an intended re-send after the user
edits the plan. The key includes `step_id`, and a re-planned step gets a new id. Verify this
assumption in `domain/models/plan.py` before building.

### 2.3 Retry budget: measure, then bound (ORCH-3)

- **Measure first.** Add a stress case to `tests/stress/test_llm_resilience.py`: every model
  returns 503. Record the total adapter attempts per cascade call and the wall time.
  - Inner: `RetryWithBackoff` delays `[1,2,4,8,15,30]` (`resilient_adapter.py:144`).
  - Outer: cascade `wait_for` 15s/90s (`_cascade.py:336-349`).
  - SDK retries already 0 (`adapter_factory.py:174`).
- **Only if** attempts exceed `models × 3` or the wall time exceeds the cascade budget:
  propagate a deadline through a ContextVar set by the cascade. `RetryWithBackoff` then stops
  scheduling a retry whose delay ends past the deadline. This is deadline propagation, not a
  new retry layer.
- **Exit:** the measured numbers are recorded in the test as assertions. **Effort:** S
  (measure), plus S (deadline, if needed).

### 2.4 Session cost budget (ORCH-4, D6)

**Resolved 2026-10-24: no per-session USD bound exists on `PlanActFlow`.**

- `config/constants.py` holds token-budget history limits only (`:56,67`).
- The only USD budget is the sub-agent one (`di/__init__.py:65`,
  `SubAgentCostTracker(budget_usd=0.50)`).
- Cost data does exist. Wave C of `tasks/remaining_fix_plan.md` (W4.1, W4.2) added the
  `LLMCallCompleted` event with an `estimate_cost` USD figure. `DurableEventBus` stores it in
  the `events` table (`cost`, `model`, `tokens_used`). `EventStore.get_cost_window`
  (`infrastructure/event_store.py:253`) sums it by time window.
- Gap: only the executor cascade emits that event. Wave C itself records that planner,
  verifier and intent-review calls emit nothing.

**Measured baseline** (read-only query of the local `~/.weebot/events.db`, 2026-10-24).
409 sessions with `llm_call_completed` rows, all from 2026-10-23, cascade calls only:

| Statistic | USD per session | LLM calls per session |
|---|---|---|
| p50 | 0.017 | 6 |
| p90 | 0.093 | — |
| p95 | 0.159 | 49 |
| p99 | 0.477 | — |
| max | 2.399 | 102 |

One day of data, cascade-only, priced by `estimate_cost`, not by the provider's bill. So the
true per-session cost is higher than this table, by an unknown factor.

**Decision D6: a two-threshold budget that asks before it kills.**

A single hard number either never fires or kills real work, because the distribution is
long-tailed (p99 is 28× the median). So use two thresholds, both enforced through
mechanisms the repo already has.

1. **Soft limit — degrade, keep going.** Default **$0.50** (about the measured p99). When a
   session crosses it:
   - the cascade stops trying PREMIUM-tier models for the rest of the session and runs
     FREE and BUDGET only (`CascadeTier`, `_cascade.py:437-441`);
   - emit a `SessionBudgetSoftLimit` event and log at WARNING.

   This costs no user interaction, and only about 1 session in 100 sees it.
2. **Hard limit — ask, then stop.** Default **$2.50** (above the measured maximum, about
   5× p99). When a session crosses it, the flow raises an "ask" through the existing ADR-013
   approval channel:
   - a console prompt in CLI `flow` on a TTY;
   - a flow pause in the web UI and gateways;
   - refusal in cron, webhooks and MCP, where nobody can answer.

   An approval grants one more hard-limit increment for that session (a single-use grant,
   like every ADR-013 grant). A refusal or expiry ends the flow with a typed termination
   reason, `BUDGET_EXCEEDED`, and a persisted, resumable session.
3. **Where it lives.**
   - **The check** is a termination condition in `application/termination/conditions.py`,
     the existing Strategy seam. It is not an `if` in `plan_act_flow.py:702`.
   - **The running total** is per session, held by the flow and updated from each
     `LLMCallCompleted` event. No DB query per iteration.
   - **On resume,** seed the total from the event store. Add one method,
     `get_session_cost(session_id)`, to the existing `EventStorePort`; that is a method on
     an existing port, not a new port.
   - **Sub-agents** roll up: each sub-agent's spend is added to its parent session's total.
     The sub-agent's own $0.50 cap stays as its local limit.
4. **Configuration.** Add `WEEBOT_SESSION_COST_SOFT_USD=0.50` and
   `WEEBOT_SESSION_COST_HARD_USD=2.50` to `WeebotSettings` and `.env.example`. A per-flow
   override goes in `PlanActFlowConfig`, so the harness and benchmark flows can set their
   own. Setting either value to `0` disables that threshold.
5. **Prerequisite: complete metering first.** Enforcing a cap on cascade-only metering would
   under-count every session. So 2.4 lands **after** 2.1 and Phase 6, where the
   `BoundedLLMAdapter` becomes the one choke point and emits `LLMCallCompleted` for every
   call, planner and verifier included.
6. **Re-derive the defaults from data, then pin the rule.** Two weeks after complete metering
   lands, re-run the per-session query. Set:
   - soft = measured p99;
   - hard = max(5 × p99, measured max).

   Record the new numbers in this section. The rule is the decision; $0.50 and $2.50 are its
   current output.

**Tests.**

- A fake cost source crosses the soft limit: the next cascade call skips PREMIUM models, and
  the event is emitted.
- Crossing the hard limit in a non-interactive context ends the flow with
  `BUDGET_EXCEEDED`, and the session is persisted and resumable.
- Crossing it with an approval continues for exactly one increment.
- Resume seeds the total from the event store.
- Sub-agent spend counts toward the parent total.

**Effort:** M. **Sequence:** after 2.1 and Phase 6.

**Risk.** Defaults set from one day of cascade-only data. Step 6 corrects them, and the hard
limit asks rather than kills, so a wrong default costs one prompt, not lost work.

---

## 6. Phase 3 — Boundaries and cycles

Each item lowers `import_exemptions` by exactly the lines it removes, in the same commit.

### 3.1 Infrastructure imports the domain, not the tools package (LAY-1a)

- `tools/base.py` is a re-export of `domain/models/base_tool.py` and
  `domain/models/tool_result.py` (`tools/base.py:11,15`).
- Change `infrastructure/adapters/tool_discovery.py`,
  `infrastructure/external_service_integration.py`, `infrastructure/mcp/mcp_tool_bridge.py`
  and `infrastructure/mcp/mcp_toolkit_adapter.py` to import from `weebot.domain.models`.
- Delete those `infra-no-app-services` exemptions.
- **Effort:** S. **Risk:** none at runtime; it is the same class object.

### 3.2 `RoleBasedToolRegistry` moves to application (LAY-1b, Q5)

- **Move** `tools/tool_registry.py` (521 lines) to `application/services/tool_registry.py`.
  It imports only `tools.base` (domain re-exports) and `application.services.tool_guards`.
- **Lazy Playwright factory.** The one lazy Playwright creation (exemption
  `weebot.tools.tool_registry -> weebot.infrastructure.browser.playwright_adapter`) becomes a
  `browser_factory: Callable[[], BrowserPort]` injected from `application/di`.
- **Shim.** `weebot/tools/tool_registry.py` keeps a one-line re-export for one release, so
  external scripts and skills do not break. Remove it once `effects/inbound.md` in the map
  shows no outside callers.
- **Callers.** `mcp_tool_registry_bridge.py:25`, `native_tool_retrieval_service.py:14`,
  `flows/collaborators/tool_assembler.py:12`, `flows/mcp_scope_config.py:14`,
  `di/__init__.py:484,621` and `di/_factories.py:431` all import the new path.
- **`infrastructure/adapters/tool_discovery.py`.** It must not import application services
  (contract `infra-no-app-services`). It receives the registry by constructor, typed by a
  `Protocol` in `application/abstractions/`. That is the Separated Interface seam the Sep plan
  P3 already uses. If `ToolRepositoryPort` already fits, use it instead (check first).
- **Removes:** 7 `application→tools` edges, `tools→application.services.tool_guards`, and the
  Playwright and `tool_discovery→tool_registry` exemptions.
- **Effort:** M. **Risk:** import-path churn. The shim covers it.

### 3.3 Swarm tool receives its agents (LAY-1c)

- `tools/swarm.py:89,135` imports `GoalAgent` and `SynthesizerAgent` from
  `application.agents`.
- Inject `decompose: Callable[[str, int], Awaitable[SwarmSpec]]` and
  `synthesize: Callable[…]` via the DI factory that builds the tool.
- **Effort:** S.

### 3.4 Executor memory through `MemoryPort` (LAY-1d)

- `application/agents/executor/_base.py` imports `tools.persistent_memory`.
- Route through `application/ports/memory_port.py`, injected like the executor's other
  collaborators.
- **Effort:** S–M. Check the call shape first; if the port lacks the method, this item
  becomes a port *method* addition, not a new port.

### 3.5 Retire `core/agent.py` (LAY-1e, closes `ARCHITECTURE.md` debt item D2)

- `RecursiveWeebotAgent` (162 lines) is the only `core→tools` and `core→application.di`
  source (`core/agent.py:35,42,52,53`), and the only LangChain import in `core`.
- Its callers: `run.py` (legacy `--interactive` REPL) and
  `tests/unit/test_recursive_agent_browser_async.py`.
- **Decided (D3: yes):** switch `run.py --interactive` to `ChatFlow` through
  `interfaces/factories.py`. Delete `core/agent.py` and its test. Remove the four
  `core-no-app` exemptions for `weebot.core.agent`.
- `core.safety -> application.ports.llm_port` stays. It is the ADR-009 documented exception
  ("port interfaces in core are allowed").
- **Effort:** S–M. **Risk:** the legacy REPL changes behavior. That REPL is listed as legacy
  in `CLAUDE.md`.

### 3.6 States return transitions (LAY-2a, Q6) — do before Sep §5.4

- **Problem.** The 8-module SCC comes from states lazily importing their successors:
  - `critiquing → planning, plan_review, premortem`;
  - `executing → evidence_gate, planning, reviewing, updating, verifying`;
  - `updating → critiquing, executing`;
  - and so on. The full edge list is in the audit.
- **Design.**
  - `flows/states/base.py` gains `class StateId(StrEnum)` and
    `@dataclass(frozen=True) class Transition: target: StateId; kwargs: Mapping[str, Any]`.
  - `flows/states/__init__.py` holds `STATES: Mapping[StateId, type[FlowState]]`, built once.
  - A state that today constructs `PlanningState(...)` returns or sets
    `Transition(StateId.PLANNING, {...})`.
  - `PlanActFlow` instantiates through `STATES`. So does `FlowRouter`, which already resolves
    the initial state.
- **Why now.** The Sep plan §5.4 narrows the state-facing context ("highest blast radius,
  do it last"). Doing the transition table first shrinks that change: states then depend on
  `base` plus the narrow context only.
- **Tests.** A table test: for each `StateId`, the registry builds the class. Existing flow
  tests stay green. `module_cycles` drops by 1.
- **Effort:** M. **Risk:** kwargs drift between a transition and its constructor. Mitigation:
  a test constructs every state from a representative `Transition`, and once Sep 2.2 restores
  config types, `kwargs` can become per-state `TypedDict`s.

### 3.7 Composition root does not import interfaces (LAY-2b, Q7)

- `di/__init__.py:255` imports `interfaces.factories.create_flow`, and `:411` imports
  `interfaces.cli.agent_runner.AgentRunner`.
- **`create_flow`** (`interfaces/factories.py:204-322`) builds application objects only.
  Move it to `application/di/_factories.py`. `interfaces/factories.py` re-exports it for its
  callers.
- **`AgentRunner`.** The CLI entry point registers it into the container at startup
  (`container.register(...)` in `cli/main.py`). The container never imports it.
- **Delete** the `weebot.application.di -> weebot.interfaces.**` exemption. `module_cycles`
  drops by 1.
- **Sequence after 2.1.** Both edit `di/__init__.py`. **Effort:** M.

### 3.8 Templates package cycle (LAY-2c)

- `templates/__init__.py` re-exports submodules. `templates/agent_integration.py` and
  `templates/integration.py` import the package back.
- Change them to import submodules directly. `module_cycles` drops by 1.
- **Effort:** S.

### 3.9 Config is a leaf (LAY-3, Q8)

- **`config/capability_profiles.py:20`** imports `TaskCategory` from
  `application.services.task_model_router`. Move the enum to
  `weebot/domain/models/task_category.py`. `task_model_router` re-exports it.
- **`config/fs_permissions.py:33,137`** `load_fs_permission_checker()` builds an application
  service. Move the builder to `application/di` and keep only data loading in `config`.
- **New `.importlinter` contract `config-is-leaf`:** `weebot.config` must not import
  `weebot.application`, `weebot.interfaces`, `weebot.infrastructure` or `weebot.tools`.
  Raise no exemptions for it. Add the package to the
  `test_every_top_level_package_is_under_a_contract` coverage.
- **Effort:** S.

---

## 7. Phase 4 — Async hygiene (CON-2)

`python scripts/lint_async_io.py` lists 29 sites and reports "29, at its ceiling".

1. **Fix the linter first.** These four are awaited calls on async methods named
   `read_text`/`write_text`, so they are false positives:
   - `infrastructure/adapters/file_storage_adapter.py:49,57,60`;
   - `application/services/step_evidence_auditor.py:231`.

   Skip `Call` nodes whose parent is `Await`. The ceiling goes from 29 to 25 in the same
   commit.
2. **Web-process sites first.** These block the single event loop that serves every session:
   - `scheduling/scheduler.py:524,575,625,643` (the scheduler runs in the FastAPI lifespan);
   - `interfaces/gateways/telegram.py:330`;
   - `infrastructure/browser/som_renderer.py:248` (PIL is CPU-bound, use `to_thread`);
   - `infrastructure/adapters/speech/openrouter_speech_adapter.py:41` and
     `whisper_adapter.py:69`;
   - `infrastructure/sandbox/osworld.py:277`;
   - `infrastructure/adapters/agentskills_index.py:125` and `skill_index_github.py:169`
     (tarfile, use `to_thread`);
   - `infrastructure/persistence/skill_store.py:107`;
   - `qmd_integration/mcp_client.py:178,258` (`subprocess.Popen` becomes
     `asyncio.create_subprocess_exec`).
3. **Application services write through the existing async `FileStoragePort`**
   (`LocalFileStorageAdapter`, `file_storage_adapter.py:18`) instead of sprinkling
   `to_thread`:
   - `harness_generation_flow.py:119,126,132,464,488`;
   - `harness_optimization_target.py:243`;
   - `skill_materializer.py:79`;
   - `trajectory_exporter.py:71`.
4. **CLI sites** (`cli/commands/harness.py:104`, `skills.py:156`, `soul.py:93`) are harmless
   in a one-shot `asyncio.run`, but each is a one-line `to_thread`. Fix them so the gate can
   become blocking at zero.

**Exit:** `blocking_io_in_async = 0`, and the gate switches to blocking at zero like
`lint-unawaited`. **Effort:** M overall, but each site is S. Batch by directory.

---

## 8. Phase 5 — Coupling hotspots (CPL-1, CPL-2)

Owned by the Sep plan. This phase adds only measurements and ordering.

- **God methods (Sep §4.3).** Re-measure `ExecutorAgent.execute_step` and `PlanActFlow.run`.
  The Sep plan measured them at 521 and ~270 lines. `_base.py` has grown from the 803 lines
  ADR-007 recorded to 1180.
  - Extract the tool-result handling block (`_base.py` around 1030-1060: terminate,
    fence, buffer append, vision-in-the-loop) into `executor/_step_result_handler.py`.
    That follows the ADR-007 seams; 1.1 already touches this block, so do it right after.
  - The `functions_over_150_lines` ratchet (0.4) records each drop.
- **Typed keys (Sep P2).** Introduce `Key[T]` and typed `register`/`get` overloads in
  `application/di`. Start with the keys this plan touches:
  - `llm_pool`;
  - the LLM adapter keys (2.1);
  - `flow_factory` (3.7);
  - the tool-registry key (3.2).

  `scripts/lint_di_wiring.py` resolves both key kinds. Add a ratchet `string_di_keys` at the
  measured count, going down per migrated key.
- **Narrow `FlowContext` (Sep §5.4)** stays last, after 3.6.

---

## 9. Phase 6 — Observability (OBS-1)

1. **Context propagation.**
   - Bind `session_id`, `step_id` and `correlation_id` in ContextVars at
     `TaskRunner._run_flow` (`task_runner.py:240`) and at `PlanActFlow.run` entry.
   - Re-bind `step_id` in the executor per step.
   - `core/structured_logger.py` already reads a correlation id. Make it read all three, so
     every log record from tools, the cascade and adapters carries them with no call-site
     change.
2. **One record per LLM call.** The `BoundedLLMAdapter` from 2.1 is the single choke point:
   it emits model, input and output tokens, latency, outcome and `prompt_sha` per call, as a
   structured log plus a Prometheus histogram. First check `core/model_cascade_tracker.py` for
   an existing per-call record; reuse it if it exists.
3. **Prompt versioning without a registry.** `prompt_sha = sha256(system_prompt)[:12]`,
   computed where system prompts are assembled: `executor/_prompt_builder.py`, the planner
   and `services/harness_prompt_assembler.py`. Pass it on the call (a kwarg the decorator
   reads) and record it.

**Tests.** A log record emitted inside a tool during a flow run carries `session_id`,
`step_id` and `correlation_id`. A fake LLM call produces one record with all fields.

**Effort:** M. **Sequence after 2.1.**

---

## 10. Phase 7 — Docs tell the truth (DOC-1 to DOC-5, UNK-1)

Strike the false claims at the start of the work, so nobody plans against them. Rewrite the
sections at the end, so they describe the finished state.

- **DOC-1.** `ARCHITECTURE.md:61`: replace "Remaining 10 entries … target ≤25" with a pointer
  to `import_exemptions` in `tasks/quality/ceilings.toml` and `scripts/lint_import_exemptions.py`.
  No number in the doc (Q10).
- **DOC-2 (D4: keep).** ADR-008: add an amendment saying `TaskQueuePort` was not deleted and
  is kept on purpose, reserved for the Sep plan's Phase 5.2 (scheduler extraction and
  multi-process work dispatch). Then make "reserved" visible in the code, so the next audit
  does not log it as dead:
  - a one-line comment at `ports/task_queue_port.py` and at `task_runner.py`'s queue path,
    naming Sep 5.2;
  - keep both adapters (`infrastructure/queue/in_memory_task_queue.py`,
    `redis_task_queue.py`) under test, so they do not rot while unused. If no test exercises
    them today, add one contract test that runs the same enqueue, dequeue and ack sequence
    against both.
- **DOC-3.** ADR-007: add an amendment with the current sizes, and say that the target is now
  the `functions_over_150_lines` ratchet, not prose.
- **DOC-4.** Replace the header's self-score with a link to the latest audit record and its
  score. Drop "Maturity: Production" until Sep Phase 5.5 passes.
- **Diagram.** After 3.5, `core` really has no edges into `tools`/`application.di`, and the
  diagram becomes true. Redraw `tools` between application and infrastructure (it depends on
  application ports and is wired by DI). Remove the `infra -->|implements ports| app` arrow
  for tools.
- **DOC-5.** Lands with 1.1.
- **UNK-1.** Give each bullet in `docs/SECURITY_MODEL.md` the test that proves it, or mark it
  `unverified` inline. Write tests for bullets on the auth path (fail-closed bind, webhook
  role) if none exist. The doc's own header says its behavior claims were never re-verified.
- **Map.** Update the `map/` cards for every moved noun (`RoleBasedToolRegistry`, `BaseTool`,
  `FlowState`, `ToolExecutor`, `LLMPool`), and run `make gen-map-index` and `make lint-map`.

**Effort:** S–M.

---

## 11. Phase 8 — Scalability (SCL-1)

Owned by the Sep plan Phase 5 (5.1 Postgres, 5.2 scheduler extraction, 5.3 process-local
state, 5.5 proof). Replica count stays 1 until 5.5 passes (`docker-compose.yml:36-52`).

This plan adds three inputs to Sep 5.3, found in the audit and not listed there.

**1. TaskRunner state in process dicts.** These are lost on restart and invisible to a
second replica:

- `_retry_counts` (`task_runner.py:81`);
- `_flow_factories` (`:82`);
- `_failed_sessions` (`:83`), which is the dead-letter queue.

Move the retry count and failure reason onto the `Session` (persisted). The dead-letter
queue becomes `SessionStatus.FAILED` plus a reason, so no new store.

**2. Per-session executor maps.** `_LOCAL_TAB` and `_WRITTEN_FILES` in `_tool_executor.py`
are taint inputs, so losing them changes security decisions. Move them into session facts,
like the effect ledger in 2.2.

**3. Module registries.** Each needs an owner and a reset story:

- `core/behavior_tracker.py:559` `_tracker_registry`;
- `infrastructure/persistence/connection_pool.py:424` `_pool_registry`;
- `interfaces/factories.py:40` `_shared_container`;
- `tools/advanced_browser.py:18` `_playwright_instance`.

**The 10× proof** (feeds Sep 5.5): extend `tests/stress/test_sqlite_write_contention.py` with
a run of 30 concurrent sessions against a fake LLM with injected latency, through the real
web app. Assert:

- the LLM pool bound holds (2.1 counters);
- there is no `database is locked`;
- p95 event-persist latency stays under a recorded budget.

This is the trace the audit said it could not produce statically.

---

## 12. Sequencing and interactions

```
Phase 0 (0.1-0.4) ─┬─> 1.1 SEC-1 ──> 1.1b scan ──> 2.2 ORCH-2 ──> Phase 5 executor extraction
                   │      (all edit _tool_executor.py and _base.py; do not run in parallel)
                   ├─> 1.2 SEC-2   (independent)
                   ├─> 1.3 CON-1   (independent)
                   ├─> 1.4 OPS-1 pin test (independent)
                   ├─> 2.1 ORCH-1 ─┬─> 3.7 di↔interfaces (both edit di/__init__.py)
                   │               └─> Phase 6 (needs the decorator as choke point)
                   │                      └─> 2.4 cost budget (needs complete metering)
                   ├─> 2.3         (independent)
                   ├─> 3.1, 3.3, 3.8, 3.9 (independent, S each)
                   ├─> 3.2 ──> 3.4 (3.4 touches _base.py: after 2.2)
                   ├─> 3.5         (independent; D3 decided yes)
                   ├─> 3.6 ──> Sep §5.4
                   ├─> Phase 4     (independent, batch by directory)
                   └─> Phase 7 strike-through now; rewrite last
Phase 8 = Sep Phase 5, after everything above.
```

**Overlaps with `tasks/remaining_fix_plan.md`.**

- Wave E (persistence, DI, flow; F28 type-safe mediator dispatch) edits `application/di` and
  `flows/` too. Land Wave E's DI work before or after 3.7 and typed keys, never interleaved.
- Wave B (guard stack) touches `_tool_executor.py`. Sequence it with 1.1 and 2.2.

**Parallel-safe batches.** `{1.2, 1.3, 1.4, 3.1, 3.8, 3.9, Phase 4}` touch disjoint files and
can go to separate sessions or branches.

---

## 13. Score targets (same rubric as the audit)

| Dimension | Now | After | Condition to reach it |
|---|---|---|---|
| Separation of concerns | 1 | 2 | 1.2, 3.1–3.5, 3.9 done; remaining exemptions are composition-root edges only |
| Consistency with baseline | 1 | 2 | Phase 7 done; no MAJOR drift (tools fixed by 3.2–3.3) |
| Coupling and dependency health | 0 | 1 → 2 | 1 once `module_cycles = 0` (3.6–3.8); 2 also needs the module registries in §11 owned |
| Testability and observability | 1 | 2 | Phase 6 done; coverage floor ratcheted (0.3) |
| Failure resilience and scalability | 1 | 2 | 2.1–2.4 done; "scalability" stays partial until Sep 5.5 |

Target after Phases 0–7: **8–9/10** on the code. Replica scaling stays with the Sep plan.

---

## 14. Decisions (resolved 2026-10-24)

| # | Question | Decision | Where it lands |
|---|---|---|---|
| D1 | Do error results from EXTERNAL tools taint the session? | **No.** Errors are fenced but never taint. | 1.1 step 4, `must_taint` |
| D2 | Run the injection scanner on fenced content? | **Yes**, as a signal that escalates trust and records detections; never as the control, and never editing content. | 1.1b |
| D3 | Delete `core/agent.py` and switch the legacy REPL to `ChatFlow`? | **Yes** | 3.5 |
| D4 | Delete `TaskQueuePort` and the queues, or reserve them for Sep 5.2? | **Keep**, reserved for Sep 5.2, marked in code and kept under a contract test | Phase 7, DOC-2 |
| D5 | Make `VALKEY_PASSWORD` fail closed? | **No.** Keep the default; pin the unpublished port with a test. | 1.4 |
| D6 | Session cost cap default | **Two thresholds:** soft $0.50 degrades to FREE/BUDGET models, hard $2.50 asks through the ADR-013 channel then stops. Defaults are re-derived from data by a fixed rule (soft = p99, hard = max(5 × p99, max)). | 2.4 |

---

## 15. Definition of done

- Every row in §1 is closed, accepted with its guard pinned (OPS-1, D5), or listed in §11 as
  owned elsewhere, with a link.
- Ceilings after this plan:

  | Ceiling | Now | Target |
  |---|---|---|
  | `module_cycles` | 3 | 0 |
  | `dynamic_weebot_imports` | 18 | optional-dependency count only |
  | `blocking_io_in_async` | 29 | 0, blocking |
  | discarded-task check | 8 | 0, blocking |
  | `import_exemptions` | 73 | lower by every line removed in Phases 1 and 3 (no target number, per Q10) |
  | `functions_over_150_lines` | measured | lower than measured |
  | `string_di_keys` | measured | lower than measured |

- No list of tool names decides trust. No `LLMPort` leaves the container unbounded. No
  egress call replays on a session retry.
- `make check` and the CI `lint-and-arch` job run the same gates.
- `ARCHITECTURE.md` holds no hand-typed counts.

## Appendix A — Verification commands

```bash
make install
make check
make lint-imports
python scripts/lint_import_exemptions.py
python scripts/lint_async_io.py
python scripts/lint_unawaited_coroutines.py
python scripts/lint_di_wiring.py
python scripts/quality_ceilings.py --verify-not-raised --baseline origin/main
pytest tests/unit/test_architecture_fitness.py -v
pytest tests/unit/core/test_trust_boundary_registry.py tests/unit/core/test_trust_boundary.py -v
pytest tests/integration/test_security_penetration.py -v
pytest tests/stress/ -v --timeout=120
```

## Appendix B — Audit ledger (2026-10-24, condensed)

Evidence levels follow the audit's EGFV labels. Runtime claims are HYPOTHESIS until the
tests named in this plan run.

| ID | Location | Evidence | Sev | Reach |
|---|---|---|---|---|
| SEC-1 | `core/trust_boundary.py`; `_base.py:1042`; `_tool_executor.py:438-445` | VERIFIED design, HYPOTHESIS effect | HIGH | REACHABLE |
| SCL-1 | `docker-compose.yml:36-52`; `connection_pool.py:109,187`; `task_runner.py:60-86` | VERIFIED structure, HYPOTHESIS load | HIGH | REACHABLE |
| LAY-4 | 18 `import_module("weebot.…")` sites; `interfaces/factories.py:28` | VERIFIED | MED | REACHABLE |
| LAY-1 | AST edges: app→tools 8, tools→app 6, infra→tools 6, tools→infra 17, core→tools 3, core→di 1 | VERIFIED; diagram claim FALSE | MED | REACHABLE |
| LAY-2 | SCCs: `flows/states` 8, `di↔interfaces` 3, `templates` 3 | VERIFIED edges | MED | REACHABLE |
| SEC-2 | `interfaces/web/auth.py:124-135,223-234` | VERIFIED | MED | REACHABLE |
| ORCH-1 | `llm_pool` consumers: `_cascade.py`, DI only; 68 direct calls | VERIFIED consumers, HYPOTHESIS load | MED | REACHABLE |
| ORCH-2 | `task_runner.py:270-286`; 0 idempotency hits | VERIFIED absence | MED | REACHABLE |
| CON-1 | 8 discarded-task sites (§1.3) | VERIFIED pattern | MED | REACHABLE |
| CON-2 | `lint_async_io.py` output, 29 (4 false positives) | VERIFIED | MED | mixed |
| CPL-1 | `_base.py` 1180, `plan_act_flow.py` 985, `di/__init__.py` 700 lines | VERIFIED | MED | REACHABLE |
| CPL-2 | `di/__init__.py:459`; `lint_di_wiring.py` docstring | VERIFIED | MED | GUARDED |
| DOC-1 | `ARCHITECTURE.md:61` vs `ceilings.toml:227` | FALSE | MED | — |
| DOC-3 | ADR-007 vs `wc -l` | FALSE | MED | — |
| DOC-2 | ADR-008 vs `ports/task_queue_port.py` | FALSE | LOW | DEAD |
| DOC-4 | `ARCHITECTURE.md:4` | HYPOTHESIS | LOW | — |
| DOC-5 | `trust_boundary.py:9` vs `wrap_untrusted` | FALSE | LOW | REACHABLE |
| LAY-3 | `config/capability_profiles.py:20`; `config/fs_permissions.py:33` | VERIFIED | LOW | REACHABLE |
| ORCH-3 | `resilient_adapter.py:144`; `_cascade.py:336-349` | HYPOTHESIS | LOW | REACHABLE |
| ORCH-4 | `di/__init__.py:65` (sub-agents only); `config/constants.py:56,67` (tokens only) | VERIFIED absence (resolved 2026-10-24) | MED | REACHABLE |
| OBS-1 | `correlation_id` in 4 files; 0 prompt-version hits | VERIFIED | LOW | REACHABLE |
| CI-1 | `Makefile:130` vs `architecture.yml`; `:35`, `:171` | VERIFIED | LOW | REACHABLE |
| OPS-1 | `docker-compose.yml:23,30,78` | VERIFIED | LOW | GUARDED |
| UNK-1 | `docs/SECURITY_MODEL.md` header | UNKNOWN | — | UNKNOWN |
