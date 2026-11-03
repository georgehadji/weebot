---
status: open
date: 2026-11-03
note: implementation plan for the H1-H42 parity backlog of hermes_v022_weebot_comparison.md; phases 0-6, one design per item (paradigm, patterns, interfaces, files, tests, gates); nothing started
---

# Hermes v0.22 parity: implementation plan

**Source backlog:** [hermes_v022_weebot_comparison.md](hermes_v022_weebot_comparison.md), §7 (H1-H40).
**Baseline:** `main`-line code at `321cd868` (branch `chore/openrouter-catalog-refresh-2026-11-03`).
**Method:** before this plan was written, three read-only passes checked every landing point in the code. Line numbers come from those passes. **Re-check each `file:line` before editing**, because the code moves.
**Goal:** Weebot should match or beat Hermes on every row of the 43-row matrix (§4 of the source), while keeping the eight places Weebot already leads (§5). The FSM, cascade, D5 taint, evals, layer enforcement, observability, Windows sandboxes and multi-agent patterns are the product, and this plan builds on them rather than replacing them.

The mapping passes found 15 defects that the comparison study missed (§15). Among them:
- security gaps, such as skills with no trust key counting as trusted, and browser fills bypassing `BrowserPort`;
- a rate-limit routing bug;
- caching telemetry that is always wrong.

They are folded into the items below, and two of them get new IDs (H41, H42).

---

## Contents

1. Ground rules every PR follows
2. Paradigm and pattern guide (which tool for which module)
3. Owner decisions needed before or during the work
4. Sequencing, dependency graph and milestones
5. Phase 0: correctness and security (H1, H2, H3, H4, H5, H41, H42)
6. Phase 1: token economics and context (H7, H9, H10, H11, H15, H16, Q1)
7. Phase 2: tool depth (H6, H17, H18, H20, H20b, H21)
8. Phase 3: MCP, secrets, egress (H12, H12b, H13, H19, H23)
9. Phase 4: gateways and automation (H8, H27, H28, H29, H30)
10. Phase 5: extensibility and supply chain (H14, H24, H25, H26, H33)
11. Phase 6: selective breadth (H22, H31, H32, H34-H40)
12. ADRs, docs and map cards to write
13. Measurement plan (how "equal or better" is proven)
14. Risks register
15. Appendix: defects found during mapping

---

## 1. Ground rules every PR follows

These come from `CLAUDE.md`, `.importlinter`, `tests/unit/test_architecture_fitness.py` and `tasks/quality/ceilings.toml`. Each item below assumes them without repeating them.

### 1.1 Layering and wiring

- **Ports** go in `weebot/application/ports/<thing>_port.py` as an `ABC` with `@abstractmethod`. That is the majority style; `ToolGuard`, `HookRegistryPort` and `IGatewaySessionStorePort` are Protocols.
  - Use a `Protocol` only for a structural, single-method seam that many unrelated classes satisfy, such as `ToolGuard` or `CompressionPass`.
  - Every new port goes into `port_adapter_map` (`test_architecture_fitness.py:345`) or into `known_orphans` (`:982`).
- **Domain models** go in `weebot/domain/models/`, written in pydantic v2.
  - Use `frozen=True` for value objects.
  - Small internal records may be frozen `@dataclass(slots=True)` in application or core.
- **Adapters** go in `weebot/infrastructure/...`. Register them in `Container.configure_defaults` (`weebot/application/di/__init__.py:139`):
  - with typed `Key[T]` (`di/keys.py`) or the port class;
  - **never** with a new string key, because `string_di_keys = 44` is ratcheted;
  - with factories in the relevant `di/_*.py` mixin.
  - No adapter is constructed outside DI. `container_construction = 7` is ratcheted.
- **Tools** (`weebot/tools/`) never import `weebot.infrastructure` or `sqlite3` (contracts `tools-no-infra` and `tools-no-db`). They get their collaborators injected through DI factories in `di/_agent_tools.py`.
  - Removing an `ignore_imports` exemption lowers `import_exemptions` (58).
- **No module-global session-keyed state.** This was finding WB-03 of the 2026-10 wave 2 audit. Session-scoped state lives in a DI singleton with a bounded LRU and an eviction hook. That hook is registered in the session purge registry, `weebot/interfaces/web/dependencies.py:_session_stores()`.

### 1.2 Config, flags, secrets

- **Behaviour flags** go in `weebot/config/feature_flags.py` as `NAME: bool = _env_bool("WEEBOT_NAME", default=...)`.
  - A flag defaults to off only where the risk is real. Each item states its default and the reason for it.
- **Tunables** go in `WeebotSettings` (`weebot/config/settings.py:37`) as `Field(validation_alias=AliasChoices("WEEBOT_X", "X"), default=..., description=...)`.
  - Regenerate `.env.example` with `scripts/generate_env_example.py`.
- **Secrets** are read only through `SecretAccessor` (`weebot/config/secret_accessor.py:101`). `bare_env_reads = 60` may only go down.

### 1.3 Persistence and events

- **SQLite schema** changes go in two places:
  - the owning repo's `_ensure_schema`, as `CREATE TABLE IF NOT EXISTS` or `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`;
  - a new alembic revision whose `down_revision` is the current head, `f2c0mm1t0001`.
  - `tests/integration/test_migration_schema_matches_app.py` must stay green.
- **Events:**
  - Declare a new `DomainEvent` subclass in `weebot/domain/models/event.py`.
  - If it can land in `Session.events`, add it to the `AgentEvent` union. A missing member makes stored sessions unloadable (comment at `event.py:586-589`).
  - Document it in `docs/EVENT_CATALOG.md` (`test_all_event_types_documented`, `:801`).

### 1.4 Size, safety and the gates

- **Size:** god-module cap of 800 lines (`:945`); `functions_over_150_lines = 23`. New functions stay under 60 lines, and new modules under 400.
  - Several touched files are near the cap: `_cascade.py` 799, `_tool_executor.py` 676, `_base.py` 660. New behaviour goes in **new sibling modules**, never into those files.
- **Safety:**
  - Every shell command goes through `bash_guard`.
  - Every `except` logs.
  - No `print()`.
  - Untrusted content stays fenced, with `wrap_untrusted`.
- **Map and ADRs:**
  - Every new noun gets a `map/objects/<layer>/<name>.md` card from `map/_templates/object.md`.
  - Run `scripts/check_map_citations.py --fix` after moves.
  - Every cross-cutting decision gets an ADR in `docs/adr/` (next number is **016**; see §12).
- **Tests:** 1-2 behaviour-contract tests per fix, proven red on the base before the fix. No change-detector or source-reading tests, except the deliberate lock gates named in H10.
- **Definition of done per PR:**
  - `make check` passes: tests, arch, lints, map, ceilings at exact equality.
  - Ceilings are lowered where debt was paid.
  - Docs are touched: `SECURITY_MODEL.md`, `CONFIGURATION.md`, `ENTRY_POINTS.md`, `EVENT_CATALOG.md`, as relevant.
  - Eval deltas are attached for any item marked **[eval-gated]** (§13).

---

## 2. Paradigm and pattern guide

The rule is: **functional core, imperative shell.**
- Decisions (classify, match, plan, detect, coerce, parse) are pure functions over immutable inputs. They are unit-tested without mocks.
- I/O (LLM calls, subprocesses, sockets, DB) sits in thin adapters behind ports.

This is how `core/trust_boundary.py`, `core/error_classifier.py` and `tool_call_repair.py` are written today, and this plan keeps the style.

