---
status: reference
date: 2026-10-29
supersedes: plans/d4_wiring_research_2026_10_27.md
note: what wiring every G8 and G9 module would take, re-checked at dc16cf13 after the learning loops landed; three read-only agents, five claims spot-checked
---

# D4 research: what it takes to wire up all of G8 and G9

Decision D4 of `tasks/plans/audit_2026_10_27_fix_plan.md` asks what happens to groups G8 and G9. The owner asked what it would take to wire everything up instead of deleting it. Three read-only agents (G8, G9 adapters, G9 verifiers) mapped every module at commit dc16cf13, after the learning-loops merge (a24e05ec). This note replaces the 2026-10-27 note, which was written before that merge.

How far to trust it: each agent built an import graph and grepped for string, YAML and registry references. Five claims were re-checked by hand and held: the `progress_gate` hook reads `_step_evaluator` (`_step_outcome.py:242-244`); chain of verification turns unparseable output into "no inconsistencies" (`chain_of_verification.py:141`); benchmark profiles replace seed profiles whole (`capability_profiles.py:70`); `self_improver` checks paths with `startswith` (`self_improver.py:265,271`); the Windows sandbox decodes output as UTF-8 (`native_windows.py:388-389`). Nothing else was run against a live model, network or database. The D4 decision itself is still open.

## The short answer

"Wire everything" is not one job. The modules fall into four kinds:

1. **Wireable now, small:** a hook already exists or one registration is missing.
2. **Wireable after fixes:** the module is broken, so wiring means repair, hook and tests.
3. **Needs something that does not exist yet:** a producer, a second process, a database, an account or a design decision.
4. **Should not be wired:** it duplicates live code, or wiring it would weaken security. For some of these, a few unique rules can be moved into the live code.

Rough total if everything in kinds 1-3 is done: several weeks of work, two new external services (Valkey, Postgres), one paid account (Modal), and new per-run model calls. Kind 1 alone is a few days.

## Already live, so not part of D4

The learning loops wired most of what the old note discussed:

- live use counting promotes skills (`validation_handler.py:140-175`), and `skill_promotion_check` is now a retired job (`config/jobs.yaml:6-11`);
- the model router, `posterior_repository`, `evaluator_selector`, `HarnessOptFlow`, `SkillOptFlow`, `MemoryCompactor`, the executor's `ContextCompressor`, `VerifyingState`'s own chain of verification, and `RegressionGate`.

## Kind 1: wireable now, small

| Module | Hook | Fix first | Flag | Cost per run | Effort |
|---|---|---|---|---|---|
| `step_evaluator` (129 + port) | The consumer is live: `progress_gate` at `_step_outcome.py:242`, set at `_plan_act_wiring.py:138`. Register `step_evaluator` in `di/__init__.py` after :199 with the verifier model, and pass it in `flow_builder.py` after :178. | `step_evaluator.py:102` parses JSON without stripping code fences, so a fenced reply fails open. The not-passed branch (`_step_outcome.py:276-283`) skips `record_skill_uses(passed=False)`, and `previous_outputs` is oldest-first while the prompt says newest-first. | new `WEEBOT_STEP_EVALUATOR`, off at first | 1 verifier call per step | S |
| `EvalRunner` and judges (about 375) | An optional `--judge` on `harness baseline` (`cli/commands/harness.py:338-380`), which today scores completion only. | `judges.py:76` has the same fence bug. `eval_runner.py:109-113` judges a task after an execution error. Per-criterion averages are on 0-10 while the overall score is 0-1. | CLI option | 1 judge call per task | S-M |
| `platform_encoding.safe_decode` (35) | `native_windows.py:388-389`, `wsl2.py:185-186`, `docker_linux.py:333-334`. These hard-code UTF-8, so CP-1252 PowerShell output is mangled. | none | none | none | S |
| Windows toast subscriber (`interfaces/windows_toast_subscriber.py`) | `bus.subscribe(sub.on_event)` at the web composition root, near `web/main.py:218`. It is the only toast path; the whole `infrastructure/notifications/` package has no other caller. | Sanitize credentials in the error text it shows. | new `WEEBOT_WINDOWS_TOAST`, off | none | S |
| OpenRouter speech adapter (106) | `_create_speech` (`_factories.py:93-96`), chosen by flag. Today's whisper adapter needs `openai-whisper` and `pyttsx3`, which are not in requirements, so voice tools are inert. | `os.getenv` at :27 must become `SecretAccessor`. TTS returns mp3, but `voice_output_tool.py:81,91` writes `.wav`. Not verified: that OpenRouter serves the audio endpoints. Audio leaves the machine. | new `WEEBOT_SPEECH_BACKEND`, default whisper | per use | S-M |

