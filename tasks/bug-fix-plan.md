# Weebot Bug Fix Plan — 13 Findings

> **Architecture**: Clean Architecture (Hexagonal) — Domain → Application → Infrastructure → Interfaces
> **Rule**: Dependencies point inward. Domain must remain pure. Infrastructure implements ports defined in Application.

---

## 🔴 Critical

### 1. XAI_API_KEY: System Env Overrides `.env` — Blocks Image Generation

**Layer:** Infrastructure / Config  
**Files:** `weebot/config/settings.py:27-39`, `weebot/infrastructure/adapters/llm/adapter_factory.py:282-301`

**Root cause:** `pydantic-settings` reads `os.environ` (system env) before falling back to `env_file`. The system environment has an old xAI key (`xai-9WnjS6...`) without image-generation permissions. The `.env` file has a working key (`xai-prm8UtMf6...`) that returns HTTP 200 from `api.x.ai/v1/images/generations`. Since `os.getenv("XAI_API_KEY")` also reads system env first, both the settings layer AND the adapter factory's `_has_direct_key()` + `os.getenv("XAI_API_KEY")` path pick up the wrong key.

**Fix (3 changes):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/config/settings.py:30` | Set `env_file_override=True` in `SettingsConfigDict` so `.env` values take priority over system env vars |
| B | `weebot/infrastructure/adapters/llm/adapter_factory.py:285` | Read xAI key via `WeebotSettings().xai_api_key` instead of `os.getenv("XAI_API_KEY")`, so the settings layer's resolution logic applies consistently |
| C | `weebot/infrastructure/adapters/llm/adapter_factory.py:400` | In `_has_direct_key()`, also read from `WeebotSettings()` for consistency, or document that this helper only checks raw env |

**Acceptance:** Running `image_gen` with `kind='openrouter'` and `use_case='photo'` calls xAI's `/v1/images/generations` directly (confirmed by HTTP 200 in logs) and returns a valid image URL instead of SVG fallback.

---

### 2. OpenRouter API Key Returns 401 "User Not Found"

**Layer:** Infrastructure / LLM Adapters  
**Files:** `weebot/infrastructure/adapters/llm/openai_adapter.py:19-22`, `.env`

**Root cause:** The `OPENROUTER_API_KEY` in `.env` is invalid or expired. Every call to `https://openrouter.ai/api/v1/chat/completions` returns `401 Unauthorized` with `{"error": {"message": "User not found.", "code": 401}}`. This silently breaks:
- Verification state (flow completion check) — always falls through
- OpenRouter image model cascade fallback — all image models return 401
- Any model routed through OpenRouter (Kimi, DeepSeek fallback, etc.)

**Fix (3 changes):**

| Step | File | Change |
|------|------|--------|
| A | `.env` | Rotate the OpenRouter API key — generate a new key at https://openrouter.ai/keys |
| B | `weebot/infrastructure/adapters/llm/openai_adapter.py:95-100` | After an auth error (401/403), log a clear WARNING with the provider name and key prefix, then raise — don't silently retry |
| C | `weebot/application/services/health_service.py` (new or existing) | Add `check_llm_keys()` that validates all configured API keys on `/api/health` by making a minimal call (list models or 1-token chat). Flag expired keys in health response |

**Acceptance:** `python -m cli.main health` shows all API keys as valid. OpenRouter calls return HTTP 200. Verification state succeeds.

---

## 🟠 High

### 3. Planner Over-Decomposition — 6-7 Steps for Trivial Tasks

**Layer:** Application / Agents / Planner  
**Files:** `weebot/application/agents/planner.py`, `weebot/config/constants.py`

**Root cause:** The planner agent generates a step for every micro-action (mkdir, echo, verify each echo, compile results). A simple "echo 3 strings" task becomes 6 steps. The plan step budget has no floor — any task gets decomposed to at least 3 steps.

