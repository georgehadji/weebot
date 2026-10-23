# Plan: fix everything still open

Status: DRAFT for review, written 2026-10-22. Nothing in it has started.

This file only sets the order and lists the work found since the waves were written. Finding details, card links and wave task text stay in `tasks/icm_fix_plan.md` (F-numbers and W-numbers below point there). The rules in its section 1 hold for every task here: a failing test first, ceilings never raised, fail closed, a card update per task, and a human gate per wave.

## What "everything" covers

| Source | Open items |
|---|---|
| Findings catalog | F06, F20, F22-F28, F32-F35, F37. F02/F03 close with the W3.7 flip. |
| Wave 3 leftovers | W3.7 flip, ADR-013 "not done" list, W3.9 "not done" list |
| Real run, 2026-10-22 | IntentReview timeout, trajectory JSON error, premortem notes not persisted, CLI raw event print (F37) |
| Test and lint hygiene | 2 Windows baseline failures, 1 flaky ledger test, the Stripe test's `sys.modules` deletion, 3 E402 in `tests/conftest.py`, 1 E501 at `planning.py:286` |

Not covered: Jev (decision 6: skip), and clusters with no map card yet (section 6 of the fix plan). Wave G below covers those if you want them.

## Order

Gate commands for every wave: run `pytest tests/` from Git Bash with `.venv/Scripts` on PATH. Then run each `scripts/lint_*.py` one at a time, not while pytest runs, and then `lint-imports`.

### Wave A: hygiene (S each, about one session)
The goal is a zero-failure baseline, so later gates mean something.

- A1 **Windows baseline failures.**
  - `test_output_path.py:16`: compare the path case-insensitively.
  - `test_behavior_ledger_git.py`: clean up the temp tree with an `onerror` handler that clears the read-only bit on `.git/objects`.
  - Both are test-side fixes.
- A2 **Flaky `test_concurrent_appends_are_all_committed`** (1 pass in 3 alone; entries go missing). Reproduce in a loop first and find the cause before changing anything. A likely suspect is concurrent `git` on Windows racing on `index.lock`, which could be a real ledger bug and not only a test bug.
- A3 **Stripe test reload.** Remove the `sys.modules` deletion in `test_no_secret_with_dev_opt_in_allowed`. `get_settings.cache_clear()` already resets settings per test. The test stays the `.env` check (decision A below).
- A4 **Lint.** Fix the E402s in `tests/conftest.py:43-45` and the E501 at `planning.py:286`. First measure `ruff check .` across the repo. If it is not zero, record the count and decide whether a ruff ratchet is worth adding, instead of fixing everything at once.
- A5 **F37.** Trace where `flow run` prints the `PlanReviewEvent` repr, and why `session_id` is empty: `PlanReviewState` yields the event without `_emit`. Then fix it so the event is emitted once and rendered once.
- A6 **IntentReview timeout.** `_TIMEOUT = 5.0` (`intent_review_service.py:31`) times out on thinking models on every run, and the warning prints an empty message.
  - Log the exception type (`%r`).
  - Make the timeout a setting with a default that fits the configured model.
  - It still fails open.
- A7 **Trajectory analysis** (`trajectory_builder.py:107`). Parse an empty or non-JSON reply into a validated model (rule 2), and log the raw reply length instead of the JSON error.
- A8 **Premortem notes persisted** (F36 residual). Emit `PlanEvent(UPDATED)` when `PremortemState` changes the plan, with the same test shape as F36.

Gate: 0 failed.

Wave A result, 2026-10-22 (each task had a failing test before the fix):
- **A1 DONE.** `test_output_path` compares the path in lower case. `test_behavior_ledger_git` removes `.git` with an `onexc` handler that clears the read-only bit.
- **A2 DONE, a real ledger bug.** The flaky test hid data loss on disk. Parallel `LedgerManager.append` calls overwrote each other in the daily file (probe: 1-2 of 12 entries missing in 4 of 8 runs), so no commit could carry them.
  - `mark_override` is a read-modify-write on the same file, so it could also drop an append.
  - Fix: a `_FILE_LOCK` around the append and around the override's read-modify-write (`core/behavior_tracker.py`). The lock is per process, so a CLI and a web process appending at once can still race.
  - New repro: `test_concurrent_appends_keep_every_entry_on_disk`, with git stubbed out (failed 3 of 3 before). Both concurrency tests then passed 10 of 10.
- **A3 DONE.** The Stripe test no longer deletes `weebot.config.settings` from `sys.modules`. Running it before `tests/unit/config/test_get_settings.py` failed 2 tests before and passes after.
- **A4 DONE, partly.**
  - Fixed: the E402s in `tests/conftest.py` and the E501 at `planning.py:286`.
  - Repo-wide `ruff check .` finds 975 errors, mostly E501 (339), W293, E402, F401 and F841. The CI gate (`ruff check weebot/ cli/ --select F821,E9`) passes. The 10 F821s are in `tests/unit/test_cove_regressions.py`, a skip-marked class for the deleted `ResumableTask`. They were not deleted because this folder has no git to restore from.
  - Recommendation: no blanket ruff ratchet yet. Delete that dead class in a reviewed change.
- **A5 DONE (F37).**
  - `PlanReviewState` now emits the `PlanReviewEvent` through `_emit` (stamped, saved, published), and the CLI renders it as one line.
  - `flow run` and `dream` no longer repeat the question in the `input()` prompt; the subscriber has already printed it.
  - Test: `tests/unit/fixes/test_f37_plan_review_event.py`. `test_plan_review_state.py`'s mock flow gained an async `_emit`.
- **A6 DONE.** New setting `WEEBOT_INTENT_REVIEW_TIMEOUT_S` (`intent_review_timeout_s`, default 30, `gt=0`).
  - `IntentReviewService` reads it when no timeout is passed, which covers both callers (DI and `PlanningState`).
  - A timeout logs "timed out after Ns"; other errors log with `%r`. It still fails open.
  - Test: `tests/unit/application/services/test_intent_review_service.py`.
- **A7 DONE.** `TrajectoryBuilder` parses the reply with the shared `extract_json_text`, so a fenced reply now works, and it names an empty reply. Test: `test_trajectory_builder_reply.py`.
- **A8 DONE.** `PremortmState` emits `PlanEvent(UPDATED)` before adopting the plan with its risk notes. Test: `tests/unit/fixes/test_premortem_plan_persisted.py`.
- **Found during the gate: the generated `.env.example` weakened two security defaults.**
  - `scripts/generate_config_reference.py` listed `WEEBOT_EGRESS_ENFORCE` and `WEEBOT_ENFORCE_SESSION_OWNERSHIP` with default `"false"`, while the code defaults both to on. Regenerating for A6 reverted the hand-fixed template, and `test_w6_ws_authorisation` caught the session-ownership one.
  - Fixed at the source, in the generator. A new test checks the egress line too.
  - The generator's list also lacked `WEEBOT_SHELL_GUARD_MODE` (W3.1); it is added. Compared with the earlier template (read from the developer's `.env` copy, secret values not shown), nothing else changed.
- **Gate:** 5472 passed, **0 failed**, 10 xfailed, 119 skipped. Lints at ceilings (serial); import-linter 9 kept; the CI ruff gate passes. This is the first zero-failure baseline on this machine.

### Wave B: finish the guard stack
- B1 **F06**, decision 3: wire the `finance`/`payment` categories and `financial_tools_always_ask` into the guard chain as ASK. First list which tools are financial, from the registry and `stripe_*`. M
- B2 **ADR-013 leftovers:**
  - Journal `approval_granted`, `approval_denied` and `approval_expired` to the event store.
  - Add a unit test for the `_base.py` `approval_required` branch.
  - Do one manual browser round trip: web UI, ask, "yes", re-run.
  - S-M. A UI renderer for `tool_approval` is optional (decision C).