## Moving rules into the live security gates (instead of wiring the validators)

The live guard chain (`tool_guards.py:373-391`) allowed these when measured. The old validators that catch them would also block ordinary commands, so move only the rules:

- `powershell -ExecutionPolicy Bypass` and `-ep bypass`: ASK in the approval policy.
- `eval $VAR`: DANGEROUS or ASK in BashGuard.
- `cipher /w:` and `cacls ... /grant everyone:f`: add to the approval policy or BashGuard.
- `state_verifier`'s file-content comparison and delete confirmation: add them to `StepEvidenceAuditor` (`step_evidence_auditor.py:102-158`) through `FileStoragePort`.

Leave out `CommandValidator`'s rule against `$()` and backticks. It would refuse commands like `echo $(date +%s)` and `docker run -v $(pwd):/app`. Leave out its Python rules too: they flag `re.compile(` and `import sys`.

Each rule needs a failing test first. `tests/unit/security/test_dormant_gates_fail_closed.py:255-310` checks that these classes have no caller, and stays as it is while only rules move. Effort: S in total.

## Kind 2: wireable after fixes

- **Chain of verification** (281). Fix first:
  - :141 turns unparseable output into "verified", with the garbage as the corrected text;
  - `CoVeResult` has no score.

  It duplicates `VerifyingState` (`verifying.py:43`). Wiring it means moving `VerifyingState` onto the service (M). Its only other consumer is the promotion gate. It costs up to 7 calls. The dormant-gates test pins it as uncalled.
- **Skill promotion gate** (110), as a veto only. Hook: an optional gate in `RecordSkillUseHandler` at `validation_handler.py:161`. When the gate fails, the skill stays a candidate. Cache the verdict. Register it in `di/_learning.py` next to `skill_review_gate`. Fix first:
  - :69 reads `.score`, which is always 0;
  - :84 awaits a scorer that is a synchronous class method taking a `Session`;
  - decide what "unverifiable" means for procedural skills.

  Needs the chain-of-verification fixes. New `WEEBOT_SKILL_PROMOTION_GATE`, off. About 7 calls per promotion. M.
- **Comparison runner** (185): A/B runs with and without a skill. This is a better promotion signal than chain of verification. Needs a `skill_names` parameter on `create_flow`. 2 full runs per prompt. M-L.
- **Benchmark runner** (about 410): the missing producer for model quality profiles; `save_benchmark_profile` (`capability_profiles.py:135`) has no caller. Hook: a `models benchmark-model <id>` CLI command, with a cost guard (default $0.50). Fix first:
  - :70 must merge per axis, or a benchmark erases the seeded legal, citation and planning axes;
  - `_BENCHMARK_PATH` (:27) writes inside the package.

  M.
- **Code quality signal** (141): hook at `cli/commands/harness.py:275`. Fix first, and this is a bug in live code: `harness_opt_flow.py:293` counts a task as passed whenever `flow.run()` does not raise. `PlanActFlow` reports failure through events, so the regression gate sees almost no failures. S after the fix.
- **Staged evaluator** (99): a cheap probe stage before the full run in `validation_runner.py:117-135`. No bugs, no tests. M.
- **Summary repository** (78): register `SummaryRepositoryPort` at `_capabilities.py:33-37`. Missing:
  - a producer (`CompletedState`) and a consumer (planning);
  - `delete_by_session_id` for the session-delete cascade (`web/dependencies.py:29-40`);
  - a path under the data directory instead of `./weebot_summaries.db`;
  - embeddings gated on `LocalEmbeddings.is_available()`.

  New `WEEBOT_EPISODIC_SUMMARIES`, off. M.
- **Scorers** (exact match, execution, verifier; about 276): `ScoringPort` is bound to `PlanOutcomeScorer` (`di/__init__.py:226`), and no caller supplies a gold answer, so each returns a constant. Needs a keyed scorer registry and the harness runner passing gold answers. They overlap `harness/scorer.py`. M, low value.
- **Checkpoint store and scheduler**: half wired. `flow._checkpoint_port` is set (`_plan_act_wiring.py:147`) and never read, there is no `CheckpointPort` in DI and nothing calls `load()`. To wire it:
  - add a purge to `_session_stores` first; the deletion-wiring test enforces this;
  - fill the summary and iteration count, which the scheduler writes blank;
  - call `_ensure_schema` or run outside alembic, since CLI runs never run alembic;
  - build a resume reader.

  It duplicates session persistence. M-L.
