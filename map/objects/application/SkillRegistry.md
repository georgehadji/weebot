---
type: object
name: SkillRegistry
code: SkillRegistry
cluster: application
universe: live
status: verified
verified: 2026-10-24
commit: 50a5d748
---

# SkillRegistry

Scans skill folders for `SKILL.md` files, parses their YAML frontmatter into `Skill` domain objects and keeps them in an in-memory dict by name. Skill retrievers, the skill CLI and the materializer read skills through it.

## Why this shape
A skill is data on disk, not code, so the registry is a directory scan plus a parser, with no persistence of its own. It is built fresh per caller (no singleton). Frontmatter is parsed with libyaml's C loader when present; the docstring gives about 26 s against 4 s for a few hundred skills (`weebot/application/skills/skill_registry.py:13-24`). One bad `SKILL.md` is logged and skipped so it cannot empty the registry at container start (`:74-82`).

## Shape
- `__init__(search_paths=None)` (`:30-32`): default paths are `./.weebot/skills`, `~/.weebot/skills`, then `weebot/skills/builtin`, each only if it exists **at construction time** (`:47-62`). `add_search_path` adds one later (`:34-45`).
- `load_all()` (`:64-84`): for each search path, each subdirectory with a `SKILL.md`; `self._skills[skill.name] = skill`.
- `_parse_skill` (`:98-172`): needs a leading `---` block; name falls back to the folder name; `metadata.openclaw` and `metadata.hermes` keys are merged into `SkillMetadata`; trust tier and provenance are read from `metadata` (`:128-140`); `references/**/*.md` are listed, not loaded (`:170, 205-215`).
- Reads: `get` and `get_skill` (same body, `:94-96, 174-175`), `list_names`, `list_all`, `list_skills` (`:86-92, 181-182`), `get_active_skills` (env-ready skills, `:184-186`), `build_system_prompt_extensions` (`:188-199`). Write: `update_skill` (`:177-179`).

Consequences (read from source, not run):
- **Missing or invalid trust means trusted.** A skill with no `metadata.trust`, or a value outside the three tiers, is loaded as `trusted` (`:129-131`), matching the model default (`weebot/domain/models/skill.py:97-98`). The retrievers' only trust gate is `is_injectable` (`application/services/bm25_skill_retriever.py:75`, `semantic_skill_retriever.py:133`), so any `SKILL.md` placed in the working directory's `.weebot/skills` is injected into the live executor prompt. A typo such as `trust: quarantine` opens the gate rather than closing it.
- **Built-ins win name collisions.** Paths load project, then user, then built-in, and later ones overwrite (`:52-61, 84`). A project skill with the same name as a built-in is silently replaced by the built-in. No log line.
- **`manifest.json` skills are invisible here.** Only `SKILL.md` is read (`:72`). Seven built-ins ship only `manifest.json` + `prompt.md`: `berb-research`, `competitive_analysis`, `design-taste`, `multi_llm_orchestrator`, `reasoner`, `skill-author`, `web_research` (directory listing 2026-10-23). They are handled by `SkillPackager` (`application/skills/skill_packager.py:47-63`) and the format detector (`application/skills/format_detector.py:44-45`), not by retrieval.
- An unreadable file returns `None` with no log (`:100-103`); a bad `provenance` mapping falls back to an empty `SkillProvenance` with no log (`:133-140`).
- No shared instance: `SkillRegistry()` is built and fully scanned at `application/di/_skills.py:31`, `application/di/_factories.py:558` (MCP skill indexer, when semantic retrieval is on), `application/di/_learning.py:159`, `application/services/ponytail_skill_prompt.py:76`, `application/skills/skill_packager.py:40`, `weebot/scheduling/default_jobs.py:106`, `cli/commands/ponytail.py:77` and five times in `cli/commands/skills.py` (`:31, 119, 186, 279, 350`). An `update_skill` on one instance is not seen by the others; the materializer reaches the retriever's instance through `retriever.registry` (`application/di/_learning.py:150-160`).
- `_reference_paths` is set with `object.__setattr__` on the pydantic model (`:170`); it is not part of a dump.

## Connected to
- **Builds** `Skill` / `SkillMetadata` / `SkillProvenance` (`weebot/domain/models/skill.py`). **Read by** `BM25SkillRetriever`, `SemanticSkillRetriever` (both wrapped by `RerankingSkillRetriever`, built in `application/di/_skills.py:18-60`, registered as `"skill_retriever"`, `di/__init__.py:182`), `MCPToolSkillIndexer` (`di/_factories.py:558-560`), `SkillMaterializer` (`di/_learning.py:150-160`), `SkillPackager`.
- **Data:** `weebot/skills/builtin/*/SKILL.md` (see `map/CONTEXT.md`: loaded by path, not imported).
- **Looks like but is not:** `RoleBasedToolRegistry` (tools, not skills); `SkillStore` / `SkillStorePort` (versioned skills in SQLite for SkillOpt, `infrastructure/persistence/skill_store.py:23`); personas (`weebot/agents/`).

## If you change this
**Hits:** which skills the executor can be given, skill trust gating, `python -m cli.main skills ...`, ponytail prompts, MCP skill indexing. Tests: `tests/unit/tools/test_skill_cli.py`, `tests/unit/tools/test_skill_hermes.py`, `tests/unit/tools/test_skill_progressive_disclosure.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_remotion_video.py`, `tests/unit/skills/test_ponytail_skills.py`, `tests/unit/test_semantic_skill_retriever.py`.
**Does not hit:** `SkillStore` and the SkillOpt flow; tool registration.

## Surfaces
`cli/commands/skills.py`, `cli/commands/ponytail.py`; the skill block in executor prompts.

## See
`weebot/application/skills/skill_registry.py`
