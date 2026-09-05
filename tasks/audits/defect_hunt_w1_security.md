# Wave 1 — Security & Trust Boundary

Execution record for W1 of [`tasks/specs/defect_hunt_v7_execution_plan.md`](../specs/defect_hunt_v7_execution_plan.md).
Threats **T1** (guard escape) and **T2** (untrusted input → action); classes **C1**, **C2**, **C3**.

Every `[VF]` claim below was produced by running code, not by reading it. Commands are in §9.

---

## Phase 0-WAVE — scope, budget, baseline

| | |
|---|---|
| **Baseline** | `d00f1b4`, all 8 CI checks green, working tree clean. Not a red baseline — the wave was cleared to start. |
| **Budget** | ≤20 candidates generated · ≤12 investigated · ≤8 fixed |
| **Actually spent** | 14 generated · 8 investigated · 5 fixed |
| **Surface correction** | The plan lists `weebot/config/secret_redaction.py` and `weebot/config/credential_sanitizer.py`. Both live in `weebot/core/`. Corrected here; the plan's §4 W1 surface list should be amended. |

---

## Phase 1 — region map

| R | Region | Reachability | Blast radius | Invariant density |
|---|---|---|---|---|
| R1 | Guard enforcement seam (`bash_tool`, `python_tool`, `powershell_tool`) | REACHABLE from every agent step | SYSTEM | High — 4-tier risk model |
| R2 | Guard bypass inventory — 51 subprocess sites | REACHABLE, varies | SYSTEM | Low — no central invariant |
| R3 | Path-resolution helpers (`output_path`, ×3 `_sanitize_output_path`) | **REACHABLE from model-settable tool args** | Arbitrary file write | Docstrings state containment |
| R4 | EgressGuard resolution (`_tool_executor.py:86-111`) | REACHABLE | Ungated exfiltration | Medium |
| R5 | Trust-boundary fencing (`trust_boundary.py` ↔ registry) | **REACHABLE incl. the `webhook` role** | Prompt injection + exfiltration | Registry docstring states the invariant |
| R6 | Secret classification & event sanitisation | REACHABLE | Credential disclosure | Medium |
| R7 | Inbound-mail approval gate (`executing.py:271-288`) | REACHABLE when atomic_mail enabled | T2 entry | ADR 006 |

### Atomic assertions about the map

1. **`[VF]`** `is_untrusted_tool()` gates **two** controls, not one: the prompt fence
   (`_base.py:945`) *and* the egress trifecta taint (`_tool_executor.py:245`). The plan's D11
   described only the fence. A single stale name disables both.
2. **`[VF]`** The argument passed to `is_untrusted_tool()` is the same identifier
   `RoleBasedToolRegistry` authorizes and `ToolCollection.execute(_name=…)` dispatches on —
   so a module file name can never match. `tool_registry.py:21-22` states this invariant in
   prose: *"Tool names MUST match the `name` attribute … (e.g. `bash` not `bash_tool`)."*
3. **`[VF]`** `_SAFE_BASE` is `Path.cwd().resolve()`, captured at import, in all three
   `_sanitize_output_path` copies — so containment is relative to the process's launch
   directory, not the project root.
4. **`[HYP]`** R2's 51 subprocess sites are mostly sandbox backends that are themselves the
   isolation boundary. **Not investigated this wave** — deferred to W7.

---

## Phase 2 → Phase 4 — triaged inventory

| ID | Claim | Trigger (3a) | Innocence (3b) | Verdict |
|---|---|---|---|---|
| **D11** | Untrusted-tool list keyed on module names | **FIRED** — 6 assertions | No defence | ✅ **VERIFIED DEFECT** |
| **D11b** | `_BROWSER_EGRESS_TOOLS` carries the same stale name | **FIRED** | No defence | ✅ **VERIFIED DEFECT** |
| **D3** | `startswith` prefix ≠ path containment | **FIRED** ×3 tools | No defence — `output_path` is a *required* model-settable param | ✅ **VERIFIED DEFECT** |
| **S1** | `output_path()` returns absolute paths verbatim | **FIRED** — `/etc/passwd` → `/etc/passwd` | **Partial defence**: the sole production caller passes the constant `"Output"` | ⚠️ **VERIFIED MECHANISM, NOT REACHABLE** — latent |
| **D6** | Invalid guard regex dropped silently | **FIRED** | **Partial defence**: `custom_patterns` has no production caller | ⚠️ **VERIFIED, LOW REACHABILITY** — latent |
| **D5** | Analyzer exception → weaker legacy check | not run | **Defended**: BashGuard still runs independently at `bash_tool.py:395`; this degrades one added check, it does not bypass the guard | 🔵 **SUSPECTED — deferred** |
| **D4** | EgressGuard `None` ⇒ ungated | not run | **Defended**: requires DI resolution *and* bare `EgressGuard()` to both raise; the latter has no required args and its allowlist swallows its own load errors | 🔵 **SUSPECTED — low reachability, deferred** |
| **D12** | Inbound-mail flag cleared before the pause | not run | **Partially defended**: no clear-without-pause path exists. The residual concern — the flag is cleared before the user *answers*, so a "no" does not re-arm the gate — is real but needs the resume path mapped | 🔵 **SUSPECTED — deferred to W3** |
| — | `knowledge` unfenced | — | **Innocent**: a local note store via `ToolRepositoryPort`, not external content | ⚪ **FALSE** |
| — | `_BROWSER_EGRESS_TOOLS` is dead code | — | **Innocent**: live at `egress_guard.py:306`. My first grep was pattern-scoped and I misread it as definition-only | ⚪ **FALSE** — caught before it entered the inventory |

