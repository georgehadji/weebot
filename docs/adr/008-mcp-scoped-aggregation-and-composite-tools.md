# ADR-008: MCP Scoped Aggregation & Composite Tools

**Date:** 2026-07-03
**Status:** Approved
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

weebot's MCP bridge registered every external MCP tool into the agent's
context at startup.  With a handful of external servers the context could
exceed 50 tools, far past the point where small-model tool-selection accuracy
collapses (the literature shows degradation above 10–15 tools).  At the same
time, the MCP surface exposed low-level atomic tools that forced external LLM
clients to reason about multi-step workflows themselves, and the monolithic
``file_editor`` tool had an undifferentiated schema that hurt selection
accuracy.

This ADR records the decisions that address those problems while preserving
backward compatibility for existing MCP clients.

---

## Decision

### 1. Per-request scoped retrieval for external MCP tools (H1)

Instead of registering all external MCP tools permanently, we:

1. Index external tool descriptions with local embeddings at bridge
   initialization.
2. At the start of each ``PlanActFlow.run()``, call
   ``MCPToolRegistryBridge.scope_for_query(prompt)``.
3. The retrieval service removes the previous scoped subset from the shared
   ``RoleBasedToolRegistry`` and adds only the top-``k`` relevant tools
   (default ``MCP_DEFAULT_SCOPE_K = 8``).
4. PlanActFlow rebuilds its ``ToolCollection`` from the same registry and
   pushes it into ``ExecutorAgent`` via ``set_tools()``.

The same ``RoleBasedToolRegistry`` instance is shared between the MCP bridge
and PlanActFlow through the DI container's ``tool_registry`` singleton.  This
keeps a single source of truth and avoids drift between the bridge's view and
 the agent's view.

### 2. Composite workflow tools (H2)

Common multi-step workflows are exposed as single MCP tools:

- ``analyze_and_edit`` — file view → syntax check → targeted replace.
- ``research_and_summarize`` — web search → result processing.

Composites are declared in ``weebot/mcp/composite_tools.py`` and executed by
``CompositeToolExecutor`` through a dispatcher of atomic handlers.  Atomic
tools covered by a composite are hidden from ``list_tools`` when
``mcp_composite_tools_enabled`` is true, but remain callable internally.

Composite results use ``aborted_after_failure`` (not ``rollback_performed``)
to indicate when an ``all_or_none`` workflow stopped after a failed step.

### 3. Decompose ``file_editor`` on the MCP surface (H3)

The single ``file_editor`` tool is replaced by four focused MCP tools:

- ``file_view``
- ``file_create``
- ``file_str_replace``
- ``file_insert``

The underlying ``StrReplaceEditorTool`` is unchanged; the MCP server maps each
tool to the appropriate ``command`` value.  The legacy ``file_editor`` tool is
still registered with a ``DEPRECATED`` description so older clients keep
working.

### 4. Maintain a tool-count budget

The maintained target is **≤ 12 tools per turn** in the agent context.
Scoped retrieval keeps external MCP contributions to ≤ 8; native tool budget
is managed separately and may be scoped in a future phase.

### 5. Backward compatibility

- ``mcp_scoped_aggregation`` (default ``true``) can be set to ``false`` to
  restore the old "register all external tools" behavior.
- ``mcp_composite_tools_enabled`` (default ``true``) can be set to ``false``
  to expose all atomic tools.
- ``file_editor`` remains callable for legacy clients.

---

## Consequences

### Positive

- Agent tool context stays within the accuracy budget even with many external
  MCP servers.
- External LLM clients see higher-level, easier-to-use composite tools.
- Decomposed file tools have precise schemas and descriptions, improving
  selection accuracy.
- A single shared registry removes duplication between the MCP bridge and the
  agent flow.

### Negative

- Scoped retrieval can miss a relevant tool; the escape hatches
  (``mcp_scoped_aggregation=false`` and the bridge's fallback when no
  retrieval service is wired) mitigate this.
- Native tools are not yet scoped, so the total may still exceed the budget
  until a future phase addresses native-tool scoping.
- Composite tools require careful maintenance of the dispatcher mapping and
  the ``hidden_atomic_tools`` lists.

---

## Related

- ``docs/plans/MCP_HIGH_PROBABILITY_ENHANCEMENT_PLAN.md`` — full enhancement plan
- ``weebot/application/di/_factories.py`` — ``_create_tool_registry``, ``_create_mcp_bridge``
- ``weebot/application/flows/plan_act_flow.py`` — ``_apply_mcp_tool_scope``
- ``weebot/application/agents/executor/_base.py`` — ``ExecutorAgent.set_tools``
- ``weebot/application/services/mcp_tool_registry_bridge.py`` — ``scope_for_query``
- ``weebot/infrastructure/adapters/composite_tool_executor.py`` — composite execution
- ``weebot/mcp/composite_tools.py`` — composite specifications
- ``weebot/mcp/server.py`` — decomposed file tools and structured errors

---

## Evolution (Phase 2)

After the initial ADR was approved, three new components were introduced to make
scoping safer and to raise the abstraction level of the MCP surface.

### ``CompositeToolBuilder``

``weebot/application/services/composite_tool_builder.py`` packages atomic
handlers into FastMCP-compatible composite tools. It builds a dynamic
``inspect.Signature`` from the runtime arguments referenced by
``${var_name}`` templates inside a ``CompositeToolSpec``, and delegates
execution to a ``CompositeExecutorLike`` callable. This keeps the MCP server's
top-level surface small without losing the atomic tools that composites use
internally.

### ``NativeToolRetrievalService``

``weebot/application/services/native_tool_retrieval_service.py`` provides
semantic scoping for *native* Weebot tools. It indexes native tools as
``MCPToolInfo`` objects (with ``server_name="native"``) and retrieves the
top-``k`` relevant names for a query. This is the mechanism behind the
``mcp_scope_native_tools`` setting that keeps the total per-turn tool count
within the ≤ 12 budget.

### Non-mutating scoping decision

``MCPToolRegistryBridge.select_for_query()`` is now the preferred path used by
``PlanActFlow``. It returns the scoped subset of external MCP tool names
without modifying the shared ``RoleBasedToolRegistry``. The legacy
``scope_for_query()`` method still exists for backward compatibility but is
deprecated: it mutates the registry and emits a ``DeprecationWarning``.
