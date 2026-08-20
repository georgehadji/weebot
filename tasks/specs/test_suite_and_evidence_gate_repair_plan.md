# Test-Suite & Evidence-Gate Repair Plan

**Created:** 2026-08-20
**Status:** Draft — not yet implemented
**Trigger:** Verification pass after the whole-tree `black`/`ruff` reformat surfaced 9 failing
tests. None were caused by the reformat. Investigating them uncovered three defects that are
materially worse than the failures themselves.

---

## Executive summary

The nine failing tests were the symptom. The investigation found:

| # | Finding | Severity | Why it matters |
|---|---------|----------|----------------|
| **A** | Written-files evidence gate is silently inert | **Critical** | A verification mechanism that **fails open**. Reports "no violations" while checking nothing. |
| **B** | A bare `pytest` makes live, billed LLM calls | **Critical** | ~23 unbounded agent-loop tests run for real. `make test` is unsafe. |
| **C** | `test_artifact_gates.py` tests a layer that no longer holds the logic | High | 7 broken tests; 3 real behaviours have **zero** coverage at either layer. |
| **D** | Unit tests load `torch`/`sentence_transformers` and can fetch ~90 MB | Medium | Blows the 60 s timeout. One assertion is provably incapable of failing. |
| **E** | LaTeX font dependency is declared nowhere and validated nowhere | Medium | Missing font ⇒ XeLaTeX substitutes `nullfont` ⇒ silently broken PDF. |
| **F** | Marker taxonomy defined but largely unapplied | Low | Two markers mean the same thing; CI filters on only one. Root cause of B's CI hole. |

**A, B, and C share one failure mode**: a mechanism was wired up, looks present, reports success —
and does nothing. This is the same "registered ≠ wired" class the side-constraint work (ADR-012)
was built to catch. That work fixed the executor seam; these are three more instances of it.

**Non-goals.** Not fixing the 910 residual `ruff` lint findings; not raising the 60 s timeout
(it would hide D, not fix it); not introducing an `EmbeddingsPort` (see §D for why); not
decomposing `_catalog.py`. Not touching the reformat itself — it is already verified and committed.

---

## Architectural constraints

All work must respect the contracts in `.importlinter` (7 contracts, currently all KEPT):

- `root_package = weebot` — **`tests/` is outside the analyzed graph.** Fixtures and fakes placed
  under `tests/` cannot violate any contract. This is why §C and §D need no production changes.
- `infra-no-app-services` (`.importlinter:87-96`) forbids `weebot.infrastructure` →
  `weebot.application.{agents,cqrs,di,flows,services}`. It does **not** forbid
  `weebot.application.ports` — infrastructure importing a port is legal.
- `weebot/application/di/` is the composition root. It is the one place permitted to know about
  both `weebot.config` and `weebot.infrastructure` concretes.
- `weebot/qmd_integration/` is classified **infrastructure** (`weebot/core/layer_classifier.py:29`).

Run `lint-imports --config .importlinter` after every phase. 7/7 must stay KEPT.

---

## A — Written-files evidence gate is silently inert  🔴 Critical

### The defect

`StepEvidenceAuditor` Gate A exists to catch the failure mode "the agent claims it wrote a file
but the file is not on disk." It currently cannot catch it in the default configuration.

The chain:

1. `weebot/application/di/_factories.py:298` — `return LocalFileStorageAdapter(root_dir=".")`.
   `.` is resolved at construction time (`file_storage_adapter.py:27`) to the **process CWD**.
2. `weebot/config/settings.py:9` — `WORKSPACE_ROOT = Path(os.getenv("WEEBOT_WORKSPACE", os.getcwd()))`.
   The repo `.env` **sets `WEEBOT_WORKSPACE`**, so in normal operation `WORKSPACE_ROOT ≠ CWD`.
   `WORKSPACE_ROOT` is also the sandbox root for `security_validators.py`, so every file the agent
   writes lands under it.
