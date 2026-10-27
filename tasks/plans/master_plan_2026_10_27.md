---
status: open
date: 2026-10-27
note: master plan for everything still open after the 2026-10-27 audit work; tracks A to F with order, sizes, owner decisions and done criteria; track A started 2026-10-27: wave 0 repros written for A21 A24 A25 A26 A28, A33 A25 A24 fixed (branch fix/audit-track-a2); the rest not started
---

# Master plan: everything still open

This plan sits above `tasks/plans/audit_2026_10_27_fix_plan.md` (the audit plan, waves 0 to 6) and
`tasks/plans/d4_wiring_research_2026_10_27.md`. It does not repeat their detail. It says what is left, in
what order, who decides what, and how each piece is proven done. Sizes: S under half a day, M about a day,
L more. Sizes are estimates from the audit plan, not measurements.

## 1. Where things stand (2026-10-27)

- `main` holds the audit fixes A01, A02, A04 to A10, A12 (idempotent ids only), A13 to A20 (A20 in observe
  mode), A22, A23, A31, A32 and A34, plus the Discord replay, the rate-limit order and the WebSocket
  identity parts of A27. Three dependency commits (pip, npm, GitHub Actions) are also on `main`.
- The full suite passed (6630 tests) before the last two commits; the local ratchet gates pass. CI on the
  last dependency commit had not finished when this was written.
- Not built from the audit: A11 (deferred, needs a product call), A21, A24, A25, A26 (all parts), A28, A33,
  the A12 watermark, the remainder of W2.1, wave 0 repro tests for the unbuilt findings, and wave 6.
