# Implementation Audit Report — Security Fixes Phase 0–3

**Date:** 2026-07-24  
**Commit:** `65a374f` (main)  
**Auditor:** Reasonix  
**Scope:** 20 files, +561/-74 lines, implementing findings C1, H2, H3, H4, H6, M7, M8, M10, M12, M13, L14, L15, L16, L17

---

## Executive Summary

The implementation correctly addresses 14 of the 17 audit findings. The code is syntactically correct, settings load as expected, and all core domain-level validators (sandbox env, session ID, FTS5, approval policy) pass runtime verification. **One P0 defect** and **one P1 omission** were discovered; both must be resolved before production deployment. Three items were explicitly deferred per the plan (H5, M9, M11). No new tests were written — the plan mandates unit tests per item; this gap is flagged below.

**Verdict:** APPROVED WITH CHANGES

---

## Plan Compliance Matrix

### Phase 0 — Fail closed at the network edge

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| **C1** — `web_require_auth` + `web_host` settings | ✅ COMPLETE | `settings.py:92-99` — new fields with defaults `True`/`127.0.0.1` | |
| **C1** — `FailClosedMiddleware` | ✅ COMPLETE | `main.py:391-428` — returns 503 for non-loopback, allows `/api/health`, `/api/live`, `/`, `/api/prometheus` | Loopback check handles `request.client is None` safely |
| **C1** — `__main__` uses `WeebotSettings().web_host` | ✅ COMPLETE | `main.py:591-594` — reads `_settings.web_host` instead of bare `os.getenv` | |
| **H2** — `require_webhook_auth` dependency | ✅ COMPLETE | `webhook.py:30-68` — 3-tier auth: `X-Webhook-Key` → global key → loopback-only | |
| **H2** — Tool role from `admin` → `operator` | ❌ P0 DEFECT | `webhook.py:129` — `build_tools(role="operator")` | **Role `"operator"` does not exist** in `RoleBasedToolRegistry` (available: researcher, analyst, automation, documentation, product_manager, admin, coder, dreamer, design, media, designer, reviewer, planner_sub, custom). This will raise `ValueError` at runtime. The plan requires creating a `"webhook"` role that excludes `bash`, `powershell`, `python_execute`. |
| **M12** — `hmac.compare_digest` in MCP verifier | ✅ COMPLETE | `server.py:55-59` | |
| **M12** — `--allow-remote` requires API key | ✅ COMPLETE | `run_mcp.py:94-104` | |
| **M13** — `require_mutation_identity` helper | ✅ COMPLETE | `auth.py:83-99` — rejects anonymous non-loopback POST/DELETE with 403 | |
| **M13** — Applied to mutating endpoints | ✅ COMPLETE | `sessions.py` (create, delete, cancel, resume, run), `chat_router.py` (send_message) | |

