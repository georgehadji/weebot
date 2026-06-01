# Weebot: Hermes-Agent Enhancement Plan

> **Context:** After researching [nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent) (175k ★), eight production-grade patterns were identified that weebot is missing or has only partially implemented. This plan details concrete, in-order implementation of all eight enhancements. The final document will also be written to `docs/hermes-enhancements.md`.

---

## Why

Hermes-agent is a mature, battle-tested agent framework. Adopting its patterns gives weebot:

- **Real context awareness** — stop estimating tokens, track real usage and auto-compress before hitting limits
- **Bounded sub-agent execution** — thread-safe per-agent step budgets with refund prevent runaway flows
- **Multi-model ensemble reasoning** — Mixture-of-Agents produces superior results on hard tasks
- **Cross-session knowledge** — persistent memory survives between sessions
- **Tool output sanity** — oversized tool results no longer flood the context window
- **Training data** — exportable session trajectories for fine-tuning
- **Skill lifecycle management** — automated curation prevents skill rot
- **Smarter error recovery** — classify errors to decide between retry, fallback, compress, or fail-fast

---

## Build Order (dependency-driven)

```
#5 Tool Output Limits       ← standalone, touches 2 files
  ↓
#8 Error Classifier         ← standalone utility, needed by #1
  ↓
#1 Token Tracking + Compress ← depends on #8 for routing
  ↓
#2 StepBudget              ← depends on #1's executor changes
  ↓
#4 Persistent Memory       ← parallel with #3 after #1
#3 Mixture-of-Agents       ← parallel with #4 after #1
  ↓
#6 Trajectory Exporter     ← reuses ConversationCompressor from #1
  ↓
#7 Skill Curator           ← lowest priority, reuses cheap-LLM pattern from #1
```

---

## Files Created (7 new)

| File | Enhancement |
|------|-------------|
| `weebot/core/error_classifier.py` | #8 |
| `weebot/application/services/conversation_compressor.py` | #1 |
| `weebot/application/services/step_budget.py` | #2 |
| `weebot/tools/persistent_memory.py` | #4 |
| `weebot/tools/mixture_of_agents.py` | #3 |
| `weebot/application/services/trajectory_exporter.py` | #6 |
| `weebot/application/services/skill_curator.py` | #7 |

## Files Modified (7 existing)

| File | What Changes |
|------|-------------|
| `weebot/config/constants.py` | Add `MAX_TOOL_OUTPUT_CHARS = 20_000`, `SUBAGENT_MAX_STEPS = 15` |
| `weebot/tools/base.py` | Truncation guard in `ToolCollection.execute()` |
| `weebot/infrastructure/adapters/llm/resilient_adapter.py` | Use `ErrorClassifier` in `_is_retryable_error()` |
| `weebot/application/agents/executor.py` | Token tracking, `_maybe_compress()`, `StepBudget`, memory snapshot |
| `weebot/tools/tool_registry.py` | Register `persistent_memory`, `mixture_of_agents` |
| `weebot/application/di.py` | Add skill curator setup; pass `SUBAGENT_MAX_STEPS` to sub-agent flows |
| `cli/main.py` | Add `flow export` command |

---

## Enhancement #5 — Tool Output Size Limits

**Effort:** Small | **Impact:** Medium

Prevents browser/bash tools from flooding context window with unbounded output.

### `weebot/config/constants.py`
```python
MAX_TOOL_OUTPUT_CHARS: int = 20_000
"""Max characters in a single tool result before truncation."""
```

### `weebot/tools/base.py` — in `ToolCollection.execute()`, after `result.metadata.update({...})`
```python
from weebot.config.constants import MAX_TOOL_OUTPUT_CHARS
if result.output and len(result.output) > MAX_TOOL_OUTPUT_CHARS:
    original_length = len(result.output)
    removed = original_length - MAX_TOOL_OUTPUT_CHARS
    result.output = (
        result.output[:MAX_TOOL_OUTPUT_CHARS]
        + f"\n...[truncated: {removed} chars omitted]"
    )
    result.metadata["truncated"] = True
    result.metadata["original_length"] = original_length
else:
    result.metadata.setdefault("truncated", False)
```

