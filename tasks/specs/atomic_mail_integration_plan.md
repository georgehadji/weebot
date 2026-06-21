# Implementation Plan — Atomic Mail Agentic Integration into weebot

**Document version:** 1.0
**Date:** 2026-06-21
**Author:** Engineering (weebot)
**Status:** Proposed — pending approval
**Source research:** `atomic-mail-agentic-main/` evaluation vs. weebot capability audit

> **Note:** Saved here (not repo-root `implementation_plan.md`) to avoid overwriting the
> pre-existing, unrelated system-audit plan already at that path.

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Assessment](#2-current-architecture-assessment)
3. [Impact Assessment](#3-impact-assessment)
4. [Risk & Mitigation Matrix](#4-risk--mitigation-matrix)
5. [Detailed Implementation Plan](#5-detailed-implementation-plan)
6. [Task Breakdown Structure (WBS)](#6-task-breakdown-structure-wbs)
7. [Testing & Quality Assurance Strategy](#7-testing--quality-assurance-strategy)
8. [Deployment & Rollback Plan](#8-deployment--rollback-plan)
9. [Post-Implementation Validation Checklist](#9-post-implementation-validation-checklist)
10. [Appendix A — Engineering Practices Applied](#appendix-a--engineering-practices-applied)

---

## 1. Executive Summary

### 1.1 Objective
Integrate the **Atomic Mail Agentic** Python client (`atomic-mail-agentic-main/py/`) into weebot as a first-class agent tool, giving weebot agents the ability to **provision and operate their own email inbox** autonomously — register an `@atomicmail.ai` address, then send/receive/draft/search mail via JMAP — with zero human credential setup.

### 1.2 Why this adds real value (non-duplicative)
weebot already ships an `EmailAdapter` ([weebot/interfaces/gateways/email.py](weebot/interfaces/gateways/email.py)), but it is architecturally distinct and does **not** overlap:

| | Existing `EmailAdapter` (gateway) | Atomic Mail (proposed tool) |
|---|---|---|
| **Role** | Inbound/outbound *transport* (human ↔ agent) | Agent *capability* (agent ↔ world) |
| **Mailbox** | User's personal account | Self-provisioned, disposable agent inbox |
| **Setup** | Manual IMAP/SMTP creds in `.env` | PoW signup, ~30s, no human input |
| **Layer** | Interfaces (messaging channel) | Tools (a capability the agent wields) |

The integration unlocks net-new workflows — autonomous newsletter digests, async surveys, signup/verification email receipt during browser automation, sandboxed support inboxes — that compose with weebot's existing `schedule` and `advanced_browser` tools.

### 1.3 Facts that de-risk the work
- **Self-contained, pure-stdlib package** (~2,900 LOC, `py/src/atomicmail/`). **No new third-party dependencies** (`urllib`/`http`/`hashlib`/`secrets` only).
- **One clean seam:** `handle_tool_call(name, arguments) -> dict` ([mcp_server.py:153](atomic-mail-agentic-main/py/src/atomicmail/mcp_server.py)) already abstracts all three operations (`register`, `jmap_request`, `help`).
- **MIT licensed** — vendoring-compatible.
- **Mirrors an existing weebot pattern:** `ScheduleTool` ([weebot/tools/schedule_tool.py](weebot/tools/schedule_tool.py)) is a near-identical "delegate to a module function, map to `ToolResult`" shape.

### 1.4 Effort & recommendation
**~0.5–1 engineering day** (thin adapter tool + registry wiring + unit tests). **Recommendation: proceed, gated behind an opt-in feature flag** due to upstream Open Alpha status (100 MB quota, strict rate limits).

---

## 2. Current Architecture Assessment

### 2.1 weebot architecture (relevant slice)
Clean / Hexagonal Architecture; dependency rule `Interfaces → Infrastructure → Application → Domain` (inward only).

```
weebot/
├── domain/            # pure entities (Plan, Step, Session, Event)
├── application/       # flows, agents, skills, CQRS, ports
├── infrastructure/    # adapters (LLM, persistence, gateways)  ← vendor target
├── interfaces/        # CLI, Web/FastAPI, MCP, gateways/email.py
├── tools/             # BaseTool function-calling tools          ← tool target
└── core/              # bash_guard, model_cascade, circuit_breaker, approval_policy
```

**Tool subsystem (the integration point):**
- `BaseTool` (Pydantic) contract: `name`, `description`, `parameters` (JSON Schema), `async execute(**kwargs) -> ToolResult` ([weebot/tools/base.py:124](weebot/tools/base.py)).
- `ToolResult` provides `success_result(...)` / `error_result(...)` factories.
- `ToolRegistry._TOOL_CLASS_MAP` maps tool-name → class ([weebot/tools/tool_registry.py:370](weebot/tools/tool_registry.py)); role gates declare per-persona tool access (`automation`, `admin` at [tool_registry.py:48](weebot/tools/tool_registry.py)).
- MCP server auto-wraps any `BaseTool` for FastMCP ([weebot/mcp/server.py:164](weebot/mcp/server.py)).

### 2.2 Atomic Mail client architecture
```
py/src/atomicmail/
├── __init__.py        # public API surface
├── mcp_server.py      # handle_tool_call(name, args) -> dict   ← THE SEAM
├── session.py         # register(), create_agent_session()
├── jmap_request.py    # jmap_request() -> JmapRequestResult{ok,status,bodyText}
├── help.py            # help(topic)
├── config.py          # resolve_agent_config_from_env() — ATOMIC_MAIL_CREDENTIALS_DIR
├── credentials.py     # CredentialStore; files written mode 0600
├── pow.py / auth_http.py / jwt_utils.py  # PoW signup + auth
└── constants.py       # AUTH/API URLs from shared assets
```
- **Transport:** stdlib only.
- **Config:** env `ATOMIC_MAIL_CREDENTIALS_DIR` (default `~/.atomicmail`); credentials at mode `0600`.
- **Result contract:** `JmapRequestResult(ok: bool, status: int, bodyText: str)` ([jmap_request.py:60](atomic-mail-agentic-main/py/src/atomicmail/jmap_request.py)).

### 2.3 Technical-fit notes / debt
- Atomic Mail performs **synchronous blocking HTTP**; weebot tools are `async` → must wrap in `asyncio.to_thread`.
- Calls bypass `bash_guard` (not shell) — but **inbound email is untrusted input** and must not be auto-executed (primary security concern; mitigated via `approval_policy`).
- Upstream is **Open Alpha** → treat the service as best-effort; wrap with `circuit_breaker` for resilience parity.

---

## 3. Impact Assessment

| Area | Impact | Detail |
|---|---|---|
| **New code** | Add | `weebot/tools/atomic_mail_tool.py` (BaseTool wrapper) |
| **Vendored code** | Add | `weebot/infrastructure/adapters/atomicmail/` (copy of `py/src/atomicmail/`) |
| **Tool registry** | Modify | One `_TOOL_CLASS_MAP` entry; add `atomic_mail` to `automation` + `admin` role gates ([tool_registry.py:370](weebot/tools/tool_registry.py)) |
| **MCP server** | None | Auto-exposed via existing `BaseTool` wrapper |
| **Config/env** | Add | `ATOMIC_MAIL_CREDENTIALS_DIR`, `WEEBOT_ENABLE_ATOMIC_MAIL` flag (`.env.example`, settings) |
| **Dependencies** | None | Pure stdlib — no `requirements.txt` change |
| **APIs/DB** | None | No schema or weebot-API change |
| **Security policy** | Modify | Route "act on received email content" through `approval_policy` ([weebot/core/approval_policy.py](weebot/core/approval_policy.py)) |
| **Tests** | Add | `tests/unit/tools/test_atomic_mail_tool.py` (+ optional vendored suite) |
| **Docs** | Add | Tool entry in `CLAUDE.md` + `docs/atomic_mail.md` |
| **Deployment** | Minimal | Flag-gated; default OFF until Alpha → stable |

---

## 4. Risk & Mitigation Matrix

| # | Risk | Likelihood | Impact | Severity | Mitigation |
|---|---|---|---|---|---|
| R1 | **Prompt injection via inbound email** — agent executes instructions in received mail | Med | High | **CRITICAL** | Never feed raw email body into an execution path; gate act-on-content flows through `approval_policy`; document inbound mail as untrusted in tool description |
| R2 | Upstream Alpha instability / rate limits / 100 MB quota | High | Med | HIGH | Feature flag default OFF; wrap in `circuit_breaker`; surface clear `ToolResult.error` with `_next` hints |
| R3 | Blocking HTTP stalls async event loop | Med | Med | HIGH | `asyncio.to_thread(handle_tool_call, ...)`; honor `default_timeout_seconds` |
| R4 | Credential leakage (`~/.atomicmail/credentials.json`) | Low | High | HIGH | Keep upstream `0600`; never log dir contents; isolate per-agent via `credentials_dir` arg |
| R5 | Vendored copy drifts from upstream | Med | Low | MEDIUM | Pin commit in `VENDOR.md`; isolate under one adapter dir for clean re-sync |
| R6 | License/attribution gap | Low | Low | LOW | Retain MIT `LICENSE` in vendored dir; note provenance |
| R7 | Backward compatibility | Low | Low | LOW | Purely additive; no existing tool/contract change |

---

## 5. Detailed Implementation Plan

### Phase 0 — Spike & Decision (0.5h)
- Vendoring vs. path-dependency. **Decision: vendor** (pure stdlib, isolates Alpha churn, no PyPI dependency).
- Pin upstream commit hash.
- **Acceptance:** decision recorded. **Rollback:** n/a.

### Phase 1 — Vendor the client (1h)
**Objective:** bring `atomicmail` inside weebot's dependency boundary cleanly.
- Copy `py/src/atomicmail/` → `weebot/infrastructure/adapters/atomicmail/`.
- Copy upstream `LICENSE` + add `VENDOR.md` (source URL, commit, sync date).
- Smoke-import test.
- **Acceptance:** package imports; `help()` returns content offline. **Rollback:** delete dir.

### Phase 2 — Adapter tool `AtomicMailTool` (2–3h)
**Objective:** expose the three operations as one weebot `BaseTool` (mirrors `ScheduleTool`).
- `name = "atomic_mail"`; single `action` enum: `register | jmap_request | help`.
- `parameters` JSON Schema with per-action fields (`username`, `forced`, `ops`/`ops_file`, `vars`, `dry_run`, `attachments`, `using`, `topic`, `credentials_dir`).
- `execute()`:
  1. Validate `action` + required args (defensive, fail-fast).
  2. `result = await asyncio.to_thread(handle_tool_call, action, args)` (non-blocking).
  3. Map dict → `ToolResult.success_result(output=...)` / `error_result(error=...)`.
  4. Wrap in `circuit_breaker` (R2/R3).
- `max_concurrent = 1` (shared credential file); `default_timeout_seconds = 60`.
- `health_check()` → credentials dir resolvable / `help()` callable.
- **Security (R1):** description states inbound mail is untrusted; tool only fetches — any "act on it" must pass `approval_policy`.
- **Acceptance:** unit tests green; `help` works offline; success/error dicts mapped correctly. **Rollback:** remove file + registry entry.

### Phase 3 — Registry & role wiring (0.5h)
- Add import + `"atomic_mail": AtomicMailTool` to `_TOOL_CLASS_MAP` ([tool_registry.py:370](weebot/tools/tool_registry.py)).
- Add `"atomic_mail"` to `automation` and `admin` role gates.
- **Flag-gate:** registry includes it only when `WEEBOT_ENABLE_ATOMIC_MAIL` set.
- **Acceptance:** tool present only when flag on. **Rollback:** revert additive lines.

### Phase 4 — Config, observability, docs (1–2h)
- `.env.example`: `WEEBOT_ENABLE_ATOMIC_MAIL=0`, `ATOMIC_MAIL_CREDENTIALS_DIR=~/.atomicmail`.
- Structured logging (action, status, latency) — **never** log credentials or full bodies.
- Outcome counter metric if metrics layer present.
- Update `CLAUDE.md` tool list + add `docs/atomic_mail.md` (digest+schedule, survey, verification workflows).
- **Acceptance:** docs reviewed; logs redact secrets.

### Phase 5 — Verification & sign-off (1h)
- Full unit suite + mocked-network integration green.
- Manual end-to-end against Alpha (one throwaway inbox) behind flag.
- Code review (general + security per `code-review.md`).

---

## 6. Task Breakdown Structure (WBS)

```
1. Atomic Mail Integration
   1.1 Spike & decision
       1.1.1 Confirm vendor strategy + pin commit
   1.2 Vendor client
       1.2.1 Copy package → infrastructure/adapters/atomicmail/
       1.2.2 Add LICENSE + VENDOR.md
       1.2.3 Smoke-import test
   1.3 Adapter tool
       1.3.1 Define BaseTool schema (action enum)
       1.3.2 Implement async execute() via asyncio.to_thread
       1.3.3 Map JmapRequestResult/dict → ToolResult
       1.3.4 Wrap circuit_breaker; set concurrency/timeout
       1.3.5 health_check()
   1.4 Registry & roles
       1.4.1 Add to _TOOL_CLASS_MAP (flag-gated)
       1.4.2 Add to automation + admin role gates
   1.5 Config & observability
       1.5.1 .env.example + settings
       1.5.2 Redacted structured logging + metrics
   1.6 Security
       1.6.1 Untrusted-input doc + approval_policy gating for act-on-content
   1.7 Tests
       1.7.1 Unit: action validation, success/error mapping, async non-block
       1.7.2 Integration (mocked network)
   1.8 Docs
       1.8.1 CLAUDE.md + docs/atomic_mail.md
   1.9 Review & sign-off
```

**Critical path:** 1.1 → 1.2 → 1.3 → 1.4 → 1.7 → 1.9.

---

## 7. Testing & Quality Assurance Strategy

| Layer | Scope | Approach | Target |
|---|---|---|---|
| **Unit** | `AtomicMailTool` | Mock `handle_tool_call`; assert arg validation, `ToolResult` mapping (ok/error), unknown-action handling | ≥ 80% on new file |
| **Async correctness** | `execute()` | Assert work runs via `to_thread` (loop not blocked); timeout honored | Pass |
| **Integration** | register + jmap | Mock `urllib`/`http` responses (success, 4xx/5xx, rate-limit) → verify error surfaces with hints | Pass |
| **Security** | R1 / R4 | Received-mail content cannot enter auto-exec path; credential dir never logged | Pass |
| **Vendored suite** | upstream `py/tests/` | Run under CI, marked `external` | Green |
| **Regression** | tool registry | Existing role-gate/collection tests pass; `atomic_mail` absent when flag off | Green |

Follow AAA structure and descriptive test names (per `testing.md`). Mark live-network tests `@pytest.mark.external`, skipped by default in CI.

---

## 8. Deployment & Rollback Plan

### 8.1 Deployment (progressive, flag-gated)
1. Merge with `WEEBOT_ENABLE_ATOMIC_MAIL=0` (default OFF) — code present, dormant.
2. Enable in one dev/staging env; smoke workflow (register → send → list).
3. Monitor logs/metrics for error rate, latency, rate-limit responses.
4. Promote to opt-in for `automation`/`admin` personas once Alpha proves stable.

### 8.2 Rollback
- **Fast disable:** set `WEEBOT_ENABLE_ATOMIC_MAIL=0` → tool leaves registry, no logic redeploy.
- **Full revert:** remove registry lines + delete `atomic_mail_tool.py` and vendored dir. Additive change ⇒ zero blast radius.
- **Credential cleanup:** document removal of `~/.atomicmail/` per agent.

---

## 9. Post-Implementation Validation Checklist

- [ ] `atomic_mail` appears in collection **only** when `WEEBOT_ENABLE_ATOMIC_MAIL=1`.
- [ ] `help` returns content with **no network** access.
- [ ] `register` creates inbox; credentials at mode `0600`; dir contents never logged.
- [ ] `jmap_request` send + list succeed against Alpha; errors surface `bodyText`/hints in `ToolResult.error`.
- [ ] `execute()` runs blocking HTTP off the event loop (`to_thread`); timeout enforced.
- [ ] Circuit breaker opens on repeated upstream failures; recovers per policy.
- [ ] Inbound email content cannot trigger execution without `approval_policy` confirmation.
- [ ] New unit tests ≥ 80% coverage on `atomic_mail_tool.py`; full suite green.
- [ ] No new entries in `requirements.txt` (pure stdlib confirmed).
- [ ] `CLAUDE.md` + `docs/atomic_mail.md` updated; `VENDOR.md` records upstream commit.
- [ ] Code review (general + security) signed off; no CRITICAL/HIGH issues open.
- [ ] Rollback verified: flipping flag to `0` cleanly removes the capability.

---

## Appendix A — Engineering Practices Applied
- **SOLID / SoC:** one thin adapter (`AtomicMailTool`) bridges the vendored library to weebot's `BaseTool` port; no business logic leaks into the tool.
- **Clean Architecture:** vendored client in `infrastructure/adapters/`; tool in `tools/`; dependency rule preserved (no inward violation).
- **DRY/KISS/YAGNI:** reuse upstream `handle_tool_call` instead of reimplementing JMAP/PoW; single `action`-dispatch tool, no speculative surface.
- **Secure-by-Design / Defensive:** untrusted-input gating, secret redaction, fail-fast validation, `0600` credentials preserved.
- **Observability:** redacted structured logs + outcome metrics per call.
- **CI/CD:** flag-gated rollout, mocked-network tests in CI, live tests marked `external`.