- Open outside the audit: six Dependabot PRs that break the install or lint, one stale draft PR (#54),
  17 map cards marked stale, a docs archive step that needs approval, and the older specs listed in track F.

## 2. Rules for every change

These are the standing rules, written once so the tracks need not repeat them.

- A failing test comes first, then the fix. A fix without a test that fails before it is not done.
- Ratchet ceilings in `tasks/quality/ceilings.toml` never go up. They go down when debt is paid, in the same
  commit.
- Run the whole gate list before every push, not only pytest: the architecture test, `lint-imports`, the
  ratchet scripts (bare-except, env access, print, ruff, long functions, UI debt), the map and tasks index
  checks, and `check_map_citations.py --drift`. Two CI failures on 2026-10-27 were ratchets that pytest does
  not run. Track B makes this one command.
- Tag the commit before any deletion, so any deleted piece can be restored.
- Nothing is pushed or merged without the owner saying so in that turn. External writes (Jira, HubSpot, mail,
  closing PRs, repo settings) are asked about first.
- ICM moves (archiving docs) need a referrer check and approval.
- Never touch `.env`, the databases, logs, `Output/`, or the gitignored mail seed file. API keys go in `.env`
  by the owner, never into a command or a message.

## 3. Owner decisions that gate work

| Id | Question | Recommended | Blocks |
| --- | --- | --- | --- |
| D3a | Turn the shell default-ASK from observe to enforce? | Yes if one normal 12-task batch adds 2 or fewer asks | A20 enforce |
| D4 | What happens to G8 and G9? | Keep the summary repository and Valkey trio reserved; wire the step evaluator and an eval command; delete the rest after tagging | wave 6 G8, G9 |
| D5 | Take A11, the untrusted-content guard? | Needs a product call: it makes every non-read-only tool ask after any web or mail fetch | A11 and A21 shell half |
| D6 | Apply `.github/rulesets/main.json` so `main` is protected? | Yes; today direct pushes to `main` succeed | Track B |
| D7 | Draft PR #54 (LuaLaTeX): rebase or close? | Close or park; it is 422 commits behind | Track C |
| D8 | Approve the docs archive move (slice 7 of `icm_plan.md`)? | Yes, after the referrer report | Track E |
| D9 | Enforce native Windows "network off" with a firewall rule, or keep it advisory? | Keep it advisory and document it | A22 remainder |

## 4. Tracks

### Track A: finish the audit (waves 0 to 5)

Order follows section 7 of the audit plan. Each item is one PR-sized change with its test.

1. **Wave 0, for what is unbuilt.** A strict-xfail repro for A21, A24, A25, A26, A28 and A33, each in
   `tests/unit/fixes/`. A repro that already passes means the finding is dropped and recorded. S each,
   M together.
2. **A33 gateway safety gate.** Done 2026-10-27: the gate was deleted (see the commit). `SafetyChecker` now has no production caller; add it to wave 6.
   Original text:  Decide from the repro: make `is_critical_operation` use real tool names, or
   delete the gate if the guard chain already covers gateway runs. S.
3. **A25 single writer, then A24 compare-and-swap, then A28.** In that order: one writer makes the CAS easier
   to reason about, and A28 is independent. A25 M, A24 S, A28 S.
4. **A26, as five small PRs:** cached tokens priced at the cache rate (S); cancelled and timed-out hedge
   probes billed and recorded (S); retry policy (S); image and video calls metered with the stop-after-paid-200
   rule (S); hard limit checked inside a step (S). A26 cached tokens goes after A18, which is done.
5. **A12 watermark.** Extract commitments only from events after a stored watermark, so a save no longer
   rescans every event. Then the one-off cleanup of old duplicate rows and the unique index (alembic migration
   plus the runtime `CREATE UNIQUE INDEX IF NOT EXISTS`). M. Back up the database before the cleanup.
6. **W2.1 remainder.** One `authenticate(conn)` that every HTTP path, the middleware and the socket path
   call, including store-mode key resolution for sockets. This also closes the ownership half of A27. M.
7. **A20 enforce.** After the owner runs the batch (D3a), set `WEEBOT_SHELL_DEFAULT_ASK=enforce`, or widen
   `READ_ONLY_COMMANDS` and measure again. S.
8. **A22 remainder.** Document the advisory status of native Windows "network off" in
   `docs/SECURITY_MODEL.md` (the file is gitignored, so the note lives on the owner's disk and in
   `ARCHITECTURE.md`). S.
9. **A11 and A21 shell half.** Only after D5. If yes: set the session fact when an external-trust tool
   returns, add `UntrustedContentGuard`, and test that a mail fetch followed by a shell call asks. M.

Done when: every `test_a27_*` and `test_a<NN>_*` file is a plain passing test or the finding is recorded as
not reproduced, and the audit plan frontmatter moves to `status: done` with the commit list.

### Track B: repository health and tooling

1. **One pre-push gate command.** `make` is not installed on this Windows machine, so the gate list in section
   2 cannot be run as `make check`. Add `scripts/prepush_gates.py` that runs the same list with the venv
   Python and stops at the first failure. It reads the Makefile targets rather than copying them, so the two
   cannot drift. S. This is the one tooling change that prevents the failures seen on 2026-10-27.
2. **Make CI green on `main`.** Confirm the run on the last dependency commit. Investigate
   `test_a_checked_out_connection_is_closed_too`, which failed once on the 13-minute Linux run and passes
   locally: it counts live aiosqlite threads across the whole process, so another test's threads closing at
   the same time can change the count. Make it count only threads its own pool created. S.
3. **Branch protection (D6).** Apply the checked-in ruleset per `.github/rulesets/README.md`, so the
   Protection Drift workflow passes. This is a repository-settings change, so it is the owner's action or
   done only on their say. S.
4. **Suite speed (optional).** The unit run takes about 8 minutes locally and 13 in CI. Try `pytest-xdist`
   on a branch and report which tests share global state and break. Keep it only if the failures are few and
   fixable. M, and it is an optimisation, not a fix.
5. **Dependabot configuration.** Group the major-version bumps separately and ignore the ones blocked by a
   dependency's own pin (anthropic and openai while `browser-use` pins them), so the open list stops
   re-filling with PRs that cannot pass. S.

### Track C: dependencies and open PRs

Six Dependabot PRs fail and stay open. Each has a named unblock.

| PR | Bump | Blocked by | Unblock |
| --- | --- | --- | --- |
| #86 | anthropic 1.13 | `browser-use` pins `anthropic<1.0` | a `browser-use` release that allows 1.x, or drop `browser-use` |
| #90 | openai 3 | `browser-use` pins `openai<3.0` | same |
| #91 | uuid-utils 1 | `langchain` 1.4.7 needs `<1.0` | a `langchain-core` that allows 1.x |
| #83 | eslint 10 | lint fails to load | `eslint-config-next` support for eslint 10 |
| #13 | typescript 7 | lint fails to load | `typescript-eslint` support for TypeScript 7 |
| #79 | plugin-react 6 | install fails | a vite version that satisfies its peer range |

Each is retested, not assumed, when its blocker moves: the method is the one used on 2026-10-27 (scratch
branch, isolated venv or `node_modules`, full suite, `next build`). Draft PR #54 follows D7.
The G10 requirement removals (wave 6) shrink the dependency surface and should land first, because a smaller
set has fewer pins to collide.

### Track D: dead code and wiring (wave 6)

Ordered by risk, one PR per group, tag before each. Details are in the audit plan, section 5, wave 6.

1. **G1 to G7** (templates, interface customisation, source credibility, observability orphans, QMD
   leftovers, unreferenced scripts, osworld and similar). Each PR deletes the code and its tests, removes
   `.importlinter` lines and doc mentions, lowers the ceilings it moves, and reruns map drift. About 18k lines
   in total by the audit's count. The audit's line counts for G8 and G9 did not reproduce, so recount each
   group before deleting.
2. **G11** the private guard lists in `tools/powershell_tool.py` that the guard chain duplicates. A23 already
   removed the encoded-command copy. S.
3. **G10** requirements removals, after the groups that used them. Keep `pywin32` and `duckduckgo-search`
   until checked on a clean Windows install. Regenerate `requirements.txt.lock`.
4. **G8 and G9, per D4.** If the owner takes the recommendation:
   - wire the step evaluator behind a flag (one language-model call per step, fails open) — M;
   - add `cli/commands/eval.py` with a judge from the container (writes nothing) — S to M;
   - repair the skill promotion check only if a second veto on skills is wanted; it cannot pass as written
     and a live promotion path already exists — M to L, dry-run one release first;
   - keep the summary repository and the three Valkey files, annotated as reserved;
   - delete the rest of G8 and G9 after tagging.
5. Fix `docs/SECURITY_MODULE.md:168` (says `BashTool` uses `state_verifier`, which it does not). S.

### Track E: map, docs and ICM

1. **Stale map cards.** 17 card files carry `status: stale`. Re-read each against the code, then restore
   `verified` and restamp the commit. Do it after tracks A and D, which move the code the cards cite; doing
   it now would be redone. M.
2. **Drift coverage for `map/effects/`.** The drift check does not cover it. Extend
   `scripts/check_map_citations.py` and add a test. S.
3. **Docs archive (slice 7 of `icm_plan.md`, needs D8).** Produce the referrer report for `docs/*PLAN*`,
   `*SUMMARY*` and `PROJECT_COMPLETE.md`, get approval, copy, verify, then remove. A file with a live
   referrer is held. S after approval.
4. **Entry-file hygiene.** After any `CLAUDE.md` edit, run `scripts/gen_entry_twins.py`. Update the
   `CLAUDE.md` pointers if tracks D or E rename anything.

### Track F: older open specs (the enhancement backlog)

The tasks index lists more open plans than the ones above. Their notes show most were only partly built, and several have
had nothing built for months. They are enhancements, not fixes, and building all of them is not a good use of
effort without a product reason for each. Recommended handling: the owner triages them once, and each gets
one of three outcomes, recorded in its frontmatter: **build** (gets its own plan slice with an owner), **park**
(stays open with a reason), or **abandon** (`status: superseded` or `reference`, with a note).

| Plan | What the index note says is missing | Default until triaged |
| --- | --- | --- |
| `specs/agentic_memory_fix_plan.md` | phases 5 to 8 (retrieval, preservation check, filter_context, memory-quality job) | park; phase 5 is the one consumer for the summary repository |
| `specs/arch_audit_2026_09_remediation_plan.md` | phase 5: Postgres backend, scheduler extraction, replica proof | park; needed only for multi-replica |
| `specs/arch_audit_2026_10_remediation_plan.md` | Phase 8 | read before deciding |
| `specs/bilevel_autoresearch_implementation_plan.md` | phase 3 and 4 | park |
| `specs/code_as_harness_implementation_plan.md` | phases 2 to 4 | park |
| `specs/memento_skills_implementation_plan.md` | phase 3 semantic retrieval | park |
| `specs/reasoner_enhancements_plan.md` | phase 6 pre-router | abandon candidate: never built |
| `specs/skillclaw_auto_evolve_plan.md` | none of the 6 built | abandon candidate |
| `specs/verbalized_sampling_implementation_plan.md` | sampler has no caller | wire one caller or delete the sampler |
| `specs/weebot_unified_implementation_plan.md` | P1 to P4 | park |
| `specs/review_gate_and_residual_work_plan.md` | needs a human to register a GitHub App | owner action |
| `specs/static_defect_audit_v3_execution_plan.md` | P3 to P11 not run | park |
| `specs/ui_defect_hunt_v71_execution_plan.md` and the defect-hunt audits | see their notes | read before deciding |
| `remaining_fix_plan.md`, `icm_fix_plan.md` | F28 type-safe mediator dispatch; `container_construction` ceiling still 8 | fold into track A or D if still real |
| `scientific-book-latex-plan.md` | LLM drafting, TeX Live image, CLI and web wiring | unrelated to this repo's current work; owner call |

I have not re-read these plans for this document; the "default" column comes from the index notes only.

## 5. Order and parallelism

1. **Now, in parallel:** B1 (pre-push gate) and B2 (make CI green). Everything after them is safer.
2. **Then, two lanes that touch different files:**
   - Lane 1, safety and money: Track A in the order given.
   - Lane 2, lean: Track D G1 to G7, G10, G11. It deletes code lane 1 does not edit.
3. **Wave 6 G8 and G9** wait for D4. **A11** waits for D5. **A20 enforce** waits for D3a.
4. **Track E card refresh** runs after lanes 1 and 2 settle, as one pass.
5. **Track C** re-tests each blocked PR only when its blocker is released; Track B5 reduces the noise.
6. **Track F** triage can happen any time and costs the owner about an hour of reading.

Two writers never edit the same files at once. Lane 1 and lane 2 run in separate worktrees or sessions, and
each lands through its own PR.

## 6. Owner checkpoints

The owner is needed for these, and for nothing else in this plan:

- D3a: run one normal 12-task batch and send the count from `grep -c "shell_default_ask would ask"`.
- D4, D5, D6, D7, D8, D9 as listed in section 3.
- Live checks after the audit is done: restart the API container and confirm one scheduled job fires (A01);
  send two Telegram messages in one chat (A02); run a dispatch whose sub-agents move the parent's cost (A09).
- Approve each push and merge. The repository has no branch protection until D6, so a push goes straight to
  `main`.

## 7. Done when

- Track A: as stated in its section.
- Track B: `scripts/prepush_gates.py` passes on a clean checkout, CI on `main` is green, and the flaky test no
  longer depends on process-wide thread counts.
- Track C: every open Dependabot PR is merged, closed with a reason, or blocked with a named unblock.
- Track D: each group is deleted with its tag, the ceilings it moved are lowered, and D4 is applied as chosen.
- Track E: no card is `stale`, drift covers `map/effects/`, and the docs archive step is done or declined.
- Track F: every plan has an outcome in its frontmatter.
- This file moves to `status: done` with the commit list.

## 8. Not covered, and risks

- Areas the audit did not read are listed in section 9 of the audit plan (most of `weebot-ui`, sandbox
  backends other than native Windows, all of `bash_security.py`, most repositories, `flow_router.py`, dead
  code inside `interfaces/` and `tools/`). Fixes there are not in this plan because nothing there is known.
- Line counts in wave 6 are the audit's and did not reproduce for G8 and G9; recount before each deletion.
- The sizes are estimates. The total is large; track A and the first lane of track D are the part that
  changes behaviour, and the rest is hygiene.
- Live behaviour is checked only by the tests, the gates, and the owner's checks in section 6. The Playwright
  tests and the UI against a live backend were not run for this work.
