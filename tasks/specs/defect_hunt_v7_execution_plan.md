# Autonomous Defect-Hunt (V7) — Whole-Codebase Execution Plan

**Created:** 2026-09-04
**Status:** Draft — not yet executed
**Protocol applied:** `AUTONOMOUS DEFECT-HUNT PROTOCOL — V7 (PROACTIVE)` (EGFV · RAR · MRADO · PCST)
**Scope:** `weebot/` + `cli/` (Python 3.12). `weebot-ui/` excluded — see §2.6.
**Recon executed:** 2026-09-04 on commit `0440f3a` (branch `claude/weebot-codebase-analysis-gwg92i`)

---

## 0. What this document is

The attached protocol is a **single-target** hunt loop (Phases 0→8). This plan does two things
the protocol itself demands but cannot do for you:

1. **Executes Phase 0 once, globally** — the environment census, scope bounding, threat model,
   and taxonomy instantiation. Results are recorded in §2 and are already **evidence-classified**.
2. **Decomposes the codebase into nine bounded hunt units ("waves")**, each of which runs the
   *full* Phase 0-Wave → Phase 8 loop with its own budget and its own coverage statement.

Evidence tags used throughout are the protocol's own: **[VF]** verified fact (observed or
demonstrated by an executed command), **[HYP]** hypothesis, **[UNK]** undecidable without
runtime, **[FALSE]** contradicted by evidence.

Everything in §2 and §7 tagged **[VF]** was produced by commands actually run against this
checkout; the exact commands are in Appendix A so any claim can be re-derived.

---

## 1. Why "run V7 over the whole codebase" cannot be executed literally

The request is to apply the protocol "in the whole codebase." Taken literally that is
**self-contradicting**, and the protocol says so itself:

> "Because a proactive hunt over an unbounded codebase never terminates, Phase 0 **bounds the
> hunt** before any code is read for suspicion." — Phase 0

Scale of the surface **[VF]**:

| Measure | Value |
|---|---|
| Python files (`weebot/` + `cli/`, excl. vendored) | 1,201 |
| Lines analysed by bandit | 116,705 |
| Modules in the import graph (`lint-imports`) | 869 files / 4,832 dependencies |
| Tests collected | 3,803 (31 deselected as `external`) |
| Flow state modules | 14 |

A single V7 pass over that surface would (a) never reach Phase 8, (b) produce an unfalsifiable
coverage statement, and (c) violate the Phase 5 fix-interaction check, because dozens of fixes
across unrelated subsystems would land in one undifferentiated batch.

**Therefore this plan runs V7 nine times over nine bounded surfaces.** Each run is independently
shippable and produces its own inventory, fixes, tests, and coverage statement. A partial
program — say, waves 0–3 completed and 4–8 not — is an explicitly valid outcome under the
protocol's own PARTIAL routing.

---

## 2. PHASE 0-GLOBAL: Environment & scope census

*Executed 2026-09-04. This section is the protocol's Phase 0 static census, done once for all waves.*

### 2.1 Static census **[VF]**

```
Language:        Python
Runtime:         3.12  (project requires >=3.12 per pyproject.toml)
                 ⚠ The recon container shipped Python 3.11.15 with zero project deps.
                    A 3.12 venv + full install via `uv` succeeded — see Appendix A.1.
Framework(s):    FastAPI/Starlette (web), FastMCP (MCP), Pydantic v2, APScheduler,
                 aiosqlite + sqlite3, Alembic, Playwright, Click (CLI)
Test framework:  pytest + pytest-asyncio (asyncio_mode = auto), pytest-timeout (60s),
                 hypothesis. Config in pyproject.toml [tool.pytest.ini_options].
Entry point(s):  cli/main.py  ·  run.py  ·  run_mcp.py  ·  weebot.interfaces.web.main
                 · weebot/scheduling (cron)  · gateways (Discord/Slack/Telegram/WhatsApp)
Invariants:      DOCUMENTED — .importlinter (7 contracts), AGENTS.md §Architecture Rules,
                 CLAUDE.md §Design Patterns, docs/adr/*
Build/lockfile:  requirements.txt + requirements.txt.lock; pyproject.toml is metadata-only
```

### 2.2 Baseline — the hunt's control group **[VF]**

Established before any hunting, because a defect hunt with a red baseline cannot attribute a
new failure to its own fix.

| Gate | Result |
|---|---|
| `pytest tests/unit/` | **2 failed**, 3595 passed, 107 skipped, 7 deselected, 3 xfailed — 140s |
| `pytest tests/ --collect-only` | 3803/3834 collected, **0 collection errors** |
| `lint-imports --config .importlinter` | **7 kept, 0 broken** |
| `ruff check weebot/ cli/` | **767 findings** (336 E501, 74 F401, 67 E402, …) |
| `bandit -c pyproject.toml -r weebot/ cli/` | 68 Low / High-confidence (B110), **non-blocking in CI** |
| `scripts/lint_async_io.py` | 83 reports over **53 unique sites** |
| `make check` (repo's own top-level gate) | **FAILS** — `lint-async-io` exits 1, and it is a `check` prerequisite (`Makefile:86`) |
| Billed-call risk during the run | **none** — no provider keys, no `.env`, `addopts` carries `-m "not external"` |

> **Baseline rule for every wave:** a wave does not start against a red baseline. The two
> failures below are Wave 0 work.

### 2.3 The instrument audit — the finding that reorders everything **[VF]**

The protocol's activation contract states:

> "Flagging correct code as defective is a defect of *this protocol* and is treated with the
> same severity as missing a real bug."

A hunt inherits the reliability of its detectors. Weebot's detectors were measured before use,
and **four of them are unreliable**:

| # | Instrument | Measured behaviour | Consequence |
|---|---|---|---|
| **I1** | `make lint-bare-except-pass` | **Exits 0** while an AST scan finds **139** except-handlers in `weebot/`+`cli/` whose entire body is `pass`. The Makefile regex requires `pass` on the *same line* as `except`; the ordinary two-line form cannot match. | A blocking gate in `make check` that checks nothing. |
| **I2** | `pyproject.toml` lint comments | Comment claims ruff's `"B"` selector "includes B110 try-except-pass" — **ruff has no B110** (it is a *bandit* code; ruff's equivalent is `S110`, and `S` is not selected). The per-file-ignore comment calls `B011` "bare except: pass without logging" — ruff's `B011` is `assert-false`. | The stated policy is not the enforced policy. |
| **I3** | `scripts/lint_async_io.py` | Reports **83 violations across 53 unique sites** (same line re-reported up to 4×, once per enclosing async def). Regex `\bopen\s*\(` also matches `aiofiles.open(...)` — `video_ingest_tool.py:360` is flagged although it is correctly async. | Over-counts and emits false positives; the "83" figure that justifies its non-blocking CI status is inflated. |
| **I4** | `tests/unit/test_architecture_fitness.py::test_core_no_application_imports` | Fails with `FileNotFoundError: 'lint-imports'` — it shells out to a binary that is only on `PATH` when the venv's `bin/` is. | Environment-fragile. **Note: this is *not* an architecture violation** — `lint-imports` itself reports the contract KEPT. The test could not run, it did not disagree. |
| **I7** | `make check` vs CI | `lint-async-io` is a prerequisite of `make check` (`Makefile:86`) and exits **1**, so **`make check` is red on a clean checkout**. It appears **zero** times in `.github/workflows/architecture.yml`. | The local "all checks" gate fails while CI is green. A gate that is always red is a gate nobody reads — and the divergence means local and CI disagree about what "passing" means. |

Two further drifts, lower severity **[VF]**:

