# Weebot Harness Enhancement Plan
## LIFE-HARNESS Paper Integration + Production Hardening

**Author:** Reasonix Code  
**Date:** 2026-06-02  
**Source:** Xu, Wen, Li — "Adapting the Interface, Not the Model" (arXiv:2605.22166v2)  
**Status:** Draft — pending review

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Compliance](#architecture-compliance)
3. [Tier 1 — Quick Wins (Week 1)](#tier-1--quick-wins-week-1)
   - [1.1 Action Canonicalizer](#11-action-canonicalizer)
   - [1.2 BM25 Procedural Skill Retrieval](#12-bm25-procedural-skill-retrieval)
   - [1.3 Trajectory-Aware Repetition Detection](#13-trajectory-aware-repetition-detection)
4. [Tier 2 — Medium Effort (Week 2-3)](#tier-2--medium-effort-week-2-3)
   - [2.1 Cross-Model Harness Sharing](#21-cross-model-harness-sharing)
   - [2.2 Automated Harness Evolution](#22-automated-harness-evolution)
   - [2.3 Windows-Native Output Robustness](#23-windows-native-output-robustness)
5. [Tier 3 — Strategic (Month 2)](#tier-3--strategic-month-2)
   - [3.1 Agent-to-Agent Message Protocol](#31-agent-to-agent-message-protocol)
   - [3.2 Environment Contract DSL](#32-environment-contract-dsl)
   - [3.3 Harness-as-Code Consolidation](#33-harness-as-code-consolidation)
6. [Dependency Graph](#dependency-graph)
7. [Risk Assessment](#risk-assessment)
8. [Appendix — CI/QA Improvements](#appendix--ciqa-improvements)

---

## Executive Summary

This plan defines 9 enhancements derived from two sources: (1) the LIFE-HARNESS paper's
four-layer runtime harness architecture, and (2) patterns discovered during 18 bug fixes
across the weebot codebase.

The enhancements are organized into three tiers by effort and dependency. Tier 1 delivers
the paper's three most impactful findings (Action Realization, Procedural Skills, Trajectory
Regulation) as lightweight additions to existing infrastructure. Tier 2 extends these into
automated evolution and cross-model sharing. Tier 3 consolidates the harness into a unified,
versioned artifact.

**Total estimated effort:** ~2,200 lines across 18 files.  
**New dependencies:** `rank_bm25` (pure Python, optional), `pyyaml` (already in requirements).  
**Breaking changes:** None — all additions are opt-in layers between existing components.

---

## Architecture Compliance

### Principles

1. **Domain-first.** New harness concepts start as Pydantic models. No infrastructure in domain.
2. **Ports before adapters.** `HarnessPort`, `SkillRetrieverPort`, `CanonicalizerPort`.
3. **Pipes-and-filters.** Each harness layer is a callable that takes `(action, context) → (action', context')`. Layers compose without knowing about each other.
4. **Evidence-driven.** Every canonicalization, skill retrieval, and trajectory regulation event is logged as an `AgentEvent` for audit and evolution.
5. **Immutable state.** All mutations use `model_copy(update={...})`.

### Layers touched

```
domain/models/          ← CanonicalizationResult, SkillMatch, TrajectoryHealth
application/
  ports/                ← SkillRetrieverPort, CanonicalizerPort, TrajectoryMonitorPort
  services/             ← ActionCanonicalizer, BM25SkillRetriever, TrajectoryMonitor
  harness/              ← HarnessComposer (new sub-package)
infrastructure/
  adapters/             ← PlatformEncodingAdapter
config/
  contracts/            ← Tool contract YAML files
tools/                  ← No changes (canonicalizer wraps, doesn't modify)
```

---

## Tier 1 — Quick Wins (Week 1)

### 1.1 Action Canonicalizer

**What it does**

Sits between the executor and `ToolCollection.execute()`. Before any tool call, it:
1. Validates the action against the tool's JSON schema
2. Coerces argument types (string → int for `timeout`, array → string for `command`)
3. Fills missing required args with safe defaults from a contract file
4. Returns a `CanonicalizationResult` — either `PASS(action')` forwarding the corrected call, or `BLOCK(reason)` with a clear error message
5. Logs every canonicalization as a `CanonicalizationEvent` for later harness evolution

Maps to LIFE-HARNESS "Action Realization Layer" (the paper's #1 failure mode, responsible for 23-68% of failures across benchmarks).

**Domain models**

`weebot/domain/models/canonical.py` (new)

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Any, Optional

class CanonicalizationVerdict(str, Enum):
    PASS = "pass"            # Action forwarded (possibly corrected)
    BLOCK = "block"          # Deterministic failure — blocked
    FILL_DEFAULT = "fill"    # Missing arg filled with default

class CanonicalizationResult(BaseModel):
    verdict: CanonicalizationVerdict
    original_args: dict[str, Any] = Field(default_factory=dict)
    corrected_args: dict[str, Any] = Field(default_factory=dict)
    changes: list[str] = Field(default_factory=list)
    block_reason: str = ""
```

**Service**

`weebot/application/services/action_canonicalizer.py` (new)

```python
class ActionCanonicalizer:
    """Validate and canonicalize tool calls before execution.

    Uses per-tool contract files (YAML) or inline defaults. Each
    canonicalization is logged as a CanonicalizationEvent for
    downstream harness evolution.
    """

    def __init__(self, contracts_dir: Path | None = None):
        self._contracts: dict[str, dict] = {}  # tool_name → contract
        self._load_contracts(contracts_dir)

    def canonicalize(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> CanonicalizationResult:
        ...
```

**Contract file format**

`weebot/config/contracts/bash.yaml` (new)

```yaml
tool: bash
coercions:
  timeout: { type: float, default: 30.0, min: 1.0, max: 300.0 }
  command: { type: str, required: true }
defaults:
  use_wsl: false
  working_dir: null
block_patterns:
  - argument: command
    pattern: "^\\s*$"
    reason: "Empty command"
pitfalls:
  - "PowerShell uses ; not && for command chaining"
  - "cd does not persist between tool calls — use working_dir"
  - "Use forward slashes in paths for cross-platform compatibility"
```

**Integration point**

Modify `ToolCollection.execute()` to accept an optional `CanonicalizerPort`:

```python
async def execute(self, _name: str, **kwargs) -> ToolResult:
    if self._canonicalizer:
        result = self._canonicalizer.canonicalize(_name, kwargs)
        if result.verdict == CanonicalizationVerdict.BLOCK:
            return ToolResult.error_result(result.block_reason)
        kwargs = result.corrected_args
    # ... existing execution logic
```

**LIFE-HARNESS paper alignment**

Directly implements the Action Realization Layer (Section 4.3.3). The paper reports that action-level canonicalization alone contributes 4-62% relative improvement depending on the benchmark (Table 2: "w/o Action" drops up to 61.7% on Airline).

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/canonical.py` | Create | ~30 |
| `weebot/application/ports/canonicalizer_port.py` | Create | ~20 |
| `weebot/application/services/action_canonicalizer.py` | Create | ~100 |
| `weebot/application/models/tool_collection.py` | Modify (+canonicalizer) | ~15 |
| `weebot/config/contracts/bash.yaml` | Create | ~20 |
| `weebot/config/contracts/python_execute.yaml` | Create | ~15 |
| `weebot/config/contracts/web_search.yaml` | Create | ~10 |
| `weebot/config/contracts/file_editor.yaml` | Create | ~15 |
| **Total** | | **~225** |

---

### 1.2 BM25 Procedural Skill Retrieval

**What it does**

Replaces exact-name skill matching (`skill_registry.get(name)`) with BM25 retrieval over all skill descriptions. When the agent starts a task, the Procedural Skill Layer:
1. Tokenizes the task description
2. Scores all skills by BM25 relevance
3. Injects the top-3 matching skills into the system prompt
4. Logs which skills were retrieved and whether they were used (via post-execution analysis)

Maps to LIFE-HARNESS "Procedural Skill Layer" (Section 4.3.2). The paper reports 2-17% relative contribution from this layer.

**Port**

`weebot/application/ports/skill_retriever_port.py` (new)

```python
class SkillRetrieverPort(ABC):
    @abstractmethod
    async def retrieve(self, task: str, top_k: int = 3) -> list[SkillMatch]:
        """Return top-k skills relevant to *task*."""
        ...

@dataclass
class SkillMatch:
    skill_name: str
    description: str
    content_preview: str
    score: float
```

**Service**

`weebot/application/services/bm25_skill_retriever.py` (new)

```python
class BM25SkillRetriever(SkillRetrieverPort):
    """BM25-based skill retrieval over the skill registry.

    Indexes all loaded skills at construction time. Tokenization
    uses simple whitespace split (no external NLP deps). Scores
    are normalized to [0, 1] within each query.
    """

    def __init__(self, registry: SkillRegistry):
        from rank_bm25 import BM25Okapi
        self._skills = registry.list_all()
        corpus = [s.description + " " + s.content[:500] for s in self._skills]
        self._bm25 = BM25Okapi([doc.split() for doc in corpus])

    async def retrieve(self, task: str, top_k: int = 3) -> list[SkillMatch]:
        tokens = task.split()
        scores = self._bm25.get_scores(tokens)
        # ... normalize, sort, return top_k
```

**Integration**

Modify `ExecutorAgent.__init__()` to accept `SkillRetrieverPort`. In `execute_step()`, before building the system prompt:

```python
if self._skill_retriever:
    matches = await self._skill_retriever.retrieve(step.description, top_k=2)
    for m in matches:
        system_prompt += f"\n\n## Relevant Skill: {m.skill_name}\n{m.content_preview}"
```

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/application/ports/skill_retriever_port.py` | Create | ~25 |
| `weebot/application/services/bm25_skill_retriever.py` | Create | ~60 |
| `weebot/application/agents/executor.py` | Modify (+retriever) | ~15 |
| `weebot/application/di.py` | Modify (+binding) | ~5 |
| `requirements.txt` | Modify (+rank_bm25) | ~1 |
| **Total** | | **~106** |

---

### 1.3 Trajectory-Aware Repetition Detection

**What it does**

Extends `ExecutingState`'s current exact-match repetition detection (4 identical tool calls → stuck) with:
1. **Semantic repetition** — different tool calls that produce identical results (normalized output hash)
2. **Stagnation detection** — step count increasing but `step_result` unchanged across 3+ iterations
3. **Budget imbalance** — single sub-goal consuming >40% of remaining step budget
4. **Recovery injection** — when a pattern is detected, injects a structured recovery message instead of just failing

Maps to LIFE-HARNESS "Trajectory Regulation Layer" (Section 4.3.4). The paper reports this layer contributes 3-86% depending on environment (Table 2).

**Domain model**

`weebot/domain/models/trajectory.py` (new)

```python
class TrajectoryHealth(str, Enum):
    HEALTHY = "healthy"
    REPEATING = "repeating"        # Same tool call 4+ times
    SEMANTIC_LOOP = "semantic"     # Different calls, same output
    STAGNATING = "stagnating"      # No progress across steps
    BUDGET_HOTSPOT = "budget"      # One goal consuming >40% budget
    EXHAUSTED = "exhausted"        # Budget at 90%+ with no completion

class TrajectoryDiagnosis(BaseModel):
    health: TrajectoryHealth
    detail: str
    recovery_message: str = ""
    affected_step_ids: list[str] = Field(default_factory=list)
```

**Service**

`weebot/application/services/trajectory_monitor.py` (new)

```python
class TrajectoryMonitor:
    """Monitor post-execution trajectory for degenerate patterns.

    Called after each step in ExecutingState. Maintains a rolling
    window of recent tool calls, outputs, and step outcomes.
    """

    def __init__(self, window_size: int = 10, budget_threshold: float = 0.4):
        self._window: deque[ToolEvent] = deque(maxlen=window_size)
        self._output_hashes: deque[str] = deque(maxlen=window_size)

    def diagnose(self, plan: Plan, step: Step, budget: StepBudget) -> TrajectoryDiagnosis:
        ...
```

**Integration**

In `ExecutingState.execute()`, after each tool call:

```python
diagnosis = self._trajectory_monitor.diagnose(plan, step, budget)
if diagnosis.health != TrajectoryHealth.HEALTHY:
    logger.warning("Trajectory %s: %s", diagnosis.health.value, diagnosis.detail)
    if diagnosis.recovery_message:
        self._conversation_buffer.append({
            "role": "system",
            "content": f"[RECOVERY] {diagnosis.recovery_message}"
        })
```

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/trajectory.py` | Create | ~30 |
| `weebot/application/services/trajectory_monitor.py` | Create | ~80 |
| `weebot/application/flows/states/executing.py` | Modify (+monitor) | ~25 |
| **Total** | | **~135** |

---

## Tier 2 — Medium Effort (Week 2-3)

### 2.1 Cross-Model Harness Sharing

**What it does**

The paper's central finding: a harness evolved on a cheap model (Qwen3-4B) improves all other models without retraining. Weebot has a 4-tier cascade — this enhancement makes harness configuration model-agnostic:

1. Separate harness config (tool contracts, skill library index, trajectory thresholds) from model-specific prompts
2. Store harness as versioned YAML files in `weebot/config/harness/`
3. When the model cascade switches tiers (e.g., Owl Alpha → Grok Build), the harness stays the same
4. Add `--harness-version` CLI flag to select harness versions for A/B testing
5. Measure: does Tier 1 + harness beat Tier 2 without harness?

**Implementation**

Extract harness state into `HarnessConfig`:

```python
class HarnessConfig(BaseModel):
    version: str
    contracts: dict[str, ToolContract]     # from Tier 1.1
    skill_index: SkillIndex               # from Tier 1.2
    trajectory_thresholds: dict           # from Tier 1.3
    model_override: Optional[str] = None   # None → apply to all models
```

DI container loads `HarnessConfig` once, injects into all services. Model selection is orthogonal.

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/config/harness/harness_config.py` | Create | ~40 |
| `weebot/config/harness/v1.0.0.yaml` | Create | ~50 |
| `weebot/application/di.py` | Modify (+HarnessConfig) | ~15 |
| `run.py` | Modify (+--harness-version) | ~10 |
| **Total** | | **~115** |

---

### 2.2 Automated Harness Evolution (LIFE-HARNESS Loop)

**What it does**

Extends SkillOptFlow (already wired) with layer-specific diagnosis and editing. The current flow only edits skill prompts. This enhancement:

1. **Diagnosis phase** — reads trajectory traces, classifies each failure into one of 4 layers (contract, skill, action, trajectory)
2. **Layer-specific editing** — routes the failure to the appropriate editor:
   - Contract failures → update tool contract YAML
   - Skill failures → propose new skill or edit existing
   - Action failures → add canonicalization rule
   - Trajectory failures → adjust detection thresholds
3. **Regression validation** — runs the same tasks with the new harness, compares scores
4. **Cross-model validation** — optionally tests on a different model to verify model-agnosticity

**Architecture**

```
TrajectoryRepo
  → LayerDiagnosticAgent.classify(failed_trajectories)
    → {layer: contract, evidence: "tool called with string timeout"}
  → LayerEditorAgent.edit(layer, evidence, current_harness)
    → HarnessEdit(contract="coerce timeout to float")
  → ValidationRunner.run(harness + edit, validation_tasks)
    → {score_delta: +0.15, regression: false}
  → Accept/Reject
```

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/application/agents/layer_diagnostics_agent.py` | Create | ~100 |
| `weebot/application/agents/layer_editor_agent.py` | Create | ~120 |
| `weebot/application/flows/skill_opt_flow.py` | Modify (+layer diagnosis) | ~80 |
| `weebot/application/cqrs/commands/harness_commands.py` | Create | ~30 |
| `weebot/application/cqrs/handlers.py` | Modify (+2 handlers) | ~80 |
| **Total** | | **~410** |

---

### 2.3 Windows-Native Output Robustness

**What it does**

Five bugs fixed were Windows-specific encoding crashes. This enhancement prevents them systematically:

1. **PlatformEncodingAdapter** — wraps subprocess output, auto-detects encoding (tries UTF-8, then CP-1252, then `replace`)
2. **Fuzzing test suite** — generates random byte sequences, feeds them through tool output paths, verifies no crash
3. **WEEBOT_PLATFORM** auto-detection in `ensure_workspace()` for platform-specific paths

**Implementation**

```python
class PlatformEncodingAdapter:
    """Safe subprocess output decoding for Windows/Linux."""

    ENCODINGS = ["utf-8", "cp1252", "latin-1", "cp850"]

    @classmethod
    def safe_decode(cls, data: bytes) -> str:
        for enc in cls.ENCODINGS:
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
```

Then: replace ALL bare `.decode('utf-8')` calls in the codebase with `PlatformEncodingAdapter.safe_decode(data)`.

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/infrastructure/adapters/platform_encoding.py` | Create | ~30 |
| `weebot/infrastructure/adapters/rtk_integration.py` | Modify (use adapter) | ~5 |
| `weebot/infrastructure/adapters/rtk_provider.py` | Modify (use adapter) | ~5 |
| `weebot/infrastructure/sandbox/native_windows.py` | Modify (use adapter) | ~5 |
| `tests/unit/test_platform_encoding.py` | Create | ~60 |
| **Total** | | **~105** |

---

## Tier 3 — Strategic (Month 2)

### 3.1 Agent-to-Agent Message Protocol

**What it does**

Currently `dispatch_parallel_tasks` spawns isolated agents. They can't share intermediate findings. This adds:

1. `InterAgentMessage` domain event — lightweight, carries a topic + payload
2. `SwarmEventBus` — in-memory pub/sub for agents within a swarm
3. Swarm agents publish findings as they discover them ("found competitor X with pricing $Y")
4. Synthesizer subscribes to these messages instead of waiting for all agents to finish
5. Enables cross-agent insight sharing: one agent discovers a pattern → all others can leverage it

**Domain models**

```python
class InterAgentMessage(BaseModel):
    sender_agent_id: str
    topic: str               # "competitor_found", "pricing_discovered"
    payload: dict[str, Any]
    confidence: float
    timestamp: datetime
```

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/inter_agent.py` | Create | ~35 |
| `weebot/infrastructure/swarm_event_bus.py` | Create | ~50 |
| `weebot/application/agents/synthesizer_agent.py` | Modify (+subscription) | ~40 |
| `weebot/tools/dispatch_agents.py` | Modify (+bus injection) | ~25 |
| **Total** | | **~150** |

---

### 3.2 Environment Contract DSL

**What it does**

The paper's Environment Contract Layer is essentially structured documentation of what tools *actually do* — not their JSON schemas, but their real behavior, pitfalls, and platform quirks. This defines a YAML DSL for those contracts and injects them into tool descriptions at runtime.

**Contract format**

```yaml
# weebot/config/contracts/advanced_browser.yaml
tool: advanced_browser
description_override: |
  Full Playwright browser automation. Launches a real Chromium instance.
constraints:
  - "Each tool call creates a fresh context — state does not persist"
  - "Cloudflare-protected sites (dior.com, sezane.com) may block the browser"
  - "Use web_search first — only open browser for JS-rendered content"
actions:
  goto:
    pitfalls:
      - "Timeout default is 30s; increase for slow sites with timeout=60000"
      - "Some sites return 403 in headless mode"
  screenshot:
    pitfalls:
      - "Returns base64 PNG — large images may be truncated"
recovery:
  - "If navigation times out, try with increased timeout before giving up"
  - "If page is blocked, switch to web_search for the same query"
```

**Loader**

`weebot/application/services/contract_loader.py` (new) — loads all YAML files from `config/contracts/`, merges with tool JSON schemas to produce enhanced tool descriptions visible to the LLM.

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/application/services/contract_loader.py` | Create | ~60 |
| `weebot/config/contracts/*.yaml` | Create (8 files) | ~160 |
| `weebot/application/models/tool_collection.py` | Modify (+contract injection) | ~20 |
| **Total** | | **~240** |

---

### 3.3 Harness-as-Code Consolidation

**What it does**

Currently the harness is spread across 25+ files (bash_guard, approval_policy, tool schemas, skill prompts, trajectory rules). This consolidates everything into a single versioned artifact:

```yaml
# weebot/config/harness/v1.0.0.yaml
version: "1.0.0"
evolved_from: "qwen3-4b trajectories, 2026-06-02"
layers:
  environment_contract:
    tools:
      bash: { $ref: "../contracts/bash.yaml" }
      python_execute: { $ref: "../contracts/python_execute.yaml" }
  procedural_skill:
    retriever: bm25
    index_path: "./cache/skill_index.pkl"
    top_k: 3
  action_realization:
    canonicalizer:
      strict_mode: false
      coerce_types: true
  trajectory_regulation:
    repetition_threshold: 4
    stagnation_window: 3
    budget_hotspot_ratio: 0.4
    recovery_mode: inject
```

Benefits:
- Single-file diff for A/B testing
- Version-controlled harness evolution (git blame on harness.yaml)
- Can be shared across weebot installations (public harness registry)
- Maps directly to LIFE-HARNESS's evaluation methodology

**Files changed/created**

| File | Action | Lines |
|------|--------|-------|
| `weebot/config/harness/schema.py` | Create (Pydantic schema) | ~50 |
| `weebot/config/harness/v1.0.0.yaml` | Create | ~60 |
| `weebot/application/services/harness_loader.py` | Create | ~50 |
| `weebot/application/di.py` | Modify (+HarnessConfig from YAML) | ~20 |
| **Total** | | **~180** |

---

## Dependency Graph

```
Tier 1 (independent — can build in parallel)
  ├── 1.1 Canonicalizer ──────────────────────┐
  ├── 1.2 BM25 Skills ────────────────────────┤
  └── 1.3 Trajectory Monitor ─────────────────┤
                                               │
Tier 2 (depends on Tier 1)                     │
  ├── 2.1 Cross-Model Harness ◄───────────────┤ needs 1.1+1.2+1.3 to exist
  ├── 2.2 Automated Evolution ◄───────────────┤ needs 1.1+1.2+1.3 + trajectory repo
  └── 2.3 Platform Encoding ◄── independent ──┘
                                               │
Tier 3 (depends on Tier 2)                     │
  ├── 3.1 Agent Messaging ◄───────────────────┤ needs 2.2 (swarm evolution pattern)
  ├── 3.2 Contract DSL ◄──────────────────────┤ needs 1.1 (canonicalizer format)
  └── 3.3 Harness-as-Code ◄───────────────────┘ consolidates 1.1+1.2+1.3+3.2
```

**Recommended build order:** 1.1 → 1.2 → 1.3 → 2.3 → 2.1 → 2.2 → 3.2 → 3.1 → 3.3

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Canonicalizer over-correction** — fills wrong defaults, masks real errors | MEDIUM | Strict mode off by default. Every canonicalization logged. `BLOCK` on ambiguous cases. |
| **BM25 index staleness** — skills added after startup not searchable | LOW | Re-index on `skill_registry.changed` event |
| **Trajectory monitor false positives** — recovery messages injected for healthy trajectories | MEDIUM | Start with high thresholds (5 repetitions, 50% budget). Lower based on false-positive data. |
| **Harness evolution cost** — LLM calls for diagnosis + editing + validation | HIGH | Use cheapest model for diagnosis (Owl Alpha). Batch-validate edits. Cap at 2 iterations/day. |
| **Cross-model harness doesn't transfer** — harness optimized for Owl Alpha harms DeepSeek V4 | MEDIUM | Regression test on ALL tiers before accepting harness edit. Flag model-specific edits. |
| **Agent messaging spam** — too many InterAgentMessages flood the synthesizer | LOW | Rate-limit to 1 message/agent/10s. Deduplicate by topic hash. |

---

## Appendix — CI/QA Improvements

Derived from bug patterns found during the 18-fix audit:

| Pattern | Instances | Prevention |
|---------|-----------|-----------|
| Bare `.decode('utf-8')` without `errors=` | 5 | `grep` in CI; flag in pre-commit |
| Missing `import` statement | 2 | `ruff` rule F821 |
| Hardcoded paths (`C:\\Users\\Public`) | 2 | `grep '[A-Z]:\\\\' weebot/` in CI |
| Double-lock acquisition in same method | 2 | Manual review checklist |
| Mutable default args (Pydantic `Field(default_factory=...)`) | 0 | Already correct ✅ |

Add to `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: no-bare-decode
      name: No bare .decode() without errors=
      entry: grep -n '\.decode(.utf-8.)' 
      language: system
      types: [python]
    - id: no-hardcoded-windows-paths
      name: No hardcoded Windows paths
      entry: grep -nP '[A-Z]:\\\\' 
      language: system
      types: [python]
```
