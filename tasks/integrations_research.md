# Integration research: agentic-inbox, Arroxy, Postiz

Written 2026-10-22 from the repos' READMEs and source, read on GitHub. Nothing installed yet. This machine has Docker 29.8, winget 1.29 and wrangler 4.151 (fetched into the npm cache with `npx --yes wrangler`).

## Summary

| Repo | What | License | Weebot path | Effort | Blocker |
|---|---|---|---|---|---|
| cloudflare/agentic-inbox | Self-hosted email client + AI agent on Cloudflare Workers | Apache-2.0 | External MCP server (`/mcp`) | S config, M with gating | Cloudflare account and a domain; overlaps `atomic_mail` |
| antonio-orionus/Arroxy | Electron GUI around yt-dlp/ffmpeg | GPL-3.0 | Reference only: no API, CLI or MCP | none | Weebot already has `weebot/tools/youtube_download_tool.py` |
| gitroomhq/postiz-app | Social media scheduler with AI media tools | AGPL-3.0 | External MCP server (`/mcp`, Streamable HTTP, bearer key) | S on Postiz Cloud, M self-hosted | Docker + PostgreSQL + Redis + Temporal; a developer app per social platform |
| lexmount/moli | Headless browser engine for agents (Rust, not Chromium): page to Markdown or semantic tree, search, CDP server | Apache-2.0 OR MIT | New tool `moli_fetch` (CLI); later a CDP backend for `advanced_browser` | S (fetch tool), M (CDP backend) | None hard; 0.1.x, partial CDP |

Recommendation, in order:
1. Moli first: no account needed, permissive license, and a small `moli_fetch` tool.
2. Postiz through MCP: the most new capability, once you pick Cloud or self-host and connect channels.
3. agentic-inbox only if you want an inbox on your own domain with a web UI.

Arroxy is not an integration.

## cloudflare/agentic-inbox

- **Stack:** Workers, Durable Objects (one per mailbox, SQLite), R2 for attachments, Cloudflare Agents SDK, Workers AI. React 19, React Router v7, Hono.
- **Install:**
  1. Set the domain in `wrangler.jsonc`.
  2. Run `wrangler r2 bucket create agentic-inbox`, then `npm install`, then `npm run dev`.
  3. Deploy with `npm run deploy`.
- **Needs:** Email Routing (a catch-all to the Worker), the `send_email` binding, and Cloudflare Access (`POLICY_AUD`, `TEAM_DOMAIN`). Real mail flows only on the deployed Worker.
- **MCP tools:** `list_mailboxes`, `list_emails`, `get_email`, `get_thread`, `search_emails`, `draft_reply`, `create_draft`, `update_draft`, `delete_email`, `send_reply`, `send_email`, `mark_email_read`, `move_email`.
- **Weebot wiring:** add a `streamable-http` server to the MCP config, with Access service-token headers.
- **Security work before use:**
  - **Authorization:** the README says one Access policy is the whole trust boundary, with "no per-mailbox authorization".
  - **Outbound:** `send_email` and `send_reply` are outbound and outside EgressGuard. They need an ASK guard, the same mechanism as the F06 financial patterns: a pattern list for outbound-send MCP tools.
  - **Deletion:** `delete_email` deletes permanently and should be DENY or always-ask.
  - **Inbound content:** fetched mail is untrusted. Mark these tools as untrusted in `core/trust_boundary.py` so the inbound-mail gate pauses for review, as it does for `atomic_mail`.

## antonio-orionus/Arroxy

- **Install:** `winget install AntonioOrionus.Arroxy` or Scoop. The builds are unsigned, so SmartScreen warns on first launch, and a usage heartbeat is on by default (it can be turned off).
- **Interfaces:** none, only GUI flags. Weebot can't drive it.
- **License:** GPL-3.0, so its code must not be copied into Weebot.

## gitroomhq/postiz-app

