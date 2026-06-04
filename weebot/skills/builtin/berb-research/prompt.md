---
name: berb-research
description: Autonomous 23-stage research pipeline that produces academic papers.
metadata:
  emoji: 📚
---

# Berb Research Bridge

You have access to **Berb** at `E:\Documents\Vibe-Coding\Berb`. This is a production-grade autonomous research system that transforms a single research idea into a conference-ready academic paper through a 23-stage pipeline, costing $0.40–0.70 per paper.

## What Berb Does

| Phase | Stages | What Happens |
|-------|--------|-------------|
| **A — Scoping** | 1–2 | Topic initialization, problem decomposition |
| **B — Literature** | 3–6 | Search strategy, literature collection, screening, knowledge extraction |
| **C — Synthesis** | 7–8 | Synthesis, hypothesis generation |
| **D — Design** | 9–11 | Experiment design |
| **E — Execution** | 12–13 | Experiment run, iterative refinement |
| **F — Analysis** | 14–15 | Result analysis, research decision |
| **G — Writing** | 16–19 | Paper outline, draft, peer review (5-reviewer ensemble + Area Chair), revision |
| **H — Finalization** | 20–23 | Final polish |

**Key capabilities:**
- Multimodal literature search (arXiv, OpenAlex, Semantic Scholar, SearXNG, figures/tables)
- Self-correcting simulation with physics-aware error diagnosis
- 5-reviewer + Area Chair peer review ensemble
- Multi-language support (13 languages)
- Experiment execution (Docker, Colab, SSH, local sandbox)

---

## When to Delegate to Berb vs. Do It Yourself

| Delegate to Berb ✅ | Handle in weebot ✅ |
|---|---|
| "Research this topic and write a paper" | Quick web research for facts |
| "Do a literature review on X" | Reading documentation |
| "Generate hypotheses for Y problem" | Summarizing a single article |
| "Design and run experiments for Z" | Simple data analysis |
| Full academic paper generation | Quick answers, code fixes |
| "Investigate deeply: what does the literature say about..." | Browsing a known website |
| Conference submission preparation | One-off code generation tasks |

**Rule of thumb:** Academic depth, papers, literature reviews, experiments, and hypothesis generation → Berb. Everything else stays in weebot.

---

## CLI Invocation

Run Berb from its project directory:

```bash
cd E:\Documents\Vibe-Coding\Berb && python -m berb run \
  --topic "Your research topic or question" \
  --auto-approve \
  --output ./artifacts/<run-name>
```

### Key Commands

| Command | Purpose |
|---------|---------|
| `berb run --topic "..."` | **Main command** — run the full 23-stage pipeline |
| `berb run --topic "..." --from-stage PAPER_OUTLINE` | Resume from a specific stage |
| `berb run --topic "..." --auto-approve` | Run without gate stops (recommended for weebot delegation) |
| `berb doctor` | Health check — verify environment and config |
| `berb init` | Create `config.arc.yaml` from template (if not already set up) |
| `berb setup` | Install optional tools (OpenCode) |
| `berb report --run-dir <path>` | Generate a human-readable report from a completed run |
| `berb validate` | Validate the current configuration |
| `berb literature` | Literature-specific operations |
| `berb write` | Paper writing commands |
| `berb experiment` | Experiment execution commands |
| `berb review` | Peer review commands |
| `berb dashboard` | Start a dashboard server |
| `berb serve` | Start the web server |

### Run Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--topic "..."` | required | The research topic or question |
| `--output` | `./artifacts/<run-id>` | Output directory for artifacts |
| `--from-stage` | — | Resume from a specific pipeline stage name |
| `--auto-approve` | off | Auto-approve all gates (use for unattended runs) |
| `--config` | auto-detect | Override config file path |
| `--skip-preflight` | off | Skip LLM connectivity preflight check |
| `--resume` | off | Resume the most recent incomplete run |
| `--skip-noncritical-stages` | off | Skip (don't fail) on noncritical stage errors |
| `--no-graceful-degradation` | off | Fail pipeline on quality gate failure instead of degrading |

---

## How to Pass a Research Request to Berb

1. **Extract the research question** from the user's request. Make it specific and clear.
   - Good: `--topic "Attention mechanisms in Vision Transformers for medical image segmentation"`
   - OK: `--topic "How do transformers work for images"`

2. **Choose your flags:**
   - Always use `--auto-approve` when delegating from weebot (non-interactive)
   - Set `--output ./artifacts/<short-name>` so you know where results go
   - If they want a quick survey, add `--from-stage PAPER_OUTLINE` to skip experiments

3. **Run and report** — after Berb finishes, tell the user:
   - What was researched
   - Where the output lives (`artifacts/<run-id>/`)
   - Key findings from the paper/synthesis
   - Any notable decisions

---

## Important Notes

- Berb needs its own API keys configured in `.env` at `E:\Documents\Vibe-Coding\Berb\` — do NOT modify them unless the user asks.
- Run `berb doctor` first if you're unsure whether it's configured correctly.
- First-time setup requires running `berb init` to create `config.arc.yaml`.
- Output lands in the `./artifacts/` directory under the Berb project — you can read those files normally.
- **Requires user approval** per use (the `requires_approval_per_use` flag is set).
- The orchestrator skill (for app building) and this Berb skill (for research) are complementary — use the right tool for the right job.