### The proven exfiltration path (D11)

`browser_navigator` is registered in the **`admin`** and **`webhook`** roles. `webhook` is a
non-human entry point. Before the fix:

1. The agent browses an attacker-controlled page via `browser_navigator`.
2. `is_untrusted_tool("browser_navigator")` → `False`, because the list said `browser_tool`
   (the *module* file name). The page's text entered the prompt **unfenced** — indistinguishable
   from real directives.
3. The session was **never tainted**, so `EgressGuard.classify(..., untrusted_context_active=False)`
   returned `reasons=[]` and `requires_approval=False` for a send to an already-approved
   recipient. Measured, not inferred.

The same stale name in `_BROWSER_EGRESS_TOOLS` meant a form submission *from* that browser tool
was never classified as egress either.

### Why the existing tests did not catch it

`tests/unit/core/test_trust_boundary.py` and `tests/unit/test_trust_boundary.py` contain
25 passing assertions, including `test_email_tool_is_untrusted`, `test_slack_tool_is_untrusted`
and `test_browser_tool` parametrisations. **Every one asserts that a string is in a set.** None
asserts that a *registered* tool is fenced. They were fully compatible with the control being
off for every tool a user can actually call — the C2 fail-open pattern at the test layer.

`tests/unit/test_output_path.py::test_already_absolute_under_project` was worse: it walked up
**four** parents (`/home/user`, the repo's parent) instead of three, so the path it fed in was
*outside* the project root, and it asserted that path came back verbatim. **The test encoded the
escape as expected behaviour.** Corrected, and its name now matches what it tests.

---

## Phase 5 — fixes

| # | File | Change | Lines |
|---|---|---|---|
| 1 | `weebot/core/trust_boundary.py` | Add real `BaseTool.name` values; keep stale names (fail-safe) | +18 incl. comment |
| 2 | `weebot/core/egress_guard.py` | Add `browser_navigator` to `_BROWSER_EGRESS_TOOLS` | +5 |
| 3 | `weebot/tools/{image_gen,video_gen,youtube_download}_tool.py` | `startswith` → `is_relative_to` | +4 each |
| 4 | `weebot/core/output_path.py` | `is_relative_to` + reject absolute paths outside the root | +9 |
| 5 | `weebot/core/bash_guard.py` | Log unusable patterns instead of dropping them silently | +11 incl. logger |

All ≤15 lines, ≤1 function, causal rather than symptomatic. **Stale names were kept, not deleted**:
an unmatched name fences nothing and costs nothing, while a missing name silently disables two
controls. The asymmetry favours over-inclusion.

### Architecture invariants (plan §6)

| # | Invariant | Status |
|---|---|---|
| 1 | `lint-imports` 7/7 KEPT | ✅ verified after the fixes |
| 2 | No new `ignore_imports` | ✅ none added |
| 3 | Dependency direction; domain pure | ✅ no domain file touched |
| 6 | No port signature changed | ✅ |
| 7 | Structured output stays Pydantic-validated | ✅ untouched |
| 8 | Shell execution routes through `BashGuard` | ✅ no new subprocess site |
| 10 | Fix + proof test in one commit | ✅ |

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` `is_relative_to` accepts a path *equal* to the base (a directory — a write there fails anyway). `.resolve()` follows symlinks, so an in-workspace symlink pointing out is now correctly rejected — a strengthening, not a regression. |
| **Invalid input** | `[VF]` `output_path("")` → cwd, unchanged. `output_path(None)` → `AttributeError`, unchanged. |
| **State** | `[VF]` `_untrusted_context_active` is sticky and never reset. More tools now set it. **This is a live behaviour change — see residual risk R-1.** |
| **Regression** | `[VF]` Full suite green; see §9. |
| **Concurrency** | `[VF]` No shared mutable state introduced. The added module logger is thread-safe. |
| **New defects** | `[VF]` `output_path()` now *raises* where it returned. Its only production caller (`_base.py:539`) passes the literal `"Output"` and cannot raise. `[HYP]` A future caller passing a user path will now get `ValueError` — which is the point, but it is a new exception on a previously total function. |

---

## Phase 7 — tests

| File | Added | Purpose |
|---|---|---|
| `tests/unit/core/test_trust_boundary_registry.py` | **26 tests, new file** | The causal gate |
| `tests/integration/test_security_penetration.py` | +5 | W1 exit criterion |
| `tests/unit/test_output_path.py` | +2, 1 corrected | Boundary + the corrected test |
| `tests/unit/test_bash_guard_security.py` | +3 | Visibility of dropped rules |

**The gate was proven to block**: reverting the three name additions turns
`test_trust_boundary_registry.py` from 26 passed to **7 failed / 19 passed**; restoring returns
26 passed. It parses `BaseTool.name` values with `ast` (no imports, so optional third-party
dependencies cannot make it skip) and asserts *both* directions — every external-content tool is
fenced, and every listed name is either a real tool or explicitly grandfathered. A future rename
fails the build.

`test_registry_parse_finds_known_tools` guards the guard: a parser returning an empty set would
otherwise make every other assertion vacuous — the exact failure mode Wave 0 was created to fix.

---

## Phase 8 — coverage & residual-risk statement

### Covered

R3, R4 (partial), R5 investigated to a verdict with executable evidence. Three verified defects
fixed and proven; two latent ones fixed; five candidates cleared or deferred **with a stated
reason**, not silently dropped.

### NOT covered — stated plainly

- **R1 and R2 were not hunted.** The 51 subprocess sites were enumerated but not triaged. D8
  (`state_verifier.py:501` raw `create_subprocess_shell`) is **untouched**. Deferred to W7.
- **R6 (secret classification) was not investigated.** D9 and D10 remain `[HYP]`, unexamined.
- **R7 was read but not triggered.** D12 is `[UNK]` on the resume path.
- **D5, D4 were cleared by reasoning, not by an executable trigger.** Their innocence arguments
  are in the table above; neither is proven innocent, only defended. `[HYP]`, not `[VF]`.
- **No fuzzing, no statistical harness.** All triggers are deterministic single-shot.

### Residual risks

- **R-1 — egress friction is now higher, and enforcement is on by default.**
  `is_enforcing()` reads `WEEBOT_EGRESS_ENFORCE` defaulting to **true**. Adding `weather`,
  `search_images`, `spacescraper` and the OCR variants to the untrusted set means those tools now
  taint the session, so subsequent sends require approval where they previously did not.
  **This is the intended trifecta semantics, but it is a real, user-visible tightening.**
  The security-economics counter-argument deserves stating: over-tainting trains users to approve
  reflexively or to set `WEEBOT_EGRESS_ENFORCE=false`, which disables the control completely —
  strictly worse than the narrow injection risk from, say, wttr.in.
  **Recommended follow-up `[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`:** decouple the two
  controls. The *fence* has no usability cost and should apply to everything external; only the
  *taint* should be reserved for high-risk ingest. That needs two lists or a severity level plus
  changes at both call sites — beyond this wave's ≤15-line fix policy, so it was deliberately not
  attempted here.
- **R-2 — the untrusted list is still hand-maintained.** The new gate catches a *rename*; it
  cannot catch a genuinely new external tool whose author adds it to neither list. Making
  untrustedness a declared property of `BaseTool` would be causal, and is the better long-term
  fix. Also cross-boundary.
- **R-3 — `EXTERNAL_CONTENT_TOOLS` in the test is a human judgment call.** `weather` is included,
  `knowledge` excluded. Both are defensible; neither is derived from code.
- **R-4 — `_SAFE_BASE` is still CWD-derived.** The containment check is now correct, but what it
  contains *relative to* still depends on the launch directory. Running the agent from `/` would
  make the entire filesystem "the workspace". Not fixed — out of this wave's fix budget, and the
  fix is a design decision about where the workspace root comes from.

### One pre-existing flaky test, attributed not dismissed

`tests/stress/test_llm_resilience.py::TestMixedFailureModes::test_partial_outage_with_retries`
failed once during `make check` and passed in the same session's `pytest tests/` run.
Attribution evidence, in order of strength:

1. **`[VF]` The W1 diff cannot reach it.** Importing
   `weebot.infrastructure.adapters.llm.resilient_adapter` loads **none** of the seven modules
   this wave changed.
2. **`[VF]` 10/10 passes** across 12 isolated runs on this branch.
3. **`[VF]` Its runtime spans 4.63s → 57.98s** for identical input — a 12× spread.
4. **`[VF]` The mechanism is in the test's own configuration.** It drives `fail_rate=0.5` off
   the *global unseeded* `random` module, over 20 concurrent requests, with retry delays
   `[1, 2, 4, 8, 15, 30]` summing to 60s against a **30s adapter timeout** — so under load the
   later retries are cut off and the effective attempt count drops, which is what moves the
   ≥18/20 assertion.

**`[INFERENCE]`** a timing-induced flake in a pre-existing load-sensitive test, not a W1 regression.

**Deliberately not touched.** Loosening the assertion would weaken a test; seeding the RNG or
making the timing deterministic is a real fix but belongs to **W5** (LLM adapters), which owns
this surface. It is recorded here rather than repaired out of scope. It does not gate CI —
no CI job runs `tests/stress/` — but it does make `make check` intermittently red, which is a
Wave-0-class instrument problem that W5 should close.

### Verdict

**PARTIAL.** Three verified defects and two latent ones fixed with proof tests and a gate that
blocks their reintroduction. R1, R2 and R6 were declared in scope and were **not** hunted; the
wave stopped at its investigation budget rather than at its surface. W7 inherits R1/R2; R6 needs
its own pass.
