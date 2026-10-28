---
type: object
name: Built-in skills
code: weebot/skills/builtin/, .weebot/skills/ (loaded by SkillRegistry)
cluster: tools
universe: live
status: verified
verified: 2026-10-29
commit: 78bcc65f
---

# Built-in skills

Markdown instruction packages, not code: each skill directory holds a `SKILL.md` (YAML frontmatter + body) or a `manifest.json` + `prompt.md`. They are found by path and injected into prompts; nothing imports them.

## Why this shape
A skill is prose the model reads, so a file per skill keeps it editable without code changes. One loader scans fixed directories in order (`weebot/application/skills/skill_registry.py:47-100`) and a retriever picks which skills a task gets (`weebot/application/di/_skills.py:18-76`).

## Shape
- Search paths, in order: `<cwd>/.weebot/skills`, `~/.weebot/skills`, `weebot/skills/builtin` (`weebot/application/skills/skill_registry.py:48-62`); each only if it exists at construction. `add_search_path` adds more (`weebot/application/skills/skill_registry.py:34-45`; `SkillMaterializer` uses it, `weebot/application/services/skill_materializer.py:87`).
- `load_all` rescans on every call and reads `<dir>/SKILL.md`, else `<dir>/manifest.json` (`weebot/application/skills/skill_registry.py:64-100`); one bad file is logged and skipped (`weebot/application/skills/skill_registry.py:86-94`). On a `name` clash the first path wins, so a project skill shadows a built-in one (`weebot/application/skills/skill_registry.py:95-99`); skills added only in memory are kept (`weebot/application/skills/skill_registry.py:100`).
- `_parse_skill` (`weebot/application/skills/skill_registry.py:114-186`): frontmatter `name` (default: dir name), `description`; `metadata` (or `metadata.openclaw` / `metadata.hermes`) gives `emoji`, `env`, `platforms`, `requires_toolsets`, `trust`, `provenance` (`weebot/application/skills/skill_registry.py:138-172`); `references/*.md` are listed for later loading (`weebot/application/skills/skill_registry.py:184, 259-269`).
- `_parse_manifest` (`weebot/application/skills/skill_registry.py:188-211`): `name`, `description`, `emoji`, `env`, `homepage`, `trust` from `manifest.json`; the body is `prompt_file` (default `prompt.md`).
- `trust` defaults to `"trusted"` when absent; a value outside `quarantined/candidate/trusted` becomes `"quarantined"` with a warning (`weebot/application/skills/skill_registry.py:248-256`). The retrievers inject only trusted skills (`weebot/application/services/bm25_skill_retriever.py:76`, `weebot/application/services/semantic_skill_retriever.py:137`).
- `is_ready` is true when `metadata.env` is empty or all set (`weebot/domain/models/skill.py:277-286`).
- Consumers: the DI skill retriever, BM25 or semantic, optionally reranked (`weebot/application/di/_skills.py:27-76`); also `SkillRegistry()` built directly at `weebot/application/di/_factories.py:596`, `weebot/application/di/_learning.py:191`, `weebot/application/services/ponytail_skill_prompt.py:76`, `weebot/scheduling/default_jobs.py:110`, `cli/commands/ponytail.py:77`, `cli/commands/skills.py:31, 182, 186, 279, 350`.

