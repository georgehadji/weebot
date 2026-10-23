# processes/ — movements through the code, one card each (Input, Movement, Output; numbered steps citing `path:line`)

- [flow-run-turn](flow-run-turn.md) — one `flow run` turn: CLI, AgentRunner, create_flow, PlanActFlow states from Planning to Completed.
- [tool-call-guard-chain](tool-call-guard-chain.md) — a model's tool call: egress gate, ToolCollection, GuardedTool chain, approval channel, inner tool.
- [model-cascade](model-cascade.md) — CascadeExecutor.call_with_cascade: role and step model choice, hedged probes, fallback, rescue, usage events.
- [session-persistence](session-persistence.md) — save on every emit, restore on resume, cross-process cancel marker.
- [mcp-tool-loading](mcp-tool-loading.md) — config/mcp_servers.json to guarded `mcp__*` tools in the flow's collection.