3. `weebot/infrastructure/adapters/file_storage_adapter.py:29-34` — `_resolve()` raises
   `ValueError("Path traversal blocked")` for any path outside the adapter root.
4. `weebot/application/services/step_evidence_auditor.py:93-99` — catches `(OSError, ValueError)`,
   logs at **`debug`**, and `continue`s.

Net effect: every written path is outside the audit root, every check raises, every raise is
swallowed, and the gate returns `[]` — indistinguishable from "all files verified present."

This is worse than having no gate. `VerifyingState._gate_artifact_verification`
(`verifying.py:519-548`) and the per-step call site in `executing.py:639-645` both consume this
result as evidence of correctness.

### Fix

**A1. Make the audit root the workspace root.** In `_factories.py:298`, bind
`LocalFileStorageAdapter(root_dir=WORKSPACE_ROOT)`. The composition root is the correct place to
resolve this — it is the only layer that may know both the config constant and the concrete adapter.

**A2. Audit every `FileStoragePort` consumer before changing the binding.**
Per the recorded *verify-scope* lesson — checking a subset of the blast radius once produced false
confidence and licensed a harmful fix — this step is mandatory, not optional:

```bash
grep -rn "FileStoragePort\|LocalFileStorageAdapter" weebot/ tests/
```

For each consumer, confirm whether it expects CWD-relative or workspace-relative paths. Any
consumer that passes repo-relative paths (e.g. reading `weebot/templates/...`) will break if the
workspace root differs from the repo root. If such a consumer exists, bind **two** named adapters
in DI rather than changing the shared one, and give the audit path its own.

**A3. Stop swallowing the signal.** In `step_evidence_auditor.py:93-99`, split the two cases:

- `ValueError` (out-of-root) — this is a **configuration** fault, not a data fault. Log at
  `warning` with the path and the adapter root, and count it. A gate that cannot inspect its
  subject must not report a clean bill of health.
- `OSError` (genuinely malformed path) — keep the current skip-without-blocking behaviour; a
  syntactically invalid path is the agent's problem to have already failed on, not the gate's.

**A4. Regression test that fails on the current code.** Construct an auditor whose storage root
differs from the written path's directory and assert the audit **does not** silently return `[]`.
Write this test first and watch it fail before applying A1.

### Verification

- New test red before A1/A3, green after.
- `pytest tests/unit/test_verifier_readonly_tripwire.py` still green (the E7b read-only tripwire).
- Manual: run a flow with `WEEBOT_WORKSPACE` set away from CWD, have a step claim a write that
  does not happen, confirm the gate now flags it.

---

## B — A bare `pytest` makes live, billed LLM calls  🔴 Critical

### The defect

`make test` (`Makefile:25-26`) is `pytest tests/ -v --tb=short`. In this working tree that
invocation makes real, billed OpenRouter/Kimi calls, including four **unbounded agent-loop** tests
(`max_steps=25, max_iterations=8`).

The guards that look like they prevent this do not, for four independent reasons:

1. **`WeebotSettings` reads `.env` off disk, ranked above `os.environ`.**
   `weebot/config/settings.py:44-49` sets `env_file` to the repo-root `.env`; `:64-69` orders
   `dotenv_settings` **above** `env_settings`. The autouse `clean_env` fixture
   (`tests/conftest.py:64-81`) only calls `monkeypatch.delenv` — it mutates `os.environ` and
   therefore cannot touch a file. Key resolution funnels through `_resolve_direct_key()`
   (`weebot/infrastructure/adapters/llm/adapter_factory.py:327-345`), which tries `WeebotSettings()`
   **first**.
   Only `tests/unit/` is protected — `tests/unit/conftest.py:41-55` nulls
   `WeebotSettings.model_config["env_file"]`. **`integration/`, `e2e/`, and `stress/` have no
   equivalent.**
2. **`tests/integration/conftest.py:9-27`** parses `.env` and writes every key into `os.environ` in
   `pytest_configure` — i.e. at **collection** time, before any fixture runs.
3. **Module-level `skipif`s are evaluated at import**, after (2) has already populated the
   environment. The guard sees a key and declines to skip.