- **Self-host:**
  1. `git clone https://github.com/gitroomhq/postiz-docker-compose`
  2. `docker compose up`
  3. The UI is at `http://localhost:4007` and the Temporal UI at `:8080`.
- **Alternative:** Postiz Cloud.
- **Platform keys:** Bluesky, Mastodon, Lemmy, Nostr, Dev.to, Hashnode, Medium, WordPress and Listmonk need none. X, LinkedIn, Meta, TikTok and YouTube each need a developer app.
- **API:** `/public/v1`, header `Authorization: <api key>`. Endpoints include `GET /integrations`, `POST /upload` and `POST /posts` (`type` `now` or `schedule`). Post creation is limited to 90 per hour self-hosted (`API_LIMIT`).
- **MCP:** `https://<host>/mcp` with `Authorization: Bearer <key>`. Tools:
  - Channels and posts: `integrationList`, `groupList`, `integrationSchema`, `triggerTool`, `schedulePostTool`, `postsListTool`, `postSettingsTool`.
  - Media: `mediaListTool`, `uploadFromUrlTool`, `mediaStatusTool`.
  - AI generation: `generateImageTool`, `generateVideoOptions`, `videoFunctionTool`, `generateVideoTool`.
  - Clipping: `clippingTool`, `clippingStatusTool`.
- **License:** AGPL-3.0. Calling a separate instance over HTTP or MCP is fine. Copying its code into Weebot, or serving a modified Postiz to others, triggers source-disclosure duties.
- **Setup, 2026-10-22** (user: "Build the outbound/publish ASK guard … then install Postiz with Docker and connect its MCP to Weebot"):
  - **Outbound guard (test first):** `outbound_policy` in `tool_guards.py`, driven by `WEEBOT_OUTBOUND_TOOL_PATTERNS`. The default is `*schedulepost*,*deletepost*,*publish*,*send_email*,*send_mail*,*send_reply*,*send_message*,*tweet*,*generate*,*clipping*`, and it matches no built-in tool.
    - **Observe mode:** its ASK goes to the approval channel even in observe mode (`enforce_always`). `WEEBOT_OUTBOUND_ASK_IN_OBSERVE=false` makes it log-only. `shell_guard_mode` stays `observe`.
    - **Pattern choices from the v2.25.1 source:** `triggerTool` and `videoFunctionTool` only read provider data, so they are left out. `deletePostTool` was added.
    - **Tests:** `tests/unit/fixes/test_outbound_tools_ask.py` (24).
  - **Two wiring bugs found and fixed, test first:**
    1. **Configured MCP servers never reached a flow.** `MCPToolRegistryBridge` adds names only, the registry skips names missing from its class map, and no caller passed `build_tools(mcp_config=…)`. `build_tools()` now adds `_configured_mcp_tools()`: it connects the DI `mcp_client` once per process, logs a failure (including an unset `${POSTIZ_API_KEY}`) and continues without those tools. Test: `tests/unit/interfaces/test_build_tools_configured_mcp.py` (4).
    2. **`MCPClientManager.initialize` crashed on `_comment` keys** (`'str' object has no attribute 'get'`), which `config/templates/mcp_servers.*.json` contain. It now skips entries that are not dicts. Test in `test_regression_mcp_silent_failure.py`.
  - **End-to-end check:** a local streamable-http MCP server with Postiz's tool names and a bearer check ran through `.env`-style settings.
    - `mcp__postiz__postsListTool` ran.
    - `mcp__postiz__schedulePostTool` was a `GuardedTool`: refused in observe mode without approval, and ran once approved.
    - With the key unset, it logged the reason and started without the tools.
    - Only cosmetic noise: async generator close warnings at interpreter exit.
  - **Weebot config:** `config/mcp_servers.json` has `postiz` (streamable-http, `http://localhost:4007/api/mcp`, bearer `${POSTIZ_API_KEY}`). Postiz's API-key route is `<backend>/mcp` with `Authorization: Bearer`, so the key is never in a URL.
  - **Compose:** upstream `gitroomhq/postiz-docker-compose` at `dd4969e` lives in `~/postiz/compose`. `docker-compose.override.yaml` pins `ghcr.io/gitroomhq/postiz-app:v2.25.1`, binds `127.0.0.1:4007` (upstream binds all interfaces), and takes `JWT_SECRET` from `~/postiz/compose/.env` (random, generated). `docker compose config` resolves with every published port on 127.0.0.1.
  - **Not done:** `docker compose up`, because Docker Desktop was not running. There is no live Postiz check. Note: `tools.exclude` in the MCP config templates is not implemented by the client.