- **I5** — `AGENTS.md:210` states CI enforces **≥60%** coverage; the workflow and `.coveragerc`
  both enforce **52%**.
- **I6** — `.importlinter` carries **67** `ignore_imports` entries; the tracked taxonomy
  (`tasks/plans/ignore_imports_taxonomy.md`) documents **52**. "7/7 KEPT" is a true statement
  *conditioned on 67 exemptions*, and the exemption set has grown since it was last inventoried.

**This is why Wave 0 exists and why it precedes every hunt wave.** It is not scope creep; it is
the precondition for the protocol's own epistemic guarantee.

### 2.4 Threat model for this system

Weebot is an autonomous agent that executes shell commands, writes files, drives a browser,
reads inbound email, and spends money on LLM APIs. Ranked by cost-if-real:

| Rank | Threat | Why it ranks here |
|---|---|---|
| **T1** | **Guard escape** — a destructive or exfiltrating action reaches the host | Irreversible, externally visible |
| **T2** | **Untrusted input → action** — injected content in scraped pages, inbound mail, or MCP output steers tool use | The agent's whole value depends on this boundary holding |
| **T3** | **Fail-open verification** — a gate reports "clean" while checking nothing | **Empirically this repo's dominant defect class** (see below) |
| **T4** | **Unbounded / mis-accounted spend** — retry amplification, orphaned parallel calls, cost telemetry that reads 0 | Silent money loss; no operator signal |
| **T5** | **State corruption / data loss** — session, plan, event, checkpoint, backup | Recovery depends on it being right |
| **T6** | **Liveness** — hangs, timeouts that never fire, deadlocks | An agent that hangs is indistinguishable from one that is working |
| **T7** | **Resource leaks** — subprocesses, file handles, DB connections, browser contexts | Degradation over long-running sessions |

**On T3.** `tasks/specs/test_suite_and_evidence_gate_repair_plan.md` already named this class:
findings A, B and C there "share one failure mode: a mechanism was wired up, looks present,
reports success — and does nothing." I1 above is a **fourth independent instance**, found in the
first hour of recon. T3 is therefore weighted above its blast radius would otherwise justify.

### 2.5 Defect taxonomy, instantiated for weebot

The protocol's default catalogue, pruned and ranked against the threat model. Waves 1–8 each
declare which classes they hunt; the union across waves is the program's coverage claim.

| # | Class | Weebot-specific instantiation | Threat |
|---|---|---|---|
| C1 | **Trust-boundary / input** | Guard bypass paths, path traversal, prompt injection, unvalidated MCP/webhook kwargs, deserialization | T1, T2 |
| C2 | **Fail-open control** *(added — not in the default catalogue)* | Any gate, validator, auditor, or linter whose failure mode is "report clean". Includes `except: pass` around a security decision, and a `None` guard object that silently disables enforcement | T3 |
| C3 | **Error & exception paths** | Swallowed exceptions, partial state on failure, missing rollback, failure returning a success-shaped result | T3, T5 |
| C4 | **Contract / dependency** | Assumptions library behaviour does not guarantee; adapter/port contract drift; provider responses omitting fields | T4, T5 |
| C5 | **Resource lifecycle** | Subprocess/file/DB/browser acquire-without-release, leak on error path, orphaned asyncio tasks | T7 |
| C6 | **Concurrency** | Shared mutable state across async/threads, check-then-act, unlocked counters, `await` holding a lock | T5, T6 |
| C7 | **State machine** | Illegal transitions, missing default case, TOCTOU on session state, resume-after-pause semantics | T5, T6 |
| C8 | **Type & serialization** | Silent coercion, `None` propagation, schema drift, LLM-JSON parse fallbacks | T4, T5 |
| C9 | **Boundary & arithmetic** | Off-by-one, empty/singleton collections, `zip` length mismatch, float comparison, division by zero | T5 |

C2 is an addition to the protocol's default taxonomy, justified by §2.4/T3. Everything else is
the protocol's list, re-worded to this system.

### 2.6 Scope declaration

**In scope** (`weebot/` + `cli/`), allocated across waves in §4.

**Out of scope, with reasons:**

| Excluded | Reason |
|---|---|
| `weebot/GitNexus-main/` | Vendored third-party; already excluded from ruff and bandit. A defect here is `[REQUIRES HUMAN REVIEW: defect in dependency]` per Phase 5, not an in-repo fix. |
| `weebot-ui/` (Next.js/TypeScript) | Different runtime, toolchain, and defect taxonomy. Has its own CI job. Warrants a separate V7 run with a JS-instantiated taxonomy — **not** folded into this one. |
| `weebot/qmd_integration/` | Omitted from coverage measurement (`.coveragerc`); optional subsystem gated on `llama-cpp-python`. Deprioritised, not discarded — a defect here is LOW severity by reachability. |
| `scripts/`, `examples/`, `Output/` | Excluded from ruff by project config; not runtime surface. **Exception:** `scripts/lint_async_io.py` and `scripts/check-secrets.sh` are *instruments* and are in scope for Wave 0. |
| Root-level `transcript*.txt`, `*.html`, `subs.en.vtt` | Working artefacts, not program surface. Repo hygiene is tracked separately as WI-18. |

**Global budget.** Three counters, per the protocol:

- `budget_spent` — **≤ 20 candidates generated and ≤ 12 investigated to verdict per wave**;
  **≤ 8 verified defects fixed per wave**. Nine waves ⇒ a program ceiling of ~108 investigated
  candidates. Reaching a wave's ceiling ends that wave and emits its coverage statement.
- `hunt_iterations` — cap **3** per region tier (protocol default). Exhausting it advances the
  hunt queue; it does not abort the wave.
- `fix_revisions` — cap **1** per defect. Exceeding ⇒ `[REQUIRES HUMAN REVIEW]`.

**Blocking condition check:** runtime ✅ determinable, entry points ✅ enumerated, scope ✅
bounded, source ✅ present. **No Phase 0 blocker. The hunt may proceed.**

---

## 3. Approach selection

Three materially different ways to organise a whole-codebase hunt were considered.

### Approach A — Risk-ranked subsystem waves
Bound each wave to one subsystem (security guards, flow engine, persistence, …), ordered by the
threat model; run a full V7 cycle per wave.

- **Assumes:** defects cluster by mechanism, and blast radius follows subsystem boundaries.
- **Strengths:** matches V7's structure one-to-one; each wave is a coherent, reviewable PR;
  fix-interaction checks stay tractable because interacting fixes are co-located.
- **Weaknesses:** cross-subsystem defects — usually the most interesting ones — fall between
  waves. **Mitigation:** an explicit seam wave (W8).
- **Failure mode:** a wave ships green while the defect lives in the seam it shares with the
  next wave.

### Approach B — Taxonomy-horizontal sweeps
One defect class at a time across the entire tree: all resource-lifecycle everywhere, then all
concurrency, and so on.

