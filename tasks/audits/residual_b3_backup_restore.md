# B3 — backup and restore: the named test gap

Execution record for phase B3 of
[`review_gate_and_residual_work_plan.md`](../specs/review_gate_and_residual_work_plan.md) §3.3.

**Baseline:** `4e4e68a4` (B2). 3873 passing.

`implementation_audit_report.md` §6 recorded no tests for `scripts/backup.py`,
`scripts/restore.py` or `_database_backup_job`, and the V7 plan called this *"the
highest-value place in the repo to add proof tests"* — a subsystem whose last
three defects were CRITICAL. Nothing had been written.

**Writing them found three defects, and one of them loses data.**

---

## The three defects

| | Defect | Verdict |
|---|---|---|
| **B3-a** | `_database_backup_job` raises `AttributeError` on every run | ✅ **the daily backup has never once executed** |
| **B3-b** | `verify_backup` raises instead of returning `False` on a malformed file | ✅ the interlock's contract is violated |
| **B3-c** | Restoring the pre-restore backup destroys it first | ✅ **the documented undo silently loses data** |

### B3-a — a scheduled job that has never run

```python
db_path = settings.sessions_db_path or os.environ.get("WEEBOT_SESSIONS_DB")
```

`[VF]` **`WeebotSettings` has no attribute `sessions_db_path`.** It appears
nowhere in `settings.py`, `git log -S` shows it was **never** in that file, and
it is referenced in exactly one place in the whole tree — this line. So
`_database_backup_job()` raised `AttributeError` before deciding anything, on
every scheduled run since it was written.

This is the plan's own prediction, realised harder than it feared:

> *"A backup job that fails silently is indistinguishable from one that works
> until the day it matters — the purest possible instance of the C2 class."*

It does not fail silently; it fails *immediately*, every time. The configured
path is the module-level `SESSIONS_DB` in `settings.py:12`, which already reads
`WEEBOT_SESSIONS_DB` and defaults to `./weebot_sessions.db`.

### B3-b — the interlock raised rather than refusing

`verify_backup` is the safety interlock between a bad backup and an overwritten
database, and callers use it as `if not verify_backup(path):`. But
`PRAGMA integrity_check` **raises `sqlite3.DatabaseError`** once a file is
damaged badly enough — which is exactly the case the interlock exists for — so
the exception went through the `if` rather than becoming a `False`.

It failed *safe* (the exception precedes the copy, so no destination was
destroyed) but not *correctly*: the CLI crashes with a traceback instead of
reporting `exit 2`, and any caller that wraps this in a broad `except` and
continues would read a crash as "not verified" rather than "corrupt".

### B3-c — the safety net destroys itself

The documented recovery path is: a mistaken restore can be undone by restoring
the `<dest>.pre-restore-bak` that `restore()` leaves behind. **It does not
work**, and the reason is a name collision:

```
1. restore(backup → live)   live(OLD) renamed to live.sqlite.pre-restore-bak
                            backup(NEW) copied to live          ✓ correct
2. restore(pre_bak → live)  live(NEW) renamed to live.sqlite.pre-restore-bak
                              ^^^ that IS pre_bak — OLD is overwritten by NEW
                            copy2(pre_bak → live) now copies NEW back
```

`[VF]` Reproduced end to end: `live` before `['OLD']`, after step 1 `['NEW']`
with the net holding `['OLD']`, and after the undo `['NEW']` — with the original
**gone**, under the message *"Restore completed successfully."*

The recovery path for an irreversible operation returns the very data it was
meant to undo, and reports success.

---

## Fixes

| # | File | Change |
|---|---|---|
| 1 | `weebot/scheduling/default_jobs.py` | Read `_settings.SESSIONS_DB`; drop the `WeebotSettings()` build that served only the broken lookup |
| 2 | `scripts/restore.py`, `scripts/backup.py` | `verify_backup` catches `sqlite3.DatabaseError` and returns `False` |
| 3 | `scripts/restore.py` | `_pre_restore_path()` never clobbers an existing net |

Fix 3 keeps the documented `.pre-restore-bak` name for the common first case and
only diverges on a collision, so nothing about the normal path changes.

---

## The tests

`tests/unit/scripts/test_backup_restore_roundtrip.py`, **17 tests**, covering the
plan's full matrix. The round trip is property-based via `hypothesis` (added to
`requirements.txt`): a hand-written example asserts that one database survives,
a property asserts that *databases* do.

