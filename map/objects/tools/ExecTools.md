---
type: object
name: ExecTools
code: BashTool, PowerShellTool, PythonExecuteTool, StrReplaceEditorTool, SecureOutputFile, ValidationPipeline
cluster: tools
universe: live
status: verified
verified: 2026-10-30
commit: fe394636
---

# ExecTools

The tools that run code or write files: `bash`, `powershell`, `python_execute`, `file_editor`.

## Why this shape
Each exec tool keeps its own gates inside `execute` and also runs behind `GuardedTool` (see the BaseTool card). The inner gates predate the chain; the chain was added so `powershell` and the MCP server could not skip BashGuard (`weebot/application/services/tool_guards.py:1-9`). Execution goes through a `SandboxPort`, so the tool does not choose how a process is isolated (see the Sandbox card).

## Shape
| Tool (`name`) | Class | Gates inside the tool | Chain (`GuardedTool`) | Runs via |
|---|---|---|---|---|
| `bash` | `BashTool` (`weebot/tools/bash_tool.py:44`) | CommandSecurityAnalyzer DANGEROUS refuses, an analyzer crash refuses (`weebot/tools/bash_tool.py:251-308`); BashGuard BLOCKED refuses (`weebot/tools/bash_tool.py:362, 383-394`); ExecApprovalPolicy deny refuses, ask refuses unless a human approved this call (`weebot/tools/bash_tool.py:396-404`) | yes, all shell adapters (`weebot/application/services/tool_guards.py:41-43`) | `sandbox.execute_shell(shell="powershell" on Windows unless use_wsl, else "bash")` (`weebot/tools/bash_tool.py:414-418`) |
| `powershell` | `PowerShellTool` (`weebot/tools/powershell_tool.py:27`) | the shared encoded-command matcher (`weebot/core/encoded_command.py:32-34`, every prefix of `-EncodedCommand`, used by BashGuard, the analyzer and this tool) and a check for long base64 that decodes to PowerShell (`weebot/tools/powershell_tool.py:95-136`); ExecApprovalPolicy deny refuses (its deny rules now hold the cmdlets and system paths this tool once listed privately, wave 6 G11), ask refuses unless a human approved (`weebot/tools/powershell_tool.py:158-168`) | yes, all shell adapters | `sandbox.execute_shell(shell="powershell")` (`weebot/tools/powershell_tool.py:184-188`) |
| `python_execute` | `PythonExecuteTool` (`weebot/tools/python_tool.py:32`) | BashGuard BLOCKED on the code (`weebot/tools/python_tool.py:158-161`); ExecApprovalPolicy deny refuses, ask refuses unless a human approved (`weebot/tools/python_tool.py:163-175`) | wrapped; the BashGuard and analyzer adapters skip it (they read only `command` of `bash`/`powershell`, `weebot/application/services/tool_guards.py:41, 79-83`), the policy adapter evaluates its `code` (`weebot/application/services/tool_guards.py:164-182`) | `sandbox.execute_python(memory_limit_mb=256)` (`weebot/tools/python_tool.py:178-180`) |
| `file_editor` | `StrReplaceEditorTool` (`weebot/tools/file_editor.py:17`) | null byte check (`weebot/tools/file_editor.py:91-94`); `PathValidator` (`weebot/tools/file_editor.py:96-127`); resolved path must be under `WORKSPACE_ROOT` (`weebot/tools/file_editor.py:130-138`); `fs_permissions` rules, `interrupt` fails closed (`weebot/tools/file_editor.py:140-166`) | no (not in `GUARDED_TOOLS`, `weebot/application/services/tool_guards.py:43`) | direct `Path.write_text` / atomic `.tmp` replace (`weebot/tools/file_editor.py:183-301`) |

- Sandbox: the three exec tools take a `SandboxPort`; with none they call `create_default_sandbox()` (`weebot/infrastructure/sandbox/factory.py:385`) and, if that fails, log a warning and return an error on every call (`weebot/tools/bash_tool.py:131-144, 407-411`; `weebot/tools/powershell_tool.py:66-79, 179-183`; `weebot/tools/python_tool.py:101-114, 137-141`). The registry injects the container's sandbox (`weebot/application/services/tool_registry.py:469, 482-483`).
- Timeouts: `bash` defaults to `ToolConfig.bash_timeout`, floor 1 s, ceiling `max_tool_timeout` or 300 (`weebot/tools/bash_tool.py:163-169, 342-354`); `python_execute` the same with `python_timeout` (`weebot/tools/python_tool.py:119-122, 143-153`); `powershell` 30 s default, ceiling 300 or `max_tool_timeout`, no floor (`weebot/tools/powershell_tool.py:140-144, 170-176`). `bash` and `powershell` declare `default_timeout_seconds = 300` and keep the tail on truncation (`weebot/tools/bash_tool.py:64-65`, `weebot/tools/powershell_tool.py:36-37`).
- Output trust: `bash`, `powershell` and `python_execute` declare `LOCAL` on purpose, so their output is neither fenced nor tainting (`weebot/tools/bash_tool.py:62`, `weebot/tools/powershell_tool.py:34`, `weebot/tools/python_tool.py:48`); the network is gated by the sandbox and `EgressGuard` instead (`tasks/specs/arch_audit_2026_10_remediation_plan.md`, Appendix C item 4). `file_editor` is `EXTERNAL` (`weebot/tools/file_editor.py:19`); `GuardedTool` reports its wrapped tool's value (`weebot/application/services/tool_guards.py:487-490`). The rules are in `weebot/core/trust_boundary.py:58-90`.
- `bash` rewrites a leading `curl` to `curl.exe` on Windows (`weebot/tools/bash_tool.py:334-340`) and fires a `post_bash_guard` hook without awaiting it (`weebot/tools/bash_tool.py:365-381`).
- `powershell` accepts shortcut names (`system_info`, `reset_browser`, ...) that expand to fixed commands before the gates (`weebot/tools/powershell_tool.py:84-93, 146-152`).
- `file_editor` commands: `view`, `create` (refuses to overwrite, `weebot/tools/file_editor.py:234-237`), `str_replace` (first match only, `weebot/tools/file_editor.py:272`), `insert`, `write_large` (overwrites without the existence check, `weebot/tools/file_editor.py:183-198`).