### Phase 1 — Tool-layer confinement

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| **H3** — `.env` removed from `ALLOWED_EXTENSIONS` | ✅ COMPLETE | `security_validators.py:54-83` — `.env` absent from both extension sets | Verified with runtime test |
| **H3** — `DENIED_BASENAMES` block | ✅ COMPLETE | `security_validators.py:54-60` — 10 entries: `.env`, `.env.local`, `.env.production`, `.env.development`, `.env.staging`, `.env.test`, `id_rsa`, `id_ed25519`, `id_dsa`, `id_ecdsa` | Checked before extension rules — correct |
| **H4** — `ALLOWED_CREATE_EXTENSIONS` separate | ✅ COMPLETE | `security_validators.py:70-84` — 39 extensions, no exec types | |
| **H4** — `EXECUTABLE_EXTENSIONS` blocked for create | ✅ COMPLETE | `security_validators.py:63-68` — 12 entries including `.ps1`, `.bat`, `.cmd`, `.sh`, `.exe`, `.dll`, `.com`, `.msi`, `.scr`, `.vbs`, `.js`, `.wsf` | `.js` included — correct: Windows Script Host makes `.js` executable |
| **H4** — `validate()` applies create check | ✅ COMPLETE | `security_validators.py:169-186` | Differential check for create vs read/edit |
| **M7** — `_DESTRUCTIVE_KEYWORDS` set | ✅ COMPLETE | `approval_policy.py:45-49` — 13 keywords | |
| **M7** — Output-folder regex anchored | ✅ COMPLETE | `approval_policy.py:58` — `^remove-item\s+...$` with `[^;&|]*` negations | |
| **M7** — Chained destructive command detection | ✅ COMPLETE | `approval_policy.py:183-198` — `re.search(r'[;&|]', command)` + keyword scan | |
| **M7** — New ALWAYS_ASK rules | ✅ COMPLETE | `approval_policy.py:72-113` — `reg`, `net`, `icacls`, `takeown`, `bcdedit`, `diskpart`, `schtasks`, `Set-Content`, `out-file`, `rd`, `erase`, `rmdir` | All verified with runtime tests |
| **H6** — `_build_child_env` deny-by-default | ✅ COMPLETE | `native_windows.py:38-76` — allowlist of 14 env vars | Runtime verified: API keys excluded, PATH included, proxy set when network disabled |
| **H6** — Proxy gating for network disabled | ✅ COMPLETE | `native_windows.py:64-71` — sets `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY` + lowercase variants to `127.0.0.1:9` | |
| **H6** — Security docstring | ✅ COMPLETE | `native_windows.py:48-52` — states it's a resource-limit wrapper, not security boundary | |
| **H6** — `get_capabilities()` docstring | ✅ COMPLETE | `native_windows.py:90-94` — NETWORK_ACCESS reflects config, not enforcement | |
| **L15** — Python timeout clamp | ✅ COMPLETE | `python_tool.py:141-150` — floor 1.0, cap `max_tool_timeout` or 300.0 | TypeError/ValueError caught |

### Phase 2 — Gateway authenticity

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| **M8** — WhatsApp fail-closed | ✅ COMPLETE | `whatsapp.py:70-93` — returns `False` when no `WHATSAPP_APP_SECRET` (was `True`) | Escape hatch: `whatsapp_allow_unsigned_webhooks` in settings |
| **H5** — Discord allowlist | ⚠️ DEFERRED | Per plan: "verify `parse_interaction` payload fields" | Not in this commit |
| **M9** — Stripe webhook | ⚠️ DEFERRED | Per plan: "deeper refactoring needed" | Not in this commit |

### Phase 3 — Injection and hygiene

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| **M10** — Session ID `field_validator` | ✅ COMPLETE | `session.py:156-168` — pattern `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` | Legacy sessions load via `model_validate` — verified OK |
| **M10** — `CreateSessionRequest` pattern | ✅ COMPLETE | `requests.py:11,18-22` — `Field(pattern=_SESSION_ID_PATTERN)` | Returns 422 on bad input |
| **M10** — Dead-letter filename sanitization | ✅ COMPLETE | `session_persistence_adapter.py:99-101` — `re.sub(r"[^A-Za-z0-9._-]", "_", session.id)` | |
| **L14** — `_websocket_auth` helper | ✅ COMPLETE | `main.py:538-580` — subprotocol → Authorization → query param (deprecated) | |
| **L14** — WS test HTML updated | ✅ COMPLETE | `main.py:88-92` — passes `apiKey` via `[bearer.${apiKey}]` subprotocol | |
| **L14** — behavior_router WebSocket | ❌ P1 OMISSION | `behavior_router.py:235-246` — **still uses old query-param-only auth**, not `_websocket_auth` | The plan references `routers/behavior_router.py:235+` explicitly. This endpoint was missed. |
| **L16** — Redact-by-default `_log_access` | ✅ COMPLETE | `secret_accessor.py:160-170` — redacts unless `_is_non_secret()` | Logic verified |
| **L16** — `_is_non_secret` function | ✅ COMPLETE | `secret_accessor.py:42-50` — suffix + key-set allowlist | |
| **L17** — `_sanitize_fts_query` | ✅ COMPLETE | `fts5_search.py:20-38` — wraps tokens in double quotes, escapes embedded quotes | Runtime verified |
| **M11** — Migration `exec` → AST evaluator | ⚠️ DEFERRED | Per plan: "new module needed; significant effort" | Not in this commit |

