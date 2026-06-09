# Security Audit: aipoch/medical-research-skills

**Date:** 2026-06-08  
**Scope:** 556 SKILL.md files, 544 Python scripts, 326 R scripts, 9 shell scripts  
**Clone path:** `~/.weebot/skills/medical-research/`

---

## Executive Summary

**Overall risk: LOW.** The skill library is well-structured for agent use. No curl-pipe-bash patterns, no hardcoded credentials, no `sudo` or `rm -rf /` in any skill workflow. The few concerning patterns are either false positives (safety guarantees in descriptions) or low-risk (internal package installs). The main security consideration is that weebot's existing bash/Python sandboxes must be active when executing skills — the scripts themselves are safe but an agent with unrestricted shell access could be dangerous regardless of which skill it's following.

---

## Findings

### ✅ Clean — No issues found

| Check | Result |
|-------|--------|
| curl \| bash | 0 matches across 556 SKILL.md files |
| Hardcoded API keys / passwords | 0 matches |
| `sudo` in skill workflows | 0 matches |
| `rm -rf /` in skill workflows | 0 matches |
| `chmod 777` | 0 matches |
| raw.githubusercontent.com in skills | 0 matches (only in installer script) |
| `eval()` / `exec()` as dangerous calls | 0 (2 hits are safety guarantees: "never uses eval()") |
| Download + remote-execute chains | 0 (3 hits are safety guarantees or workflow descriptions) |

### 🟡 LOW — `os.system()` for pip install

**File:** `scientific-skills/Academic Writing/referral-letter-generator/scripts/main.py:355,473`

```python
os.system(f"{sys.executable} -m pip install reportlab -q")
os.system(f"{sys.executable} -m pip install python-docx -q")
```

**Risk:** Uses `os.system()` instead of `subprocess.run()`. While the command is constructed from `sys.executable` (not user input), `os.system()` passes through the shell and is generally discouraged.

**Mitigation:** Weebot's Python sandbox (`python_tool.py`) should restrict `os.system()`. This is already handled by weebot's `SandboxPort`.

### 🟡 LOW — `subprocess.run(shell=True)`

**File:** `scientific-skills/Other/academic-poster-generator/scripts/review_poster.py:28-34`

```python
subprocess.run(command, capture_output=True, text=True, timeout=30, shell=True)
```

**Risk:** The `command` list is constructed internally from file paths (not user input), so injection risk is minimal. Still, `shell=True` with a list argument is unconventional.

**Mitigation:** Weebot's bash guard evaluates all shell commands. This would be caught by the `SUSPICIOUS` or `SAFE` tier depending on the command content.

### 🟡 LOW — Dynamic import via `__import__()`

**File:** `scientific-skills/Evidence Insight/diffdock-molecular-docking/scripts/setup_check.py:14`

```python
__import__(pkg)
```

**Risk:** Dynamic import check for package availability. Not exploitable since `pkg` comes from a hardcoded list, not user input.

### ℹ️ INFO — 134 skills reference `pip install`

This is normal for Python-based bioinformatics skills. The skills document dependencies; they don't auto-install without the agent choosing to. Weebot's bash guard will gate any `pip install` as SUSPICIOUS.

### ℹ️ INFO — 544 Python scripts included

These are reference implementations, not auto-executed. The agent decides whether to run them. Weebot's `PythonExecuteTool` runs code in an isolated subprocess with timeout and output limits.

### ℹ️ INFO — `openclaw-install.sh` uses curl-pipe-bash

**File:** `scripts/openclaw-install.sh:4`

```bash
bash <(curl -s https://raw.githubusercontent.com/aipoch/medical-research-skills/main/scripts/openclaw-install.sh)
```

This is the project's own installer, not a skill the agent would follow. Irrelevant to agent safety.

---

## Recommendations for weebot

1. **Keep bash guard active** — The `SUSPICIOUS` tier catches `pip install`, and the `DANGEROUS` tier catches `rm -rf`, `chmod 777`, etc. All skill-executed commands should go through `bash_guard.py`.

2. **Keep Python sandbox active** — `PythonExecuteTool` should restrict `os.system()`, `subprocess.Popen(shell=True)`, and network access (`SANDBOX_ALLOW_NETWORK=false`).

3. **No R sandbox exists** — 326 R scripts are present. If weebot ever gains R execution capability, these would need the same sandboxing as Python.

4. **Skill audit hook** — Consider running the repo's own `skill-auditor` against loaded skills before first use. It already checks for `os.system()`, network calls, and file writes.

5. **Watch for skill updates** — The repo auto-updates via CI. Consider pinning to a specific commit hash or running a re-audit on `git pull`.

---

## Verdict

**Safe to use with weebot's existing sandboxing.** No skill instructs the agent to download and execute remote code, access system directories, or use hardcoded credentials. The included scripts are standard bioinformatics tooling (pip installs, subprocess calls for external tools) — all of which weebot's bash guard and Python sandbox already gate.
