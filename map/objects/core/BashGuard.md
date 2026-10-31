---
type: object
name: BashGuard (and the shell-tool gate chain)
code: BashGuard, RiskLevel
cluster: core
universe: live
status: verified
verified: 2026-10-31
commit: ff808eb3
---

# BashGuard

A regex scanner that rates a command string SAFE, SUSPICIOUS, DANGEROUS or BLOCKED. It decides nothing by itself: each tool that runs shell or code, and the `GuardedTool` chain around it, reads the rating and chooses what to do with it. Inside the tools only BLOCKED stops a command; in the chain (default mode `enforce`) BLOCKED is refused and DANGEROUS asks a human.

## Why this shape
Pure core-layer code with no infrastructure imports; metrics and hooks are injected (`weebot/core/bash_guard.py:427-439`, `on_security_event`; the hook registry is a module global, `bash_guard.py:24-29`). It is fail-closed on its own breakage: a BLOCKED or DANGEROUS pattern that fails to compile makes every `evaluate` return BLOCKED instead of "clean" (`bash_guard.py:454-484, 523-535`). The source says built-in patterns are pinned to compile by a test, so the risk is for `custom_patterns` (`bash_guard.py:469-474`).

## Shape
- `RiskLevel` enum: safe, suspicious, dangerous, blocked (`bash_guard.py:32-38`). `SafetyCheck(pattern, risk_level, description, suggestion)` is a frozen record (`bash_guard.py:41-48`).
- Rule tables, 55 patterns in six groups: `DESTRUCTIVE_PATTERNS` (rm variants, `curl|bash`, redirects into system dirs), `SYSTEM_PATTERNS` (systemctl, chmod 777, mkfs, dd, `python -c`, `reg add/delete`, `format X:`), `CREDENTIAL_PATTERNS`, `NETWORK_PATTERNS`, `ATTACK_PATTERNS` (fork bomb, base64 into an interpreter, obfuscated `__import__`), `WINDOWS_PATTERNS` (`Invoke-Expression`, `iex`, `-EncodedCommand`, `Remove-Item -Recurse -Force`, `shutdown`) (`bash_guard.py:72-425`). Compiled case-insensitively (`bash_guard.py:458`).
- `evaluate(command)` (`bash_guard.py:507`): `_normalize` first (tabs, escaped spaces, `rm` flag variants like `-fr`, `--recursive --force` all become `rm -rf`, `bash_guard.py:486-505`), then every matching pattern becomes a `SafetyCheck`; the highest level wins (`bash_guard.py:560-578`). The callback fires for any non-safe result and never raises (`bash_guard.py:581-586`). An empty command is SAFE with a named `<empty>` check, not an empty list (`bash_guard.py:537-554`).
- Helpers: `is_safe`, `is_blocked`, `requires_approval` (SUSPICIOUS or DANGEROUS), `get_risk_description`, `format_check_results` (`bash_guard.py:590-661`).
- Some commands match twice at different levels (`curl ... | bash` is BLOCKED at `bash_guard.py:115-121` and DANGEROUS at `bash_guard.py:237-242`); the maximum applies.

## How the tools use it (the part that matters)
| Tool | Gates, in order | Source |
|---|---|---|
| `bash` | `CommandSecurityAnalyzer` (DANGEROUS refuses; the HMAC override token was retired by ADR-013; analyzer crash refuses) → **BashGuard: only BLOCKED returns an error** → `ExecApprovalPolicy` (DENY errors; needs-confirmation errors unless `GuardedTool` runs the call as human-approved, fixed 2026-10-23) → sandbox | `tools/bash_tool.py:251-308, 356-404` |
| `python_execute` | BashGuard on the code string (only BLOCKED refuses) → `ExecApprovalPolicy` → sandbox | `tools/python_tool.py:155-175` |
| `powershell` | in the tool's own code: `_validate_no_encoded_commands`, then `ExecApprovalPolicy` (dangerous cmdlets and system paths are DENY rules in the policy itself) → sandbox. **No BashGuard, no `CommandSecurityAnalyzer`** | `tools/powershell_tool.py:154-168` |
| `GuardedTool` around the three tools above | `BashGuardAdapter` (BLOCKED to DENY, DANGEROUS to ASK, SUSPICIOUS note only), `AnalyzerAdapter`, `ApprovalPolicyAdapter`, financial and outbound policy, `EgressAdapter` (not in flows); most restrictive verdict wins; DENY refused, ASK goes to the approval channel, then the tool runs as human-approved | `application/services/tool_guards.py:89-115, 431-444, 492-523` |
| other callers | `latex_compiler.py` (refuses BLOCKED), CLI `guard` command | `infrastructure/document/latex_compiler.py:26,136-137`, `cli/commands/guard.py` |

