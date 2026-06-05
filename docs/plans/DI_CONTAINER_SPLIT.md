# DI Container Split Plan — Weebot `di.py`

**Target:** Split `weebot/application/di.py` (973 lines, 64 methods) into `di/` subpackage
**D3 Debt:** God DI container — 17+ singleton factories in one file
**Score impact:** Scalability 8→9, pushing total from 9.3 → 9.5+
**Risk:** MEDIUM — wiring changes, no behavior change
**Effort:** 1 day

---

## Structure After Split

```
weebot/application/
├── di.py                    # ~150 lines — Container core + imports
└── di/
    ├── __init__.py           # Re-exports Container
    ├── _factories.py         # 23 @staticmethod factory methods
    ├── _agent_tools.py          # Web-clone multi-agent bindings
    ├── _capabilities.py     # AgentWasp + scheduler bindings
    ├── _skills.py           # SkillCurator bindings
    └── _skillopt.py         # SkillOpt bindings (~200 lines, largest)
```

## Method Groupings

### Keep in `di.py` (Container core) — ~150 lines

| Method | Lines | Rationale |
|--------|-------|-----------|
| `__init__` (`@dataclass` fields) | ~5 | State |
| `register()` / `register_instance()` | ~9 | Core API |
| `get()` | ~14 | Core API |
| `configure_defaults()` | ~75 | Orchestrator — wires ALL factories |
| `_maybe_get()` / `_maybe_get_str()` | ~12 | Utility |
| `build_agent_runner()` | ~20 | Public builder |
| `build_mediator()` | ~42 | Public builder |
| `build_chat_flow()` | ~15 | Public builder |
| `_maybe_get_model()` | ~4 | Utility |
| `validate()` | ~12 | Diagnostic |

**Total: ~208 lines**

### Extract to `di/_factories.py` — ~180 lines

23 static methods that create adapters. These are pure factory functions with no `self` dependency (except `_create_event_bridge` which needs `self.get()`).

| Method | Lines |
|--------|-------|
| `_create_state_repo` | 12 |
| `_create_event_bus` | 3 |
| `_create_tracing` | 3 |
| `_create_event_bridge` | 4 (uses `self.get()`) |
| `_create_activity_stream` | 3 |
| `_create_tool_repo` | 5 |
| `_create_structured_logger` | 3 |
| `_create_config_adapter` | 3 |
| `_create_audit_service` | 3 |
| `_create_memory_adapter` | 4 |
| `_create_speech` | 4 |
| `_create_event_store` | 3 |
| `_create_response_cache` | 3 |
| `_create_sandbox` | 38 |
| `_create_llm` | 5 |
| `_create_mediator` | 2 |
| `_create_task_runner` | 4 |
| `_create_steering` | 4 |
| `_create_task_router` | 3 |
| `_create_personality` | 3 |
| `_create_harness_config` | 12 |
| `_create_kg_adapter` | 4 |
| `_create_browser_inspector` | 2 |

**Subtotal: ~130 lines + imports**

### Extract to `di/_agent_tools.py` — ~65 lines

Web-clone multi-agent tool bindings.

| Method | Lines |
|--------|-------|
| `configure_web_clone` | 13 |
| `_create_browser_inspector` | 3 |
| `_create_dispatch_agents` | 10 |
| `_create_workflow_orchestrator` | 11 |
| `_build_plan_act_flow_for_session` | 18 |

### Extract to `di/_capabilities.py` — ~110 lines

AgentWasp capability bindings + background job registration.

| Method | Lines |
|--------|-------|
| `configure_agentwasp_capabilities` | 22 |
| `_create_kg_service` | 6 |
| `_create_behavioral_learner` | 6 |
| `_create_opportunity_engine` | 7 |
| `register_agentwasp_jobs` | 70 |

### Extract to `di/_skills.py` — ~50 lines

SkillCurator bindings.

| Method | Lines |
|--------|-------|
| `configure_skill_curator` | 7 |
| `_create_skill_curator` | 12 |
| `register_curator_job` | 30 |

### Extract to `di/_skillopt.py` — ~200 lines

SkillOpt bindings — largest group.

