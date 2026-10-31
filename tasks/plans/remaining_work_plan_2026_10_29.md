---
status: open
date: 2026-10-29
supersedes: plans/master_plan_2026_10_27.md, plans/audit_2026_10_27_fix_plan.md
note: everything still open after the 2026-10-29 audit, checked against the code on fix/audit-2026-10-29 (89b8121e); eight waves, security and data loss first, decision-gated work after the owner decides, map and docs last; supersedes the open lists in master_plan_2026_10_27.md sections 3-4 and audit_2026_10_29_fix_plan.md section 7
---

# Plan: everything still open after the 2026-10-29 audit

## 1. How this list was made

Every item comes from one of four sources:

- the open lists in `tasks/plans/master_plan_2026_10_27.md`;
- section 7 of `tasks/plans/audit_2026_10_29_fix_plan.md`;
- the open items of `tasks/plans/audit_2026_10_27_fix_plan.md`;
- the out-of-scope list of the free-provider change.

Each item was checked against the code at `89b8121e`. Items found done are listed in section 2 and not planned again. Line numbers are approximate. Re-read the code before each fix.

Rules for every change stay as in the master plan:

- A failing test comes first.
- Ceilings are lowered, never raised.
- Run `scripts/prepush_gates.py`, then the map drift check, then the full suite before a push.
- A fix that needs an owner decision waits for it.

## 2. Checked and already done (not planned)

- **B1:** `scripts/prepush_gates.py` exists.
- **B2:** the aiosqlite thread test counts only its own pool's threads (`tests/unit/infrastructure/persistence/test_pool_close_reaches_every_connection.py:40-52`).
- **E2:** the drift check covers `map/effects/` (`scripts/check_map_citations.py:54-57`, `tests/unit/test_map_is_consistent.py:266`).
- **A22:** host classification is done.
- **A23:** prefix matching is done.
- **A27:** the sender-parse half is done.
- **A17:** the UI no longer sends `?token=`.
- **Free providers:** single-model roles skip `free/` ids (`role_primary_model`, `_create_llm_for_role`, `PlannerAgent`). A 429 trips only that model and falls back to the paid cascade.
- **ARCHITECTURE.md:** debt D2 is closed.

## 3. The waves, in order

The order follows four rules:

1. Fix what lets a regression through.
2. Then fix what leaks data or weakens a guard, as long as it needs no decision.
3. Then fix what loses or corrupts data.
4. Then fix broken features.

Work that waits on an owner decision comes after the owner decides. Structural debt and the map come last, because every earlier wave moves the code they describe. Sizes: S is under an hour, M is half a day, L is more.

### Wave 0: the gate catches what CI catches (S)

- **G1. Run every CI ratchet locally.** These four scripts run in `.github/workflows/` but not in `scripts/prepush_gates.py` or the Makefile:
  - `lint_unused_locals.py`;
  - `lint_bandit_b110.py`;
  - `lint_agent_json_parsing.py`;
  - `check_branch_protection.py` (network; mark it CI-only).

  The first two let PR 105 fail CI after a green local gate (fixed in `89b8121e`). Add them as Makefile targets so `prepush_gates.py` picks them up. Add a test that every `python scripts/*.py` step in the workflows has a local target or an explicit CI-only mark.
- **G2. Land PR 105.** It holds wave 6, D4, the free providers and the 2026-10-29 audit. Merging it merges `feat/wave6-lean`, `feat/d4-wiring` and `feat/free-providers` too, so they need no PRs of their own. This is an owner action.

### Wave 1: guards that fail open (no decision needed)

- **S1. Taint replay race** (`application/agents/executor/_tool_executor.py:229-241`, `_session_scope.py:90`), S.
  - **Problem:** `claim_hydration` marks the session hydrated before `await self._effect_ledger.flags(sid)`. A second parallel tool call in the same batch skips the replay and runs its egress check without the persisted taint. If `flags()` raises, the session is never replayed.
  - **Fix:** a per-session `asyncio.Lock` or future around the replay; mark it hydrated only after success, and release the claim on error.
  - **Test:** two parallel calls after a restart; the second waits and sees the taint.
- **S2. Tainted sessions reach `:free` models** (`_cascade.py:746` `_live_model_rescue`; ACR candidates near `:600`), S.
  - **Problem:** `keep_private` only knows `free/<provider>/` ids, so OpenRouter `:free` models, which may train on prompts, are never filtered. The live-model rescue and the ACR candidates skip the filter entirely.
  - **Fix:** `trains_on_prompts` returns True for `:free` ids, and `keep_private` runs on the rescue and ACR lists.
  - **Test:** a tainted session whose cascade 404s is never rescued onto a `:free` model.
