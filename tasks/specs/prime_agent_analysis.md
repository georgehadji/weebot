# Prime Agent: how it works, and what weebot should take from it

**Date:** 2026-08-06
**Sources:** `PrimeIntellect-ai/prime-agent` (main, 1133 files, TypeScript monorepo + Python skills); https://www.primeintellect.ai/blog/prime-agent
**Method:** direct source reads. Every weebot claim below carries a `file:line` citation and a WIRED/DEAD verdict.

---

## 1. What Prime Agent is

Two abstractions, and the terminology is defined precisely in the codebase itself
(`packages/coding-agent/src/core/prompts/rlm.ts:31`):

> "continual harness names the persisted prompt, memory, skill, and subagent layer; RLM names the runtime, IPython kernel, and native call interface exposed to the model."

**RLM (Recursive Language Model)** — the runtime. A long-lived IPython kernel is the
agent's primary tool interface. Sub-agents, tools and skills are all *Python functions
called inside that kernel*, not JSON tool-call schemas.

**Continual Harness** — the mutable state. The harness is formalised as
`H = (ρ, G, K, M)` — prompt, sub-agents, skills, memory — and all four expose the
same CRUD surface *to the agent itself*, at runtime, mid-task.

The thesis: harness components should be **mutable by the agent during execution**,
rather than static scaffolding fixed at design time. Improvement comes from
accumulated experience, not configuration.

---

## 2. How it actually works

### 2.1 The kernel as tool substrate

Tool calls are `await` expressions. Their return values bind to Python variables and
compose into ordinary program logic (`rlm.ts:27`). Consequences the design leans on:

- Intermediate results stay in kernel variables instead of being re-serialised into
  context every turn. State survives compaction.
- Installed Python skills are **pre-imported modules** — `await <skill>.<fn>(...)`.
  Discovery is `help()` / `dir()` / `inspect.signature()`, not a tool manifest.
- `%%bash` cells are throw-away subshells; `%cd` and `os.environ` are the kernel-level
  escapes that persist (`rlm.ts:25`).

A deliberate anti-pattern is called out at `rlm.ts:21`: do **not** install a project's
dependencies into the agent kernel to make it importable. Evaluate external systems
through their own interface; use the kernel only to coordinate. Similarly `rlm.ts:33`
forbids inventing wrappers like `call_skill(...)` or `run_subagent(...)`.

### 2.2 The harness CRUD surface

Exposed to the model as `rlm.harness` and `rlm.get_harness_state()` (`rlm.ts:29`):

```
create_memory / update_memory / delete_memory
create_skill  / update_skill  / delete_skill
create_subagent / update_subagent / delete_subagent
create_prompt_note / update_prompt_note / delete_prompt_note
record_refinement(...)   overview()
```

Calls are session-local by default; `global_=True` targets the cross-session store
(the odd spelling is because `global` is a Python keyword).

### 2.3 `/refine` — the self-improvement loop

From `skills/refine/SKILL.md`:

- `await refine.run(instructions=None, global_=False)` returns `{"scheduled": True}`
  **immediately**.
- Refinement **never runs mid-cell**. A scheduled refinement runs when the current turn
  ends; the harness applies changes, **rebuilds the system prompt**, then resumes the
  agent automatically.
- `await refine.status()` exposes `pending` and `in_flight`.
- One request per turn; a second call before turn end only updates the instructions.

The doctrine that drives it (`rlm.ts:158`) is explicitly *minimal-edit*: diagnose →
update the smallest relevant component → validate on the next action → record the
outcome. Repeated delegation patterns become subagent specs; repeated procedures become
skills; durable facts become memories; narrow policies become prompt addendums.
"Do not rewrite the whole continual harness when a focused memory, skill, prompt note,
or subagent spec is enough."

### 2.4 Sub-agents: admission, not completion

The single most consequential design choice (`rlm.ts:129`):

