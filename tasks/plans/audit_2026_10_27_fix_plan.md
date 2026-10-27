---
status: open
date: 2026-10-27
note: built on fix/audit-wave-1: A01 A02 A04 A05 A06 A07 A08 A09 A10 A12 A13 A14 A15 A16 A17 A18 A19 A20 (observe mode) A22 A23 A31 A32 A34, the Discord replay, rate-limit order and WebSocket identity parts of A27; A11 deferred (needs a product call); wave 0 and the rest of waves 2-6 not started; D1 built, D3a built in observe mode, D3b advisory, D4 research in d4_wiring_research_2026_10_27.md
---

# Plan: fix the findings of the 2026-10-27 whole-repo audit

Source: the `/ponytail-audit` run of 2026-10-27 (five read-only readers, then a check of each
claim against the code). This file is the only written record of that audit, so the finding
register below is self-contained. Each finding carries its evidence status:

- **verified**: the cited lines were re-read during the audit and do what the finding says.
- **trace**: a reader followed the call path, but the conclusion was not re-checked by hand.
  Wave 0 turns every trace into a test before anything is changed.

## 1. Corrections to the audit report

- **A03 is withdrawn.** The report said the `powershell` tool skips BashGuard and the command
  analyzer. The tool's own `execute` does, but the registry wraps it: `tool_registry.py:532-534`
  calls `guard_tools(...)`, which puts `bash`, `powershell` and `python_execute` behind
  `GuardedTool` with `default_guard_chain()` (BashGuard, analyzer, approval policy, financial,
  outbound). `shell_guard_mode` defaults to `enforce` since W3.7 (`remaining_fix_plan.md:299`).
  What remains is lean work: the tool's private regex lists now duplicate the chain (see A30).
- **A06 is still open, although `icm_fix_plan.md` F59 says "Fixed 606e5e0f".** That commit added
  `require_mutation_identity` to the behavior POST routes. The behavior WebSockets
  (`behavior_router.py:248-288`) still authenticate only `if weebot_api_key:`. W2.3 below fixes
  them and corrects the F59 row.
- **Severity of A04 drops from high to medium.** The chain's BashGuard also runs on
  `powershell`, but its `Remove-Item\s+-Recurse\s+-Force` rule needs the flags before the path,
  so `Remove-Item Output\j\x -Recurse -Force` still passes. The repro test decides.

## 2. Rules for every item

1. **Failing test first.** Each finding gets a repro in `tests/unit/fixes/test_a27_<NN>_<slug>.py`,
   written as `pytest.mark.xfail(strict=True)` in wave 0. The fix commit removes the marker.
   A repro that passes before the fix means the finding was wrong: record that here and drop it.
2. **Layers.** Dependencies point inward (`interfaces -> infrastructure -> application -> domain`).
   New cross-layer needs go through a port in `weebot/application/ports/` or `weebot/domain/ports.py`
   plus a DI registration in `weebot/application/di/`. No new `ignore_imports` in `.importlinter`.
3. **Ratchets.** `tasks/quality/ceilings.toml` uses exact equality. Never raise a ceiling. A
   deletion that lowers a count lowers the ceiling in the same commit.
4. **Map cards.** After committing a change to a cited file, run
   `python scripts/check_map_citations.py --drift`. Re-read and fix each card it reports, then
   run `python scripts/gen_map_index.py --check`.
5. **One PR per wave**, smallest first. Each PR runs the full suite (`pytest tests/`), `ruff check .`,
   `lint-imports`, and the scripts behind `make check` (run directly where `make` is missing).
6. **Conventions.** `SecretAccessor` for env reads, `logger` not `print`, a log line in every
   `except`, shell work only through the tool layer, adapters resolved from the container.

## 3. Finding register