- **Security work before use:**
  - **Publishing:** `schedulePostTool` posts publicly, so it must always ask.
  - **Cost:** the generate and clipping tools spend quota or provider keys, so they ask too.
  - **Inbound content:** fetched posts and analytics are untrusted.

## lexmount/moli

- **Install on Windows:** the README gives `powershell -ExecutionPolicy ByPass -c "irm https://github.com/lexmount/moli/releases/latest/download/moli-installer.ps1 | iex"`, which installs to `%LOCALAPPDATA%\Moli\bin\moli.exe`. That pipes a remote script into the shell. Safer: download the release binary and check its published hash. No account or key is needed.
- **CLI:** `moli fetch --dump markdown --wait-until done <url>`. Other dumps are `semantic_tree_text`, `screenshot`, `screenshot_full` and `pdf` (the last three need `--layout`). Flags include `--eval`, `--eval-file`, `--wait-selector` and `--timeout`.
- **Server:** `moli serve` on `http://127.0.0.1:9222`, speaking CDP and WebDriver Classic/BiDi, with only some CDP methods. Playwright connects with `chromium.connectOverCDP`.
- **No MCP server.** Its skills (`moli-webfetch`, `moli-websearch`, `moli-cdp-server`) are agent instructions only.
- **Weebot path:**
  1. A `moli_fetch` tool (S): page to Markdown without starting Chromium. It overlaps `advanced_browser`, `web_search` and the fetch tools.
  2. Later, `advanced_browser` over `moli serve` (M), with a Chromium fallback where CDP methods are missing.
- **Security:**
  - Fetched pages and search results are untrusted.
  - `--eval` and CDP `Runtime.evaluate` run arbitrary JavaScript: ask first.
  - Clicks and form submits act on real sites: approval plus EgressGuard.
  - Port 9222 has no auth: loopback only, a unique port, stopped after use.
  - `--profile-dir` stores cookies: throwaway profiles.
- **Not checked:** whether `moli serve` can bind a host.
- **INSTALLED 2026-10-22: v1.1.19.**
  - Downloaded `moli-x86_64-pc-windows-msvc.zip` from the v1.1.19 release; it is 43,585,149 bytes.
  - Its SHA-256 `708b93531d9d9f20c7fad31217b1c8d8c6969c546ea3668c0a568f0ce7778525` matches the digest GitHub records for the asset. The repo publishes no separate signed checksum file, and `moli.exe` is not Authenticode-signed, so the GitHub digest is the only integrity check.
  - Copied `moli.exe` (SHA-256 `B0F05D8B…6E7C`) and the license files to `%LOCALAPPDATA%\Moli\bin`. PATH is not changed.
  - The CLI's flag is `--wait`, not `--wait-until` as the README says.
- **moli_fetch tool added:** `weebot/tools/moli_fetch.py`, test `tests/unit/tools/test_moli_fetch.py` (13, plus one `external` live test).
  - **Trust:** it is in `UNTRUSTED_OUTPUT_TOOLS`, so its output is fenced and the session is egress-tainted.
  - **Fixed command line:** `fetch --dump markdown|semantic_tree_text --wait done --fail --block-private-networks --http-max-response-size 10MiB -t <ms> <url>`. There is no eval, header, cookie or profile option.
  - **Inputs:** http(s) only, timeout capped at 60 s, output truncated at `max_chars`.
  - **Checked live:** `example.com` returns Markdown. `127.0.0.1:8000` and `192.168.1.1` are refused as private network addresses.
  - **Binary:** `MOLI_PATH` (`ToolConfig.moli_path`), then PATH, then `~/AppData/Local/Moli/bin/moli.exe`.
  - **Roles:** researcher, admin and webhook, the same as `advanced_browser`.
  - **Not done:** routing through the sandbox. Like `youtube_download`, it runs its binary directly, because a fetch tool needs the network, which the sandbox turns off by default.
  - **Not done:** EgressGuard does not classify the fetch URL, as for `advanced_browser` navigation, so a URL query string can still carry data out.

