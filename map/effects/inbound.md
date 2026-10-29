---
type: effects
status: verified
verified: 2026-10-29
commit: 9078f3c2
---
# inbound — what outside this repo points into it

A rename or move of the target breaks the consumer, and no test in the repo catches it. Check this list before moving any of these paths. Citations re-checked 2026-10-28 at `112752a5`.

| Consumer (outside the repo) | Points at | Where it is set | Card |
|---|---|---|---|
| Claude Desktop `claude_desktop_config.json` (per user, `%APPDATA%\Claude\`) | absolute path to `run_mcp.py`; `--transport stdio` (default) or `sse` | template `claude_desktop_config.json.example:25, 44`; flags `run_mcp.py:81-87` | [MCPServer](../objects/interfaces/MCPServer.md) |
| Docker image (both Dockerfiles) | `docker-entrypoint.sh`, then `weebot.interfaces.web.main:app` on port 8000 | `Dockerfile:79-80`, `Dockerfile.api:36-37`; `Dockerfile:64` copies `run_mcp.py` into the image, so renaming it breaks the build; the entrypoint runs `alembic upgrade head` (`docker-entrypoint.sh:9`), so `alembic/` and `alembic.ini` must stay where they are | [WebAPI](../objects/interfaces/WebAPI.md) |
| `docker compose` | builds `Dockerfile.api` (API, 8000) and `weebot-ui/Dockerfile` (UI, 3000); mounts `./Output` at `/data/output` | `docker-compose.yml:52-54, 91, 109-111` | [WebAPI](../objects/interfaces/WebAPI.md), [WebUI](../objects/interfaces/WebUI.md) |
| GitHub Actions `architecture.yml` | `scripts/lint_*.py`, `scripts/quality_ceilings.py`, `scripts/check_ruleset_consistency.py`, and the test paths it runs (`tests/unit/`, `tests/integration/test_cqrs_handlers.py`, `tests/e2e/`, `tests/stress/`) | `.github/workflows/architecture.yml:60-227` | — |
| GitHub Actions `protection-drift.yml` | `.github/rulesets/main.json`, `scripts/check_branch_protection.py` | `.github/workflows/protection-drift.yml:23-25` | — |
| The UI's server-side proxy | the API at `BACKEND_URL`, else the configured endpoint | `weebot-ui/src/app/api/[[...path]]/route.ts:5` | [WebUI](../objects/interfaces/WebUI.md) |
| The operator's `.env` (not committed) | read from the start folder by every CLI command | `cli/main.py:61` | [CLI](../objects/interfaces/CLI.md) |
| MCP server list (`MCP_SERVERS_CONFIG_PATH`, default `config/mcp_servers.json`) | `uvx`, `npx` and hosted MCP servers outside the repo | `weebot/config/settings.py:292` | [MCPServer](../objects/interfaces/MCPServer.md) |

Not inbound: `weebot cron schedule` keeps its jobs in-process (APScheduler), so no OS scheduler holds a path into the repo. State Weebot writes under `~/.weebot/` (cancel markers, dead letters, the dream-scan marker) is outbound.
