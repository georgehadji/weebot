---
type: object
name: RoleBasedToolRegistry
code: RoleBasedToolRegistry
cluster: tools
universe: live
status: verified
verified: 2026-10-27
commit: ae284495
---

# RoleBasedToolRegistry

Maps an agent role (`admin`, `coder`, `webhook`, ...) to the names of the tools it may use, and builds a `ToolCollection` of tool instances for a role or an explicit list of names. It is the coarse access control for tools; the guards run later, per call. It lives in `weebot/application/services/tool_registry.py`; `weebot/tools/tool_registry.py` is a re-export shim for old import paths (`:1-9`).

## Why this shape
A name table is the simplest whitelist: a role gets exactly the listed tools. Names must equal `BaseTool.name` (`weebot/application/services/tool_registry.py:20-21`). Construction is centralised here because several tools need special wiring (an LLM port, a flow factory, a shared browser, a sandbox, constructor collaborators) that the caller should not repeat (`:413-534`).

## Shape
- `DEFAULT_ROLE_MAPPINGS`: 12 roles (`:27-185`). `admin` has every normal tool (`:73-122`); `webhook` is admin-level minus `bash`, `powershell`, `python_execute`, `terminate`, `spacescraper`, `computer_use` and `design_system`, "webhooks should not exec arbitrary code by default" (`:123-162`); `custom` has none (`:184`).
- `__init__(role_mappings=None, wiring=None)` (`:190-213`): copies the given table, else `DEFAULT_ROLE_MAPPINGS`, list by list (`:209-212`). `wiring` is a zero-argument callable returning the collaborators every collection gets (`:202-206`); the DI container's `tool_registry` passes `Container.tool_wiring` (`weebot/application/di/_factories.py:467-478`), which returns `state_repo`, `rerank`, `tool_config`, a `browser_factory` and per-tool constructor kwargs for `ocr`, `audit_session`, `knowledge`, `product`, `video_ingest`, `voice_input`, `voice_output`, `persistent_memory` (`:460-502`).
- Role methods: `get_tools_for_role` (raises `ValueError` for an unknown role, `weebot/application/services/tool_registry.py:215-233`), `add_role`, `add_tool_to_role`, `remove_tool_from_role`, `validate_tool_for_role`, `list_roles`, `list_all_tools`, `get_registry_summary` (`:235-315`).
- `build_tool_class_map` (`:321-375`): walks `weebot.tools`, imports each module, reads each `BaseTool` subclass's `name` field default (instantiating with no arguments only when there is none, `:357-364`), caches the map on the class; errors are skipped (`:367-370`).
- `create_tool_collection(role, ...)` (`:377-411`) and `create_tool_collection_from_names(names, ...)` (`:413-534`): arguments a caller passes win over `wiring()` (`:446-452`). Per name: wired constructor kwargs, and a tool whose construction fails is skipped (`:473-478`); LLM port for `browser_navigator` and `mixture_of_agents`; flow factory for `debate`, `dispatch_parallel_tasks`, `workflow_orchestrator`, and for `swarm` together with its `decompose` / `synthesize` callables (`:483-497`); one browser from `wiring["browser_factory"]`, shared by `advanced_browser` and `browser_inspector`, skipped when none is wired (`:498-506`); the sandbox for `bash`, `powershell`, `python_execute` (`:457-482`); `set_config` and `set_rerank` when a tool has them (`:518-524`). Unknown names are logged and skipped (`:526-527`). The returned collection holds `bash`, `powershell`, `python_execute` and financial/outbound tools as `GuardedTool` decorators, without the egress guard (`:528-534`); the wrapped tool is `.inner` (see the BaseTool card).

Consequences (read from source, not run):
- A tool with no `name` default is instantiated with no arguments during discovery (`:361-364`); a tool that fails to import or construct drops out with only a debug log or silently (`:367-370`). Duplicate names: first one wins (`:365-366`). Discovery still walks `weebot.tools` (`:341-345`), so application keeps one edge into the tools package.
- A tool in `collaborators` whose collaborator does not resolve is left out of the wiring (`weebot/application/di/_factories.py:518-521`) and then built with no arguments (`weebot/application/services/tool_registry.py:507-517`); if that fails it is skipped with a debug log.
- The DI container calls its registry the "single source of truth" (`weebot/application/di/_factories.py:468`), yet registries are also built at `weebot/application/di/__init__.py:516, 653` (wired) and unwired at `cli/commands/agents.py:175`, `weebot/application/services/mcp_tool_registry_bridge.py:87`, `weebot/application/di/_factories.py:198` (handed to `ToolDiscoveryAdapter`, which takes the registry by constructor, `weebot/infrastructure/adapters/tool_discovery.py:188`) and the fallback in `weebot/interfaces/factories.py:297`.

## Connected to
- **Built by** `FactoriesMixin._create_tool_registry` (above) and the direct sites. **Used by** `ToolAssembler` (`weebot/application/flows/collaborators/tool_assembler.py:12, 24-31`), the MCP scope logic via `scope_config.registry` (`weebot/application/flows/mcp_scope.py:37`), `weebot/application/di/_agent_tools.py:46`, `weebot/application/services/cron_agent_runner.py:78-90`, and the MCP bridge adapter (`weebot/application/di/_factories.py:425`).
- **Related:** `BaseTool` and `ToolCollection` (BaseTool card), the `Sandbox` card, `guard_tools` (`weebot/application/services/tool_guards.py:507`).
- **Looks like but is not:** the guards (`BashGuard`, `ExecApprovalPolicy`, `EgressGuard`) which act on each call; the MCP server's own tool list (`weebot/mcp/server.py`), built separately.

## If you change this
**Hits:** which tools every role can call (including the `webhook` exec exclusion), every flow's tool set, cron jobs, MCP scoped retrieval, tests `tests/unit/tools/test_tool_registry.py`, `tests/unit/test_berb_tool.py`, `tests/unit/application/di/test_mcp_di_factories.py`, `tests/integration/test_mcp_scoped_retrieval.py`, `tests/integration/test_mcp_tool_budget.py`.
**Does not hit:** guard rules; the sandbox; individual tool behaviour.

## Surfaces
`python -m cli.main agents pack apply` (`cli/commands/agents.py:162-175`); the tool list each agent role sees.

## See
`weebot/application/services/tool_registry.py`
