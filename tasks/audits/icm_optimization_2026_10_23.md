# ICM optimization research (2026-10-23)

Question: where can the Interpretable Context Methodology (ICM: one folder one job, small routing files, load only what a step needs, files as state, human gates on editable outputs) make Weebot faster, cheaper or easier to change?

There are two subjects:

- **A. The repo.** The tree that agents and people edit. Its ICM form is a System map, already in progress under `map/`.
- **B. Weebot's runtime.** What the agent loads and writes on each run. Here ICM's "load only what the step needs" applies to every LLM call.

The biggest win is in B. It was measured, not estimated.

## B1. Every executor call sends all 171 tool definitions (highest value)

**Measured.** A billed run of "Look up today's weather in Athens and summarise it in one sentence" made 8 executor calls on DeepSeek V4.1 Flash 1017:

| | per call |
|---|---|
| prompt tokens (provider usage) | 52,424 to 54,411 |
| tools sent | 171 (57 built-in, 114 MCP) |
| tool-definition share | about 49,250 tokens (about 94%) |

That is about 425k prompt tokens for a one-sentence answer. ICM's healthy band is 2k to 8k per step.

**Why it happens:**

- `CascadeExecutor` sends `self._tools.to_params()` on every call (`weebot/application/agents/executor/_cascade.py:342`, `_base.py:750`).
- `build_tools` gives every role every configured MCP tool (`weebot/interfaces/factories.py`, `_configured_mcp_tools`).
- Scoping exists but is not wired. `ToolAssembler` returns the full set when there is no `mcp_bridge` (`weebot/application/flows/collaborators/tool_assembler.py:53`), and `create_flow` never passes one (`PlanActFlowConfig.mcp_bridge` stays None, `plan_act_flow_config.py:198`).
- The largest definitions are MCP: `mcp__apify__search_actors` (about 1,300 tokens), the HubSpot search, create and update tools, and Apify `call_actor`. Each costs as much as a whole stage contract.

**ICM move: a per-step tool contract.** A step loads the tools it needs, as a stage loads its inputs:

1. **Core set, always sent:** `web_search`, `file_editor`, `python_execute`, `bash`/`powershell`, `advanced_browser`, `ask_human`, `terminate`, `todo_write`. About 10 tools, roughly 4k tokens.
2. **Category set:** keyed by the step's existing `TaskCategory` (`weebot/application/services/task_model_router.py:16`). For example, `research` adds `vane_search`, `moli_fetch` and `search_history`.
3. **MCP tools only when the step names their service:** Jira, HubSpot, Apify, Postiz, or by retrieval (`apply_mcp_tool_scope`, `weebot/application/flows/mcp_scope.py`). Otherwise send one short "connected services" line so the planner knows they exist.
4. **Escape hatch:** if the model calls a tool outside the set, the collection already resolves it by name (`ToolCollection.execute`). Add a note that lists the other tool names without their definitions.

**Expected effect:** about 52k down to 6k to 12k tokens per call, so 4 to 8 times fewer input tokens. That means lower latency on every step and better tool choice (fewer near-duplicates such as `web_search` vs `vane_search` vs `agent_reach`).

**Check:** rerun the same weather task with the same token hook (patch `CascadeExecutor._call_completed` to record `prompt_tokens`), then the 45-task regression set. Pass means the same task score at lower tokens.

**Risk:** a step misses a tool it needed. The escape hatch and the regression set cover this.

## B2. The plan review becomes an edit surface

Today the plan is shown in the terminal, and the user answers in text ("approve" or a change request). FlowRouter then re-plans from that text.

**ICM move:** write the plan to a file the user can edit before approving, for example `Output/<session-id>/01_plan.md`. On "approve", the flow reads the file back, so an edited step list is the plan that runs. The run's later artifacts (step outputs, final answer) go in the same folder, numbered in order: `02_steps/`, `03_result.md`. Run status is then readable from the folder, and a person can fix a step's input before a resume.

This also replaces today's ad-hoc `Output/` names (`ab`, `ab3`, `agentuses2`, `vfm2` and others) with one folder per run.

**Scope:** `PlanReviewState` (`weebot/application/flows/states/plan_review.py`) and the resume path. The SQLite store stays the system of record.

## B3. Where ICM should not be applied

- **Session state stays in SQLite** (WAL, event store). The web server runs concurrent sessions, and ICM names high concurrency as where it loses.
- **The cascade and hedging stay code.** That is automated mid-run branching, also outside ICM.
- **The skill retriever already follows ICM.** Skills are L3 factory (`weebot/skills/builtin/*/SKILL.md`), retrieved per step by BM25 or semantic search, not all injected. Keep it.
- **Step context scopes already follow ICM.** `ContextScope` minimal/full selects which prompt sections a step loads (`weebot/application/agents/executor/_prompt_builder.py:19`). B1 extends the same idea to tools.

## A. The repo (System map form)

Status: slices 0 to 3 of `tasks/icm_plan.md` are done (every noun in `map/objects/_index.md` links a card). Slices 4 to 7 are not.

### A1. Walk test result