| ID | Finding | Module | Sev | Evidence |
|---|---|---|---|---|
| A01 | Persisted jobs are never re-added to APScheduler after a restart, so no scheduled job runs again | `weebot/scheduling/scheduler.py:144, 697-703`; `default_jobs.py:382-389` | H | verified |
| A02 | `SQLiteGatewaySessionStore._row_to_session` calls `.get` on `sqlite3.Row`; every gateway read fails once a row exists | `infrastructure/persistence/gateway_session_store.py:97, 112-113` | H | verified |
| A03 | (withdrawn, see section 1) | `tools/powershell_tool.py` | - | verified wrong |
| A04 | `_in_output` checks the path as text, so a junction under `Output\` lets an auto-approved `Remove-Item` delete outside it | `core/approval_policy.py:403-415, 345` | M | verified |
| A05 | The email allowlist reads the first `<...>` in `From`, which can sit inside the display name | `interfaces/gateways/email.py:229-236` (and 43-50, 132-139) | H | verified |
| A06 | Behavior WebSockets accept any client when no API key is set | `interfaces/web/routers/behavior_router.py:248-288, 369-377` | H | verified |
| A07 | The Next.js proxy has no Origin check and forces JSON, so any web page can drive the loopback-trusted backend | `weebot-ui/src/app/api/[[...path]]/route.ts:19-33` | H | verified |
| A08 | `POST /api/sessions` with an existing `session_id` overwrites that session | `interfaces/web/routers/sessions.py:127-135` | H | verified |
| A09 | Sub-agent flows have no cost meter and are never linked to the parent, so their spend escapes the budget | `application/di/__init__.py:676-689`; `di/_agent_tools.py:54-75`; `services/session_cost.py:64`; `adapters/sub_agent_factory.py:106` | H | verified |
| A10 | Public webhook routes buffer bodies of any size before any check | `routers/slack_webhook.py:43-44`, `discord_webhook.py:42-46`, `whatsapp_webhook.py:70` | H | trace |
| A11 | The inbound-mail gate is set after the step and checked before the next one, so tools later in the same step act on mail ungated | `flows/states/_step_run.py:106-108`; `_execution_gates.py:96-112` | H | verified |
| A12 | Commitments get a fresh `uuid4` on every `save_session`, so each promise is re-inserted on each save | `domain/services/commitment_extractor.py:127`; `sqlite_state_repo.py:323-334` | M | verified |
| A13 | Two answers to one WAITING (or PENDING) session both pass the status check and start two flows | `use_cases/dispatch_session_input.py:106-116`; `services/task_runner.py:150-181, 373-392` | M | trace |
| A14 | `_execute_job`'s `finally` saves the start-of-run snapshot with `INSERT OR REPLACE`, undoing a pause, edit or delete made during the run; `cron_jobs.json` is read-modify-written without re-reading and without an atomic write | `scheduling/scheduler.py:477-479, 488-501, 625-645` | M | verified (job), trace (json) |
| A15 | `acquire_write` catches `Exception`, not `CancelledError`, so a cancelled writer leaves an open transaction that the next writer commits | `infrastructure/persistence/connection_pool.py:187-199` | M | verified |
| A16 | `DirectOrFallbackAdapter` circuit counters never reset once open; the fallback counter locks the same way | `infrastructure/adapters/llm/direct_or_fallback_adapter.py:141-148, 186-207` | M | verified |
| A17 | The UI sends the API key as `?token=` on WebSockets, and uvicorn logs the query string | `interfaces/web/main.py:727-739`; `weebot-ui/src/lib/api.ts:30-34` | M | trace |
| A18 | Non-cascade calls are priced by `response.model`; direct adapters return bare ids the catalog lacks, so they cost 0.0 | `application/strategies/llm_pool.py:254, 277`; `core/model_cascade_config.py:43-45` | M | trace |
| A19 | `run.py --diagnostic` imports modules that do not exist (`weebot.agent_core_v2`, `weebot.notifications`, `weebot.ai_router`) | `run.py:90-99` | L | verified |
| A20 | `ExecApprovalPolicy` approves any segment that matches no rule (for example `[IO.Directory]::Delete(...)`) | `core/approval_policy.py:317-322, 324-364` | M | verified |
| A21 | Egress is a regex on send verbs; data in a GET query, .NET HTTP or DNS is not egress, so the untrusted-context escalation never fires | `core/egress_guard.py:85-112, 316-343` | M | trace |
| A22 | Host checks take the hostname string: loopback, link-local and RFC1918 targets can be "allow always"; native Windows "network off" is proxy env vars only | `core/egress_guard.py:362-382, 479-486`; `infrastructure/sandbox/native_windows.py:79-87` | M | trace |
| A23 | Encoded-command checks miss `-EncodedCommand` prefixes (`-en`, `-enco`, ...) and `powershell_tool.py:162` swallows decode errors | `tools/powershell_tool.py:102-106, 150-163`; `tools/bash_security.py:151-162`; `core/bash_guard.py:399` | L | trace |
| A24 | The memory-compaction job loads a RUNNING session, then saves the stale copy over the live row | `scheduling/default_jobs.py:84-94` | M | trace |
| A25 | TaskRunner and EventPublisher both save the whole session from different copies; emitted-not-yielded events are lost and a durable WAITING is overwritten | `services/task_runner.py:266-361`; `flows/states/completed.py:421`; `plan_review.py:138-145` | M | trace |
| A26 | LLM accounting gaps: cancelled hedge probes are billed but unrecorded; timeouts never trip the breaker; cached prompt tokens are priced at full rate; timeouts are retried 7 times with no deadline outside the cascade; image and video calls are never metered and buy again after a paid 200; the hard limit is checked only between steps | `executor/_cascade.py:424-435, 559-620`; `llm/openai_adapter.py:338-341`; `resilient_adapter.py:141-146`; `tools/image_gen_tool.py:654-740`; `tools/video_gen_tool.py:322-371`; `flows/plan_act_flow.py:517` | M | trace |
| A27 | Web auth seams: `RateLimitMiddleware` sits inside `APIKeyMiddleware`, so failed guesses are never limited and the bucket key is an unverified header; WebSocket ownership re-reads `X-API-Key`, which browsers never send; Discord signatures have no timestamp freshness check; email trusts the top `Authentication-Results` without its authserv-id | `interfaces/web/main.py:438, 529, 658-667`; `auth.py:112, 231`; `rate_limit.py:199-205`; gateways | M | trace |
| A28 | Scheduler and job times are naive local `datetime.now()` while comments say UTC; `list_sessions()` default limit 100 makes health and compaction jobs skip the oldest sessions; `trajectory_repo` deletes every trajectory when none qualifies as a keeper | `scheduling/scheduler.py`; `default_jobs.py`; `persistence/trajectory_repo.py:203-213` | L | trace |
| A29 | About 31k production lines have no production caller (groups G1-G9 in wave 6) | many | L | verified on samples |
| A30 | About 17 `requirements.txt` entries are never imported; `powershell_tool.py`'s private guard lists duplicate the guard chain | `requirements.txt`; `tools/powershell_tool.py:60-170` | L | verified on samples |
| A31 | `pyproject.toml` `packages.find include = ["weebot*", "cli*"]` leaves out `research_modules` and `integrations`, so `weebot research` fails after `pip install` | `pyproject.toml` | L | trace |
| A32 | Docker UI sets `NEXT_PUBLIC_API_URL=http://weebot-api:8000` without `/api`, so the proxy targets `/sessions` and gets 404 | `docker-compose.yml`; `route.ts:4` | L | trace |
| A33 | `GatewayAdapter.handle()`'s safety gate never fires: `is_critical_operation(text, "gateway")` is false for every tool but `powershell_executor` | `core/safety.py:47` | L | trace |
| A34 | `BashGuard`'s event callback swallows exceptions without a log line | `core/bash_guard.py:566-570` | L | verified (by reader) |

