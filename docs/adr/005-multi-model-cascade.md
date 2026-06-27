# ADR-005: Multi-Model Cost Cascade

**Status:** Accepted
**Date:** 2025-07-17
**Deciders:** Architecture team

## Context

Weebot agents make thousands of LLM calls per task. Using a single
premium model (e.g., Claude Opus or GPT-5) for every call would be
prohibitively expensive. Different subtasks have different quality
requirements — planning a multi-step task needs strong reasoning;
summarizing a result needs moderate capability; formatting a response
can use a cheap model.

The system must balance cost against quality without requiring the
agent to manually select a model per call. It must also handle provider
outages gracefully — if a premium model is unavailable, fall back to
a cheaper model rather than failing.

## Decision

Adopt a **4-tier cost cascade** with per-role model configuration:

- **FREE** — models with `:free` suffix (e.g., `qwen/qwen3.7-plus:free`,
  `google/gemini-3.1-flash-image-preview`). Used for repetitive or
  low-criticality calls. Zero cost, lower quality.
- **BUDGET** — cheap paid models (e.g., `x-ai/grok-build-0.1`,
  `deepseek/deepseek-v4-flash`). Used for routine agent steps,
  summarization, and feedback parsing.
- **PREMIUM** — high-quality models (e.g., `minimax/minimax-m3`,
  `claude-4.5-sonnet`). Used for planning, code review, and
  critical reasoning.
- **ELITE** — top-tier models (e.g., `claude-4.6-opus`, `gpt-5.2`).
  Used for architecture decisions, complex debugging, and user-facing
  responses requiring maximum quality.

### Per-Role Model Maps

Each agent role (planner, executor, reviewer, dreamer, summarizer,
subagent) gets its own 3-model cascade [primary, fallback, fallback2].
Configured in `config/model_refs.py` (`_ROLE_MODEL_CASCADE` dict).

### Image and Video Cascades

Separate cascades exist for image generation (`IMAGE_CASCADE`, 9
use cases with 3–4 models each) and video generation (`VIDEO_CASCADE`,
5 use cases). These route through either OpenRouter chat completions
with image/video modality or direct provider APIs (xAI, Ideogram).

### Failure Handling

Each cascade tier has circuit breaker support:
- 3 consecutive failures → mark model as DEGRADED for 60 seconds.
- All tiers exhausted → return error to agent with list of failed models.
- Fallback chains are defined per-role, not globally — a planner failing
  doesn't affect image generation.

## Consequences

**Positive:**
- Cost reduction: routine steps use budget models ($0.15/M input tokens),
  reserving premium models ($10–15/M input) for high-value reasoning.
- Provider fault tolerance: if OpenRouter is down, direct provider API
  (xAI, Anthropic) is tried as fallback.
- Extensible: adding a new model means adding one entry to the
  model refs and one to the cascade. No flow code changes.

**Negative:**
- Model selection logic is spread across `model_refs.py`, `model_cascade.py`,
  and `model_registry.py` — three places to update.
- Cost tracking requires per-call model logging (the circuit breaker
  tracks failures but not dollar cost per model).
- `:free` suffix convention is OpenRouter-specific. Direct API calls
  (xAI, Anthropic) don't support it — need a separate free model ID.

**Compliance:** Every cascade must have at least 2 models. Every role
must have a defined model cascade. Enforced by architecture fitness
tests (`test_cascade_executor_file_exists`, etc.).