| Module kind | Paradigm | Patterns | Where it applies | Why |
|---|---|---|---|---|
| Classifiers, policies, matchers, parsers | Pure functional; immutable inputs; total functions returning values (never raising for "no match") | Specification (composable predicates), Table-driven dispatch (dict → handler, never `if` ladders) | H2 cache predicate, H3 ladder planner, H11 detectors, H16 coercion, H6 match strategies, H18 floors, H30 schedule parser | Deterministic, trivially testable, no mocks, safe to call from any layer |
| Ordered fallbacks | Functional pipeline | Chain of Responsibility (first match wins), Strategy objects in an ordered tuple | H3 recovery ladder, H6 fuzzy patch chain, H9 compression passes, H19 secret resolvers | Order is data, so a new step is one line in the tuple, and each step is tested alone |
| Cross-cutting interception of tool calls | OO composition | Chain of Responsibility (existing `GuardChain`), Middleware chain (existing `application/middleware`), Decorator (`GuardedTool`) | H16, H18, H20 late diagnostics, H7 spillover, H33 hooks | One interception mechanism; plugins and hooks become middleware adapters rather than a second hook system |
| LLM adapters | OO | Decorator stack (`Caching → Resilient → Bounded`, existing), Adapter | H2, H3, H13 | Already the house shape; new behaviour is a new decorator or a fix in one |
| Flow control | State machine | State (existing `FlowState` classes) | H27 `GoalCheckState`, H20b verify gate | Weebot's FSM is its lead over Hermes; long-horizon autonomy becomes a state, not a prompt |
| Commands from UI, CLI and gateways | Message passing | Command + Mediator (existing CQRS), frozen pydantic commands, `CommandResult` | H5 rollback, H21 undo/retry/branch, H27 `/btw`, H8 pairing, H26 steer/stop | One entry point for web, CLI and gateway; behaviours (logging, validation, telemetry) come free |
| Durable side effects | Append-only log | Event journal (existing `EventStorePort`), Outbox (at-least-once + idempotency key), Ledger | H20b evidence, H26 delegation ledger, H29 delivery outbox, H14 skill mutation ledger | Crash-safe and auditable; rewinds never rewrite history |
| Snapshots and undo | Value snapshots | Memento (shadow-git tree object, session event cut), Command (inverse operations) | H5, H21, H14 rollback | Restore is "apply a memento", and restoring creates a memento of its own (undo the undo) |
| Long-lived per-session workers | Actor-style concurrency | One `asyncio` task per actor with a mailbox (`asyncio.Queue`), supervised by a bounded LRU manager | H17 kernels, H20 LSP servers, H29 per-chat busy state | Serialises access to a stateful process; eviction is explicit; no shared mutable state |
| Resource limits | Declarative policy objects | Policy value object + context manager (RAII) + Bulkhead (semaphore owned by a DI singleton) + Circuit breaker (existing) | H4 delegation, H13 key pools, H12 sampling caps | Limits are data on a frozen object, enforced at one choke point |
| Extension | Plugin architecture | Registry + entry points + Facade (`PluginContext`) + Capability consent (hash-pinned) | H33, H28 adapters, H19 sources, H24 memory providers | Breadth grows at the edges; the core stays a narrow waist (Hermes's own axiom) |
| Gateways | OO template | Template Method (base runs the turn; subclasses implement `send`/`edit`/`typing`), Capabilities value object, sum-type results | H28, H29 | Replaces the string-sentinel dispatch (`OK_SET_MODEL:x`) with typed results |
| External identity and secrets | Ports & adapters | Composite resolver, Proxy (credential vault handles), Ambassador sidecar (egress proxy) | H19, H23, H12 OAuth | Secrets never pass through the model or the transcript |

### 2.1 Anti-patterns this plan refuses

- **A second parallel enum or registry for something that already exists.** For example, extend `ErrorCategory` (H3) instead of adding `FailoverReason`. Make `HookRegistryPort`'s implementation an adapter over `MiddlewareChain` (H16/H33).
- **String-sentinel return values for control flow.** The gateway dispatcher's `OK_*` strings are replaced in H29.
- **God objects and import-time construction.** Hermes still has these. They are flagged in the `ARCHITECTURE.md` debt list.
- **Hidden network or LLM calls inside a pure decision function.**
- **Hermes's flat ReAct loop, "OS is the only boundary", and third-party products in core.** See §8 of the source study.

---

## 3. Owner decisions needed

Each of these changes behaviour that a user would notice, or reverses an earlier decision. The plan gives a recommendation for each, and the work proceeds on it unless the owner overrides.

| # | Decision | Recommendation | Affects |
|---|---|---|---|
| D1 | Owner decision **D-F** (2026-10-31) parked P1-P4 of the unified plan: plugin platform, Environment port, ACP bridge and credential pool. The reason given was "no current consumer". | **Keep them parked** (H33, H22, H38, H13), and build their consumers' minimal needs in core first:<br>• an adapter registry for H28;<br>• a resolver chain for H19.<br>Un-park H33 when a second out-of-tree adapter or source exists. | H13, H22, H33, H38 |
| D2 | Prompt caching on by default for Claude routes. Cache writes cost 1.25×; cache reads cost 0.1×. | **On.** Every executor step re-sends the same prefix several times. Net savings are expected from step 2 of any session; H10 proves it. | H2, H10 |
| D3 | Tool-scope granularity. Today ADR-008 re-scopes `tools[]` every step, which breaks the cache at every step boundary. | **Make it a setting** (`step` or `plan`, default `step`). Decide by eval (H10): `plan` sends the union of the plan's step scopes once per run. | H10 |
| D4 | File checkpoints on by default. They cost disk space under `data/checkpoints`. | **On, with caps:**<br>• skip workdirs over 20 k files or 500 MB;<br>• keep 50 turns per session;<br>• GC after 14 days. | H5 |
| D5 | MCP stdio servers stop inheriting the full environment. This is a breaking change for servers that relied on an inherited token. | **Do it now.** Migration path: declare `env: {GITHUB_TOKEN: "${GITHUB_TOKEN}"}` (`expand_env` already exists), or list the name in `env_passthrough`. Doctor warns about it. | H1 |
| D6 | Skills with no `trust:` key currently count as **trusted**. | **Make them `candidate`** unless they are built-in. Re-tag the existing installed skills once, with a migration script. | H42, H14 |
| D7 | The OpenAI-compatible API is a new network surface. | **Off by default** (`WEEBOT_OPENAI_API_ENABLED`). It reuses the existing auth stores; there is no new key env var. | H12b |
| D8 | H23 needs a per-session MITM CA trusted inside the Docker sandbox. | **Do step 1 now:** a CONNECT allowlist proxy, with no TLS interception. **Do step 2** (token swap with TLS interception) only if keys must live inside the sandbox. | H23 |
| D9 | Gateway pairing changes who can reach the bot. | Existing allowlists keep working. Pairing only adds a path for new users. Default deny stays. | H8 |

---

## 4. Sequencing, dependency graph, milestones

```
Phase 0 (1.5 wk)  H41 H42 H1 H2 ─┬─ H3 ── H4 ── H5
                                 │
Phase 1 (3 wk)    H16 ─ H7 ─ H11 ┼─ H9 ─┬─ H10 (needs H2 + H24a)
                  H15            │      │
                  Q1             │      └─ H24a (memory freeze, pulled forward from H24)
Phase 2 (4 wk)    H6 ── H20 (needs H16 middleware) ── H20b
                  H18 ── H17 (needs H18 floors + H1 env helper + H16)
                  H21 (needs H5)
Phase 3 (3 wk)    H12 (needs H1, H19 store) ─ H12b ─ H19 ─ H23 (needs H19) ─ [H13 parked, D1]
Phase 4 (4 wk)    H28 ── H29 ── H8 ── H30 (needs H29 outbox) ── H27 (needs H10 for /btw)
Phase 5 (4 wk)    H14 ── H25 ── H24b ── H26 (needs H4) ── [H33 parked, D1]
Phase 6           demand-driven
```

Hard dependencies (the edges above):

| Item | Needs | Reason |
|---|---|---|
| H10 | H2, H24a | Without working cache gating and a frozen memory snapshot, a stable prefix earns nothing |
| H17 | H1, H16, H18 | The kernel needs the shared child-env builder, tool middleware for RPC dispatch, and floors before tool RPC can run unattended |
| H20 | H16 | Late diagnostics attach through `transform_tool_result` |
| H21 | H5 | "Undo" rolls back files together with events |
| H23 | H19 | The proxy reads real keys from the resolver chain |
| H29 | H28 | One gateway base class |
| H30 | H29 | Delivery goes through the gateway outbox |
| H26 | H4 | The ledger records the depth and policy that H4 introduces |

Phases may overlap where no edge exists. The phase order is a priority order, not a set of waterfall gates.

**PR sizing:** one item per PR. L items split along the numbered steps given in each item. Branch names: `feat/hNN-<slug>` or `fix/hNN-<slug>`.

**Milestones:**

| Milestone | Contents | Exit check |
|---|---|---|
| M0 | Phase 0 done | Security and correctness carry-overs closed. `SECURITY_MODEL.md` updated. |
| M1 | Phase 1 done | Cache-read ratio ≥ 60% of prompt tokens on the eval suite's Claude runs. Cost per solved task ≤ 0.7× baseline. |
| M2 | Phase 2 done | Edit-failure loops ≤ 0.5× baseline. Python-kernel tasks use ≥ 30% fewer LLM turns. |
| M3 | Phase 3 done | Remote MCP over OAuth works end to end. Open WebUI drives Weebot over `/v1`. |
| M4 | Phase 4 done | Streaming chat replies and pairing on Telegram, the reference adapter. NL cron with monitor mode. |
| M5 | Phase 5 done | Every skill install path is scanned, locked and ledgered. |

**Total:** about 19-20 engineer-weeks for Phases 0-5.

---

## 5. Phase 0: correctness and security

### H41. Rate-limit tier does not match the real gateway routes (new) — S

**Problem.** `RATE_LIMITS` path tiers (`weebot/interfaces/web/rate_limit.py:38`, `_PATH_TIERS`) key the webhook tier on `/api/discord/`, `/api/slack/` and `/api/whatsapp/`. The routers are mounted at `/api/gateway/<x>/` (`web/main.py:608-620`). The real routes therefore fall into some other tier; the mapping pass did not establish which.

**Design.** Table-driven, as today. Derive the prefixes from the mounted routers instead of literals. Iterate `app.routes` once at startup and map each router to its tier with a `tier` attribute on the router module. This makes drift impossible.

**Changes:** `rate_limit.py`, each gateway router module (`TIER = "webhook"`), `main.py` mount loop.

**Tests:** a contract test that every mounted path resolves to a declared tier, and that `/api/gateway/telegram/x` resolves to `webhook`.

**Acceptance:** 61 requests in 60 s to a gateway webhook path return 429.

### H42. A skill without a `trust:` key counts as trusted (new) — S

**Problem.** `SkillRegistry._trust_tier` (`weebot/application/skills/skill_registry.py:248`) maps a missing `trust` key to **trusted**. `weebot skill install` for WEEBOT and MANUS formats (`cli/commands/skills.py:199-236`) copies `SKILL.md` verbatim, so an imported skill with no key is trusted and gets injected.

**Design.** A pure function `effective_trust(frontmatter, source) -> TrustTier`:
- `source` is `builtin` → `trusted`;
- missing key → `candidate`;
- unknown value → `quarantined`.

The source is known from the path, `weebot/skills/builtin/` versus elsewhere. This is a Specification over two fields.

**Changes:**
- `skill_registry.py`;
- a one-time script `scripts/migrate_skill_trust.py` that writes `trust: candidate` into installed non-builtin skills lacking the key (dry-run by default);
- `docs/SECURITY_MODEL.md`.

**Tests:** a builtin with no key is trusted. `.weebot/skills/x/SKILL.md` with no key is candidate. Candidate skills follow the existing injection rules; only quarantined skills are excluded, at `bm25_skill_retriever.py:72`.

### H1. Environment allowlist for every child process — S

**Problem:**
- MCP stdio passes `env={**os.environ, **env}` (`weebot/infrastructure/mcp/mcp_client_manager.py:163`), so every provider key reaches every MCP server.
- The WSL2 sandbox and one native `Popen` (`infrastructure/sandbox/wsl2.py:138-156`, `native_windows.py:328`) pass `env=merged if merged else None`. An empty merge therefore inherits everything.
- The domain docstring `MCPServerConfig.env` (`domain/models/mcp.py:93`) already promises an "overlay on safe baseline".

**Design:**
- **Pure function** in a new `weebot/core/child_env.py`:
  ```python
  BASE_POSIX = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "USER", "SHELL", "TZ"})
  BASE_WINDOWS = frozenset({"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP",
                            "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
                            "PROGRAMFILES", "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS"})
  PROXY = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"})

  def build_child_env(source: Mapping[str, str], *, declared: Mapping[str, str] = {},
                      passthrough: Iterable[str] = (), inherit_proxy: bool = True,
                      platform: str = sys.platform) -> dict[str, str]: ...
  ```
  - Keys are compared case-insensitively on Windows.
  - Declared values win.
  - The function never returns `None`.
- `source` comes from a new read-only view, `SecretAccessor.environ_view() -> Mapping[str, str]`. This keeps the bare-env-read count from rising; it drops by 1 if `mcp_client_manager.py:163` was counted.
- **Reuse.** Rewrite `native_windows._build_child_env` (`:50`) as a thin wrapper that adds `SandboxConfig.env_vars` and the dead-proxy variables. That way one allowlist serves MCP, native, WSL2 and (H17) kernels.
- **Config.** Add `env_passthrough: list[str]` to the MCP server config. `expand_env` (`infrastructure/mcp/config_loader.py`) already resolves `${VAR}` in declared env.

**Changes:**
- `core/child_env.py` (new);
- `mcp_client_manager.py:163`;
- `wsl2.py:138-156`;
- `native_windows.py:50,220,328`;
- `config/secret_accessor.py`;
- a doctor check: "MCP server X declares no env; it previously inherited N secret-looking names".

**Tests:**
- red first: a fake `stdio_client` captures `params.env`. With `OPENROUTER_API_KEY` in the source, the key is absent;
- declared `${GITHUB_TOKEN}` is present;
- on win32 (`@pytest.mark.platforms` or `skipif`), `APPDATA` is present so that `npx` works;
- WSL2 with an empty merge yields the allowlist, not `None`.

**Gates:** lower `bare_env_reads` if it drops. Map card `core/child_env.md`. `SECURITY_MODEL.md` §secrets.

### H2. Prompt-cache gating, telemetry and flag split — S

**Problem.** These were confirmed by reading the code:
- `_CACHING_MODEL_MARKERS` (`caching_llm_adapter.py:26-30`) cannot match `claude-sonnet-5.5` (`config/model_refs.py:84-96`). `CachingLLMAdapter` therefore never wraps any allowed model.
- `LLM_ENABLE_CACHING` (`adapter_factory.py:104`) gates both prompt caching and the **response cache** in `ResilientLLMAdapter` (`:215`), and defaults to False.
- The telemetry reads `usage["input_tokens"]` (`caching_llm_adapter.py:141`), but adapters emit `prompt_tokens`. It is always 0 and warns on every call.
- `AnthropicAdapter` never reads `cache_read_input_tokens` / `cache_creation_input_tokens`.
- The OpenRouter branch (`openai_adapter.py:218-229`) sends `cache_control` only when tools are present.
- **Unverified:** whether `AnthropicAdapter` passes `role: "system"` messages inside `messages=` instead of `system=`.

**Design:**
- A **Specification**, as a pure function:
  ```python
  _CLAUDE = re.compile(r"^(?:anthropic/)?claude-(?!2|instant)", re.I)
  def supports_prompt_caching(model: str) -> bool: return bool(_CLAUDE.match(model or ""))
  ```
- **Split the flag:**
  - `LLM_ENABLE_PROMPT_CACHING`: a new settings field, default **True** (D2);
  - `LLM_ENABLE_CACHING`: the response cache, unchanged, default False.
- **Telemetry:** read `prompt_tokens`, plus `cached_tokens` or `cache_read_input_tokens`. Emit a Prometheus counter `llm_cache_read_tokens_total{model}` through the existing metrics port.
- **Anthropic adapter:** map the SDK usage fields into `LLMResponse.usage` as `cache_read_tokens` and `cache_write_tokens`. Fix system-message placement if the test below shows it is wrong.
- **OpenRouter:** apply `cache_control` for all `anthropic/*` routes, using the same predicate.
- **Pattern:** keep the Decorator stack. Change only the predicate and the factory wrap at `adapter_factory.py:194-198`.

**Tests:**
- every id matched by `_ALLOWED_CLAUDE` (`model_refs.py:91`) is cacheable, and `claude-2.1` is not;
- the factory wraps a `claude-sonnet-5.5` adapter when only `LLM_ENABLE_PROMPT_CACHING` is set;
- a telemetry fixture with `prompt_tokens=1000, cached_tokens=800` reports a ratio of 0.8;
- an Anthropic usage fixture maps the cache fields;
- system placement: a recorded Anthropic SDK request has `system=` set and no `role: system` in `messages`.

**Gates:** update the existing tests (`tests/unit/test_caching_llm_adapter.py`, `test_anthropic_caching_adapter.py`, `fixes/test_claude_prompt_caching.py`); they encode the old markers. Update `CONFIGURATION.md`. **[eval-gated]**: record cache-read ratio and cost before and after.

### H3. Error-recovery ladder — M

**Problem.** A context overflow is classified CONTEXT_LENGTH. Because COMPRESS counts as retryable, `ResilientLLMAdapter` retries the **same payload** up to six times with backoff (`resilient_adapter.py:147,405`). The cascade then moves on to other models, which fail the same way, and finally raises `AllModelsTrippedError`. That error surfaces as "check your OpenRouter credits" (`executor/_turn.py:76`). `ErrorClassifier.should_compact` and `should_fallback_model` (`core/error_classifier.py:135,145`) have zero callers. (`TokenBudgetMonitor.should_compact` is an unrelated method with the same name.)

**Design.**
1. **Extend `ErrorCategory`** (`error_classifier.py:18`). Do not create a parallel enum. Add:
   - `PAYLOAD_TOO_LARGE`, `MULTIMODAL_UNSUPPORTED`, `RATE_LIMIT_UPSTREAM`, `QUOTA_EXHAUSTED`, `TOOL_SCHEMA_REJECTED`, `CONTENT_FILTERED`;
   - patterns for each in `_PATTERNS`;
   - `RecoveryAction` gains `STRIP_MEDIA` and `LARGER_CONTEXT_MODEL`.
2. **Functional core:** `plan_recovery(category, attempt: RecoveryAttempt) -> RecoveryAction | None`. It lives in a new `weebot/core/recovery_ladder.py` and is a pure, table-driven ladder:

   | Category | Ladder (in order; each rung tried at most once per call) |
   |---|---|
   | CONTEXT_LENGTH, PAYLOAD_TOO_LARGE | COMPRESS (target 0.5 of window) → COMPRESS aggressive (prune all old tool output, H9 pass 1) → LARGER_CONTEXT_MODEL (from catalog) → FAIL_FAST with a precise message |
   | MULTIMODAL_UNSUPPORTED | STRIP_MEDIA (replace images with "[image omitted: N]") → FALLBACK_MODEL to a vision-capable model |
   | RATE_LIMIT_UPSTREAM | if `Retry-After` ≤ 5 s → BACKOFF on the same model, else FALLBACK_MODEL. Never retry the same model more than once |
   | QUOTA_EXHAUSTED, AUTH | FAIL_FAST (key- or account-level; another model on the same key will not help) — message names the provider |
   | TOOL_SCHEMA_REJECTED | FALLBACK_MODEL |

   `RecoveryAttempt` is a frozen dataclass (`rungs_used: frozenset`, `model`, `window`).
3. **Imperative shell:**
   - `ResilientLLMAdapter._is_retryable_error` stops treating COMPRESS and FALLBACK categories as retryable. It raises a typed `RecoverableLLMError(category, retry_after)` from `weebot/domain/exceptions` (or wherever `LLMAuthenticationError` lives).
   - `CascadeExecutor._cascade_try_chat_unpooled` (`_cascade.py:357`) today swallows exceptions and returns None. It re-raises `RecoverableLLMError` for COMPRESS-family categories, so the executor can act, and still swallows the rest.
   - A new sibling `executor/_recovery.py` holds `RecoveryRunner`, which wraps the call in `next_turn` (`_turn.py:48`): catch → `plan_recovery` → perform the action (compress via `ContextCompressor.force_compress(ratio)`, strip media, pick a model from `config/model_refs` by window) → retry.
4. **Messages.** Replace the generic credits message with one string per category, from a dict.

**Why this shape.** The ladder is policy, so it is pure data plus a pure function; it can be tested exhaustively by category × attempt state. Execution stays in the executor, which owns the buffer. `_cascade.py` is at 799 lines, so it changes only to re-raise.

**Tests:**
- red first: a fake LLM that raises an overflow message on payloads over N tokens. Today: six identical retries. After: one compress, then success, and the second payload is smaller;
- a 429 with `Retry-After: 60` moves to the next model with zero same-model retries;
- a quota error fails fast with the provider named;
- ladder exhaustiveness: every `ErrorCategory` has a ladder entry. This is a dict-coverage test, not a change detector.

**Gates:** ADR-017 "Recovery ladder". Map card. `functions_over_150_lines` unchanged.

### H4. Delegation policy: depth, concurrency, timeout, role — M

**Problem:**
- No depth cap exists anywhere in the delegation code.
- `SubAgentFactory` children get **one shared admin tool collection** (`di/__init__.py:685`). `"admin"` is also hard-coded at `:544` and `di/_agent_tools.py:56`.
- `SubAgentSpec.role` and `.tools` (`domain/models/sub_agent.py`) never scope tools.
- `dispatch_parallel_tasks` (`tools/dispatch_agents.py:27`) is a **second spawn path**. It does not use the factory and has no per-task timeout.
- `mixture_of_agents`, `workflow_orchestrator` (both tool and core) and `hyper_agent` keep their own semaphores.

**Design:**
- **Value object** `DelegationPolicy` in `weebot/domain/models/delegation.py`, frozen pydantic:
  - `max_depth: int = 1` (range 1-3);
  - `max_concurrent_children: int = 4`;
  - `max_children_per_session: int = 20`;
  - `child_timeout_s: int = 300`;
  - `blocked_tools: frozenset[str]`, defaulting to `dispatch_parallel_tasks`, `swarm`, `debate`, `mixture_of_agents`, `workflow_orchestrator`, `hyper_agent`, `ask_human`, `schedule`, `install_tool`, plus `persistent_memory` write actions.
  - At depth < `max_depth`, the dispatch tools stay allowed, so that depth 2 is possible when configured.
  - Values come from settings: `WEEBOT_DELEGATION_MAX_DEPTH` and others.
- **Choke point:** `DelegationGuard`, a DI singleton in `application/services/delegation_guard.py`.
  - `async with guard.enter(parent_session, spec) as ticket:` checks depth, the per-session count and the global bulkhead.
  - Depth propagates through a `ContextVar[int]`. That is the same mechanism as `approval_scope` in `tool_approval.py`, and asyncio copies it into child tasks.
  - It is also stamped into the child `Session.context` (`parent_session_id`, `delegation_depth`) so it survives process hops.
  - The bulkhead semaphore is owned by the singleton, not a module global (WB-03).
- **Role scoping:** add a `subagent` role, and per-`SubAgentRole` mappings, to `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS` (`tool_registry.py:26-186`).
  - The child tool set is: (role tools ∩ `spec.tools` when given) − `blocked_tools`.
  - Remove the three `"admin"` literals in favour of `policy.child_role_for(spec.role)`.
- **One spawn path:** `DispatchAgentsTool._run_one` calls `SubAgentFactoryPort.spawn(spec)` instead of `flow_factory(session)`. `swarm` and `debate` route through it already. `mixture_of_agents` and `workflow_orchestrator` wrap their spawns in `guard.enter`.

**Patterns.** Policy value object, Context manager (RAII), Bulkhead, Specification (blocked-tool predicate).

**Tests:**
- a child at depth 1 calling `dispatch_parallel_tasks` gets a DENY result naming the policy;
- 10 concurrent spawns with `max_concurrent_children=4` never exceed 4 in flight;
- a child running longer than its timeout is cancelled and reported as a timeout;
- the child tool collection has no `bash` when the role is `researcher`;
- red first: today's child collection contains `install_tool`.

**Gates:** ADR-018 "Delegation policy". `SECURITY_MODEL.md`. Map cards for `delegation_guard` and `delegation`. Lower `string_di_keys` if the factory moves to a typed key.

### H5. Shadow-git workspace checkpoints and rollback — M

**Problem.** Weebot can undo a plan (in memory only; `plan_act_flow.py:578`, which has no callers), but not a file edit.
- The existing `CheckpointPort` (`application/ports/checkpoint_port.py`) stores **flow** checkpoints. It keeps the latest one per session, so the name is taken.
- `WorkspaceSnapshotPort` (`workspace_snapshot_port.py:85`) only detects changes: "never restore".
- `GuardedTool` does not wrap `file_editor`.

**Design:**
- **Port** `WorkspaceCheckpointPort(ABC)` in `application/ports/workspace_checkpoint_port.py`:
  ```python
  async def snapshot(self, *, session_id: str, turn_id: str, root: Path, reason: str) -> CheckpointRef | None
  async def list(self, session_id: str, limit: int = 50) -> list[CheckpointRef]
  async def diff(self, ref: CheckpointRef, *, paths: Sequence[str] = ()) -> str
  async def restore(self, ref: CheckpointRef, *, paths: Sequence[str] = ()) -> RestoreReport  # snapshots first
  async def gc(self, *, older_than_days: int) -> int
  ```
  `CheckpointRef` is a frozen domain model holding `id`, `session_id`, `turn_id`, `tree_sha`, `created_at`, `file_count` and `reason`.
- **Adapter** `ShadowGitCheckpointAdapter` in `infrastructure/checkpoints/shadow_git.py`:
  - It uses git plumbing with a **separate git dir**, `data/checkpoints/<sha1(root)>/`, and `--work-tree=<root>`: `add -A` respecting `.gitignore`, `write-tree`, `commit-tree`, and `update-ref refs/weebot/<session>/<n>`.
  - It never touches the user's own `.git`.
  - It runs fixed-argv subprocesses with `shell=False`, the `build_child_env` env (H1) and a timeout.
  - Caps from D4 apply. Over the caps it returns `None` and logs once per session.
- **Trigger** (Memento): in `ToolExecutor.execute_tool` (`_tool_executor.py:372`), before the first call per turn where `not reads_only(tool, args)`, call `checkpoints.snapshot(...)` once.
  - It uses the existing classifier, `tool_guards.reads_only` (`:382`). There is no new classification.
  - To keep `_tool_executor.py` small, the call is one line that delegates to a new sibling, `executor/_turn_checkpoint.py`.
- **Commands** (CQRS):
  - `RollbackWorkspaceCommand(session_id, steps_back | ref_id, paths)`;
  - `ListCheckpointsQuery`.
- **Surfaces:**
  - CLI `weebot rollback [N] [--session ID] [--path P] [--diff]` (click, `cli/commands/rollback.py`);
  - web `POST /api/sessions/{id}/rollback`;
  - a UI button in Phase 6 (H35).
- **Undo the undo:** `restore` takes a snapshot first.
- **Doctor:** checks that git is on PATH and reports disk usage.

**Tests:**
- integration with a temp dir: write a file through `file_editor`, roll back one step, and the content is restored;
- `.gitignore`d files are untouched;
- a rollback can itself be rolled back;
- a read-only turn creates no checkpoint;
- caps: a 21 k-file fixture is skipped with one warning;
- the user's own `.git/HEAD` is unchanged.

**Gates:** ADR-019 "Workspace checkpoints". Flag `WEEBOT_FILE_CHECKPOINTS` (default on, D4). Purge on session delete through `_session_stores()`. Map card. `ENTRY_POINTS.md`.

---

## 6. Phase 1: token economics and context

### H16. Schema-guided argument coercion and a live middleware chain — S

Built first in Phase 1, because H7, H20, H17 and H33 plug into it.

**Problem:**
- `tool_call_repair.py` repairs JSON syntax and fuzzy names, but it does not coerce types.
- `MiddlewareChain` (`application/middleware/chain.py`) is plumbed all the way to `ExecutorAgent`, but **no production code constructs one**.
- `HookRegistryPort` has no implementation.

**Design:**
- **Coercion.** A pure function in `application/services/tool_arg_coercion.py`:
  ```python
  def coerce_args(schema: Mapping, args: Mapping) -> tuple[dict, tuple[Coercion, ...]]
  ```
  - Rules:
    - `"42"`→int and `"4.2"`→float, only when the schema says integer or number;
    - `"true"`/`"false"`→bool;
    - a JSON-string array or object → parsed;
    - a scalar → `[scalar]` when the schema says array;
    - a `null` optional → dropped;
    - an enum value matched case-insensitively → canonical.
  - It never invents required fields. Coercions are logged and attached to `ToolResult.metadata["coerced"]`.
  - It is called in `ToolExecutor.execute_tool` after `repair_json_string` (`_tool_executor.py:390`) and before `tools.execute`.
- **Middleware.** Extend `Middleware` (`application/middleware/base.py`) with `before_tool_call(call) -> call | Deny` and `transform_tool_result(call, result) -> result`. Default no-ops keep existing subclasses valid.
  - `ToolMiddlewareChain` runs them as Chain of Responsibility.
  - DI builds a default chain from the built-ins: spillover (H7), late diagnostics (H20) and coercion telemetry. It is passed through `PlanActFlowConfig.middleware_chain` (`plan_act_flow_config.py:204`).
  - `HookRegistryPort` gets its first implementation, `MiddlewareHookRegistry`. It adapts named hook stages onto middleware, so one interception mechanism serves both.

**Tests:**
- `{"count": "3"}` against `{"type": "integer"}` arrives as 3;
- the string `"[1,2]"` for an array arrives as `[1, 2]`;
- a required field is never invented;
- a middleware that denies a call stops execution and returns a structured error;
- `transform_tool_result` sees the post-truncation result.

**Gates:** map cards for `tool_arg_coercion` and `middleware_chain`. Move `hook_context_types` out of `known_orphans` if it becomes used.

### H7. Tool-output spillover and a per-turn output budget — S

**Problem.** Truncation happens in `ToolCollection.execute` (`application/models/tool_collection.py:281-291`), not in `tools/base.py`, which is a re-export shim. Anything over `MAX_TOOL_OUTPUT_CHARS = 20_000` is discarded. `.error` is never truncated. There is no per-turn budget.

**Design:**
- **Port** `SpilloverStorePort` (`write(session_id, call_id, text) -> SpillRef`, `purge(session_id)`). The adapter writes to `data/spillover/<session>/<call>.txt`, reusing `FileStoragePort` where it fits.
- **`SpilloverMiddleware.transform_tool_result`** (H16). When the output is longer than the cap:
  1. write the full text;
  2. replace the output with a head (60%) and tail (40%) preview within the cap;
  3. append a footer: `[full output: <path>, N chars — read with file_editor view view_range=[a,b]]`.

  The same applies to `.error` above 8 K.
- **Per-turn budget.** `ToolBatchRunner` (`executor/_tool_batch.py:109`) sums output characters per turn. Above `WEEBOT_TURN_OUTPUT_BUDGET` (default 60 K), every later result in that turn spills, keeping only a 2 K preview.
- **D5 interaction (must hold).** Spill files are written by the system, not by `file_editor` on the session's behalf. They are therefore **not** in `_scope.note_written_file`. Reading them back taints the session exactly as the original output would have.
- **Purge:** register the store in `_session_stores()`.

**Tests:**
- a 50 K output yields a ≤ 20 K preview and a file holding all 50 K;
- reading the spill file with `file_editor` sets the taint flag (red if anyone later adds spill paths to the written-file exemption);
- the turn budget forces spillover on the fourth 25 K result;
- deleting the session removes the spill directory.

### H11. Loop guardrails v2 — S-M

**Problem.** `IterationGuard` (`executor/_iteration_guard.py:54`) catches only exact signature repeats (limit 4) and assistant repeats (limit 2).
- Its constants are duplicated at `_base.py:478-483`.
- `record_iteration` is counted per loop turn but compared with the 24 tool-call cap, so the name misleads.
- There is no cycle detection, no stubs for duplicate results, no empty-response policy, and no wall-clock wrap-up.

**Design:**
- **Strategy list of detectors.** Each is a small class with `observe(event: GuardEvent) -> GuardVerdict | None` and pure state, composed in `IterationGuard`:

  | Detector | Rule | Verdict |
  |---|---|---|
  | `CycleDetector` | the signature sequence has period p ∈ {2, 3, 4} repeated twice (A-B-A-B, A-B-C-A-B-C) | NUDGE once, then STOP |
  | `DuplicateResultStub` | sha256 of the result equals an earlier call's | replace the output with `"[identical to result of call #k]"` (saves tokens) |
  | `EmptyResponseBudget` | empty or whitespace replies; retry while the cumulative wasted cost is under `min(0.5 × step cost, $0.02)` | RETRY with a nudge, then STOP |
  | `RepetitionGuard` | assistant text 5-gram Jaccard ≥ 0.85 against the last 2 turns | NUDGE |
  | `WallClockWrapUp` | 80% of the step's wall-clock budget is used | inject a wrap-up note into the next **user** message (never the system prompt, to keep H10's prefix stable) |