**Fix (2 changes):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/application/agents/planner.py` | Add a `min_task_complexity` heuristic: if the user prompt is under 200 chars AND doesn't contain "and" or multiple verbs, generate exactly 1 step (no decompose). If under 500 chars, cap at 3 steps |
| B | `weebot/config/constants.py` | Add `PLANNER_MAX_STEPS_DEFAULT: int = 7` and `PLANNER_MAX_STEPS_TRIVIAL: int = 1` constants. Pass to planner prompt as constraints |

**Acceptance:** "Echo hello world" → 1 step. "Echo 3 strings and verify" → 2-3 steps max. "Build a portfolio website" → up to 10 steps (unchanged for complex tasks).

---

### 4. `Get-ChildItem -Recurse` Hits `cache/pytest` Permission Denied

**Layer:** Application / Agents / Executor (system prompt)  
**Files:** `weebot/application/agents/executor.py` (system prompt section), `WEEBOT_CORE.md`

**Root cause:** The executor does `Get-ChildItem -Recurse` from the workspace root to find files. The `cache/pytest` directory (created by pytest) has restricted permissions. PowerShell throws `DirUnauthorizedAccessError` which is not suppressed. After 3 consecutive identical errors, the "stuck step" detector fires and blocks the step.

**Fix (2 changes):**

| Step | File | Change |
|------|------|--------|
| A | `WEEBOT_CORE.md` or executor system prompt | Add rule: "All PowerShell `Get-ChildItem -Recurse` calls MUST include `-ErrorAction SilentlyContinue`. Never recurse from workspace root — use specific subdirectories (`Output/`, `tasks/`)." |
| B | `weebot/core/bash_guard.py` | Add `-ErrorAction SilentlyContinue` injection: when the bash guard sees `Get-ChildItem.*-Recurse` without `-ErrorAction`, append it automatically before execution |

**Acceptance:** `Get-ChildItem -Recurse` calls from executor no longer fail with permission denied. Stuck-step detector does not fire spuriously.

---

### 5. Agent Uses Unix Commands on PowerShell — Wastes 2-3 Calls Per Step

**Layer:** Application / Agents / Executor (system prompt)  
**Files:** `WEEBOT_CORE.md`, executor system prompt in `weebot/application/agents/executor.py`

**Root cause:** The executor runs on Windows/PowerShell but its system prompt teaches Unix commands (`ls -la`, `rm -rf`, `2>/dev/null`, `&&` chains, `||`). Each step wastes 2-3 calls translating Unix→PowerShell. Observed 15+ times across tests.

**Fix (1 change):**

| Step | File | Change |
|------|------|--------|
| A | `WEEBOT_CORE.md` + executor system prompt | Add a "PowerShell Command Table" section mapping common Unix commands to their PowerShell equivalents. Make it the FIRST thing the executor sees. |

Table to add:
```
Unix              →  PowerShell
ls -la <dir>      →  Get-ChildItem <dir> | Format-Table Name, Length, LastWriteTime
rm -rf <dir>      →  Remove-Item -Recurse -Force <dir>
mkdir -p <dir>    →  New-Item -ItemType Directory -Force -Path <dir>
cat <file>        →  Get-Content <file>
grep <pat> <file> →  Select-String -Path <file> -Pattern <pat>
curl <url>        →  Invoke-WebRequest -Uri <url>
echo <text>       →  Write-Output <text>
&& chains         →  ; (PowerShell separates with semicolon)
2>/dev/null       →  -ErrorAction SilentlyContinue
|| true           →  ; $null = $?
```

**Acceptance:** Executor uses PowerShell-native commands on first attempt. No `ls -la` errors in logs.

---

### 6. Bash Guard Blocks Valid Complex PowerShell Commands

**Layer:** Infrastructure / Bash Guard  
**Files:** `weebot/core/bash_guard.py`

**Root cause:** The bash guard's operator-count heuristic flags commands with 6-7 pipeline operators as "Suspicious" even when they're harmless file-search patterns like `Get-ChildItem | Where-Object | Select-Object | Format-Table`. These are standard PowerShell idioms.

**Fix (1 change):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/core/bash_guard.py` | Add an allowlist for known-safe PowerShell patterns before the operator count check. If a command matches `Get-ChildItem.*\|.*Select-Object\|.*Format-` or `Get-Content.*\|.*ForEach-Object`, skip the operator-count suspicion check. Raise the threshold from 5 to 8 operators for the generic check. |

