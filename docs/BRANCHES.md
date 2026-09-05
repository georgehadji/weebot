# Branches: why this repository has two disjoint histories

Phase A4 of [`tasks/specs/review_gate_and_residual_work_plan.md`](../tasks/specs/review_gate_and_residual_work_plan.md),
which listed the task as *"delete or document the stale `master` branch"*.
**The answer is document, and the plan's premise was wrong: `master` is not
stale.** It is the project's first five months of history, and it holds both
release tags. This file is the written reason for keeping two.

## The measurement

| | `main` | `master` |
|---|---|---|
| Head | `3fd25df` (2026-09-05) | `901e476` (2026-07-21 09:53) |
| Commits | 120 | 490 |
| First commit | 2026-07-21 14:56 | 2026-02-28 01:38 |
| Root commits | **four** | one (`6f020ee`) |
| Release tags | none | **`v2.0.0`, `v2.1.0`** |
| Referenced by CI | yes (`architecture.yml`) | no |

**The two branches share no common ancestor.** `git merge-base main master`
exits 1 with no output. They are separate histories that happen to live in one
repository, not a branch and its trunk.

```
master   6f020ee ──────── v2.0.0 ── v2.1.0 ─────────── 901e476   (490 commits)
         2026-02-28                                    2026-07-21 09:53

main                                          b746057 ─────────── 3fd25df   (120 commits)
                                              2026-07-21 14:56    2026-09-05
                                              + three more parentless roots
```

`[INFERENCE]` The chronology points to a restart rather than a fork: `main`'s
earliest commit lands five hours after `master`'s last, on the same day, with no
ancestry between them. Three further parentless commits were added to `main` on
2026-07-21 and 2026-07-29, so `main` itself was assembled from several
unconnected starting points rather than grown from one. The commit contents were
evidently carried across; the git ancestry was not.

## Why `master` stays

1. **It holds the only two release tags.** `v2.0.0` and `v2.1.0` are both on
   `master` and on no other branch. The tags are independent refs so the commits
   would survive the branch's deletion, but the branch is what makes them
   readable as a line of development.
2. **It is the only record of 490 commits** — 2026-02-28 to 2026-07-21 — that
   are unreachable from `main`.
3. **Keeping it costs nothing.** It is referenced by no workflow, no Makefile
   target and no configuration, so it cannot affect a build. It is not a
   maintenance burden; it is an archive.

Deleting it would trade an irreversible loss of context for no benefit.

## Consequences to know about

- **`main` is the default branch and the only one under protection.** The
  ruleset in [`.github/rulesets/main.json`](../.github/rulesets/main.json)
  targets `~DEFAULT_BRANCH`, so `master` is unprotected — appropriate for an
  archive, but it does mean `master` can be force-pushed or deleted by anyone
  with write access. If that matters, add a second ruleset targeting it.
- **Do not attempt to merge them.** With no merge base, `git merge master` into
  `main` would need `--allow-unrelated-histories` and would produce a conflict
  in essentially every shared path. There is no version of that which is useful.
- **Archaeology needs an explicit ref.** `git log v2.1.0` and
  `git log origin/master` work; searching `main`'s history for anything before
  2026-07-21 will find nothing.

## If you do decide to remove it

Tag it first, so the history stays reachable after the branch ref is gone:

```bash
git tag archive/pre-2026-07-restart origin/master
git push origin archive/pre-2026-07-restart
git push origin --delete master
```

Deleting the branch without that tag leaves 490 commits reachable only through
`v2.0.0` and `v2.1.0`, and unreachable entirely if those tags are ever removed.
