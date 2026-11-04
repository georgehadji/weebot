---
type: object
name: ApprovalFloors
code: Floor, BUILTIN_FLOORS, FloorGuard, command_variants
cluster: core
universe: live
status: stub
---

# ApprovalFloors

Shell commands that no approval mode may wave through: `deny` is refused, `human` needs a person to say yes even in AUTO.

## Why this shape
AUTO mode granted every ASK, so nothing stood between the agent and `rm -rf ~`. A floor is a plain text match that runs in the guard chain, ahead of the modes. ADR-022 has the reasoning.

## Shape
- `Floor(id, matches, action, reason)`, `BUILTIN_FLOORS`, `glob_floors(globs)`, `first_floor(variants, floors)` (`weebot/core/approval_floors.py`).
- `command_variants(command)` (the text, without backticks, without quotes, base64 decoded) and `FloorGuard`, first link of `default_guard_chain` (`weebot/application/services/tool_guards.py`).
- `GuardAction.HUMAN` becomes `ToolCallApproval.human_only`; `AutoApproval` answers it through the flow pause instead of granting it (`weebot/application/services/tool_approval.py`).

## Connected to
Reads the `WEEBOT_APPROVAL_DENY_GLOBS` setting. Runs for `bash` and `powershell` only. Not the same as `ExecApprovalPolicy` (rules a mode can lower) or `BashGuard` (risk tiers).

## If you change this
**Hits:** what AUTO mode may run unasked, the `ToolApprovalEvent` payload (`human_only`), `AutoApproval`.
**Does not hit:** `python_execute` code, the file tools, the egress gate.

## Surfaces
The approval prompt a user sees for a floor; the refusal text `approval_floor: <id>: <reason>`.

## See
`docs/adr/022-approval-floors.md`
