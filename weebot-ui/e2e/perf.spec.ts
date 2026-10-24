/**
 * Phase 7.1 baseline: what a busy session costs. Numbers are printed so they can be recorded in
 * the plan; the assertions are the budgets (tasks/specs/ui_ux_remediation_plan.md, D3).
 */
import { expect, test, WebSocketRoute } from "@playwright/test";
import { makeEvents, mockBackend } from "./fixtures";

test.use({ viewport: { width: 1280, height: 800 } });

// Baseline 2026-10-24 (production build, uncompressed JS before the load event):
//   static imports:  /  884 KB, /sessions 885, /ops 1245, /models 662, /behavior 695
//   Phase 7.2 lazy:  /  748 KB, /sessions 749, /ops  715, /models 662, /behavior 695
//   live event on a 2,041-row timeline: 2.8 ms of scripting before React.memo rows, 1.4 ms after.
// Budgets are the "after" figures plus ~7% headroom. Virtualization (7.3) is not needed.
const BUDGETS = {
  firstLoadJsKb: {
    "/": 800,
    "/sessions/sess-1": 800,
    "/ops": 770,
    "/models": 710,
    "/behavior": 750,
  } as Record<string, number>,
  scriptMsPerLiveEvent: 6,
};

for (const route of Object.keys(BUDGETS.firstLoadJsKb)) {
  test(`first-load JavaScript, ${route}`, async ({ page }) => {
    // Only what loads before the `load` event: later requests are Link prefetches of other routes.
    const bodies: Promise<number>[] = [];
    let loaded = false;
    page.on("load", () => (loaded = true));
    page.on("response", (res) => {
      if (!loaded && res.url().includes("/_next/static/") && res.url().endsWith(".js")) {
        bodies.push(res.body().then((b) => b.length, () => 0));
      }
    });
    await mockBackend(page, { events: makeEvents(5) });
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const kb = Math.round((await Promise.all(bodies)).reduce((a, b) => a + b, 0) / 1024);
    console.log(`PERF first-load JS ${route}: ${kb} KB (uncompressed)`);
    expect(kb).toBeLessThanOrEqual(BUDGETS.firstLoadJsKb[route]);
  });
}

test("scripting cost of one live event on a 2,000-event session", async ({ page }) => {
  let socket: WebSocketRoute | undefined;
  await mockBackend(page, { events: makeEvents(2000), onSocket: (ws) => (socket ??= ws) });
  await page.goto("/sessions/sess-1");
  await expect(page.getByRole("log", { name: "Conversation" })).toBeVisible();
  await expect.poll(() => socket !== undefined).toBe(true);

  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const scriptMs = async () => {
    const { metrics } = await cdp.send("Performance.getMetrics");
    return (metrics.find((m) => m.name === "ScriptDuration")?.value ?? 0) * 1000;
  };

  const count = 40;
  const before = await scriptMs();
  for (let i = 0; i < count; i++) {
    socket!.send(
      JSON.stringify({ type: "message", id: `live-${i}`, role: "assistant", message: `live ${i}`, timestamp: "t", session_id: "sess-1" })
    );
    await page.waitForTimeout(25);
  }
  await expect(page.getByText(`live ${count - 1}`)).toBeVisible();
  const perEvent = (await scriptMs() - before) / count;
  const rows = await page.locator('[role="log"] > *').count();
  console.log(`PERF script per live event with ${rows} rows: ${perEvent.toFixed(2)} ms`);
  expect(perEvent).toBeLessThanOrEqual(BUDGETS.scriptMsPerLiveEvent);
});