## 4. Module, paradigm, pattern

| Module | Paradigm and pattern | Why this and not the alternative |
|---|---|---|
| Scheduler (A01, A14, A28) | **Desired-state reconciliation**: `jobs.db` is the source of truth and APScheduler is a projection rebuilt by one idempotent `reconcile()` on start and after each mutation. Run bookkeeping uses **conditional writes** (targeted `UPDATE ... WHERE`), not snapshot replace. All times are aware UTC. | The bug class is "two stores drift". Reconcile makes startup, create and resume one code path. Alternative rejected: a persistent APScheduler `SQLAlchemyJobStore`, which adds a second persisted copy of the same jobs. |
| Gateway session store (A02) | **Data Mapper** with one row-to-model function over `dict(row)`, plus a **port contract test** run against every `GatewaySessionStore` implementation | The in-memory store hid the SQLite bug because no shared contract suite exists. One suite catches the next divergence too. |
| Web trust boundary (A06, A07, A08, A17, A27) | **One authenticator** (`authenticate(conn) -> Principal | None`, a pure function over headers, subprotocol and client address) used by HTTP middleware, route dependencies and every WebSocket. The proxy applies the **Fetch Metadata resource-isolation policy**. Session create is an **insert-only command** that fails on conflict. Rate limiting is the **outermost** middleware. | Today auth is computed in four places with different sources (A06, A27). A single function returning a value object removes the divergence. Alternative rejected: adding checks route by route, which is how the gaps appeared. |
| Request size (A10) | **Pure ASGI middleware** that checks `Content-Length` and counts streamed bytes | `BaseHTTPMiddleware` cannot bound a streamed body. One middleware covers every route, public or not. |
| Email gateway (A05, A27) | **Parse, don't validate**: parse `From` once into a `VerifiedSender` value object (`email.utils.getaddresses`, exactly one address, the matching DMARC result from a trusted authserv-id). The allowlist and the DMARC check take that object. | Three call sites parse `From` today. A value object that only the parser can build keeps the raw string out of the checks downstream. |
| Shell approval (A04, A20, A23) | **Pure function over immutable data**, continuing `icm_fix_plan.md` F04/F05: canonicalize first (resolve paths, normalize parameter prefixes), then validate. For shell tools only, an unmatched segment folds to ASK unless it is on a small read-only allowlist. | Validation before canonicalization is the root of A04 and A23. Shell-only scope keeps the `python_execute` constraint recorded in `icm_fix_plan.md:295` (`executor.shutdown()` must not be refused). |
| Untrusted content (A11, A21) | **Taint tracking at the tool boundary**: `ToolExecutor` marks the session tainted the moment an EXTERNAL-trust tool returns. A new `UntrustedContentGuard` joins `default_guard_chain()` (**Chain of Responsibility**, the existing `ToolGuard` protocol in `application/services/tool_guards.py`) and returns ASK for non-read-only tools and for any network-capable shell command while tainted. | Reuses the chain built for F01-F12. Per-call checking closes the same-step gap. Alternative rejected: ending the step after every mail fetch, which hides the problem for one tool only. |
| Network targets (A22) | **Pure classification** with `ipaddress`: literal, then resolved, then ASK for loopback, link-local and private ranges, never stored as "always" | A hostname string says nothing about where a request goes. |
| Write connection (A15) | Correct **context manager** semantics: roll back on `BaseException`, commit only on clean exit | The lock is released either way. The connection must be clean when it is. |
| Session runs (A13, A25) | **Single-writer principle** (the flow's `EventPublisher` owns persistence; TaskRunner writes only the final status through the flow's session) plus a **keyed lock** per session around load, check, save, start, plus an **idempotency key** (`client_msg_id`) | Two writers from two copies is the cause of A25. A lock without one writer still loses events. |
| Background jobs touching sessions (A24) | **Optimistic concurrency**: `save_session_if_unchanged(session, expected_updated_at)` on the state port (a default over load and compare; SQLite does it in one `UPDATE ... WHERE updated_at = ?`), and skip sessions the runner holds | The compaction job must never win against the live flow. A compare-and-swap is the smallest general rule. |
| Commitments (A12) | **Deterministic identity** (natural key: session, event, promise text, hashed with `uuid5`) plus a `UNIQUE` index; extraction runs only on events past a watermark | Idempotent writes make re-saves harmless. The watermark removes the rescan cost. |
| Money (A09, A18, A26) | **Event-sourced cost** (continuing `icm_fix_plan.md` F23): every billed request, including cancelled probes and media calls, publishes one `LLMCallCompleted`; the meter is the projection. Sub-agents form a **Composite** cost tree through the existing `SessionCostMeter.link`. Pricing is one function keyed by the requested catalog id. The hard limit becomes a **guard clause** at the top of `call_with_cascade`. | One home for the fact "this request cost X". Conservative accounting (estimate when usage is missing) keeps the limit on the safe side. |
| Provider resilience (A16, A26) | **Reuse `weebot/core/circuit_breaker.py`** (it already has CLOSED, OPEN, HALF_OPEN) instead of the hand-written counters; retry policy as data with timeouts non-retryable or capped at one | Deletes two ad-hoc breakers. The existing breaker already has the half-open probe the adapter lacks. |
| Dead code (A29, A30) | **Delete in vertical slices**, one group per PR, tests and ceilings in the same commit | Small PRs keep each `make check` readable. Alternative rejected: one big deletion, which hides a wrong "unused" call. |