**Verify:** Run `bash_tool` with `ls -laR /`. Confirm `result.metadata["truncated"] == True` and `len(result.output) <= 20_060`.

---

## Enhancement #8 — Error Classifier

**Effort:** Small | **Impact:** Medium

Routes LLM error recovery correctly: context-length errors should compress rather than retry; auth errors should fail fast rather than burn retry budget.

### NEW: `weebot/core/error_classifier.py`
```python
"""ErrorClassifier — maps exceptions to recovery-routing categories."""
from __future__ import annotations
import re
from enum import Enum


class ErrorCategory(Enum):
    RATE_LIMIT = "rate_limit"
    CONTEXT_LENGTH = "context_length"
    AUTH = "auth"
    MODEL_UNAVAILABLE = "model_unavailable"
    TOOL_ERROR = "tool_error"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ErrorClassifier:
    _PATTERNS: list[tuple[str, ErrorCategory]] = [
        (r"context.{0,30}(length|window|limit|exceed|too.long)", ErrorCategory.CONTEXT_LENGTH),
        (r"maximum.{0,20}token", ErrorCategory.CONTEXT_LENGTH),
        (r"prompt.{0,20}too.{0,10}long", ErrorCategory.CONTEXT_LENGTH),
        (r"rate.?limit|too.many.request|429|quota.exceed", ErrorCategory.RATE_LIMIT),
        (r"api.?key|unauthorized|authentication|403|invalid.?key", ErrorCategory.AUTH),
        (r"model.{0,20}(not.found|unavailable|deprecated|overloaded)|503", ErrorCategory.MODEL_UNAVAILABLE),
        (r"connection|timeout|network|unreachable|502|504", ErrorCategory.NETWORK),
    ]

    @classmethod
    def classify(cls, exc: BaseException) -> ErrorCategory:
        combined = f"{type(exc).__name__} {str(exc)}".lower()
        for pattern, category in cls._PATTERNS:
            if re.search(pattern, combined):
                return category
        return ErrorCategory.UNKNOWN

    @classmethod
    def should_compact(cls, exc: BaseException) -> bool:
        return cls.classify(exc) == ErrorCategory.CONTEXT_LENGTH

    @classmethod
    def should_fail_fast(cls, exc: BaseException) -> bool:
        return cls.classify(exc) == ErrorCategory.AUTH

    @classmethod
    def should_fallback_model(cls, exc: BaseException) -> bool:
        return cls.classify(exc) in (ErrorCategory.RATE_LIMIT, ErrorCategory.MODEL_UNAVAILABLE)
```

### `weebot/infrastructure/adapters/llm/resilient_adapter.py`
- Add import: `from weebot.core.error_classifier import ErrorClassifier, ErrorCategory`
- Replace `_is_retryable_error()` body:
  ```python
  def _is_retryable_error(self, exc: Exception) -> bool:
      cat = ErrorClassifier.classify(exc)
      return cat not in (ErrorCategory.AUTH, ErrorCategory.CONTEXT_LENGTH, ErrorCategory.UNKNOWN)
  ```
- In `chat()` `except` block, add before `raise`:
  ```python
  if ErrorClassifier.should_fail_fast(e):
      raise
  ```

**Verify:** Unit-test `ErrorClassifier.classify(Exception("rate limit exceeded")) == ErrorCategory.RATE_LIMIT`.

---

## Enhancement #1 — Real Token Tracking + Auto-Compress

**Effort:** Medium | **Impact:** High

`LLMResponse.usage` already carries real token counts (prompt/completion/total) from every adapter response, but nothing reads them. The `TokenBudgetMonitor.should_compact()` fires but nothing compresses. This wires real tracking and triggers `ConversationCompressor` at 75% of the context window.

### NEW: `weebot/application/services/conversation_compressor.py`