- A single `GuardConfig` frozen dataclass holds every constant. `_base.py` takes it from DI; this removes the duplicate literals. Rename `record_iteration` to `record_loop_turn`.
- New code goes into `executor/_loop_detectors.py`, so `_iteration_guard.py` stays small.

**Tests:**
- an A-B-A-B sequence stops after one nudge;
- identical results become stubs;
- the empty-retry budget is honoured under a fake cost meter;
- the wrap-up note lands in a user-role message.

**[eval-gated]:** iterations per solved step must not rise and wasted-iteration share must fall.

### H9. Compression v2 — M

**Problem:**
- Double head/tail: `ContextCompressor._maybe_compress` (`executor/_context_compressor.py:81-121`) slices `keep = len//4` from each end, and `ConversationCompressor` then applies its own head-3 / tail-6 inside the middle.
- `context_window` defaults to 128 000 and DI does not pass a per-model value (`_base.py:77`).
- The summary is inserted as a mid-buffer `role: system` message. Anthropic does not allow that, and it breaks prefix assumptions.
- Counts are in messages, not tokens.
- `TokenBudgetMonitor` is dead code; it has no production instance.

**Design.** A **pipeline of compression passes**. Each pass is a Strategy object satisfying a Protocol:
```python
class CompressionPass(Protocol):
    name: str
    async def apply(self, msgs: Sequence[Message], budget: TokenBudget) -> Sequence[Message]
```
The passes, in order:
1. `PruneOldToolOutputs`: pure. Tool results older than the protected tail are replaced with `[tool output pruned: <tool>, N chars; spill: <path>]`, reusing the H7 spill path when one exists.
2. `DedupeResults`: pure.
3. `SummarizeMiddle(llm)`: the only I/O pass. It uses the cheap tier through the cascade, as today. It runs only if the passes before it did not reach the target.
4. `DeterministicFallback`: pure. On LLM failure or an empty summary, it keeps the head plus the token-budgeted tail plus a list of the dropped tool names.