### Cross-cutting

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| `.env.example` updated | ✅ COMPLETE | `19 new lines` — `WEEBOT_HOST`, `WEEBOT_WEB_REQUIRE_AUTH`, `WEEBOT_WEBHOOK_API_KEY`, `WEEBOT_WEBHOOK_ALLOW_EXEC_TOOLS`, `WEEBOT_MCP_API_KEY` | |
| **Tests** | ❌ MISSING | No test files created | The plan mandates unit tests for every item (11 new test files: `test_web_auth_default.py`, `test_webhook_router_security.py`, `test_mcp_auth.py`, `test_path_validator.py`, `test_python_tool_timeout.py`, `test_approval_policy_hardening.py`, `test_sandbox_env.py`, `test_whatsapp_signature.py`, `test_session_id_validation.py`, `test_secret_accessor.py`, `test_fts5_sanitize.py`) |
| Architecture compliance | ✅ PASS | No domain→outer imports introduced | Verified via syntax check |

---

## Architecture Compliance Assessment

| Check | Result | Detail |
|-------|--------|--------|
| Domain purity | ✅ PASS | `session.py` only imports `re`, `pydantic`, domain models |
| Infrastructure adheres to ports | ✅ PASS | `native_windows.py` imports `SandboxPort`, `fts5_search.py` operates at persistence boundary |
| Interfaces no direct infra imports | ✅ PASS | Routers only call `build_tools`/`create_flow` from factories |
| Settings centralized | ✅ PASS | All new fields in `WeebotSettings`; `.env.example` updated |
| No bare `os.environ` in new code | ✅ PASS | All config reads go through `WeebotSettings` or `SecretAccessor` |

---

## Code Quality Findings

| Severity | File | Issue |
|----------|------|-------|
| 🟢 LOW | `secret_accessor.py:1` | Comment typo: "helpders" → "helpers" |
| 🟢 LOW | `main.py:538-580` | `_websocket_auth` is defined at module level but uses `import hmac as _hmac` 4 separate times inside the function (3 conditionals + query param fallback). The import could be hoisted once. No functional impact. |
| 🟢 LOW | `approval_policy.py:45-49` | `_DESTRUCTIVE_KEYWORDS` set includes `"format"` which is a standard Python method name. This is a deliberate inclusion and is scoped only to shell command evaluation (not Python code), but could cause confusion during maintenance. Documented in the existing module docstring. |
| 🟡 MEDIUM | `webhook.py:129` | `build_tools(role="operator")` — role does not exist (see P0 defect). |
| 🟡 MEDIUM | `behavior_router.py:235-246` | WebSocket auth not updated to use `_websocket_auth` (see P1 omission). |
| 🟡 MEDIUM | `python_tool.py:148` | `self._tool_config and self._tool_config.max_tool_timeout` — `max_tool_timeout` attribute not verified to exist on `ToolConfig`. HYPOTHESIS: if absent, `_max_timeout` stays at 300.0, which is the safe default, so this degrades gracefully. |
| 🟡 MEDIUM | Global | No unit tests written. The plan specifies 11 new test files. |

---

## Testing & Coverage Assessment

| Category | Plan Requirement | Actual | Gap |
|----------|-----------------|--------|-----|
| `tests/unit/test_web_auth_default.py` | Required | **Missing** | C1 + M13 endpoint auth tests |
| `tests/unit/test_webhook_router_security.py` | Required | **Missing** | H2 webhook auth + role assertion |
| `tests/unit/test_mcp_auth.py` | Required | **Missing** | M12 constant-time compare + CLI guard |
| `tests/unit/test_path_validator.py` (extend) | Required | **Missing** | H3 denied basenames + H4 create block |
| `tests/unit/test_python_tool_timeout.py` | Required | **Missing** | L15 timeout clamping |
| `tests/unit/test_approval_policy_hardening.py` | Required | **Missing** | M7 new rules + chained detection |
| `tests/unit/test_sandbox_env.py` | Required | **Missing** | H6 env scrubbing |
| `tests/unit/test_session_id_validation.py` | Required | **Missing** | M10 session ID + dead-letter path |
| `tests/unit/test_secret_accessor.py` | Required | **Missing** | L16 redact-by-default |
| `tests/unit/test_fts5_sanitize.py` | Required | **Missing** | L17 FTS query sanitization |
| `tests/unit/test_whatsapp_signature.py` | Required | **Missing** | M8 WhatsApp fail-closed |
| Manual verification | Not required but helpful | **Done** | Sandbox env, session ID, approval policy, FTS5, settings defaults |

