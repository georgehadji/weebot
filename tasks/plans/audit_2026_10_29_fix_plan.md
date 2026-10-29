---
status: open
date: 2026-10-29
note: plan for the 24 findings of the 2026-10-29 whole-repo audit (R01-R20 numbered in the report, R21-R24 the four smaller ones it named); five waves, injection boundary first; owner decided 2026-10-29: D-R1 and D-R3 as recommended, D-R2 option A (planner uses its configured models); wave 1 started on fix/audit-2026-10-29
---

# Plan: fix the findings of the 2026-10-29 whole-repo audit

## 1. Context

The 2026-10-29 audit (ponytail audit, run on `feat/free-providers`) re-checked the 2026-10-27 findings and hunted for new ones. Of the 23 open items it re-checked from the earlier audit, 19 were fixed and 4 were partly fixed (A17, A22, A23 and A27; still tracked in `audit_2026_10_27_fix_plan.md`). It found 20 new problems, numbered 1 to 20 in the report, and named four smaller ones. This plan covers all 24:

| ID | Finding | Area | Severity |
|---|---|---|---|
| R01 | A destructive command on a new line after an `Output\` write runs without approval | shell approval | must |
| R02 | Atomic mail sends escape the egress gate through `$VAR` substitution | egress | must |
| R03 | Store-mode auth stamps sessions `"anonymous"`; owners get 404, all principals share one owner | web auth | must |
| R04 | DELETE of a running session does not stop it; the flow re-inserts the row | web, task runner | must |
| R05 | Gateways and `/api/webhook/run` never tear down tools (Chromium leak per message) | gateways | must |
| R06 | A run with UNVERIFIED or never-run steps ends COMPLETED | flow | must |
| R07 | "I cannot ..." replies are rewritten to "Step completed" | executor | must |
| R08 | `screen_capture` writes its PNG to any path | tools | must |
| R09 | Discord runs the whole flow before answering, so every real interaction times out | gateways | must |
| R10 | Telegram and Signal poll loops spin on API errors | gateways | must |
| R11 | `OpenRouterAdapter` skips the parent constructor; every 429 becomes `AttributeError` | LLM adapters | should |
| R12 | PowerShell non-zero exit with empty stderr is reported as success | tools | should |
| R13 | `file_editor write_large` creates scripts; `str_replace` with empty `old_str` prepends | tools | should |
| R14 | `image_gen` / `video_gen` can overwrite `.env` or source under cwd | tools | should |
| R15 | The approval prompt shows only the first 500 characters, and no arguments for non-shell tools | approval | should |
| R16 | TaskRunner keeps flow factories and retry counts for every session forever | task runner | should |
| R17 | The planner ignores its model (role config and `--model`) | planner | should |
| R18 | Rate-limit tiers ignore the HTTP method (reads charged as mutations) | web | should |
| R19 | Active-session and chat-history counts are always 0 | web read side | nice |
| R20 | `/sessions/{id}/input` drops the session's ponytail mode and model | web | nice |
| R21 | `/what's up` crashes the gateway command parser (unbalanced quote in `shlex.split`) | gateways | small |
| R22 | Behavior reports return 500 on empty days; the date path parameter can escape the ledger directory | web | small |
| R23 | The first 12 characters of the API key are logged on auth errors | LLM adapters | small |
| R24 | A fuzzy-matched tool name dispatches to a tool whose egress check never ran | tool dispatch | small |

The intended outcome:

- every finding is closed by a test that failed first;
- the shared mechanism that let each class of bug happen is fixed once, not per call site;
- a fitness test stops the most likely recurrences.

## 2. Ground rules

- **Branch:** `fix/audit-2026-10-29`, cut from `feat/free-providers` (it builds on the unpushed D4 and free-provider work). Merge order: `feat/wave6-lean`, then `feat/d4-wiring`, then `feat/free-providers`, then this branch. Nothing is pushed until the owner asks.
- **One commit per finding.** Where one mechanism closes several findings (R08 + R13 + R14), it is one commit with one test file per finding.
- **A failing test comes first** for every behaviour. Security fixes also keep a table-driven negative list (calls that must stay allowed), so a fix cannot pass by blocking everything.
- **Layers** (`.importlinter`, `tests/unit/test_architecture_fitness.py`):
  - `domain` stays pure;
  - `core` imports neither `application` nor `infrastructure`;
  - new cross-layer needs go through ports and DI;
  - no new `ignore_imports`, no new string DI keys.