The plan:
- **Budgeting** goes in a pure `select_tail(msgs, target_tokens, protect_last_n=4)`. It walks backwards and never splits a tool call from its result (reuse `executor/_tool_pairing.py`).
  - Target: `target_ratio = 0.20` of the window for the tail.
  - Trigger at 50% of the window, or 75% when the window is under 512 K.
- **Window** comes from the model catalog (`config/model_refs` or catalog lookup). `ContextCompressor` is built in DI with `window_for(model)`, not a constant.
- **Summary placement:** the summary goes in a `role: user` message, `"[Context summary — N turns compressed]\n..."`, directly after the head. The plan summary and todo list are re-injected in the same message.
- **Remove the double slicing.** `ConversationCompressor` becomes the `SummarizeMiddle` pass and receives the exact middle.
- **Delete `TokenBudgetMonitor`**, or wire it as the trigger source. The plan picks delete, because the pipeline owns the trigger.
- **`force_compress(ratio)`** is exposed for H3.

**Paradigm.** A functional pipeline in which only one pass does I/O; passes are order-as-data. It mirrors Hermes's "no-LLM prune first" while staying testable without mocks.

**Tests:**
- a tool-heavy fixture (40 tool results of 5 K each) compresses below target without any LLM call;
- a tool call is never separated from its result;
- the summary is user-role;
- LLM failure produces the deterministic fallback;
- the window is taken from the model (a 1 M-window model does not compress at 100 K).

**Gates:** **[eval-gated]**. Task success must not drop by more than 1 pp, and tokens per task must fall.

### H24a. Freeze the memory snapshot per session (pulled forward from H24) — S

**Problem.** `PersistentMemoryTool.load_snapshot` (`tools/persistent_memory.py:261`) is re-read from disk and appended to the **system** prompt at every step (`executor/_step_setup.py:103-116`). Every memory write by any session therefore changes the prefix. In addition, `USER.md` content appears both in the snapshot and as `## User Profile` (`_step_setup.py:96-97`).

**Design:**
- `MemorySnapshotCache`, a DI singleton with a bounded LRU keyed by session id, evicted through `_session_stores()`. It loads once on first use per session.
- A write through `persistent_memory` goes to disk immediately. The tool result says "saved; in context from next session". The model sees its own write in the tool result, so nothing is lost inside the session.
- Drop the duplicate user-profile block, keeping one source.
- Flag `WEEBOT_MEMORY_SNAPSHOT_FREEZE`, default on.

**Tests:**
- two steps in one session render byte-identical snapshot text even after a write;
- a new session sees the write;
- the profile appears once.

### H10. Prompt-prefix invariant and prompt-surface lock — M

**Problem.** `build_executor_prompt` (`executor/_prompt_builder.py:75`) places per-step BM25 skill text, behavioural rules, the user profile, the output root and the memory snapshot inside the system prompt. `_turn._assemble_messages` (`_turn.py:108`) appends `_tool_note`, which varies per step. `ToolCollection.to_params()` (`tool_collection.py:176`) returns the step-scoped tools in whatever order they arrive. No test checks prefix stability.

**Design.**
- **Prompt layout as a Builder** that produces a frozen value, `PromptLayout`, in `application/models/prompt_layout.py`:
  ```python
  @dataclass(frozen=True, slots=True)
  class PromptLayout:
      system_static: str        # boot block + base prompt + harness + personality  (stable per session)
      system_session: str       # frozen memory snapshot (H24a) + user profile       (stable per session)
      step_context: str         # BM25 skills, behavioural rules, output root, tool note, constraints
      prefix_sha: str           # sha256(system_static + system_session + canonical tools json)
  ```
- **Wire order**, following the Anthropic cache order (tools → system → messages):
  1. `tools[]`, sorted by name, with canonical JSON (`sort_keys`, the same normaliser as `normalize_tool_call_arguments`);
  2. `system = system_static + system_session`;
  3. a cache breakpoint on the last system block;
  4. `step_context` as the first **user** message of the step;
  5. a second breakpoint on the last user message before the newest assistant turn (`AnthropicCachingAdapter.prepare_messages`, `anthropic_caching_adapter.py:115`, already places up to 3).
- **Tool scope (D3).** A setting `WEEBOT_TOOL_SCOPE_GRANULARITY = step | plan`. With `plan`, the planner's step list is scoped once (the union of the step scopes) and pinned for the run. In both modes the "More tools exist" note moves into `step_context`.
- **Port** `PromptPrefixStore` (`application/ports/prompt_prefix_port.py`). It records `prefix_sha` per session per step and emits the metric `prompt_prefix_changes_total{reason}`. The in-memory adapter is bounded (an LRU in DI).
- **Fitness test:** run the executor with fake LLM and tools for 3 iterations in one step, and again for 2 steps under `plan` granularity, then assert a single `prefix_sha`. This is a behaviour contract, not a change detector.
- **Prompt-surface lock** (Hermes `prompt-surface-diff.yml` analogue):
  - `scripts/prompt_surface.py` renders `system_static` and the canonical tool schemas for each role from fixture inputs.
  - It writes `tasks/quality/prompt_surface.lock` (sha per role, plus text under `tasks/quality/prompt_surface/`).
  - `make check` fails when the render differs from the lock and prints the unified diff. The author re-locks with `--update`.
  - It is the same kind of deliberate, reviewed gate as `ceilings.toml`, so prompt and tool-schema changes are visible in every PR.
- **Duplicate builder at `_base.py:586-601`** (`_summarize_on_budget_cap`): route it through `PromptLayout` too.

**Tests:** the fitness test above. Lock round-trip. Cache breakpoints placed at the two boundaries in a recorded request.

**Gates:** ADR-016 "Prompt prefix invariant", covering H2, H10 and H24a. **[eval-gated]**, decides D3: report cache-read ratio and cost per task under `step` and `plan`. Target cache-read ratio ≥ 60% on Claude runs (M1).

### H15. Session search v2: trigram index, modes, real FTS syntax — S

**Problem:**
- `event_fts` (`infrastructure/persistence/fts5_search.py:40-47`) is `porter unicode61` only.
- It has no event id or timestamp columns.
- `_sanitize_fts_query` (`:15-33`) quotes every token, which neutralises the FTS operators the tool text advertises.
- The index watermark `_fts5_indexed` lives in memory, so every restart re-indexes.
- `search_history` reaches past ports into `fts5_search` and `connection_pool`, through two import exemptions.

**Design:**
- **Schema:** rebuild `event_fts` with `event_id UNINDEXED, ts UNINDEXED`, and add `event_fts_trigram USING fts5(..., tokenize='trigram')`.
  - Trigram needs SQLite ≥ 3.34; probe `sqlite_version()` and degrade with a log line.
  - Tool-result rows are excluded from the trigram table, for size.
  - Add a `fts_watermark(session_id PRIMARY KEY, last_event_idx)` table.
  - Both tables are derived data, so the migration is drop, recreate and re-index lazily. There is no data migration.
  - Postgres: an alembic revision adds a `pg_trgm` GIN index on the events summary. Until it lands, the Postgres path keeps today's behaviour.
