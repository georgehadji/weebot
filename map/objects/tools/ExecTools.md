---
type: object
name: ExecTools
code: BashTool, PowerShellTool, PythonExecuteTool, StrReplaceEditorTool, SecureOutputFile, ValidationPipeline
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# ExecTools

The tools that run code or write files: `bash`, `powershell`, `python_execute`, `file_editor`. Two more modules sit beside them, `secure_output.py` and `validation.py`, and nothing imports either.

## Why this shape
Each exec tool keeps its own gates inside `execute` and also runs behind `GuardedTool` (see the BaseTool card). The inner gates predate the chain; the chain was added so `powershell` and the MCP server could not skip BashGuard (`weebot/application/services/tool_guards.py:3-9`). Execution goes through a `SandboxPort`, so the tool does not choose how a process is isolated (see the Sandbox card).

## Shape
| Tool (`name`) | Class | Gates inside the tool | Chain (`GuardedTool`) | Runs via |
|---|---|---|---|---|
| `bash` | `BashTool` `weebot/tools/bash_tool.py:37` | CommandSecurityAnalyzer DANGEROUS refuses, an analyzer crash refuses (`:242-299`); BashGuard BLOCKED refuses (`:353, 378-389`); ExecApprovalPolicy deny or ask refuses (`:392-399`) | yes, all shell adapters (`tool_guards.py:41-43`) | `sandbox.execute_shell(shell="powershell" on Windows unless use_wsl, else "bash")` (`:409-413`) |
| `powershell` | `PowerShellTool` `weebot/tools/powershell_tool.py:20` | regex encoded-command and cmdlet blocklist (`:87-169`); path blocklist (`:104-119`); ExecApprovalPolicy deny or ask refuses (`:193-200`) | yes, all shell adapters | `sandbox.execute_shell(shell="powershell")` (`:217-219`) |
| `python_execute` | `PythonExecuteTool` `weebot/tools/python_tool.py:27` | BashGuard BLOCKED on the code (`:151-154`); ExecApprovalPolicy deny or ask on the code (`:157-165`) | wrapped, but the shell adapters skip it: they read only `command` of `bash`/`powershell` (`tool_guards.py:41, 79-83`) | `sandbox.execute_python(memory_limit_mb=256)` (`:168-170`) |
| `file_editor` | `StrReplaceEditorTool` `weebot/tools/file_editor.py:16` | null byte check (`:88-91`); `PathValidator` (`:95-122`); resolved path must be under `WORKSPACE_ROOT` (`:127-133`); `fs_permissions` rules, `interrupt` fails closed (`:140-161`) | no (not in `GUARDED_TOOLS`, `tool_guards.py:43`) | direct `Path.write_text` / atomic `.tmp` replace (`:178-295`) |

- Sandbox: the three exec tools take a `SandboxPort`; with none they call `create_default_sandbox()` (`weebot/infrastructure/sandbox/factory.py:380`) and, if that fails, log a warning and return an error on every call (`bash_tool.py:122-136, 402-406`; `powershell_tool.py:57-71, 211-215`; `python_tool.py:94-108, 130-134`). The registry injects the container's sandbox (`weebot/tools/tool_registry.py:459, 471-472`).
- Timeouts: `bash` defaults to `ToolConfig.bash_timeout`, floor 1 s, ceiling `max_tool_timeout` or 300 (`bash_tool.py:154-160, 334-345`); `python_execute` the same with `python_timeout` (`python_tool.py:112-115, 136-146`); `powershell` 30 s default, ceiling 300 or `max_tool_timeout`, no floor (`powershell_tool.py:171-175, 203-208`). `bash` and `powershell` declare `default_timeout_seconds = 300` and keep the tail on truncation (`bash_tool.py:55-56`, `powershell_tool.py:27-28`).
- `bash` rewrites a leading `curl` to `curl.exe` on Windows (`bash_tool.py:325-331`) and fires a `post_bash_guard` hook without awaiting it (`:357-376`).
- `powershell` accepts shortcut names (`system_info`, `reset_browser`, ...) that expand to fixed commands before the gates (`powershell_tool.py:75-84, 183`).
- `file_editor` commands: `view`, `create` (refuses to overwrite, `:229-232`), `str_replace` (first match only, `:264`), `insert`, `write_large` (overwrites without the existence check, `:178-193`).
- `SecureOutputFile` (`weebot/tools/secure_output.py:15`): writes to a `mkstemp` file with mode 0o600, `cleanup()` deletes it (`:34-58`). No importer in `weebot/`, `cli/` or `tests/`.
- `ValidationPipeline` (`weebot/tools/validation.py:221`) with `SecurityValidator`, `SafetyValidator`, `BusinessRuleValidator` (`:41-218`) and `validate_tool_call` (`:253`). No importer anywhere; its `file_editor` rule checks a `file_path` param the tool does not have (`:134` vs `file_editor.py:36`).

