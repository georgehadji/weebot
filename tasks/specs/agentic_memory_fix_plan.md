# Memory subsystem repair plan (AgeMem-derived)

Companion to [agentic_memory_agemem_weebot_analysis.md](agentic_memory_agemem_weebot_analysis.md).
Date: 2026-08-11. Every claim below carries a `file:line` anchor and was verified by reading
or executing the code, not inferred from names.

**Read §0 and §1 before touching anything.** §0 corrects two claims in the analysis document
that turned out to be wrong; §1 is the set of gates and pre-existing failures that determine
whether a change is even shippable.

---

## 0. Corrections to the prior analysis

**0.1 — `self._compactor` is NOT dead. The analysis was wrong.**
`plan_act_flow.py:182` assigns it and `states/executing.py:607` consumes it as
`context._compactor.compact_session(context._session)` — `context` *is* the PlanActFlow.
Mid-flow compaction already runs after every non-terminal step. **Deleting the field raises
AttributeError on every step of every task**, and no test would catch it (`grep '_compactor'`
over `tests/` returns nothing). The original grep only covered `plan_act_flow.py`.

The dead thing is real but different: the **turn-boundary compression block at
`plan_act_flow.py:758-829` has never executed once**. It builds `MessageEvent(role="system")`,
but `event.py:78` declares `role: Literal["user", "assistant"]`, so pydantic raises
ValidationError at line 806 on every invocation, swallowed by the block's bare `except
Exception` → `logger.debug` at :828-829. The `self._session = ...` assignment at :816 is
unreachable. Worse, `mgr.prepare()` at :778 does the full token count *and* the whole
`LossyContextCompressor.compress()` pass before the line that raises — the work is done and
thrown away on every iteration past 20 events.

**0.2 — `memory_metadata` is not empty, and `salience` is a regression, not a missing feature.**
`git show c921de5:weebot/infrastructure/persistence/sqlite_state_repo.py` shows the original
`upsert_memory_metadata(self, entry_hash, entry_text, source='agent', salience: float = 0.5)`
which also updated `entry_text` on conflict. Commit `5327746` moved the method to
`_memory_metadata_repo.py` and dropped both. The live `weebot_sessions.db` still holds 7 rows,
all at `salience=0.22` with `access_count` 90/12 — a value the current SQL (0.5 insert,
`MIN(1.0, salience+0.05)` bump) can never produce. So F1 is a **revert**, and the plan must
account for existing rows.

---

## 1. Ground rules

### 1.1 Gates that actually block

CI is one workflow, `.github/workflows/architecture.yml`. The blocking commands are:

```bash
ruff check weebot/ cli/ --select F821,E9
```
```bash
lint-imports --config .importlinter --verbose
```
```bash
python -m pytest tests/unit/test_architecture_fitness.py
```
```bash
python -m pytest tests/unit/ -v --tb=short --cov=weebot --cov-report=term --cov-fail-under=52
```

Plus `tests/e2e/test_persistence.py`, `tests/integration/test_cqrs_handlers.py`,
`tests/integration/test_security_penetration.py`, `tests/integration/test_event_bridge_contract.py`,
`tests/e2e/ -m "not external"`, and `bash scripts/check-secrets.sh --ci`.

**Not gates, despite appearances:** `make check` cannot pass today (`scripts/lint_async_io.py`
exits 1 with 80 violations; `lint-no-print` would fail on 142 `print(` calls). `make` is not
installed on this machine — run the underlying commands directly. Full-ruleset `ruff check`
reports 37 pre-existing violations across the four target files; **do not drive-by fix them**
(`ruff --fix` on `sqlite_state_repo.py` alone rewrites 20 lines). mypy is installed but
unconfigured and has no baseline — keep it out of the acceptance criteria.

### 1.2 Pre-existing failures — not yours

- `tests/unit/test_architecture_fitness.py::test_orphan_ports_flagged` **fails on a clean
  tree**: `Ports with zero implementations (orphans): {'StepAuditPort'}`. Introduced by commit
  `8cc7611` (the LongHorizon-Harness work). `StepAuditPort` lives at
  `application/ports/step_audit_port.py:19` with its only implementation at
  `application/services/step_evidence_auditor.py:37`; the test only scans `application/di/` and
  `infrastructure/` and the port is missing from `known_orphans` (:918-940). **Fix this first
  (P0.2) — it is a one-line addition and it is blocking CI right now.**
- `test_core_no_application_imports` fails **on Windows only**: `subprocess.run(..., text=True)`
  cannot decode the em dash in an import-linter contract name under the cp1253 console codepage,
  so `result.stdout` is `None`. import-linter itself is green (7 kept, 0 broken). Will not
  reproduce on ubuntu CI. Do not chase it.

### 1.3 Test loop — use the fast path

`pytest` costs ~150-180s per invocation in entry-point plugin autoload alone (`40 passed in
26.28s` took 204s wall). Verified 3-4x faster with identical results:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/unit/test_salience.py -q -p pytest_asyncio.plugin -p pytest_timeout -p pytest_mock
```

The asyncio plugin name must be `pytest_asyncio.plugin`, **not** `pytest_asyncio` — the wrong
name silently produces "async def functions are not natively supported" failures that look
exactly like a real async regression.

### 1.4 Architecture constraints binding this work

| Rule | Source | Consequence |
|---|---|---|
| `weebot/tools/` must not import `weebot.infrastructure` | `.importlinter:31-36` | The two `persistent_memory` exemptions cover **only** `filesystem_memory` and `sqlite_state_repo` (:38-41, :50-52). A `numpy_vector_store` import is illegal. |
| `ignore_imports` budget | `test_architecture_fitness.py:1401` `assert count <= 72`; currently **70** | Two slots left, repo-wide. Prefer designs needing zero. |
| `application/services/` must not import `weebot.infrastructure` at **any** scope | `test_architecture_fitness.py:754-793` | `semantic_skill_retriever.py`'s lazy `NumpyVectorStore` import is a closed grandfathered exception, not a pattern to copy. |
| `plan_act_flow.py` ≤ 1000 lines | `test_architecture_fitness.py:871` | Measured **997**. Three lines of headroom. Re-measure with `read_text().count('\n')+1` before editing. |
| `plan_act_flow.py` ≤ 35 distinct `from weebot.` imports | `:1143-1151` | Currently 31. |
| New port under `application/ports/` must be referenced from `infrastructure/` or `di/` | `:891-982` | Otherwise `test_orphan_ports_flagged` fails — exactly the `8cc7611` mistake. |
| `_base.py` must not contain `def _maybe_compress` or `self._maybe_compress` | `:1029-1042` (regex) | Keep all compression logic in `_context_compressor.py`. The existing `self._context_compressor._maybe_compress()` at `_base.py:565` does not match. |
| `PersistentMemoryTool` must stay zero-arg constructible | `tool_registry.py:441-448`, `tool_discovery.py:238-245` | Both call `tool_cls()` just to read `.name`. A required ctor arg silently removes the tool from the registry. |
| New feature flag shape | `feature_flags.py` | `NAME_ENABLED: bool = _env_bool("WEEBOT_NAME", default=False)`, imported **lazily inside the consuming function** — a module-level `from ... import FLAG` captures the value at import and cannot be monkeypatched. |

### 1.5 Test-isolation hazard

`WEEBOT_MEMORY_DIR` is frozen at **module import time** in two places
(`filesystem_memory.py:21-23`, `settings.py:12`), so `monkeypatch.setenv` after import does
nothing. `SQLiteStateRepository`'s default is the CWD-relative literal `'./weebot_sessions.db'`
(`sqlite_state_repo.py:49`), not `settings.SESSIONS_DB`. No conftest isolates either.

Consequence measured on this machine: `~/.weebot/memory/AGENT.md` is 9 KB / 32 entries, of which
**26 are the literal string `test entry`** written by `tests/unit/test_med_priority.py:157`
constructing `FileSystemMemoryAdapter()` against the real home directory. That file is
concatenated verbatim into **every executor step's system prompt**
(`filesystem_memory.py:48-59` → `_base.py:463-465`, no truncation anywhere).

Every new test must pass `memory_dir=tmp_path` and `db_path=str(tmp_path/'x.db')` **explicitly**.

---

## 2. Decisions required before coding

| ID | Decision | Recommended default | Why |
|---|---|---|---|
| **D-A** | Which salience model wins: `compute_salience` (0.4·recency + 0.6·frequency, `salience_scorer.py:25-70`) or the SQL accumulate model (0.5 insert, `+0.05` per access) | **SQL accumulate.** Drop the `compute_salience` call at `persistent_memory.py:140` entirely. | The tool hardcodes `access_count=2` → a constant **0.22**, which is *below* the sweep's 0.3 eviction threshold. Wiring it in makes every memory row an eviction candidate from birth on an hourly job. Nothing currently depends on the Python formula. |
| **D-B** | The 7 legacy `salience=0.22` rows (49 days old) become eviction candidates once the sweep has anything to see | **Leave them.** Document it. | Eviction deletes *metadata rows only*, never `AGENT.md`. The next read re-inserts at 0.5. Churn, not loss. Revisit if Phase 4 ever ranks prompt content by salience. |
| **D-C** | Cleaning the 26 `test entry` rows out of the user's real `~/.weebot/memory/AGENT.md` | **Ask the user, back up first.** | It is the user's data, even though it is test litter. The *leak* (P0.4) can be fixed without touching the file. |
| **D-D** | `sentence-transformers` is the only working embedding backend and is declared in **no** dependency file (`requirements.txt`, `requirements.txt.lock`, and `pyproject.toml`'s empty `dependencies` list all lack it) | **Optional extra + graceful degrade.** Never a hard dependency. | Adding torch puts ~2 GB and a multi-minute import into every install. On CI, `is_available()` is `False`, so anything depending on real retrieval silently no-ops there. |
| **D-E** | Whether Phases 5-8 happen at all | **Defer. Reassess after Phase 4.** | Once the test litter is gone and the snapshot is capped, a 6-entry `AGENT.md` does not need semantic retrieval. Phases 5-8 are only justified if real memory grows past the cap. |

---

## 3. Phase 0 — prerequisites (no behavior change)

Ship these first, as one small PR. Nothing here changes runtime behavior; every later phase
depends on at least one of them.

### P0.1 — Unblock CI
Add `"StepAuditPort"` to the `known_orphans` set at
`tests/unit/test_architecture_fitness.py:918-940`, in the same "implementation lives in
application/" group as the already-listed `StepEvaluatorPort`. One line + a comment naming
`application/services/step_evidence_auditor.py:37`.

**Verify:** `python -m pytest tests/unit/test_architecture_fitness.py -k orphan_ports -q`

### P0.2 — Stop the memory-file leak
`tests/unit/test_med_priority.py:157` writes to the developer's real home directory. Two edits:

1. In that test, `PersistentMemoryTool(memory=FileSystemMemoryAdapter(memory_dir=tmp_path))`.
2. Add an autouse fixture to `tests/unit/conftest.py` that monkeypatches
   `weebot.infrastructure.persistence.filesystem_memory.DEFAULT_MEMORY_DIR` to a tmp path.
   This works where `monkeypatch.setenv` does not, because `FileSystemMemoryAdapter.__init__`
   reads the **module attribute** at call time (`filesystem_memory.py:35-36`), not the env var.

**Verify:** run the unit suite, then confirm `~/.weebot/memory/AGENT.md` mtime is unchanged.

### P0.3 — Correct the docstring that misdescribes the system
`persistent_memory.py:6-11` claims the snapshot is *"a FROZEN snapshot at session start"* that
*"preserves the LLM's prefix cache for the entire session"*. False:
`execute_step_handler.py:78-86` constructs a **new** `ExecutorAgent` per step and
`_base.py:436-467` re-reads both files from disk on **every** step. Any design that cites the
prefix-cache property is designing around a lie. Fix the docstring in the same PR as any
snapshot work at the latest — earlier is better.

While in the file: collapse the duplicate `FileSystemMemoryAdapter` import (`:20` and `:21-24`,
both covered by the same single `ignore_imports` entry) and drop the unused `DELIMITER` / `Path`
imports.

### P0.4 — Decide D-C
If the user approves, back up `~/.weebot/memory/AGENT.md` and remove the 26 `test entry`
records. Do this **after** P0.2, or the litter comes straight back.

---

## 4. Phase 1 — salience write and read paths (F1)

**Goal:** the memory-metadata pipeline actually records something, the pinned user profile is
actually stored and actually retrieved, and neither change starts deleting data.

### 4.1 What is broken (all verified by execution)

1. `SQLiteStateRepository.upsert_memory_metadata(self, entry_hash, entry_text, source='agent')`
   (`sqlite_state_repo.py:423-426`) takes no `salience`. Two callers pass one:
   - `persistent_memory.py:141` — 4 positional args → `TypeError: too many positional arguments`,
     swallowed by `except Exception: pass` (:144-145).
   - `user_model_consolidator.py:65` — `salience=1.0` kwarg → `TypeError: got an unexpected
     keyword argument 'salience'`, swallowed by `except Exception: logger.debug` (:72).
2. The value is computed **in SQL**, not bound: `_memory_metadata_repo.py:19-35` hardcodes
   `0.5` on insert and `MIN(1.0, salience + 0.05)` on conflict. Adding a parameter to the facade
   alone would be silently ignored.
3. The `ON CONFLICT` branch never updates `entry_text` **or** `source`. The consolidator always
   writes the same key `sha256(b'user_model_profile')[:16]`, so even with the arity fixed the
   profile is **write-once** and every later hourly consolidation discards its own output. And
   `source` can never transition `'agent'`→`'user'`, which is the exact field the consolidator
   filters on (`user_model_consolidator.py:51`).
4. The read is wrong independently: `get_low_salience_entries(threshold=1.01, limit=5)`
   (`_base.py:423`, `_prompt_builder.py:106`) is `WHERE salience < ? ORDER BY salience ASC LIMIT ?`
   (`_memory_metadata_repo.py:41-51`). A pinned `salience=1.0` row sorts **last** and vanishes as
   soon as five lower-salience rows exist.
5. Fixing the arity **unmasks a second bug in the same function**:
   `user_model_consolidator.py:41-42` does `raw_rules = await self._repo.list_behavioral_rules()`
   then attribute access `r.rule_text`, but the SQLite path returns `list[dict]`
   (`sqlite_state_repo.py:394-396` → `_behavioral_rule_repo.py:38-43`). AttributeError, swallowed
   at :43-44 — rules are **always empty in production**. The existing unit test cannot see it
   because its fixture returns pydantic `BehavioralRule` objects
   (`tests/unit/test_user_model_consolidator.py:13-19`).

### 4.2 Changes

**Do not touch `StateRepositoryPort`.** `upsert_memory_metadata` and `delete_memory_entries` are
**not** on the port today (`state_repo_port.py:56-72` declares only `get_low_salience_entries`);
they are duck-typed. Adding them as `@abstractmethod` makes `InMemoryStateRepository` and
`PostgreSQLStateRepository` **uninstantiable** — verified: `Can't instantiate abstract class
without an implementation for abstract method 'upsert_memory_metadata'` — breaking
`tests/integration/test_cqrs_handlers.py:49` and `tests/e2e/test_flow_e2e.py:98`, both blocking
CI jobs, plus three more test files. Keeping them off the port is both the smaller diff and the
safer one.

| # | File | Change |
|---|---|---|
| 1 | `infrastructure/persistence/_memory_metadata_repo.py:19-35` | Add `salience: float \| None = None`. Bind it into the INSERT (default `0.5` when `None`). In `ON CONFLICT DO UPDATE SET`, add `entry_text = :text`, `source = :source`, and make salience `MAX(salience, :salience)` when an explicit value is given, else keep `MIN(1.0, salience + 0.05)`. Explicit values **pin**; they never lower an accumulated score. |
| 2 | `infrastructure/persistence/_memory_metadata_repo.py` | Add `get_by_hash(entry_hash) -> dict \| None` — a plain `SELECT ... WHERE entry_hash = ?`. |
| 3 | `infrastructure/persistence/sqlite_state_repo.py:423-426` | Thread `salience` through. Add `get_memory_entry(entry_hash)` delegating to `get_by_hash`. Both must `await self._init_helpers()` first, or `self._memory_metadata` is `None`. |
| 4 | `tools/persistent_memory.py:133-145` | Delete the `compute_salience` import and call (**D-A**). `_track_salience` records access only; the SQL bump owns the value. Replace `except Exception: pass` with a warning logged **once per instance** (a `_salience_warned` flag), DEBUG thereafter — `_read` calls this once per entry (`:149-151`), i.e. 32 times per read on the live file. |
| 5 | `tools/persistent_memory.py:80-99` | Accept an optional `state_repo=None` ctor arg (default preserved — the class **must** stay zero-arg constructible). When the DI fallback runs, resolve `StateRepositoryPort` from the same Container it already builds and stash it, instead of constructing a bare `SQLiteStateRepository()` whose CWD-relative default lands salience rows in a different file from every reader. `weebot.tools → weebot.application.ports` is a legal direction. |
| 6 | `application/agents/executor/_base.py:416-433` and `_prompt_builder.py:101-113` | Replace the `get_low_salience_entries(threshold=1.01, limit=5)` scan with a direct `get_memory_entry(key)` lookup, keeping the existing `repo is not None` guard and the swallowing `except`. |
| 7 | `scripts/replace_prompt_block.py` | **Delete it.** It is a one-off codemod already applied (`_base.py:414-467` matches its output verbatim) that hardcodes the exact `threshold=1.01, limit=5` block at `:47-64`. Re-running it silently reverts change #6. |
| 8 | `application/services/user_model_consolidator.py:42` | `r.rule_text` → duck-typed dict access. Flip the fixture at `tests/unit/test_user_model_consolidator.py:13-19` to return dicts; `test_consolidate_without_llm:27` already asserts the rule text appears, so it becomes a genuine gate. |

**Leave `WHERE salience < ?` strictly exclusive.** `threshold=1.0` at
`user_model_consolidator.py:49` and `threshold=1.01` at the executor read sites are
"fetch everything" hacks riding on that `<`. Changing it to `<=` makes the consolidator read
back the `salience=1.0` profile it just wrote and feed the model its own output into the next
distillation. Add an inline comment naming the dependency.

**No Alembic migration is required.** The `salience REAL NOT NULL DEFAULT 0.5` column already
exists (`sqlite_state_repo.py:163-178`) — that is why the 0.22 rows survived the refactor. F1
changes VALUES and ON CONFLICT only. If a future change *does* add a column it needs **both** a
new Alembic revision (`down_revision='c0re_5ch3m4_v1'`, hand-written SQL — `env.py` sets
`target_metadata=None`, so autogenerate is unavailable) **and** the inline DDL edit: Docker runs
only Alembic (`docker-entrypoint.sh:4-10`), local/CLI/pytest run only the inline DDL, and
`IF NOT EXISTS` is a no-op against an existing table.

### 4.3 Tests (all against a **real** `SQLiteStateRepository` on `tmp_path`)

`InMemoryStateRepository.get_low_salience_entries` returns `[]` unconditionally
(`in_memory_state_repo.py:51-54`), so any test substituting it passes vacuously. Every existing
test in this area uses `AsyncMock`, which accepts any arity and therefore cannot see the bug.

Put them in `tests/unit/` — **not** a new `tests/integration/` file. CI runs `tests/unit/`
wholesale but only three *named* files from `tests/integration/`, so a new integration file
would never execute on the pipeline.

1. `upsert_memory_metadata(..., salience=1.0)` then read back `== 1.0`. Fails today with
   `got an unexpected keyword argument 'salience'`.
2. Upsert the same hash twice with different `entry_text`; assert the second text wins
   (the write-once fix).
3. Insert 5 rows at low salience plus the pinned profile at 1.0; assert `get_memory_entry(key)`
   returns it. Fails today under the ASC+LIMIT query.
4. `build_executor_prompt(..., state_repo=fake)` where `fake.get_memory_entry` returns
   `{'entry_text': 'PROFILE-XYZ'}`; assert `'PROFILE-XYZ' in prompt`.
5. caplog: pre-set `tool._salience_repo` to a mock raising `RuntimeError`, call
   `_track_salience`, assert exactly **one** WARNING (not one per entry).
   `tests/conftest.py:17-39` already un-pins the weebot logger so caplog works.
6. Instantiation smoke: `InMemoryStateRepository()`, `PostgreSQLStateRepository()`,
   `SQLiteStateRepository(db_path=str(tmp_path/'x.db'))`. Instantiation *is* the assertion —
   `tests/unit/test_port_contracts.py:126-132` filters out abstract classes, so it would
   silently drop a broken adapter rather than fail.
7. Change `tests/unit/test_user_model_consolidator.py:21` to
   `AsyncMock(spec=SQLiteStateRepository.upsert_memory_metadata)` and assert
   `kwargs['salience'] == 1.0`.

### 4.4 Stop conditions

- If the hourly `memory_salience_sweep` (`config/jobs.yaml`, enabled, interval 1h) is ever
  wired to a salience source that writes **below 0.3**, stop and revisit **D-A** — that turns a
  dead feature into a live deleter.
- After F1, `_read` upserts every entry on every read and `MIN(1.0, salience+0.05)` saturates
  everything to 1.0 within ~10 reads, making the sweep permanently inert. That is the *safe*
  failure direction and is accepted here, but note it: the tier machinery
  (`classify()`, `demote_candidates()`, `enforce_hot_capacity()`) is never called by `sweep()`,
  which hardcodes `tier=COLD` (`memory_lifecycle_service.py:168`). Fixing that is out of scope.

---

## 5. Phase 2 — destructive memory edits (F2)

`persistent_memory.py:183-186`:

```python
for i, e in enumerate(entries):
    if match in e:
        entries[i] = new_entry     # every match becomes the SAME text
```

Verified: three entries containing `'note'` → `['CLOBBER', 'CLOBBER', 'CLOBBER']`. Reported to
the agent as success. `_remove` (`:195-206`) has identical substring semantics, deletes every
match unconditionally, and — unlike `add`/`replace` — never runs `scan_injection` on its input.

No compatibility risk: zero tests call replace or remove on this tool, and the only skill that
touches persistent memory (`skills/builtin/reify_skill/SKILL.md:75-77`) calls a **non-existent**
`action=add_memory` with non-existent `content`/`group` params — every such call returns
`Unknown action: 'add_memory'` and writes nothing. The tool's own docstring says
*"replace an existing entry"*, singular (`:37`).

**Changes:**
1. `_replace`: when `match` hits more than one entry, return
   `ToolResult.error_result(...)` with the candidate texts in `data` — never raise. A raise is
   converted by `tool_collection.py:258-272` but loses all structured `data`.
2. `_remove`: same >1-match guard, and return the removed texts in `data` so the deletion is
   recoverable from the transcript. Also run `scan_injection` on `match`.
3. Reject a literal `§` in `entry` on write — the delimiter is unescaped, so
   `add('sec§tion')` silently reads back as two entries (`filesystem_memory.py:79`).
4. Fix or delete the `reify_skill/SKILL.md:75-77,111` instruction in the same PR.

**Test** (new `tests/unit/test_persistent_memory.py`): seed three entries containing `'note'`
via `FileSystemMemoryAdapter(memory_dir=tmp_path)`, call `action='replace', match='note'`,
assert `result.is_error` **and** that `read_entries` still returns the three originals.

---

## 6. Phase 3 — the dead turn-boundary block, and a live index bug (F3, restated)

### 6.1 Delete the block

Remove `plan_act_flow.py:758-829` outright.

- It has never executed (§0.1) and its only observable effect is burning a full token count plus
  a complete `LossyContextCompressor.compress()` pass on every iteration past 20 events.
- Per-step compaction already runs at `executing.py:607` on the same session lineage. Making the
  block *work* would add a **fourth** event-replacement site to a system that already has three
  (`executing.py:607`, `memory_archivist.py:82-84`, and this one) and two independent lineages
  racing the same DB row (`task_runner.py:190-194` vs `event_publisher.py:59-79`).
- `save_session` is a **full-row overwrite** (`_session_queries.py:46`) firing on every emitted
  event, so any in-memory event-list shrink is a permanent DB deletion on the next event.
- Deleting ~70 lines buys headroom under the 1000-line ceiling (measured **997**).
- Its filter was wrong anyway: `hasattr(ev,'role') and hasattr(ev,'message')` matches only
  `MessageEvent`, so `ToolEvent` — the actual token bloat — was never even counted.

Keep `self._compactor` at `plan_act_flow.py:182`. It is live (§0.1).

### 6.2 Fix the stale `_memory_index` — this one is a real, reachable crash

`Session` is a plain (non-frozen) pydantic model whose `_memory_index: SessionMemory` is a
`PrivateAttr` (`session.py:199`). Pydantic v2 `model_copy()` **carries the PrivateAttr by
identity** — the comment at `session.py:237-240` claiming it resets to the `default_factory` is
wrong (verified: `s.model_copy(update={'events': [...]})._memory_index is s._memory_index` →
`True`). `SessionMemory` stores raw list positions and indexes them unguarded
(`session_memory.py:37-38`, `:84-85`).

Reproduced by execution: a 7-event session built via `add_event` (5 identical `ToolEvent`s +
`PlanEvent` + `WaitForUserEvent`) run through
`MemoryCompactor(preserve_constraints=False).compact_session()` (dedup 7→3) makes **both**
`get_last_plan()` and `has_unresolved_wait_event()` raise `IndexError: list index out of range`.
`get_last_plan()` sits on the resume path (`flow_router.py:155`) and inside `run()`
(`plan_act_flow.py:610`), and `StateGraph.route` catches only `(AttributeError, KeyError)`
(`state_graph.py:74`) — the IndexError propagates.

`MemoryCompactor` collapses **consecutive identical** `ToolEvent`s
(`memory_compactor.py:67-111`), and `executing.py:607` runs after every non-terminal step. A
repeated tool result is all it takes.

**Changes:**
1. Add `Session.replace_events(events)` in `domain/models/session.py` that does the `model_copy`
   **and** resets `_memory_index` to a fresh `SessionMemory`.
2. Route both existing replacement sites through it: `executing.py:607` and
   `memory_archivist.py:82-84`.
3. Reset the FTS5 watermark when an event list shrinks. `sqlite_state_repo.py:262-280` stores
   `_fts5_indexed[session.id] = len(session.events)` and indexes `session.events[last_indexed:]`;
   a shrink makes the slice empty and drops the watermark, so subsequent growth re-indexes
   already-indexed events into duplicate FTS5 rows.

**Tests:** the existing F9 suite cannot catch any of this — all five tests build sessions with
the `Session(id=..., events=[...])` constructor, leaving `_memory_index` empty and the failure
mode structurally invisible. New tests **must** build via `Session().add_event(...)`:

1. Build ≥5 identical `ToolEvent`s plus a `PlanEvent` via `add_event`, compact, then assert
   `get_last_plan()` returns the plan (fails today with IndexError).
2. Assert the turn-boundary block is gone — or simply that a flow run past 20 events emits no
   `"Turn-boundary compression skipped"` debug record.

**Note for the record:** compaction can neither corrupt a checkpoint nor be recovered from one.
`FlowCheckpoint.conversation_summary` is documented as holding compacted context
(`checkpoint.py:45-55`) but both writers hardcode it to `""`
(`_checkpoint_scheduler.py:60`, `collaborators/event_emitter.py:163`), and both resume paths load
the Session from the state repo and route on `get_last_plan()`. Do not claim checkpoint
protection the system does not have.

---

## 7. Phase 4 — cap the prompt snapshot (A1a)

**Only after P0.2/P0.4.** Ranking or capping against a corpus that is 26/32 test litter measures
garbage.

### 7.1 Seam first
`load_snapshot` is a `@classmethod` that constructs its own `FileSystemMemoryAdapter()`
(`persistent_memory.py:210-220`), ignoring `self._memory` entirely — so any test injecting a
`tmp_path` adapter reads the developer's real home directory instead. Change the signature to
`load_snapshot(cls, memory: MemoryPort | None = None)` and update the single production caller
at `_base.py:462-463` (which calls it on the **class**, not an instance) to pass the adapter.

### 7.2 Cap
- **Newest-N entries plus a character budget. Do not rank by salience.** Measured: `AGENT.md`
  has 32 entries but `memory_metadata` has 7 rows, and re-hashing shows all 32 map to 7 hashes
  because 26 are byte-identical. On any install created after commit `5327746` the table is empty
  and every entry ranks zero. Salience ranking degenerates into arbitrary truncation.
- Flag-gated, **default OFF** (`feature_flags.py` file rule), read lazily inside the function.
- When the cap trims, append one visible line — `"N of M memory entries hidden"` — so the
  omission is legible to both the model and the operator. Today the whole file is concatenated
  with no length check and `MAX_TOOL_OUTPUT_CHARS=20000` never touches the system prompt.
- Fence the snapshot as reference data, not instructions. Injection scanning is write-side only
  and matches just 8 chat-template markers (`filesystem_memory.py:26-29`); anything already on
  disk is injected unscanned and unfenced, unlike the file-reading warning at
  `_prompt_builder.py:52-56`.
- Fix the docstring (P0.3) in the same PR — the prefix-cache justification does not exist.

**Test:** 50 entries in a `tmp_path` `AGENT.md`, assert the snapshot is under the budget and
contains the hidden-count line.

---

## 8. Phase 5 — retrieval (A1b) — deferred, and illegal as originally sketched

Gate this on **D-E**: only worth building if real memory outgrows the Phase 4 cap.

**The original sketch is illegal.** `weebot.tools.persistent_memory →
weebot.infrastructure.adapters.numpy_vector_store` breaks the `tools-no-infra` contract
(`.importlinter:31-36`); the two existing exemptions cover `filesystem_memory` and
`sqlite_state_repo` only, and the repo-wide budget has two slots left against a hard CI assert.

**Compliant shape — six files, zero new exemptions:**
1. NEW `application/ports/memory_index_port.py` — ABC with `async index(texts)` /
   `async search(query, top_k)`.
2. NEW `infrastructure/adapters/<name>_memory_index.py` implementing it. This is the **only**
   place `LocalEmbeddings` and `NumpyVectorStore` may be imported. It must literally contain
   `from weebot.application.ports.memory_index_port import MemoryIndexPort` or
   `test_orphan_ports_flagged` fails on the port itself.
3. `application/di/_factories.py` — `_create_memory_index()` with a **function-local** infra
   import (pattern: `_factories.py:98-103`).
4. `application/di/__init__.py` — register inside `configure_defaults`.
5. `tools/persistent_memory.py` — accept the port via ctor with a `None` default; add
   `retrieve` to **both** the action enum (`:59`) **and** the execute if-chain (`:109-123`) —
   `ActionCanonicalizer` does not validate enums, so a schema-only edit yields `Unknown action`
   and an execute-only edit is invisible to the model.
6. `config/feature_flags.py` — default OFF.

Do **not** put the index in `application/services/`.

**Hard constraints the adapter must satisfy:**
- Gate on `LocalEmbeddings.is_available()` — the cheap `find_spec` probe (`embeddings.py:309-320`).
  `get_model_info()` and `get_embedding_dimension()` both force a full model load.
- Wrap every embed call in `asyncio.to_thread`. `embed_query`/`embed_documents`/`embed_batch`
  are `async def` with **zero awaits** calling synchronous torch directly
  (`embeddings.py:184-294`); measured, an asyncio ticker scheduled every 5 ms fired **0 times**
  during 38.9 s of `embed_documents`. `sqlite_summary_repo.py:46,58` (dead code) already models
  the correct pattern.
- Cold start is measured in **minutes** (torch 41 s + transformers 218 s + sentence-transformers
  109 s + construct 9 s ≈ 376 s offline; 758 s for the first `embed_query` with network on).
  Never index on a write path. Guard the lazy build against a thundering herd —
  `semantic_skill_retriever.py:85-88` has an unguarded `if not self._index_built: await
  self.refresh()`, and 5 concurrent cold calls produced 5 full-corpus re-embeds.
- Use a **dedicated** `NumpyVectorStore` instance. `upsert` is a wholesale **replace**
  (`numpy_vector_store.py:41-60`) with no persistence — sharing one with skill retrieval wipes
  the other index.
- Fall back to substring/BM25 when embeddings are unavailable, so a clean `pip install -r
  requirements.txt` still works. **Never let `retrieve` be the only path to an entry the
  Phase 4 cap hid.**
- Import `get_local_embeddings` **lazily inside the function** so tests can
  `monkeypatch.setattr('weebot...get_local_embeddings', fake)`; the singleton ignores kwargs
  after the first call (`embeddings.py:344-356`).

**Tests must never construct a real `LocalEmbeddings`** — inject a fake returning fixed 384-dim
vectors (pattern: `tests/unit/test_semantic_skill_retriever.py:70-103`). `pyproject.toml:87` sets
`timeout=60` globally, so a real-model test is killed by pytest-timeout rather than failing
cleanly.

---

## 9. Phase 6 — preservation check (A2) — narrowed

**Do not mirror `MemoryCompactor._inject_constraints`.** That mechanism regex-scans raw
untrusted tool output for bare `token`/`password`/`secret`/`security`, captures the rest of the
line, and injects it verbatim as an assistant message under a
`[CRITICAL CONSTRAINTS - DO NOT VIOLATE]` header — bypassing the credential sanitization and
truth binding that live only in `event_publisher.py:83-116` — and then persists it. Reproduced:
a tool result containing `Authorization token: sk-live-ABCDEF123456` produced an injected event
containing that key. It also reads `str(event)` (pydantic repr), where real newlines become the
two-character escape `\n`, so its `[^\n.]+` patterns run past line boundaries and merge unrelated
lines plus repr fragments. **This is a bug to file, not a pattern to copy.**

**Prerequisite (a real bug, worth fixing on its own):** `_context_compressor.py:106` treats
`ConversationCompressor.compress()`'s return value as a summary string, but it returns
`List[Dict]` (`conversation_compressor.py:63-65`). Line `:111` stuffs that list into a message's
`content`, and `_multimodal.py:172-177` then maps each dict (no `"type"` key) to the literal text
`[unsupported content block: None]`. It compounds: with `maxlen=15` the middle slice is always 9
messages, below `ConversationCompressor`'s 10-message minimum, so it returns the middle unchanged
with **no LLM call at all**. Net effect when it fires: 9 real turns replaced by nine copies of an
error placeholder.

**Then reassess whether A2 is worth building.** The compression trigger is effectively
unreachable in text-only sessions: `deque(maxlen=15)` × `MAX_TOOL_OUTPUT_CHARS=20000` caps the
`char/4` estimate at ~75 000 against a `128_000 × 0.75 = 96 000` threshold. Only a base64
screenshot crosses it. Attaching a preservation check to a path that never runs verifies nothing.

If built anyway:
- Executor side only. The flow-level half would land in `plan_act_flow.py`, which has **3 lines**
  of headroom.
- Logic in a **new stdlib-only module** (`domain/services/` is legal — precedent:
  `constraint_extractor.py`, 131 lines, pure `re`, zero I/O), called in one line.
- Build the restatement from `step.description` **only** — agent-authored and trusted — never
  from retained tool output.
- Add `set_step_context(description)` to `ContextCompressor` (mirroring
  `TrajectoryMonitor.set_step_context` at `_base.py:528`; do **not** model on
  `ToolExecutor.set_step_context`, which exists and is never called).
- **Replace** a message in place rather than appending — the deque is bounded, so an append
  evicts the head, which is the goal/plan context message the check is trying to protect.
- Keep every symbol inside `_context_compressor.py`: `test_architecture_fitness.py:1029-1042`
  fails on any `def _maybe_compress` or `self._maybe_compress` appearing in `_base.py`.
- Any test must pass a small `context_window` explicitly (e.g.
  `ExecutorAgent(llm=mock, tools=ToolCollection(), context_window=100)` — the ctor param at
  `_base.py:156` *is* forwarded to the compressor at `:215`) and assert compression actually ran,
  or the early return at `:88` satisfies it trivially.

---

## 10. Phase 7 — `filter_context` (A3) — via `ToolResult.data`

**Do not hand the deque to a tool.** Tools are constructed **before** the `ExecutorAgent` exists
(`interfaces/factories.py:241-298` → `PlanActFlowConfig` → `plan_act_flow.py:252-276`), the
registry's injection allow-list is closed (`tool_registry.py:546-558`), and `BaseTool` is a
Pydantic model that rejects plain attribute assignment.

The sanctioned channel already exists: return `ToolResult.data={"context_filter": {...}}` and
apply it in the executor loop where `result.data` is **already** read
(`_base.py:837-843`, the `awaiting_human` precedent from `tools/control.py:52-58`). Zero new
imports, zero layering edges, and mutation happens synchronously in the loop after
`execute_tool_batch` returns rather than concurrently inside `asyncio.gather`.

Hard invariants:
- Delete assistant+tool **groups atomically**, or rewrite a tool message's content in place.
  Every `{'role':'tool','tool_call_id': X}` needs its preceding assistant message whose
  `tool_calls` contains X; only `moonshot_adapter.py:79-115` repairs orphans — the default
  OpenAI/OpenRouter path 400s.
- Never rebind `self._conversation_buffer`. `ContextCompressor` (`_base.py:213`) and
  `ToolExecutor` (`:236`) captured the same deque **object**; rebinding orphans both. Mutate in
  place only.
- Preserve the `⟦UNTRUSTED_DATA…⟧` / `⟦END_UNTRUSTED_DATA⟧` delimiters byte-for-byte
  (`core/trust_boundary.py:63-78`), or replace the whole message with a fresh trusted placeholder.
- A tool cannot filter its own result or its batch-mates' — results are appended only after the
  whole batch returns (`_base.py:678` → `:856-863`).

**The minimal test is an invariant test:** after any filter operation, assert every tool message
in the buffer has a matching preceding assistant `tool_call_id`, and that the goal/plan head
message (`_base.py:493-496`) survives.

---

## 11. Phase 8 — memory-quality job (A4) — report-only first

Only after Phases 0-4, and only if memory has grown enough to need pruning.

- **Prerequisite: make writes atomic.** `_add` is a lock-free read-modify-write
  (`persistent_memory.py:168-170`) and `write_entries` uses `Path.write_text` — truncate in
  place, no temp+rename (`filesystem_memory.py:82-86`). Each DI fallback yields a **different**
  adapter instance, so there is no shared lock across writers. An unattended job that edits the
  user's only durable memory through that path loses the file on one crash mid-write. Temp file
  + rename, keep a `.bak`.
- Ship v1 as **report-only**. No deletions until a human has read a run.
- Bound it explicitly (top-N per run, mirroring `MAX_SKILL_PROMOTIONS_PER_RUN=20` at
  `config/learning.py:20-39`) and assert the bound with a counting fake LLM.
- Pass an explicit cheap `model=` — `MODEL_BUDGET` per `SkillCurator` (`skill_curator.py:58-69`).
  Note `MODEL_BUDGET` ('x-ai/grok-build-0.1') is priced at $1.00/$2.00 per 1M, more expensive
  than `deepseek-v4-flash` ($0.098/$0.197) or `qwen/qwen3.7-flash` ($0.03/$0.13) — pick
  deliberately.
- Do **not** put "cost stays under X" in the acceptance criteria: all four
  `_record_decision` call sites leave `cost_estimate` at 0.0, and `ExecutorAgent` builds its own
  `ModelCascadeTracker` rather than the DI singleton, so nothing measures it.
- New `job_id` — do not resurrect the disabled `skill_promotion_check`. Register the callable
  before `load_from_config` and wrap it in `_with_job_metrics`.
- **Verify it fires on a second process boot before claiming it works** (see §12).

---

## 12. Found but explicitly out of scope

Filed here so they are not lost, and so nobody mistakes them for regressions introduced by this
work. None of them is required for Phases 0-4.

1. **Default jobs stop firing after the first process lifetime.** `jobs.db` persists but
   APScheduler's `AsyncIOScheduler` uses an in-memory jobstore. On restart `_create_if_absent`
   sees the existing row and returns before `create_job()`, which is the only path calling
   `add_job()`; `load_from_config` skips existing rows the same way. Second and later boots have
   **zero** recurring jobs (`scheduler.py:224-231, 533-534, 694-700`). Flipping
   `enabled: false → true` in `jobs.yaml` also has no effect on an existing install.
2. **`SemanticTaskRouter` is 100% non-functional** if anyone sets `WEEBOT_SEMANTIC_TASK_ROUTER=1`:
   `_build_centroids` calls `emb.embed_query(ex)` without `await` in a sync `__init__` (centroids
   always empty), and it constructs a domain `TaskRoute` with a `TaskCategory` imported from a
   different, incompatible enum — every return path raises `ValidationError`
   (`semantic_task_router.py:134, 20, 164`).
3. **`MemoryArchivist` is dead** — `TaskRunner` accepts it but the DI factory never passes it
   (`_factories.py:138-147`); no construction site exists anywhere.
4. **`SummarizeHandler` is broken** — it constructs `ExecutorAgent(llm=...)` without the required
   `tools` argument, and calls `executor.summarize()`, which does not exist
   (`summarize_handler.py:43`, `_base.py:350-358`).
5. **`SQLiteSummaryRepository`** (`infrastructure/persistence/sqlite_summary_repo.py`) is a
   complete, correct, **persisted** save + top-k cosine store with proper `asyncio.to_thread`
   usage, and is 100% dead code. Read it before writing any persisted vector store — it is 85
   lines and already half the job.
6. **`WeebotSettings` has no `env_prefix`**, so documented `WEEBOT_*` names for settings fields
   are frequently dead (verified: `WEEBOT_HOST=9.9.9.9` is ignored in favour of `WEB_HOST`).
   Only three fields have an explicit `alias=`.
7. **`ExecutorAgent._context_window` is a dead field**, and `context_window` is hardcoded to
   128 000 rather than derived from the model registry (which does carry real per-model windows).

---

## 13. Verification playbook

Per phase, in order. Substitute the fast-path prefix from §1.3 for iteration.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/unit/test_salience.py tests/unit/test_memory_lifecycle.py tests/unit/test_f9_synchronous_consolidation.py tests/unit/test_lossy_context_compressor.py tests/unit/test_user_model_consolidator.py tests/unit/test_regression_memory_traversal.py tests/unit/test_med_priority.py -q -p pytest_asyncio.plugin -p pytest_timeout -p pytest_mock
```

Baseline measured today: **40 passed** for the first four files; **22 passed** for the
consolidator/traversal/FTS/CQRS group. No pre-existing failures in any of them.

Phase 1 additionally requires (both are blocking CI jobs that construct
`InMemoryStateRepository`):

```bash
python -m pytest tests/unit/test_cqrs_persistence.py tests/unit/test_planning.py tests/integration/test_in_memory_state_repo.py tests/integration/test_cqrs_handlers.py -q
```

Phase 3 additionally requires:

```bash
python -m pytest tests/e2e/test_flow_e2e.py tests/e2e/test_persistence.py -q
```

Every phase must end with:

```bash
lint-imports --config .importlinter --verbose
```
```bash
ruff check weebot/ cli/ --select F821,E9
```
```bash
python -m pytest tests/unit/test_architecture_fitness.py -q
```

`test_architecture_fitness.py` takes ~76 s (it shells out to `lint-imports`) — not a cheap gate
to loop on. Expect the two §1.2 failures until P0.1 lands (one of them, the Windows cp1253 one,
permanently on this machine).

---

## 14. Recommended order and shipping units

| PR | Contents | Risk | Reversible |
|---|---|---|---|
| 1 | P0.1 + P0.2 + P0.3 | none — test/docs only | trivially |
| 2 | P0.4 (needs **D-C**) | user data — back up first | from backup |
| 3 | Phase 1 (F1) — needs **D-A**, **D-B** | medium: activates a dormant write path | yes, self-contained |
| 4 | Phase 2 (F2) | low: tool-local, fail-closed | yes |
| 5 | Phase 3 (F3) — delete block + `replace_events` | medium: touches the live flow path | yes |
| 6 | Phase 4 (A1a) — flag default OFF | low behind the flag | flag off |
| — | Phases 5-8 | gated on **D-E**; reassess after PR 6 | — |

PRs 1-2 are pure hygiene with no runtime effect. PR 3 is where behavior changes. PR 5 is the
only one that touches a hot path, and it removes code rather than adding it.