- **Port** `SessionSearchPort` with `discover(query, limit)` (sessions ranked by bm25), `scroll(session_id, around_event_id, window)` and `read(event_id)`.
  - It is implemented in `infrastructure/persistence/session_search_sqlite.py`.
  - The query planner is pure: tokens shorter than 3 characters or containing non-Latin script go to trigram; otherwise to unicode61; the results are unioned.
  - `syntax="fts"` passes operators through after validation, and `syntax="text"` quotes them, as today.
- **Tool:** `search_history` gets the port injected and gains `mode`. **Delete both import exemptions** and lower `import_exemptions` by 2.

**Tests:**
- the substring `"onfig"` finds `config`;
- a Greek or CJK query finds a hit;
- `a OR b` works with `syntax="fts"`;
- restarting does not re-index already-indexed sessions;
- `.importlinter` passes without the exemptions.

### Q1. Per-unit complexity ratchet (matrix row 42) — S

Add ceilings `functions_over_cc_20` and `functions_over_nesting_6`, measured by a new `scripts/lint_complexity.py` built on the stdlib `ast` (no new dependency), at today's values. Ratchet down as Phase 0-2 refactors land. This is Hermes's per-unit rule with Weebot's exact-equality mechanism.

---

## 7. Phase 2: tool depth

### H6. Edit pipeline: fuzzy patch, stale-write guard, syntax lint — M

**Problem.** `StrReplaceEditorTool` (`tools/file_editor.py:17`) offers `view`, `create`, `str_replace`, `insert` and `write_large`.
- `str_replace` replaces the first occurrence, by exact match only.
- The tool does not track reads, so it cannot refuse a write over a file that changed since the model last saw it.
- Nothing checks syntax after a write.

**Design:**
- **Match chain** (Chain of Responsibility over pure strategies) in `application/services/patch_matching.py`:
  ```python
  class MatchStrategy(Protocol):
      name: str
      def find(self, haystack: str, needle: str) -> list[Span]
  STRATEGIES = (Exact(), LineTrimmed(), WhitespaceNormalized(), IndentationFlexible(),
                EscapeNormalized(), UnicodeNormalized(), BlockAnchor(min_ratio=0.8))
  ```
  - `UnicodeNormalized` applies NFKC and maps smart quotes and dashes.
  - `BlockAnchor` matches the first and last line exactly, with a middle `difflib` ratio of at least 0.8.
  - `apply_patch(text, old, new) -> PatchOutcome`: the first strategy with **exactly one** span wins. Several spans give an error listing their line numbers. No span gives an error with the closest candidate snippet.
  - The outcome records which strategy matched, and the tool result reports it (useful telemetry).
- **Commands.** `str_replace` falls back through the chain; `"exact": true` restores strict behaviour. A new `patch` command takes several `{old, new}` hunks and applies them atomically: all hunks or none, with the existing `.tmp` + `replace`.
- **File-state registry** `FileStateRegistry`, a session-scoped DI singleton with an LRU and purge hook, in `application/services/file_state.py`:
  - `view` records `(path → mtime_ns, size, sha256)`.
  - A write to a path whose current stamp differs from the recorded one, or that this session never viewed, is refused with `"file changed since you last viewed it; view it again"`.
  - `create` of a new file is exempt.
  - The tool receives the registry through DI (`di/_agent_tools.py`), keeping `tools-no-infra` clean.
- **Syntax lint** `SyntaxCheckPort`. The in-process adapter covers `.py` (`ast.parse`), `.json`, `.toml` (`tomllib`), `.yaml` (when PyYAML is installed) and `.ipynb` (JSON). Errors are appended as warnings to the result; the write stands. Language servers come in H20.

**Tests:**
- a table-driven test per strategy (needle variants → expected span);
- ambiguity error;
- atomic multi-hunk patch: one bad hunk leaves the file untouched;
- an external modification between view and write is refused;
- a Python syntax error after a write is reported.

**[eval-gated]:** the edit-failure-loop rate on coding suites must reach at most 0.5× baseline (M2).

### H18. Approval upgrades: floors, scopes, guardian, breaker, unattended — M

**Problem:**
- `AutoApproval` (`application/services/tool_approval.py:115`) **grants every ASK** in AUTO mode (`flows/states/_step_run.py:84-89`). Nothing exists that AUTO cannot bypass.
- Grants (`core/approval.py:157`) are single use and expire after 10 minutes, with no scopes.
- No denial circuit breaker exists.
- Gateways have no notion of an unattended context; cron already uses `DenyApproval`.

**Design.** The existing `GuardChain` (`tool_guards.py:410`) is the Chain of Responsibility. Each upgrade is one link or one strategy.
- **(a) Floors.** A Specification list in `core/approval_floors.py`, pure:
  ```python
  @dataclass(frozen=True) class Floor: id: str; matches: Callable[[NormalizedCommand], bool]; action: Literal["deny", "human"]
  ```
  - Built-ins:
    - recursive delete of `/`, `~`, `%USERPROFILE%` or a drive root;
    - writes to credential stores (`~/.ssh`, `~/.aws`, the `.env` of the Weebot root);
    - `git push --force` to the default branch;
    - disk format and partition commands;
    - registry hive deletes;
    - `curl|sh` / `iwr|iex`;
    - disabling Defender or the firewall.
  - User deny globs come from the setting `WEEBOT_APPROVAL_DENY_GLOBS`.
  - Matching runs against **deobfuscated variants** from `CommandSecurityAnalyzer` normalisation (`tools/bash_security.py:304`).
  - A `FloorGuard` link runs **first** in `default_guard_chain`. A `human` floor maps to a new `GuardAction.HUMAN`, which `AutoApproval` cannot grant: it pauses the flow even in AUTO, or denies when unattended.
- **(b) Scopes.** `ApprovalGrant.scope: once | session | always`.
  - `session` and `always` key on a normalised **command pattern** (argv[0] + subcommand + flags without values), not the full fingerprint.
  - `always` is stored per profile in `~/.weebot/approvals.json`, with an atomic write.
  - Scopes never apply to DANGEROUS tier, floors, or tainted sessions; D5 stays strict.
- **(c) Guardian.** A `GuardianPort` with an `LLMGuardianAdapter`:
  - It decides `approve | deny | escalate`, as structured output validated by pydantic.
  - It only ever sees one SUSPICIOUS-tier command, plus the step description. It sees no tool outputs, and therefore no untrusted text.
  - It uses the cheap tier through the cascade, and never runs in tainted sessions.
  - The default is `escalate` on any parse failure.
  - Flag `WEEBOT_APPROVAL_GUARDIAN`, default **off**: real risk, opt-in.
- **(d) Denial breaker.** A per-session counter in a DI singleton. After 3 denials in a step, or 6 in a session, the step stops with `StepStatus.BLOCKED` and asks the human.
- **(e) Unattended.** `ApprovalChannel.UNATTENDED`, set by `approval_scope` for gateway runs that have no human approver bound. It maps to `DenyApproval`, matching cron.

**Tests:**
- AUTO mode plus `rm -rf ~` pauses (red today: auto-granted);
- a deny glob matches a base64- or quote-obfuscated variant;
- a session scope auto-allows the second `npm test` but not `npm publish`;
- the guardian is never called in a tainted session or for DANGEROUS;
- the breaker trips at 3;
- an unattended gateway run denies an ASK.

**Gates:** ADR-021. `SECURITY_MODEL.md` (approval section). `EVENT_CATALOG.md` for `ApprovalScopedGrant` and `GuardianVerdict`.

### H17. Persistent Python kernel with tool RPC — L

**Problem.** `PythonExecuteTool` (`tools/python_tool.py:32`) runs one-shot code through `SandboxPort.execute_python`, and builds its own sandbox when none is injected (`:101-107`). No mechanism lets code call tools.

**Design.**
- **Ports:**
  - `KernelPort(ABC)` with `start(session_id) -> KernelHandle`, `exec(handle, code, timeout) -> KernelResult` and `stop(handle)`;
  - `ToolRpcPort` is the host side.
- **Actors.** `KernelManager` is a DI singleton holding an LRU of at most 4 live kernels. Each kernel is an actor: one asyncio task that owns the process, plus a mailbox (`asyncio.Queue`) that serialises `exec` calls. Eviction on LRU or on session end goes through `_session_stores()`.
- **Kernel process.** A small REPL server, `weebot/sandbox_runtime/kernel_server.py`, is copied into the sandbox. It keeps a persistent `globals()`, captures stdout and stderr, and returns `{"stdout", "error", "duration"}`. Only stdout (capped, spilled per H7) goes back to the model.
- **RPC transport by backend:**
  - Docker: a Unix socket in a per-session host dir bind-mounted into the container. `--network none` stays intact (dependency note in the source study).
  - native_windows and wsl2: loopback TCP on an ephemeral port bound to 127.0.0.1, with a per-session 32-byte token in the first frame.
  - Modal: not supported in v1; fall back to one-shot execution.
- **Stub module** `weebot_tools` inside the kernel: `web_search(q)`, `file_view(path)`, `file_write(path, text)`, `bash(cmd)`, …. JSON-RPC 2.0 frames go to `ToolRpcServer` on the host.
  - That server dispatches **through `ToolExecutor.execute_tool`**, so bash_guard, floors (H18), egress, D5 taint, approvals, coercion and the ledger all apply unchanged.
  - The RPC allowlist is configurable and defaults to read tools, `file_*` and `bash`. Dispatch tools are never allowed.
- **Trust.** If any RPC call during an `exec` returned EXTERNAL output, the kernel result is marked EXTERNAL, which taints the session. Otherwise it is LOCAL, as `python_execute` is today.
- **Budget.** Each RPC call counts against the step's tool-call cap (24). The `exec` call itself refunds its loop iteration (`StepBudget.refund`, `step_budget.py`). The net effect is that N tool calls cost one model turn.
- **Env** is built by `build_child_env` (H1).
- **Tool surface.** `python_execute` gains `persistent: bool` (default true when the kernel is available) and `reset: bool`.

**Steps, as PRs:**
1. ports, `KernelManager`, native backend, no RPC;
2. RPC server, stub and the guard path;
3. Docker socket transport;
4. WSL2 transport;
5. telemetry and eval.

**Tests:**
- state persists across two `exec` calls;
- a stub `bash("rm -rf ~")` is blocked by the floor;
- a stub `web_search` marks the result EXTERNAL and taints the session;
- a wrong token is rejected;
- the fifth kernel evicts the least recently used;
- in Docker, `socket.create_connection(("1.1.1.1", 80))` fails while RPC works.

**Gates:** ADR-020. **[eval-gated]**: a data-wrangling suite must show at least 30% fewer LLM turns at equal pass rate (M2).

### H20. LSP delta diagnostics (opt-in) — M

**Design:**
- `LspPort(ABC)`: `open(path, text)`, `change(path, text)`, `diagnostics(path, timeout) -> list[Diagnostic]`.
- `Diagnostic` is a frozen domain model: path, range, severity, code, message, source.
- **Adapter:** a minimal LSP client over stdio (JSON-RPC framing), in `infrastructure/lsp/`. Using `pygls` as the client would be a new dependency; decide at PR time against the ~300-line hand-rolled client.
- **Actors.** `LspManager` keeps one server process per (workspace, language), LRU 3, evicted on session end.
- **Servers:** `pyright-langserver`, `typescript-language-server` and `ruff server`, if on PATH. Doctor lists them.
- **Delta:** `new = after − before`, keyed on (range start line ± 2, code, message).
  - `before` is captured at `view` time from the H6 registry, or lazily before the write.
  - Only new diagnostics are reported.
- **Non-blocking:** wait up to 1.5 s. Late diagnostics are queued and attached to the **next** tool result by the `transform_tool_result` middleware (H16).
- **Trust-gated:** servers start only for workspaces under the configured workspace root or listed in `WEEBOT_LSP_TRUSTED_ROOTS`, because language servers execute project config.
- Flag `WEEBOT_LSP_DIAGNOSTICS`, default **off**: opt-in (spawns processes).

**Tests:**
- with a fake LSP server, an edit introducing an undefined name reports exactly one new diagnostic, and existing ones are suppressed;
- a late result attaches to the next call;
- an untrusted root starts no server.

### H20b. Verification evidence on the effect ledger — S

**Problem.** `EffectLedger` (`application/services/effect_ledger.py:36`) records only outbound calls. `StepEvidenceAuditor` (`step_evidence_auditor.py:45`) parses test output per step. `VerifyingState` (`flows/states/verifying.py:41`) does not read the ledger. Nothing proves that tests ran **after** the last edit.