## 5. Waves

Sizes: S under half a day, M about a day, L more.

### Wave 0: repro tests (no product change)

- W0.1 One strict-xfail repro per finding A01-A28 and A31-A33 in `tests/unit/fixes/test_a27_<NN>_*.py`.
  For races (A13, A24, A25), use two coroutines and an `asyncio.Event` to force the
  interleaving. For A07, use a UI-side test of `route.ts` if the UI has a test runner; otherwise
  write a Python test of the backend half and record a manual check here. M
- W0.2 A repro that passes before any fix: record "not reproduced" in section 3 and drop the
  finding. S

### Wave 1: features that are broken now

- W1.1 **A02 gateway store.** Add `row = dict(row)` at the top of `_row_to_session`. Add
  `tests/unit/infrastructure/test_gateway_session_store_contract.py`, parametrized over the
  in-memory and SQLite stores: create, get, list, upsert, platform limit. S
- W1.2 **A01 scheduler reconcile.** In `SchedulingManager`, add `async def reconcile(self)`.
  - For each `list_jobs(enabled_only=True)` job that is not paused and not in `self.scheduler`,
    call `_schedule_job`.
  - Remove APScheduler jobs whose row is gone or disabled.
  - Call it at the end of `start()`, before `run_catch_up()`.
  - `create_job`, `update_job` and `resume_job` keep calling `_schedule_job`. That is safe if
    `_schedule_job` passes `replace_existing=True`; check the flag.
  - Test: create a job, build a new manager over the same `jobs.db`, `start()`, and assert the
    job is scheduled. M
