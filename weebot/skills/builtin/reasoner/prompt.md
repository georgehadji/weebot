---
name: reasoner
description: Production-grade reasoning orchestrator with 24 multi-LLM reasoning methods (46 presets) — debate, scientific, jury, research, socratic, pre-mortem, bayesian, dialectical, analogical, delphi, CoVE, SoT, ToT, PoT, self-discover, subagent, writing, coding, brainstorming, iterative-critique, cross-language, image-generation, nvidia, and more.
metadata:
  emoji: 🧠
---

# Reasoner Bridge

You have access to **Reasoner** at `E:\Documents\Vibe-Coding\Reasoner`. This is a production-grade reasoning orchestrator that decomposes complex problems into structured multi-phase pipelines, leverages 90+ LLM models across diverse training ecosystems in parallel, applies independent critique, stress-tests solutions, and synthesizes actionable recommendations with epistemic labeling (`VERIFIED` / `HYPOTHESIS` / `UNKNOWN`).

---

## What Reasoner Does

Reasoner runs a structured 6-phase pipeline on any problem:

| Phase | What Happens | Models Used |
|-------|-------------|-------------|
| **0 — Classification** | HyperGate pre-router: classify problem type, auto-select method | Fast, cheap model |
| **1 — Decomposition** | Break problem into sub-problems with dependency graph | Primary model |
| **2 — Perspectives** | Generate diverse solution candidates from 3-4 different model ecosystems | Cross-lab diversity (DeepSeek, Qwen, Mistral, GLM, etc.) |
| **3 — Critique** | Cross-moderate and score each perspective | Independent ecosystem (different from Phase 2) |
| **4 — Stress-Test** | Adversarial challenge: edge cases, counter-arguments, failure modes | Scorer model |
| **5 — Synthesis** | Synthesize final answer with epistemic confidence label | Synthesis model |

---

## 24 Reasoning Methods — When to Use Which

| Method | Best For | Example | Presets |
|--------|----------|---------|---------|
| **Multi-Perspective** (default) | General complex problems | "Analyze our go-to-market strategy" | budget / ultra-budget / premium |
| **Debate** | Polarized decisions, trade-offs | "Build vs. buy for our data platform" | budget / premium |
| **Jury** | High-stakes decisions with multiple judges | "Should we pivot to a new market?" | budget / premium |
| **Research** | Evidence-heavy questions (web-grounded) | "Latest best practices for K8s security" | budget / premium |
| **Scientific** | Hypothesis testing & validation | "Does this compound inhibit the enzyme?" | budget / premium |
| **Socratic** | Clarifying ambiguous problems | "What are we actually trying to solve?" | budget / premium |
| **Pre-Mortem** | Risk assessment & failure analysis | "What could go wrong with this deployment?" | budget / premium |
| **Bayesian** | Probabilistic reasoning | "Given test results, chance of success?" | budget / premium |
| **Dialectical** | Thesis-antithesis-synthesis analysis | "Free will vs. determinism in AI safety" | budget / premium |
| **Analogical** | Creative cross-domain problem solving | "How would nature solve this optimization?" | budget / premium |
| **Delphi** | Forecasting & expert consensus | "AI regulation landscape in 2027?" | budget / premium |
| **Chain-of-Verification (CoVE)** | Fact-checking via draft→verify→revise | "Verify these claims about quantum computing" | budget / premium |
| **Skeleton-of-Thought (SoT)** | Fast, latency-sensitive reasoning | Quick structured answer to complex question | budget / premium |
| **Tree-of-Thoughts (ToT)** | Planning, exploration & optimization | "Find optimal multi-variable configuration" | budget / premium |
| **Program-of-Thoughts (PoT)** | Quantitative/code-first reasoning | "Calculate ROI with these parameters" | budget / premium |
| **Self-Discover** | Novel problems — auto-selects reasoning modules | Dynamically picks the best approach | budget / premium |
| **SubAgent** | Per-subagent routing with dedicated models | Multi-role analysis pipeline | budget / premium |
| **Writing / Article** | Research-backed article generation (CoVE+SoT+PreMortem) | "Write a strategic analysis memo" | budget / premium |
| **Coding** | 5-phase production code generation | "Build a REST API client library" | budget / premium |
| **Cross-Language** | Multilingual reasoning (DeepL translation) | Non-English problem analysis | budget / premium |
| **Brainstorming** | Verbalized Sampling idea generation | "Generate 15 creative marketing ideas" | budget / premium |
| **Iterative Critique** | Adversarial generator-critic loop | "Stress-test this business plan" | budget / premium |
| **Image Generation** | Generate images via LLM APIs | "Create a diagram explaining..." | budget / premium |
| **NVIDIA Nemotron** | Experimental — single-provider (NVIDIA NIM) | Testing with NVIDIA free tier | test |