**Design.** Reuse the ledger. Do not build a new one.
- A pure classifier, `classify_verification_command(argv) -> VerificationKind | None`, covering pytest, `npm test`/`run build`, `make check`/`test`, `ruff`, `tsc`, `cargo test`, `go test`, `dotnet test` and `mvn test`. A table, extensible through settings.
- `ToolExecutor` records the effect `verification_ran` (kind, exit code, ts) for shell or python calls that classify as verification. It records `code_written` (path, ts) for `file_editor` writes of source extensions.
- `VerifyingState._gate_evidence` (new, beside `_gate_sweep`, `:379`): when the last `code_written` is later than the last passing `verification_ran`, stamp `ctx.extra["verification_status"] = "stale_after_edit"` and emit a `VerificationEvidenceStale` event.
  - Interactive mode: one re-run nudge back to executing, bounded to one.
  - AUTO mode: stamp it and let the product gate report it.
- The completed-session summary lists the commands that actually ran.

**Tests:**
- edit → test → done is verified;
- test → edit → done is stale;
- a failing test is never counted as evidence.

### H21. Conversation undo, retry, branch — M

**Problem:**
- Session events are one JSON blob (`sessions.events_json`). `Session.replace_events` exists (`session.py:257`).
- Plan undo is in memory and has no callers.
- The append-only `EventStorePort` journal exists separately.

**Design.**
- `SessionTimeline`, a pure service over `Session.events`:
  - `turn_boundaries(events) -> list[Boundary]` (user-message events);
  - `cut_at(boundary) -> (kept, dropped)`.
- **Commands** (CQRS):

  | Command | Behaviour |
  |---|---|
  | `RewindSessionCommand(session_id, turns=1, files=True)` | `replace_events(kept)`; append `SessionRewound{dropped_ids, boundary}` to the **journal**, which is never rewritten; if `files`, `RollbackWorkspaceCommand` to the H5 checkpoint whose `turn_id` matches the boundary |
  | `RetryLastTurnCommand(session_id)` | rewind 1 turn, then resubmit the dropped user text through the normal run path (`TaskRunnerPort`) |
  | `BranchSessionCommand(session_id, at_event_id)` | copy events up to the cut into a new session (`parent_session_id`, `branched_from_event`); the files are not copied (documented) |
- **Guard:** refuse while a run is active, checked through the existing cancel marker and active-session query.
- **Plan-act sessions:** v1 supports rewinds at plan-run boundaries only, restoring the `FlowCheckpoint` taken at that boundary. Mid-run rewind is out of scope.
- **Surfaces:**
  - web `POST /api/sessions/{id}/rewind|retry|branch`;
  - gateway `/undo /retry` (H29);
  - CLI `weebot flow rewind|retry|branch`.

**Tests:**
- rewinding 1 turn removes exactly that turn's events and restores files;
- the journal still holds the dropped events;
- a branch shares no mutable state with the original;
- rewinding during a run is refused.

---

## 8. Phase 3: MCP, secrets, egress

### H12. MCP client depth — M-L

**Problem:**
- `MCPSamplingHandler` (`application/services/mcp_sampling_handler.py:85`) is dead code: no `sampling_callback` is passed to any `ClientSession`.
- There is no elicitation.
- `MCPAuthConfig` (`domain/models/mcp.py:35`) declares OAuth and mTLS, but neither is implemented.
- The `sse` transport ignores headers and auth.
- The manager works on raw dicts, while the typed `MCPServerConfig` is used only by the bridge.
- There is no per-server trust field.

**Design, in steps:**
1. **Typed config, one source of truth.** The manager parses `config/mcp_servers.json` entries into `MCPServerConfig`, adding the fields:
   - `trust: Literal["trusted", "untrusted"] = "untrusted"`;
   - `env_passthrough` (H1);
   - `sampling: MCPSamplingPolicy` (exists, `mcp.py:67`);
   - `auth`.

   Raw-dict access is deleted.
2. **Sampling:**
   - Pass `sampling_callback=MCPSamplingHandler(...)` per session.
   - Caps come from the policy: rpm, max tokens, allowed models.
   - Sampling calls go through `CascadeExecutor` at the BUDGET tier and count on the parent `SessionCostMeter`.
   - They are refused in tainted sessions unless the policy says otherwise.
3. **Elicitation.** `elicitation_callback` → an `ElicitationBroker` that routes the request to `ask_human` / `FlowPauseApproval`. An unattended context declines (H18e). The schema is validated before the request is shown.
4. **OAuth 2.1** (DCR + PKCE):
   - Use the MCP SDK's client OAuth provider (`mcp.client.auth`).
   - Implement its token storage over a new **`SecretStorePort`**, which is writable (unlike `SecretAccessor`): keyring adapter, with an encrypted-file fallback under `~/.weebot/secrets/`.
   - CLI `weebot mcp login <server>` opens the browser and uses a loopback redirect.
   - Fix `sse` so that it applies headers and auth.
5. **Trust.** For `untrusted` servers, every tool is non-read for D5 and approvals regardless of the verb heuristic (`tool_guards.py:315`), and the output is EXTERNAL. `trusted` keeps today's heuristic.
6. **Lazy schema cache.** `list_tools` results are cached on disk, keyed on the sha256 of the server config. The server connects on first tool use, not at boot.
7. **OSV preflight** for `npx` and `uvx` packages. Resolve `pkg@version` from args, then query through `VulnerabilityFeedPort` (shared with H25). A critical finding blocks the spawn unless acked.

**Tests:**
- a fake MCP server requesting sampling gets a reply within caps, and the cost lands on the parent meter;
- elicitation in AUTO/unattended is declined;
- the OAuth flow runs against a local fake authorisation server (integration);
- an untrusted server's `read_x` tool still asks in a tainted session;
- the cache skips `list_tools` on the second boot;
- an OSV-flagged package is blocked.

**Gates:** ADR-022 (secrets part). `SECURITY_MODEL.md` MCP section. Map cards.

### H12b. OpenAI-compatible API — M

**Design:**
- A router, `interfaces/web/routers/openai_compat.py`, mounted at `/v1` when `WEEBOT_OPENAI_API_ENABLED` is set (D7).
- **Auth** reuses `auth.py`: `Authorization: Bearer`, in store or legacy mode. Rate tier is `expensive`. Session ownership uses the existing `verify_session_ownership`.
- `GET /v1/models`: Weebot's run modes as models (`weebot-chat`, `weebot-plan`, `weebot-auto`) plus personas (`weebot-persona-<name>`).
- `POST /v1/chat/completions`:
  - The messages map to a session. Resume uses the `X-Weebot-Session` header or the `user` field; otherwise a new session is created.
  - The run starts through `TaskRunnerPort`, exactly as `sessions.py:336` does.
  - `stream=true` is translated by an **Adapter**: a pure `to_openai_chunk(event) -> dict | None` that turns `EventBus` events into `chat.completion.chunk` deltas (message tokens, tool-step annotations in `delta.content` behind a setting).
  - Non-stream mode waits for `DoneEvent`.
  - Client-supplied `tools` return 400 in v1, documented.
  - `usage` comes from the session cost meter.
- **Runs API:**
  - `POST /v1/runs` (create);
  - `GET /v1/runs/{id}/events` (SSE, the same visibility filter as `routers/sse.py:33`);
  - `POST /v1/runs/{id}/approval` (`{call_id, decision, scope}` → `ApprovalManager.grant`);
  - `POST /v1/runs/{id}/stop` (the existing cancel path).
- **Idempotency.** The `Idempotency-Key` header goes into a new table `api_idempotency(key, principal, run_id, created_at)` with a TTL of 24 h, in both SQLite and alembic. A repeated key returns the same run.

**Tests:**
- the official `openai` Python client, pointed at the TestClient, streams a reply;
- a second request with the same Idempotency-Key does not create a second run;
- another principal's session id returns 404;
- with the flag off, the router is not mounted.

### H19. Secret sources and a model-blind credential vault — M

**Design:**
- **`SecretSourcePort`** (`resolve(ref) -> ResolvedSecret | None`, `scheme: str`), with adapters:
  - `EnvSource`;
  - `OnePasswordSource` (`op read op://…`);
  - `BitwardenSource` (`bws secret get …`).

  The CLI adapters run with a 5 s timeout and `build_child_env`, and are read-only.
- A **Composite** `ResolvingSource` is installed at the composition root through `SecretAccessor.set_source(...)`. This keeps `config/` free of infrastructure imports.
  - Values shaped like `op://...` or `bws://...` in `.env` are resolved **once at startup** and cached in memory.
  - Provenance (the source name only) is logged and shown in `weebot doctor`.
  - A failure fails closed for that key: the key is absent, with a doctor error.
- **Vault** `CredentialVaultPort`:
  - `list_handles(origin) -> list[CredentialHandle]`;
  - `fill(handle, page, selector_user, selector_pass)`.
  - A handle is an opaque id plus its origin, and it is bound to that origin: filling on another origin is refused (anti-phishing).
- **Bypass to fix first.** `advanced_browser` (`tools/advanced_browser.py:238-245`) calls Playwright `page.fill` directly with the model's value and skips `BrowserPort`. Route its `fill` through one function. When `value` matches `vault:<id>`, that function resolves through the vault adapter. The real value never enters events, logs or the transcript; the existing redaction is the backstop.

**Tests:**
- an `op://` ref resolves through a fake `op` binary on PATH;
- a resolution failure leaves the key absent and doctor reports it;
- filling a `vault:` handle on the wrong origin is refused;
- a session transcript contains no secret value (grep the session JSON).

### H23. Egress control in the Docker sandbox — L

**Step 1 (D8): CONNECT allowlist proxy.**
- The sandbox container moves from `--network none` to an **internal** docker network, but only when a call clears network use (`network_cleared_for_call`, `sandbox_port.py:27`).
- The only reachable host on that network is a proxy sidecar: an Ambassador pattern, with the image pinned by digest.
- The sidecar allows CONNECT only to hosts that `EgressGuard` approves (`core/egress_guard.py:523`). The allowlist is pushed per call.
- Native and WSL2 keep the documented "best effort" status.

**Step 2: token swap (optional, needs D8).**
- The sandbox env holds opaque placeholders (`WEEBOT_TOKEN_OPENROUTER=wbt_…`).
- The proxy terminates TLS with a per-session CA, which is mounted into the container trust store, and swaps the placeholders for the real keys, read from H19, on allowlisted hosts only.
- Start from the same open-source proxy approach as Hermes iron-proxy, pinned by SHA.

**Tests:**
- curl to a non-allowlisted host from inside the sandbox fails;
- an allowlisted host succeeds;
- (step 2) the request reaching a fake upstream carries the real key, and the sandbox `env` never does.

**Gates:** ADR-022. `SECURITY_MODEL.md` sandbox section.

### H13. Credential pools — M (**parked by D-F; build when a consumer exists**)

**Design, kept ready:**
- `CredentialPool` per provider, holding N keys from `KEY`, `KEY_2..n`, or a comma list through `SecretAccessor`.
- Strategy objects: `FillFirst`, `RoundRobin`, `LeastUsed`.
- A 429 cooldown keyed by (key fingerprint, model).
- The breaker key in `CascadeExecutor` becomes (model, key fingerprint).
- Fold in this hygiene fix: the adapter cache key (`adapter_factory.py:160`) holds the plaintext key. Use a sha256 prefix instead. **Do that fix now, inside H2's PR**; it is a one-line change.

---

## 9. Phase 4: gateways and automation

### H28. Gateway adapter contract and registry — M + S per adapter

**Problem:**
- `GatewayAdapter(ABC)` (`interfaces/gateways/base.py:~97`) has only `start`, `stop` and `send_response`.
- Only Telegram uses `GatewayCommandDispatcher`, and its sentinel strings (`OK_SET_MODEL:x`) are interpreted ad hoc (`telegram.py:301-318`). Four default commands are never acted on.
- Discord, Slack and WhatsApp are built per request inside the webhook routers.

**Design** (Template Method plus a capabilities value object):
```python
@dataclass(frozen=True) class ChannelCapabilities: edit: bool; typing: bool; threads: bool; max_len: int; media: frozenset[str]; voice_in: bool
class GatewayAdapter(ABC):
    capabilities: ClassVar[ChannelCapabilities]
    # transport primitives (subclass implements)
    @abstractmethod async def send(self, chat: ChatRef, msg: OutMessage) -> SentRef
    async def edit(self, ref: SentRef, msg: OutMessage) -> None: raise NotImplementedError   # only if capabilities.edit
    async def typing(self, chat: ChatRef) -> None: ...
    # template method (base owns the turn): auth → command dispatch → busy policy → run → render → deliver
    async def handle(self, inbound: GatewayMessage) -> None: ...
```
- **Typed command results** replace the sentinels: `NewSession | StopRun | SetModel(model) | Reply(text) | ResumeSession(id) | …`, a closed union of frozen dataclasses dispatched by a dict (`type → handler`) in the base.
- **Registry:** `GatewayRegistry` built from a static map of the six built-ins, plus `importlib.metadata.entry_points(group="weebot.gateways")`. Lifespan start comes from configuration, not from per-request construction. This is the minimal registry D1 allows without the full H33.
- **Migration order:**
  1. Telegram, the reference adapter;
  2. Discord and Slack, which keep webhook ingress and use the base for egress;
  3. WhatsApp, Signal and Email.

  New adapters (Matrix, Teams, Google Chat, generic HMAC webhook, ntfy, SMS) are added only when a user asks.

