import { expect, test } from "@playwright/test";
import { mockBackend } from "./fixtures";

const WIDTHS = [375, 768, 1280];

for (const width of WIDTHS) {
  test.describe(`shell at ${width}px`, () => {
    test.use({ viewport: { width, height: 800 } });

    test.beforeEach(async ({ page }) => mockBackend(page));

    for (const route of ["/", "/sessions/sess-2", "/sessions", "/ops", "/models"]) {
      test(`${route}: one main, one h1, no horizontal overflow`, async ({ page }) => {
        await page.goto(route);
        await expect(page.locator("main")).toHaveCount(1);
        await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > document.documentElement.clientWidth
        );
        expect(overflow).toBe(false);
      });
    }

    test("the app bar is one 48px row", async ({ page }) => {
      await page.goto("/");
      const box = await page.locator("header").boundingBox();
      expect(box?.height).toBe(48);
    });
  });
}

test.describe("skip link", () => {
  test("is the first tab stop and moves focus to main", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main")).toBeFocused();
  });
});

test.describe("mobile navigation", () => {
  test.use({ viewport: { width: 375, height: 800 } });
  test.beforeEach(async ({ page }) => mockBackend(page));

  test("the menu is a real dialog: opens, traps focus, closes on Escape, returns focus", async ({ page }) => {
    await page.goto("/");
    const trigger = page.getByRole("button", { name: "Open menu" });
    await trigger.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Ops" })).toBeVisible();
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      // base-ui parks focus on its own guard spans at the ends and moves it back a tick later;
      // what must settle is focus never resting on a control of the page behind the dialog.
      await expect
        .poll(() =>
          page.evaluate(() => {
            const a = document.activeElement;
            return a?.matches("a, button, input, textarea, select") && !a.closest("[role=dialog]")
              ? `${a.tagName} ${a.getAttribute("aria-label") ?? a.textContent}`
              : null;
          })
        )
        .toBeNull();
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("the sessions rail is a side sheet and a link closes it", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Sessions" }).click();
    const sheet = page.getByRole("dialog", { name: "Sessions" });
    await expect(sheet).toBeVisible();
    await sheet.getByRole("link", { name: /Summarise the Q3 report/ }).click();
    await expect(page).toHaveURL(/\/sessions\/sess-2$/);
    await expect(sheet).toBeHidden();
  });

  test("the mobile bar is compact", async ({ page }) => {
    await page.goto("/");
    const bar = page.getByRole("button", { name: "Sessions" });
    const box = await bar.boundingBox();
    expect(box!.height).toBeLessThan(60);
  });

  test("the nav marks the current page", async ({ page }) => {
    await page.goto("/ops");
    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(page.getByRole("dialog").getByRole("link", { name: "Ops" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });
});

test.describe("desktop", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  test.beforeEach(async ({ page }) => mockBackend(page));

  test("the rail shows the prompt as the title, never 'Untitled'", async ({ page }) => {
    await page.goto("/");
    const rail = page.getByRole("navigation", { name: "Sessions" });
    await expect(rail.getByRole("link", { name: /tidy up my Downloads folder/ })).toBeVisible();
    await expect(page.getByText(/Untitled/)).toHaveCount(0);
  });

  test("the rail survives navigation between conversations", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Sessions" })).toBeVisible();
    await page.evaluate(() => {
      (document.querySelector("nav[aria-label=Sessions]") as HTMLElement).dataset.probe = "1";
    });
    await page.getByRole("navigation", { name: "Sessions" }).getByRole("link", { name: /Q3 report/ }).click();
    await expect(page).toHaveURL(/sess-2/);
    expect(await page.locator("nav[aria-label=Sessions]").getAttribute("data-probe")).toBe("1");
  });

  test("the command palette is a dialog with the combobox pattern", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Sessions" })).toBeVisible(); // hydrated
    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog", { name: "Command palette" });
    await expect(dialog).toBeVisible();
    const input = dialog.getByRole("combobox");
    await expect(input).toBeFocused();
    await page.keyboard.press("ArrowDown");
    const active = await input.getAttribute("aria-activedescendant");
    expect(active).toBeTruthy();
    await expect(page.locator(`#${active}`)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("Ops tabs lay out as a row of tabs above their panel", async ({ page }) => {
    await page.goto("/ops");
    const list = page.locator('[data-slot="tabs-list"]').first();
    const box = await list.boundingBox();
    expect(box!.height).toBeLessThan(60);
  });
});