| Method | Lines |
|--------|-------|
| `configure_skillopt` | 48 |
| `build_skill_opt_flow` | 75 |
| `_create_llm_by_id` | 3 |
| `_create_optimizer_agent` | 5 |
| `_create_skill_store` | 3 |
| `_create_trajectory_repo` | 5 |
| `_create_evolution_tracker` | 3 |
| `_create_validation_gate` | 12 |
| `_create_target_flow_factory` | 20 |
| `_create_scorer` | 43 |

## Implementation Approach: Mixin Classes

Each extracted file defines a Mixin class. `Container` inherits from all mixins:

```python
# di.py
from weebot.application.di._factories import FactoriesMixin
from weebot.application.di._agent_tools import AgentToolsMixin
from weebot.application.di._capabilities import CapabilitiesMixin
from weebot.application.di._skills import SkillsMixin
from weebot.application.di._skillopt import SkillOptMixin

@dataclass
class Container(FactoriesMixin, AgentToolsMixin, CapabilitiesMixin,
                SkillsMixin, SkillOptMixin):
    _bindings: dict[type, Callable[[], Any]] = field(default_factory=dict)
    _singletons: dict[type, Any] = field(default_factory=dict)
    # ... core methods
```

Each mixin:
- Has NO `__init__` (relies on `@dataclass` from Container)
- Uses `self._bindings`, `self._singletons`, `self.get()`, etc. from Container
- Is a plain class (not `@dataclass`) with local imports for adapter classes

## Execution Sequence

### Phase 1: Create `di/_factories.py` (lowest risk, 23 methods)

1. Create the mixin class with all 23 factory methods
2. Update `di.py` imports (add `from .di._factories import FactoriesMixin`)
3. Add `FactoriesMixin` to Container's parent classes
4. Remove the 23 methods from Container
5. Verify: `python -c "from weebot.application.di import Container; c=Container(); c.configure_defaults()"`

### Phase 2: Create `di/_agent_tools.py`

1. Create AgentToolsMixin
2. Inherit into Container
3. Remove methods

### Phase 3: Create `di/_capabilities.py`

1. Create CapabilitiesMixin
2. Inherit into Container
3. Remove methods

### Phase 4: Create `di/_skills.py`

1. Create SkillsMixin
2. Inherit into Container
3. Remove methods

### Phase 5: Create `di/_skillopt.py` (highest risk)

1. Create SkillOptMixin
2. Inherit into Container
3. Remove methods

### Phase 6: Create `di/__init__.py`

```python
"""DI subpackage — split from di.py to reduce God DI anti-pattern."""
from weebot.application.di import Container
```

### Phase 7: Verify

```bash
python -c "
from weebot.application.di import Container
c = Container()
c.configure_defaults()
errors = c.validate()
assert not errors, f'DI validation errors: {errors}'
print(f'OK: {len(c._bindings)} bindings, {len(c._singletons)} singletons created')
"
pytest tests/unit/test_architecture_fitness.py tests/unit/test_port_contracts.py -v
```

## Backward Compatibility

All existing callers are unaffected:
- `from weebot.application.di import Container` — unchanged
- `container.configure_defaults()` — unchanged
- `container.get(SomePort)` — unchanged
- `container.build_agent_runner()` — unchanged

The only change is structural: methods move from Container class body into mixin parent classes.

## Rollout

| Phase | Risk | Lines Moved | Verifcation |
|-------|------|-------------|-------------|
| 1: _factories | LOW | 130 | All 23 factories return same objects |
| 2: _agent_tools | LOW | 65 | Web-clone configure unchanged |
| 3: _capabilities | MEDIUM | 110 | AgentWasp + scheduler intact |
| 4: _skills | LOW | 50 | Curator unchanged |
| 5: _skillopt | MEDIUM | 200 | SkillOptFlow builder intact |
| 6: __init__ | TRIVIAL | 3 | Re-export works |
| 7: Verify | TRIVIAL | — | All tests pass |

**Rollback per phase:** `git checkout` the individual mixin file and remove its inheritance from Container.

## Success Criteria

- [ ] `di.py` reduced from 973 to ≤ 200 lines
- [ ] `Container` unchanged public API (imports, `configure_defaults()`, `get()`, `build_*()`)
- [ ] `python -c "from weebot.application.di import Container; c=Container(); c.configure_defaults()"` succeeds
- [ ] `container.validate()` returns empty list
- [ ] All architecture fitness tests pass
- [ ] All port contract tests pass