| Check | Result |
|---|---|
| Root entry file to map in one hop | pass (`CLAUDE.md`: "Before editing unfamiliar code, open `map/CLAUDE.md`") |
| `map/` answers name collisions without a card | pass (`map/CONTEXT.md` table) |
| One card cites source, states the why, gives Hits / Does not hit | pass (40 verified cards) |
| "I am changing X: what moves?" from `effects/` | **fail**: `map/effects/` does not exist (slice 5) |
| Processes (turn, guard chain, cascade, persist) | **fail**: `map/processes/` does not exist (slice 4) |
| Root entry file under about 60 lines, routing only | **fail**: `CLAUDE.md` is 96 lines and carries content payload (below) |

### A2. Slim the root entry file (L0)

`CLAUDE.md` (96 lines; its three generated twins follow it) is loaded into every agent session in this repo. Two sections are rules for one kind of task, not routing:

- "Website Generation Standards (MANDATORY)" (`CLAUDE.md:67-79`)
- "AI Orchestrator Delegation" (`CLAUDE.md:89-91`)

Both apply only to website or app builds. Their home is the factory those tasks already load: the `multi_llm_orchestrator` skill and a web-build skill. Leave one routing line each. The target is under 60 lines: Commands, layer rule, map pointer, the ratchet rule, and where-to-go rows.

### A3. Finish the map (slices 4 to 6)

1. **`processes/`:** only the movements that run. One turn of `flow run` (plan, review, execute, verify, complete); the tool-call guard chain (GuardedTool, approval, egress); the model cascade with hedge; session persistence; MCP tool loading.
2. **`effects/CONTEXT.md`:** "changing X, open these cards". Start with the hubs that every Wave G fix touched: `factories.create_flow` and `build_tools`, `ToolCollection`, `tool_guards`, `SkillRegistry`, `trust_boundary`.
3. **Generate `objects/_index.md` from card frontmatter** with a script; never hand-edit it (invariant 9). It is hand-edited today.
4. **Staleness check:** a script that fails when a card's `path:line` citation no longer exists, or when the cited file changed after the card's `commit`. The RoleBasedToolRegistry card already drifted. A verified card that is silently wrong costs more than a missing one.

### A4. `tasks/`: two forms mixed in one folder

`tasks/` holds 186 files of two kinds:

- **Eval tasks** (factory, reused every run): `browser_*`, `email_*`, `linkedin_*`, `sample_*`, `dentist_website`, each `task.md` + `samples.json`. These are a Pipeline's inputs. Give them their own `evals/` shelf with a `CONTEXT.md` that says how they run and what passes.
- **Plans, specs and audits** (records that accumulate): `plans/` (14), `specs/` (71), `audits/` (31), `new-skills/` (36), plus root plan files. These are a Record library. Each record gets frontmatter (`status: open | done | superseded`, `date`, `supersedes`), and a generated `tasks/_index.md` lists open work.

**One home per fact.** Fix status is written twice today:

- `tasks/icm_fix_plan.md` has the F table with hashes.
- `tasks/remaining_fix_plan.md` repeats the hashes in prose. For example, F38's `89d20bd9` appears in both.

Keep the F table as the only status home, and have `remaining_fix_plan.md` link to it.

### A5. Root clean-up (slice 7; needs a referrer check, then approval)

61 tracked files sit at the root. Candidates per the method's Dead role are below. None should move until `tasks/icm_slice1_references.md`'s checks run on each file.

| Files | Role |
|---|---|
| 13 transcript files (`transcript_*.txt/json/srt`, `subs.en.vtt`) and their helpers `fetch_transcript.py`, `chunk_transcript.py` | product of one task |
| 7 pricing pages (`pricing_*.html`, `pricing-styles.css`, `pricing-example.html`), `responsive_test.html` | product of one task |
| the `Adapting the Interface…pdf` paper | reference; belongs under `docs/` |
| `run_dashboard_demo.py`, `run_llm_demo.py` | leftover |
| `implementation_plan.md` (1,688 lines, last touched 2026-07-29), `PRODUCTION_READINESS_ASSESSMENT.md`, `repository_audit_report.md` | records (`tasks/` record library or `docs/archive/`) |
| `implementation_audit_report.md` | same name is also at `docs/implementation_audit_report.md`: pick one home |

## Order and size

| # | Change | Value | Size | Gate |
|---|---|---|---|---|
| 1 | B1 per-step tool contract | about 4 to 8 times fewer input tokens per call; faster steps | 1 to 2 sessions | token rerun + 45-task regression |
| 2 | A2 slim root `CLAUDE.md` | every repo session loads less | small | twins regenerate; `make check` |
| 3 | A3 processes, effects, generated index, staleness check | change-impact answers in two hops | 2 sessions | cold walk test |
| 4 | B2 plan file as edit surface; one `Output/` folder per run | human edits reach the run; run status from files | 1 session | a run whose plan was edited in the file executes the edited plan |
| 5 | A4 `evals/` vs record library; one home for fix status | plans findable by status | 1 session | generated index matches files |
| 6 | A5 root clean-up | a readable root | small, after referrer check | user approval of the migration table |

Not measured here: planner prompt size (the planner runs through the Mediator, not the cascade hook used for B1). It is worth one hook run before item 1, because the planner also receives the tool list.