- **Size limits:** `application/` files stay at or under 800 lines (`test_god_modules_under_800_lines`).
  - Near the limit: `_cascade.py` 800, `executor/_base.py` 773, `task_runner.py` 626.
  - `core/approval_policy.py` is 795 lines. It is not under that test, but R01 moves code out of it rather than into it.
- **Ratchets** (`tasks/quality/ceilings.toml`): never raise a ceiling; lower it when debt is paid. Use `SecretAccessor`, `logger` (not `print`), and log in every `except`.
- **After each finding:**
  - run the touched tests;
  - run `scripts/prepush_gates.py --skip test` (all gates);
  - run `check_map_citations.py --drift`;
  - restamp the map cards the change hits.
- **After each wave:** the full suite in the scratch worktree, in the background.

## 3. Order, and why

Five waves:

- **Waves 1 and 2** go first because they are the trust boundaries. Booby-trapped content reaches the tools through the model; untrusted callers reach the API. Those bugs cause damage that cannot be undone: deleted files, sent mail, data shown to the wrong user.
- **Wave 3** makes outcomes truthful. It comes before the resource and feature work because later checks (tests, live runs) depend on failures being reported as failures.
- **Wave 4** fixes leaks and gateway behaviour. **Wave 5** fixes feature correctness.

Within a wave, a finding that builds a shared helper comes before the findings that reuse it.

| Wave | Order | Why this position |
|---|---|---|
| 1. Injection boundary | R01, R24, R02, R08+R13+R14, R15, R23 | Each lets injected content act without the owner. R24 before R02, because R02's test needs the canonical tool name to reach the egress check. R15 after the write policy, because the prompt then names the real target path. |
| 2. Web trust and integrity | R03, R22, R04, R18 | R03 first: R04 and R18 depend on a verified principal (R18's bucket key, and R04's ownership check before a cancel). |
| 3. Truthful outcomes | R11, R12, R07, R06 | Inputs first: correct LLM errors (R11) and tool errors (R12), then the step result (R07), then the run outcome that consumes step statuses (R06). |
| 4. Resource lifetime and gateways | R05, R09, R10+R21, R16 | R05 builds the owned-flow helper that R09's background run uses. R10 and R21 share files. |
| 5. Feature correctness | R20, R19, R17 | R17 last, because it changes spend and waits on D-R2. |

## 4. Each finding: module, pattern, change, test

### Wave 1: injection boundary

**R01: newline-chained commands (`core/approval_policy.py`, `tools/bash_tool.py`), M**

- **Pattern:** canonicalize, then validate, with the tokenizer as a pure, explicit state machine. The shell syntax is a parameter (Strategy), because Python code must stay one block and shell text must not.
- **Why this pattern:** approval decisions are per segment, so the bug is in segmentation, not in any rule. Fixing the splitter once fixes:
  - the carve-out bypass;
  - the `is_read_only_segment` first-token bypass (`ls\nri -r -fo C:\x`);
  - any future rule.
- **Change:**
  1. Move `split_segments` and `_inline_literal_vars` into a new pure module `weebot/core/shell_segments.py`. This takes about 70 lines out of `approval_policy.py`.
  2. `split_segments(command, *, syntax: SegmentSyntax)` gains `SegmentSyntax.SHELL` and `SegmentSyntax.PYTHON`. In SHELL, `\n`, `\r\n` and a bare `\r` outside quotes are separators, and a backtick-newline continuation joins lines. PYTHON keeps today's behaviour. The callers at `approval_policy.py:417, 451` pass SHELL; python_execute never reaches them (`tool_guards.py:186`).
  3. `READ_ONLY_COMMANDS` loses `env`. `env X` runs X, so it is read-only only with no arguments.
  4. `_in_output(path, cwd)` takes the directory the command will run in. `BashTool` passes `working_dir` to the evaluation as well as to the run (`bash_tool.py:395` against `:414-416`).
- **Test first:** `tests/unit/fixes/test_r01_newline_is_a_segment_break.py`, parametrized:
  - must ask: the audit's two strings; the CRLF and `\r` forms; `env rm -rf X`; `Remove-Item Output\data.csv` with `working_dir` set to another project;
  - must stay allowed: a multi-line Python block via python_execute, a backtick continuation of one cmdlet, and `Set-Content Output\a.txt hi` alone;
  - also keep the audit's probe (`GuardChain.evaluate` on the strings) as an assertion.
