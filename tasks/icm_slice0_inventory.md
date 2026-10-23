---
status: reference
date: 2026-10-22
---

# ICM slice 0: inventory (read-only, nothing moved)

Plan: `tasks/icm_plan.md`. Roles: catalog / contract / factory / product / dead. "Dead" is only a proposal until slice 1 checks markdown and external referrers.

Method: code and config referrers found by grep excluding `*.md`, `node_modules`, `Output`, `docs/archive`, `tasks/specs`. Markdown referrers are NOT yet checked (slice 1). Hits that turned out to be function names (`_fetch_transcript`, `pricing_to_cost`) are counted as no referrer.

## Entry files done (steps 1-5)

`CLAUDE.md` is the only hand-edited entry file; `AGENTS.md`, `GEMINI.md`, `QWEN.md` are generated and gated in CI. Originals in `docs/archive/`.

## Repo root

| Item | Role | Code/config referrers | Proposal |
|---|---|---|---|
| `CLAUDE.md` (+ generated twins) | catalog | many | keep |
| `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `LICENSE`, `VERSION` | catalog / contract | build and docs | keep |
| `pyproject.toml`, `requirements*.txt*`, `Makefile`, `alembic.ini`, `Dockerfile*`, `docker-compose.yml`, `docker-entrypoint.sh`, `package*.json`, `.importlinter`, `.coveragerc` | factory | build/CI | keep |
| `run.py`, `run_mcp.py` | factory (entry points) | `docs/ENTRY_POINTS.md`, docker | keep |
| `claude_desktop_config.json.example`, `reasonix.toml` | factory | `reasonix.toml` only in `.gitignore` | keep example; ask owner about `reasonix.toml` |
| `PRODUCTION_READINESS_ASSESSMENT.md`, `implementation_plan.md` (77K), `implementation_audit_report.md`, `repository_audit_report.md` | product (audits/plans) | none in code | move to `docs/archive/` or `tasks/`, after markdown referrer check |
| `transcript*.txt/json/srt`, `subs.en.vtt` (12 files) | product | none (`data/agent_team_vs_swarm.jsonl` only contains the word) | move to `Output/` or `_archive/` |
| `chunk_transcript.py`, `fetch_transcript.py` | product (one-off scripts) | none (`video_ingest_tool.py` has its own `_fetch_transcript`) | move to `scripts/` or archive |
| `pricing-example.html`, `pricing-styles.css`, `pricing_*.html` (5), `responsive_test.html` | product | none | move to `website_copy/` or archive |
| `run_dashboard_demo.py`, `run_llm_demo.py` | product (demos) | none | move to `examples/` |
| `start-next.bat` | factory? | none | ask owner |
| `Adapting the Interface ... .pdf` (2.1M) | product / reference | none | ask owner; likely `docs/reference/` |

## Top-level directories

| Dir | Role | Evidence | Proposal |
|---|---|---|---|
| `weebot/`, `cli/`, `tests/`, `alembic/`, `scripts/`, `docker/` | factory | core | keep, do not touch |
| `weebot-ui/` | factory | own manifest, compose service | keep |
| `docs/` | contract/product mix | ~50 overlapping plan/audit files | clean in slice 7 |
| `tasks/` | product (plans/specs, lessons) | | keep |
| `config/`, `templates/`, `data/`, `examples/`, `integrations/` | factory | not yet individually checked | classify in slice 1 |
| `research_modules/` | factory | imported by `cli/main.py`, `run.py` | keep (live) |
| `Output/` | product | 5 tracked files, `.gitignore` says generated output is not committed | confirm; likely untrack |
| `Useful Github Projects/` | reference | 9 tracked files; only a docstring in `weebot/qmd_integration/__init__.py` mentions it | owner decision |
| `website_copy/` | product | no referrers | keep or archive, owner decision |

## weebot/ packages (live / leftover / ghost)

| Package | Files | External importers | Verdict |
|---|---|---|---|
| `application`, `domain`, `infrastructure`, `interfaces`, `core`, `tools`, `config` | 324/87/169/45/47/48/63 | many (config 182) | live |
| `models`, `utils`, `templates`, `mcp`, `scheduling`, `qmd_integration` | 2-35 | 7-15 each | live |
| `agents` | 5 | 2 (`cli/commands/agents.py`, one test) | live, small |
| `skills` | 33 | 0 imports | live as data (SKILL.md/manifest loaded by path); confirm in slice 3 |
| `osworld` | 4 | 1 (only `tests/unit/test_osworld_adapter.py`) | leftover candidate |
| `docs` | 1 (`FINAL_PROJECT_SUMMARY.md`) | 0 | stray doc inside the package; move to `docs/` |

`agent_core_v2` (named in ARCHITECTURE.md ADR-009, 2027-03-01 sunset) was not located by file name; find it in slice 3 before marking it leftover.

## Name collisions to record in `map/CONTEXT.md` (slice 2)

To verify in source, not yet confirmed: persona vs agent (`cli agents list` lists personas, `application/agents/` holds Planner/Executor), skill vs tool (`weebot/skills/builtin` vs `weebot/tools`), flow vs session (`flow run` creates a session).

## Not yet checked (slice 1)

- Markdown referrers of every proposed move (README, `docs/README.md`, `UPDATED_DOCUMENTATION_INDEX.md`, `PROJECT_STRUCTURE.md`, specs).
- `.github/workflows`, `.dockerignore`, Dockerfile COPY lines for the root files.
- Case-folded destination collisions on Windows.
- External consumers (Claude Desktop config, scheduled tasks, other repos).

## Decisions needed from you

1. `reasonix.toml`, `start-next.bat`, the PDF: keep, move or drop?
2. `Output/` (5 tracked files) and `Useful Github Projects/` (9 tracked files): untrack, archive, or keep?
3. `weebot/osworld`: treat as leftover (keep, but flag in the map)?
4. Approve moving root audits/plans, transcripts, pricing HTML and demos in slice 7 after slice 1 confirms no referrers?