> `await rlm('sub-task')` spawns a child and returns immediately after task admission
> with `rlm_child_id`, `name`, `session_dir`, and `model`; **it never waits for or
> returns the child's answer.**

Results arrive only via messaging or files (`rlm.ts:33`). The parent is told to spawn
independent children in separate calls and **end its turn** rather than await them
(`rlm.ts:149`). Children inherit the parent's model unless one is explicitly requested
via `rlm.find_models(...)`. Handles are recoverable after kernel restart or compaction
with `rlm.list_subagents()`; children are deleted explicitly with
`rlm.delete_subagent(child)`.

This is fire-and-forget with mid-flight steering — structurally different from a
blocking `dispatch(...)` that returns a finished result.

### 2.5 Agent-to-agent messaging and observation

Messaging is restricted to the **nuclear family** — parent, siblings, direct children.
Roots count as siblings; deeper communication **relays through the intermediate child**
(`rlm.ts:117`). A child replies with
`await agent_message.send(msg, receiver_role="parent")`; not every task requires a reply
(`rlm.ts:54`).

`agent-observe` is the read-only twin (`skills/agent-observe/SKILL.md`): list family,
inspect one session, fetch bounded recent-message previews (`limit` 1–50, `max_chars`
80–2000). It explicitly "cannot prompt, steer, clear, kill, rename, or otherwise mutate
another session," and targets outside the family are rejected. Notably it also advises
asking the user before using observed context to steer another session.

### 2.6 Autonomy: goals and heartbeats

**Goals** (`skills/goal/SKILL.md`) — a persistent objective the harness **keeps
re-prompting** across turns until complete. `goal.create(objective, token_budget=None)`;
state carries `status`, `token_budget`, `tokens_used`, `time_used_seconds`. Crucially:
the harness continues the goal until `goal.complete()` is *called* — saying "done" in
prose is not enough. Guardrail: only create a goal when explicitly asked; don't infer
goals from ordinary tasks. And don't call `complete()` merely because the budget ran out.

**Heartbeats** (`skills/rlm-heartbeat/SKILL.md`) — recurring prompts injected into the
*live* session, default every 5m. The important detail is `delivery_mode`:

- `steer` (default) — **interrupt the current turn** so the heartbeat runs promptly.
- `follow_up` — wait for the current turn to finish.

Agent-owned RLM heartbeats are deliberately separated from the user-visible
`/heartbeat`; the skill cannot touch the user's.

### 2.7 Skills

