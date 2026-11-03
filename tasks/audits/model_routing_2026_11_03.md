---
status: reference
date: 2026-11-03
---

# Model routing against AA Intelligence Index v5.0 (2026-11-03)

Artificial Analysis released Intelligence Index v5.0 on 2026-10-27 (new tests, mostly private sets, new weights). The 2026-10-23 pass ([model_routing_2026_10_23.md](model_routing_2026_10_23.md)) used v4.3.2, so its index numbers do not carry over. Figures below come from artificialanalysis.ai comparison pages and the leaderboard, read 2026-11-03. The v4 -> v5 deltas come from secondary reports (letsdatascience.com, runtimewire.com, 2026-10-28/29). Not checked by hand.

Columns: Index, AutomationBench (AB), Terminal-Bench 4.0 (TB), FrontierCode 2.0 (FC), AA-Omniscience (Om), cost per task, end-to-end latency.

| Model (effort) | Index | AB | TB | FC | Om | $/task | E2E s |
|---|---|---|---|---|---|---|---|
| Claude Opus 5.5 (high) | 52 | 63 | 57 | 36 | 42 | 3.46 | 50 |
| Claude Sonnet 5.5 (high) | 41 | 59 | 44 | 26 | 19 | 1.64 | 19 |
| Claude Haiku 5.5 (high) | 30 | 34 | 22 | 23 | 5 | 0.16 | 35 |
| GPT-6.1 Sol (medium / high) | 46 / 50 | 63 / 64 | 48 / 52 | 33 / 37 | 40 / 41 | 0.36 / 0.59 | 17 / 77 |
| GPT-6.1 Terra (medium / high) | 38 / 42 | 58 / 58 | 32 / 42 | 35 / 37 | 27 / 28 | 0.17 / 0.26 | 10 / 26 |
| Kimi K3.1 Pro | 46 | 73 | 67 | 25 | 30 | 3.68 | 83 |
| DeepSeek V4.1 Flash (max) | 32 | 67 | 34 | 28 | 1 | 0.60 | 16 |
| MiniMax M3.1 Flash | 29 | 73 | 26 | 21 | -6 | 0.49 | 22 |
| MiMo-V2.6-Pro | 30 | 59 | 35 | 24 | -4 | 0.26 | 61 |
| MiMo-V2.6-Flash | 27 | 64 | 23 | 22 | -11 | 0.13 | 72 |
| GLM-5.3 (max) / GLM-5.3-Flash | 32 / 28 | 62 / 60 | 42 / 33 | 22 / 18 | 6 / 1 | 5.01 / 0.58 | 29 / 35 |
| GPT-6 Luna (max) | 28 | 53 | 13 | 25 | -8 | 0.15 | 124 |

## Applied (score-backed only)

| Role | Before | After | Why |
|---|---|---|---|
| planner | Haiku, Sol, Kimi, MiMo-Pro | Haiku, Sol, Kimi | MiMo-Pro index 30 |
| planner_sub | MiMo-Pro, DeepSeek, Sol | Sol, DeepSeek, Haiku | Sol medium 46 vs 30, 17 s vs 61 s |
| executor | DeepSeek, MiMo-Pro, MiniMax, GLM-Flash | DeepSeek, MiniMax, Sol | MiniMax AB 73; GLM-Flash dominated |
| coder | Sol, Sonnet, GLM, DeepSeek | Sol, Sonnet, Kimi, DeepSeek | Kimi TB 67 vs GLM 42, cheaper |
| critic | Sol, Kimi, Opus | Sol, Opus, Kimi | Opus 52 vs 46, cheaper, faster |
| researcher | Haiku, MiMo-Pro, Sol, DeepSeek | Haiku, Sol, DeepSeek | MiMo-Pro Om -4 vs Sol 40 |
| analyst | Sol, MiMo-Pro, Kimi | Sol, Opus, Kimi | Opus 52 vs 30 |
| dreamer | MiMo-Pro, DeepSeek, Sol | Sol, DeepSeek, Haiku | Sol medium 46 at $0.36 vs 30 at $0.26 |
| product_manager | MiMo-Pro, Sol, Haiku | MiMo-Pro, Sonnet, Sol | MiMo-Pro kept for AA-Briefcase (knowledge work) |
| admin | DeepSeek, MiniMax, MiMo-Pro | DeepSeek, MiniMax, Sol | privileged ops get the stronger fallback |
| subagent | Luna, MiMo-Flash, Haiku, GLM-Flash | Luna, MiMo-Flash, Haiku | GLM-Flash dominated |

Unchanged: reviewer, verifier, designer, documentation, summarizer, automation, vision. Also unchanged: the cascade tier constants (`MODEL_CASCADE_TIER3` is still MiMo-Pro) and `_DEFAULT_ROLE_CASCADE`, which more modules read.

## Needs a billed eval before switching

1. **Haiku as primary** (planner, researcher, reviewer): v5.0 puts it far below Sol (AB 34 vs 64, Om 5 vs 41), against the 2026-10-23 billed ties. Researcher is the riskiest.
2. **GPT-6.1 Terra** for the cheap tier (executor, verifier, automation, subagent, summarizer, planner_sub): Terra medium is 38 at $0.17 and 10 s, but DeepSeek has the higher AB (67 vs 58) and a lower per-token price. Terra Pro has no independent benchmark.
3. **Reasoning effort**: plain ids send the provider default; which one that is was not confirmed, and Sol's cost moves ~1.6x and latency ~4.5x between medium and high.
4. **Vision**: v5.0 has no vision component.