- W1.3 **A19 run.py diagnostic.** Drop the missing modules from the list in `run.py:90-99`, and
  the ones wave 6 deletes. Test: `run.py --diagnostic` reports no import errors (subprocess with
  a stub env). S
- W1.4 **A32 docker UI URL.** Set `BACKEND_URL=http://weebot-api:8000/api` (server-side, not
  `NEXT_PUBLIC_`) in `docker-compose.yml`. Check with `docker compose config`. S
- W1.5 **A31 packaging.** Add `research_modules*` and `integrations*` to `packages.find`, or
  move them under `weebot/` if wave 6 keeps them (decision D4). Test: build a wheel and list it. S

### Wave 2: web and gateway trust boundary

- W2.1 **One authenticator.** In `weebot/interfaces/web/auth.py`, add
  `authenticate(conn: HTTPConnection) -> Principal | None`.
  - It checks, in order: the `X-API-Key` header, `Authorization: Bearer`, then a
    `bearer.<token>` WebSocket subprotocol. Every comparison uses `hmac.compare_digest`.
  - In store mode it resolves per-principal keys.
  - Loopback with no key configured yields `Principal("local")`.
  - `_resolve_user`, `require_mutation_identity`, `APIKeyMiddleware`, `_websocket_auth` and
    `verify_session_ownership` all call it. This fixes the ownership half of A27. M
- W2.2 **A17 key out of the URL.**
  - The server accepts WebSockets with the matched subprotocol echoed
    (`websocket.accept(subprotocol=...)`).
  - The UI connects with `new WebSocket(url, ["bearer." + key])`, in `lib/api.ts` and
    `EventStreamProvider.tsx`.
  - Remove the `?token=` path after one release with a deprecation log line (decision D2).
  - Test: an accepted handshake echoes the protocol. M
- W2.3 **A06 behavior WebSockets.** Both handlers call the W2.1 authenticator and close with
  4001 when it returns None. Cap `get_recent` count at 1000. Correct the F59 row in
  `icm_fix_plan.md`. S
- W2.4 **A08 create is create.**
  - Add `create_session(session) -> bool` to `StateRepositoryPort`. Its default implementation
    loads, then saves only if absent, so other repositories keep working.
  - `SQLiteStateRepository` overrides it with `INSERT ... ON CONFLICT(id) DO NOTHING` and
    checks `rowcount`.
  - The router returns 409 when it returns False. S
- W2.5 **A07 proxy.**
  - In `route.ts`, reject non-GET/HEAD requests unless `Sec-Fetch-Site` is `same-origin`. If
    the header is absent, require `Origin` to equal the request host.
  - Pass the client's `Content-Type` through instead of forcing JSON, and forward
    `Authorization`.
  - Backend side: stop treating loopback as an identity for mutations when
    `WEEBOT_BEHIND_PROXY=1` (decision D1). S
- W2.6 **A10 body limit.** Add `weebot/interfaces/web/body_limit.py`, a pure ASGI middleware.
  - Reject a `Content-Length` above `WEEBOT_MAX_BODY_BYTES` with 413. The default is 1 MiB;
    upload routes may allow more.
  - Count bytes in `receive()` for chunked bodies.
  - Register it as the second-outermost middleware (the rate limiter from W2.7 is outermost).
  - In the Slack and Discord routes, verify the signature before `request.json()`.
  - Test: a 2 MiB POST to `/api/gateway/slack/events` gets 413 before the route runs. S
- W2.7 **A27 middleware order.** Add `RateLimitMiddleware` last so it is outermost. Key the
  bucket by client IP until a principal is verified. Test: 30 bad keys from one IP hit 429. S
- W2.8 **A05 email sender.** Add `weebot/interfaces/gateways/email_sender.py` with a frozen
  `VerifiedSender(address, domain, dmarc_pass)` and `parse_sender(msg, trusted_authserv_ids)`.
  - It reads `email.utils.getaddresses(msg.get_all("From", []))` and requires exactly one
    address.
  - It takes the DMARC result only from an `Authentication-Results` header whose authserv-id is
    trusted. The trusted ids come from settings, defaulting to the IMAP host.
  - All three call sites in `email.py` use it.
  - Tests: a display-name spoof, two From headers, a forged top header. M
- W2.9 **A27 Discord replay.** Reject interactions whose `X-Signature-Timestamp` is older than
  5 minutes. S
- W2.10 **A33 gateway safety gate.** Choose by the repro:
  - Make `is_critical_operation` use the real tool names.
  - Or delete the gate, if the guard chain already covers gateway runs. It does when the tools
    come from the registry. S

