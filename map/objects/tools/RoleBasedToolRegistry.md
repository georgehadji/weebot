---
type: object
name: RoleBasedToolRegistry
code: RoleBasedToolRegistry
cluster: tools
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# RoleBasedToolRegistry

Maps an agent role (`admin`, `coder`, `webhook`, ...) to the names of the tools it may use, and builds a `ToolCollection` of tool instances for a role or an explicit list of names. It is the coarse access control for tools; the guards run later, per call.

## Why this shape
A name table is the simplest whitelist: a role gets exactly the listed tools. Names must equal `BaseTool.name` (`weebot/tools/tool_registry.py:21-23`). Construction is centralised here because several tools need special wiring (an LLM port, a flow factory, a shared browser, a sandbox) that the caller should not repeat (`:520-617`).

## Shape
- `DEFAULT_ROLE_MAPPINGS`: 12 roles (`:27-165`). `admin` has every normal tool; `webhook` is `admin` minus `bash`, `powershell`, `python_execute` and `terminate`, "webhooks should not exec arbitrary code by default" (`:107-144`); `custom` has none.
- `__init__(role_mappings=None, wiring=None)`: copies the given table, else `DEFAULT_ROLE_MAPPINGS`, list by list (W5.5, F33). `wiring` is a callable returning the collaborators every collection gets; the DI container's `tool_registry` carries `Container.tool_wiring`.
- Role methods: `get_tools_for_role` (raises `ValueError` for an unknown role), `add_role`, `add_tool_to_role`, `remove_tool_from_role`, `validate_tool_for_role`, `list_roles`, `list_all_tools` (`:221-310`).
- `build_tool_class_map` (`:382-432`): walks `weebot.tools`, imports each module, instantiates each `BaseTool` subclass with no arguments to read its `name`, caches the map on the class; errors are skipped.
- `create_tool_collection(role, ...)` and `create_tool_collection_from_names(names, ...)` (`:469-617`): per-name wiring. LLM port for `browser_navigator` and `mixture_of_agents`; flow factory for `debate`, `swarm`, `dispatch_parallel_tasks`, `workflow_orchestrator`; one shared `PlaywrightAdapter` for `advanced_browser` and `browser_inspector`; the sandbox for `bash`, `powershell`, `python_execute`; `set_config` and `set_rerank` when a tool has them. Unknown names are logged and skipped (`:615-616`). Since 2026-10-22 (plan W3.2) the returned collection holds `bash`, `powershell` and `python_execute` as `GuardedTool` decorators (`application/services/tool_guards.py`); the wrapped tool is `.inner`.

Consequences (read from source, not run):
- Fixed 2026-10-23 (W5.5, F32): the `allowed_roles` autodiscovery could never take effect; it is deleted with the unenforced `BaseTool.allowed_roles` field. `DEFAULT_ROLE_MAPPINGS` is the one role table.
- If that branch did work, it would replace the whole default table with the eight roles `image_search` names, and add every "universal" tool (including `bash`, `powershell`, `python_execute`, `terminate`) to each; `admin` and `webhook` would disappear (`:463-467`).
- Fixed 2026-10-23 (W5.5, F33): role lists are copied per instance, so `add_tool_to_role` on one registry no longer reaches another.
- Fixed 2026-10-23 (W5.5, F34): the capability tiers were written (the MCP bridge set them) but never enforced. Wiring the gate as written would have removed `terminate` from every role and `bash` from background runs, so the tiers, `CapabilityGate` and `CapabilityTier` are deleted; the guard chain gates execution.
- Each flow-factory tool, each state-repo lookup and each tool with `set_rerank` builds a new `Container()` and runs `configure_defaults()` (`:548-549, 571-573, 607-609`), inside `except Exception: pass` (`:553-554, 574-575, 612-613`). On failure the tool silently gets `flow_factory=None` or no reranker, and what it does get comes from a throwaway container, not the application's.
- Discovery instantiates every tool class with no arguments (`:420`); a constructor with side effects runs them there, and a tool that fails to import or construct drops out with only a debug log (`:424-427`). Duplicate names: first one wins (`:422-423`).
- The DI container calls this the "single source of truth" (`application/di/_factories.py:430-438`), yet it is also built directly at `di/__init__.py:433, 581` and `cli/commands/agents.py:175`.

## Connected to
- **Built by** `FactoriesMixin._create_tool_registry` (above) and the three direct sites. **Used by** `ToolAssembler` (`application/flows/collaborators/tool_assembler.py:12`), the MCP scope logic (`application/flows/mcp_scope.py:84`), `di/_agent_tools.py:49`, `application/services/cron_agent_runner.py:78, 86`, and the MCP bridge adapter (`di/_factories.py:379-386`).
- **Related:** `BaseTool` and `ToolCollection` (`weebot/tools/base.py`), the `Sandbox` card, `CapabilityGate` (`application/services/capability_gate.py`, only referenced here under `TYPE_CHECKING`).
- **Looks like but is not:** the guards (`BashGuard`, `ExecApprovalPolicy`, `EgressGuard`) which act on each call; the MCP server's own tool list (`weebot/mcp/server.py`), built separately.

## If you change this
**Hits:** which tools every role can call (including the `webhook` exec exclusion), every flow's tool set, cron jobs, MCP scoped retrieval, tests `tests/unit/tools/test_tool_registry.py`, `tests/unit/test_berb_tool.py`, `tests/unit/application/di/test_mcp_di_factories.py`, `tests/integration/test_mcp_scoped_retrieval.py`, `tests/integration/test_mcp_tool_budget.py`.
**Does not hit:** guard rules; the sandbox; individual tool behaviour.

## Surfaces
`python -m cli.main agents ...` (`cli/commands/agents.py:168-175`); the tool list each agent role sees.

## See
`weebot/tools/tool_registry.py`