- B3 **Observe data.** Collect `tool guard [observe]` lines from real runs; one run exists so far. Summarize them as counts by guard and verdict, plus any DENY that should not be. This runs alongside Waves C-F.
- B4 **W3.7 flip** to `enforce`, which closes F02 and F03 and turns the last F01 xfail into a plain test. **Needs your go** after B3 (decision B). S
- B5 **Sandbox leftovers.**
  - First, a short ADR on workspace mounts.
  - Then Docker `--read-only` with a tmpfs `/tmp`, and `--user`.
  - Then make `create_default_sandbox()` follow the Docker-first priority with an availability check (F31 rest).
  - Then an optional strict mode that refuses network-off on a backend without isolation (F30 rest).
  - M-L.
- B6 **MCP per-call network.** The MCP server bypasses `ToolExecutor`, so it never gets per-call network. Document this in `docs/SECURITY_MODEL.md`; no code unless MCP users need it.

Wave B result so far, 2026-10-22 (`shell_guard_mode` stays `observe`):
- **B1 DONE (F06).** Finding: no built-in tool is financial. One can only arrive from an external MCP server, through three adapters (`MCPToolBridge`, `MCPToolkitAdapter`, `MCPToolRegistryBridge`), and no tool carried a category. So the `finance`/`payment` rule could not fire.
  - **Design** (user choice, 2026-10-22: name patterns): new setting `WEEBOT_FINANCIAL_TOOL_PATTERNS`, comma-separated case-insensitive globs. The default is `*stripe*,*payment*,*invoice*,*refund*,*payout*,*checkout*,*billing*`. The existing `FINANCIAL_TOOLS_ALWAYS_ASK` (default true) switches it off.
  - **Mechanism:** `is_financial_tool()` and `FinancialToolAdapter` (guard `financial_policy`, ASK) are in `tool_guards.py`, and the adapter is in the default chain. `guard_tools()` now also wraps financial tools.
  - **Where tools are wrapped:** the registry (as before); `build_tools()` in `interfaces/factories.py`, which wraps the combined list after MCP, extra and Apify tools join, resolves `guard_tools` through DI (the interfaces layer may not import `tool_guards`) and fails closed if it is missing; and the MCP server's `_register_dynamic_tools`.
  - **Behaviour:** in observe mode the ASK is logged and the call runs. In enforce mode it goes to the approval channel; headless runs are refused.
  - **Tests:** `tests/unit/fixes/test_f06_financial_tools_ask.py` (9). `test_mcp_tool_guards.py` now counts only `guard_tools` calls that had tools.
- **B2a DONE: approval outcomes are journaled.**
  - `set_approval_journal(store)` writes `approval_granted`, `approval_denied` and `approval_expired` through `EventStorePort.log_event`, best effort, like `DurableEventBus`. The data is tool, guard, fingerprint and channel; no arguments, which may hold secrets.
  - Expiry comes from a new `on_expired` callback on `ApprovalManager`, so core still imports nothing from application.
  - Wired in the web lifespan and in CLI `flow`.
  - Test: `tests/unit/application/services/test_approval_journal.py` (5).
- **B2b DONE.** `tests/unit/test_executor_tool_approval_pause.py` drives `ExecutorAgent.execute_step` with a tool that answers PENDING. It checks for `ToolApprovalEvent`, then `WaitForUserEvent` with the prompt, then no further LLM turn. A mutation run (data key renamed) makes it fail.
- **B2c DONE, 2026-10-22: browser round trip.** Backend run with `uvicorn` without reload (`.claude/launch.json`), UI with `npm run dev`; `npm ci` was needed first.
  - **Result:** task `python_execute` `urllib` GET `https://httpbin.org/get` (new host) in session `7b3c1c44-33bd-4027-bb8f-e18a6b3397d6`.
    1. The plan review came up and was approved.
    2. The browser showed "Tool 'python_execute' needs your approval (egress_guard ... httpbin.org)".
    3. Reply "yes" logged `approval grant issued`, then `approval grant used` for the same fingerprint (`575472bb…`), and the call re-ran and printed 200.
    4. The event store holds `approval_granted` (channel `flow`) and 23 events for the session, `tool_approval` among them.
  - **Five real bugs blocked it; each fixed with a failing test first:**
    1. `POST /api/sessions` returned 500 for every new web session. `_session_to_response` passed the `SessionContext` model to a dict field. It now dumps the model; a dict is also accepted, because `model_copy` skips validation. Test: `tests/unit/interfaces/web/test_session_response.py`.
    2. A web reply to a WAITING session did nothing: `dispatch_session_input._resume` stored the answer and set RUNNING without running the flow, so no plan review or approval in the web UI could move on. It now calls `TaskRunner.resume_session` (added to `TaskRunnerPort`).
    3. `TaskRunner.resume_session` ran the flow with `context["last_prompt"]`, the original task, not the answer. FlowRouter would have read the task as a plan-change request. An optional `prompt` now reaches `_run_flow`, retries included. Tests: `tests/unit/test_task_runner_resume.py`, `test_dispatch_session_input.py`.
    4. `DurableEventBus` journaled nothing: `model_dump()` kept datetime objects and `EventStore.log_event` `json.dumps` them, so every write failed with a warning. Both helpers now use `mode="json"`. Test: `tests/unit/infrastructure/test_durable_event_bus_journal.py`.
    5. My W3.4 wiring was incomplete: nothing called `ToolExecutor.set_step_context`, so the approval scope had session `""` and Flow pause denied every web approval silently. `ExecutorAgent.execute_step` now passes the step's session. Test: `test_the_step_session_reaches_the_tool_call`.
  - **Seen, not fixed:**
    - **The Plan panel shows "Internal server error":** `ops_router` `plan-viz` sent a query through `send()`, which is F22. Fixed in W7.1 (Wave D).
    - **Python run through the shell is not egress:** the planner once turned the task into PowerShell `python -c "...urlopen..."`, which `EgressGuard` does not classify, because only `python_execute` code is checked (W3.8).
    - **DPPM made a poor plan:** for a one-line change request it produced a 13-step plan (web search, file writes, bash).
    - **The old `POST /sessions/{id}/resume` endpoint has the same no-op bug** as item 2. The UI uses `/input`.
    - **Session `0b52fc54…` is stuck in RUNNING:** it came from the earlier no-op resume.
- **Gate:** 5487 passed, 0 failed, 10 xfailed. Lints at ceilings (serial); import-linter 9 kept; the CI ruff gate passes.

Wave B, continued 2026-10-22 (user: "Proceed"):
- **`/resume` endpoint fixed.** `POST /sessions/{id}/resume` now goes through the same dispatch as `/input`, via a shared `_dispatch_input` helper in `routers/sessions.py`, so it resumes the flow. It still refuses a session that is not WAITING with 400. Test: `tests/unit/interfaces/web/test_resume_session_endpoint.py`.
- **Shell-run Python is egress.** `EgressGuard` classifies `python`/`python3`/`py` with `-c` code that imports a network library, run through `bash` or `powershell`. The recipient is the first URL host, else unknown, which asks. Test: `tests/unit/test_egress_shell_python.py` (5 positive cases failed before the fix; 4 negatives).
  - Not covered: `python script.py`, whose code is in a file.
- **B6 DONE.** `docs/SECURITY_MODEL.md` now states:
  - the sandbox network rules
  - that MCP gets no per-call network or approvals, and needs `SANDBOX_ALLOW_NETWORK=true` for code that uses the network
  - what the egress gate classifies, and that fetch URLs are not checked
  - how approvals resolve per channel, including that the guard chain only logs in observe mode

  The ADR-013 status line is updated for the journaling.