- **S3. Swarm sub-agents can get a free model** (`application/agents/hyper_agent.py:125`), S.
  - **Problem:** `get_model_cascade_for_role(role)[0]` can return a `free/` id for a single-model sub-agent flow, which bypasses both the fallback and `keep_private`.
  - **Fix:** `role_primary_model(role) or SUBAGENT_TIER_MODEL[...]`.
- **S4. A23 rest: an undecodable base64 blob is allowed** (`tools/powershell_tool.py:108-128`, `except Exception: pass`), S.
  - **Fix:** delete the heuristic, since `has_encoded_command` already runs first and A30 asked for this copy to go. If it stays, fail closed.
- **S5. A27 rest: email trusts the topmost `Authentication-Results`** (`interfaces/gateways/email.py:54-70`), S-M.
  - **Fix:** accept only headers whose authserv-id is in a new `trusted_authserv_ids` setting (default: the IMAP host), and use the first trusted one.
  - **Test:** a forged header above the real one is ignored.
- **S6. R18b: rate-limit bucket keyed by an unverified key** (`interfaces/web/rate_limit.py:259-271`), S.
  - **Problem:** rotating junk keys get fresh buckets, and bearer clients fall back to the IP bucket.
  - **Fix:** call `authenticate(request)` (it caches on the scope) and key by the verified principal, else by IP.
- **S7. Error classifier matches digits inside ids** (`core/error_classifier.py:58-82`), S.
  - **Problem:** `req_4012ab` reads as AUTH, which fails fast with no retry; `429` or `500` inside a trace id picks the wrong backoff.
  - **Fix:** guard each code with `(?<![\w-])` and `(?![\w-])`.
  - **Test:** a table of messages with ids.

### Wave 2: data a delete leaves behind, or gets wrong

- **L1. Session delete cascade**, M.
  - **What survives a delete today:**
    - `session_constraints` and `correction_records` (SQLite `sqlite_state_repo.py:262-291`, Postgres `_role_stores.py:52-65`);
    - `trajectories` and `failure_signatures` (`trajectory_repo.py:46-104`);
    - the steering queue (`infrastructure/adapters/steering_adapter.py` `_queues`).

    User text in `evidence_span` and `original_output` stays, and orphan trajectories keep feeding skill optimisation.
  - **Fix:** a `delete_by_session_id` on each store. Register each in `_session_stores()` (`interfaces/web/dependencies.py:28-42`), and clear steering in `DeleteSession`.
  - **Test:** one session written to every store, then deleted, leaves no row behind.
- **L2. Knowledge-graph node owner** (`sqlite_knowledge_graph.py:206-211`, `postgresql/knowledge_graph.py:97-104`), S, needs decision D-KG. DONE (6532eae5, wave 2; `tests/unit/fixes/test_l2_kg_node_owner.py`).
  - **Problem:** re-saving a node never updates `source_session_id`. Deleting session A can remove a node session B relies on, and a node first written with `''` is never claimed.
  - **Recommendation:** fill only when empty (`COALESCE(NULLIF(old, ''), new)`). A node-to-session join table is the full fix (L) and is not needed now.
