# AgeMem (Agentic Memory) vs weebot — analysis and proposed changes

Paper: *Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for
LLM Agents* (Yu et al., Wuhan Univ. / Alibaba, arXiv:2601.01885v3).
Date: 2026-08-11. Scope: what is worth porting into weebot, what is not, and three
verified bugs found while checking weebot against the paper's design.

---

## 1. What the paper actually claims

Six memory operations are exposed to the agent as **tools inside its action space**,
rather than run by an external memory manager on a schedule:

| Tool | Target | Effect |
|---|---|---|
| `ADD` / `UPDATE` / `DELETE` | LTM | mutate the persistent store (`UPDATE`/`DELETE` require a `memory_id` obtained from a prior retrieval) |
| `RETRIEVE` | STM | pull top-k semantically similar LTM entries into the live context |
| `SUMMARY` | STM | LLM-compress a span of the conversation in place |
| `FILTER` | STM | drop context messages whose cosine similarity to a criteria string exceeds θ_f (default 0.6) |

Training is three-stage progressive RL with step-wise GRPO: the terminal reward is
broadcast to every earlier step, so a storage decision made in Stage 1 is credited by
the Stage-3 task outcome. Composite reward = task + context + memory:

- `R_compression = max(0, 1 − T_used/T_max)`
- `R_preventive = 1[a context-reduction tool fired **before** overflow]`
- `R_preservation = 1[key entities of the query still present at answer time]`
- `R_storage = N_high_quality / max(1, N_total)` (LLM-judged)
- `R_maintenance = 1[an update or delete happened]`
- `R_relevance = LLM score of retrieved memories vs query`
- penalties: −1 rounds exceeded, −0.5 context overflow

**Honest read of the results.** The headline gain comes from RL, not from the tool
interface. Table 2: AgeMem-noRL averages 33.43 vs Mem0 37.14 on Qwen2.5-7B — i.e.
untrained tool-based memory is *worse* than trigger-based memory like Mem0. RL adds
~8.5 points. What is portable without RL is (a) the operation set, especially
`RETRIEVE` and `FILTER`, and (b) the reward decomposition reused as **runtime guards
and offline metrics**. The token savings from STM tools are modest (3.1–5.1%,
Fig. 3) and should not be the reason to adopt anything.

---

## 2. weebot's memory system as it stands

| AgeMem op | weebot equivalent | verdict |
|---|---|---|
| `ADD` | `persistent_memory action=add` (`weebot/tools/persistent_memory.py:162`) | present |
| `UPDATE` | `action=replace`, substring match | present, **unsafe** (§3.2) |
| `DELETE` | `action=remove`, substring match | present |
| `RETRIEVE` | **none** — `read_snapshot()` dumps *all* of AGENT.md + USER.md into the system prompt (`filesystem_memory.py:48`, injected at `executor/_base.py:460-467`) | **missing** |
| `SUMMARY` | `ContextCompressor._maybe_compress` at 75% of window (`executor/_context_compressor.py:78`) + `ConversationCompressor` (head 3 / tail 6, cheap model) | present, preventive |
| `FILTER` | **none** | **missing** |

Adjacent machinery weebot already has:

- `LocalEmbeddings` (sentence-transformers all-MiniLM-L6-v2, local, free) via
  `weebot/qmd_integration/embeddings.py`
- `VectorStorePort` + `NumpyVectorStore`, already used by `SemanticSkillRetriever`
- `ConstraintExtractor` re-injection after compaction (`memory_compactor.py:132`) —
  a working precedent for the paper's `R_preservation`
- `MemoryLifecycleService` hot/warm/cold sweep + `salience_scorer`
- `MemoryCompactor`, which truncates oversized shell/screenshot tool results

So the pieces exist. The gaps are **retrieval over memory**, **filtering of context**,
and — more urgently — three places where existing memory plumbing is broken or dead.

---

## 3. Fixes (do these first; they are bugs, not features)

### 3.1 `upsert_memory_metadata` arity mismatch — kills two features silently

`SQLiteStateRepository.upsert_memory_metadata(self, entry_hash, entry_text, source="agent")`
(`sqlite_state_repo.py:423`) takes no `salience`. Two callers pass one:

- `weebot/tools/persistent_memory.py:141` — positional 4th arg, swallowed by
  `except Exception: pass` (line 144). **No salience metadata is ever written for any
  memory entry.** `compute_salience()` and the whole `MemoryLifecycleService.sweep()`
  eviction path therefore operate on an empty table.
- `weebot/application/services/user_model_consolidator.py:65` — `salience=1.0`
  keyword, swallowed by `except Exception` at line 72. **The consolidated user profile
  is never stored**, so the reader at `executor/_base.py:423` and
  `executor/_prompt_builder.py:106` always finds nothing and the "User Profile" block
  never reaches the system prompt.

Verified by signature binding:

```
repo sig: (self, entry_hash: str, entry_text: str, source: str = 'agent') -> None
4-arg call FAILS -> too many positional arguments
```

Fix: add `salience: float | None = None` through `state_repo_port` → `sqlite_state_repo`
→ `_memory_metadata_repo.upsert` (the SQL already hardcodes `0.5` on insert and
`MIN(1.0, salience + 0.05)` on conflict; honour an explicit value instead when given).

Second half of the same bug: even with the write fixed, the read is wrong.
`get_low_salience_entries(threshold=1.01, limit=5)` is used as "fetch all", but it is
`ORDER BY salience ASC LIMIT 5` — a pinned `salience=1.0` profile sorts **last** and
will not be returned once five lower-salience entries exist. Needs a direct
`get_memory_entry(entry_hash)` lookup.

This is exactly the paper's `R_maintenance` axis: weebot has an LTM maintenance
pipeline that has never run.

