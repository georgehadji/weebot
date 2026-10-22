# How to walk this map

## Universes

| Universe | Meaning |
|---|---|
| live | In force. Implement and cite against these. |
| leftover | Still present, no longer the main path. Touch only if that path is in scope. |
| ghost | Named or filed but not wired. Do not implement against these. |

Current flags (from `tasks/icm_slice0_inventory.md`):
- leftover: `weebot/osworld/` (only `tests/unit/test_osworld_adapter.py` imports it).
- unresolved: `agent_core_v2` is named in `ARCHITECTURE.md` (ADR-009, sunset 2027-03-01) but no file by that name was found; locate it before flagging.
- data, not code: `weebot/skills/builtin/*/SKILL.md` is loaded by path, not imported.

## Names that collide (product word vs code)

| Word | Means here | Source | Do not confuse with |
|---|---|---|---|
| persona | a markdown-defined agent identity, routed by score | `AgentPersona` `weebot/agents/models.py:46`, `PersonaScore` `weebot/agents/router.py:11`, CLI `agents list` | the LLM roles `PlannerAgent` `weebot/application/agents/planner.py:77` and `ExecutorAgent` `weebot/application/agents/executor/_base.py:197` |
| skill | a `SKILL.md` / manifest package, looked up by `SkillRegistry` `weebot/application/skills/skill_registry.py:27` | `weebot/skills/builtin/` | a tool: callable code in `weebot/tools/`, registered in `RoleBasedToolRegistry` `weebot/tools/tool_registry.py:15` |
| flow | the state machine `PlanActFlow` `weebot/application/flows/plan_act_flow.py:73` | `weebot/application/flows/` | a session: persisted record `Session` `weebot/domain/models/session.py:201`; `cli flow run` creates one |
| plan / step | domain models `Plan` `weebot/domain/models/plan.py:154`, `Step` `:53` | | a "workflow template" (YAML, `weebot/templates/`) |
| ModelConfig | the catalog entry returned by `get_model_config` | `weebot/domain/models/model_config.py:22` | the dataclass of the same name in `weebot/core/model_cascade_config.py:38` (task-table row) |
| approval | a rule outcome (`ApprovalMode`) from `ExecApprovalPolicy`, enforced by the shell tools | `weebot/core/approval_policy.py:21` | `ApprovalDecision` / `ApprovalManager` in `weebot/core/approval.py`, a human-answer layer that nothing calls |
| risk level | `RiskLevel` (4 levels incl. BLOCKED) for `BashGuard` | `weebot/core/bash_guard.py:29` | `CommandRiskLevel` (3 levels) for `CommandSecurityAnalyzer`, `weebot/tools/bash_security.py:25` |

## Walking order

1. `map/CLAUDE.md` for routing.
2. `objects/_index.md` for the one-line noun list.
3. One card. Do not read the whole `objects/` folder.

Layer rules are enforced elsewhere: `.importlinter`, `tests/unit/test_architecture_fitness.py`. The map describes them, it does not replace them.