Consequences (read from source, not run):
- An approved ASK still fails. With the default `enforce` mode, `GuardedTool` sends an ExecApprovalPolicy ASK to a human (`tool_guards.py:171-174, 388-391`); after "yes" it calls the inner tool, which evaluates the same policy again and refuses `requires_confirmation` with no knowledge of the grant (`bash_tool.py:395-399`, `powershell_tool.py:197-200`). No exec tool reads `tool_approval.already_approved` (only `tool_guards.py:401` does). The approval tests use a recorder as the inner tool (`tests/unit/application/services/test_tool_approval.py:182-185`), so they do not catch this.
- `python_execute` never gets an ASK from the chain (the adapters skip it), so code that matches an ALWAYS_ASK rule is refused with no approval route (`python_tool.py:160-165`). `denied_result` tells the agent python_execute "run[s] without approval" (`weebot/application/services/tool_approval.py:271-276`).
- `MAX_TOOL_TIMEOUT` is named in the `bash` description (`bash_tool.py:61`) and in `ToolConfig` (`weebot/config/tool_config.py:27`), but nothing reads it: `tool_config_from_settings` leaves `max_tool_timeout` at 300 (`tool_config.py:59-73`).
- `PowerShellTool` has no `set_config`, and the registry builds it with `sandbox=` only (`tool_registry.py:471-472, 497-498`), so its `tool_config` is always None.
- `powershell` builds a new `ExecApprovalPolicy()` per call (`powershell_tool.py:193`); a base64 decode error in its encoded-content check is ignored with `except Exception: pass` (`:158-159`), the fail-open shape `bash` removed (`bash_tool.py:199-238`).
- `file_editor` writes are not guarded by the chain, and the `webhook` role, which drops `bash`/`powershell`/`python_execute`, keeps `file_editor` (`tool_registry.py:107-144`). Containment is the workspace check above.
- `_wsl_available()` (`bash_tool.py:28-34`) has no caller; `use_wsl=True` picks `shell="bash"` without checking WSL (`:410`).
- Comment says tool-level overrides use `set_config(ToolConfig)` (`file_editor.py:12-13`); `StrReplaceEditorTool` has no `set_config`.

## Connected to
- **Built by** `RoleBasedToolRegistry` (sandbox and `set_config` wiring, `tool_registry.py:459-498`), the MCP server (`weebot/mcp/server.py:384-392`).
- **Gated by** the BashGuard, CommandSecurityAnalyzer and ExecApprovalPolicy cards (`weebot/core/bash_guard.py`, `weebot/tools/bash_security.py`, `weebot/core/approval_policy.py:222, 264-320`); `PathValidator` (`weebot/infrastructure/security/security_validators.py:34`); `load_fs_permission_checker` (`weebot/config/fs_permissions.py:137`).
- **Runs on** the Sandbox card's `SandboxPort`.
- **Looks like but is not:** `validation.py`'s validators (dead) and the guard chain (live).

## If you change this
**Hits:** the `admin`, `coder`, `analyst`, `automation`, `product_manager` roles (`bash`), `admin` only (`powershell`), MCP `bash`/`python` tools. Tests: `tests/unit/tools/test_bash_tool.py`, `tests/unit/tools/test_bash_security_falsifying.py`, `tests/unit/tools/test_python_tool.py`, `tests/unit/tools/test_python_tool_timeout.py`, `tests/unit/tools/test_file_editor.py`, `tests/unit/tools/test_tool_wrappers.py`, `tests/unit/test_fs_permissions.py`, `tests/unit/security/test_security_gates_fail_closed.py`, `tests/unit/test_adversarial_security.py`, `tests/unit/test_audit_findings.py`, `tests/unit/fixes/test_f12_hook_payload.py`, `tests/unit/interfaces/test_mcp_server.py`, `tests/integration/test_security_penetration.py`, `tests/integration/test_website_generation.py`, `tests/e2e/test_portfolio_website.py`, `tests/conftest.py`.
**Does not hit:** `secure_output.py` and `validation.py` (no callers); the guard rules themselves.

## Surfaces
Agent tool calls; MCP `bash`/`python` tools; the approval prompt for ASK verdicts.

## See
`weebot/tools/bash_tool.py`, `weebot/tools/powershell_tool.py`, `weebot/tools/python_tool.py`, `weebot/tools/file_editor.py`