- **Assumes:** consistency-per-class matters more than locality.
- **Strengths:** the strongest possible coverage statement ("class C5 audited across 100% of the
  surface"); highly mechanisable with AST queries.
- **Weaknesses:** every PR touches the whole tree — unreviewable, and maximal regression risk.
  V7's fix-interaction check becomes intractable when 40 fixes span 9 subsystems.
- **Failure mode:** a 40-file PR that no reviewer can meaningfully approve, so it is approved anyway.

### Approach C — Instrument-driven / signal-first
Repair and extend the static detectors, then hunt only where they fire.

- **Assumes:** the detector corpus is a good proxy for the defect distribution.
- **Strengths:** highest candidates-per-unit-effort; every candidate is pre-grounded at a real
  location; naturally terminates; leaves permanent CI value behind.
- **Weaknesses:** **structurally blind to C2 (fail-open control)** — no linter detects "this gate
  reports clean while checking nothing." Recon confirms this is the repo's dominant class.
- **Failure mode:** a clean-looking hunt that misses exactly the class that keeps recurring.

### Recommendation — **A as the engine, C as Wave 0, B inside each wave**

Rationale, from evidence rather than preference:

- **C cannot lead.** Applied alone it would have missed I1 (a gate that exits 0 while 139
  handlers match), the latex fix-interaction regression, and the `output_path` escape — none of
  which any configured linter reports. But C *must go first*, because §2.3 shows four detectors
  are unreliable and A's candidate generation would inherit that noise.
- **B cannot lead.** Its PR shape is incompatible with V7's ≤15-line / ≤1-function fix
  constraint at aggregate scale.
- **B is excellent *within* a wave.** Once the surface is bounded to one subsystem, walking C1→C9
  systematically over it is precisely what makes the wave's coverage statement defensible
  per class rather than anecdotal.

**Rejected outright:** running V7 once over everything (§1) — it violates Phase 0's bounding
requirement and cannot terminate.

**Residual uncertainty:** the choice between A and B is genuinely close if the goal were a
one-shot compliance audit rather than a sequence of shippable changes. A is recommended because
weebot has a working CI, an active branch, and a review process — the plan optimises for
*landing* fixes, not for producing a report.

---

## 4. The wave plan

Ordering is `hunt_priority ≈ likelihood × blast_radius × reachability`, per Phase 1b.

| Wave | Surface | Classes hunted | Threats |
|---|---|---|---|
| **W0** | Instruments & baseline | — (repair, not hunt) | precondition |
| **W1** | Security & trust boundary | C1, C2, C3 | T1, T2 |
| **W2** | Verification & evidence gates | C2, C3, C8 | T3 |
| **W3** | Flow state machine & concurrency | C6, C7, C5 | T5, T6 |
| **W4** | Persistence & data integrity | C5, C7, C4, C9 | T5 |
| **W5** | LLM adapters, cascade & cost | C4, C8, C3, C6 | T4 |
| **W6** | External interfaces & non-human entry points | C1, C2, C3 | T1, T2 |
| **W7** | Tools & resource lifecycle | C5, C1, C9 | T7, T1 |
| **W8** | Seams & fix-interaction | cross-cutting | all |

---

### W0 — Instruments & baseline repair *(precondition, not a hunt)*

**Why first:** §2.3. Candidate generation in W1–W7 is only as trustworthy as the detectors that
seed it, and four detectors are measurably unreliable.

**Work:**

| Item | Action |
|---|---|
| I1 | Replace the `lint-bare-except-pass` regex with an **AST check** (`ast.ExceptHandler` whose body is exactly `[ast.Pass]`). Land it **non-blocking with a ratchet count of 139**, then reduce. Making it blocking on day one turns `make check` permanently red — which is how gates get ignored. |
| I2 | Correct the two `pyproject.toml` comments. Decide explicitly: either add `S110` to ruff's `select` (and set the ratchet), or delete the claim. Do not leave a comment asserting an unenforced policy. |
| I3 | Deduplicate `lint_async_io.py` reports by `(file, line)`; exclude `aiofiles.`/`anyio.` prefixed calls. Re-measure; the post-fix number is the real ratchet. |
| I4 | Make `test_core_no_application_imports` invoke import-linter via `sys.executable -m importlinter` (or skip cleanly when absent) instead of shelling to a bare `lint-imports`. |
| B1 | Fix the latex timeout regression — see §7.1. |
| I7 | Decide `make check`'s contract. Either bring `lint-async-io` into CI (with the post-I3 ratchet) or drop it from the `check` prerequisites. **A top-level gate that is red on a clean checkout teaches the team to ignore it** — the same failure mode as I1, one level up. |
| I5 | Correct `AGENTS.md:210` to 52%, or raise the CI floor. One of the two must move. |
| I6 | Re-inventory the 67 `ignore_imports` entries against the taxonomy doc. **No new entry may be added by any later wave** (see §6). |

**Exit criteria:** `pytest tests/unit/` green · `make check` green or every non-blocking gate
explicitly ratcheted with a recorded number · every instrument's baseline count committed to
`tasks/audits/defect_hunt_baseline.md`.

**Budget:** no candidate budget — W0 is bounded by the item list above.

---

### W1 — Security & trust boundary   *(T1, T2 · classes C1, C2, C3)*

**Surface:** `weebot/core/bash_guard.py`, `egress_guard.py`, `trust_boundary.py`, `approval.py`,
`approval_policy.py`, `output_path.py`, `weebot/tools/bash_security.py`, `bash_tool.py`,
`python_tool.py`, `powershell_tool.py`, `weebot/infrastructure/security/**`,
`weebot/infrastructure/sandbox/**`, `weebot/config/secret_accessor.py`,
`weebot/core/secret_redaction.py`, `weebot/core/credential_sanitizer.py`, the atomic-mail
inbound gate in `flows/states/executing.py`.

**Phase 1 regions, highest priority first** (reachability and blast radius from recon):

| R | Region | Why it ranks |
|---|---|---|
| R1 | Guard enforcement seam — `bash_tool.py`, `python_tool.py`, `powershell_tool.py` | Every shell path converges here; SYSTEM blast radius |
| R2 | Guard bypass inventory — every `subprocess`/`create_subprocess_*` site not routed through `BashGuard` | An unrouted path makes R1 moot |
| R3 | Path-resolution helpers — `output_path.py`, the `_sanitize_output_path` family | Arbitrary file write; **one already verified** (§7.2 S1) |
| R4 | EgressGuard resolution & enforcement — `_tool_executor.py` | C2: a `None` guard silently ungates egress |
| R5 | Trust-boundary fencing — `trust_boundary.py` name list vs registered tool names | C2: an unfenced untrusted tool is invisible |
| R6 | Secret classification & event sanitisation | Credential disclosure into events/DB/WebSocket |
| R7 | Inbound-mail approval gate | T2 entry point |

**Pre-seeded candidates:** §7.3 D1–D12.

**Budget:** ≤20 generated · ≤12 investigated · ≤8 fixed.

**Exit:** every R1–R7 region triaged or explicitly deferred with a reason · coverage statement
emitted · `tests/integration/test_security_penetration.py` extended with each proof test.

---

### W2 — Verification & evidence gates   *(T3 · classes C2, C3, C8)*

**Surface:** `application/services/step_evidence_auditor.py`, `step_evaluator.py`,
`plan_critic.py`, `meta_critic.py`, `chain_of_verification.py`, `skill_review_gate.py`,
`flows/states/verifying.py`, `critiquing.py`, `product_gate.py`, `premortem.py`,
`models/structured_output.py`, `application/eval/judges.py`,
`infrastructure/scoring/verifier_scorer.py`.

**The wave's governing question — apply to every gate on the surface:**

> *If this gate's own machinery fails, does it report a violation or report clean?*

A gate that reports clean on internal failure is a **C2 defect regardless of whether a trigger
input exists**, because its stated purpose is to be the thing that catches failures.

**Method (this is where Approach B lives):** enumerate every function on the surface returning a
pass/fail, score, or violation list. For each, construct the *instrument-failure* trigger —
storage misconfigured, LLM returns empty, JSON malformed, dependency missing — and observe the
return value. Any success-shaped return is a confirmed candidate.

**Pre-seeded candidates:** §7.3 D13–D18.

**Budget:** ≤20 · ≤12 · ≤8.

---

### W3 — Flow state machine & concurrency   *(T5, T6 · classes C6, C7, C5)*

**Surface:** `flows/plan_act_flow.py` (965 LOC), `flow_state_machine.py`, `state_graph.py`,
`base_flow.py`, all 14 modules under `flows/states/`, `_checkpoint_scheduler.py`,
`_iteration_context.py`, `agent_session_manager.py`, `flows/collaborators/`, `chat_flow.py`,
`hyper_agent_flow.py`.

**Regions:** transition table completeness (missing default case per state) · pause/resume
semantics, including flags cleared *before* the pause they gate · shared mutable state crossing
async boundaries (module-level dicts, class-level caches, singletons) · orphaned `asyncio` tasks
on the error path · checkpoint scheduling vs state mutation ordering (TOCTOU).

**Note:** `executing.py:277` clears `atomic_mail_inbound_pending` *before* raising the pause
event — flagged in recon as **[HYP]**; it is a C7 candidate for this wave, cross-listed with W1/R7.

**Pre-seeded candidates:** §7.2 **S5** (both declared transition tables are dead — verified) and
§7.3 D19–D29.

**Budget:** ≤20 · ≤12 · ≤8. Expect a high `[UNK]` residual — concurrency interleavings are the
canonical "cannot be decided statically" case. Per Phase 3a, non-deterministic candidates get a
repeated-trial harness (N ≥ 100) and are labelled **STATISTICAL**, never deterministic [VF].

---

### W4 — Persistence & data integrity   *(T5 · classes C5, C7, C4, C9)*

**Surface:** `weebot/infrastructure/persistence/**`, `event_store.py`, `checkpoint_store.py`,
`alembic/versions/**`, `scripts/backup.py`, `scripts/restore.py`,
`scheduling/default_jobs.py` (`_database_backup_job`).

**Regions:** transaction boundaries and atomicity across plan+events · connection lifecycle
(per-call vs pooled) and leak-on-error · WAL configuration and concurrent-writer behaviour ·
migration/code column-name agreement (this class has bitten the repo before — defect #11 in
`implementation_audit_report.md`) · backup round-trip integrity.

**Known gap to close, not hunt:** `implementation_audit_report.md` §6 records "No tests for
backup.py / restore.py / `_database_backup_job`". A subsystem whose last three defects were
CRITICAL and which has no tests is the highest-value place in the repo to add proof tests.

**Pre-seeded candidates:** §7.2 **S4** (37 verified sqlite connection leaks) and §7.3 D30–D38.

**Budget:** ≤20 · ≤12 · ≤8.

---

### W5 — LLM adapters, cascade & cost   *(T4 · classes C4, C8, C3, C6)*

**Surface:** `infrastructure/adapters/llm/**`, `infrastructure/llm/langchain_adapter.py`,
`core/circuit_breaker.py`, `utils/backoff.py`, `application/agents/executor/_cascade.py`,
`_context_compressor.py`, `_tool_executor.py`, `core/model_cascade_config.py`,
`model_cascade_tracker.py`, `models/structured_output.py` (shared with W2),
`config/model_refs.py`.

**Regions:** timeout coverage on every adapter construction path · retry amplification
(SDK retries × `RetryWithBackoff` × cascade loop) · circuit-breaker key/state consistency and
thread-safety · orphaned parallel probes on the cascade's `FIRST_COMPLETED` path · cost/token
accounting completeness · LLM-JSON parse fallbacks (C8).

**Pre-seeded candidates:** §7.3 D39–D44. One (**S3**) has a verified mechanism.

**Special note on this wave:** cost-accounting defects are *silent by construction* — the
symptom is a number that reads 0.0. Proof tests must assert on the *accounting*, not on the call
succeeding.

**Budget:** ≤20 · ≤12 · ≤8.

---

### W6 — External interfaces & non-human entry points   *(T1, T2 · classes C1, C2, C3)*

**Surface:** `weebot/interfaces/web/**` (auth, CORS, middleware order, WebSocket, all routers),
`weebot/mcp/**`, `run_mcp.py`, `interfaces/gateways/**` (Discord/Slack/Telegram/WhatsApp),
`weebot/scheduling/**` (cron triggers agent runs — a non-human entry point), `cli/**`.

**Regions:** per-route auth posture vs global-middleware reliance · WebSocket authentication vs
**authorisation** (a session subscription is not the same as ownership) · webhook signature
verification ordering · MCP transport auth when constructed outside `run_mcp.py` ·
`.env.example` defaults vs code defaults (a template that ships a weaker default than the code
is a real deployment defect) · dynamic-tool kwargs validation.

**Pre-seeded candidates:** §7.3 D45–D50.

**Budget:** ≤20 · ≤12 · ≤8.

---

### W7 — Tools & resource lifecycle   *(T7, T1 · classes C5, C1, C9)*

**Surface:** `weebot/tools/**` (48 modules), `infrastructure/browser/**`,
`infrastructure/document/**`, `tools/video_ingest_tool.py`, `image_gen_tool.py`,
`video_gen_tool.py`, `youtube_download_tool.py`, `screen_tool.py`, `scraper.py`.

**Regions:** subprocess lifecycle (kill/drain/orphan — the finding-G class) · file handles opened
without a context manager · browser context/page release on the error path · unvalidated
caller-supplied output paths (cross-listed with W1/R3) · `zip()` without `strict=` where lengths
can diverge (14 sites) · `except: pass` sites inherited from the W0/I1 ratchet.

**Budget:** ≤20 · ≤12 · ≤8. Largest surface, lowest per-region blast radius — expect this wave
to hit its budget ceiling and terminate PARTIAL. That is the expected, honest outcome.

---

### W8 — Seams & fix-interaction

**Not a new surface — a review of everything W1–W7 changed.**

Justification: Phase 5's fix-interaction check is per-wave; nothing in the protocol checks
interactions *across* waves. The repo has already paid for this gap once — **B1** (§7.1) is a
verified case where a fix from one work item silently disabled the proof test of another.

**Work:** re-run the full taxonomy against every changed region (Phase 6 vector 6) · check
whether any W_i fix altered the reachability or trigger of any W_j candidate — including
candidates previously **CLEARED**, since innocence defences can be invalidated by a later change ·
re-run every proof test from every wave together · full `make check`.

**Budget:** bounded by the set of changed regions, not a candidate count.

---

## 5. Per-wave runbook

Every wave executes this loop. Deviations must be recorded in the wave's audit file.

```
PHASE 0-WAVE   Restate scope, budget, and the taxonomy classes this wave hunts.
               Confirm the baseline is green. A red baseline halts the wave.

PHASE 1        Enumerate regions R1..Rn on the wave surface. For each record:
                 defect classes present · entry reachability (REACHABLE from <entry>
                 via <path> / GUARDED / UNKNOWN / DEAD) · blast radius · invariant density.
               Rank into a hunt queue. State >=3 atomic assertions about the map itself,
               each tagged [VF]/[HYP]/[UNK].

PHASE 2        Generate candidates D[N] from the top of the queue. Each MUST name:
                 the violated property · a specific file:line · the triggering condition ·
                 the consequence · severity · prior · and an INNOCENCE PATH.
               "This looks sketchy" is rejected. Do not regenerate cleared candidates.

PHASE 3        Per candidate, highest expected-risk-reduction first:
                 3a Trigger test  — executable, from a real entry point, respecting documented
                    invariants, not mocking away the suspected mechanism.
                    Non-deterministic -> N>=100 harness, result labelled STATISTICAL.
                    No executable trigger writable -> candidate stays [UNK], routed to Phase 8.
                 3b Innocence attempt — adversarially defend the code: find the guard, prove
                    unreachability, or name the holding invariant.
               CONFIRMED only if trigger FIRED and innocence found no defence.

PHASE 4        Triaged inventory table: VERIFIED DEFECT / SUSPECTED / FALSE (innocent) / UNKNOWN.
               Record the innocents — they document coverage and prevent re-raising.
               No numeric confidence. Rank verified defects by severity x reachability x blast.

PHASE 5        Fix, in inventory order. <=15 lines, <=1 function, causal not symptomatic.
               Cross-boundary -> [REQUIRES HUMAN REVIEW]. Dependency -> MITIGATION + escalation.
               Run the fix-interaction check across this wave's fixes before finalising.

PHASE 6        Self-review, six vectors: boundary · invalid input · state · regression ·
               concurrency · new-defect-introduction. Tag verdicts [VF]/[HYP].
               FIX BREAKS -> one revision, then re-run all six. Second break -> escalate.

PHASE 7        Per verified defect: proof-of-defect test (red before, green after) +
               >=2 boundary tests + >=1 no-regression test. Every Phase 6 [HYP] on
               boundary/concurrency/new-defect becomes an executable test or is downgraded.

PHASE 8        Process checks, engineering checks, and the mandatory
               COVERAGE & RESIDUAL-RISK STATEMENT. Route ACCEPT / RE-ITERATE / ESCALATE / PARTIAL.
```

**Hard rule on Phase 3b.** Recon produced two illustrative near-misses (§7.4): a ruff `B023`
closure warning and a ruff `F601` duplicate-key warning, both of which are most likely
behaviourally inert. Under this plan a static-analysis hit is a **candidate, never a defect**.
Fixing a linter finding without an innocence attempt is a protocol violation.

---

## 6. Architecture invariants every fix must preserve

These are weebot-specific and non-negotiable. They convert "respect the architecture" into
checkable conditions.

1. **`lint-imports` stays 7/7 KEPT** after every fix. Run it per fix, not per wave.
2. **No new `ignore_imports` entry may be added to make a fix pass.** Adding one converts an
   architecture violation into a permanent exemption — masking, which Phase 5 forbids. If a fix
   requires one, it is `[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`.
3. **Dependency direction holds:** `Interfaces → Infrastructure → Application → Domain`.
   `weebot/domain/` stays pure — a domain fix that needs an outward import is the wrong fix.
4. **Fix through ports, not around them.** A fix that reaches past a port to a concrete adapter
   is symptomatic by construction.
5. **`weebot/application/di/` is the composition root** — the only place permitted to know both
   `weebot.config` and `weebot.infrastructure` concretes. Wiring fixes belong there
   (precedent: finding A1 in the test-suite repair plan).
6. **Changing a port signature is automatically cross-boundary** ⇒ `[REQUIRES HUMAN REVIEW]`,
   no exceptions, regardless of line count.
7. **Structured output stays Pydantic-validated** — a fix must not widen a model to `Any` or
   add a bare-dict escape hatch to make a parse succeed.
8. **All shell execution routes through `BashGuard`.** A fix that adds a new subprocess call site
   must route it, or justify the exemption in the wave audit file.
9. **`make check` passes before a wave PR is opened** — tests, arch gates, import-linter, and
   every lint ratchet at or below its recorded baseline.
10. **No fix lands without its Phase 7 tests in the same commit.** A fix and its proof test are
    one unit of work.

---

## 7. Pre-seeded candidate inventory

Produced during Phase 0/1 recon. **This is the wave entry material — it is not a defect list.**
Everything below carries its evidence tag; only **[VF]** items have been demonstrated.

### 7.1 B1 — Verified fix-interaction regression **[VF]** *(Wave 0)*

`tests/unit/test_latex_document.py::test_compile_timeout_returns_result_instead_of_hanging`
**fails on the current HEAD.**

Observed directly:

```
elapsed=0.01  ok=False
ERROR category=CompileErrorCategory.UNKNOWN
      msg='Required font(s) not installed: GFS Didot, GFS Neohellenic'
```

The test monkeypatches `_build_command` and sets `timeout_seconds=1` to exercise the
orphaned-grandchild timeout path added by commit `9cd2d1d` (finding G). The font-dependency
validation added by commit `0440f3a` (findings E/F) short-circuits **before** the compile is
launched, so the timeout path is never reached and the asserted `TIMEOUT` category never appears.

- **Violated property:** the proof test for finding G must remain able to reach the timeout path.
- **Class:** C3 (error path) + fix-interaction.
- **Severity:** HIGH — not because the LaTeX pipeline is critical, but because *the regression
  guard for a verified production-hang defect is now inert*. That is a C2 failure about a C6/T6 defect.
- **Why it belongs in W0:** the baseline must be green before hunting starts, and this is one of
  the two failures.
- **Note for the fix:** the correct repair is to the *test's* setup (bypass or satisfy the font
  precondition so the timeout path is reachable), not to weaken the font validation. Confirm
  which by checking whether production callers can reach `compile()` with fonts absent.

