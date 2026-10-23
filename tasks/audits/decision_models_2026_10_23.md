---
status: reference
date: 2026-10-23
---

# Decision models instead of chat LLMs — where they fit (2026-10-23)

Question: in which parts of the workflow would a decision model such as
Perplexity Decisions (`POST https://api.perplexity.ai/v1/decisions`) beat a
chat LLM on speed and cost?

What the API does: it takes `state` (text, JSON or image parts) plus named
questions and returns probabilities, not text. Question types: `noul`
(P(yes)), `choice` (1-255 named options, with per-option probabilities) and
`score` (an ordered rubric of 1-10 levels, with an expected score). Models:
`pplx-decider-v1.2` (27B) at $0.02 per 1M input tokens, and
`pplx-decider-flash-v1.2` (4B) at $0.01; output is free and there is no
per-request fee. Auth is `PERPLEXITY_API_KEY` as a Bearer token. There is no
key in `.env` yet, and no live latency or accuracy test has been run.

Rule for a fit: the call's output is only a yes/no, a pick from a fixed set,
or a score, and no generated text from it is used downstream. If generated
text is used, the call fits only as a hybrid: decide first, then generate the
text only on the branch that needs it.

## Candidates, best first

| # | Call | Decision today | Runs | Hot path | Fit |
|---|---|---|---|---|---|
| 1 | `flows/states/verifying.py` `_check_consistency` | YES/NO | up to 3 per task, sequential | yes, before Done; CoVe on by default | `noul`. Also gives P(yes), so a threshold instead of string parsing |
| 2 | `flows/states/verifying.py` `_score_output` | 4 axes, 1-5 each | 1-3 per task | yes, same path | `score`, one question per axis in one request |
| 3 | `services/code_reviewer_service.py` | approved / revise / reject + hint | per code step, up to 2 retries | yes; premium reviewer model | hybrid: `choice`, then chat for the hint only on revise |
| 4 | `services/intent_review_service.py` | ready / not_ready / blocked + questions | once per new prompt | yes, blocks planning, 30 s timeout | hybrid: `choice`, then chat for questions only when not ready |
| 5 | `services/session_constraint_extractor.py` | extracts constraint text | per user turn passing a regex | yes, before planning | pre-gate: `noul` "does this turn add or revoke a constraint?", then chat only on yes (the prompt says most turns produce none) |
| 6 | `services/plan_merger.py` | best of N plans | complex tasks only | yes, planning | `choice` |
| 7 | `services/tree_of_thoughts_scorer.py` | 3 axes, 1-5, per candidate | per failed step | failure path | `score` |
| 8 | `services/step_evaluator.py`, `services/plan_critic.py` | progress score + regression; approve/revise/reject + confidence | per step; per plan | would be hot | `score` / `choice`; neither is wired in `interfaces/factories.py` today |

Background or offline, so speed matters little and only cost does:
`main_review_service.py` (idea gate), `retention_agent.py`,
`correction_tracker.py`, `skill_review_gate.py` (flag off),
`skill_curator.py`, `layer_diagnostics_agent.py`, `code_quality_signal.py`,
`infrastructure/scoring/verifier_scorer.py` and `eval/judges.py`.
`evaluator_selector.py` should stay on chat models: it measures an evaluator
prompt on a chat model, so swapping the backend changes what it measures.

Not candidates: planning, execution, summaries, CoVe question generation and
answering, revisions, compressors, the dreamer, debate and the like, since
they produce text. Also not candidates: the routers, the ACR scorer,
FlowRouter, tool guards and StepEvidenceAuditor, which make no LLM call.

## Expected gain, and what is not known

- The verifier calls in rows 1-2 now run on DeepSeek V4.1 Flash, and on the
  2026-10-23 batch each whole task cost about $0.02. These yes/no calls are a
  small share of that, so the money saved per task is small. The likely gain
  is latency: up to 3 sequential round trips at the end of every task, plus a
  verdict that is a probability rather than a parsed string.
- Rows 3-4 replace calls that are slower or on a premium model (the reviewer
  is GPT-6.1 Sol first), so they save the most per call, but only as hybrids.
- Unknown until measured: the API's latency from here, and whether a 4B or
  27B decider agrees with the current models on Weebot's own prompts. The
  next step is a small A/B on the logged CoVe and reviewer verdicts before
  any wiring.

## If adopted, how it would fit the architecture

A `DecisionPort` in `application/ports/` (the methods `noul`, `choice` and
`score`), with a Perplexity adapter in `infrastructure/adapters/` registered
in `application.di`. The current chat-LLM implementation would stay as the
fallback when no key is set or the call fails. The fail-closed rules in
`verifying.py` (a check that did not run is not a pass) carry over unchanged.

## Found on the way

- `_check_consistency` parsed with `"yes" in reply`, so "No - saying yes
  would need more" read as consistent. Fixed: the reply must start with yes
  (`tests/unit/fixes/test_cove_claim_contains_the_result.py`).
- `plan_critic` and `step_evaluator` exist with DI wiring but are never passed
  to PlanActFlow in `interfaces/factories.py`, so CritiquingState and
  per-step evaluation do not run on the default path. Wiring them adds LLM
  calls per plan and per step, so this is a product decision, not a bug fix.
