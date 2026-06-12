# Attack Surface Report

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21  
**Testing Method:** Adversarial test suite (72 parametrized attack vectors)

---

## Attack Surface Overview

```
                                    ATTACK SURFACE
                                      │
                  ┌───────────────────┼───────────────────┐
                  ▼                   ▼                   ▼
          API ENDPOINTS          TOOL EXECUTION      PERSISTENCE
  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────┐
  │ FastAPI HTTP routes  │  │ BashTool (PS/WSL)   │  │ SQLite DB   │
  │ WebSocket /ws, /ws/* │  │ PythonExecuteTool   │  │ EventStore  │
  │ Webhook /api/webhook │  │ FileEditorTool      │  │ Scheduler   │
  │ MCP server (stdio/SSE)│  │ WebSearchTool       │  │ State Repo  │
  └─────────────────────┘  └─────────────────────┘  └─────────────┘
```

---

## Adversarial Test Results

### BashGuard — 31 Attack Variants

| Attack Category | Payloads Tested | Passed | Failed |
|----------------|----------------|--------|--------|
| Destructive `rm -rf` | 8 variants | 8 | 0 |
| Filesystem formatting | 3 variants | 3 | 0 |
| Download + execute pipe | 4 variants | 4 | 0 |
| Credential leakage | 4 variants | 4 | 0 |
| Fork bombs | 1 variant | 1 | 0 |
| Base64-encoded commands | 3 variants | 3 | 0 |
| Safe commands (false positives) | 8 variants | 8 | 0 |
| **Total** | **31** | **31** | **0** |

**Finding:** BashGuard correctly blocks all tested attack vectors with zero false positives on safe commands.

---

### PathValidator — 14 Attack Variants

| Attack Category | Payloads Tested | Passed | Failed |
|----------------|----------------|--------|--------|
| Directory traversal (../) | 3 variants | 3 | 0 |
| Windows path traversal (..\\) | 2 variants | 2 | 0 |
| URL-encoded traversal (%2e%2e%2f) | 1 variant | 1 | 0 |
| Double URL-encoded (%252f) | 1 variant | 1 | 0 |
| Absolute system paths (/etc/) | 2 variants | 2 | 0 |
| UNC paths (\\server\share) | 1 variant | 1 | 0 |
| Null byte injection | 2 variants | 2 | 0 |
| Valid paths (no false positives) | 3 variants | 3 | 0 |
| **Total** | **14** | **14** | **0** |

**Finding:** PathValidator correctly rejects all traversal attempts and accepts valid workspace paths.

---

### CommandValidator — 12 Attack Variants

| Attack Category | Payloads Tested | Passed | Failed |
|----------------|----------------|--------|--------|
| Dangerous PowerShell cmdlets | 5 variants | 5 | 0 |
| Dangerous bash patterns | 4 variants | 4 | 0 |
| Dangerous Python patterns | 3 variants | 3 | 0 |
| **Total** | **12** | **12** | **0** |

---

### InputSanitizer — 15 Attack Variants

| Attack Category | Payloads Tested | Passed | Failed |
|----------------|----------------|--------|--------|
| SQL injection (UNION, DROP, OR 1=1) | 5 variants | 5 | 0 |
| XSS (script, img onerror, javascript:) | 4 variants | 4 | 0 |
| Log injection | 1 variant | 1 | 0 |
| API key masking | 2 variants | 2 | 0 |
| HTML escaping | 1 variant | 1 | 0 |
| SQL sanitization | 1 variant | 1 | 0 |
| **Total** | **15** | **15** | **0** |

**Note:** The `<script>` tag detection was broken before the audit (regex `[\\s\\S]` bug in `r""` string). Fixed during this audit. All 15 tests now pass.

---

## Overall Attack Surface Assessment

| Surface | Attack Vector | Risk | Mitigation |
|---------|--------------|------|-----------|
| **CORS** | Cross-origin credential theft | ✅ Mitigated | Explicit origin allowlist |
| **WebSocket** | Unauthenticated event stream | ✅ Mitigated | Token-based auth |
| **API Key** | Timing side-channel | ✅ Mitigated | hmac.compare_digest |
| **BashTool** | Command injection, destructive ops | ✅ Mitigated | 3-layer security (Analyzer + BashGuard + Policy) |
| **BashTool** | HMAC override bypass | ✅ Mitigated | hmac.HMAC fix verified |
| **PythonTool** | Code injection | ✅ Mitigated | BashGuard + ApprovalPolicy |
| **FileEditor** | Path traversal | ✅ Mitigated | PathValidator blocks 14 variants |
| **Webhook** | Unauthorized admin access | ⚠️ Low risk | Protected by global API key |
| **MCP** | Unauthenticated tool access | ⚠️ Low risk | Documented: set WEEBOT_MCP_API_KEY |
| **HTML injection** | XSS via sanitizer bypass | ✅ Mitigated | Regex bug fixed, 4 variants tested |

---

## Attack Scenario Walkthrough

### Scenario: Remote Code Execution via WebSocket

**Attempted Attack:**
1. Attacker scans network, finds weebot server on port 8000
2. Attempts `ws://weebot-server:8000/ws` with no auth
3. If `WEEBOT_API_KEY` is set → **BLOCKED** (connection closed with code 4001)
4. If `WEEBOT_API_KEY` is NOT set → **ALLOWED** (no auth configured — documented risk)

**Verdict:** Protected when auth is configured.

### Scenario: API Key Exfiltration via Timing Attack

**Attempted Attack:**
1. Attacker makes 1000 requests to `/api/sessions` with different `X-API-Key` values
2. Measures response time to determine correct key character by character
3. Standard `!=` comparison leaks timing information

**Verdict:** ✅ **Mitigated** — now uses `hmac.compare_digest()` (constant-time comparison).

### Scenario: Path Traversal to Read .env File

**Attempted Attack:**
1. Attacker sends `file_editor` command with path `../../../.env`
2. PathValidator checks for `../` patterns → **BLOCKED**
3. URL-encoded variant `%2e%2e%2f` → **BLOCKED**
4. Double-encoded variant `%252e%252e%252f` → **BLOCKED**

**Verdict:** ✅ **Mitigated** — blocked at multiple layers.
