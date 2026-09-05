# B2 — the ratchets become bidirectional

Execution record for phase B2 of
[`review_gate_and_residual_work_plan.md`](../specs/review_gate_and_residual_work_plan.md) §3.2.

**Baseline:** `051f35ee` (B1). 3858 passing.

Five ceilings, unchanged since Wave 0 measured four of them:

```
139  silent except handlers      29  blocking I/O in async
143  print() in production       73  bare env reads       68  bandit B110
```

They lived in **three** places — two as `CEILING` constants in Python scripts,
two as `?=` variables in the Makefile, one added later during A1.

---

## Three defects, not the two the plan named

The plan identified two. Measuring the mechanism found a third, and it is the
one that was immediately exploitable.

**1. Nothing enforced "never raise it."** The rule was a comment. A future edit
could raise a ceiling and CI would pass, silently converting the ratchet into a
rubber stamp.

**2. Nothing rewarded lowering it.** `lint_async_io.py` already printed *"Ceiling
can be lowered to N"* when the count dropped — as **advice**, which would be
ignored indefinitely. The slack between actual and ceiling is precisely where a
regression hides, invisibly, until it reaches the top.

**3. `[VF]` Two of the five could be disarmed from the environment.** `?=` in a
Makefile takes an override from the command line *or* the environment:

```
$ PRINT_CEILING=99999 make lint-no-print
143 print() call(s) in production code; ceiling is 99999.
exit=0
```

Both spellings work — `make lint-no-print PRINT_CEILING=99999` too. **CI runs
these targets.** Nothing was exploiting it, but the mechanism to switch off a
gate without touching a tracked file was already there, which is the same class
as A1's `|| echo` one layer down.

---

## The design

**One declarative source** — `tasks/quality/ceilings.toml` — and one rule, in
`scripts/quality_ceilings.py`:

| | |
|---|---|
| `actual > ceiling` | **fail** — new debt was added |
| `actual == ceiling` | pass |
| `actual < ceiling` | **fail** — *"set `name = <actual>`"* |

**The third row is the whole design.** It costs nothing while debt is untouched,
and makes any reduction permanent the moment it happens.

Counting stays where it already was — the AST walkers, the greps in the Makefile
— and only the *comparison* moved. That was deliberate: centralising the rule
must not be able to change a number, and all five still report exactly
139 / 29 / 143 / 73 / 68.

### Why the exact-equality rule is not sufficient on its own

Pinning `actual == ceiling` means a raised ceiling fails immediately — *unless*
the matching debt is added in the same commit, which passes. So the upward guard
is still needed, and it compares the committed ceilings against the base branch.
`[VF]` A raised ceiling is rejected naming the transition (`10 -> 11`); lowered,
unchanged and newly-added ceilings all pass.

### The distinction that keeps the upward guard honest

`git show <ref>:<path>` returns the same exit code for *"the file is new"* and
*"I could not look"*. Collapsing them would make an unfetched base branch read
as approval — the fail-open pattern, reintroduced inside the guard against
fail-open patterns.

So the ref is resolved first, separately:

- **ref resolves, file absent** → pass. No ceiling can have been raised relative
  to a file that did not exist. This is the real case for this very commit.
- **ref does not resolve** → `CANNOT VERIFY`, exit 1. An unfetched baseline is
  not a passing one, and the CI step fetches explicitly for that reason.

---

## Proof

Every guard was sabotaged and observed to fail:

| Sabotage | Caught |
|---|---|
| Raise a ceiling against the baseline | ✅ names `10 -> 11` |
| Reintroduce `PRINT_CEILING ?= 143` in the Makefile | ✅ |
| Reintroduce a `CEILING = 139` constant in a script | ✅ |
| Ask for an unresolvable baseline | ✅ `CANNOT VERIFY`, not a pass |
| Count below the ceiling | ✅ names the value to write |
| Count above the ceiling | ✅ |
| An unknown ceiling name | ✅ error, not a silent pass |

`[VF]` The `?=` override is dead: `PRINT_CEILING=99999 make lint-no-print` now
reports `print_in_production: 143, at its ceiling.`

**Two flaws were found in the test harness itself, not the production code.**
`git branch -M base` renames the *current* branch, so the next commit moved the
baseline too and every comparison was against itself — which **passed, for
entirely the wrong reason**. Four tests were green on a tautology. A tag stays
put; the fix is a tag, and the reasoning is recorded where the harness builds
its fixture. Second, a test named `test_every_ceiling_matches_reality` had a
docstring claiming it asserted equality and a body that only printed. It was
deleted rather than fixed: a test that asserts nothing is exactly what this
programme exists to remove, and having written one while removing others is
worth recording rather than quietly correcting.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` Zero is a legitimate ceiling and is asserted in both directions. A newly-added ceiling name passes the upward guard; a removed one is ignored rather than treated as lowered. |
| **Invalid input** | `[VF]` An unknown ceiling name is an error, not a pass — a typo must not silently gate nothing. Non-integer and negative ceilings fail the file check. |
| **State** | `[VF]` The checker is a pure read; the upward guard shells out to `git` read-only. No file is written by any of it. |
| **Regression** | `[VF]` Full suite 3858 → **3873** passed / 0 failed. All five counts unchanged at 139 / 29 / 143 / 73 / 68 — the point of moving only the comparison. |
| **Concurrency** | Not applicable. |
| **New defects** | `[HYP]` The bandit count depends on bandit's version. Under the old `<=` rule a detection change was only a problem upward; under exact equality a dependency bump that finds one *fewer* B110 now fails CI until the ceiling is lowered. Loud and one-line to fix, but it is new fragility that did not exist before, and dependabot will meet it first. |

---

## Phase 8 — coverage & residual risk

### Not covered

- **No debt was paid down.** All five counts are exactly where Wave 0 left them.
  B2 repairs the *mechanism* so paydown sticks; the plan is explicit that it
  *"does not pay down the ratchets"* (§6), and neither did this.
- **The per-PR budget and targeted sweeps were not implemented.** §3.2's paydown
  strategy — each PR fixes the sites in functions it already touches, plus
  mechanical sweeps only where a class is uniform — is a working practice, not
  code, and nothing here enforces it.
- **`print()` → `logger` was not swept**, though the plan names it the best
  mechanical candidate. `except: pass` deliberately was not: each of the 139
  needs a human decision about what to log and whether to re-raise.

### Residual risks

- **R-1 — exact equality adds friction to unrelated PRs.** Any change that
  incidentally removes a `print()` now fails CI until `ceilings.toml` is edited
  in the same commit. That *is* the intent — the cleanup gets locked in — but it
  converts a silent improvement into a required edit, and someone in a hurry
  will feel it.
- **R-2 — the bandit ceiling is version-coupled.** See the six-vector note. A
  `bandit` bump can now fail the build in either direction.
- **R-3 — the upward guard depends on a fetch.** It fails loudly without one
  rather than passing, so the failure mode is safe, but a CI change that drops
  the `git fetch` line turns a working guard into a red build rather than into a
  silent one. Loud, but still a way to lose the guard.
- **R-4 — five ceilings, one file, no per-ceiling ownership.** Nothing records
  who is responsible for driving each number down, so "may only go down" has no
  force pushing it downward. The ratchet prevents regression; it does not
  create progress.

### Verdict

**COMPLETE.** The mechanism is repaired: one source, one rule, enforced in both
directions, with the environment override closed and every guard proven against
the drift it exists to catch. The numbers are untouched, which is the correct
outcome for a phase about the mechanism rather than the debt.