### 7.2 Executably verified code seeds **[VF]**

| ID | Location | Demonstrated behaviour | Class | Wave |
|---|---|---|---|---|
| **S1** | `weebot/core/output_path.py:41` | `output_path("/etc/passwd")` returns `"/etc/passwd"`. The `..` guard at `:32` passes (no `..` segments); `os.path.abspath` does not start with the project root; `str(_PROJECT_ROOT / relative)` then discards the left operand because `relative` is absolute. **Violated property:** the docstring's "resolve to an absolute path under the project Output dir." `output_dir()` subsequently `os.makedirs()` the parent. | C1 | W1 |
| **S2** | `weebot/models/structured_output.py:194-219` | `parse_agent_output` **never raises**. Malformed input returns `WeebotOutput(status=PARTIAL)`; `""` returns `FAILED`; even well-formed-but-incomplete JSON returns `PARTIAL`. **Violated property:** a caller cannot distinguish "the model reported PARTIAL" from "we failed to parse." *Nuance: returning PARTIAL for incomplete input is defensible; the defect is the indistinguishability, plus the `''`→FAILED vs `'not json'`→PARTIAL inconsistency.* | C2, C8 | W2/W5 |
| **S4** | 37 sites across 10 modules (`persistence/checkpoint_store.py`, `strategy_store.py`, `skill_variant_store.py`, `posterior_repository.py`, `meta_improvement_log.py`, `sqlite_summary_repo.py`, `sqlite_misalignment_journal.py`, `scheduling/scheduler.py`, `mcp/resources.py`, `interfaces/cli/support.py`) | `with sqlite3.connect(...) as conn:` — the sqlite3 connection context manager **commits the transaction; it does not close the connection**. Demonstrated: executing on `conn` after the `with` block still succeeds. **Violated property:** each call leaks a connection and its file descriptor. `checkpoint_store.py` additionally targets the same `sessions.db` the aiosqlite pool holds open. | C5 | W4/W7 |
| **S5** | `flows/flow_state_machine.py:21-33` and `flows/state_graph.py:91-154` | **Both declared transition tables are dead.** `FlowStateMachine` has zero references outside its own module; `FlowRouter._get_graph` (`flow_router.py:34`) has no callers. Real transition authority is ~40 imperative `context.set_state(...)` calls. **Violated property:** the architecture documents a declarative state machine that does not execute — and `flow_router.py:95-168` duplicates the same priorities imperatively, so the two can drift silently. | C7 | W3 |
| **S3** | `weebot/application/agents/executor/_cascade.py:303` | `getattr(resp, "usage", {}).get(...) if hasattr(resp, "usage") else 0` raises `AttributeError` when `usage is None`. The `hasattr` guard is vacuous — `usage` is always a declared field. Adapters explicitly set `usage=None` when a provider omits it. **Mechanism [VF]; reachability [HYP]** — requires a provider response without usage, to be confirmed in W5 Phase 3a with a fake adapter. | C4, C8 | W5 |