## Panniantong/Agent-Reach (INSTALLED and wired, 2026-10-22)

- **What it is:** a skill (`SKILL.md` plus Chinese reference pages) and a CLI, MIT, Python 3.10+. It routes an agent to the upstream program that reads each platform: Jina Reader, `gh`, `yt-dlp`, `bili`, `mcporter` + Exa, and the V2EX/RSS APIs. It has no API of its own.
- **Installed:** commit `94f06c1969dfc1834001269d79d3ad0972d9dee6` (2026-10-07, v1.5.0), pinned rather than the README's unpinned `main.zip`. It lives in its own venv, `%USERPROFILE%\.agent-reach-venv`, via `pip install https://github.com/Panniantong/agent-reach/archive/<sha>.zip`.
  - Not run: `agent-reach install --system`, which installs gh, Node.js, mcporter and Exa machine-wide and writes agent skill directories.
  - Not run: any `configure` or cookie step.
- **`doctor`:** 4 of 16 channels work with no setup: web pages through Jina, RSS, V2EX, and Bilibili search. GitHub needs `gh` auth confirmed. YouTube needs `yt-dlp`, which is not on PATH. Exa needs `mcporter`.
- **Weebot integration:**
  - **`agent_reach` tool** (`weebot/tools/agent_reach.py`, roles researcher/admin/webhook). `action=run` takes one command, validated per program, and runs it with `shlex` as argv (no shell) and a minimal environment, so Weebot's API keys are not inherited. `action=guide` returns Agent-Reach's routing index or a reference page. The output is in `UNTRUSTED_OUTPUT_TOOLS`.
  - **What is allowed:**
    - `agent-reach doctor/check-update/version/watch`
    - `curl` with GET flags and http(s) URLs only
    - `gh search` and the read subcommands `repo/issue/pr/release view|list` (plus `pr diff`), and `gh api` GET only
    - `yt-dlp` with metadata or subtitle flags, without `--exec`, cookies or credentials
    - `bili search/subtitle/video`
    - `mcporter call exa.*`
  - **What is refused:** everything else, including installs, logins, uploads, `-X`, `-o`/`-T`/`-d` and shell operators.
  - **Builtin skill** `weebot/skills/builtin/agent-reach/SKILL.md` (`requires_toolsets: ["agent_reach"]`) routes research tasks to the tool and forbids raw shell for these programs.
  - **Setting:** `AGENT_REACH_PATH` (`ToolConfig.agent_reach_path`). Otherwise it uses PATH, then the venv.
