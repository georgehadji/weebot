---
type: object
name: ExecApprovalPolicy (approval modes and rules)
code: ExecApprovalPolicy, ApprovalMode, CommandRule
cluster: core
universe: live
status: verified
verified: 2026-10-27
commit: 2c6a2a72
---

# ExecApprovalPolicy

A rule table that answers "may this command run, must a human confirm it, or is it denied?" for a command or code string. It returns an `ApprovalResult`; it never asks anyone. Every caller turns "needs confirmation" into a tool error.

## Why this shape
Ported from OpenClaw and written for Windows PowerShell (`weebot/core/approval_policy.py:1-8`). Like BashGuard it is fail-closed on its own breakage: if any regex rule fails to compile, the policy sets `approved=False, requires_confirmation=True` for every command until fixed, instead of skipping the bad rule, because the table includes DENY rules (`:210-250`). The tables are meant to be immutable after import: `_DEFAULT_RULES` is a tuple, `TOOL_CATEGORIES` a `MappingProxyType` (`:192-197, 366`).

## Shape
- `ApprovalMode`: `AUTO_APPROVE`, `ALWAYS_ASK`, `DENY`, `FORCE_ALWAYS_ASK` (`:21-25`). `CommandRule(pattern, mode, is_regex, undo_hint)`; `ApprovalResult(command, approved, requires_confirmation, undo_hint, reason)` (`:28-42`).
- Default rules, 21 (`:65-189`): auto-approve `Remove-Item` and Python `open(..., "w")` inside an `Output\` path; DENY `format X:` and `Format-Volume`; ALWAYS_ASK `reg add/delete`, `net user/localgroup`, `icacls`, `takeown`, `bcdedit`, `diskpart`, `schtasks`, `Set-Content ... $env:`, `Out-File` to a non-Output absolute path, `remove-item`, `del`, `rm`, `stop-process`, `kill`, `rd`, `erase`, `rmdir`.
- `evaluate(command, tool_category="")` (`:239`):
  1. Broken rule → ask for everything (`:240-250`).
  2. A category that maps to `FORCE_ALWAYS_ASK` (`finance`, `payment`, `inbound_mail`, `:366-374`) returns approved-but-needs-confirmation (`:253-262`).
  3. Collect matching rules (regex search, or case-insensitive substring); **chained destructive override**: if the command contains `;`, `&` or `|` and any destructive keyword (`rm`, `del`, `remove-item`, `set-content`, `move-item`, `copy-item`, `kill`, ...) it asks, whatever else matched (`:279-295`).
  4. Otherwise the **longest pattern string** wins; DENY → `approved=False`; ALWAYS_ASK → approved with `requires_confirmation=True`; AUTO_APPROVE → plain approve (`:297-322`).
  5. **No rule matched → approved, no confirmation** (`:324-327`).
- Helpers: `get_approval_mode_from_annotation(read_only, destructive)` maps MCP hints to a mode (`:342-358`); `get_category_approval_mode` defaults unknown categories to `AUTO_APPROVE` (`:377-386`).

Consequences (read from source, not run):
- Fixed 2026-10-22 (plan W3.3, F04, F05): `evaluate` now splits the command with `split_segments()` and folds the segments, so `Format-Volume ...; rm x` is denied. Any matching DENY rule beats a longer pattern within a segment. Set-Content, Copy-Item, Move-Item and Rename-Item ask on their own. Steps 3 and 4 above describe the code at `f00ea38`; the source docstring holds the current rule.
- "Longest pattern wins" compares string length of the *pattern*, not specificity. Regex rules tend to be long, so they usually beat the short plain-text rules like `"rm "` (`:299`).
- `Set-Content`, `Copy-Item`, `Move-Item`, `Rename-Item` are only asked about when chained after a separator; standalone they match no rule and are approved (they are in `_DESTRUCTIVE_KEYWORDS`, `:46-62`, but have no standalone rule).
- The `finance` and `payment` categories have no live caller: the only `evaluate` call that passes a category is `ExecutingState` with `"inbound_mail"` (`weebot/application/flows/states/_execution_gates.py:104`); the tools call `evaluate(command)` without one. Only tests exercise those two.
- Fixed 2026-10-23 (ADR-013): a confirmation now reaches a human. `GuardedTool` sends an ASK verdict to the approval channel and runs the approved call inside `human_approved_call` (`application/services/tool_guards.py:462-469`, `core/approval.py:143-155`). `bash`, `python_execute` and `powershell` return "requires confirmation" as an error string only outside that block (`tools/bash_tool.py:398-402`, `python_tool.py:166-171`, `powershell_tool.py:193-197`). `ApprovalManager` (`core/approval.py:157`) is now the single-use grant store behind it (`application/services/tool_approval.py:93`).

## Connected to
- **Callers:** `BashTool` (`bash_tool.py:144, 395`), `PythonTool` (`python_tool.py:114, 162`), `PowerShellTool` (`powershell_tool.py:186-187`, a new instance per call), `ExecutingState` inbound-mail gate (`weebot/application/flows/states/_execution_gates.py:98-104`; the pause and the answer handling live in FlowRouter, see its card), `SafetyChecker.generate_plan_b` (`core/safety.py:43,64`; no production caller since the gateway gate was deleted, audit A33).
- **Related:** `BashGuard` (risk levels, own card), `EgressGuard` (outbound sends, own card), `weebot/core/approval.py` (unused interactive layer).
- **Looks like but is not:** `BashGuard.requires_approval()` (a method on the scanner, not enforced by the tools); `ApprovalMode` here vs `ApprovalDecision` in `approval.py`.

## If you change this
**Hits:** all three code-running tools (a new rule changes what the agent may run), the inbound-mail pause, `SafetyChecker`; tests `tests/unit/test_approval_policy.py`.
**Does not hit:** BashGuard ratings; egress classification; the sandbox.

## Surfaces
Agent shell and code tools; the inbound-mail confirmation question the user sees.

## See
`weebot/core/approval_policy.py`