- **Risk:** a PowerShell here-string (`@' ... '@`) spanning lines is now several segments. Its inner lines match no rule and fall into `shell_default_ask` (observe today). That fails closed. See D-R3.

**R24: canonical tool name before any guard (`application/models/tool_collection.py`, `executor/_tool_executor.py`), S**

- **Pattern:** resolve, then validate. A tool call is identified once by its canonical name, a value every later stage uses.
- **Change:**
  1. Add `ToolCollection.resolve_name(name) -> str | None`, holding today's exact-then-fuzzy logic.
  2. `ToolExecutor` resolves the name before egress classification, the guard chain and dispatch, and passes the canonical name to all three.
  3. `ToolCollection.execute` stops fuzzy-matching on its own; an unknown name is an error there.
- **Test first:** `test_r24_fuzzy_names_meet_the_egress_check.py`. `Advanced_Browser` with `action=submit` is classified exactly as `advanced_browser`, and `execute("Advanced_Browser")` without resolution returns an error.

**R02: atomic mail send detection (`core/egress_guard.py`, `infrastructure/adapters/atomicmail/jmap_request.py`), M**

- **Pattern:** parse, don't validate. Decide on the request the adapter will actually send (placeholders filled, JSON parsed, method names compared exactly), not on raw text.
- **Change:**
  1. Move the `$VAR` substitution (`_VAR_PATTERN`, `jmap_request.py:30, 453`) into a pure `weebot/core/jmap_ops.py`:
     - `resolve_vars(raw, vars) -> str`;
     - `method_names(ops_json) -> set[str]`.
  2. The adapter imports it (infrastructure to core is allowed), so substitution has one home.
  3. `egress_guard` resolves first, then calls the request a send when any method name equals `EmailSubmission/set`.
  4. If substitution or parsing fails, the request counts as a send (fail closed), with an unknown recipient, so approval is required.
- **Test first:** `test_r02_mail_send_is_seen_after_substitution.py`:
  - `Email$S/set` with `S=Submission` is egress;
  - a read preset is not;
  - `Email/set` (a draft) is not;
  - malformed `ops` is egress.

**R08 + R13 + R14: one write-target policy for every tool that writes files (`infrastructure/security/security_validators.py`; `tools/file_editor.py`, `tools/screen_tool.py`, `tools/image_gen_tool.py`, `tools/video_gen_tool.py`), L**

- **Pattern:** a policy object with an explicit intent:
  - `PathValidator.check_write(path, *, intent: WriteIntent) -> Path`, where `WriteIntent` is CREATE, OVERWRITE or EDIT;
  - it raises a typed `WriteRefused` on refusal;
  - intent decides the extension set (`ALLOWED_CREATE_EXTENSIONS` against `ALLOWED_EXTENSIONS`) and the exists rule (CREATE refuses an existing file, EDIT needs one, OVERWRITE needs one and never touches `DENIED_BASENAMES`).
- **Why this pattern:** the three findings are one missing invariant: "every file write states what it intends and is checked against the workspace". Fixing each tool locally would leave the next tool open. That is how `screen_capture` happened after `file_editor` was fixed.
- **Change:**
  - **The validator:** the workspace root is `WORKSPACE_ROOT`, not `Path.cwd()` captured at import (`image_gen_tool.py:38`, `video_gen_tool.py:50`).
  - **file_editor:**
    - `create` uses CREATE;
    - `write_large` uses CREATE when the path is new and OVERWRITE when it exists, so `.ps1`/`.bat`/`.cmd`/`.sh` can no longer be created this way;
    - `str_replace` and `insert` use EDIT;
    - `str_replace` refuses an empty `old_str` with a clear error.
  - **screen_capture:** `save_path` goes through CREATE or OVERWRITE.
  - **image_gen and video_gen:** `output_path` goes through CREATE, refusing an existing file; a caller who wants to replace one deletes it first through the shell, which asks.
  - **`EXECUTABLE_EXTENSIONS`** (`security_validators.py:72`, never read): either the CREATE rule reads it, or it is deleted.