### Wave 3: agent action safety

- W3.1 **A04 canonicalize before checking.** In `approval_policy._in_output`, resolve
  `Path(cwd, p).resolve(strict=False)` and require `is_relative_to(cwd / "Output")`. Return False
  for `New-Item` with `-ItemType SymbolicLink|Junction|HardLink`. Test: the two-step junction
  case asks on step one. S
- W3.2 **A20 shell default.**
  - Give `ExecApprovalPolicy.evaluate` a `tool_kind` argument: `"shell"` from the guard
    adapter for `bash` and `powershell`, `"python"` for `python_execute`.
  - For shell, an unmatched segment is ALLOW only when its first token is on a read-only
    allowlist, else ASK. The allowlist covers `Get-*`, `Select-*`, `Test-Path`, `Format-*`,
    `ls`, `cat`, `grep`, `find`, `git status|log|diff`, and similar.
  - Any `[...]::` static call asks.
  - Keep the allowlist as data, in `weebot/core/approval_rules.py` or the existing rules file.
  - Run it in observe mode first through `WEEBOT_SHELL_GUARD_MODE`. Record how many asks a
    normal 12-task batch adds before enforcing (decision D3). M
- W3.3 **A23 encoded commands.** One shared matcher for `-e`, `-ec`, and every prefix of
  `-EncodedCommand`, with `-` or `/`, used by the analyzer and BashGuard. Delete the
  `powershell_tool.py` copy (A30). An undecodable blob fails closed. S
- W3.4 **A11 and A21 taint.**
  - In `ToolExecutor.execute_tool`, set the session fact `untrusted_content_seen` as soon as a
    tool with `OutputTrust.EXTERNAL` returns content (mail, web fetch, browser).
  - Add `UntrustedContentGuard` to `default_guard_chain()`. While the fact is set, it returns
    ASK for non-read-only tools, and for any shell command that matches `_SHELL_NETWORK_RE` or
    contains a URL or host token.
  - Keep `_inbound_mail_gate` as the step-level pause for the next step.
  - Test: a mail fetch followed by a shell call in the same step asks. M
- W3.5 **A22 network targets.**
  - Add `classify_host(host) -> HostClass` in `weebot/core/egress_guard.py`. It runs
    `ipaddress` on the literal and on the `getaddrinfo` results.
  - Loopback, link-local (including 169.254.169.254) and RFC1918 targets always ask and are
    never stored as "always".
  - Document native Windows "network off" as advisory in `docs/SECURITY_MODEL.md`. Enforcing it
    (a Windows Firewall rule or an AppContainer) is decision D3. S
- W3.6 **A34 log in except.** Add `_log.warning(..., exc_info=True)` in
  `bash_guard.py:566-570`. Lower `silent_except_handlers` if it counted this one. S

### Wave 4: persistence and concurrency

- W4.1 **A15.** In `connection_pool.acquire_write`, change `except Exception:` to
  `except BaseException:` and log the rollback failure. Test: cancel a writer mid-transaction,
  then a second write commits only its own row. S
- W4.2 **A13 keyed lock and idempotency.** In `TaskRunner`:
  - Add `self._session_locks: dict[str, asyncio.Lock]`, evicted when the task finishes.
  - Hold the lock across load, check, save and start in `_start_task`, `resume_session` and
    `_start_direct`.
  - Refuse to start when `self._tasks[sid]` exists and is not done.
  - Store the last `client_msg_id` in the session context and ignore a repeat.
  - Test: two concurrent answers start one flow. M
- W4.3 **A25 single writer.**
  - When the flow has a `state_repo`, TaskRunner stops its per-event `save_session`.
  - Its final save uses `flow._session` with the status override, not its own copy.
  - Record the rule in `ARCHITECTURE.md`: the publisher owns session persistence.
  - Tests: an emitted-not-yielded event survives the run; a WAITING pause stays WAITING. M
- W4.4 **A24 compare-and-swap.**
  - Add `save_session_if_unchanged(session, expected_updated_at) -> bool` to the state port.
    Its default implementation loads, compares, then saves.
  - SQLite does it in one `UPDATE ... WHERE id = ? AND updated_at = ?`.
  - The compaction job uses it, and skips sessions in `TaskRunner.running_ids()`, exposed
    through a small port. S
- W4.5 **A12 commitments.**
  - Use `uuid5(NAMESPACE_URL, f"{session_id}:{event_id}:{promise_text}")` as the id.
  - Delete existing duplicates first, keeping the oldest row per key.
  - Then add a unique index on `(source_session_id, source_event_id, promise_text)`, both as an
    alembic migration and as a runtime `CREATE UNIQUE INDEX IF NOT EXISTS`.
  - Extract only from events after a stored watermark, as the FTS index does.
  - Test: three saves of one session leave one row. M
