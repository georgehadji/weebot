<rules for="browser">
When using the browser:
1. Launch first with action='launch' before navigating — the browser context is fresh each time
2. Use web_search before the browser — most information is available without rendering JS
3. Cloudflare-protected sites will block headless browsers — use web_search as fallback
4. Screenshots help verify the page state — take one after navigation
5. Timeout default is 30s — increase to 60s for slow sites
6. State does not persist between browser tool calls — each call is a fresh context
</rules>
