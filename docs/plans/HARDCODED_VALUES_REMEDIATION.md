# Single Source of Truth — Hardcoded Values Remediation Plan

**Source:** SRE audit of hardcoded model names, URLs, paths, magic numbers, prompts, and provider strings  
**Principle:** Every configurable value must be defined exactly once and referenced everywhere else  
**Estimated effort:** ~2 days

---

## 1. Hardcoded Model Names → `config/model_refs.py`

### 1.1 Use existing constants (0.5 day)

These files hardcode model names that already HAVE constants in `model_refs.py` — just import and use them.

| Step | File | Line | Current | Replace with |
|------|------|------|---------|--------------|
| M1 | `application/cqrs/commands.py` | 21 | `model: str = "gpt-4"` | `MODEL_COMMAND_DEFAULT` |
| M2 | `core/agent.py` | 34 | `model="gpt-4"` | `MODEL_DEPRECATED_AGENT` |
| M3 | `core/tool_agent.py` | 55 | `model or os.getenv("WEEBOT_MODEL", "gpt-4o-mini")` | `model or os.getenv("WEEBOT_MODEL", MODEL_DEPRECATED_TOOL_AGENT)` |
| M4 | `application/di.py` | 261 | `model = default_model or "openrouter/auto"` | `model = default_model or MODEL_DI_FALLBACK` |

### 1.2 Add missing constants to `model_refs.py` and wire (0.25 day)

These files use model names that don't have dedicated constants yet.

| Step | File | Line | Hardcoded | New constant |
|------|------|------|-----------|-------------|
| M5 | `infrastructure/adapters/rtk_ai_router.py` | 44–51 | `"gpt-4o-mini"`, `"gpt-4o"`, `"gpt-3.5-turbo"` | `MODEL_RTK_FALLBACK_FAST`, `MODEL_RTK_FALLBACK_STANDARD`, `MODEL_RTK_FALLBACK_LEGACY` |
| M6 | `tools/mixture_of_agents.py` | 23–26 | `["openai/gpt-4o-mini", "anthropic/claude-3-5-haiku", "google/gemini-flash-1.5", "meta-llama/llama-3.3-70b-instruct"]` | `MODEL_MOA_REFERENCE_MODELS: list[str]` in `model_refs.py` |
| M7 | `core/tool_agent.py` | 18 | `MAX_STEPS = 30` | Replace with `constants.MAX_EXECUTOR_STEPS` (already 25 — note: **this changes behavior** from 30→25) |

### 1.3 Remove docstring fake-data hardcodes (0.25 day)

| Step | File | Action |
|------|------|--------|
| M8 | `interfaces/web/routers/dashboard.py` | Replace `ModelUsage(name="GPT-4o", ...)` sample data with values from `model_registry` |
| M9 | `infrastructure/adapters/llm/resilient_adapter.py`, `core/workflow_tracer.py`, `infrastructure/llm/langchain_adapter.py`, `infrastructure/event_logging.py`, `infrastructure/event_store.py`, `utils/cost_ledger.py` | Replace docstring example model names with `model_refs.MODEL_COMMAND_DEFAULT` references |

**Verification:**
```bash
grep -rn '"gpt-4"' weebot/ --include="*.py" | grep -v test_ | grep -v docs/ | grep -v model_refs | grep -v model_registry
# Expected: 0 results (all references use constants)
```

---

## 2. Hardcoded URLs → `config/settings.py` or `config/api_endpoints.py`

### 2.1 Centralize API base URLs (0.25 day)

| Step | File | Line | Current | Fix |
|------|------|------|---------|-----|
| U1 | New: `config/api_endpoints.py` | — | — | `API_BASE_URLS = {"deepseek": "...", "openrouter": "...", "openai": "..."}` |
| U2 | `infrastructure/adapters/llm/deepseek_adapter.py` | 19 | `base_url="https://api.deepseek.com"` | Import from `api_endpoints.API_BASE_URLS["deepseek"]` |
| U3 | `infrastructure/adapters/llm/openrouter_adapter.py` | 21 | `base_url="https://openrouter.ai/api/v1"` | Import from `api_endpoints.API_BASE_URLS["openrouter"]` |
| U4 | `tools/web_search.py` | 9–10 | `_DDG_URL`, `_BING_URL` | Move to `api_endpoints.py` as `SEARCH_DDG_URL`, `SEARCH_BING_URL` |
| U5 | `tools/weather_tool.py` | 11 | `_WTTR_URL` | Move to `api_endpoints.py` as `WEATHER_WTTR_URL` |

---

## 3. Hardcoded Paths → `config/settings.py`

### 3.1 Use existing path settings (0.25 day)

| Step | File | Current | Fix |
|------|------|---------|-----|
| P1 | `tools/persistent_memory.py` | `~/.weebot/memory/` | `settings.WEEBOT_HOME / "memory"` |
| P2 | `infrastructure/persistence/filesystem_memory.py` | `Path.home() / ".weebot" / "memory"` | Same |
| P3 | `tools/file_editor.py` | `_WORKSPACE_ROOT = "C:\\Users\\Public\\..."` | `settings.WORKSPACE_ROOT` (already exists!) |
| P4 | `interfaces/web/routers/dashboard.py` | `WORKSPACE_ROOT / "weebot_sessions.db"` | `constants.DB_SESSIONS_PATH` (already exists!) |
| P5 | `application/di.py` | `db_path="./weebot_sessions.db"` | Replace with `constants.DB_SESSIONS_PATH` |
| P6 | `application/di.py` | `scheduler_db="./weebot_jobs.db"` | New `constants.DB_JOBS_PATH` |

