---
type: object
name: SkillRegistry
code: SkillRegistry
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# SkillRegistry

Scans skill folders for `SKILL.md` files, parses their YAML frontmatter into `Skill` domain objects and keeps them in an in-memory dict by name. Skill retrievers, the skill CLI and the materializer read skills through it.

## Why this shape
A skill is data on disk, not code, so the registry is a directory scan plus a parser, with no persistence of its own. It is built fresh per caller (no singleton). Frontmatter is parsed with libyaml's C loader when present; the docstring gives about 26 s against 4 s for a few hundred skills (`weebot/application/skills/skill_registry.py:13-24`). One bad `SKILL.md` is logged and skipped so it cannot empty the registry at container start (`skill_registry.py:82-94`).

## Shape
- `__init__(search_paths=None)` (`skill_registry.py:30-32`): default paths are `./.weebot/skills`, `~/.weebot/skills`, then `weebot/skills/builtin`, each only if it exists **at construction time** (`skill_registry.py:47-62`). `add_search_path` adds one later (`skill_registry.py:34-45`).
- `load_all()` (`skill_registry.py:64-100`): for each search path, each subdirectory with a `SKILL.md` (or, failing that, a `manifest.json`, `skill_registry.py:78-80`); a rescan merges over the dict, keeping in-memory skills absent from disk (`skill_registry.py:100`).
- `_parse_skill` (`skill_registry.py:114-186`): needs a leading `---` block; name falls back to the folder name; `metadata.openclaw` and `metadata.hermes` keys are merged into `SkillMetadata`; trust tier and provenance are read from `metadata` (`skill_registry.py:144-154`); `references/**/*.md` are listed, not loaded (`skill_registry.py:184, 259-269`). `_parse_manifest` builds a `Skill` from `manifest.json` plus its prompt file (`skill_registry.py:188-211`).
- Reads: `get` and `get_skill` (same body, `skill_registry.py:110-112, 213-214`), `list_names`, `list_all`, `list_skills` (`skill_registry.py:102-108, 224-225`), `get_active_skills` (env-ready skills, `skill_registry.py:227-229`), `build_system_prompt_extensions` (`skill_registry.py:231-242`). Writes: `update_skill` (`skill_registry.py:216-218`) and `remove_skill`, which forgets a name in memory (`skill_registry.py:220-222`).

Consequences (read from source, not run):
- **Missing trust means trusted; a bad value means quarantined.** A skill with no `metadata.trust` loads as `trusted`, matching the model default (`_trust_tier`, `skill_registry.py:248-256`; `weebot/domain/models/skill.py:107-109`). A value that is set but outside the three tiers is logged and quarantined (F42), so a typo such as `trust: quarantine` closes the gate. The retrievers' only trust gate is `is_injectable`, true for `trusted` and `candidate` (`weebot/domain/models/skill.py:290-298`; `application/services/bm25_skill_retriever.py:76`, `semantic_skill_retriever.py:137`), so any `SKILL.md` without a trust key placed in the working directory's `.weebot/skills` is injected into the live executor prompt.
- **Project skills win name collisions.** Paths load project, then user, then built-in, and within one scan the first path wins (F71, `skill_registry.py:52-61, 95-99`). A shadowed skill is logged at info level (`skill_registry.py:95-97`).
- **`manifest.json` skills load here too (F52).** A folder with no `SKILL.md` but a `manifest.json` goes through `_parse_manifest` (`skill_registry.py:78-80, 87-91`). Seven built-ins ship only `manifest.json` + `prompt.md`: `berb-research`, `competitive_analysis`, `design-taste`, `multi_llm_orchestrator`, `reasoner`, `skill-author`, `web_research` (directory listing 2026-10-31). `SkillPackager` (`application/skills/skill_packager.py:42-50`) and the format detector (`application/skills/format_detector.py:44-45`) also handle that format.
- An unreadable file returns `None` with no log (`skill_registry.py:116-119`); a bad `provenance` mapping falls back to an empty `SkillProvenance` with no log (`skill_registry.py:146-154`).
- No shared instance: `SkillRegistry()` is built and fully scanned at `application/di/_skills.py:31`, `application/di/_factories.py:644` (MCP skill indexer, when semantic retrieval is on), `application/di/_learning.py:191`, `application/services/ponytail_skill_prompt.py:76`, `application/skills/skill_packager.py:40`, `weebot/scheduling/default_jobs.py:110`, `cli/commands/ponytail.py:77` and six times in `cli/commands/skills.py` (`cli/commands/skills.py:31, 114, 182, 249, 342, 413`). An `update_skill` on one instance is not seen by the others; the materializer reaches the retriever's instance through `retriever.registry` (`application/di/_learning.py:183-193`).
- `_reference_paths` is set with `object.__setattr__` on the pydantic model (`skill_registry.py:184`); it is not part of a dump.

## Connected to
- **Builds** `Skill` / `SkillMetadata` / `SkillProvenance` (`weebot/domain/models/skill.py`). **Read by** `BM25SkillRetriever`, `SemanticSkillRetriever` (both wrapped by `RerankingSkillRetriever`, built in `application/di/_skills.py:18-76`, registered as `"skill_retriever"`, `weebot/application/di/__init__.py:189`), `MCPToolSkillIndexer` (`application/di/_factories.py:644-646`), `SkillMaterializer` (`application/di/_learning.py:183-193`), `SkillPackager`.
- **Data:** `weebot/skills/builtin/*/SKILL.md` (see `map/CONTEXT.md`: loaded by path, not imported).
- **Looks like but is not:** `RoleBasedToolRegistry` (tools, not skills); `SkillStore` / `SkillStorePort` (versioned skills in SQLite for SkillOpt, `infrastructure/persistence/skill_store.py:23`); personas (`weebot/agents/`).

## If you change this
**Hits:** which skills the executor can be given, skill trust gating, `python -m cli.main skills ...`, ponytail prompts, MCP skill indexing. Tests: `tests/unit/tools/test_skill_cli.py`, `tests/unit/tools/test_skill_hermes.py`, `tests/unit/tools/test_skill_progressive_disclosure.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_remotion_video.py`, `tests/unit/skills/test_ponytail_skills.py`, `tests/unit/test_semantic_skill_retriever.py`.
**Does not hit:** `SkillStore` and the SkillOpt flow; tool registration.

## Surfaces
`cli/commands/skills.py`, `cli/commands/ponytail.py`; the skill block in executor prompts.

## See
`weebot/application/skills/skill_registry.py`
