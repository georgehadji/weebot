# ADR-023: The memory snapshot is read once per session

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H24a, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "proceed".
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`build_step_prompts` called `PersistentMemoryTool.load_snapshot` at every step and appended the result to the system prompt. A memory write by any session therefore changed the prompt prefix of every running one, so a provider's prompt cache could not hold (H10 needs a stable prefix). The consolidated user profile was also added twice for `full` and `creative` steps: once by the prompt builder and once by `_step_setup.py`.

## Decision

1. **`MemorySnapshotCache`** (`application/services/memory_snapshot_cache.py`) is a DI singleton under the typed key `MEMORY_SNAPSHOT_CACHE`. It keeps the snapshot text per session id in a bounded LRU (256 sessions). The first step of a session reads the files; later steps get the same string.
2. **The executor asks for its own session**: `memory_snapshot` now takes the session id, and the container passes `cache.get`.
3. **A write still goes to disk at once.** The tool's result says `Saved; it is in context from the next session.` The model sees its own write in the result, so nothing is lost inside the session. With the freeze off the note is left out.
4. **A session delete forgets the entry**, through `_session_stores()`.
5. **Flag** `WEEBOT_MEMORY_SNAPSHOT_FREEZE`, default on. Off restores the read at every step.
6. **One profile block**: the one in `_step_setup.py` and its loader `_load_user_profile` are deleted. The prompt builder's block, which has the same scope rule, stays.

## Consequences

- The memory text in the system prompt no longer changes inside a session.
- Two sessions running at once may hold different snapshots; each is internally stable.
- An executor built without a session id uses the id `unknown`, so such runs share one entry until the process ends or the entry is dropped.
- The consolidated profile is still read from the state repo at every step by the prompt builder, so it can change inside a session. It is not part of this change.
