---
type: object
name: Built-in skills
code: weebot/skills/builtin/, .weebot/skills/ (loaded by SkillRegistry)
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# Built-in skills

Markdown instruction packages, not code: each skill directory holds a `SKILL.md` (YAML frontmatter + body) or a `manifest.json` + `prompt.md`. They are found by path and injected into prompts; nothing imports them.

## Why this shape
A skill is prose the model reads, so a file per skill keeps it editable without code changes. One loader scans fixed directories in order (`weebot/application/skills/skill_registry.py:47-62`) and a retriever picks which skills a task gets (`application/di/_skills.py:18-63`).

## Shape
- Search paths, in order: `<cwd>/.weebot/skills`, `~/.weebot/skills`, `weebot/skills/builtin` (`skill_registry.py:48-62`); each only if it exists at construction. `add_search_path` adds more (`:34-45`; `SkillMaterializer` uses it, `application/services/skill_materializer.py:82`).
- `load_all` reads only `<dir>/SKILL.md` (`skill_registry.py:64-84`); one bad file is logged and skipped (`:78-82`). Later paths overwrite earlier ones on the same `name` (`:84`), so `builtin` wins a name clash.
- `_parse_skill` (`:98-172`): frontmatter `name` (default: dir name), `description`; `metadata` (or `metadata.openclaw` / `metadata.hermes`) gives `emoji`, `env`, `platforms`, `requires_toolsets`, `trust`, `provenance` (`:122-158`); `references/*.md` are listed for later loading (`:205-215`).
- `trust` defaults to `"trusted"`, and any value outside `quarantined/candidate/trusted` becomes `"trusted"` (`:129-131`). The retrievers inject only trusted skills (`application/services/bm25_skill_retriever.py:71`, `semantic_skill_retriever.py:130`).
- `is_ready` is true when `metadata.env` is empty or all set (`weebot/domain/models/skill.py:266-275`).
- Consumers: the DI skill retriever, BM25 or semantic, optionally reranked (`application/di/_skills.py:27-63`); also `SkillRegistry()` built directly at `application/di/_factories.py:518`, `_learning.py:159`, `services/ponytail_skill_prompt.py:76`, `scheduling/default_jobs.py:106`, `cli/commands/ponytail.py:77`, `cli/commands/skills.py:31, 119, 186, 279, 350`.

| Skill (frontmatter / manifest name) | Dir | Format | Tools it names |
|---|---|---|---|
| agent-reach | `builtin/agent-reach` | SKILL.md | `agent_reach`, `moli_fetch`, `bash`, `powershell`, `python_execute` |
| architecture_design | `builtin/architecture_design` | SKILL.md | `file_editor` |
| berb-research | `builtin/berb-research` | manifest.json | - |
| camofox-browser | `builtin/camofox-browser` | SKILL.md | `camofox_browser`, `advanced_browser`, `agent_reach`, `moli_fetch` |
| competitive_analysis | `builtin/competitive_analysis` | manifest.json | `swarm` |
| data-analysis | `builtin/data-analysis` | SKILL.md | - |
| design-taste-frontend | `builtin/design-taste` | manifest.json | - |
| desktop-automation | `builtin/desktop-automation` | SKILL.md | `computer_use`, `screen_capture`, `desktop_a11y` (`:19, 29`) |
| git-best-practices | `builtin/git-best-practices` | SKILL.md | - |
| multi_llm_orchestrator | `builtin/multi_llm_orchestrator` | manifest.json | `reasoner` |
| orchestration_guide | `builtin/orchestration_guide` | SKILL.md | `swarm`, `debate`, `dispatch_parallel_tasks`, `workflow_orchestrator`, `mixture_of_agents` |
| ponytail, ponytail-audit, ponytail-help, ponytail-review | `builtin/ponytail*` | SKILL.md | - |
| reasoner | `builtin/reasoner` | manifest.json | - |
| reify_skill | `builtin/reify_skill` | SKILL.md | `video_ingest`, `voice_input`, `persistent_memory` |
| remotion-video | `builtin/remotion-video` | SKILL.md | `remotion_video`, `video_gen`, `file_editor`, `youtube_download` (`:24`) |
| scientific-book | `builtin/scientific-book` | SKILL.md | - |
| seo_optimizer | `builtin/seo_optimizer` | SKILL.md | `web_search`, `advanced_browser`, `bash`, `file_editor`, `image_gen`, `knowledge` |
| skill-author | `builtin/skill-author` | manifest.json | - |
| tdd_app_dev | `builtin/tdd_app_dev` | SKILL.md | - |
| web-3d-motion | `builtin/web-3d-motion` | SKILL.md | - |
| web-development | `builtin/web-development` | SKILL.md | - |
| web_research | `builtin/web_research` | manifest.json | `web_search`, `advanced_browser` |
| youtube-download | `builtin/youtube-download` | SKILL.md | `youtube_download` (`:9, 15-21`), `video_ingest`, `web_search`, `advanced_browser`, `python_execute` |
| apify-scraper | `.weebot/skills/apify-scraper` | SKILL.md | the ten `apify_*` presets (`:17-28`) |
| code-review | `.weebot/skills/code-review` | SKILL.md | - |
| find-bugs | `.weebot/skills/find-bugs` | SKILL.md | - |
| integration-test-skill | `.weebot/skills/test-skill` | SKILL.md | - ("Temporary skill to verify install + BM25 rebuild") |