```python
"""ConversationCompressor — summarizes middle turns to reduce context window usage.

Protects first KEEP_HEAD=3 and last KEEP_TAIL=6 turns.
Summarizes the middle via a cheap-model LLM call.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)
KEEP_HEAD: int = 3
KEEP_TAIL: int = 6

class ConversationCompressor:
    def __init__(self, llm: LLMPort, cheap_model: Optional[str] = None,
                 keep_head: int = KEEP_HEAD, keep_tail: int = KEEP_TAIL) -> None:
        self._llm = llm
        self._keep_head = keep_head
        self._keep_tail = keep_tail
        if cheap_model is None:
            from weebot.config.model_refs import MODEL_BUDGET
            cheap_model = MODEL_BUDGET
        self._cheap_model = cheap_model

    async def compress(self, buffer: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return buffer with middle turns replaced by a single summary message.
        Returns original buffer unchanged if too short to compress."""
        total = len(buffer)
        if total < self._keep_head + self._keep_tail + 1:
            return buffer
        head = buffer[:self._keep_head]
        middle = buffer[self._keep_head:total - self._keep_tail]
        tail = buffer[total - self._keep_tail:]
        summary = await self._summarize(middle)
        summary_msg = {
            "role": "system",
            "content": f"[Context summary — {len(middle)} turns compressed]\n{summary}",
        }
        compressed = head + [summary_msg] + tail
        logger.info("Compressed buffer: %d → %d messages", total, len(compressed))
        return compressed

    async def _summarize(self, messages: List[Dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            if content:
                parts.append(f"{msg.get('role','').upper()}: {content[:2000]}")
        if not parts:
            return "(empty section)"
        transcript = "\n\n".join(parts)
        try:
            resp = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "Summarize this conversation in 3-7 factual sentences."},
                    {"role": "user", "content": transcript},
                ],
                model=self._cheap_model, temperature=0.0, max_tokens=512,
            )
            return resp.content or "(summary unavailable)"
        except Exception as exc:
            logger.warning("Compressor LLM call failed: %s", exc)
            return f"(compression failed: {exc})"
```

### `weebot/application/agents/executor.py` — 4 targeted changes

**1. New imports** (after existing imports):
```python
from weebot.application.services.conversation_compressor import ConversationCompressor
from weebot.application.services.token_budget_monitor import TokenBudgetMonitor
from weebot.core.error_classifier import ErrorClassifier
```

**2. Extend `__init__` signature** (after `max_context_turns: int = 15,`):
```python
token_budget_monitor: Optional["TokenBudgetMonitor"] = None,
auto_compress: bool = True,
context_window: int = 128_000,
```
And in body (after `self._facts: Dict[str, Any] = {}`):
```python
self._token_budget_monitor = token_budget_monitor or TokenBudgetMonitor()
self._auto_compress = auto_compress
self._context_window = context_window
self._total_prompt_tokens: int = 0
self._total_completion_tokens: int = 0
self._compressor: Optional[ConversationCompressor] = None
```

**3. Track usage in `_call_with_cascade()`** — after each `resp = await self._llm.chat(...)`:
```python
if resp and resp.usage:
    self._total_prompt_tokens += resp.usage.get("prompt_tokens", 0)
    self._total_completion_tokens += resp.usage.get("completion_tokens", 0)
    await self._maybe_compress()
```

**4. New methods** (add after `summarize()`):
```python
async def _maybe_compress(self) -> None:
    if not self._auto_compress:
        return
    total = self._total_prompt_tokens + self._total_completion_tokens
    threshold = int(self._context_window * 0.75)
    if total >= threshold and len(self._conversation_buffer) >= 10:
        logger.info("Token usage %d >= threshold %d — compressing", total, threshold)
        if self._compressor is None:
            self._compressor = ConversationCompressor(llm=self._llm)
        compressed = await self._compressor.compress(list(self._conversation_buffer))
        self._conversation_buffer.clear()
        for msg in compressed:
            self._conversation_buffer.append(msg)
        # Reset counters post-compaction to avoid immediate re-trigger
        self._total_prompt_tokens = int(self._total_prompt_tokens * 0.3)
        self._total_completion_tokens = 0

@property
def token_usage(self) -> Dict[str, int]:
    return {
        "prompt_tokens": self._total_prompt_tokens,
        "completion_tokens": self._total_completion_tokens,
        "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
    }
```