---

## 4. Magic Numbers → `config/constants.py`

### 4.1 Add missing constants and wire (0.25 day)

| Step | File | Current | New constant |
|------|------|---------|-------------|
| N1 | `application/flows/plan_act_flow.py` | `max_step_repetitions=3`, `max_iterations=50` | `DEFAULT_MAX_STEP_REPETITIONS`, `DEFAULT_MAX_FLOW_ITERATIONS` — constructor params already exist, just define defaults as constants |
| N2 | `application/flows/skill_opt_flow.py` | `epochs=4`, `batch_size=40`, `minibatch_size=8` | `DEFAULT_SKILLOPT_EPOCHS`, `DEFAULT_SKILLOPT_BATCH`, `DEFAULT_SKILLOPT_MINIBATCH` |
| N3 | `application/agents/chat_agent.py` | `MAX_CONTEXT_MESSAGES=50` | `constants.MAX_CHAT_CONTEXT_MESSAGES` |
| N4 | `core/tool_agent.py` | `MAX_STEPS=30` | Replace with `constants.MAX_EXECUTOR_STEPS` (already = 25 — **behavior change**) |
| N5 | `infrastructure/mcp/mcp_client_manager.py` | `max_retries=3`, `base_delay=1.0`, `max_delay=10.0` | `constants.MCP_MAX_RETRIES`, `MCP_RETRY_BASE_DELAY`, `MCP_RETRY_MAX_DELAY` |
| N6 | `infrastructure/external_service_integration.py` | `timeout=30`, `retry_attempts=3` | `constants.EXTERNAL_SERVICE_TIMEOUT`, `EXTERNAL_SERVICE_RETRIES` |

---

## 5. System Prompts → `config/prompts/`

### 5.1 Externalize remaining inline prompts (0.5 day)

| Step | File | Prompt variable | New file |
|------|------|----------------|----------|
| S1 | `application/agents/planner.py` | `PLANNER_SYSTEM_PROMPT` (~30 lines) | `config/prompts/planner_system.txt` |
| S2 | `application/agents/planner.py` | `UPDATE_PLAN_SYSTEM_PROMPT` (~6 lines) | `config/prompts/planner_update.txt` |
| S3 | `core/tool_agent.py` | `SYSTEM_PROMPT` | `config/prompts/tool_agent_system.txt` |
| S4 | `tools/mixture_of_agents.py` | `_AGGREGATOR_SYSTEM` | `config/prompts/moa_aggregator.txt` |
| S5 | `tools/mixture_of_agents.py` | `_REFERENCE_SYSTEM` | `config/prompts/moa_reference.txt` |

**Pattern:** Load from file on first access, with inline fallback. Same as `_load_executor_system_prompt()` in `executor.py`.

---

## 6. Provider Strings → `model_registry.ModelProvider` Enum

### 6.1 Replace string-based provider dispatch with enum (0.25 day)

| Step | File | Current | Fix |
|------|------|---------|-----|
| E1 | `application/di.py` | `if "/" in model: provider = "openrouter" elif model.startswith("claude"): ...` | Use `ModelProvider.from_model_name(model)` |
| E2 | New method in `model_registry.py` | — | `ModelProvider.from_model_name(model: str) -> ModelProvider` — encodes the if/elif logic once |
| E3 | `config/tool_config.py` | String comparisons for tool routing | Same pattern |

**Verification:**
```bash
grep -rn '"openrouter"\|"anthropic"\|"deepseek"\|"openai"' weebot/ --include="*.py" | grep -v test_ | grep -v model_registry | grep -v __pycache__
# Expected: 0 results (except in config/model_registry.py which IS the source)
```

---

## Dependency Order

```
1.1 (model names) ──┐
1.2 (new constants) ┤
6.1 (provider enum) ┤ All independent — can run in parallel
2.1 (URLs)          ┤
3.1 (paths)         ┤
4.1 (magic numbers) ┤
5.1 (prompts)       ┘
```

All seven workstreams are independent — no cross-dependencies.

---

## Risk Register

| # | Risk | Probability | Mitigation |
|---|------|------------|------------|
| R1 | Changing `MAX_STEPS` from 30 → 25 in `tool_agent.py` changes legacy agent behavior | Low | `tool_agent.py` is deprecated (Bucket D). Document the change; no production impact. |
| R2 | `file_editor.py` switching from inline `_WORKSPACE_ROOT` to `settings.WORKSPACE_ROOT` may have import cycle | Low | Both already import `config/` modules without issues |
| R3 | `dashboard.py` fake sample data removal may break UI rendering | Low | Remove only the hardcoded model names; keep the structure |

---

## Verification Gates

```bash
# Gate 1: No hardcoded model strings outside config
grep -rn '"gpt-4\|"gpt-4o\|"claude-3\|"deepseek-chat' weebot/ --include="*.py" | grep -v test_ | grep -v docs/ | grep -v model_refs | grep -v model_registry | grep -v '\.reasonix'

# Gate 2: No hardcoded provider strings outside model_registry
grep -rn '"openrouter"\|"anthropic"\|"deepseek"\|"openai"' weebot/ --include="*.py" | grep -v model_registry | grep -v test_ | grep -v '\.reasonix'

# Gate 3: Architecture fitness tests still pass
pytest tests/unit/test_architecture_fitness.py -v  # → 19 pass, 0 skip

# Gate 4: All unit tests pass
pytest tests/unit/ -v -q  # → all pass
```