4. **Two test modules parse `.env` themselves**, deliberately. `tests/e2e/test_portfolio_website.py:60-65`
   says so in its own docstring: it reads the file directly *"so the autouse clean_env fixture …
   doesn't hide the keys."* Its four tests (`:194`, `:261`, `:489`, `:619`) carry **no `skipif` at
   all**.

Locally the keys resolve and these run for real. In CI there is no `.env` and no configured secret
(`.github/workflows/architecture.yml` references no `secrets`; the only values are the literal
`ci-test-key` dummies at `:209-210`), so they silently skip. **They have never been validated in
CI.** The exclusion works by accident.

### Fix

**B1. Make "off" the default, at the settings seam.** Promote the `env_file`-nulling fixture from
`tests/unit/conftest.py:41-55` to `tests/conftest.py` as autouse for the whole suite. Live tests
opt back in explicitly (B2) rather than every other test opting out implicitly. This closes
bypasses (1) and, combined with B2, (2).

**B2. One marker, one env gate, applied uniformly.** Adopt the pattern that already works —
`tests/unit/atomicmail/test_external_network.py:21-22`:

```python
_LIVE = os.environ.get("WEEBOT_TEST_LIVE", "").strip().lower() in ("1", "true", "yes")
_SKIP = pytest.mark.skipif(not _LIVE, reason="Set WEEBOT_TEST_LIVE=1 to run live-network tests")
```

Apply `@pytest.mark.external` **and** the env gate to every test in:
`tests/integration/test_real_api.py`, `test_real_api_openrouter.py`, `test_website_generation.py`,
`tests/e2e/test_portfolio_website.py`, and `tests/e2e/test_flow_e2e.py::TestFlowRunE2E`.

A marker alone is insufficient — a bare `pytest tests/` still collects and runs it. The env gate is
what makes the default safe; the marker is what makes it *filterable*.

**B3. Collapse `real_api` into `external`.** Two markers meaning the same thing is precisely what
produced the CI hole: `architecture.yml:121` runs `pytest tests/e2e/ -m "not external"`, but
`test_portfolio_website.py` is marked `real_api`, so the filter misses it. It is collected and
imported in CI today and avoids running only because `.env` is absent. Add a key to CI and that
job starts making billed calls under a 60 s timeout.
Remove the `real_api` registration from `tests/conftest.py:52-57` after migrating its 24 uses.

**B4. Default-deny in `addopts`.** In `pyproject.toml:78`:

```toml
addopts = "--tb=short --strict-markers -ra -m 'not external'"
```

An explicit `-m` on the command line overrides it, so live runs stay one flag away. This makes the
safe path the default path for `make test` and for any contributor who types `pytest`.

**B5. Fix `Makefile:25`** to state the intent explicitly rather than relying on `addopts`, and add
a separate `make test-live` target that sets `WEEBOT_TEST_LIVE=1`.

### Verification

- With `.env` present, `pytest tests/` collects **zero** `external` tests. Confirm with
  `pytest tests/ --collect-only -q -m external` (should list them) vs plain `--collect-only`.
- Network assertion: run the full suite with network disabled and confirm no failures attributable
  to connectivity.
- `WEEBOT_TEST_LIVE=1 pytest -m external` still runs them, proving live mode is intact.

---

## C — `test_artifact_gates.py` tests the wrong layer  🟠 High

### The defect