Consequences (read from source, not run):
- Inside the tools, DANGEROUS and SUSPICIOUS ratings are logged and counted but do not stop `bash` or `python_execute`; `get_risk_description` says DANGEROUS needs "explicit approval", and only the `GuardedTool` chain asks (`tool_guards.py:89-115`). A bare `BashTool()` has no such gate.
- `bash`, `powershell` and `python_execute` from the registry (`application/services/tool_registry.py:539-541`, flows pass `include_egress=False` because `ToolExecutor` gates egress) are wrapped in `GuardedTool`; the MCP server wraps `bash` and `python_execute` (`weebot/mcp/server.py:392`). Default mode is `enforce` since W3.7 (`weebot/config/settings.py:241-245`); `observe` only logs the verdict and the tools' own gates decide (`tool_guards.py:11-18`).
- The `post_bash_guard` hook payload marks `requires_approval` for SUSPICIOUS and DANGEROUS (`bash_tool.py:376-377`). It is a report only, spawned through `core/background_tasks.py` (`bash_tool.py:365-381`); nothing reads it to stop the command. The hook registry is a module global set by `set_bash_guard_hooks` (`bash_guard.py:27-29`).
- The `powershell` tool itself skips BashGuard, although the root `CLAUDE.md` rule says every shell command goes through `bash_guard.py`: its `Invoke-Expression`, `iex`, `-EncodedCommand` and `Remove-Item -Recurse -Force` rules reach it only through `GuardedTool` (`tests/unit/fixes/test_f01_powershell_skips_bash_guard.py`); built bare, only `ExecApprovalPolicy` and the encoded-command validator apply.
- `CommandSecurityAnalyzer.analyze` returns early only on DANGEROUS from layers 1-3 and otherwise returns the layer 4 verdict alone (`tools/bash_security.py:308-318`). Layers 1-3 can only return SAFE or DANGEROUS, so nothing is dropped today; a future SUSPICIOUS rule in those layers would be. See its own card.

## Connected to
- **Wired in** `BashTool.__init__` (`bash_tool.py:147`) and `PythonExecuteTool.__init__` (`python_tool.py:117`) with a Prometheus counter `bash_guard_events_total` (`infrastructure/observability/metrics.py:59`).
- **Related:** `CommandSecurityAnalyzer`, `ExecApprovalPolicy`, `EgressGuard` and `ApprovalManager` (single-use approval grants, held in `application/services/tool_approval.py:94`) (own cards, all in this folder).
- **Looks like but is not:** `ExecApprovalPolicy` (a different rule table, PowerShell-oriented, modes not levels); `CommandRiskLevel` (3 levels, analyzer).

## If you change this
**Hits:** `bash`, `python_execute` and (through `BashGuardAdapter`) `powershell` tools, `latex_compiler`, the `guard` CLI, the `bash_guard_events_total` metric, `post_bash_guard` hooks; tests `tests/unit/test_bash_guard_security.py`, `tests/unit/test_bash_guard_windows.py`, `tests/unit/test_bash_guard_cli.py`, `tests/unit/application/services/test_tool_guards.py`, `tests/unit/test_architecture_fitness.py` (core must not import outward).
**Does not hit:** the `powershell` tool's own code; egress decisions; the sandbox.

## Surfaces
Agent shell/code tools; `python -m cli.main guard ...` for checking a command by hand.

## See
`weebot/core/bash_guard.py`
