/**
 * The browser-chrome colour per theme. These are the `--background` tokens in globals.css
 * (`--p-ink-50` / `--p-ink-950`) written as hex, because `<meta name="theme-color">` cannot read
 * CSS variables. Shared by the root layout (viewport export) and ThemeProvider (user override).
 */
export const THEME_COLOR = { light: "#FAF9F5", dark: "#141413" } as const;
