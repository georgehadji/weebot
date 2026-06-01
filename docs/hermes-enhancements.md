# Weebot: Hermes-Agent Enhancements

> Implemented from the [nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent) research (175k ★).
> Eight production-grade patterns ported into weebot's clean architecture.

---

## Summary

| # | Enhancement | New Files | Modified Files | Impact |
|---|-------------|-----------|----------------|--------|
| 5 | Tool Output Size Limits | — | `tools/base.py`, `config/constants.py` | Medium |
| 8 | Error Classifier | `core/error_classifier.py` | `infrastructure/adapters/llm/resilient_adapter.py` | Medium |
| 1 | Token Tracking + Auto-Compress | `application/services/conversation_compressor.py` | `application/agents/executor.py` | High |
| 2 | StepBudget with Refund | `application/services/step_budget.py` | `executor.py`, `flows/plan_act_flow.py`, `di.py` | Medium-High |
| 4 | Persistent Cross-Session Memory | `tools/persistent_memory.py` | `tools/tool_registry.py`, `executor.py` | Medium-High |
| 3 | Mixture-of-Agents (MoA) Tool | `tools/mixture_of_agents.py` | `tools/tool_registry.py` | High |
| 6 | Trajectory Exporter | `application/services/trajectory_exporter.py` | `cli/main.py` | Medium |
| 7 | Background Skill Curator | `application/services/skill_curator.py` | `application/di.py` | Low-Medium |

---

## Enhancement #5 — Tool Output Size Limits

**Problem:** Browser, bash, and web-search tools can return unlimited output, consuming the entire context window in a single tool call.

**Solution:** `ToolCollection.execute()` truncates results exceeding `MAX_TOOL_OUTPUT_CHARS = 20_000` chars and records `metadata["truncated"]` and `metadata["original_length"]` for observability.

**Files:**
- `weebot/config/constants.py` — `MAX_TOOL_OUTPUT_CHARS`, `SUBAGENT_MAX_STEPS`
- `weebot/tools/base.py` — truncation guard after `result.metadata.update({...})`

---

## Enhancement #8 — Error Classifier

**Problem:** `ResilientLLMAdapter._is_retryable_error()` used a flat string-pattern list that retried auth errors (pointless) and context-length errors (should compress, not retry).

**Solution:** `ErrorClassifier` maps exceptions to `ErrorCategory` enum via regex patterns. Auth → fail fast. Context-length → do not retry (compressor handles it). Rate-limit/network → retry as before.

**Files:**
- `weebot/core/error_classifier.py` — new `ErrorClassifier` + `ErrorCategory`
- `weebot/infrastructure/adapters/llm/resilient_adapter.py` — replace `_is_retryable_error()`, add auth fast-fail guard

---

## Enhancement #1 — Real Token Tracking + Auto-Compress

**Problem:** `LLMResponse.usage` already carries real `prompt_tokens`/`completion_tokens` from every API call, but nothing reads or accumulates them. `TokenBudgetMonitor.should_compact()` fires warnings but nothing compresses.

**Solution:**
1. `ExecutorAgent._track_usage_and_maybe_compress()` accumulates real token counts after every LLM call
2. `_maybe_compress()` fires `ConversationCompressor` at 75% of the context window
3. `ConversationCompressor` protects first 3 and last 6 turns; summarizes the middle via a cheap-model call (defaults to `MODEL_BUDGET`)

**Files:**
- `weebot/application/services/conversation_compressor.py` — new service
- `weebot/application/agents/executor.py` — new init params, `_track_usage_and_maybe_compress()`, `_maybe_compress()`, `token_usage` property

---

## Enhancement #2 — Thread-safe StepBudget with Refund

**Problem:** `ExecutorAgent.execute_step()` used `for _ in range(self._max_steps)` — not thread-safe, no refund mechanism. Sub-agents from `DispatchAgentsTool` had the same 25-step budget as the parent.

**Solution:** `StepBudget(max_steps)` replaces the loop. Thread-safe via `threading.Lock`. `refund()` gives steps back when `terminate` is called early. Sub-agents get `SUBAGENT_MAX_STEPS = 15` via `PlanActFlow(max_steps=...)`.

**Files:**
- `weebot/application/services/step_budget.py` — new `StepBudget` class
- `weebot/config/constants.py` — `SUBAGENT_MAX_STEPS = 15`
- `weebot/application/agents/executor.py` — wires `StepBudget`, replaces loop, adds terminate refund
- `weebot/application/flows/plan_act_flow.py` — accepts `max_steps` kwarg
- `weebot/application/di.py` — passes `SUBAGENT_MAX_STEPS` to sub-agent flows

---

## Enhancement #4 — Persistent Cross-Session Memory

**Problem:** `ExecutorAgent._facts` dict is session-scoped — lost when the session ends. The agent has no memory of what it learned in previous sessions.

**Solution:** `PersistentMemoryTool` writes `§`-delimited entries to `~/.weebot/memory/AGENT.md` and `USER.md`. A frozen snapshot is injected into the system prompt at the start of each `execute_step()` call, preserving the LLM's prefix cache. Mid-session writes are durable but don't change the in-flight prompt.

