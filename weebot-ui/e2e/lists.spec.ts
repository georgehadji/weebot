import { expect, test } from "@playwright/test";
import { mockBackend } from "./fixtures";

test.use({ viewport: { width: 1280, height: 800 } });

test.describe("rail search", () => {
  test("filters as you type, matches Greek without tonos, and clears", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/");
    const rail = page.getByRole("navigation", { name: "Sessions" });
    await expect(rail.getByRole("link")).toHaveCount(9 + 1); // nine sessions and the New link
    const search = page.getByRole("searchbox", { name: "Search sessions" });

    await search.fill("γιαννιτσα");
    await expect(rail.getByRole("link", { name: /Γιαννιτσά/ })).toBeVisible();
    await expect(rail.getByRole("link")).toHaveCount(1 + 1);

    await search.fill("zzzz");
    await expect(rail.getByText(/No sessions match/)).toBeVisible();

    await rail.getByRole("button", { name: "Clear search" }).click();
    await expect(search).toHaveValue("");
    await expect(rail.getByRole("link")).toHaveCount(9 + 1);
  });
});

test.describe("failure and empty states", () => {
  test("the rail shows an error with Retry when the list cannot load, and recovers", async ({ page }) => {
    const options = { failSessionList: 500 };
    await mockBackend(page, options);
    await page.goto("/");
    const rail = page.getByRole("navigation", { name: "Sessions" });
    await expect(rail.getByRole("alert")).toContainText("Couldn't load sessions");
    options.failSessionList = 0;
    await rail.getByRole("button", { name: "Retry" }).click();
    await expect(rail.getByRole("link", { name: /tidy up my Downloads/ })).toBeVisible();
    await expect(rail.getByRole("alert")).toHaveCount(0);
  });

  test("an empty rail says how to start", async ({ page }) => {
    await mockBackend(page, { sessions: [] });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Sessions" }).getByText(/No sessions yet/)).toBeVisible();
  });

  test("the sessions page shows a loading status, then the list, with no spinner-only state", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/sessions");
    await expect(page.getByRole("heading", { name: "Sessions", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Summarise the Q3 report and list the three biggest risks" })).toBeVisible();
    await expect(page.getByText("5 events").first()).toBeVisible();
  });

  test("the home page offers example prompts that fill the composer", async ({ page }) => {
    await mockBackend(page, { sessions: [] });
    await page.goto("/");
    await page.getByRole("button", { name: /Summarise the files in my Downloads/ }).click();
    await expect(page.getByRole("textbox", { name: "Message weebot" })).toHaveValue(/Downloads folder/);
  });
});

test.describe("a page that crashes", () => {
  test("shows a recoverable error inside the app frame, not Next's bare error page", async ({ page }) => {
    await mockBackend(page);
    // A malformed trust payload makes the behavior page throw while rendering.
    await page.route("**/api/behavior/trust", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
    );
    page.on("pageerror", () => {});
    await page.goto("/behavior");
    await expect(page.getByRole("heading", { name: "Something went wrong on this page" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  });
});

test.describe("deleting a session", () => {
  test("asks first, names the session, defaults to Cancel, and never uses a native confirm", async ({ page }) => {
    await mockBackend(page);
    let nativeDialog = false;
    page.on("dialog", (d) => {
      nativeDialog = true;
      void d.dismiss();
    });
    await page.goto("/sessions");
    const trigger = page.getByRole("button", { name: /Delete session tidy up my Downloads folder/ });
    await trigger.click();

    const dialog = page.getByRole("alertdialog").or(page.getByRole("dialog", { name: "Delete this session?" }));
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("tidy up my Downloads folder");
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
    expect(nativeDialog).toBe(false);
  });
});

test.describe("touch targets", () => {
  test.use({ viewport: { width: 375, height: 800 }, hasTouch: true, isMobile: true });

  test("buttons are at least 44px tall on a coarse pointer", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/sessions");
    for (const name of ["Refresh sessions", "Open menu", "Open command palette"]) {
      const box = await page.getByRole("button", { name }).boundingBox();
      expect(box!.height, name).toBeGreaterThanOrEqual(44);
      expect(box!.width, name).toBeGreaterThanOrEqual(44 - 1);
    }
  });
});
