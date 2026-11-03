# ADR-017: A spent LLM cascade is recovered by a ladder, not by retrying the same payload

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H3, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "begin implementing".
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

A context overflow was classified `CONTEXT_LENGTH`, whose recommended action is `COMPRESS`. `ErrorClassifier.is_retryable` counted `COMPRESS` and `FALLBACK_MODEL` as retryable, so `ResilientLLMAdapter` re-sent the same payload up to six times with backoff. The cascade then moved to other models, which failed the same way, and raised `AllModelsTrippedError`. The executor showed "check your OpenRouter credits". `ErrorClassifier.should_compact` and `should_fallback_model` had no callers.

## Decision

1. **Extend `ErrorCategory`, do not add a parallel enum.** New categories: `PAYLOAD_TOO_LARGE`, `MULTIMODAL_UNSUPPORTED`, `RATE_LIMIT_UPSTREAM`, `QUOTA_EXHAUSTED`, `TOOL_SCHEMA_REJECTED`. `RecoveryAction` gains `STRIP_MEDIA` and `LARGER_CONTEXT_MODEL`.
2. **Policy is pure.** `weebot/core/recovery_ladder.py` holds `LADDERS` (category to ordered rungs) and `plan_recovery(category, attempt)`, which returns the next untried rung or `None`. Each rung runs at most once per call, so the ladder ends.
3. **`is_retryable` excludes `COMPRESS`.** The adapter no longer re-sends an overflowing payload. `FALLBACK_MODEL` (404/503) stays retryable, since a 503 is often transient; a rejected tool schema is `ESCALATE`, so it is not retried either.
4. **The cascade types its terminal error.** `terminal_error` (`executor/_recovery.py`) raises `RecoverableLLMError` (a subclass of `AllModelsTrippedError`) when a failure in the cascade has a ladder category, carrying `category` and any `Retry-After`. `_cascade.py` changes by one line, since it is at the 800-line cap.
5. **The executor performs the rung.** `call_with_recovery` wraps the cascade call in `next_turn`: compress (`ContextCompressor.force_compress`), prune old tool outputs, strip images, or back off, then rebuild the messages and retry. A rung that changed nothing is not followed by a retry.
6. **One message per category** replaces the generic credits text (`failure_message`).

## Consequences

- An overflow now costs one compress and one retry, not six identical requests.
- `FALLBACK_MODEL` and `LARGER_CONTEXT_MODEL` rungs are planned but not performed: the cascade already tried its models, and a catalog lookup by window is not wired. They count as spent, so the user gets the precise message.
- `ExecutingState` skips replanning only for the "All models in the cascade have tripped" text (`_step_outcome.py:182`). Recoverable errors carry their own message, so a spent ladder can now replan.
- Tests that counted `ErrorCategory` and `RecoveryAction` members were updated; they were change-detectors.
