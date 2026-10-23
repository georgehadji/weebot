# Model routing against current scores (2026-10-23)

Source: Artificial Analysis leaderboard (artificialanalysis.ai/leaderboards/models), read 2026-10-23. Columns: Intelligence Index, cost per task (USD), end-to-end response time. Where AA lists several reasoning efforts, the row nearest Weebot's call is used (plain ids, no `:thinking`, so the provider default). Routing lives in `weebot/config/model_refs.py` (`ROLE_MODEL_CONFIG`).

| Model | Index | $/task | E2E s |
|---|---|---|---|
| Claude Opus 5.5 (high) | 54 | 1.82 | 28 |
| Kimi K3.1 Pro | 55 | 2.11 | 36 |
| Gemini 4 Argon (high) | 53 | 1.99 | 60 |
| GPT-6.1 Sol (max / high) | 52 / 50 | 0.72 / 0.32 | 245 / 39 |
| Claude Sonnet 5.5 (high) | 47 | 0.88 | 15 |
| MiMo-V2.6-Pro | 46 | 0.13 | 50 |
| DeepSeek V4.1 Flash 1017 (max) | 45 | 0.26 | 14 |
| GLM-5.3 (max) | 45 | 2.01 | 32 |
| MiniMax-M3.1-Flash | 43 | 0.22 | 30 |
| Claude Haiku 5.5 (high / max) | 38 / 43 | 0.08 / 0.21 | 19 / 323 |
| GLM-5.3-Flash | 42 | 0.28 | 40 |
| MiMo-V2.6-Flash | 38 | 0.06 | 46 |
| GPT-6 Luna (max) | 38 | 0.07 | 69 |

## Per role

| Role | Primary | Verdict | Why |
|---|---|---|---|
| executor | DeepSeek V4.1 Flash | keep | Highest-volume loop: 14 s at 45. MiMo Pro scores 46 at half the cost but takes 50 s per call. |
| planner, researcher | Haiku 5.5 | keep | Billed hard-task eval this day: tied the previous primaries at 3-10x lower cost. |
| reviewer | Haiku 5.5 | keep | Billed subtle-bug eval: 6/6, same as Sol, at ~1/12 the cost. |
| critic, analyst | GPT-6.1 Sol | keep | Best index per dollar above 50 (52 at $0.72; 50 at $0.32). |
| premium fallback (planner, reviewer, critic, analyst) | Kimi K3.1 Pro | **changed** from Argon | 55 vs 53 at the same cost and 36 s vs 60 s; live tool call verified (3.5 s vs 5.3 s). |
| automation, admin | DeepSeek V4.1 Flash | **changed** from MiniMax | 45 vs 43, 14 s vs 30 s, +$0.04 per task. |
| coder | Sonnet 5.5 | keep, open question | Sol (high) scores 50 at $0.32 against Sonnet's 47 at $0.88, but the index is not a coding score and Sonnet won the billed multi-step coding runs (3/3). A billed Sonnet-vs-Sol coding eval decides it. |
| verifier | DeepSeek V4.1 Flash | keep | Same reasoning as the executor. |
| dreamer, product_manager, designer | MiMo-V2.6-Pro | keep | Background roles, latency does not matter: 46 at $0.13 is the best value. |
| summarizer, documentation | Haiku 5.5 | keep | Cheap at high effort, fast. |
| subagent | GPT-6 Luna | keep | 38 at $0.07; MiMo Flash (38, $0.06) is fallback 1. |

Not covered: per-component scores (agentic, terminal coding) behind the index, which need the per-model pages; and models AA does not list.