- W4.6 **A14 job bookkeeping.**
  - Replace the `finally` save with `UPDATE jobs SET status=?, run_count=run_count+1,
    error_count=?, last_error=?, last_run=? WHERE job_id=? AND status != 'paused'`. Skip it when
    the row was deleted.
  - For `cron_jobs.json`, re-read the file right before writing, and write with
    `weebot.core.durable_state.write_text_atomic` under an `asyncio.Lock`.
  - Test: a pause made during a run stays paused. S
- W4.7 **A28 time and limits.**
  - Use `AsyncIOScheduler(timezone=timezone.utc)` and `datetime.now(UTC)` for job times. The
    read path accepts the old naive values as UTC.
  - Health and compaction jobs page through `list_sessions` instead of taking the default 100.
  - `trajectory_repo` keeps the newest N when no trajectory qualifies. S

### Wave 5: money

- W5.1 **A09 sub-agents.**
  - At the composition root (`_build_sub_flow` in `di/__init__.py`, and the dispatch flow in
    `di/_agent_tools.py`), pass `cost_meter=self._maybe_get(SESSION_COST_METER)`.
  - Call `meter.link(child_id, parent_id)`, taking the parent from `session_id_var`.
  - `SubAgentFactory` records `meter.total(child_id)` instead of `0.0`.
  - `hyper` uses the same tracker instance the factory writes to.
  - Test: a child spending $1.50 moves the parent's total by $1.50 and trips its hard limit. M
- W5.2 **A18 one pricing key.**
  - `BoundedLLMAdapter` prices the requested catalog id, the same rule as the cascade.
  - `DirectOrFallbackAdapter` stamps `result.model` with the prefixed id.
  - `estimate_cost` logs a catalog miss at WARNING, once per id.
  - Test: a DeepSeek-direct call is priced above 0. S
- W5.3 **A26 cached tokens.** Add a keyword argument:
  `estimate_cost(model, prompt, completion, *, cached_prompt=0)`. It prices cached tokens at
  the catalog's cache-read rate, or at 0.1 of the prompt rate when the catalog has none.
  Adapters pass `usage["cached_tokens"]`. S
- W5.4 **A26 cancelled and timed-out probes.**
  - Keep a `future -> model` map in the hedge loop.
  - In the `finally`, publish `LLMCallCompleted` for each cancelled or timed-out probe, with an
    estimated prompt cost, 0 completion, and `estimated=True`.
  - Call `_cascade_record_failure` on timeout. S
- W5.5 **A16 breaker reuse.** Replace the two counters in `DirectOrFallbackAdapter` with two
  `weebot.core.circuit_breaker.CircuitBreaker` instances (half-open after 60 s). Test: after the
  cooldown one primary call is tried. S
- W5.6 **A26 retry policy.** In `ResilientAdapter`, `TimeoutError` and the TIMEOUT category
  retry at most once. Planner calls run inside the same `deadline_scope` the cascade uses. S
- W5.7 **A26 media calls.**
  - Image and video tools publish `LLMCallCompleted` on every 200. The per-call price comes
    from `model_refs.py`; add the prices there as data.
  - They stop after a paid 200, even when parsing or the download fails. They return the error
    instead of buying again from the next model. S
- W5.8 **A26 hard limit inside a step.** At the top of `call_with_cascade`, when
  `meter.total(sid) >= meter.hard_usd`, raise the budget error that `enforce_budget` already
  handles, so the flow gate asks. Test: a step that crosses the limit stops at the next call. S

### Wave 6: lean (A29, A30)

Order by risk, one PR per group. Each PR:
- deletes the code, and the tests that only exercise it;
- removes its `.importlinter` lines and doc mentions;
- lowers the ceilings it moves;
- reruns the map drift check.

Groups:

- G1 `weebot/templates/` except `parser.py`, `marketplace.py` and `builtin/`; the top-level
  `templates/`; `weebot/core/tool_agent.py`; `scripts/deploy_staging.py`; the two template
  examples. About 7.9k lines. Drops `jinja2`.
- G2 `weebot/infrastructure/interface_customization.py` and `persistence/profile_storage.py`.
  About 1.4k lines.
- G3 `application/services/source_credibility_assessment.py` and `multi_source_research.py`.
  About 1.3k lines.
- G4 the observability orphans, about 2.8k lines. Update the allow-lists in
  `test_architecture_fitness.py`.
  - `core/dashboard.py`, `core/workflow_tracer.py`, `core/alerting.py`
  - `infrastructure/observability/audit_log.py`, `otel_sink.py`
  - `infrastructure/monitors/`, `infrastructure/analytics/` and its port
  - `utils/logger.py`, `notifications/_base.py`, `weebot/docs/MONITORING_DASHBOARD.json`
