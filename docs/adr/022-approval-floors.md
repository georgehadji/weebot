# ADR-022: Approval floors that no mode can lower

**Date:** 2026-11-04
**Status:** Implemented 2026-11-04 as part (a) of plan H18 (`tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "continue". Parts (b) scopes, (c) guardian, (d) denial breaker and (e) unattended are not built.
**Owner:** weebot maintainers
**Supersedes:** N/A (the plan calls this ADR-021; that number is the loop-guardrails ADR)

---

## Context

`AutoApproval` grants every ASK in AUTO execution mode (`_step_run.py`), so a destructive command that only asked, such as `rm -rf ~`, ran unasked once the user chose AUTO. Nothing existed that AUTO could not bypass. H17 (tool RPC from a kernel) needs such a floor before code can call `bash` unattended.

## Decision

1. **`core/approval_floors.py`** (pure): a `Floor` is `(id, matches(text), action, reason)`, `action` being `deny` or `human`. Built-ins: recursive delete of a filesystem or drive root (`deny`) or of the home directory (`human`); writes to `.ssh`, `.aws`, `.gnupg` or a `.env` (`human`); force push to `main` or `master` (`human`); disk format and partition commands (`deny`); registry key deletes (`human`); download-and-run (`human`); turning off Defender or the firewall (`human`). `WEEBOT_APPROVAL_DENY_GLOBS` adds `deny` floors from user globs.
2. **`FloorGuard`** in `tool_guards.py`, first in `default_guard_chain`, for the shell tools. It reads every variant from `command_variants`: the text as written, without PowerShell backticks, without quotes and backslash-before-letter, and with any base64 run decoded (`bash_security.decode_base64_text`, as the analyzer does).
3. **`GuardAction.HUMAN`** sits between ASK and DENY. `GuardedTool` hands it to the approval channel like an ASK, with `ToolCallApproval.human_only=True`. `AutoApproval` does not grant a `human_only` request: it answers PENDING unless a human grant exists, so the flow pauses (`_step_run.py` pauses on a `human_only` `ToolApprovalEvent` even in AUTO). `DenyApproval` refuses it, so cron, webhooks and MCP still refuse.
4. The prompt, the event and the pending payload carry `human_only`; a "yes" records the usual single-use grant, which AUTO then spends on the rerun.

## Consequences

- A floor is a text match, not a parser. A command built at run time (`$x = 'r' + 'm'; & $x ...`) meets no floor; the analyzer and the approval policy still see it, as before.
- `python_execute` code and the file tools are not read. A floor on `shutil.rmtree(os.path.expanduser("~"))` or a `file_editor` write to `~/.ssh` is not built.
- `.env` matches any file with that exact name, not only the one at the Weebot root, so editing a project's `.env` in AUTO mode now pauses.
- `GuardAction.DENY` changed from 2 to 3. Nothing stores the number.
- **Not built:** scopes (`once | session | always`), the guardian, the denial breaker, `ApprovalChannel.UNATTENDED`. The plan's unattended case assumes a gateway "with no human approver bound"; the code has no such binding (cron and webhooks already refuse through `DenyApproval`), so it needs a decision first.

## Part (d): denial breaker

Added 2026-11-04, under the user's instruction "proceed". A refused tool call now carries `data["approval_denied"]` (`tool_approval.DENIAL_DATA_KEY`): the refusal of an ASK (`denied_result`) and a DENY verdict from the guard chain. `ToolBatchRunner._denial_loop`, beside `_policy_error_loop`, counts them in `DenialBreaker` (`tool_approval.denial_breaker()`, a process singleton like the grant store): 3 in one step, or 6 in one session, ends the step with an `ErrorEvent` and a `WaitForUserEvent` that quotes the last refusal and says how to go on. A trip clears the session's counts, so the next refusals start a new tally; the counts are dropped when a session completes or is deleted.

- The plan says the step stops with `StepStatus.BLOCKED`; no such status exists, so the step ends the way `_policy_error_loop` ends one (loop error plus a question for the person).
- The plan says "a DI singleton"; the grant store and the journal are module singletons in `tool_approval.py`, so the breaker is too.
- `_policy_error_loop` already stops three same-class policy errors in a row, but approval refusals match none of its classes, and a success resets it; the breaker counts refusals across a whole step.
- The guardian's refusal (part c) is a separate branch; it needs the same marker once both land.
