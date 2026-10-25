---
round: 1
cleared_count: 13
purpose: >-
  Round 2 Phase 2 exclusion list. Do not regenerate a candidate whose ID and
  location appear here; the innocence defence was recorded in round 1 and
  remains valid unless the code at that location has changed.
verification_wave: W12
---

# Defect Hunt V7.1 — Round 1 Cleared-Candidate Register

This register lists the 13 **cleared** candidates from round 1 (September 2026), extracted from `tasks/audits/candidates.yml`.

**Purpose:** Per §4.2 of `defect_hunt_v7_1_execution_plan.md`, Phase 2 of each wave must not regenerate a candidate that was cleared in round 1, *unless* the code at that location has changed since round 1.

**Verification:** Wave 12 (seams and programme close) re-verifies each defence listed here by checking:
1. The code at the recorded location
2. Whether it has changed since September 2026
3. Whether the innocence defence still holds

If the location has changed or the defence no longer applies, Wave 12 regenerates the candidate and investigates it under round 2 protocol.

## Cleared Candidates (13 total)

### Wave 1 — Security & Trust Boundary (5 cleared)

**D4** — `weebot/core/egress_guard.py`
- **Claim:** EgressGuard `None` leaves egress ungated
- **Defence (W1):** Defended, not proven innocent. Requires DI resolution *and* a bare `EgressGuard()` to both raise. W1 recorded this as [HYP], cleared by reasoning rather than by an executable trigger.
- **Status:** CLEARED (reasoning)

**D5** — `weebot/tools/bash_tool.py`
- **Claim:** Analyzer exception falls back to a weaker legacy check
- **Defence (W1):** Defended: BashGuard still runs independently at bash_tool.py:395, so the degrade is not to "no check". Cleared by reasoning, [HYP] not [VF].
- **Status:** CLEARED (reasoning)

**D9** — `region R6 — secret classification & event sanitisation`
- **Claim:** (not recorded — W1 names only the region, never an individual claim)
- **Defence (W1):** Full test coverage added: `tests/unit/core/test_every_event_field_is_sanitised.py`
- **Status:** CLEARED (test coverage)

**D10** — `region R6 — secret classification & event sanitisation`
- **Claim:** (not recorded — W1 names only the region, never an individual claim)
- **Defence (W1):** Same test as D9: `tests/unit/core/test_every_event_field_is_sanitised.py`
- **Status:** CLEARED (test coverage)

**D54** (from Perimeter audit P1) — `weebot/core/bash_guard.py:517`
- **Claim:** The security-event callback is invoked under `except Exception: pass`, so an audit record for a DANGEROUS command can be lost silently
- **Defence (P1):** Defence not recorded in candidates.yml
- **Status:** CLEARED (reason unknown — re-verify in W12)

### Wave 2 — Interfaces (3 cleared)

**D17** — `weebot/application/services/verifier_scorer.py:84`
- **Claim:** Bare `json.loads(response.content)` fails open
- **Defence (W2):** Defence not recorded in candidates.yml
- **Status:** CLEARED (reason unknown — re-verify in W12)

**D18** — `weebot/models/structured_output.py:430`
- **Claim:** Any failure produces an empty distribution
- **Defence (W2):** Defence not recorded in candidates.yml
- **Status:** CLEARED (reason unknown — re-verify in W12)

**S2** — `weebot/models/structured_output.py`
- **Claim:** `parse_agent_output` never raises, so a caller cannot distinguish "the model reported PARTIAL" from "we failed to parse"
- **Defence (W2):** Defence not recorded in candidates.yml
- **Status:** CLEARED (reason unknown — re-verify in W12)

### Wave 3 — Flows (3 cleared)

**D20** — `weebot/application/flows/plan_act_flow.py:712`
- **Claim:** Terminate-with-next-step returns without `set_state`, so `prompt_consumed` is never reset
- **Defence (W3):** Test coverage added: `tests/unit/application/flows/test_a_state_gets_the_value_it_asks_for.py`
- **Status:** CLEARED (test coverage)

**D22** — `weebot/application/flows/states/reviewing.py`
- **Claim:** `else: # "reject"` silently marks any unrecognised verdict FAILED
- **Defence (W3):** Defence not recorded in candidates.yml
- **Status:** CLEARED (reason unknown — re-verify in W12)

**D24** — `weebot/infrastructure/event_bus.py`
- **Claim:** `subscribe`/`unsubscribe` mutate `_handlers` without `self._lock`
- **Defence (W3):** Test coverage added: `tests/unit/test_w3_flow_state_and_subscription.py`
- **Status:** CLEARED (test coverage)

### Wave 6 — Application Services (1 cleared)

**D50** — `weebot/interfaces/web/event_broadcaster.py`
- **Claim:** Events without `session_id` broadcast to all global connections
- **Defence (W6):** Test coverage added: `tests/unit/interfaces/web/test_d50_event_scope_routing.py`
- **Status:** CLEARED (test coverage)

### Perimeter Audit P2 (1 cleared)

**D58** — `weebot/config/model_registry.py (deleted)`
- **Claim:** `get_cheapest_model_for_task` silently accepts any capability name it does not recognise, so an unsupported or misspelled requirement filters nothing
- **Defence (P2):** Cleared 2026-09-26 as no longer applicable, after having been fixed
- **Status:** CLEARED (code deleted / fixed)

## Usage in Wave Phases

**Phase 2 (Candidate Generation):** For each candidate generated, check:
1. Does the ID match any in this register? (unlikely, round 2 uses `H<wave>.<n>`)
2. Does the **location** match any cleared candidate's location?
3. If yes: has the code at that location changed since September 2026?

If location matches and code is unchanged: **skip** (do not regenerate). If code has changed: **regenerate** with a new round 2 ID.

**Wave 12 Re-verification:** For each of the 13 cleared candidates:
1. Locate the code (or confirm deletion for D58)
2. Check git history: has it changed since September 5, 2026?
3. If changed: re-investigate under round 2 protocol
4. If unchanged and defence is reasoning-based (D4, D5, D17, D18, S2, D22, D54): verify the reasoning still holds
5. If unchanged and defence is test-based (D9, D10, D20, D24, D50): verify the test still exists and passes

---

**Register Status:** ACTIVE for round 2
**Source:** `tasks/audits/candidates.yml` (round 1, status: cleared)
**Last Updated:** 2026-10-25 (Wave 0)
