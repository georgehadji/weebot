"use client";

import { createContext, useCallback, useContext, useEffect, useMemo } from "react";
import { useStoredValue } from "@/hooks/useStoredValue";
import { readStored, STORAGE_KEYS, writeStored } from "@/lib/storage";
import { THEME_COLOR } from "@/lib/theme";

type Theme = "dark" | "light";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const asTheme = (stored: string | null): Theme => (stored === "light" ? "light" : "dark");

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Storage is the source of truth. The server snapshot is "dark", so hydration matches the
  // server render and React then re-renders to the stored theme without a mismatch.
  const [stored, store] = useStoredValue("local", STORAGE_KEYS.theme, "dark");
  const theme = asTheme(stored);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.setAttribute("data-theme", theme);
    // color-scheme keeps native scrollbars, form controls and select popups in step with an
    // override the OS preference does not know about.
    root.style.colorScheme = theme;
    document
      .querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
      .forEach((meta) => meta.setAttribute("content", THEME_COLOR[theme]));
  }, [theme]);

  const setTheme = useCallback((next: Theme) => store(next), [store]);
  const toggleTheme = useCallback(
    () => writeStored("local", STORAGE_KEYS.theme, asTheme(readStored("local", STORAGE_KEYS.theme)) === "dark" ? "light" : "dark"),
    []
  );

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