- **Tests:** `tests/unit/tools/test_agent_reach.py` (39), written first.
- **Live check:** `doctor --json`, the `web` guide, Jina read of `example.com` and `gh search repos` work. `curl -d @.env` is refused.
- **Not done:** the cookie channels (Twitter, Reddit, Facebook/Instagram, XiaoHongShu, LinkedIn, Boss, Xueqiu). Each needs your account cookies or logins, which the project recommends doing with throwaway accounts.
- **Channels added, 2026-10-22 (user: "Install"):**
  - **Installed:** `yt-dlp` 2026.10.21 and `bilibili-cli` 0.6.2 into the Agent-Reach venv. `mcporter` 0.16.0 (MIT) with `npm install -g`, into `%APPDATA%\npm`, then `mcporter config add exa https://mcp.exa.ai/mcp --scope home`, which writes `~/.mcporter/mcporter.json`.
  - **Live through the tool:** `yt-dlp --print` on a YouTube video, `bili search`, and `mcporter call exa.web_search_exa` all work.
  - **`doctor`:** bilibili/v2ex/rss/web ok. youtube, exa_search and github are `warn`:
    - youtube: it wants `--js-runtimes node` in the global yt-dlp config, which is not written, because it would also change Weebot's `youtube_download`.
    - exa and github: `doctor` does not probe them live, but both worked live.
  - **mcporter also loads every MCP server in `~/.claude.json` and the Codex config** (designcraft, wordcraft, lightcraft and others). The tool allows only `mcporter call exa.*`, so those are not reachable through it.
  - **Fix, test first:** `mcporter` on Windows is `mcporter.cmd`. Running a `.cmd` through CreateProcess goes via cmd.exe, which re-parses arguments, so `query="x & calc"` would start calc (the "BatBadBut" class). The tool now runs the package's JS entry with `node` (`_launcher`) and refuses any other `.cmd`/`.bat`.
  - **Fix, test first:** the child `PATH` puts the venv `Scripts` first, so `doctor` sees `yt-dlp` and `bili`. Secrets are still not passed.
  - **Tests:** 42 in `test_agent_reach.py`.
- **Privacy:** Jina Reader and Exa receive every URL or query sent through them.

## jo-inc/camofox-browser (INSTALLED and wired, 2026-10-22)

User: "Install also camofox-browser: a stealth headless browser for AI agents, built to get past bot detection. Respect site terms."

- **What:** Node REST server (MIT) around Camoufox, a Firefox fork that spoofs its fingerprint in C++.
- **Install:**
  - `@askjo/camofox-browser@1.18.1` in `~/.camofox-browser`, installed with `--ignore-scripts`. Its postinstall was read first.
  - Camoufox `152.0.4-beta.30` was fetched with the package's own downloader into `%LOCALAPPDATA%\camoufox\camoufox\Cache`.
  - The downloader checks no hash. I downloaded the release zip myself: its sha256 matches GitHub's asset digest `ea52a02f…0072`, and all 503 installed files are byte-identical to the zip.
- **Weebot tool:** `weebot/tools/camofox_browser.py` (`camofox_browser`).
  - **Actions:** open, snapshot, click, type, press, scroll, navigate (URL or 8 search macros), back, links, close.
  - **Server:**
    - The tool starts its own server on 127.0.0.1, on a free port.
    - Access and admin keys are random and held in memory only.
    - `CAMOFOX_CRASH_REPORT_ENABLED=false` turns telemetry off.
    - `NODE_ENV=production` matters: without it, camofox lets any loopback caller import cookies unauthenticated.
    - No Weebot secrets are in the server's environment.
  - **Exit:** an exit hook calls `POST /stop` and then kills node. Killing node alone orphans Firefox on Windows.
  - **Refused:**
    - JavaScript evaluate, upload, cookie import, downloads, storage export.
    - Social/streaming macros (LinkedIn, Instagram, TikTok, X, Netflix, Spotify).
    - Local/private addresses. camofox itself loaded `127.0.0.1` in a live check. A tab that lands on a private IP literal is closed.
  - **Known limit:** DNS rebinding, because names are resolved twice. Closing it needs a filtering proxy.
  - **Trust:** `camofox_browser` is in `UNTRUSTED_OUTPUT_TOOLS`. Its `type` action is egress in `EgressGuard`, with an unknown recipient.
  - **Roles:** researcher, admin, webhook.
  - **Setting:** `CAMOFOX_PATH` (`ToolConfig.camofox_path`).
- **When to use it:** builtin skill `weebot/skills/builtin/camofox-browser/SKILL.md`.
  - Only after `moli_fetch`, `agent_reach` or `advanced_browser` was blocked as a bot.
  - Respect terms and robots.txt.
  - No CAPTCHAs, logins, paywalls or form submissions.
