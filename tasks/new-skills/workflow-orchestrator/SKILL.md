---
name: workflow-orchestrator
description: "Use when chaining multiple tasks into an automated pipeline. Trigger: workflow, pipeline, chain tasks, automate sequence, batch process, orchestrate."
license: MIT
---
# Workflow Orchestrator

## When to use
Chain multiple tasks into a single automated pipeline with dependencies and error handling.

## Workflow
1. **Define steps** — list tasks in order with inputs and outputs for each.
2. **Check dependencies** — confirm each step's inputs exist before starting.
3. **Execute sequentially** — run each step, capturing output for the next.
4. **Handle errors** — if a step fails, log the error and offer to retry, skip, or abort.
5. **Report** — summary per step: status, duration, output location.

## Output
Pipeline execution report with per-step status and final output.