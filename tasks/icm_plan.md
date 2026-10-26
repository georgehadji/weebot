---
status: open
date: 2026-10-22
note: slice 7 rest: docs/*PLAN*, *SUMMARY*, PROJECT_COMPLETE.md not yet in docs/archive/ (needs referrer check and approval)
---

# Plan: make Weebot an ICM workspace

Status: DRAFT, nothing moved or written yet. Method: icm-architect, Restructure mode + System map form.

Related, not duplicated: `tasks/specs/icm_weebot_analysis.md` and `tasks/specs/icm_implementation_plan.md` apply ICM ideas to Weebot's runtime (per-step context scoping in the agent code). This plan is about the repo's own folder structure, so later agents can navigate and edit it. Defects the cards found are planned separately in `tasks/icm_fix_plan.md`.

## 1. Form and why

Weebot is a code repo that later agents will edit (about 800 Python files under `weebot/`, plus `weebot-ui/`, `docs/`, `tasks/`). It is not a production line, so the right form is a **System map**: a `map/` shelf of noun cards, a short shelf of process cards, and a change-impact index. The source tree stays the source of truth. The map cites it and never becomes a second spec.

Do not restructure `weebot/` itself. Its Clean Architecture layering is already enforced by `.importlinter`, `tests/unit/test_architecture_fitness.py` and the Makefile gates. Moving code would break those contracts for no gain. ICM work here is additive (a map) plus a docs clean-up.

## 2. Problems the map must fix (from inventory)

- Entry files are not routing files. `CLAUDE.md` mixes commands, architecture, website rules and workflow; `AGENTS.md` (20K), `GEMINI.md`, `QWEN.md` are separate hand-edited copies that can drift.
- `docs/` holds about 50 overlapping plan, audit and summary files (`ARCHITECTURE_*_PLAN*.md`, `*_SUMMARY.md`, `PROJECT_COMPLETE.md`, ...). Several are superseded. No one-home-per-fact.
- Repo root is cluttered with product: `transcript*.txt/json/srt/vtt` (about 12 files), `pricing_*.html`, `responsive_test.html`, `chunk_transcript.py`, `fetch_transcript.py`, `run_*_demo.py`, a PDF, and audit reports (`implementation_plan.md` 77K, `implementation_audit_report.md`, `repository_audit_report.md`).
- `Output/`, `Useful Github Projects/`, `research_modules/`, `website_copy/` have unclear status (factory vs. product vs. dead).
- Name collisions between product language and code names are not written down anywhere (to be found in slice 0, for example persona vs. agent, skill vs. tool, flow vs. session).

## 3. Target layout

```
map/                       new shelf, next to docs/, not inside weebot/
  CLAUDE.md                L0 catalog (twins generated: AGENTS.md, routing.md)
  CONTEXT.md               how to walk; live / leftover / ghost; name collisions
  _meta/schema.md          closed node types
  _templates/object.md, process.md
  objects/
    CONTEXT.md
    _index.md              one line per noun: stub | verified | stale
    domain/                Plan, Step, Session, Event
    application/           PlanActFlow, FlowRouter, PlannerAgent, ExecutorAgent, CQRS mediator, skills
    infrastructure/        LLM adapters, SQLite event store, ports and DI container
    interfaces/            CLI, web (FastAPI), MCP server
    core/                  bash_guard, model_cascade, SecretAccessor
    tools/                 tool registry, atomic_mail
  processes/               only real movements: plan-act-update turn, model cascade call,
                           bash command guard, inbound-mail approval gate, session resume
  effects/CONTEXT.md       "if you change X, open these cards"
```

`processes/` and `effects/` get created only after the noun clusters exist. Start with the 6 clusters above; add more only when a real editor question needs one.

## 4. Slices (human gate after each)

**Slice 0, inventory (no writes).** Classify every top-level item as catalog / contract / factory / product / dead. Mark live / leftover / ghost for each `weebot/` package (candidates for leftover: `agent_core_v2`, `osworld`, `qmd_integration`; ADR-009 mentions a 2027-03-01 sunset). Output: migration table old path, new path, role, referrers. Approve before slice 1. Draft done: `tasks/icm_slice0_inventory.md`.

**Slice 1, reference integrity (before any move).** For every file proposed to move or archive, find referrers: Makefile, `.importlinter`, `pyproject.toml` (`ruff` exclude, `bandit` exclude), `.coveragerc`, `.dockerignore`, Dockerfiles, `docker-compose.yml`, `.github/workflows`, `.github/rulesets`, `scripts/*`, `tests/*`, `README.md`, `docs/README.md`, `UPDATED_DOCUMENTATION_INDEX.md`, `PROJECT_STRUCTURE.md`. Ask the owner about external consumers (Claude Desktop config, scheduled tasks, other repos). Check case-folded destination collisions (Windows). Files with a live referrer are held or moved together with every referrer. Draft done: `tasks/icm_slice1_references.md`.

**Slice 2, catalog.** Write `map/CLAUDE.md` (under 60 lines), `CONTEXT.md`, schema, templates, `objects/_index.md` with stub lines. Add one routing row to root `CLAUDE.md` pointing at `map/`. Walk test: "where is X?" resolves in two hops.

**Slice 3, nouns.** One card per type, clustered by how an editor asks. Cite `path:line`. `verified` only with date and commit hash. Fill Hits / Does not hit, first order only. Start with the most-edited clusters: application/flows, application/agents/executor, infrastructure/persistence, core/bash_guard.

**Slice 4, verbs.** Process cards for the five movements listed above only.

**Slice 5, effects index plus outside-in pass.** Write `effects/CONTEXT.md`. Then list what points INTO the repo from outside (Claude Desktop config via `claude_desktop_config.json.example`, `run_mcp.py` path, CI, docker entrypoints) and record each on the card it lands on. Done 2026-10-24: `map/effects/inbound.md` lists each outside consumer with its citation.

**Slice 6, re-verify.** Re-check Hits / Does not hit against source. Cold walk test (section 7). Done 2026-10-24: the cold walk answered 5 of 6 questions in 2 to 4 hops (about 6.5k tokens); the miss was a stale EgressGuard card, so `scripts/check_map_citations.py --drift` now compares cited lines with the card's `commit` (`make lint-map`), and all 42 cards were re-verified at d4ffb555. Re-run 2026-10-26 (fresh agent, same questions): 6 of 6 PASS, about 7.1k tokens. It found wrong citations in `map/effects/CONTEXT.md` and `map/CONTEXT.md` (fixed) and in `map/processes/flow-run-turn.md` (marked stale); the drift check does not scan those files yet.

**Slice 7, clean-up (separate PR, needs approval).** Per the slice 0 table:
- `transcript*`, `subs.en.vtt`, `chunk_transcript.py`, `fetch_transcript.py` to `Output/` or a `_archive/`, after referrer check.
- `pricing_*.html`, `responsive_test.html` to `website_copy/` or `_archive/`.
- Overlapping `docs/*PLAN*`, `*SUMMARY*`, `*_COMPLETE*` to `docs/archive/` (folder exists); keep ADRs in `docs/adr/`. Leave a link where a moved file was referenced.
- Never delete. Copy, verify parity (count and hash), then remove the original.

## 5. Entry files (DECIDED: option below approved)

Decision: root `CLAUDE.md` is the only hand-edited entry file. `AGENTS.md`, `GEMINI.md`, `QWEN.md` become generated twins. Order matters: before the first generation, diff each of the three against `CLAUDE.md`, move any unique content (`AGENTS.md` is 20K) into `map/` cards or `docs/`, and only then overwrite. Diff done: see `tasks/icm_entry_diff.md`. Add a generated-file header and a `scripts/` generator plus a check that fails if a twin drifts. Slice 2 carries this work.

Original reasoning: ICM wants one hand-edited entry file and generated byte-identical twins. Today `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `QWEN.md` all differ. Proposal: keep root `CLAUDE.md` as the only hand-edited file (shrink to routing plus commands), move the unique content of `AGENTS.md` into `map/` cards or `docs/`, and generate `AGENTS.md`, `GEMINI.md`, `QWEN.md` from `CLAUDE.md` with a small script in `scripts/`. This is the biggest behaviour change for other agent tools; confirm before doing it.

## 6. Guardrails specific to this repo

- Do not touch `weebot/`, `tests/`, or ratchet data (`scripts/quality_ceilings.py`) as part of this work. Run `make check` before and after any move to prove nothing broke.
- New map files must not trip the existing lints (`lint-ruleset`, `lint-di-wiring`). Map is markdown only, outside `weebot/` and `cli/`.
- Website-generation rules in root `CLAUDE.md` are factory reference. They move to `map/` or `docs/` and root keeps a one-line pointer.
- Token budget: root entry + `map/CLAUDE.md` + one card stays within 2k to 8k tokens.

## 7. Walk test (done criteria)

A cold agent with no memory can: (1) find `map/` from root `CLAUDE.md` in one hop; (2) learn what the colliding names mean from `map/CLAUDE.md` alone; (3) open one card and see source citations, the why, and Hits / Does not hit; (4) from `effects/CONTEXT.md` name what a stated change hits and what it does not; (5) follow a `See` link to source, not another essay; (6) stay within the token band.

## 8. Open questions for the owner

1. ~~Entry-file twins~~ Decided: generate from `CLAUDE.md` (section 5).
2. Which `weebot/` packages are leftover or ghost vs. live?
3. Are `Output/`, `Useful Github Projects/`, `research_modules/` product, factory or dead?
4. Any external consumers with hard-coded paths into this repo?
5. Is the 2.1M PDF at the root needed in-repo?

## 9. Order

Slices 0 to 2 first (small: mostly reading and one catalog). Slices 3 to 5 are the bulk and can proceed cluster by cluster. Slice 7 is optional and last; nothing in slices 0 to 6 depends on it.