Commit `8cc7611` (2026-08-10, *"gate step completion on environment evidence
(LongHorizon-Harness E1-E7a)"*) rewrote `VerifyingState._gate_artifact_verification` from inline
checks into pure delegation to `StepEvidenceAuditor`. It did **not** touch
`tests/unit/test_artifact_gates.py`, whose only commit is `577e7c8` (2026-06-13). The file has been
broken for the ~10 days since.

Two distinct problems:

**C-i. The tests error.** `_make_flow()` (`test_artifact_gates.py:13-22`) builds a bare
`MagicMock()`. `getattr(flow, "_step_audit_service", None)` auto-vivifies a child mock instead of
returning `None`, so the `is None` early return at `verifying.py:535` never fires, and
`await`ing a plain `MagicMock` raises `TypeError`. The helper also still sets `flow._plan.steps`
and `flow._executor`, neither of which the gate has read since the refactor.

**C-ii. The assertions target strings that no longer exist.** Neither `written_files_missing` nor
`test_run_failed` appears anywhere in `weebot/`. Current equivalents:

| Old assertion | Current `dimension:description` | Source |
|---|---|---|
| `written_files_missing:<paths>` | `completeness:written file missing on disk: {p}` | `step_evidence_auditor.py:101-109` |
| `test_run_failed` | `accuracy:test run reported failure` | `step_evidence_auditor.py:130-138` |

Gate B semantics also changed **deliberately** (`step_evidence_auditor.py:121-128`): the old version
skipped whenever `"passed"` appeared anywhere in output, making it inert for `"3 failed, 1 passed"`.
The new one skips only on `"0 failed"`. **A rewrite must not restore the old assertion shape.**

**C-iii. And the coverage does not exist at the new layer either.** `StepEvidenceAuditor` has no
dedicated behavioural test file. `tests/unit/test_verifier_readonly_tripwire.py` is a read-only
tripwire; its one behavioural test (`:184-205`) trips all three gates at once and asserts only that
`report.violations` is non-empty.

| Behaviour | Covered today |
|---|---|
| missing written file flagged | only inside the all-gates-at-once assertion |
| failed pytest flagged | same, not isolated |
| passing tests **not** flagged | **no** |
| non-test bash **not** flagged | **no** |
| invalid path does not raise | **no** |

So the file is simultaneously obsolete *and* the only thing guarding three real behaviours.
Deleting it loses coverage; leaving it leaves seven errors.

### Fix

Rewrite `tests/unit/test_artifact_gates.py` in place — same path, no new files.

**C1. Move the five behaviour cases down one layer.** Test `StepEvidenceAuditor.audit_step(...)`
directly against a stub `FileStoragePort` (or `LocalFileStorageAdapter(root_dir=tmp_path)`),
asserting on `report.violations[*].dimension` and `.description`.

> **Depends on §A.** With the current `root_dir="."` binding, the old fixture path
> `/nonexistent/__missing_file__.py` (`test_artifact_gates.py:48`) is **silently skipped, not
> flagged**. Use paths inside the storage root, or a stub port. Sequence §A before §C so the
> rewrite is written against correct behaviour.

**C2. Add one delegation test for the gate itself.** Assert two things and nothing more:
`_step_audit_service = None` ⇒ `[]`, and a canned `AuditReport` from an `AsyncMock` ⇒ the
`"completeness:…"` formatting at `verifying.py:547`.

**C3. Use the existing flow-mock convention.** There is no shared flow fixture; the convention is a
per-file private helper. Copy `_flow_with_completed_step` from
`tests/unit/test_verifying_fail_closed.py:37-48`, which already solves this exact bug — line `:42`
carries a comment about this precise failure class:

```python
flow._hooks = None  # MagicMock's auto-attr would be truthy + non-awaitable
```

Do **not** add a shared conftest fixture yet — two call sites is not three.

### Verification

`pytest tests/unit/test_artifact_gates.py tests/unit/test_verifier_readonly_tripwire.py` green,
and each of the five behaviours has a test that fails when its gate is disabled.

---

## D — Unit tests load `torch`; one assertion cannot fail  🟡 Medium

### The defect

`tests/unit/test_knowledge_graph_fts.py:418-435`,
`test_dense_leg_does_not_crash_when_unavailable`, **never simulates unavailability.** It has no
`monkeypatch`, no injected null port, no flag — it simply assumes the machine lacks the library.
Contrast its sibling `test_search_falls_back_to_like` (`:180-214`), which actively drops the FTS
table to force the fallback.

When `sentence_transformers` *is* installed, the test takes the opposite branch from the one its
name describes:

1. `sqlite_knowledge_graph.py:453` — `dense_weight > 0` ⇒ `_get_query_embedding(query)`
2. `:425` — `if not emb.is_available(): return None`
3. `embeddings.py:303-314` — `is_available()` is backed by `_is_installed` (`:94-109`), which is
   `importlib.util.find_spec` — a **presence** probe. Installed ⇒ `True`.
4. `:152-160` — real `from sentence_transformers import SentenceTransformer` (the >60 s cold import
   cascade through `sklearn` → `pandas`), then `SentenceTransformer("all-MiniLM-L6-v2")` at `:158`,
   which **downloads ~90 MB from huggingface.co** when uncached. Cached locally; **not** cached on
   a CI runner.

**Both assertions are vacuous.** `ScoredNode.sparse_score` is declared
`Field(default=0.0, ge=0.0, le=1.0)` (`weebot/domain/models/knowledge_graph.py:94`) — Pydantic
enforces `ge=0.0` at construction, so `assert all(r.sparse_score >= 0 ...)` is *structurally
incapable of failing*. And `_get_query_embedding` wraps everything in `except Exception: return None`
(`:430-431`), so the graceful-degradation guarantee holds unconditionally in production — the test
would pass either way. That is why this shipped unnoticed.

**This is not a one-test problem.** `get_local_embeddings()` has six call sites with the identical
lazy-import + `is_available()` + heavy-load shape:

- `weebot/infrastructure/persistence/sqlite_knowledge_graph.py:422` and `:608`
- `weebot/infrastructure/adapters/mcp_tool_retrieval_adapter.py:39`, `:51`
- `weebot/application/services/semantic_task_router.py:122`
- `weebot/application/services/semantic_skill_retriever.py:179`

Monkeypatching inside one test leaves the other five paths just as slow.

### Fix

**D1. Neutralise the shared singleton once.** `embeddings.py:338-350` (`_embeddings`,
`_embeddings_lock`, `get_local_embeddings()`) is the single chokepoint all six callers route
through, and the module contains **no** `os.getenv` — there is currently no way to turn it off.
Add one autouse fixture to `tests/conftest.py` that pre-seeds that singleton with an instance whose
availability flags are forced `False`.

This matches the existing convention in that exact file — `reset_connection_pool`
(`tests/conftest.py:84-116`) and `reset_settings_singletons` (`:119-138`) already reach into
`sys.modules` to reset module-level singletons for the same reason. No production change; `tests/`
is outside the import graph, so no contract is touched.

**D2. Make the test earn its name.** Replace the Pydantic-guaranteed assertion with the actual
observable consequence of an unavailable dense leg:

```python
assert all(r.dense_score == 0.0 for r in results)
```

**D3. Keep a real-model path, opt-in.** A second test exercising the genuine embedding path,
marked `external` per §B, so the capability stays covered without taxing every run.

**Rejected alternatives.**
*Introducing an `EmbeddingsPort`* — a new port with exactly one implementation, for a problem a
six-line fixture solves; this is the speculative generality YAGNI exists to prevent. It stays
rejected only until a second implementation is genuinely needed.
*Raising `timeout = 60`* — converts a 60 s hang into a longer one and hides the fact that a **unit**
test is loading `torch`.

### Verification

- `pytest tests/unit/test_knowledge_graph_fts.py` completes well inside the 60 s timeout.
- Assert the fixture actually bites: with it active, `get_local_embeddings().is_available()` is
  `False` in a scratch test.
- D2's assertion fails if the dense leg is wired up — verify by temporarily disabling the fixture.

---

## E — LaTeX font dependency is declared and validated nowhere  🟡 Medium

### The defect

`weebot/infrastructure/document/templates/greek_scientific_preamble.tex:60-64` hard-codes three
system fonts:

```latex
\setmainfont{GFS Didot}
\setsansfont{GFS Neohellenic}
\setmonofont{DejaVu Sans Mono}[Scale=0.85]
```

`LatexCompilerService.toolchain_available()` (`latex_compiler.py:36-38`) checks only that `latexmk`
and `xelatex` are on `PATH`. Font availability is checked nowhere — not at compile time, not in
`doctor`, not in the test guard.

Consequence: on a machine with the toolchain but without the fonts, XeLaTeX substitutes `nullfont`
and emits `Package polyglossia Error: The current main sans serif font, nullfont, does…`. The
"locked, tested preamble" is only locked and tested on machines that happen to have the fonts. The
preflight check (`fonts_not_embedded == 0`) catches it only *after* a full compile.

This is a product gap, not merely a test gap: a book generated on an under-provisioned machine is
silently wrong.

**Environment status (resolved 2026-08-20):** `GFS Neohellenic` (4 OTF styles), `GFS Neohellenic
Math`, and `DejaVu Sans Mono` (4 TTF styles) were installed per-user to
`%LOCALAPPDATA%\Microsoft\Windows\Fonts` with HKCU registration, matching how `GFS Didot` was
already installed here; `fc-cache -f` was run. All three families now resolve. **The validation gap
below remains open regardless.**

### Fix

**E1. Derive the required-font list from the preamble, not a duplicate constant.** Parse
`\setmainfont`/`\setsansfont`/`\setmonofont`/`\newfontfamily` out of
`locked_preamble_path()`. The locked template stays the single source of truth and the check
auto-follows any edit to it.

**E2. Add `LatexCompilerService.missing_fonts() -> list[str]`.** Infrastructure layer — it shells
out to `fc-list`, which is an OS/environment concern and belongs next to the existing
`toolchain_available()` static method.

Detection notes: `fc-list` ships with both MiKTeX and TeX Live, so if the toolchain is present it
almost certainly is too. Match on family name, and **fail open** — if `fc-list` itself is missing,
return `[]` rather than a false "missing", so a valid compile is never blocked by an undetectable
font database.

**E3. Fail fast, with an actionable message.** Have `compile()` (or `BookGenerationFlow.generate`)
check `missing_fonts()` up front and return a `CompileResult` naming the missing families, rather
than producing a `nullfont` PDF.

**E4. Extend the test guard.** The two tests at `test_latex_document.py:159-161` and `:178-180`
currently `skipif(not toolchain_available())`. Add the font condition so the skip reason
distinguishes *"toolchain missing"* from *"fonts missing"* — a silent skip is acceptable; a
confusing failure is not.

**E5. Add a `doctor` check.** Follow the existing pattern at
`weebot/interfaces/cli/support.py:306-326` — `DoctorCheck(name="latex_fonts", status="ok"|"warn",
details=…)`. Status `warn`, not `error`: the LaTeX pipeline is optional.

### Verification

- `missing_fonts()` returns `[]` on this machine; returns the family name when pointed at a
  preamble requesting a fictitious font.
- `python -m cli.main doctor` reports `latex_fonts ok`.
- Both LaTeX tests pass. **Note:** the first compile after a font change is slow — MiKTeX fetches
  packages on demand (`AutoInstall=1`), and the compile can exceed the per-test
  `@pytest.mark.timeout(360)` while `LatexCompilerService`'s own 300 s budget expires and blocks
  draining a child that has not exited. Warm the MiKTeX package cache with one manual `latexmk`
  run before judging these tests.

---

## F — Marker taxonomy defined but unapplied  🟢 Low

`pyproject.toml:80-86` registers five markers; `tests/conftest.py:52-57` adds `real_api`;
`tests/stress/conftest.py:3-4` adds `stress`. Actual usage:

| Marker | Uses |
|---|---|
| `real_api` | 24 (the 4 network files) |
| `external` | 7 |
| `slow` | 4 |
| `integration`, `unit`, `e2e`, `stress` | **0** |

`--strict-markers` is already on (`pyproject.toml:78`), so unregistered markers error — good.
The problem is two markers with one meaning (see §B3) and four registered-but-unused.

**Fix.** Collapse `real_api` → `external` as part of §B3. Then either apply
`integration`/`unit`/`e2e` consistently or drop the registrations — a marker nobody applies is a
filter that silently selects nothing, which is how §B's CI hole stayed invisible.

---

## Sequencing

Phases are ordered by dependency, then severity.

| Phase | Work | Depends on | Rationale |
|---|---|---|---|
| **1** | §B1-B5 — make the suite safe by default | — | Everything else requires running tests repeatedly. Do this before iterating. |
| **2** | §A1-A4 — fix the evidence gate | — | Highest severity. §C is written against its corrected behaviour. |
| **3** | §C1-C3 — rewrite the artifact-gate tests | §A | Needs A's corrected path semantics. |
| **4** | §D1-D3 — neutralise the embeddings singleton | §B1 | Shares the `tests/conftest.py` surface. |
| **5** | §E1-E5 — font validation | — | Independent; fonts already installed, so tests are green meanwhile. |
| **6** | §F — marker cleanup | §B3 | Bookkeeping after B lands. |

Each phase: implement → `pytest tests/unit -q` → `lint-imports --config .importlinter` (7/7 KEPT) →
commit. Do not batch phases into one commit; A and C in particular need to be independently
revertible.

---

## Risks

| Risk | Mitigation |
|---|---|
| §A changes a **shared** DI binding | A2's full-consumer audit is mandatory. If any consumer wants CWD-relative paths, bind a second named adapter instead of mutating the shared one. |
| §A3 turns a silent skip into a warning; noisy logs if a legitimate out-of-root path is common | Land A1 first so out-of-root becomes rare, then A3. If still noisy, the noise is real signal about a second misconfiguration. |
| §B4's `addopts` default surprises someone expecting live tests | `-m` on the CLI overrides it; document in the Makefile target and in `CONTRIBUTING`/`CLAUDE.md`. |
| §B1 breaks integration tests that legitimately want `.env` | That is the point — they opt in via `WEEBOT_TEST_LIVE=1`. Verify live mode still works before landing. |
| §C rewrite loses a behaviour the old tests covered | Enumerate the five behaviours (table in §C-iii) as an explicit checklist; each needs a named test. |
| §E3's fail-fast blocks a compile that would have succeeded | Fail open when `fc-list` is unavailable (E2). Font *detection* failure must never become compile failure. |

---

## Open question — a file that vanished mid-session

`tests/test_ensemble_concurrency.py` executed during a full-suite run at ~15:00 on 2026-08-20
(`test_two_persona_fan_out_runs_concurrently_not_serially`, a timing assertion at line 39, failing
against live OpenRouter traffic). It does not exist now, and `git log --all` has no record of it on
any branch — it was untracked. `git stash list` is empty and this session's only stash was
path-scoped to two unrelated files.

**I do not know what removed it, and I did not knowingly delete it.** Flagging rather than
speculating. If it was intentional, disregard. If not, it is unrecoverable from git (never
committed) and would need to be rewritten — in which case build it hermetically: the repo already
has both halves of the pattern, `FakeInnerAdapter(LLMPort)` with injectable latency
(`tests/stress/test_llm_resilience.py:32-58`) and an elapsed-time concurrency assertion
(`tests/unit/test_parallel_tool_execution.py:125-131`). A fan-out timing proof needs *controlled*
latency; real network calls make such an assertion flaky, so the fake is strictly better here.

---

## Appendix — the nine failures, classified

| Test | Count | Cause | Addressed by |
|---|---|---|---|
| `test_artifact_gates.py::TestArtifactVerificationGate::*` | 7 | Tests a layer that no longer holds the logic | §C |
| `test_latex_document.py::test_generation_flow_produces_print_ready_pdf` | 1 | Missing fonts (now installed) | §E |
| `test_latex_document.py::test_compile_greek_example_end_to_end` | 1 | Missing fonts (now installed) | §E |

All nine were verified pre-existing — reproduced against the pre-reformat code by stashing the
reformatted files. None was caused by the `black`/`ruff` pass.