- **Gate:** 5516 passed, 0 failed, 10 xfailed. Lints at ceilings; import-linter 9 kept; ruff clean on the changed files.
- **B5 DONE (ADR-014 Approved and implemented, 2026-10-22).**
  - **Docker layout:** `DockerLinuxSandbox` now runs with `--read-only`, `--user 1000:1000`, `--tmpfs /tmp` (exec, 256 MB), a `weebot-pip-cache` volume, and `PIP_USER=1`/`PYTHONUSERBASE=/tmp/.local` so installs work on a read-only root. `SandboxConfig.workspace_dir` (set by `build_sandbox_config` from `WORKSPACE_ROOT`) is mounted read-only at `/workspace`, with `Output/` read-write. A host cwd maps into `/workspace`, and a cwd outside the workspace goes to `/workspace`.
  - **Image:** only `weebot-tool-env:latest` is used, with no `python:3.11-slim` fallback. A missing image gives a clear error with the `docker build` command. The Dockerfile pins the `weebot` user to uid 1000.
  - **Selection:** new `SANDBOX_MODE=docker_first` uses Docker when it is running and the image is built, else the platform default with a warning. `auto` is unchanged.
  - **Strict mode:** `SANDBOX_REQUIRE_ISOLATION=true` (default false) returns `IsolationRequiredSandbox`, which refuses every call when network-off is requested on a backend without `NETWORK_ISOLATION`.
  - **Tests:** `tests/unit/infrastructure/sandbox/test_docker_workspace.py` (7) and `test_sandbox_selection.py` (7). `test_docker_image.py`'s two fallback tests now expect no image.
  - **Ceilings lowered:** `silent_except_handlers` 126 to 125 and `bandit_b110` 64 to 63. The rewritten `_resolve_image` logs instead of `except Exception: pass`.
  - **Not verified live:** Docker Desktop was not running, so no container was started and the image was not built here.
  - **Fitness fix:** the sync Docker readiness probe lives in `weebot/infrastructure/sandbox/_docker_probe.py`, because `test_no_blocking_calls_in_async` bans `subprocess.run` in `factory.py`, which has async code.
  - **Gate** (with the Agent-Reach tool): 5572 passed, 0 failed, 10 xfailed. Lints at ceilings (`bare_env_reads` still 71); import-linter 9 kept.

### Wave C: cost and events (W4.1-W4.3, F23, F24)
In order: W4.1 `LLMCallCompleted`, W4.2 one cost query, then the W4.3 Valkey fail-fast (decision 4). Turns the F23 and F24 xfails into plain tests.

Wave C result, 2026-10-22 (user: "Start Wave C … one task at a time, each with a failing test first"):
- **W4.1 DONE.**
  - **The event:** new domain event `LLMCallCompleted` (session, model, prompt/completion tokens, `estimate_cost` USD).
  - **Who emits it:** `CascadeExecutor` raises it after every successful call, on both the normal path and `_live_model_rescue`, through a new `on_call_completed` hook. A hook failure is logged and never fails the call.
  - **Publishing:** `ExecutorAgent._publish_llm_call` stamps the step's session and publishes it as a domain event.
  - **Storage:** `DurableEventBus` writes `cost`, `model` and `tokens_used` for that event type only.
  - **Wiring checked:** the flow hands the DI `DurableEventBus` to the executor, and `SessionScopedEventBus` passes domain events through.
  - **Tests:** `tests/unit/fixes/test_w41_llm_call_completed.py` (5).
  - **Not covered:** LLM calls outside the executor cascade (planner, verifier, intent review) still emit nothing.
- **W4.2 DONE.**
  - **The query:** new `EventStorePort.get_cost_window(window_hours)` sums the `llm_call_completed` rows by model, using SQLite `datetime('now', '-N hours')`.
  - **The handler:** `GetCostSummaryHandler(event_store)` returns it, and the mediator registration passes the DI event store.
  - **Callers:**
    - CLI `costs --days` (1–30) prints a per-model table from that handler instead of the placeholder rows.
    - MCP `weebot://costs` is now async and uses the same handler. `run_mcp.py` attaches an `EventStore`; before, nothing passed a tracker, so the resource was always a stub.
  - **Deleted:**
    - `weebot/infrastructure/event_logging.py` (`EventLogger`) and its example 4. Examples 1–3, which use `EventStore` directly, stay.
    - The unused DI key `cascade_tracker` and its factory, because `lint_di_wiring` flagged it once the old handler stopped resolving it.
  - **Tests:** the F23 xfail is now a plain test, plus `test_w42_one_cost_query.py` (4).
  - **Open (closed by W7.1):** the ops API called `mediator.send` (F22, Wave D).
- **W4.3 DONE (fail-fast half, per decision 4).**
  - **DI:** `_create_event_bus` raises `RuntimeError` naming the variable when `WEEBOT_VALKEY_URL` or `WEEBOT_REDIS_URL` is set. Otherwise it builds `DurableEventBus(AsyncEventBus())`.
  - **Adapter:** `ValkeyEventBus.publish` and `publish_domain_event` now raise when Valkey is connected, instead of sending to unread channels and dropping local delivery.
  - **Tests:** the F24 xfail is now a plain test, plus `test_w43_valkey_fail_fast.py` (3).
  - **Not built:** the bridge (reader task with an origin tag) waits until more than one process must share events.

### Wave D: ops API (W7.1, F22)
After W4.2. Turns the F22 xfail into a plain test.

- **W7.1 DONE (2026-10-22).**
  - **Router:** `ops_router`'s three endpoints call `mediator.query` and take the mediator and state repo from the lifespan container on `app.state` through `Depends`. No `Container()` per request.
  - **Import exemption:** `ops_router -> application.di` removed from `.importlinter`; `import_exemptions` 76 to 75.
  - **Tests:** the F22 xfail is now four plain tests (cost summary, active sessions, plan-viz, plan-viz 404). The fixture fails if a `Container` is built per request.
  - **Real container:** `configure_defaults` registers all three query handlers.
  - **Not done:** type-safe dispatch (`send` rejecting a `Query`) stays with F28 in Wave E.

### Wave E: persistence, DI, flow (W5.1-W5.5; F25-F28, F32-F35)
- **Order:**
  1. W5.2 (S)
  2. W5.3, the `Container()` ratchet
  3. W5.5, the registry
  4. W5.1, role ports
  5. W5.4 last, which needs its ADR
- **Extra acceptance check from the real run:** one `CatalogValidator` line per process, not about 25. That shows F28/F35 are gone at runtime, not only in the ratchet count.
- Turns the F32 and F33 xfails into plain tests.
- **W5.2 DONE (2026-10-22).**
  - **Dispatch kind:** `Mediator.send` raises `TypeError` for a `Query` and `query` for a `Command`, naming the right method. Before, the wrong kind failed as "no handler registered" (how F22 hid).
  - **Tracer:** constructor argument (`Mediator(tracer=...)`); `build_mediator` passes the container's `TracingAdapter`. No tracer means no spans. The Mediator no longer builds and configures a `Container()` on first use.
  - **Tool-less fallback:** when the admin tool set fails to build, `build_mediator` still logs the warning and now also sets `mediator.degraded["tools"]`. `/health` has an `agent_tools` component that reads it and turns the overall status degraded.
  - **Found on the way:** `/health/status` called `health_check()` with no arguments, so its state repo was FastAPI's `Depends` marker and the database always read unhealthy. It now passes its request and state repo.
  - **Tests:** `tests/unit/fixes/test_w52_mediator_dispatch.py` (7), all failing first.
  - **Left to W5.3:** `_maybe_get_str` swallowing `KeyError`, and the hand-built `Container()` sites.
