---
type: object
name: ExecTools
code: BashTool, PowerShellTool, PythonExecuteTool, StrReplaceEditorTool, SecureOutputFile, ValidationPipeline
cluster: tools
universe: live
status: stale
stale_reason: 2026-10-24 remediation moved code these citations point at (tool registry, trust boundary, flow builder, DI); re-verify against source
verified: 2026-10-24
commit: d4ffb555
---

# ExecTools

The tools that run code or write files: `bash`, `powershell`, `python_execute`, `file_editor`. Two more modules sit beside them, `secure_output.py` and `validation.py`, and nothing imports either.

## Why this shape
Each exec tool keeps its own gates inside `execute` and also runs behind `GuardedTool` (see the BaseTool card). The inner gates predate the chain; the chain was added so `powershell` and the MCP server could not skip BashGuard (`weebot/application/services/tool_guards.py:1-9`). Execution goes through a `SandboxPort`, so the tool does not choose how a process is isolated (see the Sandbox card).

## Shape
| Tool (`name`) | Class | Gates inside the tool | Chain (`GuardedTool`) | Runs via |
|---|---|---|---|---|
| `bash` | `BashTool` (`weebot/tools/bash_tool.py:38`) | CommandSecurityAnalyzer DANGEROUS refuses, an analyzer crash refuses (`weebot/tools/bash_tool.py:243-300`); BashGuard BLOCKED refuses (`weebot/tools/bash_tool.py:354, 379-390`); ExecApprovalPolicy deny refuses, ask refuses unless a human approved this call (`weebot/tools/bash_tool.py:392-400`) | yes, all shell adapters (`weebot/application/services/tool_guards.py:41-43`) | `sandbox.execute_shell(shell="powershell" on Windows unless use_wsl, else "bash")` (`weebot/tools/bash_tool.py:409-414`) |
| `powershell` | `PowerShellTool` (`weebot/tools/powershell_tool.py:21`) | regex encoded-command and cmdlet blocklist (`weebot/tools/powershell_tool.py:88-170`); path blocklist (`weebot/tools/powershell_tool.py:105-120`); ExecApprovalPolicy deny refuses, ask refuses unless a human approved (`weebot/tools/powershell_tool.py:193-201`) | yes, all shell adapters | `sandbox.execute_shell(shell="powershell")` (`weebot/tools/powershell_tool.py:218-220`) |
| `python_execute` | `PythonExecuteTool` (`weebot/tools/python_tool.py:28`) | BashGuard BLOCKED on the code (`weebot/tools/python_tool.py:152-155`); ExecApprovalPolicy deny refuses, ask refuses unless a human approved (`weebot/tools/python_tool.py:157-166`) | wrapped; the BashGuard and analyzer adapters skip it (they read only `command` of `bash`/`powershell`, `weebot/application/services/tool_guards.py:41, 79-83`), the policy adapter evaluates its `code` (`weebot/application/services/tool_guards.py:164-176`) | `sandbox.execute_python(memory_limit_mb=256)` (`weebot/tools/python_tool.py:169-171`) |
| `file_editor` | `StrReplaceEditorTool` (`weebot/tools/file_editor.py:16`) | null byte check (`weebot/tools/file_editor.py:88-91`); `PathValidator` (`weebot/tools/file_editor.py:95-122`); resolved path must be under `WORKSPACE_ROOT` (`weebot/tools/file_editor.py:127-133`); `fs_permissions` rules, `interrupt` fails closed (`weebot/tools/file_editor.py:140-161`) | no (not in `GUARDED_TOOLS`, `weebot/application/services/tool_guards.py:43`) | direct `Path.write_text` / atomic `.tmp` replace (`weebot/tools/file_editor.py:178-295`) |

- Sandbox: the three exec tools take a `SandboxPort`; with none they call `create_default_sandbox()` (`weebot/infrastructure/sandbox/factory.py:380`) and, if that fails, log a warning and return an error on every call (`weebot/tools/bash_tool.py:123-137, 403-407`; `weebot/tools/powershell_tool.py:58-72, 212-216`; `weebot/tools/python_tool.py:95-109, 131-135`). The registry injects the container's sandbox (`weebot/tools/tool_registry.py:465, 482-483`).
- Timeouts: `bash` defaults to `ToolConfig.bash_timeout`, floor 1 s, ceiling `max_tool_timeout` or 300 (`weebot/tools/bash_tool.py:155-161, 334-347`); `python_execute` the same with `python_timeout` (`weebot/tools/python_tool.py:113-116, 137-147`); `powershell` 30 s default, ceiling 300 or `max_tool_timeout`, no floor (`weebot/tools/powershell_tool.py:172-176, 203-209`). `bash` and `powershell` declare `default_timeout_seconds = 300` and keep the tail on truncation (`weebot/tools/bash_tool.py:56-57`, `weebot/tools/powershell_tool.py:28-29`).
- `bash` rewrites a leading `curl` to `curl.exe` on Windows (`weebot/tools/bash_tool.py:326-332`) and fires a `post_bash_guard` hook without awaiting it (`weebot/tools/bash_tool.py:357-377`).
- `powershell` accepts shortcut names (`system_info`, `reset_browser`, ...) that expand to fixed commands before the gates (`weebot/tools/powershell_tool.py:76-85, 184`).
- `file_editor` commands: `view`, `create` (refuses to overwrite, `weebot/tools/file_editor.py:229-232`), `str_replace` (first match only, `weebot/tools/file_editor.py:264`), `insert`, `write_large` (overwrites without the existence check, `weebot/tools/file_editor.py:178-193`).
- `SecureOutputFile` (`weebot/tools/secure_output.py:15`): writes to a `mkstemp` file with mode 0o600, `cleanup()` deletes it (`weebot/tools/secure_output.py:34-58`). No importer in `weebot/`, `cli/` or `tests/`.
- `ValidationPipeline` (`weebot/tools/validation.py:221`) with `SecurityValidator`, `SafetyValidator`, `BusinessRuleValidator` (`weebot/tools/validation.py:41-218`) and `validate_tool_call` (`weebot/tools/validation.py:253`). No importer anywhere; its `file_editor` rule checks a `file_path` param the tool does not have (`weebot/tools/validation.py:134` vs `weebot/tools/file_editor.py:36`).