### 7.3 Static candidates from recon — **all [HYP]**, entry material for Phase 2

These were produced by static reading. **None has had a trigger test or an innocence attempt.**
Each must enter its wave's Phase 2 in the protocol's candidate format before it may be acted on.

**Wave 1 — security & trust boundary**

| ID | Location | Claimed violated property |
|---|---|---|
| D1 | `tools/screen_tool.py:77-79` | `open(save_path,"wb")` with no path validation — arbitrary write |
| D2 | `tools/image_gen_tool.py:549-555, 690-697` | `path.write_bytes()` on raw `Path(output_path)`, bypassing `_sanitize_output_path` |
| D3 | `image_gen_tool.py:779`, `video_gen_tool.py:214`, `youtube_download_tool.py:284` | `str(resolved).startswith(str(_SAFE_BASE))` — prefix check admits a sibling directory; `_SAFE_BASE` is CWD-derived in the latter two |
| D4 | `application/agents/executor/_tool_executor.py:104-110` | EgressGuard resolution failure sets the guard to `None` and outbound calls proceed ungated (**C2**) |
| D5 | `tools/bash_tool.py:284-291` | Analyzer exception downgrades to the weaker legacy regex list (**C2**, fail-open on the strongest layer) |
| D6 | `core/bash_guard.py:440-442` | Invalid regex patterns silently dropped with no log — a typo removes a BLOCKED rule invisibly (**C2**) |
| D7 | `tools/bash_tool.py:395` / `python_tool.py:151` | Only `BLOCKED` blocks; `DANGEROUS` delegates to `ExecApprovalPolicy` — verify that policy's no-match default |
| D8 | `infrastructure/security/state_verifier.py:501` | `create_subprocess_shell(command)` — raw shell, no BashGuard on the path |
| D9 | `config/secret_accessor.py:34-41,184` | `*_URL` classified non-secret ⇒ credential-bearing connection strings DEBUG-logged verbatim |
| D10 | `flows/event_publisher.py:110-118`, `collaborators/event_emitter.py:77-84` | Credential sanitisation applies only to user `MessageEvent`; tool args/outputs persist unsanitised |
| D11 | `core/trust_boundary.py:36-63` | Untrusted-tool list keyed on names that do not match registered tool names (`browser_tool` vs `browser_navigator`, etc.) ⇒ output not fenced (**C2**) |
| D12 | `flows/states/executing.py:277` | Inbound-mail pending flag cleared *before* the pause it gates ⇒ resume proceeds unconditionally (**C7**) |

