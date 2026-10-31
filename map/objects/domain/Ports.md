---
type: object
name: Ports
code: weebot/application/ports/*_port.py
cluster: domain
universe: live
status: verified
verified: 2026-10-31
commit: ff808eb3
---

# Ports

The interfaces (ABCs and a few `Protocol`s) that the application layer depends on and the infrastructure layer implements. One file per port in `weebot/application/ports/`: 64 `.py` files (62 `*_port.py`), 70 interface classes counting `EventBusPort` (count 2026-10-30).

## Why this shape
Dependency inversion: application code types against the port, and an adapter is chosen at one place, the DI container (`weebot/application/di/__init__.py:139-407`). The layer contracts in `.importlinter` and `tests/unit/test_architecture_fitness.py` enforce the direction. They live in `application/`, not `domain/`, because most of them carry application types (events, plans, tool results). A second, smaller port set lives in `weebot/domain/ports.py` (`IModelProvider`, `IRepository`, `INotifier`, `ITool`, `EventPublisher`, `PlanTemplateStore`, `CommitmentStore`, `weebot/domain/ports.py:10-118`), and `state_roles_port.py` re-exports two of them (`application/ports/state_roles_port.py:19`).

## Shape
`ports/__init__.py` re-exports only `LLMPort`, `StateRepositoryPort` and `EventBusPort` (`weebot/application/ports/__init__.py:3-7`). "DI" says how `Container.configure_defaults` resolves it: **port** = registered under the port class; **key** = registered under a string or concrete class; **none** = no `register` call. Main implementation: the first subclass found by `class X(...Port)`; Protocols match by structure, so there is none to grep.

| Port | file:line | Main implementation | DI |
|---|---|---|---|
| ApiKeyPort | api_key_port.py:64 | SQLiteApiKeyStore `infrastructure/security/sqlite_api_key_store.py:38` | port `di/__init__.py:182` (factory `di/_factories.py:246`); the web app holds it as `app.state.api_key_store` (`interfaces/web/main.py:209`, read at `interfaces/web/auth.py:112-118`) |
| ApprovalPort | approval_port.py:36 | Deny / FlowPause / ConsoleApproval `application/services/tool_approval.py:104-160` | none |
| AuditPort | audit_port.py:15 | AuditService `application/services/audit_service.py:32` | key `AuditService` `di/__init__.py:171` |
| BehavioralLearnerPort | behavioral_learner_port.py:11 | BehavioralLearner `application/services/behavioral_learner.py:36` | key `"behavioral_learner"` `di/_learning.py:37` |
| BrowserPort | browser_port.py:151 | PlaywrightAdapter `infrastructure/browser/playwright_adapter.py:26` | none |
| CanonicalizerPort | canonicalizer_port.py:18 | ActionCanonicalizer `infrastructure/adapters/action_canonicalizer.py:34` | key `"build_action_canonicalizer"` `di/__init__.py:294` |
| CheckpointPort | checkpoint_port.py:14 | SQLiteCheckpointStore `infrastructure/persistence/checkpoint_store.py:35` | port `di/_capabilities.py:53` (always bound, for the delete cascade); flows get it only with `WEEBOT_FLOW_CHECKPOINTS` |
| ClawHubAdapterPort (Protocol) | clawhub_adapter_port.py:19 | ClawHubGitAdapter `infrastructure/adapters/clawhub_adapter.py:20` | none (consumer `application/skills/clawhub_importer.py:85`) |
| CodeReviewerPort | code_reviewer_port.py:12 | CodeReviewerService `application/services/code_reviewer_service.py:72` | key `"code_reviewer"` `di/__init__.py:190` |
| DatabaseRouterPort | database_router_port.py:15 | DefaultDatabaseRouter `infrastructure/persistence/default_database_router.py:16` | none (used in `sqlite_state_repo.py`) |
| DesktopPort | desktop_port.py:41 | WindowsDesktopAdapter `infrastructure/adapters/windows_desktop.py:66` | none |
| DreamerPort | dreamer_port.py:11 | DreamerAgent `application/agents/dreamer.py:53` | key `"dreamer_agent"` `di/__init__.py:191` |
| EventBusPort | event_bus_port.py:15 (extends EventPublisherPort) | AsyncEventBus / DurableEventBus `infrastructure/event_bus.py:43, 180`, ValkeyEventBus, SessionScopedEventBus | port `di/__init__.py:149` |
| EventPublisherPort | event_publisher_port.py:16 | WebSocketEventBroadcaster `interfaces/web/event_broadcaster.py:15` | none |
| EventStorePort | event_store_port.py:16 | AsyncEventStore `infrastructure/event_store.py:104` | port `di/__init__.py:176` |
| FileStoragePort | file_storage_port.py:14 | LocalFileStorageAdapter `infrastructure/adapters/file_storage_adapter.py:18` | port `di/__init__.py:196` |
| IGatewaySessionStorePort (Protocol) / AbstractGatewaySessionStore | gateway_session_store_port.py:15, 67 | SQLiteGatewaySessionStore `infrastructure/persistence/gateway_session_store.py:40` | port `di/__init__.py:179` |
| HookRegistryPort (Protocol) | hook_registry_port.py:14 | structural | none (typed in `executor/_base.py:83`, `models/plan_act_flow_config.py:191`) |
| IntentReviewPort | intent_review_port.py:11 | IntentReviewService `application/services/intent_review_service.py:35` | inside `"idea_gate"` `di/__init__.py:192`, `di/_factories.py:289-298` |
| JudgePort | judge_port.py:52 | ModelJudge, ScoreJudge `application/eval/judges.py:44, 102` | ModelJudge built by `harness baseline --judge` (`cli/commands/harness.py:417`) |
| KnowledgeGraphPort | knowledge_graph_port.py:16 | SQLiteKnowledgeGraph `infrastructure/persistence/sqlite_knowledge_graph.py:36`, PostgreSQLKnowledgeGraph | key `SQLiteKnowledgeGraph` `di/_capabilities.py:35` |
| LLMPort | llm_port.py:9 | adapters in `infrastructure/adapters/llm/` (LLMAdapters card) | port `di/__init__.py:153` |
| MainReviewPort | main_review_port.py:12 | MainReviewService `application/services/main_review_service.py:39` | inside `"idea_gate"` (same) |
| McpToolRegistrationPort | mcp_tool_registration_port.py:13 | RoleBasedToolRegistryAdapter `infrastructure/adapters/mcp_tool_registry_adapter.py:10` | none |
| McpToolRetrievalPort | mcp_tool_retrieval_port.py:17 | LocalEmbeddingMcpToolRetrievalAdapter `infrastructure/adapters/mcp_tool_retrieval_adapter.py:26` | none |
| MemoryPort | memory_port.py:8 | FileSystemMemoryAdapter `infrastructure/persistence/filesystem_memory.py:29` | key `FileSystemMemoryAdapter` `di/__init__.py:174` |
| MetricsPort | metrics_port.py:11 | PrometheusMetricsAdapter `infrastructure/observability/prometheus_adapter.py:15` | key `PrometheusMetricsAdapter` `di/__init__.py:229` |
| MisalignmentJournalPort | misalignment_journal_port.py:10 | SQLiteMisalignmentJournal `infrastructure/persistence/sqlite_misalignment_journal.py:46` | key `"misalignment_journal"` `di/_learning.py:32` |
| NotificationPort / NotificationSubscriber | notification_port.py:115, 211 | WindowsToastAdapter `infrastructure/notifications/windows_toast.py:18`, WindowsToastSubscriber `weebot/infrastructure/notifications/windows_toast.py:188` (the Telegram, Slack and log channels in `notifications.py` do not subclass it) | none |
| OptimizationTarget | optimization_target_port.py:20 | HarnessOptimizationTarget `application/services/harness_optimization_target.py:30` | key `"harness_optimization_target"` `di/_skillopt.py:30` |
| OptimizerPort | optimizer_port.py:25 | OptimizerAgent `application/agents/optimizer_agent.py:46` | key `"optimizer_port"` `di/_skillopt.py:23` |
| PlanCriticPort | plan_critic_port.py:11 | PlanCriticService `application/services/plan_critic.py:39` | none |
| ProviderAccountPort | provider_account_port.py:24 | OpenRouterAccountAdapter `infrastructure/adapters/llm/openrouter_account.py:15` | port `di/__init__.py:397` |
| RerankPort | rerank_port.py:16 | OpenRouterRerankAdapter `infrastructure/adapters/openrouter_rerank_adapter.py:35` | port `di/__init__.py:188` |
| RetentionAgentPort | retention_agent_port.py:11 | RetentionAgent `application/agents/retention_agent.py:40` | key `"retention_agent"` `di/__init__.py:193` |
| SandboxPort | sandbox_port.py:138 | backends in `infrastructure/sandbox/` (Sandbox card) | port `di/__init__.py:154` |
| ScoringPort | scoring_port.py:15 | PlanOutcomeScorer `infrastructure/scoring/plan_outcome_scorer.py:31`; AnswerScorer `infrastructure/scoring/answer_scorer.py:14` over ExactMatch / ExecutionResult / Verifier | port `di/__init__.py:224` (`WEEBOT_SCORING_MODE`) |
| SelfImprovementPort | self_improvement_port.py:11 | SelfImprover `application/services/self_improver.py:60` | none; built by the `improve` CLI (`cli/commands/improve.py:45`) |
| SkillIndexPort | skill_index_port.py:31 | Agentskills / AwesomeAgentSkills / GitHub index adapters `infrastructure/adapters/` | none |
| SkillRetrieverPort | skill_retriever_port.py:15 | BM25 / Semantic / Reranking retrievers `application/services/` | key `"skill_retriever"` `di/__init__.py:189` |
| SkillStorePort | skill_store_port.py:15 | SkillStore `infrastructure/persistence/skill_store.py:23`, MaterializingSkillStore | key `"skill_store"` `di/_skillopt.py:24` |
| SoulProviderPort | soul_provider_port.py:6 (re-export of `weebot/core/soul_provider_port.py`) | FileSystemSoulProvider `infrastructure/adapters/soul_provider.py` (`di/_factories.py:265-268`) | key `"soul_provider"` `di/__init__.py:187` |
| SpeechPort | speech_port.py:12 | OpenRouter / Whisper speech adapters `infrastructure/adapters/speech/` | port `di/__init__.py:175` |
| StateRepositoryPort | state_repo_port.py:60 | SQLiteStateRepository (card), InMemory, PostgreSQL | port `di/__init__.py:147` |
| BehavioralRuleStore, CorrectionStore, SessionConstraintStore, OpportunityStore, MemoryMetadataStore, WorkflowTemplateStore, PlanTemplateWriter (Protocols) | state_roles_port.py:35-94 | structural, the state repo | none (narrowed from `StateRepositoryPort` with `as_role`) |
| SteeringPort | steering_port.py:17 | InMemorySteeringAdapter `infrastructure/adapters/steering_adapter.py:15` | port `di/__init__.py:165` |
| StepAuditPort | step_audit_port.py:20 | StepEvidenceAuditor `application/services/step_evidence_auditor.py:45` | key `"step_audit_service"` `di/__init__.py:197` |
| StepEvaluatorPort | step_evaluator_port.py:29 | NoOp / LLMStepEvaluator `application/services/step_evaluator.py:42, 60` | key `STEP_EVALUATOR` `di/__init__.py:202`, None unless `WEEBOT_STEP_EVALUATOR` |
| StrategyStorePort (Protocol) | strategy_store_port.py:20 | StrategyStore `infrastructure/persistence/strategy_store.py:40` | built inside the `STRATEGY_TRANSFER` factory `di/_capabilities.py:57, 67-69` |
| StreamingLLMPort (Protocol) | streaming_llm_port.py:27 | structural | none |
| SubAgentCostTrackerPort | sub_agent_cost_tracker_port.py:10 | SubAgentCostTracker `infrastructure/adapters/sub_agent_cost_tracker.py:17` | port `di/__init__.py:186` |
| SubAgentFactoryPort | sub_agent_factory_port.py:10 | SubAgentFactory `infrastructure/adapters/sub_agent_factory.py:44` | port `di/__init__.py:185` |
| SummaryRepositoryPort | summary_repo_port.py:8 | SQLiteSummaryRepository `infrastructure/persistence/sqlite_summary_repo.py:49` | key `SUMMARY_REPO` `di/_capabilities.py:47` (always bound); flows get it only with `WEEBOT_EPISODIC_SUMMARIES` |
| SwarmEventBusPort | swarm_event_bus_port.py:13 | SwarmEventBus `infrastructure/swarm_event_bus.py:34` | port `di/__init__.py:184` |
| TaskQueuePort | task_queue_port.py:38 | InMemory / Redis task queues `infrastructure/queue/` | port `di/__init__.py:156`; RESERVED (D4), pinned by `tests/unit/test_task_queue_contract.py` |
| TaskRouterPort | task_router_port.py:15 | KeywordTaskRouter `application/services/keyword_task_router.py:25` | none |
| TaskRunnerPort (Protocol) | task_runner_port.py:33 | TaskRunner (structural) | port, aliased to `TaskRunner` `di/__init__.py:161` |
| ToolRepositoryPort | tool_repository_port.py:9 | SQLiteToolRepository `infrastructure/persistence/sqlite_tool_repo.py:28` | port `di/__init__.py:183` |
| TracingPort / Span | tracing_port.py:33, 13 | TracingAdapter `infrastructure/observability/tracing_adapter.py:26` | key `TracingAdapter` `di/__init__.py:152` |
| TrajectoryRepositoryPort | trajectory_repository_port.py:16 | TrajectoryRepository `infrastructure/persistence/trajectory_repo.py:24` | key `"trajectory_repo"` `di/__init__.py:226` and again `di/_skillopt.py:25` |
| VectorStorePort | vector_store_port.py:16 | NumpyVectorStore `infrastructure/adapters/numpy_vector_store.py:19` | none |
| WorkspaceSnapshotPort | workspace_snapshot_port.py:85 | LocalWorkspaceSnapshotAdapter `infrastructure/adapters/workspace_snapshot_adapter.py:71` | key `"workspace_snapshots"` `di/__init__.py:205` |

Not interfaces: `hook_context_types.py` (TypedDicts, `weebot/application/ports/hook_context_types.py:14-105`).

Consequences (read from source, not run):
- Ports with an implementation but no consumer typed against them; the only file outside `ports/` that names them is the implementation (grep 2026-10-30): `CanonicalizerPort`, `DesktopPort`, `OptimizationTarget`, `PlanCriticPort`, `SelfImprovementPort`, `StreamingLLMPort` (only `infrastructure/adapters/non_streaming_llm_adapter.py`; `application/strategies/llm_pool.py:304` names it in a comment). They document a seam nobody depends on.
- Many ports are resolved under a string or a concrete class (rows marked **key**), so `container.get(SomePort)` does not find them; the caller must know the key.
- `"trajectory_repo"` is registered twice with the same factory (`di/__init__.py:226`, `di/_skillopt.py:25`); the second registration replaces the first.
- Two event-publisher interfaces: `EventPublisherPort` (ABC, here) and `EventPublisher` (Protocol, `weebot/domain/ports.py:60`, used by `weebot/core/agent_context.py:43`).

## Connected to
- **Registered in** the DI Container (DIContainer card). **Implemented in** `weebot/infrastructure/` and, for service-shaped ports, in `weebot/application/services/` and `application/agents/`.
- **Looks like but is not:** `weebot/domain/ports.py` (domain-level Protocols, tested by `tests/unit/test_domain_ports.py`).

## If you change this
**Hits:** every implementation of the changed port, its DI factory, and the layer rules (`.importlinter`, `tests/unit/test_architecture_fitness.py`). Adding an abstract method breaks every subclass at instantiation time. The busiest ports by files that name them (`grep -rlw`, 2026-10-30): `LLMPort` (114 source, 33 test files), `StateRepositoryPort` (72 / 23), `EventStorePort` (16 / 10), `SandboxPort` (13 / 5); source counted over `weebot/` and `cli/`.
**Does not hit:** the domain models; `weebot/domain/ports.py`.

## Surfaces
None directly; developers wiring adapters.

## See
`weebot/application/ports/`, `weebot/application/di/__init__.py`
