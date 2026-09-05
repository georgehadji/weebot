# Wave 8 — Seams & Fix-Interaction

Execution record for W8. **Not a new surface** — a review of everything W1–W7 changed.

The plan's justification: *"Phase 5's fix-interaction check is per-wave; nothing in the protocol
checks interactions across waves. The repo has already paid for this gap once — B1 is a verified
case where a fix from one work item silently disabled the proof test of another."*

**It paid for it again. This wave found one.**

---

## The finding: my own W3 fix regressed the thing it was fixing

Wave 3 repaired `AsyncEventBus.unsubscribe`, which could never remove a `subscribe_by_type`
handler. The replacement compared with `is`:

```python
if registered is handler or getattr(registered, "_wrapped_handler", None) is handler:
```

The original was `if handler in self._handlers`, which compares with `==`.

**Callers pass bound methods.** `weebot/interfaces/web/main.py:194` subscribes
`broadcaster.publish` and `:304` unsubscribes it at shutdown. Python builds a *new* bound-method
object on every attribute access, so:

```
b.publish is b.publish  ->  False
b.publish == b.publish  ->  True
```

Measured on the W3 code: subscribe a bound method, unsubscribe it, publish — **1 handler
remaining, 1 event delivered to the supposedly-detached broadcaster.**

So the W3 fix — whose entire purpose was to make `unsubscribe` actually remove things — silently
stopped removing the one handler the web app unsubscribes in production. Narrower than the defect
it replaced (that one leaked *every* `subscribe_by_type` handler), but a real regression, and one
no wave-local review would have caught: W3's own tests all used module-level `async def` handlers,
which *are* identical to themselves.

**Fixed:** compare by equality, restoring the original semantics while keeping the wrapper match.
Two regression tests added, both asserting the premise (`b.publish is not b.publish`) so they
cannot silently stop testing anything.

---

## Cross-wave checks performed

| Check | Result |
|---|---|
| Every wave's proof tests run together | **185 passed** |
| W1 `D11` trigger re-run | 0 fired |
| W2 trigger re-run | 0 fired |
| W4 trigger re-run | 0 fired |
| W3 `D24` statistical harness re-run against the twice-changed `unsubscribe` | 200 + 200 trials, **0 failures** |
| Full suite | see below |

### Cleared candidates re-verified — innocence can be invalidated by a later change

| Candidate | Cleared in | Still innocent? |
|---|---|---|
| **D22** — unrecognised review verdict marks a step FAILED | W3 | ✅ `verdict` is still `Literal["approved", "revise", "reject"]`; Pydantic still rejects `"approve_with_comments"` |
| **D17** — `verifier_scorer` fails open | W2 | ✅ still a bare `json.loads(response.content)`, so still fails **closed** |
| **`knowledge` is not external content** | W1 | ✅ still neither fenced nor tainting, after the W1 follow-up split the two predicates |

---

## Interactions identified by reasoning, not measured

- **W2 × W5.** W2 made a failed compression a no-op, so a buffer grows under sustained LLM
  failure. W5 made cost accounting non-zero. Together, the cost of that growth is now *visible*
  rather than silent — a positive interaction, and the reason R-1 of W2 is worth watching.
- **W4 × W7.** W4 raised `busy_timeout` from sqlite's 5 s default to the configured 30 s. W7 now
  closes 37 previously-leaked connections promptly, reducing concurrent handles. These pull in
  opposite directions on lock contention: fewer open handles reduces it, a longer busy timeout
  makes any remaining contention block longer instead of failing fast. **`[HYP]` — not measured.**
- **W1 × W6.** W1 fenced and tainted external tool output; W6 closed a WebSocket subscription that
  ignored session ownership. W6's D50 (events lacking `session_id` broadcast to *all* global
  connections) was never investigated and may be the same exposure by another route — the W6 fix
  does not address it.
- **W3 × W6.** The SSE router subscribes a per-request closure and unsubscribes it, so
  "unsubscribe removes every registration" is a no-op difference there. `EventBrokerAdapter`'s
  one-handler-to-many-types case, where the change *would* be observable, **has no callers**.

---

## What W8 did NOT do

- **No new taxonomy sweep of changed regions.** The plan calls for re-running the full taxonomy
  against every region W1–W7 touched (Phase 6 vector 6 at programme scale). What was actually done
  is narrower: re-run the proof tests, re-verify the cleared candidates, and reason about pairs of
  fixes. A genuine re-sweep of 20 changed files against all nine defect classes was not performed.
- **The interactions above are reasoning, not triggers.** Only the bound-method regression was
  established by execution. W4 × W7's contention interaction in particular deserves a load test
  that was not written.
- **Nothing was checked against candidates that were never investigated.** A fix can change the
  reachability of a candidate nobody looked at; for the ~20 deferred candidates across the
  programme, that check is vacuous because there is no baseline to compare against.

---

## Verdict

**ACCEPT, with one regression found and fixed.**

The wave justified itself: without it, a fix that shipped green in W3, with passing proof tests
and green CI, would have left the production shutdown path silently failing to detach an event
subscriber. Both the W3 tests and CI passed *because* the tests used handlers that happen to be
identical to themselves — the defect lived precisely in the gap between the test's handler shape
and production's.

That is the same failure mode as B1, which motivated this wave, arriving by a different route.