**Wave 2 — verification & evidence gates**

| ID | Location | Claimed violated property |
|---|---|---|
| D13 | `application/services/step_evaluator.py:104-112` | Any exception returns `passed=True, score=1.0` — a broken evaluator passes every step (**C2**) |
| D14 | `application/services/step_evaluator.py:93` | `json.loads(resp.content or "{}")` ⇒ empty content yields the same success default |
| D15 | `application/services/conversation_compressor.py:137` | Compression failure returns `"(compression failed: …)"`, which is truthy at `_context_compressor.py:113` ⇒ the conversation middle is replaced by the error string |
| D16 | `application/services/trajectory_builder.py:74-79` | LLM failure yields an analysis with empty `failure_modes` — a clean-looking trajectory |
| D17 | `infrastructure/scoring/verifier_scorer.py:84` | Bare `json.loads(response.content)` where content can be `""` |
| D18 | `models/structured_output.py:430-436` | `parse_sampled_distribution` returns an empty distribution on any failure (documented "fail-open") |

**Wave 3 — flow state machine & concurrency**

| ID | Location | Claimed violated property |
|---|---|---|
| D19 | `flows/states/meta_analysis.py:36` | `status = None` on a base class typed `AgentStatus`; `plan_act_flow.py:552` assigns it, so `flow.status` becomes `None` mid-flow. Any consumer doing `flow.status.value` raises (**C8**) |
| D20 | `flows/states/executing.py:707-722` | Terminate-with-next-step path returns **without any `set_state`**; re-entering the same state type means `plan_act_flow.py:701-704` never resets `prompt_consumed` and `_state_entered_at` is never refreshed (**C7**) |
| D21 | `flows/states/updating.py:108-111` | `UpdatePlanCommand` failure returns to `ExecutingState`, which re-runs the same failing step — livelock bounded only by `max_iterations` (**C7**) |
| D22 | `flows/states/reviewing.py:142` | `else: # "reject"` — any unrecognised verdict string silently marks the step FAILED (**C7**, missing default case) |
| D23 | `interfaces/web/routers/behavior_router.py:394-399` | `asyncio.get_event_loop()` + `loop.create_task(...)` called **from the watchdog observer thread**; `create_task` is not thread-safe and `get_event_loop()` raises in a non-main thread on 3.12 — swallowed by `except Exception` at `:398`, so events are dropped silently (**C6, C2**) |
| D24 | `infrastructure/event_bus.py:93-114, 155-160` | `subscribe`/`unsubscribe` mutate `_handlers` without `self._lock`; the lock guards only the publish-side snapshot (**C6**) |
| D25 | `infrastructure/event_bus.py:105-114` | `subscribe_by_type` appends a closure, so `unsubscribe(handler)` can never remove it — permanent handler leak (**C5**) |
| D26 | `interfaces/web/websocket.py:68-72` and `behavior_router.py:205-228` | Sequential `await send` with no timeout; the latter holds `_ws_lock` **across** the send loop, so one hung client stalls every subscriber and all connect/disconnect (**C6, T6**) |
| D27 | `core/activity_stream.py:57-80, 110` | `push()` is sync but calls `ensure_future` — raises off-loop, caught and downgraded to debug (**C2**). `recent()` indexes a `defaultdict`, inserting a permanent empty deque per unknown project; per-project deques have no `maxlen` (**C5**) |
| D28 | `core/approval.py:354` | `input(...)` inside `async def console_approval_callback` — blocks the entire event loop on stdin (**T6**) |
| D29 | `services/task_runner.py:142` | `t.exception()` inside `add_done_callback` raises `CancelledError` when the task was cancelled (**C3**) |

**Wave 4 — persistence & data integrity**

| ID | Location | Claimed violated property |
|---|---|---|
| D30 | `persistence/connection_pool.py:118,132` vs `:57` | Constructor `timeout=30.0` is used only for the read-queue `wait_for` and is **not passed to `aiosqlite.connect`**; no `PRAGMA busy_timeout` is set, so writers fall back to sqlite's 5 s default. No `database is locked` retry anywhere in the pool (**C4**) |
| D31 | `sqlite_state_repo.py:100-104`, `event_store.py:451-455` vs `connection_pool.py:330` | `close()` closes the pool but never removes it from the module-level `_pool_registry`; the next `get_or_create_pool()` for that path returns the **closed** pool and raises. Closing the event store can brick the state repo when paths coincide (**C5, C7**) |
| D32 | `sqlite_state_repo.py:247-318` | `save_session` spans **three separate write transactions** (per-commitment loop, session row, FTS5 index) — a crash or lock error between them leaves partial state (**C7**) |
| D33 | `sqlite_state_repo.py:314-318` | `index_event` failure is logged, yet the `_fts5_indexed` watermark still advances — those events are permanently absent from search (**C2, C3**) |
| D34 | `sqlite_state_repo.py:272-285` | The "event bloat guard" builds a truncated payload and never uses it; `_session_queries.py:31-38` re-runs the identical truncation. Two copies of one rule, only one of which resets the FTS watermark |
| D35 | `session_persistence_adapter.py:37` | `PERSISTENCE_RETRY_CONFIG` leaves `retryable=None`, so **every** exception is retried — including permanent ones (`ValidationError`, `IntegrityError`) (**C4**) |
| D36 | `persistence/connection_pool.py:289` | `close()` drains only the idle queue; a checked-out read connection is never closed, leaking its aiosqlite worker thread (**C5**) |
| D37 | `infrastructure/browser/playwright_adapter.py:76-155` | `start()` has no cleanup if `new_context`/`new_page` raises after `launch()`; `close()` has no `try/finally`, so a failure closing the context leaks the browser and driver (**C5**) |
| D38 | `qmd_integration/mcp_client.py:239` | `subprocess.Popen(...)` assigned to a local — never stored, waited, or terminated: orphaned process plus leaked pipes on every call. `:514` `terminate()` without `wait()` leaves a zombie (**C5**) |