"Tools it names" lists backticked names that match a `BaseTool.name` or an Apify preset; every one exists.

Consequences (read from source, not run):
- The seven `manifest.json` skills (berb-research, competitive_analysis, design-taste, multi_llm_orchestrator, reasoner, skill-author, web_research) are never loaded at runtime: `SkillRegistry` reads only `SKILL.md` (`skill_registry.py:72`), and their loader `SkillPackager` (`application/skills/skill_packager.py:27`) is constructed nowhere outside its own module. The root `CLAUDE.md` requires delegating to `multi_llm_orchestrator`; the agent never sees that skill.
- `youtube-download` and `remotion-video` point at `youtube_download`, and `desktop-automation` at `desktop_a11y`; neither tool is in any role (`weebot/tools/tool_registry.py:27-177`).
- `apify-scraper` declares its key as top-level `requires_env` (`.weebot/skills/apify-scraper/SKILL.md:5-6`); the parser reads `metadata.env` (`skill_registry.py:144`), so the skill is ready, and can be injected, when the Apify tools are absent.
- A skill with no `trust`, or a misspelt one, is trusted (`skill_registry.py:129-131`). The ClawHub importer installs into `~/.weebot/skills` (`application/skills/clawhub_importer.py:62`) and contains no `trust` handling, so imported community skills would pass the retriever's trust gate (inferred from the absence of `trust` in that file).

## Connected to
- **Loaded by** `SkillRegistry` (stub `objects/_index.md`). **Retrieved by** `BM25SkillRetriever` / `SemanticSkillRetriever` / `RerankingSkillRetriever`. **Written by** `SkillMaterializer` and `MaterializingSkillStore` (`application/services/materializing_skill_store.py:39`, trusted only).
- **Looks like but is not:** tools (`weebot/tools/`, card `tools/RoleBasedToolRegistry.md`); personas (card `tools/Personas.md`); `weebot/application/skills/builtin/` (optimizer prompts, its own `loader.py`).

## If you change this
**Hits:** which instructions the executor gets per task; tests `tests/unit/skills/test_ponytail_skills.py`, `tests/unit/test_semantic_skill_retriever.py`, `tests/unit/tools/test_skill_cli.py`, `tests/unit/tools/test_skill_hermes.py`, `tests/unit/tools/test_skill_progressive_disclosure.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_remotion_video.py`, `tests/unit/test_layer_classifier.py`.
**Does not hit:** tool availability; a skill naming a tool does not grant it.

## Surfaces
`python -m cli.main skills ...` (`cli/commands/skills.py`); the executor system prompt.

## See
`weebot/application/skills/skill_registry.py`
