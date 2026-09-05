# B1 — the candidate inventory becomes data

Execution record for phase B1 of
[`review_gate_and_residual_work_plan.md`](../specs/review_gate_and_residual_work_plan.md) §3.1.

**Baseline:** `836e70a1` (D47/D50). 3847 passing.

The candidates lived as Markdown tables across nine audit files. Readable, but
not checkable: nothing counted them, nothing stopped one being quietly dropped,
and answering *"what is still open?"* meant re-reading nine documents — which is
literally what happened the last time the question was asked.

`tasks/audits/candidates.yml` is now the source of truth; the audits keep their
narrative. `tests/unit/test_candidate_inventory.py` enforces that the two agree.

---

## What the inventory says

| status | count | |
|---|---|---|
| `fixed` | **22** | verified and repaired, each naming a proof test |
| `deferred` | **19** | read, consciously set aside, reason recorded |
| `cleared` | **6** | investigated, innocence established |
| `open` | **5** | generated, never investigated |
| **total** | **52** | |
| **not closed** | **24** | `open` + `deferred` |

## Two things the conversion surfaced immediately

**1. The prose count had lost a candidate.** The plan's Appendix B listed 25
uninvestigated. The inventory reports 24 not closed, and it reconciles exactly:

```
25  Appendix B
 -2  D47 fixed, D50 cleared
 +1  D13
 = 24
```

`[VF]` **D13** — *"an evaluator exception yields score=1.0, passed=True"* — was
omitted from Appendix B because W2 triaged it **PARTLY DEFENDED** rather than
leaving it uninvestigated. But W2 did not resolve it: it escalated the policy
question (its own R-2) and changed nothing. A candidate that was looked at and
left unresolved is not a closed candidate, and prose counting dropped it because
it did not fit either bucket cleanly. The data model has a bucket for it.

**2. The numbering has holes nobody noticed.** `[VF]` **D1, D2 and D7 appear
nowhere in the audits** except inside the range label *"Entry material is §7.3
D1–D12"*. Either they were generated and never written down, or the numbering
simply began at D3 and the label was loose. **Prose-based tracking cannot tell
which** — and that is this file's justification in one sentence.

They are recorded in `meta.numbering_gaps` rather than invented as records. The
escape hatch is itself guarded: a test asserts that anything listed as a gap
really has no claim anywhere, so `numbering_gaps` cannot become a way to hide a
live candidate from the check that matters.

---

## The gate

Five assertions, each proven to fail on the drift it exists to catch:

| Drift introduced | Caught |
|---|---|
| Delete a candidate the audits mention | ✅ |
| Mark one `cleared` with no `verdict_note` | ✅ |
| Mark one `fixed` with no `evidence` | ✅ |
| Point `evidence` at a test file that does not exist | ✅ |
| Hide a real candidate inside `numbering_gaps` | ✅ |

The direction that matters is the first: **the audits are checked against the
inventory, not trusted.** Without it the inventory could drift into an
optimistic subset of reality, which is the exact failure this exercise exists to
prevent — a fail-open control over the record of fail-open controls.

`[VF]` **The gate found two flaws in its own first outing**, which is the best
evidence available that it is not decorative:

1. The id regex matched `D1` inside the range `D1–D12`, so a genuine range label
   read as a claim. Fixed with a lookahead that drops the opening half of a
   range; the closing half still matches, correctly, because D12 is real.
2. On the first full-suite run it failed on **this file** — the audit naming
   D1, D2 and D7 in order to explain that they have no claim was itself read as
   a claim. `residual_b1_inventory.md` is now excluded from the scan, for the
   stated reason that it is the document *about* the inventory. Candidate claims
   are not written here, so the exclusion costs nothing.

Both fixes are recorded where the code lives rather than only in a commit
message.

The `fixed`-record evidence rule is not decorative. A fix claim is only as good
as the proof test behind it, and a renamed test file would otherwise leave 22
claims standing with nothing underneath.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` Range labels (`D1–D12`), bandit codes (`B110`) and ruff codes (`S110`, `E501`) are all excluded from id matching, each for a stated reason. The two-digit bound is what keeps `S110` out. |
| **Invalid input** | `[VF]` Missing required fields, unknown status values and duplicate ids each fail with a named record. An `open` record carrying a `verdict_note` is flagged as contradictory rather than ignored. |
| **State** | Not applicable — the gate is a pure read of two file sets. |
| **Regression** | `[VF]` Full suite 3847 → **3858** passed / 0 failed. Nothing outside `tasks/audits/` and `tests/` is touched; no production code changed in this phase. |
| **Concurrency** | Not applicable. |
| **New defects** | `[HYP]` The inventory's `status` for the 41 candidates not touched this session was transcribed from the audits by reading them. A transcription error would be invisible to the gate, which checks that ids and notes *exist*, not that a status is *right*. The claims and locations carry the same risk. |

---

## Phase 8 — coverage & residual risk

### Not covered

- **No candidate was investigated in this phase.** B1 makes them countable and
  keeps them countable. It fixes nothing. The 24 not-closed records are exactly
  as unresolved as they were before, and the plan says so explicitly (§6: *"It
  does not fix the 25 candidates"*).
- **The summary is not regenerated into the audits.** The plan's §3.1 item 4
  asked for the count to be *"regenerated into the audits"*; it is printed by
  the test run instead. Writing generated content back into hand-written audit
  files would put a machine in charge of documents whose value is that a person
  reasoned in them — a trade not worth making for a number that a build already
  prints.
- **The `claim` and `location` fields were transcribed, not re-derived.** They
  say what the audits say. Where an audit never recorded a claim — D9 and D10,
  under region R6 — the inventory records that absence rather than inventing
  one.

### Residual risks

- **R-1 — the gate checks structure, not truth.** It cannot tell a wrong
  `status` from a right one; only that every id is present, every dismissal has
  a reason, and every fix claim points at a file that exists. A mis-transcribed
  verdict survives it.
- **R-2 — `meta.numbering_gaps` is a hole by design.** It is guarded (a gap must
  have no claim anywhere), but a future candidate generated and never written
  into any audit would be invisible to both the audits and the gate. Nothing can
  check for a document that was never written.
- **R-3 — two sources of truth still exist for statuses.** The audits' verdict
  columns and the inventory's `status` field can disagree, and only the *ids*
  are cross-checked. Parsing verdicts out of prose tables was considered and
  rejected as too brittle to be a blocking gate.

### Verdict

**COMPLETE.** The inventory exists, it is enforced in both directions, every
assertion is proven against the drift it guards, and the conversion immediately
paid for itself by finding a lost candidate (D13) and three numbering holes
(D1, D2, D7) that nine waves of prose had not surfaced.