**Wave 5 — adapters, cascade & cost**

| ID | Location | Claimed violated property |
|---|---|---|
| D39 | `_cascade.py:429-443` | `asyncio.wait(FIRST_COMPLETED)`: if the first completer *failed*, pending probes are never cancelled nor awaited — they keep running and billing (**C5, C6, T4**) |
| D40 | `_cascade.py:148-162` | Credit-check failure returns `0`, which the filter reads as "below threshold" ⇒ a failed check strips every model from Phase 1 (comment claims fail-open; behaviour is fail-closed) |
| D41 | `resilient_adapter.py:185` vs `:370,385,394` | Breaker keyed on `model or self._model_name` but inspected/reset on `self._model_name` only ⇒ wrong breaker reported and reset under cascade use |
| D42 | `adapter_factory.py:298` vs `:151` | Cache key built with 3 parts on read, 4 on write ⇒ `get_adapter()` never hits |
| D43 | `_cascade.py:207` + all `_record_decision` call sites | `cost_estimate` never assigned ⇒ tracker `total_cost_estimate` is structurally always 0.0; `estimate_cost()` exists and is never called |
| D44 | concrete adapters (`openai_adapter.py:53`, `anthropic_adapter.py:20`, `openrouter_adapter.py:67-69`) | No client HTTP timeout; the only timeout is `resilient_adapter.py:315` and it is **per-attempt**, not per-call. Any construction path bypassing `AdapterFactory` has no timeout at all (**T6**) |

**Wave 6 — external interfaces**

| ID | Location | Claimed violated property |
|---|---|---|
| D45 | `interfaces/web/main.py:580-602` | `/ws/sessions/{session_id}` authenticates but never calls `verify_session_ownership` — the HTTP path at `routers/sessions.py:126` does |
| D46 | `.env.example:130` vs `interfaces/web/auth.py:223` | Template ships `WEEBOT_ENFORCE_SESSION_OWNERSHIP=false`; code defaults `true` — copying the template weakens isolation |
| D47 | `mcp/server.py:127-138` | `token_verifier=None` when `WEEBOT_MCP_API_KEY` unset; only `run_mcp.py:102-113` enforces it, so other construction paths yield an unauthenticated SSE server |
| D48 | `mcp/server.py:195-220` | Dynamic tools forward unvalidated `**kwargs` straight to `tool.execute()` |
| D49 | `interfaces/web/main.py:414` and `:511` | Two `@app.exception_handler(Exception)` registrations; the second silently overrides the first |
| D50 | `interfaces/web/event_broadcaster.py:39-43` | Events lacking `session_id` broadcast to **all** global connections |

**Cross-cutting counts to work down (not individual candidates):** 831 `except Exception`
handlers; 139 whose body is exactly `pass`; 73 bare `os.getenv`/`os.environ` reads outside
`weebot/config/`; 53 unique blocking-I/O-in-async sites; **37 `with sqlite3.connect(...)`
connection leaks**; 14 `zip()` without `strict=`; 15 `raise` without `from` inside `except`;
6 `asyncio.gather` call sites without `return_exceptions=True` on paths that mutate state.

### 7.4 Illustrative innocents — why Phase 3b is mandatory **[HYP-innocent]**

Two static-analysis hits examined during recon that most likely are **not** defects:

- **ruff `B023` at `tools/tool_registry.py:550`** — "function does not bind loop variable `_c`".
  The lambda is created only when `flow_factory is None`, and creating it assigns `flow_factory`,
  so the branch executes at most once per call. The late-binding hazard B023 warns about appears
  unreachable. *Residual concern, separate from B023:* the surrounding `except Exception: pass`
  discards DI construction failures silently — that is a genuine C2/C3 candidate for W7.
- **ruff `F601` at `config/_catalog_validator.py`** — duplicate `"thinkingmachines"` key. Both
  occurrences map to `"openrouter"`, so the duplicate is behaviourally inert; the second entry is
  dead, not wrong.

Under Phase 4 both would be recorded as **FALSE (innocent)** — recorded, not discarded, so the
same alarm is not re-raised in a later wave.

---

## 8. Fix policy in this codebase

The protocol's `≤15 lines / ≤1 function` constraint interacts badly with weebot's larger modules
(`_catalog.py` 5,837 LOC; `_base.py` 1,083; `plan_act_flow.py` 965; `executing.py` 759).
Rather than rediscovering this per wave, the policy is set here.

- **Default:** the constraint holds. Most confirmed defects in the seeds above are one-line or
  few-line causal fixes (S1, S3, D41, D42, D49).
- **`[CONSTRAINT-FORCED ESCALATION]`** is expected to be common in the application layer and
  **must be recorded explicitly**, so a reviewer can tell a genuinely risky fix from a policy
  artefact. A legitimate caller+callee two-function fix is escalated, not split into two
  half-fixes.
- **Automatic `[REQUIRES HUMAN REVIEW]`**, regardless of size: any port signature change (§6.6);
  any fix needing a new `ignore_imports` entry (§6.2); any fix to a security guard that widens
  what it permits; any change to Alembic migration history.
- **Symptomatic fixes are rejected.** Specifically: adding a log line to an `except: pass` is
  *not* a fix for a fail-open gate — the gate must change what it *returns*. Widening a Pydantic
  model to make a parse succeed is not a fix for a parse failure.
- **Dependency defects** get a `MITIGATION` label and an escalation, per Phase 5, with root cause
  stated as upstream.

---

## 9. Deliverables and conventions

Matching the repo's existing convention (`tasks/specs/` for plans, `tasks/audits/` for audit
output, lettered findings referenced from commit subjects).

| Artefact | Path |
|---|---|
| This plan | `tasks/specs/defect_hunt_v7_execution_plan.md` |
| Instrument baseline (W0) | `tasks/audits/defect_hunt_baseline.md` |
| Per-wave audit output | `tasks/audits/defect_hunt_w<N>_<surface>.md` |
| Rolling inventory across waves | `tasks/audits/defect_hunt_inventory.md` |
| Proof/boundary/regression tests | `tests/unit/**`, `tests/integration/**` alongside existing suites |

**Per-wave audit file** contains the protocol's labelled phase headers verbatim
(`PHASE 0` … `PHASE 8`), the Phase 4 triage table, the Phase 8 process/engineering check tables,
and the mandatory coverage statement.

**Branch/PR:** one branch per wave, `claude/defect-hunt-w<N>-<surface>`. One PR per wave, opened
as draft. Commit subjects follow the house pattern, e.g.
`fix(security): close the output_path absolute-path escape (finding S1)`.

**Coverage statement template** (Phase 8, mandatory — the core proactive deliverable):