Entries are scanned for prompt injection patterns (`<INST>`, `[INST]`, `SYSTEM:`, etc.) before write.

**Usage:**
```
Use the persistent_memory tool with action=add/replace/remove/read and file=agent or user.
```

**Files:**
- `weebot/tools/persistent_memory.py` — new `PersistentMemoryTool`
- `weebot/tools/tool_registry.py` — registered under `admin` role
- `weebot/application/agents/executor.py` — `load_snapshot()` injected into system prompt

---

## Enhancement #3 — Mixture-of-Agents (MoA) Tool

**Problem:** Hard tasks (complex reasoning, math, security review) are bottlenecked by a single model's perspective and blind spots.

**Solution:** `MixtureOfAgentsTool` implements the [Wang et al. 2024 MoA paper](https://arxiv.org/abs/2406.04692):
1. 4 reference models called in parallel via OpenRouter (`asyncio.gather`)
2. Aggregator model synthesizes the best combined answer
3. Falls back to longest individual response if aggregator fails

Uses existing `OPENROUTER_API_KEY` and `OpenAIAdapter` — no new dependencies.

**Default reference models:** `openai/gpt-4o-mini`, `anthropic/claude-3-5-haiku`, `google/gemini-flash-1.5`, `meta-llama/llama-3.3-70b-instruct`
**Default aggregator:** `anthropic/claude-sonnet-4.6`

**Files:**
- `weebot/tools/mixture_of_agents.py` — new `MixtureOfAgentsTool`
- `weebot/tools/tool_registry.py` — registered under `admin` role

---

## Enhancement #6 — Trajectory Exporter

**Problem:** Session events are stored in SQLite but there is no way to extract them for analysis, debugging, or fine-tuning dataset creation.

**Solution:** `TrajectoryExporter` serializes `AgentEvent` objects from SQLite to JSONL (one event per line). Optional `compress_to_budget` triggers `ConversationCompressor` before export to fit within a token limit.

**CLI:**
```bash
python -m cli.main flow export <session_id> [--output path.jsonl] [--compress 32000]
python -m cli.main flow export <session_id>  # → <session_id>.jsonl
```

**Files:**
- `weebot/application/services/trajectory_exporter.py` — new `TrajectoryExporter`
- `cli/main.py` — `flow export` command

---

## Enhancement #7 — Background Skill Curator

**Problem:** Skills accumulate and are never reviewed. Stale, obsolete skills stay active and pollute the skill registry indefinitely.

**Solution:** `SkillCurator` classifies skills by age of last `EvolutionEntry` and LLM-reviews stale/archive-candidate ones. Recommendations (`ARCHIVE`/`PIN`/`KEEP`) are appended to `skill.evolution_log`. Registered as a weekly Sunday 02:00 APScheduler cron job.

**Classification thresholds:**
- `active` — last touched < 30 days ago
- `stale` — 30–90 days (LLM-reviewed)
- `archive-candidate` — 90+ days (LLM-reviewed)

**Invariants:** Never deletes skills. Only appends to `evolution_log`. Uses cheap model to keep cost negligible.

**Activation:**
```python
container.configure_defaults()
container.configure_skill_curator()
await container.register_curator_job()
```

**Files:**
- `weebot/application/services/skill_curator.py` — new `SkillCurator`
- `weebot/application/di.py` — `configure_skill_curator()`, `_create_skill_curator()`, `register_curator_job()`

---

## Verification

```bash
# Unit checks
pytest tests/ -v --cov=weebot --cov-report=term-missing

# #5 Tool output limits
python -c "
from weebot.tools.base import ToolResult, ToolCollection, BaseTool
from pydantic import ConfigDict
import asyncio
class Big(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = 'big'; description: str = 'test'; parameters: dict = {'type':'object','properties':{}}
    async def execute(self, **kw): return ToolResult(output='A'*25000)
async def t():
    r = await ToolCollection(Big()).execute('big')
    assert r.metadata['truncated']; print('OK - truncated to', len(r.output))
asyncio.run(t())
"

# #8 Error classifier
python -c "
from weebot.core.error_classifier import ErrorClassifier, ErrorCategory
assert ErrorClassifier.classify(Exception('rate limit 429')) == ErrorCategory.RATE_LIMIT
assert ErrorClassifier.should_fail_fast(Exception('invalid api key'))
print('OK')
"

# #2 StepBudget
python -c "
from weebot.application.services.step_budget import StepBudget
b = StepBudget(3); b.consume(); b.consume(); b.consume()
assert not b.consume(); b.refund(); assert b.consume(); print('OK')
"

# #3 MoA (requires OPENROUTER_API_KEY)
python -c "
import asyncio; from weebot.tools.mixture_of_agents import MixtureOfAgentsTool
r = asyncio.run(MixtureOfAgentsTool().execute(query='What is 2+2?'))
print(r.data.get('successful_count'), r.output[:80])
"

# #6 Trajectory export
python -m cli.main flow list
python -m cli.main flow export <session_id> --output /tmp/test.jsonl
python -c "import json; lines=[json.loads(l) for l in open('/tmp/test.jsonl')]; print(len(lines), 'events')"
```