| Skill (frontmatter / manifest name) | Dir | Format | Tools it names |
|---|---|---|---|
| agent-reach | `builtin/agent-reach` | SKILL.md | `agent_reach`, `moli_fetch`, `bash`, `powershell`, `python_execute` |
| architecture_design | `builtin/architecture_design` | SKILL.md | `file_editor` |
| berb-research | `builtin/berb-research` | manifest.json | - |
| camofox-browser | `builtin/camofox-browser` | SKILL.md | `camofox_browser`, `advanced_browser`, `agent_reach`, `moli_fetch` |
| competitive_analysis | `builtin/competitive_analysis` | manifest.json | `swarm` |
| data-analysis | `builtin/data-analysis` | SKILL.md | - |
| design-taste-frontend | `builtin/design-taste` | manifest.json | - |
| desktop-automation | `builtin/desktop-automation` | SKILL.md | `computer_use`, `screen_capture`, `desktop_a11y` (lines 19, 29) |
| git-best-practices | `builtin/git-best-practices` | SKILL.md | - |
| multi_llm_orchestrator | `builtin/multi_llm_orchestrator` | manifest.json | `reasoner` |
| orchestration_guide | `builtin/orchestration_guide` | SKILL.md | `swarm`, `debate`, `dispatch_parallel_tasks`, `workflow_orchestrator`, `mixture_of_agents` |
| ponytail, ponytail-audit, ponytail-help, ponytail-review | `builtin/ponytail*` | SKILL.md | - |
| reasoner | `builtin/reasoner` | manifest.json | - |
| reify_skill | `builtin/reify_skill` | SKILL.md | `video_ingest`, `voice_input`, `persistent_memory` |
| remotion-video | `builtin/remotion-video` | SKILL.md | `remotion_video`, `video_gen`, `file_editor`, `youtube_download` (line 24) |
| scientific-book | `builtin/scientific-book` | SKILL.md | - |
| seo_optimizer | `builtin/seo_optimizer` | SKILL.md | `web_search`, `advanced_browser`, `bash`, `file_editor`, `image_gen`, `knowledge` |
| skill-author | `builtin/skill-author` | manifest.json | - |
| tdd_app_dev | `builtin/tdd_app_dev` | SKILL.md | - |
| web-3d-motion | `builtin/web-3d-motion` | SKILL.md | - |
| web-development | `builtin/web-development` | SKILL.md | - |
| web_research | `builtin/web_research` | manifest.json | `web_search`, `advanced_browser` |
| youtube-download | `builtin/youtube-download` | SKILL.md | `youtube_download` (lines 9, 15-21), `video_ingest`, `web_search`, `advanced_browser`, `python_execute` |
| apify-scraper | `.weebot/skills/apify-scraper` | SKILL.md | the ten `apify_*` presets (lines 19-28) |
| code-review | `.weebot/skills/code-review` | SKILL.md | - |
| find-bugs | `.weebot/skills/find-bugs` | SKILL.md | - |
| integration-test-skill | `.weebot/skills/test-skill` | SKILL.md | - ("Temporary skill to verify install + BM25 rebuild") |

"Tools it names" lists backticked names that match a `BaseTool.name` or an Apify preset; every one exists.

Consequences (read from source, not run):
- The seven `manifest.json` skills (berb-research, competitive_analysis, design-taste, multi_llm_orchestrator, reasoner, skill-author, web_research) load through `_parse_manifest` (`weebot/application/skills/skill_registry.py:79-80, 188-211`), so the agent can be given `multi_llm_orchestrator`, which the root `CLAUDE.md` requires delegating to.
- `youtube-download` and `remotion-video` point at `youtube_download`, which only `researcher` and `admin` have; `desktop-automation` at `desktop_a11y`, which only `admin` has (`weebot/application/services/tool_registry.py:27-185`). A skill naming a tool does not grant it.
- `apify-scraper` declares its key as top-level `requires_env` (`.weebot/skills/apify-scraper/SKILL.md`, lines 5-6); the parser reads `metadata.env` (`weebot/application/skills/skill_registry.py:158`), so the skill is ready, and can be injected, when the Apify tools are absent.
- A skill with no `trust` is trusted (`weebot/application/skills/skill_registry.py:248-251`). The ClawHub importer writes into a caller-given `install_dir` (its docstring example is `~/.weebot/skills`, `weebot/application/skills/clawhub_importer.py:81`; only tests call it) and forces `metadata.trust: quarantined` on both its writers (`weebot/application/skills/clawhub_importer.py:52-70, 227`), so imported skills fail the retrievers' trust gate until promoted.

## Connected to
- **Loaded by** `SkillRegistry` (stub `objects/_index.md`). **Retrieved by** `BM25SkillRetriever` / `SemanticSkillRetriever` / `RerankingSkillRetriever`. **Written by** `SkillMaterializer` and `MaterializingSkillStore` (`weebot/application/services/materializing_skill_store.py:43`, candidate and trusted saves, and a demotion of a skill already on disk).
- **Looks like but is not:** tools (`weebot/tools/`, card `tools/RoleBasedToolRegistry.md`); personas (card `tools/Personas.md`); `weebot/application/skills/builtin/` (optimizer prompts, its own `loader.py`).

## If you change this
**Hits:** which instructions the executor gets per task; tests `tests/unit/skills/test_ponytail_skills.py`, `tests/unit/test_semantic_skill_retriever.py`, `tests/unit/tools/test_skill_cli.py`, `tests/unit/tools/test_skill_hermes.py`, `tests/unit/tools/test_skill_progressive_disclosure.py`, `tests/unit/tools/test_agent_reach.py`, `tests/unit/tools/test_camofox_browser.py`, `tests/unit/tools/test_remotion_video.py`, `tests/unit/test_layer_classifier.py`.
**Does not hit:** tool availability; a skill naming a tool does not grant it.

## Surfaces
`python -m cli.main skills ...` (`cli/commands/skills.py`); the executor system prompt.

## See
`weebot/application/skills/skill_registry.py`
