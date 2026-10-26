import { expect, test } from "@playwright/test";
import { BackendOptions, makeEvents, makeSessions, mockBackend } from "./fixtures";

test.use({ viewport: { width: 1280, height: 800 } });

const toolEvents = [
  { type: "message", id: "u1", role: "user", message: "list files", timestamp: "2026-10-20T09:00:00Z" },
  {
    type: "tool", id: "t1", tool_call_id: "c1", tool_name: "bash", function_name: "bash",
    function_args: { command: "ls /nope" }, status: "called", result: "ls: cannot access '/nope'", is_error: true,
    timestamp: "2026-10-20T09:00:01Z",
  },
  {
    type: "tool", id: "t2", tool_call_id: "c2", tool_name: "bash", function_name: "bash",
    function_args: { command: "echo hi" }, status: "called", result: "hi", is_error: false,
    timestamp: "2026-10-20T09:00:02Z",
  },
];

test.describe("composer", () => {
  test("a failed send keeps its row with Retry, restores the draft, and retry delivers it", async ({ page }) => {
    const options: BackendOptions = { failInput: 500, events: [], sessions: makeSessions() };
    await mockBackend(page, options);
    await page.goto("/sessions/sess-1");
    const box = page.getByRole("textbox", { name: "Message weebot" });
    await box.fill("hello there");
    await box.press("Enter");

    const log = page.getByRole("log", { name: "Conversation" });
    await expect(log.getByText("Not sent")).toBeVisible();
    await expect(page.locator("p[role=alert]")).toContainText("Not sent");
    await expect(box).toHaveValue("hello there");

    options.failInput = undefined;
    await log.getByRole("button", { name: "Retry" }).click();
    await expect(log.getByText("Not sent")).toBeHidden();
    await expect(box).toHaveValue("");
    await expect(log.getByText("hello there")).toHaveCount(1);
  });

  test("the box stays enabled and focused while a message is in flight", async ({ page }) => {
    await mockBackend(page, { events: [], inputDelayMs: 800 });
    await page.goto("/sessions/sess-1");
    const box = page.getByRole("textbox", { name: "Message weebot" });
    await box.fill("slow one");
    await box.press("Enter");
    await expect(page.getByText("Sending…").first()).toBeVisible();
    await expect(box).toBeEnabled();
    await expect(box).toBeFocused();
    await box.fill("typing the next one");
    await expect(box).toHaveValue("typing the next one");
  });

  test("Enter during IME composition does not send", async ({ page }) => {
    await mockBackend(page, { events: [] });
    await page.goto("/sessions/sess-1");
    const box = page.getByRole("textbox", { name: "Message weebot" });
    await box.fill("καλημερα");
    await box.evaluate((el) => {
      const ev = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, isComposing: true });
      el.dispatchEvent(ev);
    });
    await expect(page.getByRole("log", { name: "Conversation" }).getByText("καλημερα")).toHaveCount(0);
    await expect(box).toHaveValue("καλημερα");
  });

  test("a draft survives a reload", async ({ page }) => {
    await mockBackend(page, { events: [] });
    await page.goto("/sessions/sess-1");
    await page.getByRole("textbox", { name: "Message weebot" }).fill("unfinished thought");
    await page.reload();
    await expect(page.getByRole("textbox", { name: "Message weebot" })).toHaveValue("unfinished thought");
  });
});

test.describe("timeline", () => {
  test("scrolled up, the view is left alone and a Jump to latest pill appears", async ({ page }) => {
    await mockBackend(page, { events: makeEvents(2000) });
    await page.goto("/sessions/sess-1");
    const viewport = page.locator('[data-slot="scroll-area-viewport"]');
    await expect
      .poll(() => viewport.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight))
      .toBeLessThan(5);
    await expect(page.getByRole("button", { name: /Jump to latest/ })).toHaveCount(0);

    await viewport.evaluate((el) => (el.scrollTop = 0));
    const pill = page.getByRole("button", { name: /Jump to latest/ });
    await expect(pill).toBeVisible();
    await pill.click();
    await expect(pill).toBeHidden();
    await expect
      .poll(() => viewport.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight))
      .toBeLessThan(5);
  });

  test("the timeline is a log that is not itself a live region", async ({ page }) => {
    await mockBackend(page, { events: makeEvents(3) });
    await page.goto("/sessions/sess-1");
    const log = page.getByRole("log", { name: "Conversation" });
    await expect(log).toHaveAttribute("aria-live", "off");
    await expect(page.locator("[role=status][aria-live=polite]")).toHaveCount(1);
  });
});

test.describe("tool rows", () => {
  test("show arguments and a distinct failed state, with copy", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await mockBackend(page, { events: toolEvents });
    await page.goto("/sessions/sess-1");
    const rows = page.getByRole("button", { expanded: false }).filter({ hasText: "bash" });
    await expect(rows.first()).toContainText("command: ls /nope");
    await expect(rows.first()).toContainText("Failed");
    await expect(rows.nth(1)).toContainText("Done");

    await rows.first().click();
    await expect(page.getByLabel("Tool arguments")).toContainText('"command": "ls /nope"');
    await expect(page.getByLabel("Tool result")).toContainText("cannot access");
    await page.getByRole("button", { name: "Copy" }).click();
    await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("cannot access");
  });
});
