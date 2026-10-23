---
type: object
name: Personas
code: AgentPersona, AgentPersonaParser, AgentRegistry, PersonaRouter
cluster: tools
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# Personas

A persona is a markdown-defined agent identity (name, mission, rules, deliverable template, tags), imported into `.weebot/agents/` and ranked against a task by keyword score. Code: `AgentPersona` (`weebot/agents/models.py:46`).

## Why this shape
Persona files come from outside ("agency-style agent markdown", `weebot/agents/parser.py:1`), so the parser maps known headings to fields and keeps the rest (`weebot/agents/parser.py:18-37, 130-152`). Scoring reuses `AgentProfile.match_score` instead of an LLM call (`weebot/agents/models.py:66-81`, `weebot/agents/router.py:19-26`).

## Shape
- `AgentPersona` dataclass: `persona_id`, `name`, `role`, `division`, `description`, `identity`, `mission`, `critical_rules`, `deliverables`, `workflow`, `deliverable_template`, `domain_expertise`, `tools`, `tags`, `source_path`, `created_at` (`weebot/agents/models.py:45-64`). `to_profile()` builds an `AgentProfile` whose system prompt is identity + mission + rules (`:66-81`). `validate_output` checks the template's headings appear in an output (`DeliverableContract`, `:12-42, 83-92`).
- `AgentPersonaParser.parse` (`weebot/agents/parser.py:69-128`): YAML frontmatter is stripped and its `name`, if any, is the name (`:76-93`); text before the first heading is `description`; otherwise `name` is its first line, else the first heading, else the file name (`:154-165`); `role = name` (`:174-176`); `division` is the parent folder name (`:66`); `persona_id = slug(division-name)` (`:110`, `_slugify` `:52-54`); no `skills`/`expertise` section means expertise is the words of division + name (`:107-108, 181-183`).
- `AgentRegistry(root)` (`weebot/agents/registry.py:16`): JSON per persona in `<root>/.weebot/agents/registry/`, source markdown copied to `.../definitions/` (`:19-40`); `get` by id then by name (`:42-51`); `import_path` (file, dir, or zip), `import_bundle` (extracts into `definitions/`, `:83-92`), `export_bundle`, `sync_to_claude` (copies `definitions/*.md` to a target, `:112-123`), `list_divisions`, `pack` (`:129-134`).
- `PersonaRouter.score` = `AgentProfile.match_score` + 0.5 per tag found in the task (`router.py:19-26`); `match_score` = 5 if the role string is a substring of the task, + 3 x expertise-hit ratio, + 2 x success rate (`weebot/core/agent_profile.py:52-76`), and success rate is 1.0 with no history (`:23-28`). `route` returns the top 3 (`router.py:28-33`).
- CLI `python -m cli.main agents`: `import`, `export`, `list`, `describe`, `route`, `validate-output`, `sync-claude` (default target `~/.claude/agents`), `pack list`, `pack apply` (`cli/commands/agents.py:15-199`). Every command uses `AgentRegistry(Path.cwd())`.

How it differs from LLM roles:
- `PlannerAgent` and `ExecutorAgent` (map/CONTEXT.md, "persona" row) are the roles every flow runs; tool roles (`admin`, `coder`, ...) are keys of `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS` (`weebot/tools/tool_registry.py:26-185`). Personas reach neither: outside `weebot/agents/` the package is imported only by `cli/commands/agents.py` (and tests). No flow selects a persona or uses its system prompt.
- `pack apply` maps a persona to tools: `persona.tools` if the markdown listed any, else the tool role named like the persona, else `custom` (empty) (`cli/commands/agents.py:175-186`); it then prints the specs and a deprecation notice. `--execute` is accepted and unused (`cli/commands/agents.py:164-199`).

Consequences (read from source, not run):
- A frontmatter without `name` falls back to the first body line (`weebot/agents/parser.py:91-93, 157-160`). Two files in one division that yield the same name get the same id (`:110`) and overwrite each other's `registry/<id>.json` (`weebot/agents/registry.py:32-33`).
- `import_bundle` re-parses and re-registers every `*.md` under `definitions/`, not only the bundle's (`weebot/agents/registry.py:87-91`).
- `persona.tools` are free-text bullets (`weebot/agents/parser.py:104`) used as tool names without checking `build_tool_class_map` (`cli/commands/agents.py:184`).
- Every persona starts with +2.0 from the optimistic success rate (`weebot/core/agent_profile.py:23-28, 76`), and the 5-point role bonus needs the full persona name inside the task text.

## Connected to
- **Uses** `AgentProfile` (`weebot/core/agent_profile.py:32`), `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`, only in `pack apply`).
- **Looks like but is not:** `PlannerAgent` / `ExecutorAgent` (LLM roles); tool roles; skills (card `tools/BuiltinSkills.md`); Claude Code agent files, which `sync-claude` copies to unchanged.

## If you change this
**Hits:** `cli/commands/agents.py`; tests `tests/unit/test_agent_persona_parser.py`, `tests/unit/test_layer_classifier.py`. `test_agent_persona_parser.py` also covers `PersonaRouter`; no test covers `AgentRegistry` or the CLI commands.
**Does not hit:** any flow, the planner/executor prompts, tool access.

## Surfaces
Humans via `python -m cli.main agents ...`; files under `.weebot/agents/` and the `sync-claude` target.

## See
`weebot/agents/parser.py`
