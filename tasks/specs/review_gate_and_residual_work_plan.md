# Review Gate & Residual Work — Execution Plan

Follows the V7 defect-hunt programme ([`defect_hunt_v7_execution_plan.md`](defect_hunt_v7_execution_plan.md),
merged as `240107f`). That programme fixed 23 defects and wrote down, wave by wave, exactly what
it did not do. This plan addresses two things it left behind:

- **A — there is no merge gate.** `main` is unprotected and the automated reviewer was out of
  quota, so eleven commits touching security controls landed with no review of any kind.
- **B — the work is incomplete by design.** 25 named candidates were never investigated, four
  lint ratchets have not moved since Wave 0 set them, and the plan's own named test gap
  (`backup.py` / `restore.py`) is still open.

**This is a plan, not an implementation.** Nothing here has been executed.

---

## 1. The thesis: Wave 0's lesson generalises

The defect hunt's first act was to repair its instruments, because *a hunt inherits the reliability
of its detectors*. Seven gates were found reporting clean while checking nothing.

The same failure mode is present one layer up, and this plan is organised around it:

> **You cannot build a gate on an instrument that cannot fail.**

Requiring a status check that structurally always passes creates the *appearance* of a gate while
adding none — which is worse than having no gate, because it stops anyone looking. Likewise, a
ratchet that only blocks upward movement, with nothing driving it down, is a ceiling that will sit
where it was first measured forever. Both are the **C2 (fail-open control)** class from the hunt's
own taxonomy, now expressed in CI configuration and in process rather than in Python.

So the ordering throughout is: **repair the instrument, then require it.** Never the reverse.

---

## 2. PART A — the merge gate

### 2.1 Verified facts

Measured against `240107f`; commands in Appendix A.

| Fact | Evidence |
|---|---|
| `main` is **unprotected** | `list_branches` → `"name":"main","protected":false`. No required checks, no required reviews, no push restriction. |
| `.github/workflows/architecture.yml` is the **only** workflow | `ls .github/workflows/` |
| It has **no deploy job** | merging publishes and deploys nothing |
| **7 steps swallow their own failure** with `\|\| echo` | lines 39, 53, 85, 180, 190, 194, 217 |
| The **`Security Scan` job cannot fail** | all three of its steps (pip-audit, bandit, npm audit) are `\|\| echo` |
| The automated reviewer did not run | `chatgpt-codex-connector[bot]`: *"You have reached your Codex usage limits for code reviews."* |
| A stale **`master`** branch exists at a different SHA | `901e476`, unreferenced by CI — **"stale" was wrong, see the correction below** |
| **`CODEOWNERS` does not exist** | no file at any conventional path |

### 2.2 Defect A1 — three jobs are partly or wholly fail-open

`Security Scan` is the extreme case: **every** step ends in `|| echo`, so the job's conclusion is a
constant. Adding it to a required-checks list would be theatre.

The others are mixed. `Unit Tests` and `Docker Build Smoke Test` each contain one `|| echo` step
alongside genuine ones, so the *job* can still fail — but the specific signal those steps carry
(dependency advisories, frontend audit) is silently discarded. `lint-and-arch` is the subtlest:
its two Wave 0 ratchets are blocking, while `lint-env-access` beside them is not.

**This is deliberate, and the comments say so** — the advisories have pre-existing findings and
were made non-blocking rather than left permanently red. That was a defensible choice. What is not
defensible is leaving the distinction invisible: nothing in the workflow separates *"this gate is
advisory"* from *"this gate is load-bearing"*, so a reader cannot tell which is which, and a
maintainer wiring up required checks will pick the wrong ones.

**Design correction.** Make the advisory/blocking distinction *structural* rather than a shell
idiom:

- Split `Security Scan` into **`security-advisory`** (never required, may report findings) and
  **`security-blocking`** (required, contains only checks that genuinely fail). If no check
  currently qualifies for the second, the honest outcome is that the job does not exist yet —
  say so rather than shipping an empty gate.
- Replace `|| echo` with GitHub's own `continue-on-error: true`, which surfaces the step as
  *neutral* in the UI instead of forging a success. Same behaviour, honest reporting.