- **`broker_adapter`** (100): `subscribe` calls `subscribe_by_type`, which only `AsyncEventBus` has, and events without a session id broadcast to every WebSocket client. The orchestrator has no publisher parameter. S-M, low value.

## Kind 3: needs something that does not exist yet

- **Valkey event bus** (about 285). Needs:
  - serialization and a type registry; the event union lacks `SessionStalenessEvent`, `MemoryPressureEvent`, `ScheduledJobEvent` and `LLMHealthEvent`, and 17 domain events need rebuilding;
  - origin ids so a process ignores its own messages;
  - a reader task with reconnect;
  - a journaling decision;
  - a `WEEBOT_EVENT_BUS` switch, where today the URL alone decides;
  - a running Valkey, which is in compose but given no URL.

  No second process needs it today: compose runs one API replica, and gateways run in the web process. L, high risk. Side finding: `redis_task_queue.py:87` imports `redis`, which is not pinned, so `WEEBOT_QUEUE_BACKEND=redis` fails at import.
- **Postgres knowledge graph** (about 306): only inside a Postgres phase, and the whole Postgres backend is broken first:
  - `_ensure_schema` is never called, here or in `postgresql/state_repo.py`;
  - there is no `delete_by_session_id` or session column, so deleting data would silently break;
  - there is no JSONB codec;
  - `get_stats` returns raw records;
  - the default DSN has `weebot:weebot` credentials;
  - no Postgres service exists.

  L, high risk.
- **Modal sandbox** (198): a stub that runs local `docker run` without the hardening. Needs a real `modal.Sandbox` implementation, the `modal` package and a paid account. L, high risk (remote code execution, cost).
- **`self_improver`** (about 550 with its port and model): needs a proposer and a human approval gate. Fix first:
  - path checks pass `../` and `builtin_evil`;
  - `validate_patch` scores the unpatched file;
  - the allowlist includes its own evaluation set.

  Do not build without a design decision.
- **`strategy_transfer` and `strategy_store`** (about 310): the consumer would be `planning.py:216-226`, but nothing records strategies and there is no domain concept at planning time. L.
- **`harness_profile_resolver`, `regression_suite`, `meta_improvement_log`**: no data, no fixtures and no writer. Wiring them does nothing.

## Kind 4: do not wire

- **Duplicate live code:**
  - `skill_variant_store` and `parent_selector` duplicate `SkillArchive` and `ThompsonSampler`;
  - `lossy_context_compressor` and `context_manager` duplicate `ConversationCompressor`, and they truncate instead of summarizing;
  - the two layer agents duplicate `HarnessOptFlow._propose_edits` and use a `HarnessEdit` type that collides with the real one;
  - the SSE event subscriber duplicates `web/routers/sse.py`;
  - `mcp_tool_bridge` duplicates `MCPToolRegistryBridge`, and is broken: it calls `call_tool` with un-namespaced names.
- **Security:**
  - `identity_verifier`: the caller asserts every identity field, so wiring it adds an allow path;
  - `state_verifier` as a class: its network check is an unguarded GET of an agent-supplied URL, which bypasses EgressGuard (SSRF);
  - `CommandValidator` and `tools/validation.py` as whole gates: take their rules as above instead;
  - `tools/secure_output.py`: it adds nothing over `mkstemp`.
- **No client:**
  - `legacy_project_adapter`: the `StateManager` it mimics does not exist;
  - `_adapter_base`: Playwright has its own lock;
  - also unreferenced: `clawhub_adapter`, `agentskills_index`, `non_streaming_llm_adapter`, `atomicmail/cli.py` and `document/preflight.py`.

## Order if the owner chooses to wire

1. Kind 1 and the rule moves. These are independent, take a few days, and need no new services.
2. The live harness pass-detection bug (`harness_opt_flow.py:293`), then the code quality signal.
3. Chain-of-verification fixes, then the promotion veto (or the comparison runner instead).
4. Benchmark command with the per-axis merge, then the staged evaluator.
5. Summary repository, scorers and checkpoints, each with its producer or reader and its deletion purge.
6. Event-bus groundwork (`subscribe_by_type` on the port, the four missing events, session ids on workflow events), then Valkey only when a second process exists.
7. Postgres and Modal only as their own projects.

## Whatever is decided

- `docs/SECURITY_MODULE.md:168`, and the matching text at `:16-19` and `:201-223`, claim `BashTool` runs `state_verifier`. It does not.
- `tests/unit/security/test_dormant_gates_fail_closed.py` pins four classes as uncalled; wiring any of them edits it.