**Tests:**
- a contract test suite parametrised over all registered adapters, using fakes: auth gate, every command result handled, `max_len` splitting;
- no adapter imports another;
- an entry-point adapter is discovered.

### H29. Gateway runtime — L

All of this lives in the base from H28, so every adapter gets it.
- **Streaming:** `StreamingReplyRenderer` subscribes to the run's events.
  - When `capabilities.edit` holds, it edits one message, throttled to 1.2 s or 200 new characters, and splits at `max_len`.
  - Without edit support it sends once at the end.
  - It shows typing while tools run.
- **Busy modes:** a per-chat State machine (`Idle → Running → Idle`), held in a DI singleton keyed by chat with an LRU. Input while running follows the per-chat setting:
  - `interrupt`: cancel and start the new input;
  - `queue`: FIFO with a max depth of 3;
  - `steer`: `SteeringPort`, which already exists for sessions.
- **Delivery outbox** (Outbox pattern): a table `gateway_outbox(id, adapter, chat, payload_json, idempotency_key, status, attempts, next_at)` in `gateway_sessions.db`, plus alembic.
  - Every send is written first, then delivered by a drain worker.
  - Delivery is at least once, and idempotency keys stop duplicates on platforms that support them.
  - The worker drains on boot.
  - Cron delivery (H30) uses the same outbox.
- **Voice memos:** inbound voice goes through `SpeechPort` (Whisper) to text. Optional TTS reply when the chat setting `voice_reply` is on.
- **Home channel:** `/sethome` stores (adapter, chat) per profile in the gateway session store, as the target for `home` deliveries.
- **Bot-loop guard:**
  - drop messages from bots and from self;
  - at most 1 reply per 2 s per chat;
  - stop replying after 20 replies in 5 minutes without a human message.
- **Per-channel overrides:** model, persona and system note on the gateway session record, set by admin commands.
- **One slash set,** with tiers from H8: `/new /stop /model /status /approve /deny /undo /retry /compress /usage /whoami /sethome /btw`.
  - `/approve` and `/deny` resolve pending `FlowPauseApproval` items for that chat's session.
  - `/undo` and `/retry` map to H21 commands, `/btw` to H27, and `/compress` to `force_compress`.

**Tests:**
- with a fake adapter, streaming makes at most N edits for a 2 K reply;
- busy `queue` mode processes in order;
- an outbox row survives a simulated crash and is delivered once on restart;
- a bot-loop transcript stops after the cap;
- `/approve` resumes a paused flow.

**Gates:** ADR-023. `EVENT_CATALOG.md` (`GatewayDelivery*`). Map processes card "gateway turn".

### H8. Gateway auth: pairing and command tiers — M

**Problem.** The docstring at `core/gateway_auth.py:4` claims DM pairing, which does not exist. `GatewayAuth` is built directly at `base.py:103`, not through DI. Deny-by-default exists already (`allow_all_by_default` is off).

**Design:**
- Move `GatewayAuth` behind a `GatewayAuthPort`, bound in DI. **Fix the docstring.**
- `GatewayPairingService` (application/services) with a `PairingStorePort` (SQLite table `gateway_pairings` per profile). The pairing lifecycle is a small State machine: `Issued → Claimed | Expired | Revoked`.
  1. The owner runs `weebot gateway pair new --platform telegram [--admin]`. That prints an 8-character code drawn with `secrets.choice` from an unambiguous alphabet (no 0/O/1/I). Only its sha256 is stored. TTL 1 h.
  2. The user DMs `/pair CODE`.
     - On success, the user is added to `allowed_users` (and `admin_ids` with `--admin`).
     - After a failure, that sender is limited to 1 attempt per 10 minutes.
     - After 5 failures, the sender is locked out for 24 h.
  3. Unknown senders get one fixed reply, "not authorised; ask the owner for a pairing code", rate-limited. Their content is never processed.
- **Tiers:** `GatewayCommandDispatcher.register(cmd, handler, tier="user"|"admin")`.
  - Admin-only: `/model`, per-channel overrides, `/sethome`, `/approve` for others' runs, and pairing revocation.
  - `/whoami` shows the platform id, tier and profile.

**Tests:**
- a code works once;
- an expired code fails;
- 5 wrong codes lock the sender out;
- a non-admin sending `/model` is refused;
- unknown-sender content never reaches the flow (red today for platforms where `is_authorized` is bypassed — verify per adapter in the contract suite).

### H30. Cron upgrades — M

**Problem.** Two job models exist:
- `SchedulingManager` jobs (`scheduling/scheduler.py:135`);
- `CronJobRecord` (`domain/models/cron_job.py`), stored as JSON.

Beyond that:
- `schedule_tool` creates the former; agent crons use the latter.
- Delivery (`cron_delivery_service.py`) does raw HTTP to Telegram, Discord or Slack only, with no allowlist check.

**Design:**
- **One user-facing model.** `schedule_tool` creates `CronJobRecord`s. `SchedulingManager` stays as the execution engine underneath (`load_cron_agent_jobs`, `:633`, already bridges the two).
- **Natural-language schedules,** with a pure parser and no LLM and no new dependency:
  - signature `parse_schedule(text, now, tz) -> Trigger | ParseError`;
  - grammar: `every <N> (minutes|hours|days)`, `every <weekday>[,…] [at] HH[:MM][am|pm]`, `daily|weekdays at …`, `in <N> (m|h|d)`, `at HH:MM`, `on YYYY-MM-DD at …`, raw 5-field cron;
  - table-driven tests, and `Trigger` reuses APScheduler trigger configs.
- **Delivery targets:** `DeliveryTarget` gains `gateway:<adapter>:<chat>`, `home`, `origin` (the chat that created the job) and `all`. Delivery goes through the **H29 outbox**, so the allowlist and auth apply. The raw HTTP paths are removed.
- **Monitor mode:** `monitor: {source: url|file|command, selector?, min_interval}`.
  - Before the agent runs, compute a sha256 of the source; for a URL, through the egress-guarded fetch.
  - If it is unchanged since the last run, record `skipped_unchanged` and skip the LLM.
  - Cheap unattended watching.
- **Notepad:** `data/cron/<job_id>/notes.md` is injected into the job prompt. A `cron_notes` tool action can write it, but only inside that job's `cron_job_context` (`core/cron_context.py`).
- **Blueprints:** a `schedule:` block in `SKILL.md` frontmatter (`text`, `deliver_to`, `monitor`). `weebot skill schedule <skill>` shows it and creates the job on explicit confirmation. **It is never automatic**, because an imported skill must not schedule itself.

**Tests:**
- parser table;
- monitor mode skips the second run of an unchanged file, with zero LLM calls;
- a `home` target reaches the outbox;
- a blueprint does not schedule itself on install.

### H27. Persistent goal and `/btw` — S-M

**Design:**
- **Goal:** a `SessionGoal` value object on `Session`: text, `max_cycles` default 3, `judge_model` defaulting to the BUDGET tier.
- **New FSM state** `GoalCheckState`, inserted between `VerifyingState` and `CompletedState`, only when a goal is set. This makes 16 states.
  - It asks the judge for a structured `{done: bool, reason, next_task?}`, validated by pydantic.
  - If not done, cycles remain and the cost meter allows it: go to `PlanningState` with `next_task`. Otherwise go to `CompletedState`.
  - This is the State pattern, the native shape of the FSM.
- **`/btw` side question:** `AskSideQuestionCommand(session_id, question)` CQRS.
  - It calls the LLM with the session's **identical** `PromptLayout` prefix (H10), so the cache is reused, plus the question.
  - `tools=[]`, and the cascade is told not to send tools.
  - The answer is returned and journaled as a `SideQuestionAnswered` event. It is **not** added to the executor buffer.
- **Surfaces:** web, CLI `weebot flow btw`, gateway `/btw`.

**Tests:**
- a goal judged not done at cycle 1 and done at cycle 2 completes after 2 cycles;
- `max_cycles` is honoured;
- `/btw` sends no tools, leaves the main buffer unchanged, and shows a prefix-cache hit in a recorded request.

---

## 10. Phase 5: extensibility and supply chain

### H14. Skills supply chain — M

**Problem.** `SkillSecurityScanner` (`application/services/skill_security_scanner.py:66`) runs only from the manual `skill scan` command (`cli/commands/skills.py:318`). The paths that do no scanning or trust handling:
- `skill install` for WEEBOT/MANUS formats;
- `SkillPackager.install_from_path` (`skill_packager.py:155`);
- `ClawHubImporter`, which forces quarantine but has no caller.

There is no lockfile, no ledger and no rollback.

**Design:**
- **Facade** `SkillInstaller` (application/services). It is the **only** way any path installs or updates a skill: CLI, importers, materializer, curator and distiller. Its steps:
  1. resolve the source;
  2. scan;
  3. assign trust from a policy matrix (below);
  4. write a lock entry;
  5. write a ledger entry;
  6. place the files.

  A fitness test asserts that nothing else writes under the skills dirs: a grep of writers to the skill paths outside the installer.
- **Provenance × trust matrix,** as a pure function:

  | Source | Initial trust | Scanner blocked |
  |---|---|---|
  | builtin | trusted | n/a |
  | manual install (local path) | candidate | quarantined |
  | registry import (ClawHub, awesome, GitHub) | quarantined | refuse |
  | agent_created (distiller/materializer) | quarantined | refuse |
- **Lockfile** `skills.lock` (TOML): name, source url, ref/sha, sha256 of the tree, trust and installed_at. `weebot skill verify` re-hashes and flags drift.
- **Mutation ledger:** content-addressed objects in `data/skills/objects/<sha256>` plus a ledger table (skill, before_sha, after_sha, actor `foreground|background`, reason, ts).
  - `weebot skill rollback <name> [--to SHA]` restores. A rollback is itself a ledger entry: Memento plus Command.
- **User lock:** `locked: true` in the lock entry. The curator, distiller and materializer refuse to modify a locked skill.

**Tests:**
- every install entry point produces a lock and ledger row (parametrised);
- a blocked scan on a registry import is refused;
- a background edit of a locked skill is refused;
- rollback restores the bytes.

**Gates:** ADR-026. `SECURITY_MODEL.md`.

### H25. `weebot security audit` — S

**Design:**
- `VulnerabilityFeedPort` with an `OsvAdapter` (`POST https://api.osv.dev/v1/querybatch` through the egress-guarded HTTP client).
- Collectors, as Strategy objects:
  - the venv, via `importlib.metadata.distributions()`;
  - MCP pins (npx/uvx args from typed MCP config);
  - skill requirements.
- `weebot security audit [--json] [--ack ID --reason TEXT]`. Acks go to `~/.weebot/security_acks.json`.
- **Refactor `run_doctor`** (`interfaces/cli/support.py:212`) from inline appends into a list of check functions (`DoctorCheck` providers). The audit adds an advisory check, and H1, H5, H19 and H20 add theirs the same way.
- **Name collision:** `behavior_commands.py:291` defines another `doctor`. Rename it to `behavior doctor` and document it.

### H24b. Memory provider port and lifecycle hooks — M

**Design:**
- `MemoryProviderPort(ABC)` with:
  - `on_session_start(ctx) -> SnapshotPart`;
  - `on_pre_compress(dropped: Sequence[Message]) -> list[Fact]` (facts to keep);
  - `on_delegation(child_spec) -> SnapshotPart`;
  - `on_session_end(summary)`.
- A **Composite** provider aggregates the built-in providers: file memory (`MemoryPort`), KG and episodic summaries.
- The H9 `PruneOldToolOutputs` and `SummarizeMiddle` passes call `on_pre_compress` first.
- Turn on `KNOWLEDGE_GRAPH_EXTRACTION_ENABLED` and `EPISODIC_SUMMARIES_ENABLED` only after an eval cost check: tokens and $ per session at most +5%, recall suite improved. The env flags stay as the switch.

### H26. Delegation control — M-L