**Acceptance:** `Get-ChildItem -Recurse -Include *.md | Where-Object {...} | Select-Object FullName | Format-Table` passes without "Suspicious command" warning. Destructive commands still blocked.

---

## 🟡 Medium

### 7. UTF-8 BOM Corrupts File Comparisons

**Layer:** Infrastructure / Bash Guard + Tools  
**Files:** `weebot/core/bash_guard.py` (PowerShell Out-File wrapper)

**Root cause:** PowerShell's `Out-File -Encoding utf8` prepends a BOM (`EF BB BF`) to files. When the executor later reads the file and compares bytes, the BOM causes a mismatch. This affected the bash test where step 4 compared hex output.

**Fix (1 change):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/core/bash_guard.py` or executor system prompt | Replace all `Out-File -Encoding utf8` with `Out-File -Encoding utf8NoBOM` (PowerShell 7+) or `[System.IO.File]::WriteAllText(path, content, [System.Text.UTF8Encoding]::new($false))` for PowerShell 5.1 compat. Add to the PowerShell command table in the system prompt. |

**Acceptance:** Files written by the executor have no BOM. Hex comparisons match expected values.

---

### 8. `Select-String` Wrong Parameter Names

**Layer:** Application / Agents / Executor (system prompt)  
**Files:** `WEEBOT_CORE.md`

**Root cause:** Same as #5 — the agent uses Unix `grep` mental model. `Select-String` does not have `-Recurse` or `-Depth`. The correct pattern is `Get-ChildItem -Recurse | Select-String -Pattern`.

**Fix:** Covered by fix #5 (PowerShell command table). Add specific row:
```
grep -r <pat> <dir> →  Get-ChildItem -Recurse <dir> | Select-String -Pattern <pat>
```

**Acceptance:** No `Select-String : A parameter cannot be found that matches parameter name 'Recurse'` errors.

---

### 9. Workspace Pollution — Temp Files in Project Root

**Layer:** Application / Agents / Executor  
**Files:** `weebot/application/agents/executor.py`

**Root cause:** The executor writes verification files (`step2_verification.txt`, `bash_guard_test_results.md`) to the workspace root instead of a temp directory. Over multiple sessions this accumulates garbage.

**Fix (1 change):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/application/agents/executor.py` (system prompt) | Add rule: "Temporary files (verification results, test output, intermediate artifacts) MUST be written to `tmp/` or `.weebot/tmp/`, never to the workspace root. Use `file_editor` with path prefix `tmp/`." Also add `tmp/` to `.gitignore`. |

**Acceptance:** No `.txt` or `.md` temp files appear in workspace root after a flow run.

---

### 10. `file_editor` Inconsistent Path Validation

**Layer:** Infrastructure / Tools / File Editor  
**Files:** `weebot/tools/file_editor.py`

**Root cause:** `file_editor` blocked `E:\bash_guard_test_results.txt` with "Path must be within workspace" but allowed `C:\temp\step1_echo_output.txt`. The path validation logic has inconsistent enforcement — it should consistently reject all absolute paths outside the workspace.

**Fix (1 change):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/tools/file_editor.py` | Normalize all paths relative to `WORKSPACE_ROOT` before validation. Reject any path that resolves outside the workspace root, regardless of drive letter. Log a warning with the rejected path for debugging. |

**Acceptance:** Both `E:\anything` and `C:\temp\anything` are consistently blocked. Only workspace-relative paths are accepted.

---

### 11. xAI Intermittent `APIConnectionError` on Long Sessions

**Layer:** Infrastructure / LLM Adapters  
**Files:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`, `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py`