Consequences (read from source, not run):
- An approved ASK runs once. In `enforce` mode `GuardedTool` sends an ExecApprovalPolicy ASK to a human (`weebot/application/services/tool_guards.py:178-181, 515-518`); after "yes" it calls the inner tool inside `human_approved_call` (`weebot/application/services/tool_guards.py:519-522`, `weebot/core/approval.py:143-154`), so the tool's own `requires_confirmation` check lets it through (`weebot/tools/bash_tool.py:400`, `weebot/tools/powershell_tool.py:165`, `weebot/tools/python_tool.py:170`). Called outside `GuardedTool`, the inner tool still refuses an ASK.
- `denied_result` tells the agent that `python_execute` and a script under `Output/` "run without approval" (`weebot/application/services/tool_approval.py:305-310`); the policy adapter can still ASK on `python_execute` code (`weebot/application/services/tool_guards.py:169-171`).
- `MAX_TOOL_TIMEOUT` is named in the `bash` description (`weebot/tools/bash_tool.py:70`) and in `ToolConfig` (`weebot/config/tool_config.py:27`), but nothing reads it: `tool_config_from_settings` leaves `max_tool_timeout` at 300 (`weebot/config/tool_config.py:59-73`).
- `PowerShellTool` has no `set_config`, and the registry builds it with `sandbox=` only (`weebot/application/services/tool_registry.py:482-483, 526-527`), so its `tool_config` is always None.
- `powershell` builds a new `ExecApprovalPolicy()` per call (`weebot/tools/powershell_tool.py:161`); a long base64 blob it cannot decode is refused (`weebot/tools/powershell_tool.py:129-136`), as in `bash` (`weebot/tools/bash_tool.py:208-247`).
- `file_editor` writes are not guarded by the chain, and the `webhook` role, which drops `bash`/`powershell`/`python_execute`, keeps `file_editor` (`weebot/application/services/tool_registry.py:123-162`). Containment is the workspace check above.
- `_wsl_available()` (`weebot/tools/bash_tool.py:35-41`) has no caller; `use_wsl=True` picks `shell="bash"` without checking WSL (`weebot/tools/bash_tool.py:415`).
- Comment says tool-level overrides use `set_config(ToolConfig)` (`weebot/tools/file_editor.py:13-14`); `StrReplaceEditorTool` has no `set_config`.

## Connected to
- **Built by** `RoleBasedToolRegistry` (sandbox and `set_config` wiring, `weebot/application/services/tool_registry.py:446-531`), the MCP server, which wraps `bash` and `python_execute` with the egress guard included (`weebot/mcp/server.py:383-392`).
- **Gated by** the BashGuard, CommandSecurityAnalyzer and ExecApprovalPolicy cards (`weebot/core/bash_guard.py`, `weebot/tools/bash_security.py`, `weebot/core/approval_policy.py:346, 388`); `PathValidator` (`weebot/infrastructure/security/security_validators.py:35`); `load_fs_permission_checker` (`weebot/application/services/fs_permission_policy.py:33`).
- **Runs on** the Sandbox card's `SandboxPort`.
- **Looks like but is not:** the guard chain (live).

## If you change this
**Hits:** the `admin`, `coder`, `analyst`, `automation`, `product_manager` roles (`bash`), `admin`, `coder`, `analyst`, `automation` (`python_execute`), `admin` only (`powershell`), every role but `custom` (`file_editor`), MCP `bash`/`python` tools. Tests: `tests/unit/tools/test_bash_tool.py`, `tests/unit/tools/test_bash_security_falsifying.py`, `tests/unit/tools/test_python_tool.py`, `tests/unit/tools/test_python_tool_timeout.py`, `tests/unit/tools/test_file_editor.py`, `tests/unit/tools/test_tool_wrappers.py`, `tests/unit/test_fs_permissions.py`, `tests/unit/security/test_security_gates_fail_closed.py`, `tests/unit/test_adversarial_security.py`, `tests/unit/test_audit_findings.py`, `tests/unit/fixes/test_f12_hook_payload.py`, `tests/unit/interfaces/test_mcp_server.py`, `tests/integration/test_security_penetration.py`, `tests/integration/test_website_generation.py`, `tests/e2e/test_portfolio_website.py`, `tests/conftest.py`.
**Does not hit:** the guard rules themselves.

## Surfaces
Agent tool calls; MCP `bash`/`python` tools; the approval prompt for ASK verdicts.

## See
`weebot/tools/bash_tool.py`, `weebot/tools/powershell_tool.py`, `weebot/tools/python_tool.py`, `weebot/tools/file_editor.py`
