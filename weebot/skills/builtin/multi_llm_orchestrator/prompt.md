---
name: multi_llm_orchestrator
description: Delegate full-stack app development to the Multi-LLM Orchestrator.
metadata:
  emoji: 🧠
---

# Multi-LLM Orchestrator Bridge

You have access to the **Multi-LLM Orchestrator** at `E:\Documents\Vibe-Coding\Ai Orchestrator`. This is a production-grade autonomous platform that:

- Decomposes project specs into atomic tasks
- Routes each task to the optimal LLM (52 models across 15 providers)
- Runs generate→critique→revise→evaluate cycles until quality thresholds are met
- Enforces budget hierarchy, CI-quality gating, and hallucination defenses
- Produces scaffolded, tested applications with full author attribution

---

## When to Delegate vs. Build Directly

| Delegate to Orchestrator ✅ | Build directly in weebot ✅ |
|---|---|
| Full-stack app builds (React, Next.js, FastAPI, Django) | Small fixes, single-file changes |
| Multi-file project scaffolding (10+ files) | Reading/editing existing files |
| Complex specs with success criteria | Quick scripts, utilities, config tweaks |
| Tasks requiring multiple LLM reviews/critique cycles | Simple web research, Q&A |
| "Build an X app" with no existing codebase | Modifying code you've already written |
| Projects with a budget ($ spend cap) | Tasks under 5 minutes of work |

**Rule of thumb:** If the user says "build", "create a project", "generate an app", or provides a detailed spec for something new — delegate. If they say "fix", "edit", "change", "add feature to" — build directly.

---

## CLI Invocation

Run the orchestrator from its directory:

```bash
cd E:\Documents\Vibe-Coding\Ai Orchestrator && python -m orchestrator \
  --project "Your project description here" \
  --criteria "Success criteria: what must pass/be present" \
  --budget 5.0 \
  --output-dir ./results
```

### Key Flags

| Flag | Default | When to Use |
|------|---------|-------------|
| `--project "..."` | required | Describe what to build. Be specific — include framework, features, architecture. |
| `--criteria "..."` | required | Define what "done" looks like. e.g. "pytest passes, pages load, OpenAPI docs complete" |
| `--budget N` | 8.0 | Max USD spend. Start at $2-3 for small apps, $8-10 for complex ones. |
| `--output-dir ./path` | auto | Where generated code lands. After completion, relay this path to the user. |
| `--dry-run` | off | Plan only — no code generation. Use for "what would this look like?" queries. |
| `--tdd-first` | off | Test-driven development mode — tests are written before implementation. |
| `--concurrency N` | 3 | Parallel API calls. Lower for cost control, raise for speed. |
| `--file projects/my.yaml` | — | Full project spec in YAML format (for complex/structured specs). |

### Resume a Run

```bash
cd E:\Documents\Vibe-Coding\Ai Orchestrator && python -m orchestrator --resume <project_id>
```

The orchestrator prints the `project_id` when it starts. If interrupted, find it in the output and resume.

---

## How to Pass a User's Request to the Orchestrator

1. **Extract the essence**: Translate the user's request into a concise `--project` description. Include:
   - What framework/stack to use (based on weebot-ui or their existing project)
   - Key features and functionality
   - Any architecture preferences

2. **Define criteria**: Turn their implicit "it should work" into explicit `--criteria`:
   - Build succeeds (npm build / pip install)
   - Key pages/components render
   - Tests pass if applicable
   - No console errors

3. **Set budget**: Start modest. If the user didn't specify, use `--budget 3.0`.

4. **Choose output directory**:
   - If building a standalone app → `--output-dir ./results/<app-name>`
   - If enhancing the existing weebot project → let the orchestrator scaffold and then merge manually (tell the user)

5. **Run and report**: After the orchestrator finishes, tell the user:
   - What was built
   - Where the output lives
   - Total cost / time
   - Any notable decisions the orchestrator made

---

## Sibling Tools — Use Together

While the orchestrator handles code generation, you have other tools for complementary tasks:

| Need | Use | How |
|------|-----|-----|
| **Images for the website** | **Reasoner** (`reasoner` skill) | `cd E:\Documents\Vibe-Coding\Reasoner && python main.py --problem "Generate an image..." --preset image-generation-budget` |
| **Research for site content** | **Berb** (`berb-research` skill) | `cd E:\Documents\Vibe-Coding\Berb && python -m berb run --topic "..." --auto-approve` |
| **Complex reasoning/decisions** | **Reasoner** (`reasoner` skill) | Use one of 24 reasoning methods |

When building a website that needs images (hero backgrounds, diagrams, illustrations), delegate image generation to Reasoner while the orchestrator builds the code.

---

## Important Notes

- The orchestrator has its own `.env` with API keys — do NOT modify it unless the user explicitly asks.
- It installs its own dependencies — if it fails on missing packages, suggest the user run `pip install -e ".[dev,security,tracing]"` in the orchestrator directory.
- After the orchestrator finishes, the generated code is in its `--output-dir`. You can then read/edit that code just like any other file.
- The orchestrator handles its own LLM routing, budget, and retries — you don't need to manage those.
- **Requires user approval** for each use (the `requires_approval_per_use` flag is set in manifest.json).