**Verify:** Set `context_window=1000` in a test and confirm `_maybe_compress()` fires, buffer shrinks, and contains a `[Context summary...]` system message.

---

## Enhancement #2 — Thread-safe StepBudget with Refund

**Effort:** Small | **Impact:** Medium-High

Replaces the bare `for _ in range(self._max_steps)` loop in `ExecutorAgent` with a thread-safe budget object. Sub-agents spawned via `DispatchAgentsTool` get their own independent budget capped at `SUBAGENT_MAX_STEPS=15`.

### NEW: `weebot/application/services/step_budget.py`
```python
"""StepBudget — thread-safe step allocation with consume/refund semantics."""
from __future__ import annotations
import threading


class StepBudget:
    def __init__(self, max_steps: int) -> None:
        if max_steps < 1:
            raise ValueError(f"max_steps must be >= 1, got {max_steps}")
        self._max_steps = max_steps
        self._used: int = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        with self._lock:
            if self._used >= self._max_steps:
                return False
            self._used += 1
            return True

    def refund(self, count: int = 1) -> None:
        if count < 1:
            return
        with self._lock:
            self._used = max(0, self._used - count)

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self._max_steps - self._used)

    @property
    def exhausted(self) -> bool:
        return self.remaining == 0

    def reset(self) -> None:
        with self._lock:
            self._used = 0
```

### `weebot/config/constants.py`
```python
SUBAGENT_MAX_STEPS: int = 15
"""Max tool-call iterations for sub-agents spawned by DispatchAgentsTool."""
```

### `weebot/application/agents/executor.py`
- Add import: `from weebot.application.services.step_budget import StepBudget`
- In `__init__`, after `self._max_steps = max_steps`: `self._step_budget = StepBudget(max_steps=max_steps)`
- In `execute_step()`, replace `for _ in range(self._max_steps):` with:
  ```python
  self._step_budget.reset()
  while self._step_budget.consume():
  ```
- When `terminate` tool is called, before setting `abort_step = True`:
  ```python
  self._step_budget.refund(self._step_budget.remaining)
  ```

### `weebot/application/di.py` — `_build_plan_act_flow_for_session()`
```python
from weebot.config.constants import SUBAGENT_MAX_STEPS
# Pass into PlanActFlow → ExecutorAgent
return PlanActFlow(..., max_steps=SUBAGENT_MAX_STEPS)
```
`PlanActFlow.__init__` must accept and forward `max_steps` to its `ExecutorAgent`.

**Verify:** Confirm sub-agent `ExecutorAgent._step_budget._max_steps == 15`, parent == 25.

---

## Enhancement #4 — Persistent Cross-Session Memory

**Effort:** Medium | **Impact:** Medium-High

File-backed `~/.weebot/memory/AGENT.md` + `USER.md` with `§`-delimited entries. A frozen snapshot is injected into the executor's system prompt at session start (hermes pattern: preserves prefix cache; mid-session writes don't disturb it).

### NEW: `weebot/tools/persistent_memory.py`

Key design:
- `§`-delimited entries, file-backed at `Path.home() / ".weebot" / "memory"`
- Actions: `add`, `replace` (by substring match), `remove` (by substring match), `read`
- Injection-pattern guard before every write (rejects `<INST>`, `</s>`, `SYSTEM:`, `[INST]`, etc.)
- `PersistentMemoryTool.load_snapshot() -> str` class method returns formatted content of both files for system-prompt injection

Full implementation is self-contained (no external deps beyond stdlib `re`, `pathlib`).

### `weebot/application/agents/executor.py` — inject snapshot
In `execute_step()`, after `self._system_prompt = system_prompt`:
```python
try:
    from weebot.tools.persistent_memory import PersistentMemoryTool
    snapshot = PersistentMemoryTool.load_snapshot()
    if snapshot:
        self._system_prompt = self._system_prompt + "\n\n" + snapshot
except Exception:
    pass  # Non-fatal
```

