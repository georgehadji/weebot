# Running OSWorld with weebot

This package lets weebot act as the agent in the
[OSWorld](https://os-world.github.io) benchmark — *Benchmarking Multimodal
Agents for Open-Ended Tasks in Real Computer Environments* (Xie et al., 2024).

## What the paper proposes

OSWorld is a **real, executable computer environment** (Ubuntu/Windows/macOS
in a VM) for evaluating multimodal agents on open-ended tasks. Each of its 369
tasks is a POMDP:

- **Observation** — a screenshot of the desktop plus an accessibility (a11y)
  tree (AT-SPI on Linux). Optionally Set-of-Mark overlays.
- **Action** — executable `pyautogui` code (`pyautogui.click(x, y)`,
  `pyautogui.write(...)`, `pyautogui.hotkey(...)`), plus the special tokens
  `WAIT`, `FAIL`, `DONE`. Episodes cap at ~15 steps.
- **Reward** — an **execution-based** evaluator script inspects the final
  machine/cloud state (files, cookies, app state) and returns a score in
  `[0, 1]`. There are 134 unique evaluation functions across the suite.

The headline finding: the best baseline scored **12.24%** vs **72.36%** for
humans — agents struggle with GUI grounding, coordinate precision, and
operational knowledge. The paper argues progress needs better grounding,
higher-resolution perception, longer trajectory history, and agent
architectures with exploration / memory / reflection.

## Components in this package

| File | Role |
|---|---|
| `agent_adapter.py` | `WeebotOSWorldAgent` — drop-in replacement for OSWorld's `mm_agents.agent.PromptAgent`. Implements the exact `predict(instruction, obs) -> (response, actions)` / `reset(logger, vm_ip=...)` contract, emitting `pyautogui` code through weebot's resilient LLM stack. |
| `run_benchmark.py` | Operator entry point. Mirrors OSWorld's `run.py` but wires in the weebot agent. |
| `parse_pyautogui_code` | Self-contained action parser matching OSWorld's `parse_code_from_string` (so the adapter is testable without OSWorld installed). |

The adapter contract is covered by `tests/unit/test_osworld_adapter.py`
(no VM, no network).

## Prerequisites

Running the actual benchmark is heavy and **cannot run in CI** — it needs a
real VM. You provide:

1. **An OSWorld checkout** (for `desktop_env` and `lib_run_single`):
   ```bash
   git clone https://github.com/xlang-ai/OSWorld
   cd OSWorld && pip install -r requirements.txt
   export OSWORLD_HOME=$(pwd)
   ```
2. **A virtualization provider** with the OSWorld Ubuntu image. Supported:
   `vmware`, `virtualbox`, `docker`, `aws`, `azure`, `gcp`. See OSWorld's
   `SETUP_GUIDELINE.md`. VMware/VirtualBox need the downloaded VM snapshot;
   Docker/AWS provision automatically.
3. **A model API key** for weebot's LLM adapter:
   ```bash
   export OPENROUTER_API_KEY=...      # or OPENAI_API_KEY
   ```

## Run

Smoke test on a single domain:

```bash
export OSWORLD_HOME=/path/to/OSWorld
export OPENROUTER_API_KEY=...
python -m weebot.osworld.run_benchmark \
    --provider_name vmware \
    --model openai/gpt-4o \
    --observation_type screenshot_a11y_tree \
    --domain chrome \
    --max_steps 15
```

Full suite: drop `--domain` (defaults to `all`). Results, screenshots, and
`traj.jsonl` per example land under `--result_dir` (default `./results`), and
the average score prints at the end.

### Key flags

| Flag | Default | Notes |
|---|---|---|
| `--provider_name` | `vmware` | VM backend |
| `--model` | `openai/gpt-4o` | Any model weebot's OpenAI-compatible adapter routes (OpenRouter ids work) |
| `--observation_type` | `screenshot_a11y_tree` | `screenshot`, `a11y_tree`, `screenshot_a11y_tree`, `som` |
| `--max_steps` | `15` | Episode cap (paper uses 15) |
| `--max_trajectory_length` | `3` | Recent obs/action pairs fed back into the prompt |
| `--domain` | `all` | Single domain for a quick run |
| `--osworld_home` | — | Overrides `OSWORLD_HOME` |

## Notes & possible improvements

- The a11y tree is currently passed as lightly-trimmed text. For higher
  fidelity, reuse OSWorld's `linearize_accessibility_tree` (tab-separated
  table) before sending to the model — the paper shows the linearized form
  measurably helps grounding.
- `WeebotOSWorldAgent` only supports `action_space="pyautogui"` (the paper's
  universal action space). The `computer_13` dict space is intentionally not
  supported.
- To plug in weebot's planner/reflection loop (the paper's suggested
  direction for better architectures), drive `predict` from a weebot flow
  instead of a single LLM call — the contract (return `(response, actions)`)
  stays the same.
