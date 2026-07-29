# Configuration Reference

This file is auto-generated from ``weebot.config.settings.WeebotSettings``.
Run ``python scripts/generate_config_ref.py`` to regenerate.

| Environment Variable | Type | Default | Description |
|---|---|---|---|
| `KIMI_API_KEY` | `str` | None |  |
| `DEEPSEEK_API_KEY` | `str` | None |  |
| `XAI_API_KEY` | `str` | None |  |
| `ANTHROPIC_API_KEY` | `str` | None |  |
| `OPENAI_API_KEY` | `str` | None |  |
| `OPENROUTER_API_KEY` | `str` | None |  |
| `REASONER_API_URL` | `<class 'str'>` | `"http://localhost:8003"` |  |
| `REASONER_API_KEY` | `str` | None |  |
| `REASONER_DIR` | `<class 'str'>` | `"E:\Documents\Vibe-Coding\Reasoner"` |  |
| `BERB_API_URL` | `<class 'str'>` | `"http://localhost:8004"` |  |
| `BERB_API_KEY` | `str` | None |  |
| `BERB_DIR` | `<class 'str'>` | `"E:\Documents\Vibe-Coding\Berb"` |  |
| `SCRAPER_API_URL` | `<class 'str'>` | `"http://localhost:8000"` |  |
| `SCRAPER_API_KEY` | `str` | None |  |
| `SCRAPER_DIR` | `<class 'str'>` | `"E:\Documents\Vibe-Coding\Scraper"` |  |
| `WEEBOT_API_KEY` | `str` | None |  |
| `WEB_REQUIRE_AUTH` | `<class 'bool'>` | `true` | When True and no weebot_api_key is set, refuse non-loopback requests. |
| `WEB_HOST` | `<class 'str'>` | `"127.0.0.1"` | Web API bind address (default loopback for security). |
| `WEBHOOK_API_KEY` | `str` | None | Independent API key for the /api/webhook/run endpoint. |
| `WEBHOOK_ALLOW_EXEC_TOOLS` | `<class 'bool'>` | `false` | When True, webhook endpoint may use exec tools (bash, powershell, python_execute). |
| `DISCORD_PUBLIC_KEY` | `str` | None |  |
| `DISCORD_BOT_TOKEN` | `str` | None |  |
| `DISCORD_APPLICATION_ID` | `str` | None |  |
| `TELEGRAM_BOT_TOKEN` | `str` | None |  |
| `TELEGRAM_CHAT_ID` | `str` | None |  |
| `SLACK_WEBHOOK_URL` | `str` | None |  |
| `SLACK_BOT_TOKEN` | `str` | None |  |
| `SLACK_SIGNING_SECRET` | `str` | None |  |
| `WHATSAPP_BUSINESS_API_TOKEN` | `str` | None |  |
| `WHATSAPP_BUSINESS_PHONE_NUMBER_ID` | `str` | None |  |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | `str` | None |  |
| `WHATSAPP_APP_SECRET` | `str` | None |  |
| `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS` | `<class 'bool'>` | `false` | Allow unsigned WhatsApp webhooks (dev only). |
| `STRIPE_WEBHOOK_SECRET` | `str` | None |  |
| `STRIPE_ALLOW_UNSIGNED_WEBHOOKS` | `<class 'bool'>` | `false` | Allow unsigned Stripe webhooks (dev only). |
| `SIGNAL_CLI_REST_URL` | `<class 'str'>` | `"http://localhost:8080"` |  |
| `SIGNAL_ACCOUNT_NUMBER` | `str` | None |  |
| `EMAIL_IMAP_SERVER` | `<class 'str'>` | `"imap.gmail.com"` |  |
| `EMAIL_IMAP_USER` | `str` | None |  |
| `EMAIL_IMAP_PASSWORD` | `str` | None |  |
| `EMAIL_SMTP_SERVER` | `<class 'str'>` | `"smtp.gmail.com"` |  |
| `EMAIL_SMTP_PORT` | `<class 'int'>` | `587` |  |
| `EMAIL_FROM_ADDRESS` | `str` | None |  |
| `EMAIL_POLL_INTERVAL_SECONDS` | `<class 'float'>` | `30.0` |  |
| `DAILY_AI_BUDGET` | `<class 'float'>` | `10.0` |  |
| `SKILLHUB_INDEX_URL` | `<class 'str'>` | `"https://raw.githubusercontent.com/weebot-community/skillhub/main/index.json"` |  |
| `AWESOME_AGENT_SKILLS_INDEX_URL` | `<class 'str'>` | `"https://raw.githubusercontent.com/heilcheng/awesome-agent-skills/main/README.md"` |  |
| `SANDBOX_MODE` | `<class 'str'>` | `"auto"` |  |
| `BASH_TIMEOUT` | `<class 'int'>` | `30` |  |
| `PYTHON_TIMEOUT` | `<class 'int'>` | `30` |  |
| `SANDBOX_MAX_OUTPUT_BYTES` | `<class 'int'>` | `65536` |  |
| `SANDBOX_ALLOW_NETWORK` | `<class 'bool'>` | `false` |  |
| `DRIFT_MONITORING_ENABLED` | `<class 'bool'>` | `true` |  |
| `DRIFT_BASELINE_WINDOW_DAYS` | `<class 'int'>` | `7` |  |
| `DRIFT_DETECTION_INTERVAL_MINUTES` | `<class 'int'>` | `5` |  |
| `LATENCY_P95_WARNING_MULTIPLIER` | `<class 'float'>` | `1.2` |  |
| `LATENCY_P95_CRITICAL_MULTIPLIER` | `<class 'float'>` | `1.5` |  |
| `MEMORY_WARNING_MULTIPLIER` | `<class 'float'>` | `1.3` |  |
| `MEMORY_CRITICAL_MULTIPLIER` | `<class 'float'>` | `1.5` |  |
| `ERROR_RATE_WARNING_MULTIPLIER` | `<class 'float'>` | `2.0` |  |
| `ERROR_RATE_CRITICAL_MULTIPLIER` | `<class 'float'>` | `5.0` |  |
| `KL_DIVERGENCE_WARNING` | `<class 'float'>` | `0.5` |  |
| `KL_DIVERGENCE_CRITICAL` | `<class 'float'>` | `1.0` |  |
| `ALERT_COOLDOWN_MINUTES` | `<class 'int'>` | `15` |  |
| `PERFORMANCE_ALERT_COOLDOWN_MINUTES` | `<class 'int'>` | `30` |  |
| `DATA_DRIFT_COOLDOWN_MINUTES` | `<class 'int'>` | `60` |  |
| `DRIFT_MIN_SAMPLES` | `<class 'int'>` | `1000` |  |
| `HTTP_TIMEOUT_DEFAULT` | `<class 'float'>` | `30.0` |  |
| `HTTP_TIMEOUT_CONNECT` | `<class 'float'>` | `10.0` |  |
| `HTTP_TIMEOUT_READ` | `<class 'float'>` | `60.0` |  |
| `HTTP_MAX_CONNECTIONS` | `<class 'int'>` | `20` |  |
| `HTTP_MAX_KEEPALIVE` | `<class 'int'>` | `10` |  |
| `HTTP_KEEPALIVE` | `<class 'bool'>` | `true` |  |
| `HTTP_MAX_RETRIES` | `<class 'int'>` | `3` |  |
| `HTTP_RETRY_BACKOFF` | `<class 'float'>` | `1.0` |  |
| `MCP_SERVERS_CONFIG_PATH` | `str` | None | Path to MCP servers config file (YAML/JSON). If None, no servers. |
| `MCP_TOKEN_DIR` | `<class 'str'>` | `".weebot/mcp-tokens"` | Directory for OAuth token cache (relative to workspace root or absolute). |
| `MCP_SAMPLING_ENABLED` | `<class 'bool'>` | `true` | Allow MCP servers to request sampling/createMessage. |
| `MCP_SCOPED_AGGREGATION` | `<class 'bool'>` | `true` | Enable per-request scoped retrieval of MCP-bridged external tools. |
| `MCP_SCOPE_NATIVE_TOOLS` | `<class 'bool'>` | `false` | When True, also scope native tools per query so total tools stay <= 12. |
| `MCP_COMPOSITE_TOOLS_ENABLED` | `<class 'bool'>` | `true` | Expose composite workflow tools and hide covered atomic tools on the MCP surface. |
| `PONYTAIL_MODE` | `<class 'str'>` | `"off"` | Ponytail lazy-senior-dev intensity: off \| lite \| full \| ultra |
| `GATEWAY_SESSION_TTL_SECONDS` | `<class 'int'>` | `604800` | TTL for gateway sessions before auto-close. |
| `GATEWAY_MAX_SESSIONS_PER_PLATFORM` | `<class 'int'>` | `100` | Max active sessions per platform (0 = unlimited). |
| `GATEWAY_ALLOWED_PLATFORMS` | `list[str` | `PydanticUndefined` | List of enabled gateway platforms. |
| `GATEWAY_AUTH_ENABLED` | `<class 'bool'>` | `true` | Enforce the gateway allowlist (see `python -m cli.main gateway allowlist`) for inbound Slack/Telegram/Discord messages. Chats must be allowlisted before the bot will respond to them. |
| `CONTEXT_ENGINE` | `<class 'str'>` | `"lossy"` | Context engine type: 'lossy' (compression), 'none' (pass-through). |
| `CONTEXT_COMPRESSION_THRESHOLD` | `<class 'int'>` | `12000` | Token count threshold that triggers compression. |
| `CONTEXT_COMPRESSION_TARGET_RATIO` | `<class 'float'>` | `0.5` | Target compression ratio (e.g. 0.5 = compress to 50% of threshold). |
| `CONTEXT_COMPRESSION_PROTECT_LAST_N` | `<class 'int'>` | `6` | Preserve the last N messages when compressing. |
| `PROMPT_CACHING_ENABLED` | `<class 'bool'>` | `false` | Enable Anthropic/OpenRouter prompt caching breakpoints. |
| `PROMPT_CACHING_TTL_SECONDS` | `<class 'int'>` | `300` | TTL for cached prompt breakpoints. |
| `CRON_AGENT_JOBS_ENABLED` | `<class 'bool'>` | `false` | Enable cron agent task execution. |
| `CRON_AGENT_MAX_RUNTIME_SECONDS` | `<class 'int'>` | `300` | Max runtime for a single cron agent job. |
| `CRON_AGENT_DEFAULT_MODEL` | `str` | None | Default model override for cron agent sessions. |
| `PLAN_REVIEW_ENABLED` | `<class 'bool'>` | `true` | Enable plan-review pause before execution. |
| `COVE_ENABLED` | `<class 'bool'>` | `true` | Enable Chain-of-Verification step. |
| `COVE_MAX_QUESTIONS` | `<class 'int'>` | `3` | Max verification questions in CoVE step. |
| `SKILLS_HUB_CATALOG_URL` | `str` | None | URL for remote skills hub catalog. |
| `SKILL_BLUEPRINTS_ENABLED` | `<class 'bool'>` | `false` | Enable skill blueprint auto-suggestion. |
| `LLM_MAX_CONCURRENT_REQUESTS` | `<class 'int'>` | `12` | Max concurrent LLM API requests across all sessions. |
| `FINANCIAL_TOOLS_ALWAYS_ASK` | `<class 'bool'>` | `true` | Financial/payment tools always require user approval. |
| `SECRET_REDACTION_ENABLED` | `<class 'bool'>` | `true` | Redact secrets (PANs, API keys) in tool output and logs. |
| `SECRET_REDACTION_ENTROPY_THRESHOLD` | `<class 'float'>` | `3.5` | Shannon entropy threshold for secret detection. |

