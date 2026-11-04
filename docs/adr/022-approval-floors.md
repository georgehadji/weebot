# ADR-022: Approval floors that no mode can lower

**Date:** 2026-11-04
**Status:** Implemented 2026-11-04 as parts (a) floors, (b) scopes and (c) guardian and (d) denial breaker of plan H18 (`tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instructions "continue" and "proceed". Part (e) unattended is not built.
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
5. **Scopes (part b).** `core/approval_scopes.py` (`ScopedGrants`, `command_pattern`). A reply of `session` or `always` to an ASK covers every later call with the same *command pattern* (argv[0], its subcommand, its flags without values: `npm test --silent` -> `npm test --silent`). `session` lives in memory per session; `always` is kept in `~/.weebot/approvals.json`, written atomically. Only the verdict "no approval rule covers this command" (`ExecApprovalPolicy._default_ask`, `GuardVerdict.scopable`) can be scoped, and only when it is the deciding verdict, the tool is a shell tool and the line is one plain command (no `;`, `&`, `|`, redirect or substitution). So DANGEROUS commands, floors, egress and the untrusted-content gate (D5) never carry a pattern: D5 asks as its own request, so a scope cannot skip it. The console prompt offers `[s]` and `[a]`; the flow prompt takes `session` and `always`. A covered call is journaled as `approval_granted` with channel `scope_session` or `scope_always`.
6. **Guardian (part c).** `GuardianPort.review(command, step_description) -> approve | deny | escalate` (`application/ports/guardian_port.py`), implemented by `LLMGuardianAdapter` (`application/services/llm_guardian.py`) on the `verifier` role tier. It is shown the command and the step description and nothing else, so no tool output reaches it, and the reply is validated by a pydantic model; a model error, an empty or malformed reply, an unknown verdict or a command over 2000 characters is `escalate`. `GuardedTool._resolve_ask` asks it only for a request that carries a scope pattern (so never DANGEROUS, a floor, egress or the untrusted-content gate), only when the executor said the session is untainted (`approval_scope(tainted=...)`; unknown counts as tainted), and never when a scope already covers the call. `approve` runs the call, `deny` refuses it, `escalate` goes to the approval channel as before; each is journaled with channel `guardian`. `WEEBOT_APPROVAL_GUARDIAN`, default off; the DI key `APPROVAL_GUARDIAN` is `None` while it is off, and the web and CLI entry points call `set_guardian`.

## Consequences

- A floor is a text match, not a parser. A command built at run time (`$x = 'r' + 'm'; & $x ...`) meets no floor; the analyzer and the approval policy still see it, as before.
- `python_execute` code and the file tools are not read. A floor on `shutil.rmtree(os.path.expanduser("~"))` or a `file_editor` write to `~/.ssh` is not built.
- `.env` matches any file with that exact name, not only the one at the Weebot root, so editing a project's `.env` in AUTO mode now pauses.
- `GuardAction.DENY` changed from 2 to 3. Nothing stores the number.
- A pattern ignores the words after the subcommand, so `npm run build` and `npm run deploy` share `npm run`; a flag before any subcommand with a positional after it (`python -m pytest`) gets no pattern. Flags are part of the pattern, so `npm test --silent` is a different pattern from `npm test`.
- `always` is one file for the machine, not one per profile as the plan says; there is no profile-aware home directory in the code. Session scopes are not dropped at session end (sessions are few and ids are not reused). The plan's `ApprovalScopedGrant` event is not added: the journal row above carries it.
- The guardian only sees what a scope could cover, which today is only the `WEEBOT_SHELL_DEFAULT_ASK=enforce` case ("no rule covers this command"); the default is `observe`, so with the flag on and that setting unchanged it is never called. The plan's "one SUSPICIOUS-tier command" does not exist as an ASK: `BashGuardAdapter` allows SUSPICIOUS and asks only for DANGEROUS. In AUTO mode the guardian runs before the grant, so it can refuse what AUTO would have run. It is one call per such command, with no cache.
- **Not built:** `ApprovalChannel.UNATTENDED`. The plan's unattended case assumes a gateway "with no human approver bound"; the code has no such binding (cron and webhooks already refuse through `DenyApproval`), so it needs a decision first.

## Part (d): denial breaker

Added 2026-11-04, under the user's instruction "proceed". A refused tool call now carries `data["approval_denied"]` (`tool_approval.DENIAL_DATA_KEY`): the refusal of an ASK (`denied_result`) and a DENY verdict from the guard chain. `ToolBatchRunner._denial_loop`, beside `_policy_error_loop`, counts them in `DenialBreaker` (`tool_approval.denial_breaker()`, a process singleton like the grant store): 3 in one step, or 6 in one session, ends the step with an `ErrorEvent` and a `WaitForUserEvent` that quotes the last refusal and says how to go on. A trip clears the session's counts, so the next refusals start a new tally; the counts are dropped when a session completes or is deleted.

- The plan says the step stops with `StepStatus.BLOCKED`; no such status exists, so the step ends the way `_policy_error_loop` ends one (loop error plus a question for the person).
- The plan says "a DI singleton"; the grant store and the journal are module singletons in `tool_approval.py`, so the breaker is too.
- `_policy_error_loop` already stops three same-class policy errors in a row, but approval refusals match none of its classes, and a success resets it; the breaker counts refusals across a whole step.
- The guardian's refusal (part c) carries the same marker, so it counts too.