**Root cause:** On long-running sessions (>5 minutes), xAI direct calls occasionally fail with `APIConnectionError: Connection error`. The retry logic triggers but after exhaustion falls back to OpenRouter, which also fails (bug #2). This creates a cascade failure.

**Fix (2 changes):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/infrastructure/adapters/llm/resilient_adapter.py` | Increase `max_retries` from 3 to 5 for xAI provider. Add jitter to retry backoff (random 0-2s). Add exponential backoff cap at 30s. |
| B | `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py:95-100` | Before falling back to OpenRouter, check if the secondary adapter's key is valid (make a cheap 1-token call). If invalid, skip fallback and re-raise the primary error with a clear message instead of masking it with a 401. |

**Acceptance:** Intermittent connection errors retry successfully within 5 attempts. When fallback is impossible, the error message clearly states "xAI direct failed + OpenRouter key invalid" instead of just "401".

---

## 🟢 Low / Observations

### 12. Bash Guard Works Well — No Fix Needed

All 4 dangerous commands correctly blocked. The layered security model (Pattern → Behavioral → Entropy → Semantic) caught everything. No action required.

### 13. Agent Security Analysis Capability — Leverage It

The executor independently performed a 4-layer security audit of the bash guard and found a legitimate Layer 2 bypass (`curl && chmod && ./script` passes behavioral check but is caught by semantic layer). This capability should be productized.

**Suggestion:** Add a `/audit security` slash command that invokes the agent's analysis capability on a specified component. File: `cli/commands/guard.py` (existing guard commands group).

---

## Implementation Order

| Phase | Bugs | Estimated Effort | Dependencies |
|-------|------|-----------------|--------------|
| **Phase 1: Critical fixes** | #1 (XAI key), #2 (OpenRouter key) | 30 min | None — can be done immediately |
| **Phase 2: PowerShell knowledge** | #5 (Unix→PS table), #7 (BOM), #8 (Select-String params) | 20 min | None — single file edit to WEEBOT_CORE.md |
| **Phase 3: Bash guard tuning** | #4 (recurse error), #6 (operator threshold) | 20 min | None |
| **Phase 4: Planner & Executor** | #3 (step budget), #9 (temp files) | 25 min | None |
| **Phase 5: Tool hardening** | #10 (path validation), #11 (retry logic) | 30 min | None |
| **Phase 6: Observability** | #2-C (health check keys) | 20 min | Phase 1 |
| **Phase 7: Productize** | #13 (security audit command) | 45 min | Phase 3 |

**Total estimated effort:** ~3 hours for all 13 fixes.

---

## Verification Plan

After each phase, run these tests:

```bash
# Phase 1 — Key validation
python -m cli.main health                    # All keys show valid
python -m cli.main flow run "Use image_gen with kind=openrouter use_case=photo prompt='test' save to Output/test.png"
# Should show: "Generated image via xAI direct (grok-imagine-image-quality)"

# Phase 2 — PowerShell native
python -m cli.main flow run "List files in Output directory recursively"
# Should NOT show: "ls -la" or "parameter name 'la'" or "Select-String -Recurse"

# Phase 3 — Bash guard
python -m cli.main flow run "Find all .md files in tasks/ and show their names and sizes"
# Should NOT show: "Suspicious command" or "Access to the path ... denied"

# Phase 4 — Planner budget
python -m cli.main flow run "Echo hello"
# Should create exactly 1 step, not 3+

# Phase 5 — Path validation
python -m cli.main flow run "Write 'test' to C:/temp/test.txt using file_editor"
# Should be blocked with "Path must be within workspace"

# Phase 6 — Health endpoint
curl http://localhost:8000/api/health
# Should include "keys": {"openrouter": "valid", "xai": "valid", ...}
```