- **W5.3 STARTED (2026-10-22): ratchet in place, first roots migrated.**
  - **Ratchet:** `scripts/lint_container_construction.py` counts `Container()`, `<module>.Container()` and `import_module(...).Container()` calls in `weebot`, `cli`, `run.py`, `run_mcp.py`, outside `weebot/application/di/`. Ceiling `container_construction` in `tasks/quality/ceilings.toml`, wired into `make check` (`lint-container-construction`) and CI (`architecture.yml`, blocking).
  - **Count:** 44 when added, 42 now. `interfaces/factories.py` `_resolve_personality` and `_get_flow_factory` use the module's one cached container (`_cached`), so sub-agent flows share the process event bus and state repo.
  - **Tests:** `tests/unit/fixes/test_w53_container_construction.py` (3) and the ceilings key list, all failing first.
  - **Batch 2 (2026-10-22), 42 -> 39:**
    - `ChatFlow` takes `persistence_adapter`; `Container.build_chat_flow` and the `"chat"` flow registry entry pass `"session_persistence"`. Its old lookup used a bare `Container()` that never ran `configure_defaults`, so the adapter was always missing and chat saves skipped the retrying `SessionPersistenceAdapter`.
    - Deleted `flows/collaborators/event_emitter.py` (`EventEmitter`) and `flow_persistence.py` (`FlowPersistence`): extracted from `PlanActFlow`, never constructed.
    - Tests: `tests/unit/fixes/test_w53_chat_flow_persistence.py` (3), failing first.
    - **Seen, not fixed:** `PlanActFlow._persistence_adapter` is also never set, so plan-act saves skip the retrying adapter too. `interfaces/factories.create_flow("chat", ...)` passes no `state_repo`, so those chat flows do not persist at all.
      - **Fixed (2026-10-23, `e0318704`):** `PlanActFlowConfig.persistence_adapter`; `create_flow` (plan-act and chat) and `_get_flow_factory` pass the cached `session_persistence`, and chat flows get `state_repo`. Test: `tests/unit/fixes/test_create_flow_persistence.py` (3), failing first.
  - **Batch 3 (2026-10-22), 39 -> 36:**
    - `CompletedState`'s skill-gap job and dream scan built a whole `Container()` on every flow completion to fetch `idea_gate`, `dreamer_agent` and `EventStorePort`. They now take them as arguments; `PlanActFlow` and `PlanActFlowConfig` carry `idea_gate`, `dreamer_agent`, `event_store`, and `factories.create_flow` fills them from its cached container. A missing one skips the job.
    - `ToolExecutor._get_egress_guard` constructs `EgressGuard()` directly. The DI factory is the same `EgressGuard()`, and a fresh container shares nothing.
    - With that, nothing resolved the `EgressGuard` DI binding (`lint_di_wiring`: unresolved). Deleted the binding and `FactoriesMixin._create_egress_guard`; the EgressGuard card and the module note now say who builds it.
    - Tests: `tests/unit/fixes/test_w53_completion_jobs.py` (4) and one more in `test_w53_container_construction.py`, all failing first.
    - **Not migrated, on purpose:** `core/agent.py` (`RecursiveWeebotAgent`, LangChain, sunset 2027-03-01 per ADR-009).
    - **Other PlanActFlow builders** (`_agent_tools`, `_skillopt`, `harness_opt_flow`, the DI `"plan_act"` registry entry) do not pass the three, so their completions skip the two jobs. Before, they ran them through a new container.
  - **Batch 4 (2026-10-23), 36 -> 34:**
    - `GatewayAdapter.__init__` requires `llm_port`. Its `None` branch built a whole `Container()`; every subclass already requires and passes `llm`.
    - `AgentRunner` takes `retention_agent`. Its constructor built a `Container()` to fetch it, for every runner. `Container.build_agent_runner`, `flow run`, `dream build` and `run.py` pass their own container's; the other CLI runners (`resume`, `list`, `cancel`, `undo`) never reach the retention review.
    - Tests: `tests/unit/fixes/test_w53_interface_roots.py` (4), failing first.
    - Also lowered: `import_exemptions` 75 to 73 (the two `-> application.di` exemptions for `agent_runner` and `gateways.base` removed from `.importlinter`), `silent_except_handlers` 125 to 124 and `bandit_b110` 63 to 62 (AgentRunner's `except Exception: pass`).
    - **Not migrated:** the MCP server's reranker lookup (`mcp/server.py`). `run_mcp.py` builds no container, so moving the lookup there would not lower the count; it waits until `run_mcp.py` is given one composition-root container.
  - **Batch 5 (2026-10-23), 34 -> 31: the tool registry.**
    - `create_tool_collection` / `create_tool_collection_from_names` take `state_repo` and `rerank`. They built a fresh `Container()` for every tool with `set_rerank`, for the state-repo tools and for a missing flow factory. `build_mediator`, `_create_sub_agent_factory`, `_build_plan_act_flow_for_session` and `factories.build_tools` pass their container's. With no flow factory the sub-agent tools get `None`, as they did when that lookup failed.
    - `build_tool_class_map` reads each tool's `name` from its Pydantic field default instead of instantiating every tool class (the W5.5 "fix discovery via `model_fields`" item). Instantiating ran each self-resolving tool's constructor, so six whole containers were built once per process just to map names. The map is unchanged except `product` (`ProductTool`), whose construction fails and was missing; the registry still skips it at construction, now with a debug line instead of the "not found in class map" warning.
    - Tests: `tests/unit/fixes/test_w53_tool_registry_collaborators.py` (4), failing first.
    - Also lowered: `silent_except_handlers` 124 to 121 and `bandit_b110` 62 to 59 (the registry's three `except Exception: pass` around its lookups).
    - **Not changed:** `cron_agent_runner` calls `create_tool_collection` without a container, so its sub-agent tools have no state repo and no flow factory, and web search has no reranker. The six self-resolving tools (audit, knowledge, persistent memory, video ingest, voice in/out) still build a `Container()` when constructed with no collaborator; that is W5.5's wiring table.
  - **W5.3 DONE (2026-10-23), 31 -> 9.** Batch 6: the six self-resolving tools (W5.5 wiring), `flow run`/`flow retry` and then every plain CLI command, `cli/main.py` and `run.py` use `factories.shared_container()` (one container per process; a `flow run` logs `CatalogValidator` once). The scheduler's cron-agent loader takes the caller's container and the MCP server its reranker; `run_mcp.py` builds the one root. Found on the way: cron agent jobs were never loaded by any process, every scheduled run raised `TypeError` (the shared callable needed `job_id`; the scheduler calls with none), and runners got `tool_registry=None`; the web lifespan now loads them (`tests/unit/fixes/test_cron_agent_jobs_wired.py`). `run_mcp.py` imported the scheduler from a module that does not exist, so the MCP server never had one. The 9 left: four `harness` commands (their own `db_path`/model), `flow skillopt` (extra configuration), the web lifespan, `run_mcp.py`, the shared root, and `core/agent.py` (ADR-009 legacy).
  - **Left (was 41, historical):** 30 sites outside `factories.py`. Composition roots (web lifespan, CLI commands, `run.py`) are expected to stay at one per entry point; the rest (flow states, collaborators, tools, `tool_registry.py`, `scheduler.py`, `mcp/server.py`, gateways) take collaborators as arguments, which overlaps W5.5 for the tools. `_maybe_get_str` still swallows `KeyError`.

- **W5.4 DONE (2026-10-23): ADR-015, the step executor gets the flow's settings (F25).** `StepExecutionContext` rides on `ExecuteStepCommand` (in process, excluded from dumps); `Container.step_executor` overlays it on the singletons; the handler reports token usage and skill gaps, which the flow totals. Found on the way: steps ran with the container's admin tools, not the flow's role-scoped collection (the handler ignored `command.tools`), and token-based termination read an executor that never ran a step. `PlanActFlow._executor` is `_summary_executor`. Tests: `tests/unit/fixes/test_w54_step_execution_context.py` (6, failing first).
- **W5.1 DONE (2026-10-23): role ports (F26, F27).**
  - **Roles:** `weebot/application/ports/state_roles_port.py` (behavioral rules, corrections, session constraints, opportunities, memory metadata, plan-template writes) and `weebot/domain/ports.py` (plan-template reads, commitments, and `as_role`). `SQLiteStateRepository` plays all of them; a caller resolves its role once and skips the feature when the repository does not have it, instead of raising `AttributeError`. `count_sessions` moved onto `StateRepositoryPort` with a default over `list_sessions`, so every repository answers it.
  - **F27:** `list_opportunities`, `mark_opportunity_presented`, `accept_opportunity` and their helper methods deleted.
  - **Defects the typing surfaced, all fixed:** `CommitmentEngine` passed a `limit=` the repository does not take and read dict rows as objects, so every heartbeat and every chat-time commitment summary failed inside an `except`; the summary also never fetched overdue commitments. Commitments now come back as `Commitment` objects (`Commitment.from_row`), with ISO due dates on save. `OpportunityEngine` passed the proposal object where `save_opportunity` takes fields, so no opportunity was ever stored.
  - **Tests:** `tests/unit/fixes/test_w51_role_ports.py` (22, failing first); two test doubles now play their whole role.
- **W5.5 STARTED (2026-10-23): the registry (F32, F33, F35).**
  - **F32, decided by deletion:** the `allowed_roles` autodiscovery could never take effect, and fixed it would have replaced the role table and put exec tools in every role. Deleted with the unenforced `BaseTool.allowed_roles` field and `image_search`'s copy; `DEFAULT_ROLE_MAPPINGS` is the one role table.
  - **F33:** role lists and the tier table are copied per registry instance.
  - **F35, one wiring:** the DI container gives its `tool_registry` a `wiring` callable (`Container.tool_wiring`: state repo, reranker, `ToolConfig`, per-tool constructor collaborators). The six self-resolving tools refuse with a `RuntimeError` instead of building a `Container()`, and the registry skips a tool whose collaborator does not resolve. Callers no longer repeat collaborator arguments; `mcp_scope`, which passed only `llm_port`, now gets the same collaborators. `factories.build_tools` uses the container's registry. Deleted the dead `expert_profile.py`.
  - **Tests:** `tests/unit/fixes/test_w55_tool_wiring.py` (10, failing first); the F32/F33 strict xfails are plain tests.
  - **Ceilings:** `container_construction` 31 to 25, `silent_except_handlers` 121 to 119, `bandit_b110` 59 to 58.
  - **F34, decided by deletion:** the tiers were written but never enforced. Wired as written, the gate would have removed `terminate` (privileged, operator token only) from every role and `bash`/`powershell` (restricted) from every background run, so the tier table, `get/set_tool_tier`, `get_tools_for_role_with_gate`, `CapabilityGate` and `CapabilityTier` are deleted; the guard chain (BashGuard, ExecApprovalPolicy, ADR-013 approvals) is what gates execution.
  - **Closed by decision, not code (2026-10-23):**
    - *Workspace root through `ToolConfig`:* W2.4b chose option (a), import-time constants, and `PathValidator` (`infrastructure/security/security_validators.py`) enforces the same `WORKSPACE_ROOT`. Injecting a second copy into `file_editor` alone would give the path check and the editor two sources. One value, read from settings, is the SSOT state.
    - *The name-set if/elif chains:* they pass per-call collaborators (LLM port, flow factory, sandbox, one shared browser adapter), which the per-registry `wiring` cannot hold; the per-tool constructor collaborators did move into the wiring.
  - **W5.5 DONE.**

### Wave F: model config (W6.1; F20, F18 rest)
Independent of C-E; it can go anywhere after A.
- **W6.1 DONE (2026-10-23), with the catalog refresh and a per-role value-for-money pass.**
  - **Catalog:** regenerated from OpenRouter's live list, 451 -> 460 models (+36, -27). `tests/fixtures/openrouter_models.json` refreshed in the same change. All 17 `EXTRA_MODELS` are listed by OpenRouter now, so the dict is empty (output byte-identical); their measured fields stay in `PINNED_FIELDS`.
  - **One home per model fact:** prices, context and capabilities live in the catalog; which model serves which role, task or tier lives in `model_refs.py`, ids only. Deleted: the second role table `_ROLE_MODEL_CASCADE` (it gave `planner`, `executor` and `reviewer` other models than `ROLE_MODEL_CONFIG`), the `core/model_cascade_config.py` `ModelConfig` dataclass and its hand-priced task table (now `model_refs.TASK_MODEL_CASCADE`, ids only; `estimate_cost` reads the catalog), `AGENT_CAPABILITIES.preferred_models` (routing in the domain layer; `HyperAgent` reads the role table), about 30 unused `MODEL_*` constants, `get_free_models`, `get_models_for_role_and_task`, and every token price quoted in a docstring. `task_model_router.CATEGORY_MODEL` derives from the role table through `CATEGORY_ROLE`; the sub-agent tier map is one `SUBAGENT_TIER_MODEL`.
  - **Choice:** Artificial Analysis Intelligence Index v4.3.2 (2026-10-17..23) and its per-role components against measured cost per task (research notes kept outside the repo). Executor workhorse `deepseek/deepseek-v4.1-flash`; planner and reviewer `openai/gpt-6.1-sol`; coder `anthropic/claude-sonnet-5.5`; researcher `xiaomi/mimo-v2.6-pro`; documentation `anthropic/claude-haiku-5.5`; automation `minimax/minimax-m3.1-flash`; budget `openai/gpt-6-luna`; vision `openai/gpt-5.6-luna`. Fallbacks come from other labs. Ids carry no `:thinking`: that suffix sets `reasoning_effort="max"` on every call. ACR seed profiles added for the 14 role-table models; ACR's default pool is filtered to catalog models.
  - **Dead route found:** `kwaipilot/kat-coder-pro-v2.5` left OpenRouter and was in six role cascades and the fallback chain.
  - **Tests:** `tests/unit/fixes/test_w61_model_ssot.py` (13, failing first; includes "no model-id string literal outside `model_refs`"), and `test_routed_models_exist.py` now also covers every `MODEL_*` constant, list constants included. Tests that pinned model ids now read them from `model_refs`.
  - **Not verified live:** no billed call was made. `CatalogValidator` is clean; whether DeepSeek's direct API serves `deepseek-v4.1-flash` is unchecked (the adapter falls back to OpenRouter on failure).

### Real run, 2026-10-23 (after the model refresh)
`cli.main health`, `doctor` and four `flow run` passes on a trivial task (`17 * 23`, no files). The first took 25.3 s and ended in tracebacks; the last completed cleanly in 8.5 s. Each finding got a failing test first:
- **OpenRouter credit gate always tripped.** `/auth/key` has no `credits` field (it reports `limit_remaining` in USD), so the adapter read 0 and every cascade dropped its OpenRouter-only models; the 10000 "tokens" threshold was in a unit OpenRouter does not use, and `minimax/` counted as direct though its adapter only reaches OpenRouter. Now USD (`OPENROUTER_MIN_CREDIT_USD`, default 0.10). `tests/unit/fixes/test_openrouter_credit_gate.py`.
- **Reasoning models answered nothing on short calls.** On OpenRouter `max_tokens` covers reasoning too: self-critique (100) got truncated JSON, trajectory analysis (500) an empty reply. A short call (<= 1024) that names no effort now runs at the model's lowest effort, plus 1024 tokens of headroom for a model that cannot stop reasoning (catalog-driven; it generalises the GLM-only workaround). `test_short_call_reasoning_budget.py`.
- **Health read "degraded" on every machine with an OpenRouter or xAI key.** `check_llm_ports` had no branch for them. `test_health_llm_providers.py`.
- **`flow run` died on closed stdin** (`EOFError`, "Aborted!") and **answered only the first question** (a second wait ended the command silently). It now asks every question, and on closed stdin leaves the session waiting with the resume command. `tests/unit/cli/test_flow_run_without_stdin.py`.
- **The constraint gate paused a step for restating the constraint** ("Do not create or modify any files" carried into the step). Negated clauses drop out of the token vote. `test_constraint_restated_in_step.py`.
- **MCP teardown traceback at every exit** ("exit cancel scope in a different task"): the configured MCP connections are closed by the CLI wrapper and the web shutdown (`factories.close_mcp_toolkit`). `test_mcp_toolkit_closed_on_exit.py`.
- **Raw pydantic reprs in CLI output** for CoVe checks and any unlisted event type. `test_cli_event_fallback.py`.
- **"Model: unknown, Tokens: 0" on every CQRS telemetry line**: no handler reports either; the line now gives the duration (cost per call is the LLMCallCompleted events). `test_cqrs_telemetry_line.py`.
- **Two containers per `flow run`** (two `CatalogValidator` lines; the W5.2 acceptance target is one, it was about 25 before W5.3): `flow run` and `flow retry` now use `factories.shared_container()`. `container_construction` 25 to 23. `tests/unit/cli/test_flow_one_container.py`.
- **Not fixed, noted:** `WEEBOT_CORE.md` personality file is absent; `rank_bm25` is not installed (word-overlap fallback); the OpenRouter key has a $10 limit with about $3.95 left.

- **Live probe of the role table (2026-10-23):** every one of the 16 models in `ROLE_MODEL_CONFIG` and the fallback chain made a correct tool call (`multiply(17, 23)`) through Weebot's own adapter, 0.9 to 12.1 s each. The probe found that `google/...` (and any other vendor prefix without a direct adapter, `poolside/`, `microsoft/`, ...) raised "Unknown provider" in `AdapterFactory`: a `vendor/model` id with no direct adapter now goes to OpenRouter (`tests/unit/fixes/test_adapter_factory_vendor_prefixes.py`).

- **Representative batch (2026-10-23):** eight `flow run` tasks through the real CLI (chat, Python, file read, line count, file write, web search, multi-step coding, file sizes). Seven completed correctly in 15 to 51 s each, with no tracebacks; the batch spent $0.08 of OpenRouter credit (about $0.01 per task). The coding task failed on the intent-review clarification ("is not waiting"), fixed in the same pass (`test_intent_review_pause_is_durable.py`). CoVe marked correct answers "inconsistent" and rewrote the summary on most runs. Two causes, fixed: the consistency check saw `summary[:300]`, and the summary opens with a 250+ character step description, so the result was cut off; and "the evidence does not say" answers counted as contradictions. The claim window is 2,000 characters, the evidence carries each call's arguments when the event kept them, and unverifiable answers no longer trigger a rewrite (`test_cove_claim_contains_the_result.py`). Rerun: "CoVe verification passed - no inconsistencies".

- **Representative batch, rerun on the committed fixes (2026-10-23):** the same eight tasks: 8/8 correct, every run exit 0, no tracebacks or error markers, 16 to 82 s each, $0.20 of OpenRouter credit in total. CoVe rewrote a summary on 1 of 8 runs (before: most), with unverifiable checks labelled as such. One `tool guard [observe]` line (the file-write task) feeds the W3.7 observe data.
- **Executor value-for-money check (2026-10-23):** six candidates, the same three tool-calling tasks each, real usage at catalog prices, through Weebot's adapter. All 3/3. Cost per task: `z-ai/glm-5.3-flash` $0.000005, `deepseek/deepseek-v4.1-flash` (primary) $0.000095, `minimax/minimax-m3.1-flash` $0.000104, `z-ai/glm-5.2` (previous primary) $0.000119, `xiaomi/mimo-v2.6-pro` $0.00013, `openai/gpt-6.1-sol` $0.00047. DeepSeek stays primary: GLM-5.3-Flash's OpenRouter input price is about 30x below what Artificial Analysis measured (likely promotional) and it scores lower on agentic automation (60% against 67%); these easy calls do not separate the two. Re-check that price at the next catalog refresh.

- **Per-role head-to-head (2026-10-23):** each role's routed models against alternatives on a role task, auto-graded (planner JSON plan, coder code that must pass hidden tests in an isolated subprocess, reviewer bug-spotting, researcher fact extraction from a ~35,000-character document, analyst arithmetic, documentation length and keyword limits, subagent JSON classification, vision digit reading). Every text candidate passed; these tasks are too easy to separate quality, so they confirm that the routed models work and show cost per task. Primaries cost: planner $0.0019, coder $0.0025, reviewer $0.00037, researcher $0.0053, analyst $0.00031, documentation $0.000025, subagent $0.000016, vision $0.000026. Cheaper candidates also passed (DeepSeek V4.1 Flash for reviewer and analyst at about a tenth of the primary's cost; Haiku 5.5 for researcher at about a quarter), which is worth a harder eval before moving those roles down a tier. Vision failed for every model at first: `_multimodal.convert_messages` turned OpenAI-native `image_url` blocks into "[unsupported content block]" text, so `osworld/agent_adapter.py`'s screenshots never reached a model. Fixed (native blocks pass through; data URLs mapped for Anthropic); then 4/4 (`tests/unit/test_llm_multimodal.py`).

- **DeepSeek direct, first live check (2026-10-23):** with `DEEPSEEK_API_KEY` in `.env`, DeepSeek-direct was never used. The key lives in settings, not `os.environ`, so `DeepSeekAdapter` fell back to `"no-key"`. The factory also passed the caller's `api_key`, which is the OpenRouter key, so every call went silently to OpenRouter. Moonshot had the same bug. Both branches now resolve their own key with `_resolve_direct_key`, as the xAI branch does (`tests/unit/test_adapter_factory_credentials.py`). The key is valid (the model list works), but the DeepSeek account answers `402 Insufficient Balance` for every model, so calls fall back to OpenRouter until the account is topped up. Open: the direct API lists only `deepseek-flash` and `deepseek-v4-pro`, so `deepseek-v4.1-flash` may need an id mapping once there is balance to test it. `DeepSeekAdapter` also forces thinking with `reasoning_effort="high"` on every call, short calls included, which is worth measuring then.
- **Kimi and OpenAI direct (2026-10-23):** Kimi-direct works through the factory after the same fix: `kimi-k2.6`, `kimi-k2.7-code`, `kimi-k2.7-code-highspeed` and `kimi-k3` all answer correctly in 1 to 2.5 s, and the response names the bare model, so it was not OpenRouter. No routed role uses a `moonshotai/` model today, so this matters only for picks made elsewhere (personas, the ACR pool). The OpenAI key is valid (133 models listed), but the account answers `429 You have no credits remaining`. `openai/` ids route through OpenRouter by design (`_infer_provider_from_model_name`), so routed roles are unaffected. The only code that prefers `OPENAI_API_KEY` is the deprecated `core/tool_agent.py`, which has no live callers.

- **B3 observe batch (2026-10-23):** 12 flow runs that use shell, Python and file tools, every write under `Output/observe/`. All 12 exited 0 and 11 gave the expected answer; $0.23 of OpenRouter credit. With the 16 earlier runs that makes 28, against the 20 of decision B.
  - Guard lines, all runs together: 7, every one `exec_approval_policy=ASK`. Zero DENY, zero from any other guard. By command: `Set-Content` 5, `Move-Item` 1, `Remove-Item` 1. Every one targeted a file the run itself created under `Output/`.
  - So all 7 are false positives. The `Output\` carve-out in `core/approval_policy.py` covers only `Remove-Item` with an absolute drive path and Python `open(..., "w")`. A relative `Output/...` path, or `Set-Content` / `Move-Item`, falls through to the blanket ASK rules.
  - Observe is not "nothing refused" today: the `bash` tool's own gate already refuses these commands ("Command blocked — requires user confirmation"), with no way to approve. The agent then did the same write through `file_editor` or `python_execute`, which the shell policy never sees. Enforce would turn those refusals into one or two approval prompts per file-writing task.
  - Before the flip: widen the carve-out (test first) to the write/move/remove cmdlets on paths inside `Output/`, relative or absolute. Otherwise enforce mostly adds prompts that a human will always answer yes.
  - Found on the way: answering the intent-review question ended the run after planning (exit 0, nothing done). `FlowRouter.resolve_initial_state` returned `PlanningState` with the session still WAITING, and the run loop breaks on WAITING. Fixed (`tests/unit/application/flows/test_intent_answer_resumes_planning.py`); the live rerun went intent question, plan review, execution, Done.
- **Harder per-role eval (2026-10-23):** 16 harder tasks (coding against hidden edge-case tests, subtle bug spotting including SQL injection, multi-step arithmetic, a long document with a superseded value and a two-hop fact, constrained JSON plans and a dependency order). Every candidate passed every task again: DeepSeek V4.1 Flash, Haiku 5.5 and MiMo V2.6 Pro alongside each primary. Single-turn tasks do not separate these models, so they give no evidence for moving a role; the routing stays on the Artificial Analysis picks. Separating them needs multi-turn agentic tasks (tool use over several steps), which the flow-run batches cover only as pass/fail.

- **Output/ carve-out widened (2026-10-23):** done, test first (`tests/unit/core/test_output_carve_out.py`). `ExecApprovalPolicy` now auto-approves Set-/Add-Content, Out-File, Clear-Content and New-/Remove-/Move-/Copy-/Rename-Item when every path argument lies under the workspace's `Output/`. It fails closed on `..`, on any `$` variable not resolved below, on unknown parameters, on a user rule that matches, and on any DENY. A variable assigned once, to a plain string literal, in the same command (`$dir = "...\Output\x"; Set-Content "$dir\a.txt" ...`, the shape the agent really writes) is substituted before judging. The old `Remove-Item` regex matched `\Output\` on any drive (`C:\Windows\Output\x` auto-approved); it is gone. Live rerun of the four file-writing tasks: 4/4 correct, 0 guard lines (before: 4 to 7 false ASKs). The W3.7 flip itself still waits for the user.
- **Executor cascade hedges instead of racing (2026-10-23):** Phase 1 started every probe at once; a non-streamed request cancelled client-side still bills (measured: a MiMo V2.6 Pro call cancelled at 3 s cost the full $0.0068), so each executor call paid for three models (live: 12 requests for 4 calls). One probe now runs; the next starts on failure or after 20 s. Live: 2 requests for 2 calls. The credit check before each call now reuses a `/auth/key` answer for 60 s instead of a round trip per call.
- **OpenRouter best-practice audit (2026-10-23):** against the prompt-caching, spend-controls, reasoning-tokens and web-search guides. Open, ranked: Anthropic prompt caching never fires (flag off by default, model markers predate Claude 4.x/5.x, wrapper chosen per factory model not per call, breakpoints at message level); the ledger ignores cached and reasoning tokens and `usage.cost`; executor calls set no reasoning effort, and a reasoning-exhausted empty reply is treated as a failure and bought again from the next model; `web_search` runs Perplexity, DuckDuckGo and Bing in series on every call and bills Sonar outside the ledger (`openrouter:web_search` with `engine:"parallel"` is $0.001 a search); no `session_id` for provider stickiness; cache telemetry reads `input_tokens` where the adapter emits `prompt_tokens`.
- **W3.7 flipped (2026-10-23):** `shell_guard_mode` defaults to `enforce`, on the user's go; the F01 strict-xfail is a plain test. A 12-task batch under enforce: 11/11 checkable tasks correct. An ASK with no TTY is refused, and the agent finds another route.
- **Executor VFM, multi-step and billed (2026-10-23):** 8 real CLI tasks with the executor pinned per model; every model 8/8. At catalog prices Haiku 5.5 looked cheapest ($0.074, against DeepSeek $0.107, MiniMax $0.190, MiMo Pro $0.208 or more), but the catalog prices DeepSeek at its most expensive provider. A billed A/B on the same 3 tasks settled it: DeepSeek V4.1 Flash $0.020 in 74 s, Haiku 5.5 $0.042 in 110 s. The executor primary stays DeepSeek.
- **Claude models (2026-10-23, user rule):** only Opus, Sonnet and Haiku 5.5; never Fable. `claude_model_allowed()` in `model_refs` is the check. The cascade's live rescue (which picked the largest-context paid model, possibly a Fable model) and the ACR pool filter through it.
- **50 common agent uses (2026-10-23):** compiled from the Anthropic Economic Index, LangChain's State of AI Agents and the NBER ChatGPT-usage paper, then product categories. 45 run as live CLI tasks, each graded on the file it had to write. The other 5: inbox triage, CRM or ticket updates and purchases need accounts (purchases are prohibited), and image generation is billed. Result: 45/45 correct, median 34 s. Fixed on the way:
  - OCR fell back to nothing without Tesseract; it now uses the vision model and takes an image path.
  - `build_mediator` and the sub-agent factory built unwired tool registries, so knowledge, audit, memory, voice and OCR-vision were missing from those tool sets.
  - A refused inline script now names `python_execute`, and the bash and powershell descriptions say so up front.
  - Open: 12 of 45 runs lost time to refused ASKs (8 inline `python -c`, 8 `exec_approval_policy`). Three false DENYs: "nested backtick injection" on markdown code spans written through the shell; that is a security-analyzer change left for review.
- **Refusal rerun (2026-10-23):** the 12 tasks that had hit a refused ASK, rerun with the inline-Python steering: runs with refusals went from 12 to 7, refusals from 13 to 8, and inline-script refusals from 8 to 3. 11 of 12 passed. The one fail was a real bug: PowerShell 5.1 wrote piped output in the console code page while the sandbox decodes UTF-8, so "12°C" reached the agent as "12A�C". Fixed (`[Console]::OutputEncoding` set to UTF-8; `tests/unit/infrastructure/sandbox/test_powershell_utf8_output.py`).
- **Catalog refresh (2026-10-23):** 460 models, no membership change. Three prices moved, among them DeepSeek V4.1 Flash at its most expensive provider ($0.30/$1.20 per M).
- **Direct providers, funded (2026-10-23):**
  - **DeepSeek-direct now works.** The API serves only the aliases `deepseek-flash` and `deepseek-v4-pro` and rejected `deepseek-v4.1-flash` with 400, so every direct call fell back to OpenRouter. `native_model_id()` maps the id. Live: plain and tool calls served by `deepseek-flash` in about 1 s.
  - **OpenAI-direct works for luna models.** The factory's `openai` and `anthropic` branches read keys from `os.environ` only and sent "no-key"; both now use `_resolve_direct_key`. Direct OpenAI rejects `max_tokens` (it wants `max_completion_tokens`), and rejects tools with a reasoning effort on models where reasoning is optional. Both are handled, and the catalog spec resolves for bare ids. Live: `gpt-6-luna` and `gpt-5.6-luna` answer plain and tool calls.
  - **Limit:** `gpt-6.1-sol` cannot take tools on `/v1/chat/completions` at all; it needs the Responses API. Roles use `openai/` ids through OpenRouter, where Sol's tool calls work, so routing is unaffected.
- **Executor model is now `deepseek/deepseek-v4.1-flash-1017` (2026-10-23, user pick):** half the max-provider price of `deepseek-v4.1-flash` ($0.15/$0.60 against $0.30/$1.20 per M). `MODEL_CASCADE_TIER1` and its quality profile moved; it is in the ACR pool. Via OpenRouter it answers as itself; DeepSeek-direct serves it as the `deepseek-flash` alias, which the user confirmed is the 1017 snapshot.
- **Per-role VFM, hard tasks, billed (2026-10-23):** 23 hard auto-graded tasks, priced from OpenRouter's own `usage.cost`: coder algorithms against hidden edge-case tests, subtle bugs for the reviewer, competition-style arithmetic for the analyst, long-document counting and multi-hop for the researcher, a 10-node dependency order and constrained JSON for the planner. About $0.27 spent.
  - **analyst:** the primary, GPT-6.1 Sol, is the only one at 6/6 (Haiku 5.5 and DeepSeek 1017 5/6). It stays.
  - **coder:** all 6/6; Haiku 5.5 at $0.0027 against Sonnet 5.5 at $0.048 (18x) and faster.
  - **reviewer:** all 6/6; Haiku at $0.0003 against Sol at $0.0033 (12x).
  - **researcher:** all 3/3; Haiku at $0.0056 against MiMo Pro at $0.019 (3.4x), 3.6x faster.
  - **planner:** all 2/2; Haiku at $0.0002 against Sol at $0.0019 (10x).
  - These are single-turn tasks; multi-step tool loops differ (there DeepSeek beat Haiku on billed cost). Moving coder, reviewer, researcher and planner to Haiku is the user's call.
- **Routing applied (2026-10-23):** planner, coder and researcher primaries moved to Haiku 5.5, each with the previous primary as fallback 1. The analyst stays on GPT-6.1 Sol. The reviewer stays on Sol so that it comes from a different lab than the Anthropic coder and the DeepSeek executor. Step execution is unchanged: since the hedge, the role primary (DeepSeek 1017) goes first and category models are fallbacks. The 45-task regression check passed 45/45. Fixed on the way:
  - DeepSeek-direct forced high-effort thinking on every call: a planning call took 3.8 s, against 1.4 s without thinking and 2.6 s via OpenRouter. It now thinks only when an effort is requested; planning median went back from 3.8 s to 2.4 s.
  - A REVISE from the code reviewer changed only the in-memory plan. `ExecuteStepHandler` reads the saved plan, so it refused the re-run ("already completed") and every REVISE was dropped. The revised plan is now persisted as a PlanEvent; live, the reviewer's fix to an invented-data CSV re-ran and the task passed.
- **Image generation (2026-10-23):** use 28 of the 50, now tested. `image_gen` with `kind="openrouter"` produced a correct 1024x1024 red-circle PNG via `x-ai/grok-imagine-image-quality`. Asked in plain words through the CLI, the agent drew it with PIL instead, which also met the task.
  - The last three, as local stand-ins (no account, no connector, no money), all passed live:
    - **Inbox triage:** 4 `.eml` files classified as urgent, spam and normal, written to `triage.json`.
    - **Ticket updates:** a JSON tracker edited as asked, with the untouched ticket left byte-identical.
    - **Shop checkout:** a local HTML shop driven through the browser tool; two items added, the form filled, total 15.50, stopped before payment.
  - The real-account versions (an `@atomicmail.ai` inbox, a Jira or HubSpot connector) still need the user. Real purchases stay prohibited.
- **Multi-step role checks, billed (2026-10-23):** real CLI tasks with the step model pinned.
  - **Coder:** Sonnet 5.5 went 3/3 and Haiku 5.5 2/3; on the word-wrap task Haiku rewrote the input sentence instead of wrapping it. The coder stays on Sonnet. The cost runs overlapped, but Sonnet billed several times more.
  - **Researcher:** Haiku $0.062 in 118 s and MiMo V2.6 Pro $0.055 in 205 s, both 2/2. Haiku stays first, 1.7x faster at about the same cost.
- **Mail and Jira (2026-10-23):**
  - **Mail:** the agent inbox is `weebot@atomicmail.ai`, readable live.
  - **Jira:** connected via `uvx mcp-atlassian` in `config/mcp_servers.json` (63 tools, read-only project listing works; the site has no projects yet).
  - **HubSpot:** connected via `npx @hubspot/mcp-server` (21 tools; read-only `hubspot_get_user_details` works). Writes ask first; no write test run yet.
  - **Apify:** built-in preset tools turn on with `APIFY_API_KEY`; the official MCP server (`mcp.apify.com`) is added once that key is in `.env`.
- **Reviewer moved to Haiku 5.5 (2026-10-23):** for value for money; it tied Sol 6/6 on the billed subtle-bug eval at about 1/12 the cost. Sol is fallback 1. Live: the `code_reviewer` caught an off-by-one and the empty-list case in 2.3 s (timeout 8 s). Test: `tests/unit/config/test_reviewer_routing.py`, failing first. The analyst stays on Sol, the only 6/6 there.
- **Decision models (2026-10-23):** where a decision API such as Perplexity Decisions could replace chat calls: [tasks/audits/decision_models_2026_10_23.md](audits/decision_models_2026_10_23.md). Not adopted; no key or A/B yet.

### SSOT pass (2026-10-23)
User request: "Make sure the ssot principal holds in the project". Audit and per-row status: `tasks/audits/ssot_audit_2026_10_23.md`. Every row is done or deferred with its reason; none open. Deferred: 12 (agree at runtime), 14 (tools differ on purpose), 20 (name collision, not a duplicated fact), parts of 9, 16, 24, 25, 29. `WEEBOT_VISION_REFLECTION` now defaults off (it doubled image tokens); `=1` turns it on.

### Wave G (optional): map the uncovered clusters
Cards for the other tools, interfaces, browser and domain clusters, following `map/_meta/schema.md`. Each defect found becomes a new F row and a task here. Size depends on how many clusters you want covered.
- **Done 2026-10-23:** 21 new cards (domain 5, SkillRegistry, interfaces 5, browser 2, tools 8), every `_index.md` line now links a card; `RoleBasedToolRegistry.md` marked stale (line drift). Findings F38-F79 in `tasks/icm_fix_plan.md`. Every H row is fixed, each with a failing test first: F38 `89d20bd9`, F39 `009cb41a`, F40 `138b033c`, F41 `d1b43463`, F42 `a409e2c9`, F43 `3abcb31e`, F44 `900a1b6d`, F45 `0dacf422`, F46 `7cddbca6`. M rows fixed the same way: F47-F53, F57, F59, F60, F63, F64, F66-F68, F70, F71, F73-F75, F78, and F76's attachment half (hashes in the F table). Also fixed: `SkillCurator.detect_overlaps` always returned [] (`54dc93fb`). Later the same day: F55/F56 (`ce4f82fd`, `a4c81d54`), F58 (`eb646fe3`), F61 (`935aee50`), F62 (`af06f447`), F65 (`c2265eeb`), F69 (`e28a5015`), F72 (`f9f68bb7`), F76 email sender (`9b94e943`), F77 cron/cancel/retry (`2ac3672c`, `5c574b1b`). Open: F54 (whether paid tools ask each time: the user's call) and cross-process cancel of a CLI run (design: the flow would watch a stored flag). L rows (F79) are notes in the cards.

## Parallel work
C, D (after W4.2) and F touch separate files from B and can run in their own sessions. E overlaps B in DI and the registry, so it runs after B1 and B2. The B3 observe window keeps running throughout.

## Decisions needed

**DECIDED 2026-10-22: A-D as recommended** (user: "Accept the recommended answers to decisions A-D and start Wave A").

A. **Stripe test (A3):** remove its module reload so it stops leaking a second settings module? It stays the `.env` check. Recommended: yes.
B. **Observe period before the W3.7 flip:** the original plan said two weeks.
   - Option 1: two weeks of normal use.
   - Option 2: a fixed set of about 20 representative tasks, then flip.
   - Recommended: option 2, since there is little traffic today.
C. **`weebot-ui` renderer for `tool_approval`:** today the generic `WaitForUserEvent` carries the prompt, which works. Recommended: no, until the UI is reworked.
D. **Wave G in scope?** Recommended: after Wave E, one cluster at a time, starting with the tools that have no card.

## Size

A: about 1 session. B (without the B3 wait): 2-3. C+D: 2. E: 5+, the largest. F: 1. G: open-ended.