- **Fitness test** (new, in `test_architecture_fitness.py`): an AST scan of `weebot/tools/` finds every `open(..., "w"/"wb"/"a")`, `write_text` and `write_bytes`, and requires the enclosing function to call `check_write`. A short, reviewed allowlist covers temp-file internals.
- **Tests first, one file per finding:**
  - `test_r08_screen_capture_save_path.py`;
  - `test_r13_file_editor_write_intents.py`;
  - `test_r14_media_output_paths.py` (`.env`, `.git/hooks/pre-commit`, a `.py` file, a path outside the workspace).

**R15: show the whole call in the approval prompt (`application/services/tool_approval.py`), S**

- **Pattern:** a pure presenter, `render_call(request) -> str`. It renders every argument, redacted with `credential_sanitizer.sanitize`. Long values are elided in the middle with the exact hidden count ("…1,342 characters hidden…"), and the total is capped with an explicit notice. The approval fingerprint still covers the whole call.
- **Change:** `approval_prompt` uses `render_call` for all tools, not only `command` and `code`. The short form (chat gateways) shows the head and tail of the longest argument.
- **Test first:** `test_r15_approval_shows_the_whole_call.py`:
  - a 600-character command whose dangerous tail appears in the prompt;
  - `image_gen` arguments appear;
  - a secret in an argument is redacted.

**R23: no key material in logs (`infrastructure/adapters/llm/openai_adapter.py:273, 378`, `openrouter_adapter.py:57`, `tools/bash_tool.py:283, 383`), S**

- **Pattern:** one redaction path. Logs carry a non-reversible fingerprint (`sha256(key)[:8]`) from a `key_fingerprint()` helper in `core/credential_sanitizer.py`, and command text goes through `sanitize` before `[:200]`.
- **Test first:** `test_r23_no_key_in_logs.py`. `caplog` around a 401 from a stub client contains no 4-character run of the key, and a logged command with a `Bearer` token shows it redacted.

### Wave 2: web trust and integrity

**R03: one principal for every route (`interfaces/web/auth.py`, `routers/sessions.py`, `chat_router.py`, `ops_router.py`, `dashboard.py`), M**

- **Pattern:** a single source of truth for identity, finishing the "one authenticator" from the previous plan (W2.1). An async FastAPI dependency `current_principal` wraps `authenticate()`. Routers take it as `principal: Principal`, where `Principal = Annotated[str, Depends(current_principal)]`.
- **Change:**
  1. Replace every sync `get_current_user_id(request)` call in routers (sessions:97, 125; chat_router:56, 157; ops_router:46; dashboard:38) with the dependency.
  2. Delete the sync function, or keep it private for the legacy tests.
  3. Delete `get_current_user_id_async`, which has no callers.
  4. A fitness check forbids `get_current_user_id(` under `interfaces/web/routers/`.
- **Test first:** `test_r03_store_mode_principal.py`. In store mode with two per-principal keys:
  - alice creates a session, and it is stamped `alice`;
  - alice can GET, DELETE and run it;
  - bob gets 404;
  - the list shows each user only their own sessions.
- **Data note:** sessions created in store mode before the fix carry `"anonymous"`. A one-off CLI listing is enough; no migration script.

**R22: behavior router boundary (`interfaces/web/routers/behavior_router.py`, `core/behavior_reporting.py`), S**

- **Pattern:** a typed boundary: parse at the edge.
  - The path parameter is `date: datetime.date`, so FastAPI rejects anything that is not `YYYY-MM-DD` with a 422, and no string reaches `LEDGER_DIR / ...`.
  - The reporter returns a complete typed record: a dataclass with zero defaults for `autonomous_count`, `user_initiated_count`, `override_count`, `actions_by_type` and `start_time`.
- **Test first:** `test_r22_behavior_reports.py`:
  - an empty day returns 200 with zeros;
  - an unknown session returns 200 or 404, never 500;
  - `..%5C..%5Cx` returns 422.
- **Not in scope:** the router's missing ownership checks and the arbitrary `watch/start?directory=`. They need a product decision on what the behavior panel exposes; listed in section 7.

**R04: delete stops the session first (new `application/use_cases/delete_session.py`; `routers/sessions.py:195-222`), M**