**Coverage assessment:** 0 of 11 required test files written. Manual smoke tests confirm core logic works, but regression protection is absent.

---

## Risk & Regression Analysis

| Risk | Severity | Description |
|------|----------|-------------|
| Webhook runtime crash | **P0** | `build_tools(role="operator")` will raise `ValueError` at runtime — the role doesn't exist. All webhook invocations will fail with 500. |
| behavior_router WebSocket auth gap | **P1** | The behavior WebSocket at `/api/ws` still uses query-param-only auth and was not updated to `_websocket_auth`. |
| Backward compat: `web_host` default | **P2** | Default bind changed from `0.0.0.0` to `127.0.0.1`. Existing deployments that rely on the old default must set `WEEBOT_HOST=0.0.0.0`. This is intentional per the plan but is a breaking change. |
| Backward compat: `FailClosedMiddleware` | **P2** | Headless/CI deployments without `WEEBOT_API_KEY` will get 503 unless `WEEBOT_WEB_REQUIRE_AUTH=false`. Intentional per plan but breaks CI that hits the API from remote hosts. |
| Backward compat: Sandbox env scrub | **P2** | Agent tasks that rely on inherited API keys in subprocesses will break. The plan notes this as the highest-regression-risk change (Phase 1 order 4). Migration: declare needed vars via `SandboxConfig.env_vars`. |
| Backward compat: WhatsApp fail-closed | **P2** | Existing WhatsApp webhook deployments without `WHATSAPP_APP_SECRET` will stop receiving messages. Operators must either set the secret or `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS=true`. |
| Forward compat: SecretAccessor redaction | **P3** | Config keys not in the `_NON_SECRET_KEYS` allowlist will now be redacted in debug logs. This may slow troubleshooting until operators add their custom debug keys. Non-functional impact. |

---

## Required Corrections

| Severity | File | Issue | Recommendation |
|----------|------|-------|----------------|
| **P0** | `webhook.py:129` | `build_tools(role="operator")` calls a non-existent role | Register a `"webhook"` role in `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS` that includes all tools except `bash`, `powershell`, `python_execute`, then use `role="webhook"` in the webhook endpoint. Example: copy the `"admin"` role minus the three exec tools. |
| **P1** | `behavior_router.py:235-246` | WebSocket auth not updated | Replace the inline `if _ws_settings.weebot_api_key: token = websocket.query_params.get("token")` block with `from weebot.interfaces.web.main import _websocket_auth` (or extract `_websocket_auth` to a shared module) and call `_websocket_auth(websocket, _ws_settings)`. |
| **P2** | All | No tests written | Write the 11 required test files per plan specifications. At minimum: `test_web_auth_default.py`, `test_webhook_router_security.py`, `test_mcp_auth.py`, `test_session_id_validation.py`. |
| **P3** | `secret_accessor.py:1` | Typo in comment | Change "helpders" → "helpers" |

---

## Final Verdict

### APPROVED WITH CHANGES

**Required before merge to production:**

1. **Fix P0 defect:** Register a `"webhook"` role in `RoleBasedToolRegistry` that excludes exec tools, and change `webhook.py` to use `role="webhook"`.
2. **Fix P1 omission:** Update `behavior_router.py` WebSocket auth to use `_websocket_auth` (subprotocol/header support).

**Required before next release:**

3. Write the mandatory unit tests (11 files per plan).
4. Update `AGENTS.md` Security Considerations to document the behavior changes (breaking changes for web_host, WhatsApp, sandbox env).

**Items explicitly out of scope (not defects):**

- H5 (Discord allowlist enforcement)
- M9 (Stripe webhook fail-closed)
- M11 (Migration exec → AST interpreter)
- Docker sandbox migration
- Rate limiting on API-key middleware
- `weebot-ui/` WS token transport changes