```
Surface audited:         [regions actually triaged]
Surface NOT audited:     [in-scope regions skipped for budget] + [out-of-scope]
Defect classes covered:  [C1..C9 actually hunted on this surface]
Confirmed defects:       CRITICAL n / HIGH n / MEDIUM n / LOW n
Cleared (innocent):      [count]
Residual UNKNOWN set:    [candidates needing runtime/instrumentation]
Clean-claim scope:       "Regions [R...] were audited for classes [...] and no VERIFIED
                          defect was found."          <- NOT "this subsystem is bug-free"
Highest-value next hunt: [the single region/class most likely to yield the next defect]
```

**Epistemic honesty clause** (restated because it is the deliverable's whole point): absence of
found defects is **[UNK]** about the unaudited remainder — never **[VF]** of correctness.

---

## 10. Termination and accounting

The program stops when either condition holds, per wave:

- the wave's surface map is fully triaged, **or**
- `budget_spent` reaches the wave ceiling (§2.6).

`hunt_iterations` (cap 3/region tier) advances the queue rather than aborting.
`fix_revisions` (cap 1) escalates rather than looping.

**A partial program is a valid, honest result.** If only W0–W2 complete, the deliverable is
three coverage statements and a scoped clean-claim — which is worth more than an unscoped
"we audited everything."

---

## 11. Risks to this plan

Stated so the plan can be judged, not just followed.

| Risk | Assessment |
|---|---|
| **The seeds bias the hunt.** §7.3 was produced by static reading and will pull Phase 2 toward the regions already examined. | Real. **Mitigation:** each wave's Phase 1 must enumerate its regions *before* consulting §7.3, and record at least one candidate not derived from it. |
| **Nine waves is a long program.** Later waves may run against a codebase the earlier waves changed. | Expected. W8 exists for exactly this, and §5's rule that innocence defences can be invalidated by later changes is the guard. |
| **The ≤15-line constraint may force many escalations** in the application layer, reducing throughput. | Accepted, with §8's explicit escalation policy so it is visible rather than silently worked around. |
| **W0's ratchets could be set at the wrong number** and permanently license 139 `except: pass` sites. | Set the ratchet, then reduce it in W7. A ratchet that never moves is a fail-open gate with extra steps — the exact class this program exists to find. |
| **Concurrency findings (W3) may be undecidable** and produce a large `[UNK]` residual. | Expected and correct. Phase 3a's STATISTICAL labelling exists for this; forcing a verdict would be the protocol violation. |
| **This plan's own recon could contain a false positive.** | The three §7.2 seeds were demonstrated by executed commands (Appendix A). The §7.3 seeds are explicitly **[HYP]** and may not survive Phase 3b — several probably will not. That is the intended attrition. |

---

## Appendix A — Commands used, so every [VF] claim is re-derivable

**A.1 Environment bootstrap** (the container shipped Python 3.11 with no deps):

```bash
uv venv --python 3.12 .venv-audit
uv pip install --python .venv-audit/bin/python -r requirements.txt
uv pip install --python .venv-audit/bin/python import-linter ruff bandit
```

**A.2 Baseline:**

```bash
./.venv-audit/bin/python -m pytest tests/ --collect-only -q      # 3803/3834, 0 errors
./.venv-audit/bin/python -m pytest tests/unit/ -q --timeout=90   # 2 failed, 3595 passed
./.venv-audit/bin/lint-imports --config .importlinter            # 7 kept, 0 broken
./.venv-audit/bin/python -m ruff check weebot/ cli/ --statistics # 767
./.venv-audit/bin/bandit -c pyproject.toml -r weebot/ cli/       # 68 Low/High-confidence
```

**A.3 Instrument audit (I1) — the gate vs the AST:**

```bash
make lint-bare-except-pass          # exits 0

python - <<'PY'
import ast, pathlib
hits = []
for p in list(pathlib.Path('weebot').rglob('*.py')) + list(pathlib.Path('cli').rglob('*.py')):
    if 'GitNexus-main' in str(p) or '__pycache__' in str(p):
        continue
    try:
        tree = ast.parse(p.read_text(encoding='utf-8'))
    except Exception:
        continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler) and len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
            hits.append(f"{p}:{n.lineno}")
print(len(hits))                    # 139
PY
```

**A.4 Instrument audit (I3) — duplicate reporting:**

```bash
python scripts/lint_async_io.py | grep -c "Blocking call"                       # 83
python scripts/lint_async_io.py | grep -oE "^[^:]+:[0-9]+" | sort -u | wc -l    # 53
```

**A.5 Instrument audit (I2) — rule-code misattribution:**

```bash
ruff rule B110   # error: invalid value 'B110'  (it is a bandit code)
ruff rule B011   # assert-false                 (not except-pass)
ruff rule S110   # try-except-pass — flake8-bandit, and "S" is not in [tool.ruff.lint] select
```

**A.6 Seed verification (S1, S2, S3)** — see §7.2; each was executed against the installed
package in `.venv-audit`, and B1 was reproduced by driving `LatexCompilerService.compile()`
with the same monkeypatches the failing test applies.

**A.7 Instrument audit (I7) and seeds S4/S5:**

```bash
grep -n '^check:' Makefile                                  # lint-async-io is a prerequisite
grep -c 'lint-async-io' .github/workflows/architecture.yml  # 0 -- absent from CI
python scripts/lint_async_io.py >/dev/null; echo $?         # 1  => make check is red

grep -rn 'with sqlite3.connect' weebot/ cli/ --include='*.py' | wc -l   # 37   (S4)
grep -rn 'FlowStateMachine' weebot/ cli/ tests/ --include='*.py' \
  | grep -v 'flow_state_machine.py:'                                    # none (S5)
grep -rn '_get_graph' weebot/ tests/ --include='*.py'                   # definition only (S5)
```

S4's mechanism is a stdlib property, not a weebot one: `sqlite3.Connection.__exit__` commits or
rolls back the transaction and leaves the connection open. Confirmed by executing a statement on
the connection after its `with` block exits.

---

## Appendix B — Uncertainty acknowledgment

*Mandatory per the protocol, appended to every response. This one is about the plan itself.*

- **Finding most likely to be a false positive:** **S2** (`parse_agent_output`). Returning a
  `PARTIAL` object for incomplete JSON is a defensible design choice, and a caller that only
  checks `status` may be entirely satisfied. The defect claim rests on callers *needing* to
  distinguish parse failure from a genuine PARTIAL — which W2 Phase 3 must establish by
  enumerating callers, not assume. If no caller needs the distinction, S2 is CLEARED.
- **Real defect most likely missed:** **concurrency in W3**, and the `weebot/templates/` and
  `weebot/scheduling/` surfaces, which recon touched only through linter output. W7 is also
  expected to terminate PARTIAL by design, leaving the largest tool surface thinnest.
- **What requires runtime validation:** every `[HYP]` in §7.3 — in particular D39 (orphaned
  parallel probes need an instrumented event loop to observe), D44 (timeout behaviour needs a
  slow provider), and S3's reachability (needs a provider response with `usage=None`).
- **What static analysis cannot determine here:** async interleavings in the flow state machine;
  SQLite WAL behaviour under concurrent writers; real provider response shapes; whether the
  767 ruff findings and 831 broad excepts contain behavioural defects or only style.
- **What additional input would most increase confidence:** (1) a production log sample showing
  which cascade paths and providers actually execute — this would convert several `[HYP]`
  reachability claims to `[VF]` or `[FALSE]`; (2) confirmation of the intended deployment posture
  (loopback-only vs LAN-exposed), which sets the true severity of every W6 candidate; (3) whether
  `WEEBOT_WORKSPACE` is set in the real deployment, which determines whether the evidence-gate
  class of defects is live or latent.