- **Pattern:** an application use case (Command) that owns an ordering invariant: no writer is alive when the rows go. It is the same shape as `dispatch_session_input.py`.
- **Change:** `DeleteSession(task_runner, orchestrator, scope)`. Its `execute(session_id)`:
  1. awaits `TaskRunnerPort.cancel_session(session_id)`, which already cancels and awaits the task;
  2. runs the deletion cascade;
  3. closes the `SessionScope` entry.

  The route keeps its ownership check, then calls the use case.
- **Test first:** `test_r04_delete_running_session.py`. Delete a session whose fake flow saves again after a delay; after the delete returns, `load_session` is None and the fake's save never ran.
- **Limit:** sessions run by a gateway or `/api/webhook/run` are not TaskRunner tasks, so there is nothing to cancel. Wave 4 (R05) gives them an owner. Until then the use case logs that no task was found.

**R18: rate-limit tier by method and path (`interfaces/web/rate_limit.py`), S**

- **Pattern:** a pure, table-driven function, `tier(method, path)`, over a rule table of `(methods, prefix, tier)`:
  - GET, HEAD and OPTIONS are never "mutating";
  - `/api/chat` and `/api/chat/stream` share one LLM tier;
  - longest prefix wins only among rules that match the method.
- **Change:** the middleware passes `request.method`. Optional R18b (A27's remaining part): key the bucket by the verified principal from R03, not the client-sent `X-API-Key` hash.
- **Test first:** `test_r18_rate_tiers.py`, a parametrized table, including `GET /api/sessions/x/events` as "read" and `POST /api/chat` as "llm".

### Wave 3: truthful outcomes

**R11: OpenRouterAdapter keeps its parent's invariants (`infrastructure/adapters/llm/openrouter_adapter.py`), S**

- **Pattern:** Liskov substitution. A subclass establishes everything its base reads. `OpenRouterAdapter.__init__` calls `super().__init__(...)` with its client settings, or the base moves its invariants into `_init_state()` and both constructors call it.
- **Test first:**
  - `test_r11_adapter_subclass_contract.py`, parametrized over every `OpenAIAdapter` subclass, asserts the attributes the base methods read (`_enable_model_fallback`, `_default_model`, `_client`);
  - a stubbed `RateLimitError` raises the adapter's rate-limit error, not `AttributeError`.

**R12: one rule for mapping a sandbox result (`tools/powershell_tool.py:182`, `tools/bash_tool.py:420`), S**

- **Pattern:** don't repeat yourself. A shared `to_tool_result(sandbox_result)` (in `tools/_results.py`) makes a non-zero exit an error, using stderr, else stdout, else "exit code N". Both tools call it.
- **Test first:** `test_r12_powershell_exit_code.py`: `exit 3` with empty stderr is an error; a zero exit with stderr text stays a success (warnings).

**R07: tell filler from failure (`executor/_error_handler.py`, `executor/_base.py:605-609`), S**

- **Pattern:** a pure classifier with a closed result type: `classify_reply(text) -> ReplyKind`, where ReplyKind is FILLER, REFUSAL or ANSWER. Prefixes match on word boundaries ("ok" no longer matches "Okta").
  - FILLER keeps today's placeholder.
  - REFUSAL ("i cannot", "i can't", "i'm unable", "i don't have access") keeps the model's text, and the step takes the existing failure path, so it is replanned or fails.
- **Size:** the classifier lives in `_error_handler.py`; `_base.py` (773 lines) changes by about 3 lines.
- **Test first:** `test_r07_refusals_are_failures.py`, a table of replies with their expected kinds, plus a step whose only reply is "I cannot read the file, permission denied.", which does not end COMPLETED.

**R06: the run outcome comes from the plan (`domain/models/plan.py`, `flows/states/completed.py:175-178, 301, 311`), M**

- **Pattern:** a rich domain model. `Plan.outcome() -> PlanOutcome` returns SUCCEEDED, FAILED or INCOMPLETE; INCOMPLETE means any step is UNVERIFIED or PENDING with no FAILED step. `CompletedState` maps the outcome to plan status, session status and `DoneEvent.status` with an exhaustive `match`. The rule lives in the domain, next to `failed_steps()`.
- **Change:** per D-R1, INCOMPLETE ends the session FAILED, with a reason that names the unverified and unrun steps. Learning hooks that run only on success (skill promotion, strategies, summaries) see INCOMPLETE as not success.
- **Test first:** `test_r06_incomplete_runs_are_not_completed.py`:
  - a plan with one UNVERIFIED step;
  - a plan with one PENDING step (all models tripped);
  - a plan with all steps COMPLETED (stays COMPLETED).

### Wave 4: resource lifetime and gateways

**R05: an owned flow for every one-shot run (`interfaces/factories.py`; gateways `telegram`, `slack`, `discord`, `whatsapp`, `signal`, `email`; `routers/webhook.py`), M**

- **Pattern:** scoped resource ownership, as an async context manager:

  ```python
  async with run_scope(session, role=..., llm=..., state_repo=..., profile_name=...) as flow:
      ...
  ```

  It builds the tools and the flow, and calls `flow.teardown()` in `finally`. That is the same guarantee `TaskRunner` gives (`task_runner.py:421`), in one place.
- **Change:** the seven call sites use `run_scope`. A fitness check fails if a module under `interfaces/` calls `build_tools(` outside `run_scope` or `TaskRunner`.
- **Test first:** `test_r05_gateways_tear_down.py`, parametrized over the gateways with a fake tool whose `close()` records calls. After one message, `close` has run once, including when the flow raises.

**R09: Discord deferred response (`interfaces/gateways/discord.py`, `routers/discord_webhook.py`), M**

- **Pattern:** asynchronous request-reply.
  1. Answer the interaction at once with type 5 (deferred).
  2. Run the flow in a background task owned by `core.background_tasks.BackgroundTasks.spawn` (named, cancelled on shutdown), inside `run_scope` (R05).
  3. Edit the original message: `PATCH /webhooks/{application_id}/{interaction_token}/messages/@original`.
  4. On failure, edit it to a short error.
- **Test first:** `test_r09_discord_defers.py`:
  - the route returns `{"type": 5}` without calling the LLM;
  - the background task PATCHes the final text (2,000-character limit kept);
  - a failing flow PATCHes an error.
- **Live check:** needs the owner's Discord application. Ask before using it.

**R10 + R21: poll loops back off; commands parse safely (`interfaces/gateways/telegram.py`, `signal.py`, `application/services/gateway_command_dispatcher.py:104`), S**

- **Pattern:**
  - `_get_updates` returns an explicit result, `Updates(items)` or `ApiError(status, retry_after)`, instead of `[]` for both.
  - One shared `PollBackoff` gives capped exponential backoff with jitter (built on `weebot/utils/backoff.BackoffConfig`) and honours Telegram's `parameters.retry_after`.
  - A 401 is not retryable: the gateway logs once and stops.
  - Signal uses the same helper.
  - R21: `shlex.split` moves inside the dispatcher's error handling. On `ValueError` it falls back to `text.split()`, so `/what's up` is handled as a command with plain words.
- **Test first:** `test_r10_poll_backoff.py`:
  - a fake API returning `{"ok": false, "error_code": 429, "parameters": {"retry_after": 3}}` makes the loop sleep 3 seconds;
  - repeated 500s grow the delay to the cap;
  - a 401 stops the loop.

  And `test_r21_command_parse.py`: `/what's up` gets a reply.

**R16: retry state with a lifecycle (`application/services/task_runner.py:121-216`), S**

- **Pattern:** one record per session with an explicit state, `_RetryState(factory, remaining, retry_pending)`, held in one dict and removed in `_cleanup` unless `retry_pending`. Today two dicts must change together and only one exit path cleans them.
- **Test first:** `test_r16_task_runner_forgets_finished_sessions.py`:
  - after a successful run, a cancelled run, and a run that used up its retries, no entry remains;
  - while a retry is scheduled, the entry is still there.

### Wave 5: feature correctness

**R20: one source for run options (`routers/sessions.py:338-349, 457-469`, `application/use_cases/dispatch_session_input.py`), S**

- **Pattern:** a value object, `RunOptions.from_session(session, override_model=None)` (in `application/use_cases/`), holding the model and ponytail mode. Both `/run` and `/input` build it, so they cannot drift again.
- **Test first:** `test_r20_input_keeps_run_options.py`: a session created with `ponytail_mode="ultra"` and a model keeps both on `/input`.

**R19: activity counts from a read model (`application/cqrs/handlers/active_queries.py`, `routers/chat_router.py:158-166`, `ports/state_repo_port.py`, SQLite and Postgres repos), M**

- **Pattern:** a CQRS read side. A new port method, `session_activity(session_ids) -> dict[str, SessionActivity]`, computes step, tool-call and message counts with one aggregate query over the events table: no loading of events, no query per session. SQLite and Postgres implement it (Postgres in `postgresql/_role_stores.py`).
- **Change:** the two handlers call it. `/api/chat/history` clamps `limit` to 1..500 and reports `total` from a count query. `GET /api/sessions` `total` honours the `status` filter.
- **Test first:** `test_r19_activity_counts.py` against a SQLite repo with seeded events. It runs against Postgres in the integration suite when a DSN is set.

**R17: the planner uses its model (`application/agents/planner.py:97, 200`, `flows/_plan_act_wiring.py:233-240`), S, D-R2 decided: option A**

- **Pattern:** dependency injection of configuration. The planner receives its model, `cfg.model or get_model_cascade_for_role("planner")[0]`, and `_chat_json` passes `model=`. No new layer.
- **Test first:** `test_r17_planner_model.py`:
  - with no override, the planner's `chat` is called with the planner role's first model;
  - with `--model X`, it is called with X.
- **Cost:** with D-R2 option A, every plan moves from DeepSeek flash to Haiku 5.5, which costs more per plan. The 2026-10-23 eval chose it on quality per dollar, but today's bills do not include it.

## 5. Owner decisions

Decided by the owner on 2026-10-29: "D-R2: option A, the planner uses its configured models (Haiku 5.5 first). D-R1 and D-R3 as recommended."

| ID | Question | Recommendation |
|---|---|---|
| D-R1 | How should a run with unverified or unrun steps end? | FAILED, with a reason naming the steps. A separate "incomplete" status needs UI and API changes for little gain. |
| D-R2 | Should the planner use its configured models (Haiku 5.5 first), or stay on the default (DeepSeek flash)? | A: use the configured models, as the role config and its eval note intend; plan spend rises. B: keep DeepSeek and delete the unused `planner` row, so the config stops claiming something false. Either is fine; the current state is the only wrong one. |
| D-R3 | R01 makes multi-line PowerShell (here-strings, multi-line scripts sent as one command) ask more often. Accept? | Yes. It fails closed, and `shell_default_ask` is still in observe mode (D3a), so today it only logs. |

## 6. Verification

- **Per finding:** the new test fails before the change and passes after it; the touched test files pass; all gates pass (ratchets, `lint-imports`, architecture fitness, map drift).
- **Per wave:** the full suite in the scratch worktree; the count of failures must stay 0.
- **Wave 1 regression probe:** keep the audit's guard-chain probe as a test, not a script. It evaluates the command strings through `default_guard_chain()` and asserts the verdicts, executing nothing.
- **Live checks, each only with the owner's OK:**
  - Discord (R09) with the owner's application;
  - Telegram (R10) with a bot token;
  - one billed `flow run` after wave 3, to see an unverified step end FAILED.
- **Docs:**
  - `ARCHITECTURE.md` known debt loses what this closes;
  - the map cards for the approval policy, egress guard, tools, gateways, auth and task runner are restamped;
  - `docs/SECURITY_MODEL.md` gains the write-intent rule (R08/R13/R14) and the newline rule (R01).

## 7. Not in this plan

- **Still open from the 2026-10-27 audit:** A17 (`?token=` still accepted), A22 (Windows network-off by proxy variables), A23 (a swallowed decode error), and the rest of A27 (email trusts the first `Authentication-Results` header). R18b covers A27's bucket key.
- **Seen by the 2026-10-29 audit, not chosen for this plan:**
  - `python_execute` egress regex: same family as A21, which waits on D3a and D5;
  - behavior-router ownership and `watch/start?directory=`: needs a product decision;
  - deletion cascade gaps (constraints, corrections, trajectories, steering queue) and `kg_nodes.source_session_id` never updated;
  - Telegram `/new`, `/reset`, `/stop` doing nothing;
  - the event-store timestamp comparison;
  - presence events journaled under their own id;
  - the ErrorClassifier matching status digits inside request ids;
  - claiming hydration before `flags()` finishes.

  Each is worth its own entry in the next plan.
- **Not touched:** the `weebot-ui` frontend, the MCP server and sandbox network isolation. The audit did not read them.
