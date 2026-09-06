# Applying the Precision Defect Auditor (V3) to the weebot backend

Execution plan for running `01._Debugging_1.md` — **PRECISION DEFECT AUDITOR — V3
(STATIC / NO-EXECUTION, SINGLE-PASS)** — across `weebot/` and `cli/`.

Companion to [`defect_hunt_v7_execution_plan.md`](defect_hunt_v7_execution_plan.md),
which drove waves W1–W8. This plan does **not** repeat those waves; it targets
what they did not reach, and it reconciles into the same inventory
([`tasks/audits/candidates.yml`](../audits/candidates.yml)).

Status: **draft — not yet executed.** No pass below has been run.

---

## 0. Two decisions to take before any pass runs

These are not implementation details. Both change what the audit is allowed to
claim, and both are deviations from the prompt as written. They are stated here
so a reviewer can reject them before work starts rather than discover them in a
commit.

### 0.1 The static ceiling is voluntary here, and should be lifted

V3 declares its strongest verdict `VERIFIED-STATIC` and forbids `VERIFIED`,
because it is written for contexts where *"you cannot execute the target code"*.
That premise is false in this repository: there is a working `.venv-audit`, a
3905-test suite, and eight prior waves of execution-verified defect hunting.

Running V3 verbatim would therefore cap every finding at evidence *weaker than
the repo can produce*, and would ship fixes whose regression tests were written
but never run — which is precisely the failure the whole review programme
exists to attack (*"you cannot build a gate on an instrument that cannot
fail"*).

**Decision — adopt V3 for elicitation and triage; do not adopt its evidence
ceiling.** Concretely:

| V3 phase | Adopted? | Why |
|---|---|---|
| Phase 0 context acquisition | **Yes, verbatim** | Reachability anchors are exactly what severity-gating needs |
| Phase 1 Step 1A diverse elicitation | **Yes, verbatim** (`k=6`) | Counters mode collapse; the tail classes are where W1–W8 were thinnest |
| Phase 1 innocence check | **Yes, verbatim** | The false-positive killer; keep it |
| Phase 1 inventory table | **Yes, plus one column** | Add `Candidate ID` for candidates.yml reconciliation (§4) |
| Phase 2 Fix Packages | **Yes, with promotion gate** | See §0.2 |
| Phase 3 master report | **Yes, verbatim** | The coverage/residual-risk statement is the deliverable |
| Operator rule *"never claim VERIFIED"* | **Replaced** | Superseded by the promotion gate below |
| Operator rule *"all verification stays PENDING"* | **Replaced** | We run the tests. Claims are made only from real output |

Every other operator rule stands unchanged — in particular *never emit "the code
is bug-free"*, *presume the code correct*, *record cleared candidates*, and
*salience/weight quarantine* (elicitation origin never touches Evidence or
Severity).

### 0.2 The promotion gate — how a finding earns `VERIFIED`

V3's evidence axis is kept and **extended by one rung**:

```
UNKNOWN  →  HYPOTHESIS  →  VERIFIED-STATIC  →  VERIFIED-EXECUTED
                                                ^
                        added here: a trigger test that FAILS on unfixed code
                        and PASSES after the diff, with both runs recorded
```

Rules:

- A finding may not be fixed at `HYPOTHESIS` or `UNKNOWN`. It is either promoted
  by writing a trigger test that actually fires, or it is recorded `deferred`
  with a `verdict_note` — never fixed on a guess.
- `VERIFIED-STATIC` is a way-station, not a destination. It is the correct
  verdict *while* the trigger test is being written.
- **Red before green is mandatory and must be pasted into the audit record.**
  A test that passes before the fix proves nothing and is treated as a failed
  promotion, not as a cleared candidate.
- A finding that cannot be made to fire is **not thereby innocent**. It moves to
  the Cleared list only if the innocence check succeeds on its own terms
  (upstream guard, unreachability, holding invariant). "I could not write a
  test" is recorded as `deferred`, not `cleared`.

This last rule is the one most likely to be violated under time pressure, and it
is the one that turns an audit into theatre.

---

## 1. Phase 0 — context, filled in

V3 requires C1–C3 and reachability anchors before scanning. Answering them once
here means every pass inherits them.

### C1 — Codebase

`weebot/` + `cli/`: **820 Python files, 148,416 lines** (measured, not
estimated). Clean/hexagonal architecture; dependency direction
`Interfaces → Infrastructure → Application → Domain`, enforced by 7
import-linter contracts.

### C2 — Environment

- Python 3.12, `asyncio` throughout (`asyncio_mode = "auto"` in pytest config).
- FastAPI + Starlette (web), MCP server (stdio + SSE), Typer-style CLI.
- SQLite with WAL for state and event store.
- Test suite: 3905 unit tests; `--cov-fail-under=52`; 7 tests deselected by
  `-m "not external"`.
- **The only environment with the repo's dependencies is `.venv-audit/`.** System
  Python lacks `dotenv` and `pydantic`. Every command in this plan uses it.

### C3 — Risk domains (the threat model that ranks defect classes)

| Domain | Present as | Ranks up |
|---|---|---|
| **Unbounded spend** | LLM cascade, model selection, budget filters | cost/idempotency/retry defects |
| **External untrusted input** | `atomic_mail` inbound (explicitly untrusted per CLAUDE.md), web/MCP request bodies, tool output | taint, injection, deserialization |
| **Command execution** | `bash_tool`, `python_tool`, `create_subprocess_*` | injection, guard bypass |
| **Auth / transport** | MCP SSE bind + token, web routers | auth bypass, unauthenticated bind |
| **Data persistence** | SQLite state repo, event store, backup/restore | corruption, partial write, lost update |
| **Real-time I/O** | WebSocket broadcast, SSE streams | liveness, deadlock, unbounded queues |
| **Scheduling** | `weebot/scheduling/`, cron jobs, heartbeat | silent job death, missed runs |

PII is **UNKNOWN** and must be treated as present wherever inbound mail or
session transcripts are persisted.

### Reachability anchors (entry points and trust boundaries)

Severity is reachability-adjusted, so this list *is* the severity scale. Anything
not reachable from one of these cannot be CRITICAL.

1. `cli/main.py` — `init`, `health`, `doctor`, `flow`, `agents`, `costs`
2. `run.py` (interactive REPL), `run_mcp.py`, `run_dashboard_demo.py`, `run_llm_demo.py`
3. `weebot/interfaces/web/` — **14 FastAPI routers** + WebSocket endpoints
4. `weebot/interfaces/mcp/` and `weebot/mcp/` — MCP tools over stdio and SSE
5. `weebot/scheduling/` — `scheduler.py`, `default_jobs.py`, `nl_cron.py`
6. `weebot/infrastructure/adapters/atomicmail/` — inbound mail consumer **(trust boundary)**
7. `weebot/tools/` — tool invocations driven by model output **(trust boundary)**

**Note the direction conflict, and respect it:** reachability must be computed
*outside-in* from these anchors, while auditing proceeds *inside-out* by layer
(§3). A pass on `domain/` therefore cannot assign severity from its own surface
alone — it must trace outward to an anchor, or record `Reach: UNKNOWN`, which
caps severity below CRITICAL. Do not guess reachability to justify a severity.

---

## 2. Surface partition

V3 is a single-pass auditor with `k = 5–8` candidates. 148k lines is 30–60× a
sane single-pass surface. Auditing it in one call would produce mode collapse —
six generic findings about the most-recently-read file — which is exactly what
Step 1A exists to prevent. **The partition is therefore load-bearing, not
administrative.**

### 2.1 In scope — every pass, with priority

Priority = (blast radius) × (threat-model weight) × (thinness of prior W1–W8
coverage). Passes run in this order.

| # | Pass | Surface | Files / lines | Rationale |
|---|---|---|---|---|
| **P1** | Cross-cutting core | `weebot/core/` | 43 / 12,042 | `bash_guard`, `approval`, `model_cascade` — every layer depends on it; W1 touched only the guard |
| **P2** | Config & the six registries | `weebot/config/` | 16 / 4,682 | Documented to disagree in ≥14 places; `model_refs.py` has ~50 importers |
| **P3** | Domain purity | `weebot/domain/` | 87 / 8,121 | 87 files of pure logic with the most dependents; never audited as a unit |
| **P4** | Tools & the model→shell boundary | `weebot/tools/` | 48 / 11,944 | Trust boundary; W7 covered lifecycle, not taint |
| **P5** | Scheduling | `weebot/scheduling/` | 4 / 1,343 | A backup job raised `AttributeError` on **every** run for months and nothing noticed |
| **P6a** | Application — flows & states | `weebot/application/flows/` | subset of 338 | `plan_act_flow.py` (965) + `states/` |
| **P6b** | Application — agents & skills | `weebot/application/agents/`, `skills/` | subset | `executor/_base.py` (1,083) |
| **P6c** | Application — services & CQRS | `weebot/application/services/`, `cqrs/` | subset | Largest remainder |
| **P7** | Infrastructure — persistence | `weebot/infrastructure/persistence/` | subset of 162 | W4 covered it; re-audit only for classes W4 did not hunt |
| **P8** | Infrastructure — adapters | `weebot/infrastructure/adapters/` | subset | Includes the atomicmail trust boundary |
| **P9** | Interfaces | `weebot/interfaces/` | 45 / 7,878 | W6 covered it; re-audit for tail classes only |
| **P10** | CLI | `cli/` | 19 / 4,645 | Thin, but it is entry point #1 |
| **P11** | Small packages | `weebot/agents/`, `models/`, `mcp/`, `osworld/`, `qmd_integration/`, `utils/` | 26 / 5,004 | Never audited; small enough for one pass |

`weebot/application/` is split into **P6a/b/c** because 53,233 lines in one pass
would reproduce the mode collapse the partition exists to prevent.

### 2.2 Out of scope — declared, with reasons

V3 Phase 3 requires *"Surface NOT audited: [in-scope but skipped, with reason]"*.
Declaring it up front stops it becoming a silent gap.

| Excluded | Lines | Reason |
|---|---|---|
| `weebot/GitNexus-main/` | 1,918 | Vendored third-party; already excluded from ruff. Audit it only as a dependency-CVE question, not line-by-line |
| `weebot/templates/` | 7,358 | Generated/site templates, not backend logic. In scope **only** for the website standards in CLAUDE.md, which is a different review |
| `weebot-ui/` | — | Frontend; "backend" was the request |
| `tests/` | — | Not production code. In scope only where a test *asserts a defect as its contract* (this has happened twice — see §6) |
| **`_catalog.py`** | 4,281 | **Generated and pinned.** See the hard rule in §5.3 |

---

## 3. Per-pass procedure

Each pass is one V3 run, one commit, and one appended section in a single audit
record. Ten steps.

1. **Declare the pass.** Surface, file list, and the diversity configuration in
   force. Record it — V3's Phase 3 requires `Diversity mode: [1A · B · C · k=N]`
   for auditability.
2. **Run Phase 1 Step 1A** at `k = 6`, steering across the taxonomy, not toward
   the modal bug. Do not rank or score candidates.
3. **Innocence check every candidate**, adversarially. Cleared candidates are
   recorded, never dropped.
4. **Reconcile against `candidates.yml`** before assigning an ID (§4).
5. **Attempt promotion** to `VERIFIED-EXECUTED` for every survivor (§0.2). Paste
   the red run.
6. **Write the Fix Package** in V3's format for promoted findings only.
   `~~~` fences inside the package, per the prompt.
7. **Apply the fix, run the six RAR self-review vectors**, paste the green run.
8. **Reconcile the ratchets** (§5.1) — *in the same commit*.
9. **Run the full gate sweep** (§5.4). All of it, every pass.
10. **Commit**, and append the pass's coverage statement to the audit record.

### Diversity configuration

| Toggle | Setting | Reason |
|---|---|---|
| `DIVERSITY_ELICITATION` (1A) | **ON** | Capable model; the tail classes are where W1–W8 were thinnest |
| `TOGGLE_B_INNOCENCE_DIALECTIC` | **ON for P1, P2, P4, P5; OFF elsewhere** | Those four gate spend, command execution and scheduling — false-positive cost is highest where a wrong fix changes live behaviour |
| `TOGGLE_C_TAIL_SWEEP` | **ON for P1 and P3 only** | Cross-cutting core and pure domain are where a rare-class defect is least likely to be found by any other means. ≥2× elicitation cost is not justified elsewhere |
| `ELICITATION_CANDIDATES` | **k = 6** | Mid-range; the prompt warns quality degrades if k is too large |

Toggle B's own guard applies: *if nearly every candidate is being cleared, treat
that as a red flag* and re-audit the clearings for VERIFIED-STATIC grounding.

---

## 4. Reconciliation with the existing inventory

`candidates.yml` holds **53 records: 24 fixed, 17 deferred, 6 cleared, 6 open —
23 not closed.** `tests/unit/test_candidate_inventory.py` enforces that the
audits and the inventory agree, **in both directions**.

Rules, in order:

1. **Match before you mint.** A V3 candidate describing an already-recorded claim
   is reconciled to that ID. It does not get a new one. Double-counting one root
   cause across two IDs breaks the inventory's own gate.
2. **A `deferred` record that V3 re-surfaces with new evidence is reopened**, not
   duplicated: update `status` and append to `verdict_note`.
3. New candidates continue the existing numbering. Do **not** reuse
   `D1`, `D2`, `D7` — they are recorded in `meta.numbering_gaps` and a test
   asserts nothing claims them.
4. Every new record needs `status`, `claim`, `location`; `cleared`/`deferred`
   additionally need `verdict_note`; `fixed` needs `evidence` naming a real test.
5. **Expect P1–P4 to collide with the 23 open records.** That is a feature: V3's
   independent elicitation reaching an already-known claim is corroboration.
   Reaching a *different* claim at the same site is a new candidate.

---

## 5. Repo-specific constraints a fix must satisfy

A correct fix that violates any of these turns CI red. All four have bitten this
repo already.

### 5.1 The ratchets are bidirectional — this is the sharpest trap

`tasks/quality/ceilings.toml`: **`actual > ceiling` fails AND `actual < ceiling`
fails.** Fixing a defect that happens to remove a counted pattern therefore
*breaks the build* unless the ceiling is lowered **in the same commit**.

| Ceiling | Value | A fix trips it by |
|---|---|---|
| `silent_except_handlers` | 139 | giving an `except: pass` handler a body |
| `blocking_io_in_async` | 29 | wrapping a blocking call in `asyncio.to_thread` |
| `print_in_production` | 143 | replacing a `print()` with a logger call |
| `bare_env_reads` | 73 | routing an `os.getenv` through `weebot/config/` |
| `bandit_b110` | 68 | any of the above that bandit also counted |

Two traps inside the trap:

- **`bandit_b110` and `silent_except_handlers` move independently.** They measure
  overlapping but unequal sets. Never assume one decrement implies the other —
  measure both.
- **The ratchets scan `weebot/` and `cli/` only, not `scripts/`.** A fix in
  `scripts/` moves no ceiling. Do not "helpfully" decrement one.

Before every commit: re-measure, then set each ceiling to the measured value.

### 5.2 Import-linter — 7 contracts, all `forbidden`

A fix must not create a new import edge. The contracts most likely to be broken
by a plausible fix:

- *Domain layer must not depend on outer layers* — a `domain/` fix that reaches
  for an application service breaks it. Inject through a port instead.
- *Tools must not bypass ports* — a `tools/` fix that imports persistence or an
  adapter directly breaks it.
- *Core cross-cutting layer must not depend on application* — a `core/` fix
  (pass P1) that imports an application service breaks it.

`lint-imports` must report **7 kept / 0 broken** after every pass.

### 5.3 `_catalog.py` is generated and byte-pinned — never hand-fix it

`weebot/application/services/model_registry/_catalog.py` is the largest module in
the backend (4,281 lines) and will attract findings. **It must not be edited.**

`test_the_shipped_catalog_is_exactly_what_the_recorded_payload_renders` re-renders
`tests/fixtures/openrouter_models.json` and compares the whole file, so any hand
edit fails immediately. Route fixes to their real home:

| Defect is in | Fix goes in |
|---|---|
| a model's data (price, tier, strengths) | `_catalog_overrides.py` |
| the derivation rule | `scripts/generate_catalog.py`, then regenerate |
| the payload itself | `tests/fixtures/openrouter_models.json`, then regenerate |

A regeneration updates the fixture and the catalog **in the same commit**.

### 5.4 The gate sweep — run all of it, every pass

```bash
.venv-audit/bin/python -m pytest tests/unit/ -q --no-header -p no:randomly
.venv-audit/bin/python -m pytest tests/unit/ -q --cov=weebot --cov-fail-under=52
.venv-audit/bin/python -m ruff check --select F821,E9 weebot/ cli/   # CI's selector
.venv-audit/bin/lint-imports                                        # expect 7 kept / 0 broken
.venv-audit/bin/python scripts/lint_except_pass.py
.venv-audit/bin/python scripts/lint_async_io.py
make lint-no-print lint-env-access
.venv-audit/bin/python scripts/quality_ceilings.py --verify-not-raised --baseline origin/main
.venv-audit/bin/python scripts/check_ruleset_consistency.py
```

Note `ruff check --select F821,E9` is what **CI** runs on `weebot/` and `cli/`.
A full `ruff check` reports pre-existing E501s that CI does not gate on; do not
"fix" those — that is unrelated refactoring, which V3 forbids in a fix diff.

---

## 6. What prior waves learned, and what V3 should therefore hunt

Eight waves produced one dominant defect class, named in the merge commit for
PR #59: **a control that reports clean while checking nothing.** Instances: a
Security Scan whose conclusion was a constant; a ratchet disarmed by the workflow
that ran it; two SSE tests passing against code that raised `TypeError`; a suite
asserting a defect as its contract; a print ceiling overridable to 99999; a daily
backup job that raised `AttributeError` on every run since it was written.

The OpenRouter work (PR #60) added two more of the same shape: a catalog
generator whose import probe *executed* the payload it was meant to validate, and
a pricing guard whose `except` clause returned from the function rather than the
loop, readmitting the exact entry it existed to exclude.

**Steer Step 1A accordingly.** For each pass, spend at least two of the six
candidates on:

- **Fail-open error paths** — `except` clauses that return a success-shaped
  value; guards whose failure mode is "allow"; validators that return `True` on
  exception.
- **Instruments that cannot fail** — assertions with no reachable false branch,
  gates whose result is discarded, checks whose output nothing reads.
- **Tests that pin a defect as the contract** — this is why `tests/` is in scope
  at all (§2.2).

These are exactly the "tail" classes Toggle C is for, and they are demonstrably
this codebase's modal defect — which means for *this* repo they are the head, not
the tail. Step 1A should be steered toward what remains genuinely atypical here:
ordering/idempotency assumptions, TOCTOU, DST/timezone, integer overflow,
lock-ordering, unbounded growth.

---

## 7. Deliverables

| Artefact | Path |
|---|---|
| Audit record, one section per pass | `tasks/audits/static_defect_audit_v3.md` |
| Inventory updates | `tasks/audits/candidates.yml` |
| Proof tests | `tests/unit/...` alongside the code under test |
| Ceiling changes | `tasks/quality/ceilings.toml` |
| Commits | one per pass, `fix(<area>): …` or `chore(audit): …` |

Each pass's record carries V3's Phase 3 report in full: the summary counts, the
diversity mode, prevention recommendations, the coverage & residual-risk
statement, and the mandatory uncertainty acknowledgment.

**The clean claim is always scoped.** Per pass: *"Region [P-n] was audited for
classes [...] with no VERIFIED-EXECUTED defect found."* Never *"the code is
bug-free"* — the prompt forbids it and the repo's history makes it false.

---

## 8. Sequencing across multiple prompts

The attached file is `01._Debugging_1.md`, implying a numbered series. **Only 01
was supplied.** This plan covers 01 alone and defines the seams a later prompt
plugs into:

| Seam | Hands off | Consumed by |
|---|---|---|
| After Phase 1 of each pass | the inventory table + Cleared list | a prioritisation or triage prompt |
| After Phase 2 | Fix Packages with red/green evidence | a review or verification prompt |
| After Phase 3 | coverage & residual-risk statement | a reporting or gate-design prompt |

When 02+ arrive, they slot in at these seams **without re-running Phase 1** —
re-eliciting over an already-audited surface wastes budget and re-mints IDs that
§4 exists to prevent.

---

## 9. Risks in this plan

Stated rather than buried, since the plan is itself an instrument.

- **Eleven passes is a lot of budget.** If it must be cut, cut from the tail
  (P7–P11, which W4/W6 partly covered) and keep P1–P5. Do not cut by reducing
  passes to fewer, larger surfaces — that reintroduces mode collapse and is the
  one economy that destroys the method.
- **The promotion gate (§0.2) is the expensive part**, and it is the part under
  pressure to skip. A fix without a red-before-green record is not a fix this
  repo can distinguish from a guess.
- **Toggle B can suppress real defects.** The prompt warns of motivated-reasoning
  collapse; the guard is to re-audit clearings whenever the clear rate looks high.
- **V3 will re-find known candidates.** Expected and useful, but if a pass returns
  *only* known candidates, that is evidence the surface is exhausted — record it
  and move on rather than manufacturing novelty.
- **Severity will be over-assigned if reachability is guessed.** `Reach: UNKNOWN`
  caps severity below CRITICAL; use it honestly rather than inventing a path from
  an entry point.
- **This plan has not been executed.** Nothing in it is evidence about the code.
