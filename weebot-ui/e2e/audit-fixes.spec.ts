import { expect, test } from "@playwright/test";
import { makeSessions, mockBackend } from "./fixtures";

// Regression cases for the 2026-11-03 Web Interface Guidelines audit fixes.

test.use({ viewport: { width: 1280, height: 800 } });

test.describe("dock tab lives in the URL", () => {
  test("a deep link opens the Cost tab and survives a reload", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/sessions/sess-2?dock=cost");
    const cost = page.getByRole("tab", { name: "Cost" });
    await expect(cost).toHaveAttribute("aria-selected", "true");
    await page.reload();
    await expect(page.getByRole("tab", { name: "Cost" })).toHaveAttribute("aria-selected", "true");
  });

  test("choosing a tab writes ?dock= and the first tab removes it again", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/sessions/sess-2");
    await page.getByRole("tab", { name: "Tools" }).click();
    await expect(page).toHaveURL(/dock=tools/);
    await page.getByRole("tab", { name: "Plan" }).click();
    await expect(page).not.toHaveURL(/dock=/);
  });
});

test.describe("composer is a form", () => {
  test("a double click on Send submits once", async ({ page }) => {
    let posts = 0;
    await mockBackend(page, { events: [], sessions: makeSessions() });
    page.on("request", (r) => {
      if (r.method() === "POST" && /\/sessions\/[^/]+\/input$/.test(r.url())) posts++;
    });
    await page.goto("/sessions/sess-1");
    const box = page.getByRole("textbox", { name: "Message weebot" });
    await box.fill("hello via the form");
    await page.getByRole("button", { name: "Send message" }).dblclick();
    await expect(box).toHaveValue("");
    expect(posts).toBe(1);
  });
});

test.describe("one h1 per route", () => {
  for (const route of ["/sessions", "/ops", "/models", "/settings", "/behavior"]) {
    test(`${route} has exactly one h1 (the app bar's)`, async ({ page }) => {
      await mockBackend(page);
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    });
  }
});