Consequences (read from source, not run):
- An approved ASK runs once. In `enforce` mode `GuardedTool` sends an ExecApprovalPolicy ASK to a human (`weebot/application/services/tool_guards.py:173-176, 428-434`); after "yes" it calls the inner tool inside `human_approved_call` (`weebot/application/services/tool_guards.py:435-438`, `weebot/core/approval.py:143-154`), so the tool's own `requires_confirmation` check lets it through (`weebot/tools/bash_tool.py:396`, `weebot/tools/powershell_tool.py:198`, `weebot/tools/python_tool.py:161`). Called outside `GuardedTool`, the inner tool still refuses an ASK.
- `denied_result` tells the agent that `python_execute` and a script under `Output/` "run without approval" (`weebot/application/services/tool_approval.py:270-275`); the policy adapter can still ASK on `python_execute` code (`weebot/application/services/tool_guards.py:166-167`).
- `MAX_TOOL_TIMEOUT` is named in the `bash` description (`weebot/tools/bash_tool.py:62`) and in `ToolConfig` (`weebot/config/tool_config.py:27`), but nothing reads it: `tool_config_from_settings` leaves `max_tool_timeout` at 300 (`weebot/config/tool_config.py:59-73`).
- `PowerShellTool` has no `set_config`, and the registry builds it with `sandbox=` only (`weebot/tools/tool_registry.py:482-483, 503-504`), so its `tool_config` is always None.
- `powershell` builds a new `ExecApprovalPolicy()` per call (`weebot/tools/powershell_tool.py:194`); a base64 decode error in its encoded-content check is ignored with `except Exception: pass` (`weebot/tools/powershell_tool.py:159-160`), the fail-open shape `bash` removed (`weebot/tools/bash_tool.py:207-239`).
- `file_editor` writes are not guarded by the chain, and the `webhook` role, which drops `bash`/`powershell`/`python_execute`, keeps `file_editor` (`weebot/tools/tool_registry.py:123-162`). Containment is the workspace check above.
- `_wsl_available()` (`weebot/tools/bash_tool.py:29-35`) has no caller; `use_wsl=True` picks `shell="bash"` without checking WSL (`weebot/tools/bash_tool.py:411`).
- Comment says tool-level overrides use `set_config(ToolConfig)` (`weebot/tools/file_editor.py:12-13`); `StrReplaceEditorTool` has no `set_config`.

## Connected to
- **Built by** `RoleBasedToolRegistry` (sandbox and `set_config` wiring, `weebot/tools/tool_registry.py:446-510`), the MCP server, which wraps `bash` and `python_execute` with the egress guard included (`weebot/mcp/server.py:384-392`).
- **Gated by** the BashGuard, CommandSecurityAnalyzer and ExecApprovalPolicy cards (`weebot/core/bash_guard.py`, `weebot/tools/bash_security.py`, `weebot/core/approval_policy.py:222, 264-320`); `PathValidator` (`weebot/infrastructure/security/security_validators.py:34`); `load_fs_permission_checker` (`weebot/application/services/fs_permission_policy.py:33`).
- **Runs on** the Sandbox card's `SandboxPort`.
- **Looks like but is not:** `weebot/tools/validation.py` validators (dead) and the guard chain (live).

## If you change this
**Hits:** the `admin`, `coder`, `analyst`, `automation`, `product_manager` roles (`bash`), `admin`, `coder`, `analyst`, `automation` (`python_execute`), `admin` only (`powershell`), every role but `custom` (`file_editor`), MCP `bash`/`python` tools. Tests: `tests/unit/tools/test_bash_tool.py`, `tests/unit/tools/test_bash_security_falsifying.py`, `tests/unit/tools/test_python_tool.py`, `tests/unit/tools/test_python_tool_timeout.py`, `tests/unit/tools/test_file_editor.py`, `tests/unit/tools/test_tool_wrappers.py`, `tests/unit/test_fs_permissions.py`, `tests/unit/security/test_security_gates_fail_closed.py`, `tests/unit/test_adversarial_security.py`, `tests/unit/test_audit_findings.py`, `tests/unit/fixes/test_f12_hook_payload.py`, `tests/unit/interfaces/test_mcp_server.py`, `tests/integration/test_security_penetration.py`, `tests/integration/test_website_generation.py`, `tests/e2e/test_portfolio_website.py`, `tests/conftest.py`.
**Does not hit:** `secure_output.py` and `validation.py` (no callers); the guard rules themselves.

## Surfaces
Agent tool calls; MCP `bash`/`python` tools; the approval prompt for ASK verdicts.

## See
`weebot/tools/bash_tool.py`, `weebot/tools/powershell_tool.py`, `weebot/tools/python_tool.py`, `weebot/tools/file_editor.py`