- G5 QMD leftovers: `qmd_integration/mcp_client.py`, `query_expander.py`, `rag_engine.py`,
  `adapters/qmd_rag_adapter.py`, `ports/rag_port.py`. Keep `embeddings.py`. About 1.4k lines.
- G6 unreferenced scripts (28 files, about 3.9k lines), after a last grep of docs.
- G7 about 1.1k lines:
  - `infrastructure/sandbox/osworld.py` and `config/osworld_settings.py`
  - `integrations/zotero.py` and `research_modules/literature.py` (only `run.py`'s list names
    them)
  - `weebot/FINAL_PROJECT_SUMMARY.md`
- G8 the self-improvement, eval and context-compression island (about 6.5k lines). Needs
  decision D4 first: the disabled `skill_promotion_check` job records an intent to wire
  `skill_promotion_gate` and `chain_of_verification`.
- G9 unwired adapters and verifiers (about 4.5k lines), same decision D4. The Valkey bus has a
  recorded "bridge later" intent (`icm_fix_plan.md` W4.3). Drops `valkey` together with G1.
- G10 `requirements.txt`:
  - Remove `marshmallow`, `cerberus`, `seaborn`, `scipy`, `pypandoc`, `python-docx`,
    `colorama`, `langchain`, `prompt-toolkit`, `toml`, `python-dateutil`, `uuid-utils`, `wmi`.
  - Remove `jinja2` and `valkey` together with their groups.
  - Keep `pywin32` and `duckduckgo-search` until checked on a clean Windows install.
  - Regenerate `requirements.txt.lock`.
- G11 the private guard lists in `tools/powershell_tool.py` that the chain duplicates. Keep
  `DIAGNOSTIC_COMMANDS` and the timeout handling.

## 6. Decisions for the owner

- **D1** Should loopback stop counting as an identity for mutations when the UI proxy is in
  front (`WEEBOT_BEHIND_PROXY=1`)? Recommended yes; local dev then needs a key in `.env`.
- **D2** How long should the `?token=` WebSocket path stay after W2.2? Recommended one release.
- **D3** Two questions about W3.2 and W3.5:
  - Enforce the shell default-ASK after an observe batch, as with W3.7?
  - Enforce native Windows "network off" with a firewall rule, or document it as advisory?
- **D4** Groups G8 and G9: delete now, or keep the pieces a recorded plan wants to wire
  (`skill_promotion_gate`, `chain_of_verification`, the Valkey bridge, the verifiers)? Also
  whether `weebot/osworld/` (benchmark entry point) stays.

## 7. Order and dependencies

1. Wave 0 first. It decides which trace findings are real.
2. Wave 1 next, because A01 and A02 break features today. W1.1 and W1.2 are independent.
3. Wave 2: W2.2, W2.3 and the ownership half of W2.7 depend on W2.1. W2.4-W2.6, W2.8 and
   W2.9 do not.
4. Wave 3: W3.3 before G11. W3.4 needs nothing else. W3.2 waits on D3.
5. Wave 4: W4.1 first, because it is the smallest and protects the rest. Do W4.3 before W4.2;
   the lock is easier to reason about once there is one writer.
6. Wave 5 items are independent. W5.2 before W5.3.
7. Wave 6 after waves 1-5, so a deletion does not remove a test a fix depends on. G8 and G9
   wait on D4.

## 8. Done when

- Every A-test in `tests/unit/fixes/test_a27_*.py` is a plain passing test, or the finding is
  recorded here as not reproduced.
- Full suite, `ruff check .`, `lint-imports`, the ratchet scripts, the tasks and map index checks,
  and `check_map_citations.py --drift` all pass on the branch.
- Live checks the owner runs:
  - restart the API container, then confirm one scheduled job fires (A01);
  - send two Telegram messages in one chat (A02);
  - run a dispatch whose sub-agents move the parent's cost (A09).
- This file's frontmatter moves to `status: done` with the commit list.

## 9. Not covered

- Areas the audit did not read:
  - `weebot-ui` beyond the proxy;
  - sandbox backends other than native Windows;
  - all of `bash_security.py`;
  - most persistence repositories;
  - `flow_router.py`;
  - dead code inside `weebot/interfaces/` and `weebot/tools/`, which were counted as roots.
- Multi-replica deployment (phase 5 of `specs/arch_audit_2026_09_remediation_plan.md`) is
  unchanged. W4.2's lock and W4.6's JSON lock are per process, which is correct while the API
  is pinned to one replica.