---

## What Reasoner Can Generate (Image Generation)

Reasoner has built-in **image generation** presets using multiple models:

| Preset | Models | Best For |
|--------|--------|----------|
| `image-generation-budget` | Riverflow v2 Fast Preview, Gemini Flash Image, Seedream 4.5, Flux 2 Pro | Fast, cheap images for websites, UI mockups, diagrams, illustrations |
| `image-generation-premium` | Gemini 3 Pro Image, GPT-5 Image, Gemini 3.1 Flash Image | High-quality images, detailed diagrams, marketing visuals |

Use when building websites and you need placeholder images, diagrams explaining concepts, UI mockups, or any visual content. The CLI invocation:

```bash
cd E:\Documents\Vibe-Coding\Reasoner && python main.py \
  --problem "Generate an image of a modern dashboard UI with charts and graphs" \
  --preset image-generation-budget
```

---

## When to Delegate to Reasoner vs. Handle Inline

| Delegate to Reasoner ✅ | Handle in weebot ✅ |
|---|---|
| Strategic analysis & decision frameworks | Simple yes/no questions |
| Multi-perspective problem solving | Reading/answering from a single document |
| Risk assessment & pre-mortem analysis | Quick factual lookups |
| Research-backed analysis (web-grounded) | Code debugging |
| **Generating images for websites (diagrams, illustrations, mockups)** | Simple image edits or resizing |
| "What are the pros and cons of X?" | "What does this error mean?" |
| "Help me think through this complex decision" | Simple explanations |
| Epistemic uncertainty: what do we *know* vs. *hypothesize*? | Routine code edits |

**Rule of thumb:** If the question needs multiple viewpoints, structured reasoning, or has significant consequences if answered wrong → Reasoner. If it's a straightforward answer or small task → handle inline.

---

## CLI Invocation

Run Reasoner from its project directory. Always `cd` into it first so its Python imports resolve correctly.

### Basic Run

```bash
cd E:\Documents\Vibe-Coding\Reasoner && python main.py \
  --problem "Your complex question here" \
  --preset multi-perspective-premium
```

### By Method & Preset