### 3.2 `_replace` clobbers every substring match

`weebot/tools/persistent_memory.py:176-193`:

```python
for i, e in enumerate(entries):
    if match in e:
        entries[i] = new_entry     # every match becomes the SAME text
        replaced += 1
```

A `match` hitting three entries silently overwrites all three with one identical
string — memory loss plus triple duplication, reported to the agent as success. The
paper avoids this by requiring a `memory_id` obtained from a prior `RETRIEVE`.

Lazy fix (no id infrastructure needed): fail closed when `match` hits more than one
entry, returning the candidates so the agent can disambiguate. Becomes unnecessary
once §4.1 lands and entries carry stable ids.

### 3.3 A never-executed turn-boundary compression block

**Corrected 2026-08-11.** An earlier revision of this section claimed
`self._compactor = MemoryCompactor()` at `plan_act_flow.py:182` was dead. It is not:
`states/executing.py:607` consumes it as `context._compactor.compact_session(...)` after
every non-terminal step. Deleting the field would raise AttributeError on every step of
every task. The original grep covered only `plan_act_flow.py`.

The real dead code is the turn-boundary block at `plan_act_flow.py:758-829`, which has
**never executed once**. It constructs `MessageEvent(role="system")`, but `event.py:78`
declares `role: Literal["user", "assistant"]`, so pydantic raises ValidationError at
:806 on every invocation — swallowed by the block's bare `except Exception` →
`logger.debug` at :828-829. The session assignment at :816 is unreachable. The cost is
still paid: `mgr.prepare()` at :778 runs a full token count and the entire
`LossyContextCompressor.compress()` pass before the line that raises.

Fix: delete the block. Per-step compaction already runs at `executing.py:607` on the same
session lineage, and making the block work would add a fourth event-replacement site to a
system where `save_session` is a full-row overwrite. See
[agentic_memory_fix_plan.md](agentic_memory_fix_plan.md) §6.

---

## 4. Additions worth making

### 4.1 `retrieve` action on `persistent_memory` + a capped snapshot — highest value

Today every executor step pays for the entire AGENT.md and USER.md in its system
prompt, unranked and uncapped, and (because of §3.1) nothing ever evicts. This is
precisely the "static STM" arrangement the paper argues against, and unlike the
paper's contribution it needs no training to fix.

Reuse what exists: index `§`-delimited entries with `LocalEmbeddings` into a
`NumpyVectorStore` — the same two components `SemanticSkillRetriever` already uses —
and add `action="retrieve", query=..., top_k=3` to the existing tool. Roughly 40
lines, no new dependency.

Keep the frozen snapshot (it protects the prefix cache — a real property worth
keeping, documented at `persistent_memory.py:6-11`), but cap it: inject only USER.md
plus the top-N most salient AGENT.md entries, and let the agent pull the rest on
demand. Retrieval happens through a tool call, so it never invalidates the prefix.

Side effect: retrieval results give `UPDATE`/`DELETE` real entry ids, which retires
§3.2 properly.

### 4.2 Post-compaction preservation check (`R_preservation`)

After `ContextCompressor._maybe_compress` and after the flow-level compression, verify
that the current step's key anchors — identifiers, file paths, numbers extracted from
`step.description` — still appear in the retained context; if any vanished, append one
short system line restating them. `MemoryCompactor._inject_constraints` is the exact
precedent, applied to constraints rather than task entities. ~20 lines, and it
guards the failure mode the recent step-evidence work (LongHorizon-Harness E1–E7)
otherwise only catches after the step has already gone wrong.

### 4.3 A `filter_context` STM tool

weebot's context is dominated by tool output, not dialogue — a single failed grep or
HTML fetch can outweigh the whole conversation. `SUMMARY` pays an LLM call to compress
noise that should simply be dropped. A tool that lets the agent prune its own buffer by
criteria (cosine similarity against the executor's deque, θ ≈ 0.6 per Table 5, which is
flat across 0.4–0.8) is the STM operation weebot is most obviously missing. Requires
wiring the tool to the buffer owned by `ContextCompressor`; medium effort, so it comes
after 4.1.

### 4.4 Optional: memory quality as a scheduled job (`R_storage`)

The paper's MQ metric needs ground truth weebot does not have, but the cheap proxy
runs fine: periodically LLM-judge each AGENT.md entry for "specific, reusable,
non-obvious", then merge or drop the bottom. `scheduling/default_jobs.py` already
hosts the lifecycle sweep, and the budget model tier makes it near-free. This is what
keeps LTM from rotting without RL. Speculative relative to 3.x and 4.1 — do it last, if
at all.

---

## 5. Explicitly not recommended

**Do not port the three-stage GRPO training.** It needs a trainable local policy;
weebot orchestrates API models. And per §1 the untrained tool interface does not beat
trigger-based memory on the paper's own numbers, so copying only the interface buys
little. weebot already has LTM tools — the value here is retrieval, filtering, the
preservation guard, and the three broken paths in §3.

---

## 6. Suggested order

Superseded by [agentic_memory_fix_plan.md](agentic_memory_fix_plan.md), which sequences the
same work against the repo's actual CI gates, layering contracts, and two pre-existing test
failures. Notable revisions after deeper verification:

- §4.1's retrieval as sketched is **illegal** — `weebot/tools/` may not import
  `numpy_vector_store` (`.importlinter:31-36`), and the repo-wide exemption budget has two
  slots left. It needs a port + adapter + DI factory.
- §3.1 is a **regression**, not a missing feature: `salience` was dropped from the signature
  by commit `5327746`, and `memory_metadata` is not empty (7 live rows at 0.22).
- §4.2's "mirror `_inject_constraints`" is unsafe — that mechanism re-injects secrets scraped
  from raw tool output into an assistant message, bypassing credential sanitization.