| Property | |
|---|---|
| **Round trip** `restore(backup(db)) == db` | 60 generated examples over mixed NULL/int/float/text/blob rows, plus explicit empty-table and >100 KiB blob cases |
| **WAL safety** | backup taken with a second connection mid-transaction; the backup shows the last committed state, not the dirty write |
| **Integrity gate** | a corrupted backup is refused with `exit 2` and the destination is asserted intact |
| **Pre-restore net** | the net exists, is itself a working database, **and restoring it actually undoes the restore** |
| **Retention** | older pruned, newer kept, `0` and negative keep everything, and one label's prune does not reach another's files |
| **Confirmation** | declining the prompt leaves the destination byte-identical; `--force` never prompts |
| **The scheduled job** | a non-zero backup exit and a failure to start are both logged at ERROR |

**Red before green:** against the original sources, **4 failed / 13 passed** —
one failure per defect (two for B3-a, one each for B3-b and B3-c). With the
fixes, **17 passed**.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` Empty database, >100 KiB blob (overflow pages), `retention=0` and negative retention, and a destination that does not yet exist are each covered explicitly. NaN is excluded from generation with a stated reason: sqlite stores it as NULL, so a NaN round trip tests sqlite's type rules, not the backup. |
| **Invalid input** | `[VF]` Corrupt backup, missing backup file, and a declined confirmation each assert the destination is untouched — the property that matters more than the exit code. |
| **State** | `[VF]` Every test builds its own database in `tmp_path`; the property test creates its own temporary directory per example rather than taking a function-scoped fixture, which hypothesis would share across all 60 runs. |
| **Regression** | `[VF]` Full suite 3873 → **3890** passed / 0 failed. `ruff check weebot/ cli/ --select F821,E9` clean; all five ratchets unchanged at 139/29/143/73/68. |
| **Concurrency** | `[VF]` The WAL test is the only concurrent case: a second connection holds an uncommitted write while the backup runs. Nothing here is async. |
| **New defects** | `[HYP]` `_pre_restore_path` falls back to a UTC timestamp with second granularity plus a counter. The counter makes collision impossible in practice, but the resulting filename is no longer the documented one, so a runbook or script that hard-codes `.pre-restore-bak` would not find the second net. |

---

## Phase 8 — coverage & residual risk

### Not covered

- **`restore.main()` still returns 0 when the *restored copy* fails its
  integrity check.** `restore()` computes the verdict, prints `FAILED`, and
  discards it; `main()` then prints "Restore completed successfully." and exits
  0. It is a narrow window — `main()` verifies the *backup* first, and
  `shutil.copy2` would normally raise rather than truncate — so it was left
  alone rather than widened into this change. **It is a real fail-open path and
  it is still there.**
- **`backup_database` mutates its source.** It issues `PRAGMA journal_mode=WAL`
  on the database being backed up, so taking a backup changes the source's
  journal mode. `[VF]` Worse, *changing* the mode needs an exclusive lock, so on
  a non-WAL database with a writer mid-transaction the backup fails outright
  with `database is locked` — the very scenario `sqlite3.backup()` was chosen to
  survive. The live database is already WAL, so this is latent; the WAL test
  sets the source to WAL first and says why.
- **Backups within the same second collide.** The filename is
  `{label}_{%Y%m%dT%H%M%SZ}.sqlite`, so two backups in one second silently
  overwrite. Not triggered here and not fixed.
- **No test drives the real scheduler.** The two job tests call
  `_database_backup_job()` directly with `create_subprocess_exec` patched. That
  the *scheduler* surfaces a raising job is not asserted — and it logs catch-up
  failures at `warning`, not `error`.

### Residual risks

- **R-1 — B3-a means there is no evidence any backup has ever been taken by the
  scheduler.** The fix makes the job run; it does not tell anyone that the
  backups they believed existed do not. Whoever operates this should check the
  backup directory before trusting it.
- **R-2 — the `.pre-restore-bak` name is now conditional.** Documented behaviour
  for the first restore, timestamped for later ones. Anything that globs for the
  exact old name sees only the first.
- **R-3 — the round-trip property compares table contents, not the file.** It
  asserts the data survives, not that indexes, triggers, views or `PRAGMA
  user_version` do. `sqlite3.backup()` copies pages so they should, but that is
  reasoning, not measurement.
- **R-4 — `hypothesis` is a new dependency.** It is in `requirements.txt` beside
  the pytest block, and the test file imports it directly rather than through
  `importorskip`, so a missing install is a loud collection error rather than a
  silent skip. That is deliberate — a skipped proof reads as a passing one — but
  it does mean the whole file fails if the dependency is absent.

### Verdict

**COMPLETE.** The gap named by two separate plans is closed with 17 tests, and
closing it found three defects in a subsystem that had none — including a daily
backup job that had never executed and a documented recovery path that destroys
the data it exists to recover. One fail-open path in `restore.main()` is
recorded and deliberately left.
