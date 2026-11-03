---
type: object
name: ToolArgCoercion
code: coerce_args, Coercion, Deny, ToolCall, MiddlewareChain
cluster: application
universe: live
status: stub
---

# ToolArgCoercion

Fits a tool call's arguments to the tool's own parameter schema, then lets middleware rewrite or deny the call and rewrite its result.

## Why this shape
Models send `"3"` for an integer or `"[1, 2]"` for an array. A pure function over the JSON schema fixes the type without a model call, and it is logged, so a tool that keeps getting coerced input is visible. Middleware is the existing interception mechanism; it gains two hooks instead of a second one.

## Shape
- `coerce_args(schema, args)` returns the fitted dict and a tuple of `Coercion(path, rule, before, after)`. Rules: string to int, number or bool; JSON string or scalar to array; JSON string to object; null optional dropped; enum matched ignoring case. Required fields are never invented; a value that does not parse is passed through for the tool to reject (`weebot/application/services/tool_arg_coercion.py`).
- `Middleware.before_tool_call(call)` returns a `ToolCall` or `Deny`; `transform_tool_result(call, result)` returns a result (`weebot/application/middleware/base.py`).
- `MiddlewareChain.apply_before_tool_call` stops at the first `Deny`; `apply_transform_tool_result` runs every middleware in order (`weebot/application/middleware/chain.py`).

## Connected to
Called from `ToolExecutor.execute_tool` after name resolution and before the egress checks, so every guard sees the coerced arguments; coercions go to `ToolResult.metadata["coerced"]` (`weebot/application/agents/executor/_tool_executor.py`). The chain is the executor's `middleware_chain` (`weebot/application/agents/executor/_base.py`). Looks like but is not `repair_json_string` (`weebot/application/services/tool_call_repair.py`), which fixes JSON syntax and tool names, not types, and not `after_tool_call`, which sees the result as a `ToolCallResult` after the batch runner.

## If you change this
**Hits:** every tool call's arguments, the egress and approval checks that read them, tool results' metadata.
**Does not hit:** the LLM-side `before_request` and `after_response` hooks, tool schemas.

## Surfaces
Every executor tool call. `Container._spillover_kwargs` builds the one production `MiddlewareChain` (spillover, H7); diagnostics (H20) is the next planned member.

## See
`tasks/specs/hermes_v022_parity_implementation_plan.md` (H16)