| Use Case | Command |
|----------|---------|
| **General analysis (budget ~$0.02)** | `--preset multi-perspective-budget` |
| **Maximally cheap (<$0.01)** | `--preset multi-perspective-ultra-budget` |
| **General analysis (premium ~$0.15)** | `--preset multi-perspective-premium` |
| **Debate: polarized decision** | `--preset debate-budget` or `debate-premium` |
| **Jury: high-stakes (6 models)** | `--preset jury-budget` or `jury-premium` |
| **Research: web-grounded evidence** | `--preset research-budget` or `research-premium` |
| **Scientific: hypothesis testing** | `--preset scientific-budget` or `scientific-premium` |
| **Socratic: clarify ambiguity** | `--preset socratic-budget` or `socratic-premium` |
| **Pre-mortem: risk analysis** | `--preset pre-mortem-budget` or `pre-mortem-premium` |
| **Bayesian: probabilistic reasoning** | `--preset bayesian-budget` or `bayesian-premium` |
| **Dialectical: philosophy/ideology** | `--preset dialectical-budget` or `dialectical-premium` |
| **Analogical: creative solving** | `--preset analogical-budget` or `analogical-premium` |
| **Delphi: forecasting** | `--preset delphi-budget` or `delphi-premium` |
| **Chain-of-Verification: fact-check** | `--preset cove-budget` or `cove-premium` |
| **Skeleton-of-Thought: fast answer** | `--preset sot-budget` or `sot-premium` |
| **Tree-of-Thoughts: planning** | `--preset tot-budget` or `tot-premium` |
| **Program-of-Thoughts: quantitative** | `--preset pot-budget` or `pot-premium` |
| **Self-Discover: novel problems** | `--preset self-discover-budget` or `self-discover-premium` |
| **SubAgent: per-role routing** | `--preset subagent-budget` or `subagent-premium` |
| **Writing: research-backed article** | `--preset writing-budget` or `writing-premium` |
| **Coding: production code gen** | `--preset coding-budget` or `coding-premium` |
| **Cross-language: multilingual** | `--preset cross-language-budget` or `cross-language-premium` |
| **Brainstorming: idea generation** | `--preset brainstorming-budget` or `brainstorming-premium` |
| **Iterative Critique: adversarial loop** | `--preset iterative-critique-budget` or `iterative-critique-premium` |
| **Image generation** | `--preset image-generation-budget` or `image-generation-premium` |
| **NVIDIA Nemotron (sequential only)** | `--preset nvidia-nemotron-test --sequential` |

### Key Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--problem "..."` | required | The complex question or problem |
| `--problem-file file.txt` | — | Load problem from a text file |
| `--preset` | `multi-perspective-budget` | Named routing preset (42 available) |
| `--routing '{"primary":"..."}'` | — | Custom JSON model routing (overrides preset) |
| `--top-k N` | 2 | Number of candidates to keep after pruning |
| `--sequential` | off | Run perspectives sequentially (rate-limited providers) |
| `--quiet` | off | Suppress phase-by-phase logging |
| `--output results.json` | — | Export full pipeline state to JSON |
| `--save-state` | — | Save state for later resume |
| `--resume <path>` | — | Resume from saved state |
| `--list-presets` | — | List all 42 available presets with key status |
| `--list-models` | — | List all 90+ available model IDs |
| `--enhance-prompt` | off | Use LLM to clarify/rewrite problem before execution |
| `--force-pipeline` | off | Bypass gate agent, always run full pipeline |
| `--source-type` | `general` | Search source: general, academic, social, news, code |
| `--domain` | — | Limit web search to specific domain |

---

## API / Server Mode

Reasoner also runs as a FastAPI server with a Web UI:

```bash
# Start backend + frontend + search all at once
cd E:\Documents\Vibe-Coding\Reasoner && python start_all.py
```

This starts:
- Backend on `http://localhost:8003`
- Web UI on `http://localhost:3000`
- SearXNG search on `http://localhost:8888`

---

## How to Pass a Problem to Reasoner

1. **Choose the method** that fits the user's question (see table above).

2. **Form the problem statement** — keep it specific but don't strip context. Reasoner handles long prompts well.

3. **Select the tier:**
   - `-budget` (~$0.02/run) for exploratory questions, internal use
   - `-premium` (~$0.15-0.30/run) for important decisions, client-facing analysis

4. **Run and report back**:
   - The final answer with its epistemic label (`VERIFIED`, `HYPOTHESIS`, or `UNKNOWN`)
   - Total cost
   - Key sub-problems identified
   - Any notable disagreements or confidence levels

---

## Important Notes

- Reasoner needs an API key in its `.env` file at `E:\Documents\Vibe-Coding\Reasoner` — OpenRouter recommended (one key for 350+ models). Do NOT modify it unless the user asks.
- Budget presets cost ~$0.02/run; Premium ~$0.15-0.30/run — always use budget for exploratory questions.
- The orchestrator skill (app building), Berb skill (research papers), and Reasoner skill (structured reasoning) are three complementary tools. Choose based on the task domain, not arbitrarily.
- **Requires user approval** per use (`requires_approval_per_use: true`).
