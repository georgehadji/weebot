---
type: object
name: ExecApprovalPolicy (approval modes and rules)
code: ExecApprovalPolicy, ApprovalMode, CommandRule
cluster: core
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# ExecApprovalPolicy

A rule table that answers "may this command run, must a human confirm it, or is it denied?" for a command or code string. It returns an `ApprovalResult`; it never asks anyone. Every caller turns "needs confirmation" into a tool error.

## Why this shape
Ported from OpenClaw and written for Windows PowerShell (`weebot/core/approval_policy.py:1-8`). Like BashGuard it is fail-closed on its own breakage: if any regex rule fails to compile, the policy sets `approved=False, requires_confirmation=True` for every command until fixed, instead of skipping the bad rule, because the table includes DENY rules (`approval_policy.py:371-386, 397-407`). The tables are meant to be immutable after import: `_DEFAULT_RULES` is a tuple, `TOOL_CATEGORIES` a `MappingProxyType` (`approval_policy.py:79, 338-343, 759`).

## Shape
- `ApprovalMode`: `AUTO_APPROVE`, `ALWAYS_ASK`, `DENY`, `FORCE_ALWAYS_ASK` (`approval_policy.py:27-31`). `CommandRule(pattern, mode, is_regex, undo_hint)`; `ApprovalResult(command, approved, requires_confirmation, undo_hint, reason)` (`approval_policy.py:34-48`).
- Default rules, 40 (`approval_policy.py:79-335`): one AUTO_APPROVE (Python `open(..., "w")` inside an `Output\` path; shell file cmdlets on `Output/` are no rule but `_output_scoped()`, `approval_policy.py:667-720`); 9 DENY (`format X:`, `Format-Volume`, `Clear-Disk`, deleting under `Windows` or `Program Files`, `Invoke-Expression`/`iex`, `Invoke-Command`/`icm`, `Start-Process -Credential`, `New/Set-LocalUser`, `Add-WindowsCapability`/`Remove-WindowsFeature`); the rest ALWAYS_ASK (`reg add/delete`, `net user/localgroup`, `icacls`, `cacls`, `takeown`, `-ExecutionPolicy Bypass`, `cipher /w`, symlink or junction creation and `mklink`, `bcdedit`, `diskpart`, `schtasks`, `Set-Content ... $env:`, `Out-File` to a non-Output absolute path, `remove-item`, `del`, `rm`, `stop-process`, `kill`, `set-content`, `copy-item` and `cp`, `move-item` and `mv`, forced move/copy/rename and `/y` overwrites, `rename-item`, `rd`, `erase`, `rmdir`).
- `evaluate(command, tool_category="", *, syntax, cwd)` (`approval_policy.py:388`):
  1. Broken rule → ask for everything (`approval_policy.py:397-407`).
  2. A category that maps to `FORCE_ALWAYS_ASK` (`finance`, `payment`, `inbound_mail`, `approval_policy.py:759-767`) returns approved-but-needs-confirmation (`approval_policy.py:409-419`).
  3. Split into segments on `;`, `&&`, `||`, `|`, `&` and newlines outside quotes (`split_segments`, literal `$x = "..."` inlined) and judge each alone; the strictest segment wins, DENY > ASK > AUTO (`approval_policy.py:421-454`).
  4. Per segment (`_evaluate_segment`, `approval_policy.py:470-519`): collect matching rules (regex search, or case-insensitive substring); if only built-in rules matched, none a DENY, and `_output_scoped(segment, cwd)` holds, no match (`approval_policy.py:491-494`). Any DENY match wins whatever its length, else the **longest pattern string** (`approval_policy.py:495-496`); the overwrite hint outranks a milder hint of the same mode (`approval_policy.py:497-503`).
  5. No rule matched: in a chained command a destructive keyword (`rm`, `del`, `remove-item`, `shutdown`, `clear-content`, ...) asks (`approval_policy.py:511-518`); otherwise **approved, no confirmation** (`approval_policy.py:519`).
- Also `unreviewed_segments` (`approval_policy.py:456-468`; segments no rule judges and that are not plain reads, used by `weebot/application/services/tool_guards.py:200`), `is_read_only_segment` (`approval_policy.py:563-594`) and `stays_in_workspace` (`approval_policy.py:597-605`).
- Helpers: `get_approval_mode_from_annotation(read_only, destructive)` maps MCP hints to a mode (`approval_policy.py:735-751`); `get_category_approval_mode` defaults unknown categories to `AUTO_APPROVE` (`approval_policy.py:770-779`).

Consequences (read from source, not run):
- Fixed 2026-10-22 (plan W3.3, F04, F05): `evaluate` now splits the command with `split_segments()` and folds the segments, so `Format-Volume ...; rm x` is denied. Any matching DENY rule beats a longer pattern within a segment (`approval_policy.py:491-496`). Set-Content, Copy-Item, Move-Item and Rename-Item ask on their own (`approval_policy.py:256-285, 310-315`).
- Fixed 2026-10-29 (audit R01): `split_segments` lives in `weebot/core/shell_segments.py` and, for shell text, also splits on newlines outside quotes, so a delete on the line after an Output\ write is judged on its own; python_execute code stays one block (`SegmentSyntax.PYTHON`, `python_tool.py:167`). The Output\ carve-out resolves relative paths against the directory the command runs in (`evaluate(..., cwd=)`, `bash_tool.py:397`).
- "Longest pattern wins" compares string length of the *pattern*, not specificity. Regex rules tend to be long, so they usually beat the short plain-text rules like `"rm "` (`approval_policy.py:496`).
- `shutdown`, `restart-computer` and `clear-content` are in `_DESTRUCTIVE_KEYWORDS` (`approval_policy.py:60-76`) but have no standalone rule: they ask only when chained after a separator; alone they match nothing and are approved.
- The `finance` and `payment` categories have no live caller: the only `evaluate` call that passes a category is `ExecutingState` with `"inbound_mail"` (`weebot/application/flows/states/_execution_gates.py:104`); the tools call `evaluate(command)` without one. Only tests exercise those two.
- Fixed 2026-10-23 (ADR-013): a confirmation now reaches a human. `GuardedTool` sends an ASK verdict to the approval channel and runs the approved call inside `human_approved_call` (`application/services/tool_guards.py:515-522`, `core/approval.py:143-155`). `bash`, `python_execute` and `powershell` return "requires confirmation" as an error string only outside that block (`tools/bash_tool.py:400-404`, `python_tool.py:170-175`, `powershell_tool.py:165-168`). `ApprovalManager` (`core/approval.py:157`) is now the single-use grant store behind it (`application/services/tool_approval.py:94`).

## Connected to
- **Callers:** `BashTool` (`bash_tool.py:146, 397`), `PythonTool` (`python_tool.py:116, 167`), `PowerShellTool` (`powershell_tool.py:161-162`, a new instance per call), `ExecutingState` inbound-mail gate (`weebot/application/flows/states/_execution_gates.py:96-106`; the pause and the answer handling live in FlowRouter, see its card), `SafetyChecker.generate_plan_b` (`core/safety.py:43,64`; no production caller since the gateway gate was deleted, audit A33).
- **Related:** `BashGuard` (risk levels, own card), `EgressGuard` (outbound sends, own card), `weebot/core/approval.py` (unused interactive layer).
- **Looks like but is not:** `BashGuard.requires_approval()` (a method on the scanner, not enforced by the tools); `ApprovalMode` here vs `ApprovalDecision` in `approval.py`.

## If you change this
**Hits:** all three code-running tools (a new rule changes what the agent may run), the inbound-mail pause, `SafetyChecker`; tests `tests/unit/test_approval_policy.py`.
**Does not hit:** BashGuard ratings; egress classification; the sandbox.

## Surfaces
Agent shell and code tools; the inbound-mail confirmation question the user sees.

## See
`weebot/core/approval_policy.py`