- **L3. Presence events become phantom sessions** (`infrastructure/event_bus.py:224-228`, `_journal_agent`), S.
  - **Problem:** an event with an empty `session_id` is journaled under its own uuid, and `log_event` creates an event-store session for it. Every status change of every run adds one phantom.
  - **Fix:** use `about_session_id` when present, and otherwise do not invent a session.
  - **Cleanup:** one script, run once, removes the phantoms (it deletes data, so it waits for the owner's OK).
- **L4. Event-store time filter** (`infrastructure/event_store.py:362-390`), S.
  - **Problem:** SQLite `CURRENT_TIMESTAMP` (`YYYY-MM-DD HH:MM:SS`) is compared as text with `isoformat()`, so same-day `start_time` filters return nothing. No production caller passes these filters today.
  - **Fix:** bind UTC `"%Y-%m-%d %H:%M:%S"`.
- **L5. `rerun_failed_session` never finds its factory** (`application/services/task_runner.py:510-551`), S.
  - **Problem:** `_cleanup` drops the retry state when the task ends, so `flow retry` always fails. The test at `test_task_runner_durable_state.py:147` hand-seeds the state and hides this.
  - **Fix:** take a `flow_factory` argument, as `resume_session` does, and have the CLI `flow retry` build one. That also works in a fresh process, where a cache could not.
  - **Test:** fail a run, then rerun it through the public API.

### Wave 3: features that do not do what they say

- **F1. Telegram `/new`, `/reset`, `/stop`** (`interfaces/gateways/telegram.py:222, 278-291`), M.
  - **Problem:** the commands only return text. `/new` reuses the old session. `/stop` is not even read until the run ends, because runs happen inline in the poll loop.
  - **Fix:**
    - `/new` and `/reset` call `self._flow_resolver.close(key)`;
    - each run becomes a tracked task per chat, so the poll loop keeps reading;
    - `/stop` cancels that task, inside `run_scope`, so the tools still tear down.
  - **Test:** `/new` then "hi" starts a fresh session; `/stop` mid-run cancels it.
- **F2. Behavior router ownership and `watch/start?directory=`** (`interfaces/web/routers/behavior_router.py`), S-M, needs decision D-BEH. DONE 2026-10-31 (6032de3d): session routes and sockets check ownership, recent actions and `/ws` drop other principals' sessions, `watch/start` only inside `WORKSPACE_ROOT`.
  - **Problem:**
    - Any authenticated caller reads any session's behavior data.
    - Any caller can stop another session's tracker.
    - Any caller can watch any directory on the host, and the path is echoed back.
  - **Recommendation:**
    - Confine `directory` to the workspace root with `is_relative_to`.
    - Call `verify_session_ownership` on the session routes.
    - Keep `/trust` and `/report` global, since they are aggregate.
- **F3. A17: drop `?token=` on WebSockets** (`interfaces/web/auth.py:96-102`), S, needs decision D2. DONE 2026-10-31 (f7d4abf5).
  - **Fix:** delete the fallback and flip the test that pins it, once no client uses it. The UI already sends the subprotocol.

### Wave 4: guards that wait on owner decisions

Run these only after the owner decides. Each one makes the agent ask more often.

- **P1. D3a: shell default-ASK to enforce** (`config/settings.py:220-225`, `application/services/tool_guards.py:184-207`), S.
  - **Before:** the owner runs one 12-task batch and counts `shell_default_ask would ask` in the log. The threshold is 2 or fewer asks.
  - **Fix:** the default becomes `enforce`.
  - **2026-10-30 batch:** 19 asks, so not flipped. First treat literal assignments, reads assigned to a variable, `Get-FileHash`, `Format-Table` and `--version` as reviewed (test first), then rerun the batch.
  - **Rerun (2026-10-30):** done, 12 asks; the rest are script blocks and inline code. Not flipped. Next, if wanted: add `Compress-Archive` to the `Output/` carve-out.
- **P2. D5: the untrusted-content guard (A11)**, M.
  - **Fix:** a tool guard in `default_guard_chain()` returns ASK for every non-read-only tool while `scope.is_tainted(session_id)`. Today taint only escalates egress, and the mail gate pauses only the next step.
- **P3. A21: egress beyond send verbs** (`core/egress_guard.py:87-114, 529-535`; strict xfails in `tests/unit/fixes/test_a21_egress_beyond_send_verbs.py`), M.
  - **Misses today:**
    - GET with a query string;
    - .NET `WebClient`;
    - `nslookup` and `Resolve-DnsName`;
    - in `python_execute`: `importlib`, `subprocess` calling curl, and unlisted libraries.
  - **Fix:** with P2 in place, treat any network-capable command in a tainted session as egress, rather than growing the regex list.
- **P4. D9: Windows network-off** (`infrastructure/sandbox/native_windows.py:82-95`).
  - **Recommendation:** keep it advisory, as `docs/SECURITY_MODEL.md:6` already says, and close D9. Enforcing it needs an admin-only firewall rule per program (L).

### Wave 5: structural debt in `ARCHITECTURE.md`

- **D4:** `plan_act_flow.py` is 772 lines, against a 700-line target. M. Extract the tool-result handling, with step-by-step tests first.
- **D5:** `executor/_base.py` is 780 lines, against a 650-line target and 800 cap. M. Extract the preamble. Do it before any new executor feature, which would cross 800.
- **D6:** `core/behavior_tracker.py` git operations move to `infrastructure/`, behind a port. M.
- **D1:** the four "stray root files" no longer exist at the `weebot/` root. Check where `tray` lives, then close D1. S.
- **Free-provider follow-ups**, S each:
  - check whether `ResilientLLMAdapter` retries a free model's 429 before the cascade sees it, and skip that retry for `free/` ids;
  - the circuit breaker trips after 5 failures per `CascadeExecutor` instance, so a spent daily quota costs requests until then. Optionally, share breaker state per process.

### Wave 6: repository, map and docs

- **R1. Dependabot config** (`.github/dependabot.yml`), S. DONE 2026-10-30 (8e6d1cca): rechecked on PyPI; anthropic 2.x is still blocked even by browser-use 0.13.14 (`<2.0`), openai 3.x waits on a browser-use upgrade, uuid-utils 1.x on langchain-core 1.7. Add a `python-major` group, and ignore majors for anthropic and openai (blocked by `browser-use==0.11.13`) and uuid-utils (blocked by `langchain-core`).
  - **The six blocked PRs:** #86, #90, #91, #83, #79, #13.
  - **Retest:** each is retested only when its blocker moves. `browser-use` is now at 0.13.14 on PyPI, so retest whether it still pins `anthropic<1.0` and `openai<3.0`.
- **R2. 30 stale map cards**, M-L. DONE 2026-10-30 (9f66403d): all 30 verified at 8e6d1cca. Found on the way: `handle_ponytail_command` (`interfaces/gateways/base.py:162`) had no caller, so the chat command did nothing; fixed 2026-10-30, every gateway now answers it after its sender check. Re-read each against the code, restore `verified` and restamp. Do it after waves 1-5, which move the code they cite. The drift check skips stale cards, so its 0 hides them.
  - **Areas:**
    - application: DI container, mediator, plan-act flow;
    - core guards: bash guard, command analyzer, egress guard;
    - domain: plan, ports, session;
    - infrastructure: browser, event bus, LLM adapters, SQLite repository, sandbox;
    - interfaces: CLI, chat gateways, MCP server, web API, web UI;
    - tools: base tool, browser, exec, integration, media, orchestration, web;
    - processes: flow turn, model cascade, session persistence, guard chain.
- **R3. Docs archive** (needs D8), S after approval. Twelve files are still in `docs/`: DONE 2026-10-31 (50ae1719): the remediation plan in `docs/` is archived as `ARCHITECTURE_REMEDIATION_PLAN_V2_8.md`, since the archive already held a different file of that name.
  - `ARCHITECTURE_ENHANCEMENT_PLAN.md`;
  - `ARCHITECTURE_EXCELLENCE_PLAN.md`;
  - `ARCHITECTURE_REMEDIATION_PLAN.md` and `_V2.md`;
  - `OPENCLAW_ADOPTION_PLAN.md`;
  - five `*_SUMMARY.md` files;
  - `SETUP_SUMMARY.md`;
  - `PROJECT_COMPLETE.md`.

  Make the referrer report first, then copy, verify and remove.
- **R4. Plan statuses.** DONE 2026-10-30 (8e6d1cca). Mark `audit_2026_10_29_fix_plan.md` done and update `master_plan_2026_10_27.md`, then run `scripts/gen_tasks_index.py`. Trim the `ARCHITECTURE.md` debt table after wave 5. S.
- **R5. pytest-xdist trial** (optional). Try it on a branch, and keep it only if few tests share state. M. DONE 2026-10-31 (18ceaed3): 6928 passed, 0 failed, 69 s against about 440 s; `make test` runs `-n auto`.

### Wave 7: live checks (each needs the owner's OK; some are billed) 

**Run 2026-10-31:**
- Groq (`free/groq/openai/gpt-oss-120b`) and Gemini (`free/gemini/gemini-2.5-flash`): a JSON reply and a tool call each, all correct, under 1 s.
- Telegram R10: a rejected token stops polling at once; an unreachable API backs off (3 calls in 12 s, growing gaps).
- Not runnable: the `TELEGRAM_BOT_TOKEN` (getMe 404) and `DISCORD_BOT_TOKEN` (`/users/@me` 401) in `.env` are rejected, so R09 and F1 wait for valid tokens and a person to message the bot.
- Billed `flow run`: `OPENROUTER_API_KEY` answers 401 "API key expired", so every OpenRouter call fell back to DeepSeek-direct. The planner override (`planner: openai/gpt-6-luna` in `.weebot/role_models.json`) could not be served, so R17 waits for a renewed key. The run's step was honestly verifiable, so it did not exercise R06.
- Modal: not run; the `modal` package is not installed and it needs a Modal account.

- Discord (R09) with the owner's application.
- Telegram (R10, and F1 once built) with a bot token.
- One billed `flow run`, to see an unverified step end FAILED (R06) and the planner use Haiku 5.5 (R17).
- One real Groq and one real Gemini call, with keys the owner puts in `.env`.
- The Modal sandbox backend. Postgres and Valkey were run live already.

### Wave 8: the enhancement backlog (owner triage, about an hour)

`tasks/_index.md` lists open specs with nothing built or only part built. None has a build, park or drop outcome yet. Each gets one, recorded in its frontmatter, before any of it is planned:

- `scientific-book-latex-plan.md`;
- `agentic_memory_fix_plan.md` (phases 5-8);
- `arch_audit_2026_09_remediation_plan.md` (phase 5);
- `bilevel_autoresearch_implementation_plan.md` (phases 3-4);
- `code_as_harness_implementation_plan.md` (phases 2-4);
- `memento_skills_implementation_plan.md` (phase 3);
- `reasoner_enhancements_plan.md` (phase 6);
- `skillclaw_auto_evolve_plan.md` (nothing built);
- `verbalized_sampling_implementation_plan.md` (the sampler has no caller: wire it or delete it);
- `weebot_unified_implementation_plan.md` (P1-P4);
- `review_gate_and_residual_work_plan.md` (A3, needs a human);
- `static_defect_audit_v3_execution_plan.md` (P3-P11);
- `ui_defect_hunt_v71_execution_plan.md` (W2-W8);
- `defect_hunt_v7_1_execution_plan.md` (round 2);
- `icm_fix_plan.md` and `remaining_fix_plan.md` (F28 mediator dispatch).

**UI defect hunt (the one build outcome): DONE 2026-10-31 on `fix/ui-defect-hunt`.** W2-W8 ran; 34 defects fixed across W1-W7, plus three backend fixes it surfaced (SSE drop-notice id, a `deleted` presence frame on delete, presence frames only to their owner). Verdict and five proposed consolidations: `tasks/audits/ui_defect_hunt_w8_seams.md`. The browser gates are still blocked on this host.

Never audited, and worth one audit each before new work lands there:

- the `weebot-ui` frontend;
- the MCP server;
- sandbox network isolation.

New providers (Mistral, NVIDIA NIM, OVH) are parked until Groq and Gemini prove out live. Each one is a table row, a settings field and a config-reference row, so S.

## 4. Owner decisions

| ID | Question | Recommendation | Blocks |
|---|---|---|---|
| D2 | Remove the `?token=` WebSocket fallback now? | DECIDED 2026-10-31: yes; F3 done | F3 |
| D3a | Shell default-ASK to enforce? | Not yet. 2026-10-30 batch: 19 would-ask lines in 12 runs (threshold 2), all false positives; 12/12 tasks correct. 13 are `$x = "literal"` assignments, 3 are reads the rule list lacks (`Get-FileHash`, `Format-Table`, `<exe> --version`), 1 is a read assigned to a variable, 2 run an agent-written script under `Output/`. Those read shapes now count as reads (fae7c211). Rerun: 12 lines, 12/12 correct, none of the old shapes. Left: 8 script blocks or subexpressions (`if (...) {...}`, `ForEach-Object {...}`, `"$(...)"`), 1 `python -c`, 1 `Add-Type`, 1 `Compress-Archive` into `Output/`, 1 script run. A regex cannot judge script blocks or inline code, so stay `observe`: enforce would add about one prompt per task. In a tainted session it already asks (D5) | P1 |
| D5 | Every non-read-only tool asks after untrusted content is read? | DECIDED 2026-10-30: yes; `Output/` writes and plain reads stay unasked. P2 and P3 done | P2, P3 |
| D6 | Apply `.github/rulesets/main.json`? | DECIDED 2026-10-30: yes; the owner runs the POST (an external write the agent may not make) | none |
| D7 | Draft PR #54 (LuaLaTeX): rebase or close? | DECIDED 2026-10-31: park (close the PR, keep `claude/session-n4trou`); the close is an external write the owner makes | none |
| D8 | Archive the twelve old plan and summary docs? | DECIDED 2026-10-31: yes; R3 done | R3 |
| D9 | Enforce Windows network-off with a firewall rule? | DECIDED 2026-10-30: no; it stays advisory, as documented. P4 closed | P4 |
| D-KG | Who owns a knowledge-graph node seen by two sessions? | DECIDED: the first session; fill only when empty; L2 done | L2 |
| D-BEH | What may the behavior panel show, and to whom? | DECIDED 2026-10-31: as recommended; F2 done | F2 |
| D-F | Build, park or drop each backlog spec | DECIDED 2026-10-31: 1 build (UI defect hunt W2-W8), 11 park, 4 drop; each outcome is in its record's `outcome:` frontmatter | wave 8 |

## 5. Done means

- Each wave lands on its own branch and PR, with a failing test first for every fix.
- The full suite, `prepush_gates.py` (with wave 0's new targets) and the map drift check pass.
- CI is green on the PR.
- This plan's frontmatter says which waves are done.