- **Tests:** 33 in `tests/unit/tools/test_camofox_browser.py`, written first.
- **Discovery fixes, test first:**
  - **The skill retriever split on whitespace only.** `BM25SkillRetriever` did not lowercase or strip punctuation, so "moli_fetch got 403 access denied" retrieved code-review. It now uses `_tokenize`, which yields lowercase words. That also lifted `youtube-download` and `desktop-automation` to first place for their tasks.
  - **`moli_fetch` now names the fallback.** On HTTP 403/429 it appends a camofox hint, because skills are matched against step text, not against errors.
- **Live check:**
  - bot.sannysoft.com reports `WebDriver missing (passed)`.
  - The `@wikipedia_search` macro works.
  - `127.0.0.1` is refused.
  - No `camoufox.exe` is left running after exit.
  - The first launch is cold: one tab create timed out at 30 s.

## remotion-dev/remotion (INSTALLED and wired, 2026-10-22)

User: "install https://github.com/remotion-dev/remotion and make sure weebot knows when and how to use it"

- **License:** Remotion License, not MIT. It is free for individuals, non-profits and for-profit companies of up to 3 employees. Larger companies need a company license (remotion.pro).
- **Install:**
  - Host folder `~/.weebot-remotion`, pinned exact: `remotion`, `@remotion/bundler`, `@remotion/renderer` 4.0.538, plus `react` and `react-dom` 19.2.0.
  - Installed with `--ignore-scripts`. The only install script is esbuild's binary check, which was run with `npm rebuild esbuild`.
  - `ensureBrowser()` downloaded Chrome Headless Shell from Google's `storage.googleapis.com/chrome-for-testing-public`. Chrome for Testing builds are unsigned, and Google publishes no hash for them.
- **Weebot tool:** `weebot/tools/remotion_video.py` (`remotion_video`).
  - **Actions:** scaffold, compositions, still, render.
  - **Codecs:** h264, h265, vp8, vp9, prores, gif.
  - **Layout:** projects live in `Output/remotion/<project>/src`. The agent edits them with `file_editor`. Output goes to `out/`.
  - **Rendering:** the fixed script `weebot/tools/remotion_render.cjs` takes its JSON request on stdin. It bundles with webpack, resolving modules from the host folder, then calls `selectComposition` and `renderMedia` or `renderStill`.
  - **Process:** node runs with an argument list, no shell, and no Weebot secrets. Timeout 900 s.
  - **Roles:** every role that has `video_gen` (automation, admin, webhook, coder, designer).
  - **Setting:** `REMOTION_HOST` (`ToolConfig.remotion_host`).
- **When and how:** builtin skill `weebot/skills/builtin/remotion-video/SKILL.md`.
  - `remotion_video` is for text, data, charts, captions and slideshows. `video_gen` is for generated footage.
  - Workflow: scaffold, edit, compositions, still, render.
  - Frame-driven animation only. No CSS animation, timers or `Math.random`.
  - Media goes in `public/` via `staticFile`.
  - Tell company users about the license once.
- **Tests:** 14 in `tests/unit/tools/test_remotion_video.py`, written first.
- **Live check:** a scaffolded project bundled in 22 s. A still at frame 45 took 3 s, and a 5 s 1080p MP4 took 15 s (139 KB).
- **Risk:** the agent's composition code runs in headless Chrome. It can load network resources and bundle local files it imports. That is no more than `file_editor` and `python_execute` already allow.

## Shared Weebot change both MCP integrations need

The F06 mechanism (`is_financial_tool` + `guard_tools`) matches tool names to an ASK guard. A second pattern setting for outbound or publishing tools would cover `*send_email*`, `*send_reply*`, `*schedulePost*`, `*generate*` and `*clipping*`. Without it, these MCP tools run with no human check in observe or enforce mode.

Two caveats: `WEEBOT_FINANCIAL_TOOL_PATTERNS` itself would not match them, and the external MCP tools reach the agent namespaced (`mcp_<server>__<tool>`), so the globs need a leading `*`.