### `weebot/tools/tool_registry.py`
- Add `"persistent_memory": PersistentMemoryTool` to `_TOOL_CLASS_MAP`
- Add `"persistent_memory"` to `DEFAULT_ROLE_MAPPINGS["admin"]`

**Verify:** `persistent_memory add entry="test" file="agent"` → start new session → confirm system prompt contains `# Persistent Memory`.

---

## Enhancement #3 — Mixture-of-Agents (MoA) Tool

**Effort:** Medium | **Impact:** High

Runs 4 frontier models in parallel via OpenRouter (existing `OPENROUTER_API_KEY`), feeds all responses to an aggregator for synthesis. Based on [Wang et al. 2024 MoA paper](https://arxiv.org/abs/2406.04692).

### NEW: `weebot/tools/mixture_of_agents.py`

Key design:
- Default reference models: `openai/gpt-4o-mini`, `anthropic/claude-3-5-haiku`, `google/gemini-flash-1.5`, `meta-llama/llama-3.3-70b-instruct`
- Default aggregator: `anthropic/claude-sonnet-4.6`
- Uses existing `OpenAIAdapter` with `base_url="https://openrouter.ai/api/v1"` — no new HTTP client
- `asyncio.gather()` for parallel reference calls, `asyncio.Semaphore(max_concurrency)` for throttling
- Phase 1: parallel reference calls (temperature=0.7 for diversity)
- Phase 2: aggregator synthesizes (temperature=0.3 for consistency)
- Fallback: if aggregator fails, return the longest individual response
- Returns `ToolResult` with `output=synthesized_answer` and `data={"reference_results": [...], "successful_count": N}`
- Gracefully skips failed reference models (only needs 1 success)
- No new dependencies — uses `openai` (already in requirements)

### `weebot/tools/tool_registry.py`
- Add `"mixture_of_agents": MixtureOfAgentsTool` to `_TOOL_CLASS_MAP`
- Add `"mixture_of_agents"` to `DEFAULT_ROLE_MAPPINGS["admin"]`

**Verify:** `MixtureOfAgentsTool().execute(query="What is 2+2?")` → `data["successful_count"] >= 2`, `output` is a synthesized answer.

---

## Enhancement #6 — Trajectory Exporter

**Effort:** Medium | **Impact:** Medium

Serializes session events from SQLite to JSONL. Optionally compresses middle turns (reusing `ConversationCompressor`) before export for fine-tuning use.

### NEW: `weebot/application/services/trajectory_exporter.py`

```python
class TrajectoryExporter:
    def __init__(self, repo: StateRepositoryPort) -> None: ...

    async def export_session(
        self, session_id: str, output_path: str | Path,
        compress_to_budget: Optional[int] = None, llm=None,
    ) -> int:
        """Export session events as JSONL. Returns event count written."""

    async def export_all(
        self, user_id: str, output_dir: str | Path,
        compress_to_budget: Optional[int] = None, llm=None,
    ) -> Dict[str, int]:
        """Export all sessions for user. Returns {session_id: event_count}."""
```

Event serialization: `event.model_dump()` (Pydantic), with `default=str` fallback.

### `cli/main.py` — add `flow export` command
```bash
python -m cli.main flow export <session_id> [--output path.jsonl] [--compress 32000]
```

**Verify:** Export a completed session. Confirm each line is valid JSON with a `type` field. With `--compress 8000` on a long session, confirm a `[Context summary...]` line appears.

---

## Enhancement #7 — Background Skill Curator

**Effort:** High | **Impact:** Low-Medium

Weekly background task (APScheduler cron, registered via `SchedulingManager`) that classifies skills by recency and LLM-reviews stale ones. Appends `EvolutionEntry` with `[SkillCurator]` prefix. Never deletes — only archives.

### NEW: `weebot/application/services/skill_curator.py`

```python
class SkillCurator:
    ACTIVE_DAYS = 30   # < 30 days since last EvolutionEntry → active
    STALE_DAYS = 90    # 30-90 days → stale (reviewed)
                       # 90+ days → archive-candidate (reviewed)

    async def run_curation(self) -> dict[str, str]:
        """Classify all skills; LLM-review stale ones. Returns {name: classification}."""
```

Classification uses `skill.evolution_log[-1].timestamp` (or `skill.versions[-1].accepted_at` as fallback).

LLM review prompt asks for `ARCHIVE`, `PIN`, or `KEEP` in one word + one sentence reason. Result appended to `skill.evolution_log` as `EvolutionEntry`.

### `weebot/application/di.py`
Add `configure_skill_curator()` + `_register_curator_job()` methods. Cron: Sunday 02:00 weekly.

**Verify:** `await curator.run_curation()` with a skill last touched 60+ days ago → confirm `evolution_log` has a new `[SkillCurator]` entry.

---

## Integration Points — Quick Reference

| Integration | File | Location |
|---|---|---|
| Truncation guard | `tools/base.py` | `ToolCollection.execute()`, after `result.metadata.update({...})` |
| Error routing | `resilient_adapter.py` | Replace `_is_retryable_error()` body |
| Token tracking | `executor.py` | After each `resp = await self._llm.chat(...)` in `_call_with_cascade()` |
| Auto-compress trigger | `executor.py` | New `_maybe_compress()` method |
| StepBudget loop | `executor.py` | Replace `for _ in range(self._max_steps):` in `execute_step()` |
| Memory snapshot | `executor.py` | After `self._system_prompt = system_prompt` in `execute_step()` |
| Tool registration | `tool_registry.py` | `_build_tool_class_map()` + `DEFAULT_ROLE_MAPPINGS["admin"]` |
| Sub-agent budget | `di.py` | `_build_plan_act_flow_for_session()` — pass `max_steps=SUBAGENT_MAX_STEPS` |
| Skill curator | `di.py` | New `configure_skill_curator()` + `_register_curator_job()` |

---

## Verification Suite

```bash
# After implementing, run the full test suite
pytest tests/ -v --cov=weebot --cov-report=term-missing

# Manual spot-checks per enhancement
# #5 - Tool output limits
python -c "from weebot.tools.base import ToolResult; r = ToolResult(output='x'*25000); print(len(r.output))"

# #8 - Error classifier
python -c "from weebot.core.error_classifier import ErrorClassifier, ErrorCategory; \
  assert ErrorClassifier.classify(Exception('rate limit 429')) == ErrorCategory.RATE_LIMIT; \
  print('OK')"

# #1 - Compressor
pytest tests/unit/test_conversation_compressor.py -v

# #2 - StepBudget
python -c "from weebot.application.services.step_budget import StepBudget; \
  b = StepBudget(3); b.consume(); b.consume(); b.consume(); \
  assert not b.consume(); b.refund(); assert b.consume(); print('OK')"

# #4 - Persistent memory
python -m cli.main flow run "Add 'test fact' to persistent memory"
# Start new session and verify memory appears in system prompt

# #3 - MoA tool (requires OPENROUTER_API_KEY)
python -c "import asyncio; from weebot.tools.mixture_of_agents import MixtureOfAgentsTool; \
  r = asyncio.run(MixtureOfAgentsTool().execute(query='What is 2+2?')); \
  print(r.data['successful_count'], r.output[:100])"

# #6 - Trajectory export
python -m cli.main flow list
python -m cli.main flow export <session_id> --output /tmp/test.jsonl
python -c "import json; [json.loads(l) for l in open('/tmp/test.jsonl')]"

# #7 - Skill curator
python -c "import asyncio; from weebot.application.services.skill_curator import SkillCurator; ..."
```

---

## Notes on docs/ Placement

When implementation begins, a copy of this plan will be written to `docs/hermes-enhancements.md` as the living reference document. The plan file here (`C:\Users\tesse\.claude\plans\...`) is the implementation working copy.
