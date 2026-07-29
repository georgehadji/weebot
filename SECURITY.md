# Security Policy

## Supported Versions

The `main` branch receives active development. Releases will be tagged
when the project reaches a stable milestone; until then, use the latest
`main` commit.

## Reporting a Vulnerability

**Do not file a public GitHub issue.** Instead, send an email to the
maintainers at the address listed in the commit history of any recent
change to a security-critical module (`weebot/core/`, `weebot/interfaces/web/auth*`,
`weebot/infrastructure/security/`).

You should receive a response within 48 hours. If you do not, escalate
by filing an issue with the `security` label describing only that you
have not received a response — do not include the vulnerability details.

## What to expect

- Acknowledgment of receipt within 48 hours.
- A fix within 14 days for critical-severity issues.
- A CVE number assigned where applicable.
- The reporter offered the option to be credited or to remain anonymous.

## Security-relevant configuration

| Variable | Purpose |
|---|---|
| `WEEBOT_API_KEY` | Global API key (legacy — use per-principal keys via CLI) |
| `WEEBOT_MCP_API_KEY` | Required for remote SSE MCP transport |
| `WEEBOT_WEBHOOK_API_KEY` | Key for the `/api/webhook/run` endpoint |
| `VALKEY_PASSWORD` | Valkey event bus authentication |
| `WEEBOT_WEB_REQUIRE_AUTH` | Fail-closed for remote requests (default: `true`) |
| `WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS` | Experimental — do not enable in production |

## Security layers

1. **Bash guard** (`weebot/core/bash_guard.py`) — 4-tier risk classification on shell execution
2. **Egress guard** (`weebot/core/egress_guard.py`) — monitors outbound requests
3. **Sandbox** — Python and shell execution run in a sandbox with timeout and output limits
4. **Fail-closed defaults** — remote HTTP requests refused when no API key is configured
5. **Rate limiting** — tiered token buckets keyed by principal / IP
6. **Container hardening** — non-root user, `cap_drop: ALL`, read-only filesystem
