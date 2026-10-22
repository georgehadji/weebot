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
- `_TOOL_TIERS`: capability tier per tool (`public` default; `bash` and `powershell` restricted, `python_execute` controlled, `computer_use` and `terminate` privileged) (`:172-191`).
- `__init__(role_mappings=None)`: use the given table, else try the autodiscovered one, else copy the defaults (`:193-210`).
- Role methods: `get_tools_for_role` (raises `ValueError` for an unknown role), `add_role`, `add_tool_to_role`, `remove_tool_from_role`, `validate_tool_for_role`, `list_roles`, `list_all_tools` (`:221-310`).
- `build_tool_class_map` (`:382-432`): walks `weebot.tools`, imports each module, instantiates each `BaseTool` subclass with no arguments to read its `name`, caches the map on the class; errors are skipped.
- `create_tool_collection(role, ...)` and `create_tool_collection_from_names(names, ...)` (`:469-617`): per-name wiring. LLM port for `browser_navigator` and `mixture_of_agents`; flow factory for `debate`, `swarm`, `dispatch_parallel_tasks`, `workflow_orchestrator`; one shared `PlaywrightAdapter` for `advanced_browser` and `browser_inspector`; the sandbox for `bash`, `powershell`, `python_execute`; `set_config` and `set_rerank` when a tool has them. Unknown names are logged and skipped (`:615-616`). Since 2026-10-22 (plan W3.2) the returned collection holds `bash`, `powershell` and `python_execute` as `GuardedTool` decorators (`application/services/tool_guards.py`); the wrapped tool is `.inner`.

Consequences (read from source, not run):
- **The autodiscovery branch cannot take effect.** `_build_role_mappings_from_class_map` reads `allowed_roles` with `getattr(tool_class, "allowed_roles", ["*"])` (`:452`), but `BaseTool` is a Pydantic model and `allowed_roles` is a field (`weebot/domain/models/base_tool.py:20, 34`). Pydantic v2 does not leave field defaults as class attributes, so the fallback `["*"]` comes back for every tool, every tool counts as universal, the result is empty (`:459-461`) and the defaults are used. The one tool that declares roles, `image_search` (`weebot/tools/image_search.py:87-96`), is therefore ignored. Needs a run to confirm.
- If that branch did work, it would replace the whole default table with the eight roles `image_search` names, and add every "universal" tool (including `bash`, `powershell`, `python_execute`, `terminate`) to each; `admin` and `webhook` would disappear (`:463-467`).
- Shared mutable state: the defaults are copied with a shallow `dict(...)` (`:209`), and `add_tool_to_role` / `remove_tool_from_role` change the inner lists in place (`:265, 282`), which are the class constant's lists. A tool added through one registry shows up in every registry built afterwards. `_TOOL_TIERS` is a class-level dict that `set_tool_tier` mutates (`:323-330`). The MCP registration adapter forwards add and remove calls here (`tests/unit/infrastructure/adapters/test_mcp_tool_registry_adapter.py:42-64`).
- The tier machinery is not used: `get_tools_for_role_with_gate` and `get_tool_tier` have no caller outside this class (grep, 2026-10-21), so the tiers never filter a role's tools through this path.
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
