# Chain-of-Verification (CoVe) — Comparison with Weebot

**Paper:** Dhuliawala et al. (2023), Meta AI & ETH Zurich  
**Method:** Chain-of-Verification (CoVe) — 4-step self-verification to reduce LLM hallucinations  
**File:** `Chain of verification.pdf` (arXiv:2309.11495)

---

## CoVe Method — 4 Steps

| Step | Description | Key Constraint |
|------|-------------|----------------|
| 1. Baseline Response | Standard LLM generation for the query | None |
| 2. Plan Verifications | Generate verification questions fact-checking the draft | Conditioned on query + baseline |
| 3. Execute Verifications | Answer each question independently | **Factored**: no access to baseline response (prevents repeating hallucinations) |
| 4. Final Verified Response | Produce corrected response using verification results | Conditioned on all prior steps |

**Core insight:** Answering short verification questions independently yields higher accuracy than the original longform response. The factored variant (separate prompts, no baseline context) outperforms joint variants.

---

## Weebot's Existing Capabilities

| Capability | Weebot Location | CoVe Equivalent? | Gap |
|------------|----------------|------------------|-----|
| **Plan Critic** | `weebot/application/services/plan_critic.py` | Pre-execution structure validator — checks tool fit, scope, preconditions, parallelization, vagueness | Validates plan quality, not factual correctness of generated claims |
| **Truth Binder** | `weebot/application/services/truth_binder.py` | **Post-generation fact-checker** — 5 deterministic checks: URL substitution, action-claim matching, response grounding, schedule honesty, prompt-leak redaction | Deterministic (regex), not LLM-powered; covers 5 specific patterns, not general factual verification |
| **Trajectory Monitor** | `weebot/application/services/trajectory_monitor.py` | Behavioral monitor — detects repetition, semantic loops, stagnation, budget exhaustion | Quality-of-trajectory check, not truthfulness check |
| **Debate / Multi-Agent** | `weebot/tools/debate.py` | Multi-perspective with blind-spot identification | Uses multiple agents sharing same context — no factored verification (CoVe's key insight) |
| **Self-Correction** | `StructuredExecutorAgent` with error recovery | Recovers from tool execution errors | Runtime error handling, not factual accuracy |
| **Error Classification** | `weebot/core/error_classifier.py` | Classifies exception types for routing | Exception taxonomy, not fact verification |
| **Information Synthesis** | `weebot/application/services/information_synthesis.py` | Detects coverage gaps between sources and synthesis | Detects missing sources, not hallucinated claims within sources |
| **Conversation Compressor** | `weebot/application/services/conversation_compressor.py` | Token budget management | No verification step |
| **Knowledge Graph** | `weebot/application/services/knowledge_graph.py` | Stores/retrieves facts with confidence scores | Ground truth for verification, but not a verification pipeline itself |

---

## What Weebot Is Missing

1. **No LLM-powered post-generation fact verification** — TruthBinder performs deterministic (regex) checks on 5 patterns, but there is no general LLM-powered step that generates and answers arbitrary verification questions about factual claims. CoVe does this generically.

2. **No factored verification** — When weebot does self-critique (e.g., `debate.py`), it uses multi-agent debate where each agent sees the same context. The CoVe paper's core finding is that answering verification questions **without** seeing the original baseline response yields higher accuracy — the context must be factored. Weebot has no mechanism that isolates verification context from generation context.

3. **No structured plan-to-verify step** — The PlannerAgent plans task execution steps, and PlanCriticService validates those plans structurally. But neither generates fact-checking questions about the content the agent produces.

4. **No cross-check/resolve loop** — CoVe has an explicit inconsistency-detection step (checking verification answers against baseline claims) followed by a revision. Weebot's PlanActFlow has an `Updating` state that replans on task failure, but this is a task-level retry, not a factual-inconsistency check.

---

## Feasibility Assessment

**Integration effort:** LOW — CoVe is a prompt-level technique, not a model-level change. It can be implemented as a new application service or a new flow state (`verifying.py`) in weebot's existing state machine.

**Natural integration point:** A new `Verifying` state in `PlanActFlow`, inserted between `Executing` and `Summarizing`:

```
Planning → Executing → **Verifying** → Summarizing → Completed
```

**Requirements:**
- A prompt template for Step 2 (plan verification questions from baseline)
- A prompt template for Step 3 (answer each question independently)
- A prompt template for Step 4 (produce corrected response)
- **Factored execution:** Each verification question answered via a separate LLMPort.chat() call with no baseline response in context
- Parallel execution of verification questions (they're independent — `asyncio.gather`)

**Risk:** LOW — pure prompt engineering, no infrastructure changes. The existing `LLMPort`, `PlanActFlow`, and state machine infrastructure already support this pattern.

**Estimated effort:** ~0.5 days (prompt design + flow state + integration test)