Prime Agent follows the [Agent Skills standard](https://agentskills.io/specification)
and extends it with Python-backed skills (`skills/skill-creator/SKILL.md`). Two
properties matter:

- **Progressive disclosure**: at startup only each skill's `name` and `description`
  enter the system prompt; the body loads on demand. Push exhaustive detail into
  `references/*.md`.
- **A missing or empty description means the skill is silently not loaded.**

Precedence on name collision: explicit `--skill` paths / settings → project
(`.prime/agent/skills/`) → global (`~/.prime/agent/skills/`) → package → built-in.
`/reload` picks up new skills without a restart.

### 2.8 Sessions, daemon, compaction

A background daemon supervises live sessions over local sockets with worker crash
recovery. Sessions are append-only JSONL; branching/forking/cloning happen *within a
single session file* by moving a leaf pointer. Compaction runs at a threshold or
on demand via `compact.run()`, with separate branch summarisation. `packages/ai` is a
substantial multi-provider layer (Anthropic, OpenAI, Bedrock, Vertex, Mistral,
Cloudflare, Azure, Copilot) with OAuth, cache pricing, and a 546KB generated model
registry.

---

## 3. Honest assessment

**Genuinely novel / well-executed:**

- *Admission-not-completion* sub-agents. Most harnesses (including Claude Code's Task
  tool and weebot's `DispatchAgentsTool`) block until the child finishes. Returning at
  admission enables real fan-out plus mid-flight steering.
- *The nuclear-family constraint on messaging.* A concrete, enforceable answer to
  "which agents may talk to which" that scales without becoming a broadcast bus.
- *Minimal-edit refinement applied at turn boundary, then prompt rebuild.* The
  scheduling discipline (never mid-cell) is the part that makes self-modification
  tractable.
- *Heartbeat `steer` vs `follow_up`.* Small distinction, big behavioural difference.

**Repackaged:** the skills layer is the Agent Skills standard. The provider abstraction
is conventional. "Code as the tool interface" is the CodeAct / smolagents line of work.

**Risks the authors surface themselves:** in the Factorio case study the agent
discovered a **reward hack** — spawning resources via RCON — while iteratively refining
its own skills. That is the self-refinement loop working exactly as designed and
producing the wrong thing. Any port of this must treat "the agent can edit its own
harness" as a security boundary, not a feature flag.

**Caveat on the headline number:** ARC-AGI-3 95.5% RHAE Best@1 vs a 95.4% human-expert
baseline is Opus 5 doing the reasoning. The authors state plainly that **no model has
been trained around Prime Agent's feature set**, and that many features are
underutilised without model support. Read the benchmark as a harness-plus-frontier-model
result, not a harness result.

---

## 4. Where weebot actually stands

Corrections to assumptions first — **weebot already has these; do not "adopt" them:**

| Capability | Reality |
|---|---|
| Trust-tiered skills | `quarantined → candidate → trusted`, `domain/models/skill.py:17-22`. Only `trusted` is injected at inference (`skill.py:279-283`). This is *stronger* than prime-agent's ungated harness CRUD. |
| Promotion gate | `domain/services/skill_promotion_gate.py`; `record_positive_use` auto-promotes candidate→trusted at threshold (`skill.py:291-303`). |
| Skill distillation from trajectories | `application/services/autonomous_learning.py` — LLM extracts a reusable procedure post-task. |
| Cron / scheduled work | Real scheduler, `scheduling/scheduler.py:577` `_run_cron_job`, plus `nl_cron.py` natural-language scheduling. |
| Composable termination | `MaxIteration`, `TokenBudget`, `WallClock`, `TextMention` — `application/termination/conditions.py`, composable via `__or__`. |
| Parallel sub-agents | `DispatchAgentsTool`, plus `swarm.py`, `debate.py`, `mixture_of_agents.py`, `workflow_orchestrator.py`. |
| Untrusted-content handling | `core/trust_boundary.py`, `core/egress_guard.py` (explicit "lethal trifecta" modelling), `core/secret_redaction.py`, `core/bash_guard.py`. **Materially ahead of prime-agent here.** |
| Benchmark harness | `application/harness/` = `BenchmarkRunner` over `WeebotTask` samples with scoring (`harness/runner.py:45-152`). |

**Important terminology clash:** weebot's `application/harness/` is an *offline
evaluation* harness. Prime-agent's "continual harness" is *runtime-mutable agent state*.
Same word, unrelated concepts. Do not conflate them when naming new modules.

### Two confirmed defects found during this audit

**D1 — `subagent_rpc` is exposed to the model but structurally broken.**
`SubagentRPCTool` is auto-registered (`infrastructure/adapters/tool_discovery.py:61`).
Its RPC dispatch requires `set_tool_registry()`:

```python
# weebot/tools/subagent_rpc.py:150-162
if self._tool_registry is None:
    return {"success": False,
            "error": f"tool registry not wired — cannot execute '{tool_name}'. ..."}
```

`set_tool_registry()` is **never called anywhere in the repo** (verified by grep across
`*.py`). Every `rpc_call()` therefore fails. Separately, the tool list handed to the
child script is hardcoded:

```python
# weebot/tools/subagent_rpc.py:262-264
# NOTE: In production, tool registration would be injected via DI
tool_registry = json.dumps(["bash", "python_execute", "web_search", "file_editor"])
```

The error path is honest (it correctly refuses to fabricate success — the comment at
`:153-155` shows this was a deliberate fix after the `delegate_task` stub). But the tool
still advertises a capability it cannot deliver. **Either wire it in DI or unregister it.**

**D2 — the experience→skill loop is open.** This is the real finding.

`AutonomousLearningService` saves distilled skills as **quarantined**
(`autonomous_learning.py:5,92,154-156`). `is_injectable` requires `trusted`
(`skill.py:279-283`). `record_positive_use` only promotes **candidate→trusted**;
quarantined skills "are never auto-promoted here — they must first pass validation
(Phase 1) to become candidates" (`skill.py:291-296`).

Nothing in production performs that quarantined→candidate validation. The only code that
ever creates a `candidate` is `application/services/mcp_tool_skill_indexer.py:104`
(MCP tool indexing). `with_trust()` appears only in `domain/models/skill.py:285` and in
tests (`tests/unit/domain/models/test_skill_phase0.py`).

**Net effect: every skill weebot distills from its own experience is written to storage
and can never be used.** The loop is architecturally complete except for one missing
promoter. This matches the previously-recorded "live experience→skill loop never closed"
finding and is still present.

Note the distillation service is additionally gated behind
`LIVE_SKILL_DISTILLATION_ENABLED`, falling back to `_NoOpDistiller`
(`autonomous_learning.py:11-12`) — so on default config the loop does not even start.

---

## 5. Recommended adoptions, ranked by value / effort

### A1 — Close the quarantined→candidate promoter (HIGH value, SMALL effort)

The highest-leverage change in this document, and it is not a port — it is finishing
existing weebot architecture. Everything downstream (promotion gate, trust tiers,
injection) already works.

Build a `SkillValidationService` in `weebot/application/services/` that takes a
quarantined skill, runs it against held-out tasks using the **existing**
`BenchmarkRunner` (`application/harness/runner.py`) and `TaskScorer`, and calls
`skill.with_trust("candidate")` + `skill_store.save(...)` on pass. A
`ValidateTransferHandler` already exists in the CQRS handler set
(`application/cqrs/handlers/__init__.py:230`) — check whether it can be extended rather
than duplicated.

Then flip `LIVE_SKILL_DISTILLATION_ENABLED` on behind config, and log every promotion.
Dependency direction stays clean: Application → Domain.

### A2 — Adopt minimal-edit refinement, scoped to memory + prompt notes (HIGH / MEDIUM)

Port the *discipline*, not the full CRUD surface. Specifically:

- Schedule refinement, never run it mid-step; apply at step boundary; rebuild the system
  prompt; resume. This maps onto weebot's existing `flow_state_machine.py` /
  `step_pipeline_orchestrator.py` boundaries.
- Constrain to **smallest relevant edit** — one memory or one prompt note, not a
  rewrite.
- Reuse the trust tiers: refinement output enters as `quarantined`/`candidate`, never
  straight to `trusted`.

Do **not** give the agent `delete_*` on its own harness in v1, and do not expose
`create_subagent`. See §6.

### A3 — Non-blocking sub-agent handles (MEDIUM–HIGH / LARGE)

weebot's `DispatchAgentsTool` blocks. Admission-style spawning would allow fan-out plus
steering. This is a genuine architectural gap — but it requires a session supervisor that
outlives the foreground CLI process, which weebot does not have
(`scheduler.py:577` spawns *new* flows via `flow_factory`; it does not attach to running
ones).

Sequence it behind A1/A2 and treat it as a project, not a patch. Prerequisite: a session
registry keyed by id with resumable state in `infrastructure/persistence/`. Adopt the
**nuclear-family restriction** from day one if inter-agent messaging is added — retrofitting
an access model onto a message bus is much harder than starting with one.

### A4 — Heartbeat delivery into a *live* session (MEDIUM / MEDIUM)

weebot's scheduler spawns fresh flows. Prime-agent's heartbeat injects a recurring prompt
into a running session with `steer` (interrupt) vs `follow_up` (queue) semantics. For
long-running weebot tasks — "check the build every 5 minutes while you keep working" —
this is the missing primitive. Depends on A3's session registry.

### A5 — Persistent execution kernel (MEDIUM value, LARGE effort, LOW confidence)

Verified: weebot has **no** persistent kernel. IPython is commented out
(`requirements.txt:91`), and `python_execute` is documented as a *sandboxed subprocess*
(`tool_discovery.py:85-91`) — fresh each call, no surviving variables.

The benefit is real (state survives compaction; results compose in variables). But it
collides directly with weebot's security posture — `bash_guard.py`, `egress_guard.py`
and `trust_boundary.py` all assume a mediated, inspectable tool boundary. A persistent
kernel where the model writes arbitrary Python is a much wider attack surface, and
weebot's untrusted-content handling is one of its genuine strengths.

**Recommendation: do not adopt wholesale.** If pursued, scope it to a stateful *analysis*
sandbox with no network and no filesystem write, distinct from the tool path. Prototype
and measure before committing.

### A6 — Skill progressive disclosure (LOW–MEDIUM / SMALL)

Load only `name` + `description` into the system prompt at startup; load the body on
match. Cheap context win if `skill_registry.py` does not already do this — verify first.

---

## 6. What NOT to adopt

- **Unrestricted agent self-deletion of harness state.** Prime-agent exposes
  `delete_memory`/`delete_skill`/`delete_subagent` to the model with no rollback or
  approval gate visible in the skill contracts. weebot's trust tiers exist precisely to
  prevent unvalidated state reaching inference. Keep the gate; adopt create/update only.
- **Runtime `create_subagent`.** Agent-authored sub-agent specs compound the reward-hacking
  risk the Factorio case study demonstrates. Static roles in `application/agents/` are
  the safer default.
- **The `application/harness/` rename.** Leave the benchmark harness alone. Name any new
  runtime-mutable state module something unambiguous — e.g. `application/continual_state/`.
- **The multi-provider layer.** weebot already has `model_cascade` + `model_registry`
  with cost-tiered cascading. Prime-agent's is broader, not better-suited.
- **Blanket "agent edits its own prompt."** Adopt prompt *notes* (append-only, scoped,
  revertible), not prompt replacement.

---

## 7. Suggested sequencing

1. **Fix D1** — wire `set_tool_registry()` in DI, or unregister `subagent_rpc`. One-line
   decision, removes a broken capability from the model's menu.
2. **A1** — close the promoter. Turns an entire dormant subsystem on.
3. Measure: does skill reuse actually improve task scores? Use the existing
   `BenchmarkRunner` + `comparison_runner.py`. **Do not build A2–A4 until A1 shows a
   signal** — the previously-recorded bilevel-autoresearch finding was that adding more
   context to a fixed loop gains nothing.
4. **A2** — refinement discipline, memory + prompt notes only.
5. **A3/A4** — session registry, then non-blocking handles, then live heartbeats.

---

## 8. Evidence gaps

Two full research runs were killed by session usage limits before producing output, so
the following were **not** verified at source and are stated from the blog or from the
agent-facing skill contracts rather than the TypeScript implementation:

- The daemon socket protocol, JSONL record shape, and the leaf-pointer branch/fork
  mechanism (blog + `AGENTS.md:35-42` protocol-versioning rules only).
- The internals of `core/refinement/refinement.ts` (42KB) — the *contract* is verified
  from `skills/refine/SKILL.md` and `prompts/rlm.ts`, but the validation and rollback
  guardrails inside the implementation are **UNVERIFIED**. Confirm before porting A2.
- `core/kernel/state-snapshot.ts` and `fork-server.ts` — whether session branching uses
  real process forking or variable snapshotting is **UNVERIFIED**.
- weebot-side: `plan_act_flow.py` (46KB) was not read end-to-end; the claim that no
  compaction exists in weebot is **UNVERIFIED** (grep-level only, and grep for
  `compact` was not completed).
