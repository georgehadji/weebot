import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockBackend } from "./fixtures";

const ROUTES = ["/", "/sessions", "/sessions/sess-2", "/ops", "/models", "/settings", "/behavior"];
const THEMES = ["dark", "light"] as const;
const WIDTHS = [375, 1280];

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test.describe(`axe, ${theme} theme, ${width}px`, () => {
      test.use({ viewport: { width, height: 800 } });

      for (const route of ROUTES) {
        test(route, async ({ page }) => {
          await page.addInitScript((t) => localStorage.setItem("weebot_theme", t), theme);
          await mockBackend(page);
          await page.goto(route);
          await page.waitForLoadState("networkidle");
          const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
          const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
          expect(
            blocking.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)
          ).toEqual([]);

          // Best-practice rules (not WCAG tags): heading levels do not skip, and content sits in landmarks.
          const structure = await new AxeBuilder({ page }).withRules(["heading-order", "region"]).analyze();
          expect(
            structure.violations.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)
          ).toEqual([]);

          // Native scrollbars and select popups follow the theme, not only the page colours.
          expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(theme);
        });
      }
    });
  }
}