- Adopt the ratchet pattern the hunt already established for the advisories that have a countable
  backlog (bandit's B110 findings, pip-audit advisories): a recorded ceiling, blocking above it.
  That converts three permanently-advisory gates into three real ones without a big-bang cleanup.

### 2.3 Defect A2 — the identity problem, which has no purely technical fix

The stated goal is *"an agent should not be able to merge without human sign-off."* GitHub's review
primitives cannot express that here, because:

1. GitHub **forbids approving your own pull request**.
2. The agent acts with the repository owner's identity. Author and would-be approver are the
   same principal.

Therefore `required_approving_review_count: 1` does not create the intended gate — it creates a
**deadlock**: no one can approve, including the human owner working alone.

`[VF]` This is a property of GitHub's model, not a configuration mistake. Any plan that says
"just require one approval" is wrong, and this is the single most important thing to get right in
Part A.

**Three ways out, with honest trade-offs:**

| | Approach | What it buys | What it costs |
|---|---|---|---|
| **A-i** | **Required checks only.** Protect `main`, require the genuinely-failing jobs, forbid force-push, require linear history. No review requirement. | Stops broken code. Zero friction. Implementable today. | Does **not** stop unreviewed merges — the stated problem is only half solved. |
| **A-ii** | **Distinct agent identity.** The agent operates as a GitHub App or bot account, not as the owner. Then `required_approving_review_count: 1` + `CODEOWNERS` works exactly as intended: the bot opens PRs, the human approves. | Genuinely solves it. The bot *cannot* self-approve; the owner *can* approve the bot's PRs. Also gives least-privilege tokens and a clean audit trail. | Real setup work: App registration, token plumbing, updating every automation that currently uses the owner's credentials. |
| **A-iii** | **Human-acknowledgement check.** A workflow that fails unless a human applies a `reviewed` label or posts an approving comment. | Cheap; works with one identity. | **Fail-open by construction** — the agent holds the same token and could apply the label. It documents intent rather than enforcing it. Under this plan's own thesis, that disqualifies it as a gate. |

**Recommendation: A-ii, reached via A-i.** Ship A-i immediately — it is a day's work and closes
the "broken code lands" half. Then do A-ii, which is the only option that actually closes the
"unreviewed code lands" half. **A-iii is explicitly rejected**: shipping a control that the actor
it constrains can trivially bypass is precisely the fail-open pattern this plan exists to remove.

`[UNK]` **Precondition to verify before A-i:** whether the repository is public or private, and the
account's plan. Classic branch protection on private repositories requires a paid plan; rulesets
have different availability. Check this first — it determines whether A-i is configuration or a
billing decision.

### 2.4 Protection as code, not as clicks

Whichever option is chosen, the settings should live in the repository, not only in the web UI:

- Store the intended ruleset as JSON under `.github/rulesets/main.json`, applied via the API.
- Add a CI job that **reads back** the live protection and fails if it has drifted from the file.

This is the same principle as the hunt's ratchets: a control whose configuration nobody can see is
a control nobody can verify. It also makes the protection restorable if it is ever disabled — and
recoverable configuration matters more here than usual, because the only person who can silently
disable it is also the only person reviewing.

### 2.5 Phases

| Phase | Work | Exit criterion |
|---|---|---|
| **A0** | Verify repo visibility/plan; enumerate which of the 8 jobs can genuinely fail | A written table: job → can-fail yes/no → required yes/no |
| **A1** | Replace `\|\| echo` with `continue-on-error`; split `Security Scan`; ratchet what can be ratcheted | No job in the workflow has a constant conclusion, or is documented as advisory-only |
| **A2** | Apply branch protection (A-i) via a checked-in ruleset + drift-detection job | Protection readable from the repo; drift job proven to fail when protection is removed |
| **A3** | Distinct agent identity (A-ii); `CODEOWNERS`; require 1 approval | A PR opened by the bot cannot be merged by the bot |
| **A4** | Delete or document the stale `master` branch | One default branch, or a written reason for two |

**Prove each gate blocks.** Wave 0's discipline applies unchanged: after configuring protection,
attempt a direct push to `main` and a merge with a failing check, and confirm both are refused.
A gate assumed to work is not a gate.

### Correction — `master` is not stale (added after A4 was executed)

This plan asserted a *"stale `master` branch"* on the strength of its SHA differing from `main`'s.
Measuring it during A4 disproved the characterisation, and the entry above is left standing rather
than rewritten because what the plan assumed is part of its record.

`[VF]` `git merge-base main master` **exits 1 with no output**: the two branches share no common
ancestor. `master` carries **490 commits** (2026-02-28 → 2026-07-21) against `main`'s 120, and holds
**both** release tags, `v2.0.0` and `v2.1.0`, which exist on no other branch. `main` has **four**
root commits of its own.

It is a disjoint parallel history, not a leftover pointer — so *delete* was never the right half of
the disjunction. Documented instead in [`docs/BRANCHES.md`](../../docs/BRANCHES.md). The one part of
the original claim that held: nothing in CI or the Makefile references it, so it costs nothing to
keep.

Execution record for A2 and A4: [`tasks/audits/review_gate_a2_a4.md`](../audits/review_gate_a2_a4.md).

---

## 3. PART B — the residual work

### 3.1 B1 — the 25 candidates: make the inventory data, not prose

The candidates are currently recorded as Markdown tables spread across nine audit files. That is
readable but not *checkable*: nothing counts them, nothing prevents one being quietly dropped, and
answering "what is still open?" means re-reading nine documents (as it did when this question was
last asked).

**Design: a single machine-readable inventory** at `tasks/audits/candidates.yml`, one record per
candidate:

```yaml
- id: D26
  wave: W3
  location: interfaces/web/websocket.py:68-72, behavior_router.py:205-228
  claim: _ws_lock held across a timeout-less send loop; one hung client stalls every subscriber
  classes: [C6]
  threat: T6
  status: open          # open | investigating | confirmed | fixed | cleared | deferred
  evidence: null        # path to the trigger/proof once one exists
  verdict_note: null    # required when status is cleared or deferred
```

Paired with a **consistency gate** (`tests/unit/test_candidate_inventory.py`) asserting:

1. Every `D<n>` / `S<n>` id mentioned in any `tasks/audits/*.md` exists in the inventory.
2. Every `cleared` or `deferred` record carries a non-empty `verdict_note` — a candidate cannot be
   dismissed silently, which is the protocol's Phase 4 rule expressed as a test.
3. Every `fixed` record names an `evidence` path that exists.
4. The count of `open` records is reported, and a summary is regenerated into the audits.

This converts "25 candidates never investigated" from a fact buried in prose into a number a build
prints. **The pattern is a single source of truth with a derived view** — the audits keep their
narrative, but the counts come from the data.

**Ranking for actual investigation.** Not all 25 are equal. Ordered by blast radius from the
audits' own reachability notes:

| Priority | Candidates | Why first |
|---|---|---|
| **1** | **D47** (MCP `token_verifier=None` ⇒ unauthenticated SSE server), **D50** (events without `session_id` broadcast to all connections) | Both are unauthenticated-exposure candidates. D50 may be the same leak W6 fixed, by another route — W6's fix does not address it. |
| **2** | **D26** (`_ws_lock` across a timeout-less send loop), **D28** (`input()` in `async def`) | The two clearest liveness (T6) candidates; either can stall the whole process. |
| **3** | **D39** (orphaned cascade probes keep running *and billing*), **D44** (no client HTTP timeout on any adapter) | Unbounded spend (T4) and its liveness cousin. |
| **4** | **S5** (both declared transition tables are dead code) | Largest *structural* finding; not a runtime defect, but the architecture documents a machine that does not execute. |
| **5** | remaining 18 | Work in inventory order. |

### 3.2 B2 — the ratchets: make them bidirectional

Four ceilings, unchanged since Wave 0 measured them:

```
139  silent except handlers      29  blocking I/O in async
143  print() in production       73  bare env reads
```

Two live as `?=` variables in the `Makefile`; two as `CEILING` constants in Python scripts. **The
mechanism has two defects, and they explain why the numbers never moved:**

1. **Nothing enforces "never raise it."** The rule is a comment. A future edit can raise a ceiling
   and CI will pass, which silently converts the ratchet into a rubber stamp.
2. **Nothing rewards lowering it.** `lint_async_io.py` already prints *"Ceiling can be lowered to
   N"* when the actual count drops — as advice, which will be ignored indefinitely. Slack between
   actual and ceiling is where regressions hide, invisibly, until they reach the ceiling.

**Design: one ceiling file, two enforced directions.**

- Move all four ceilings into `tasks/quality/ceilings.toml` — a single declarative source, removing
  the Makefile/Python split.
- **Upward guard:** a CI step compares the committed ceilings against those on `main` and fails if
  any increased. Raising one then requires deleting the guard, which is visible in review.
- **Downward guard (the important one):** when `actual < ceiling`, **fail** with
  `"lower CEILING to <actual>"`. This is the inversion that turns a static ceiling into a
  monotonically decreasing one: every incidental cleanup gets *locked in* rather than becoming
  slack.

That second rule is the whole design. It costs nothing when debt is untouched, and makes any
reduction permanent the moment it happens.

**Paydown, once the mechanism is right.** Do not attempt a big-bang cleanup — the counts are large
and the changes are individually trivial but collectively unreviewable. Instead:

- **Per-PR budget:** each PR that touches a file containing ratcheted debt fixes the sites in the
  functions it already touches. Debt decays along the paths under active development, which is
  where it matters most.
- **Targeted sweeps** only where a class is mechanically uniform, as the Wave 7 `sqlite3` sweep
  was (37 sites, one shape, one transformation, verified by counting). `print()` → `logger` is the
  best candidate; `except: pass` is **not** — each of the 139 needs a human decision about what to
  log and whether to re-raise, and a mechanical sweep would produce 139 unreviewed judgements.

`[HYP]` The 139 silent handlers likely contain several genuine defects of the C2 class the hunt was
built to find. That is a reason to work them deliberately, not quickly.

### 3.3 B3 — backup / restore: the named test gap

`implementation_audit_report.md` §6 records no tests for `scripts/backup.py`, `scripts/restore.py`
or `_database_backup_job` (`weebot/scheduling/default_jobs.py:113`), and the V7 plan calls this
*"the highest-value place in the repo to add proof tests"* — a subsystem whose last three defects
were CRITICAL. Nothing was written. This is the most clearly-scoped item in the whole plan.

**The code is unusually testable**, which is why this is small:

- `backup_database(src, dest_dir, label) -> Path` uses `sqlite3.backup()` (WAL-safe, page-by-page).
- `verify_backup(path) -> bool` runs `PRAGMA integrity_check`.
- `restore.py` writes `<dest>.pre-restore-bak` before overwriting.
- Both take `argv` explicitly in `parse_args(argv=None)`, so the CLI is drivable in-process with no
  subprocess and no monkeypatching of `sys.argv`.

**Design: a round-trip invariant, not example assertions.** The property that matters is

> `restore(backup(db)) ≡ db`

**Property-based testing** (`hypothesis`) is the right paradigm here rather than fixed examples:
generate a schema and rows, round-trip them, assert equality of the full table contents. A
hand-written example asserts one database survives; a property asserts *databases* survive, and
will find the encoding, empty-table and large-blob cases nobody thinks to write.

Test matrix:

| Property | Why it is the one that matters |
|---|---|
| **Round trip** `restore(backup(db)) == db` | The whole point of the subsystem |
| **WAL safety** — backup taken with an open uncommitted write | The documented reason `sqlite3.backup()` is used over `cp`; untested, so the claim is unverified |
| **Integrity gate** — a corrupt backup is refused by `restore` | `verify_backup` is the safety interlock; if it fails open, restore destroys the destination |
| **Pre-restore safety net** — `<dest>.pre-restore-bak` exists and is itself restorable | Documented as the recovery path for a mistaken restore |
| **Retention** — `--retention N` deletes older, keeps newer, `0` keeps all | Deletion logic on a backup directory: the highest-consequence off-by-one in the file |
| **`--force` / confirmation** — no overwrite without explicit consent | Guards an irreversible action |
| **`_database_backup_job`** — failure is surfaced, not swallowed | It is a scheduled job; if it fails silently, backups stop existing and nobody learns until a restore is needed |

The last row deserves emphasis. **A backup job that fails silently is indistinguishable from one
that works** until the day it matters — the purest possible instance of the C2 class. Whatever
else is deferred, that assertion should not be.

---

## 4. Sequencing

Dependencies run in one direction, and the order is not cosmetic:

```
A0  audit which jobs can fail
 └─> A1  make advisory vs blocking structural      ── required before ──┐
      └─> A2  branch protection + drift detection                       │
           └─> A3  distinct agent identity, CODEOWNERS, 1 approval      │
                                                                        │
B2-mechanism  one ceiling file, both directions enforced                │
 └─> B2-paydown  per-PR budget + uniform sweeps                         │
                                                                        │
B1  candidate inventory + consistency gate                              │
 └─> B1-work  investigate in priority order ────────────────────────────┘
                                                                    (all land through the gate)
B3  backup/restore tests            (independent — can start immediately)
```

**B3 is the only item with no prerequisite.** If effort is limited, do B3 and A1 first: the
smallest well-defined piece of real testing, and the correction that stops the CI configuration
lying about which of its gates are load-bearing.

---

## 5. Architecture invariants to preserve

Carried unchanged from the V7 plan §6, because they applied to that work and apply to this:

1. `lint-imports` stays **7/7 KEPT** after every change.
2. No new `ignore_imports` entry to make something pass.
3. Dependency direction `Interfaces → Infrastructure → Application → Domain`; `weebot/domain/`
   stays pure.
4. Fix through ports, not around them.
5. `weebot/application/di/` remains the composition root.
6. Changing a port signature is cross-boundary ⇒ `[REQUIRES HUMAN REVIEW]`.
7. Structured output stays Pydantic-validated.
8. All shell execution routes through `BashGuard`.
9. `make check` passes before any PR is opened.
10. No fix lands without its proof test in the same commit.

Plus one this plan adds:

11. **No gate is declared without proving it blocks.** Every ratchet, required check and protection
    rule ships with evidence that it fails when it should — the discipline Wave 0 established and
    the reason its ratchets are trustworthy.

---

## 6. What this plan deliberately does not do

- **It does not fix the 25 candidates.** It makes them countable and ranks them. Investigating each
  is the V7 protocol's work, not this plan's, and pretending otherwise would repeat the mistake of
  scoping a hunt larger than its budget.
- **It does not pay down the ratchets.** It repairs the *mechanism* so paydown sticks. Sweeping
  139 silent handlers without per-site judgement would trade a counted debt for 139 unreviewed
  decisions.
- **It does not propose a merge queue, staged deploys, or release automation.** The repository has
  one workflow and no deploy job; that machinery would be solving a problem that does not exist yet.
- **It does not address the Codex quota.** That is a billing decision, and the plan deliberately
  does not treat a third-party bot as a substitute for A-ii — a reviewer that can vanish when a
  quota lapses is not a gate.

---

## 7. Risks

- **R-1 — A-i without A-ii may be mistaken for done.** Required checks visibly turn the PR page
  green, which *feels* like a review gate and is not one. If A-ii is not going to happen, that
  should be a recorded decision, not a drift.
- **R-2 — the downward ratchet guard will be unpopular.** Failing a build because debt *improved*
  is counter-intuitive, and the temptation will be to delete it the first time it fires
  inconveniently. The message it prints has to explain itself well enough to survive that moment.
- **R-3 — `[HYP]` the candidate inventory could become the third place the truth lives**, alongside
  the audits and the code. The consistency gate is what prevents that, so it is load-bearing rather
  than nice-to-have; if it is skipped, do not build the inventory either.
- **R-4 — property-based tests can be flaky when the property is stated loosely.** The round-trip
  assertion must compare table *contents*, not file bytes: SQLite makes no guarantee that a backup
  is byte-identical, and asserting on bytes would produce a test that fails for correct code.
- **R-5 — protection blocks the agent too.** Once A-ii lands, autonomous sessions cannot merge
  their own work, by design. That is the point, and it should be an explicit expectation rather
  than a surprise mid-task.

---

## Appendix A — commands, so every `[VF]` claim is re-derivable

```bash
# A: branch protection and workflow shape
gh api repos/georgehadji/weebot/branches/main --jq '.protected'   # or list_branches
ls .github/workflows/
grep -n '|| echo\|continue-on-error' .github/workflows/architecture.yml

# B2: ratchet actuals (run from the repo root)
python scripts/lint_except_pass.py    # 139, ceiling 139
python scripts/lint_async_io.py       # 29,  ceiling 29
make lint-no-print                    # 143, ceiling 143
make lint-env-access                  # 73,  ceiling 73

# Cross-cutting counts (approximate — these greps are looser than the
# originals in the V7 plan, so figures differ slightly from those recorded there)
grep -rn --include='*.py' "except Exception" weebot/ cli/ | grep -v GitNexus | wc -l   # 813
grep -rn --include='*.py' "zip(" weebot/ cli/ | grep -v GitNexus | grep -v "strict=" | wc -l   # 16
```

Measured against `240107f`.

## Appendix B — the 25 uninvestigated candidates

| Wave | Candidates |
|---|---|
| W1 | D8, D9, D10, D12 |
| W2 | D16, D18, S2 |
| W3 | S5, D20, D21, D23, D26, D28, D29 |
| W4 | D32, D34, D36 |
| W5 | D39, D41, D44 |
| W6 | D47, D48, D50 |
| W7 | D37, D38 |

Full claims, locations and the reason each was deferred are in the per-wave coverage statements
under `tasks/audits/`. Four further candidates were **cleared** rather than deferred (D17, D22,
D24, `knowledge`) and are recorded there with their innocence arguments; D24 is `STATISTICAL`,
bounded by 400 trials rather than proven, and would be re-opened by any change to
`AsyncEventBus.subscribe`.