**Design** (on top of H4):
- **Ledger:** `DelegationLedgerPort` with a table `delegations(id, parent_session, child_session, depth, spec_json, status, heartbeat_at, started_at, finished_at, result_summary)` in SQLite and alembic.
  - `recover_abandoned()` runs in the web lifespan and the CLI boot. RUNNING rows with a heartbeat older than 2 minutes become ABANDONED, and the parent session gets an `ChildAbandoned` event.
- **Control tools** for parents only, with the `blocked_tools` policy hiding them from children:
  - `delegation_list`;
  - `delegation_stop(id)` (the cancel marker);
  - `delegation_steer(id, text)` (`SteeringPort` for the child session).
- **`output_schema`:** `SubAgentSpec.output_schema: dict | None`. The child's final answer is validated with `jsonschema` (already a dependency? check, otherwise pydantic `TypeAdapter` over a generated model). One retry with the validation error.
- **Worktree per child (optional):** `spec.isolation = "worktree"` → `git worktree add data/worktrees/<child>`, reusing the H5 git adapter's process runner. It is removed on completion and keeps the branch when there are changes.
- **Routing per task:** the factory honours `spec.model`, `spec.tier` and `spec.profile`.

### H33. Plugin platform — L (**parked by D-F; un-park on the second out-of-tree consumer**)

**Design, kept ready, so that H28 and H19 do not paint it into a corner:**
- **Discovery:** `entry_points(group="weebot.plugins")` plus a `plugin.yaml` manifest:
  - name, version, `kinds` (tool, hook, middleware, command, gateway, memory, secret_source);
  - `capabilities` (network, filesystem, exec, secrets, tools:<names>).
- **`PluginContext` Facade:**
  - `register_tool`, `register_middleware` (hooks are middleware, H16);
  - `register_command` (CQRS handler), `register_gateway` (H28 registry);
  - `register_memory_provider` (H24b), `register_secret_source` (H19).
- **Consent:** first load shows the capabilities. The approval is stored in `~/.weebot/plugins.lock` with the manifest sha256. A changed hash requires re-consent.
- **Kill list:** blocked name and version ranges, shipped in config.
- **API surface:** `weebot.plugin_api`, the only importable module, enforced by a new import-linter contract that forbids plugins from importing `weebot.*` except `weebot.plugin_api`. A compatibility promise is documented per minor version.
- **Isolation:** a later child-process host over JSON-RPC.

---

## 11. Phase 6: selective breadth (build on demand)

| ID | Design summary | Patterns | Pre-req |
|---|---|---|---|
| H34 | MCP server hardening: `bash` and `python_execute` off unless `WEEBOT_MCP_EXPOSE_EXEC=1`; `file_*` and `web_search` wrapped by `guard_tools` (today they are not, `mcp/server.py:378-392`); expose conversations as resources and pending approvals as a tool. **Pull into Phase 0 if the MCP server is ever run over SSE off-loopback.** | Decorator (`GuardedTool`) | H18 |
| H22 | `SshSandbox(SandboxPort)` on `asyncssh`: connection reuse, file sync by (mtime, size), remote `build_child_env` | Adapter | D1 un-park |
| H31 | Cloud browser adapters (Browserbase, Browser Use) behind `BrowserPort`. Hybrid router: public hosts go to the cloud and LAN hosts stay local, reusing `egress_guard.classify_host` (`:296`). Requires the H19 fix that routes `advanced_browser` through one fill path. | Strategy router | H19 |
| H32 | Cross-OS `computer_use` through an MCP desktop driver. A control lease (human or agent) as a State machine with explicit handover. The OSWorld harness is the gate. | State | H12 |
| H35 | Dashboard pages: cron, MCP servers (status, OAuth login), skills (trust, lock, ledger), pairing, checkpoints (rollback button), logs, config view. Each page reads existing CQRS queries; add queries rather than ad-hoc endpoints. | — | H5, H8, H12, H14, H30 |
| H36 | Kanban: only if multi-agent backlog work becomes a use case. Builds on the H26 ledger. | — | H26 |
| H37 | Textual TUI over the same CQRS mediator | — | — |
| H38 | ACP adapter (VS Code, Zed, JetBrains) as an interface-layer adapter over the mediator | Adapter | D1 un-park |
| H39 | Profile scope: a `ProfileContext` ContextVar bound at every entry point (web request, gateway message, cron job, CLI). Memory, session search and secret resolution read it. Per-profile `.env` resolved through H19, which fails closed when a profile has no binding. One gateway process serves all profiles. Today `ProfileManager` scopes only the SOUL.md role. | Context object | H19, H28 |
| H40 | Voice: `SpeechPort` adapters for Edge TTS (network, through the egress guard) and faster-whisper (local), streaming TTS, optional wake word | Adapter | H29 |
| — | OTel on by default when an endpoint is configured (row 39); i18n string catalogs; `install.ps1`; transactional updater; trajectory batch runner | — | low value |

---

## 12. ADRs, docs and map cards

ADRs are numbered from 016. `ARCHITECTURE.md:40-49` carries an inline ADR-006..009 list whose titles collide with `docs/adr/006-009`. Fix that list to link the files as part of ADR-016's PR.

| ADR | Title | Items |
|---|---|---|
| 016 | Prompt prefix invariant and cache layout | H2, H10, H24a |
| 017 | Error-recovery ladder | H3 |
| 018 | Delegation policy and ledger | H4, H26 |
| 019 | Workspace checkpoints, rewind and branch | H5, H21 |
| 020 | Persistent kernel and tool RPC | H17 |
| 021 | Approval floors, scopes and guardian | H18 |
| 022 | Secret sources, credential vault, MCP OAuth, egress proxy | H12, H19, H23 |
| 023 | Gateway contract, pairing, outbox | H8, H28, H29 |
| 024 | OpenAI-compatible API | H12b |
| 025 | Plugin platform and capability consent (when un-parked) | H33 |
| 026 | Skills supply chain | H14, H42 |

**Docs touched across the plan:**
- `docs/SECURITY_MODEL.md`: H1, H4, H8, H12, H14, H18, H19, H23, H42.
- `docs/CONFIGURATION.md` and `.env.example`: every new flag or setting, via `scripts/generate_env_example.py`.
- `docs/ENTRY_POINTS.md`: rollback, rewind/retry/branch/btw, gateway pair, mcp login, security audit, skill rollback/verify/schedule.
- `docs/EVENT_CATALOG.md`: every new event.
- `ARCHITECTURE.md`: known-debt rows closed.

**Map cards.** One per new noun, under `map/objects/<layer>/`:
- `child_env`, `recovery_ladder`, `delegation_guard`, `workspace_checkpoint`;
- `tool_arg_coercion`, `middleware_chain`, `spillover_store`, `loop_detectors`, `compression_pipeline`;
- `prompt_layout`, `session_search`, `patch_matching`, `file_state`;
- `approval_floors`, `kernel_manager`, `lsp_manager`, `session_timeline`;
- `secret_sources`, `credential_vault`, `gateway_registry`, `gateway_outbox`, `pairing_service`;
- `schedule_parser`, `goal_check_state`, `skill_installer`, `delegation_ledger`.

**Process cards:** "tool call path" (updated), "gateway turn" (new), "recovery on LLM error" (new).

---

## 13. Measurement plan

"Equal or better" has to be measured, not claimed. Weebot's eval stack (eval runner, harness suites, regression gate, OSWorld) is the referee.

1. **Baseline (before Phase 1).** Run the existing harness suites on the default role models and record:
   - pass rate;
   - $ and tokens per solved task;
   - cache-read ratio;
   - LLM turns per step;
   - tool-call failure rate on BUDGET/FREE tiers;
   - edit-failure loops (≥ 2 consecutive failed edits on one file);
   - wasted iterations (guard stops / total).

   Commit the numbers to `tasks/quality/hermes_parity_baseline.json`.
2. **[eval-gated] items** (H2, H9, H10, H11, H6, H17, H24b) each attach before/after numbers in the PR. Fail conditions:
   - pass rate drops more than 1 pp;
   - $ per solved task rises.
3. **Suites to add:**
   - `edit_heavy` (multi-file refactors) for H6/H20;
   - `data_wrangling` (CSV/JSON pipelines needing many small tool calls) for H17;
   - `long_context` (40+ tool results) for H9/H10;
   - `adversarial_gateway` (bot loops, unknown senders) for H8/H29.
4. **Security regression tests are permanent.** Each security fix (H1, H4, H18, H19, H42) leaves a red-first test in `tests/unit/fixes/`.
5. **Matrix re-score at M5.** Re-run the 43-row comparison. Each row must read W or =. Any row still H gets a decision: build, or accept with a reason.

---

## 14. Risks register

| Risk | Item | Mitigation |
|---|---|---|
| MCP servers break when they lose inherited env | H1 | `env_passthrough` and `${VAR}`; a doctor warning listing what each server used to get; release note |
| Prompt caching raises cost on one-shot calls (write premium) | H2 | Breakpoints only when the prefix exceeds 1024 tokens; metric watch; flag off-switch |
| Cache invalidation per step under ADR-008 | H10 | D3 setting plus eval decision |
| The recovery ladder hides real failures | H3 | Each rung logs, and emits `llm_recovery_total{category,rung}`; at most one try per rung |
| Checkpoint disk growth or slow `add -A` on big repos | H5 | Caps (D4), GC, skip with a warning; it runs once per turn, not per call |
| Fuzzy patch applies to the wrong place | H6 | A unique-span requirement for every strategy; the result names the strategy; `exact: true` opt-out |
| The kernel RPC becomes a guard bypass | H17 | RPC dispatches through `ToolExecutor.execute_tool` only; the allowlist excludes dispatch tools; the taint carries over; red-first test |
| Guardian LLM approves something harmful | H18 | Off by default; SUSPICIOUS only; never in tainted sessions; it never sees tool output; `escalate` on any doubt |
| An OAuth token leaks | H12 | Writable `SecretStorePort` (keyring); never in the env or transcript; redaction backstop |
| A delivery outbox duplicates messages | H29 | Idempotency keys; at-least-once documented; dedupe window per chat |
| Pairing code brute force | H8 | 8 characters from a 31-symbol alphabet (~8.5e11), 1 h TTL, 1 try / 10 min after a failure, lockout after 5 |
| Files near the 800-line cap grow past it | H3, H5, H16 | All new behaviour goes in sibling modules (§1); the god-module test enforces it |
| Hermes-isms erode Weebot's leads | all | §2.1 anti-patterns; ADR review; the matrix re-score at M5 checks the "W" rows stayed W |

---

## 15. Appendix: defects found during mapping (not in the comparison study)

| # | Defect | Evidence | Folded into |
|---|---|---|---|
| 1 | Rate-limit webhook tier keyed on paths that are not mounted | `web/rate_limit.py:38` vs `web/main.py:608-620` | H41 |
| 2 | A skill without `trust:` counts as trusted | `skill_registry.py:248` | H42 |
| 3 | WSL2 and one native `Popen` inherit the full env when the merge is empty | `wsl2.py:138-156`, `native_windows.py:328` | H1 |
| 4 | Cache telemetry reads `input_tokens`, which no adapter emits | `caching_llm_adapter.py:141` | H2 |
| 5 | One flag gates both prompt caching and the response cache | `adapter_factory.py:104,215` | H2 |
| 6 | Context overflow is retried with the same payload, then reported as a credits problem | `resilient_adapter.py:147,405`; `_turn.py:76` | H3 |
| 7 | Sub-agent `spec.role` and `spec.tools` are ignored; `dispatch_parallel_tasks` is a second spawn path with no timeout | `di/__init__.py:685`; `tools/dispatch_agents.py` | H4 |
| 8 | Double head/tail slicing, a fixed 128 K window, and a mid-buffer system summary | `_context_compressor.py:81-121`; `_base.py:77` | H9 |
| 9 | `advanced_browser` fills fields with raw model values, bypassing `BrowserPort` | `tools/advanced_browser.py:238-245` | H19 |
| 10 | Four default gateway commands are never handled; only Telegram dispatches commands | `telegram.py:301-318` | H28 |
| 11 | `search_history` advertises FTS syntax that the sanitiser neutralises | `fts5_search.py:15-33` | H15 |
| 12 | `MiddlewareChain` is plumbed but never constructed; `HookRegistryPort` has no implementation | `plan_act_flow_config.py:204`; `hook_registry_port.py` | H16 |
| 13 | The adapter cache key holds the plaintext API key | `adapter_factory.py:160` | H2 PR (H13 note) |
| 14 | `MCPServerConfig.env` documents a safe baseline that the manager does not apply | `domain/models/mcp.py:93` | H1, H12 |
| 15 | `ARCHITECTURE.md` inline ADR list collides with `docs/adr/006-009` | `ARCHITECTURE.md:40-49` | ADR-016 PR |
