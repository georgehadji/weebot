"use client";

/**
 * AppShell — the page frame every route renders in: skip link, app bar, the single `<main>`
 * landmark, and the command palette. The window is `h-dvh` (not 100vh, which ignores mobile
 * browser chrome); the bar is fixed and `<main>` scrolls, so no height is hard-coded anywhere.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { CommandPalette } from "@/components/command/CommandPalette";
import { AppBar } from "@/components/shell/AppBar";
import { useRegisterCommands } from "@/hooks/useRegisterCommands";
import { useShell } from "@/providers/ShellProvider";
import { useTheme } from "@/providers/ThemeProvider";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { toggleTheme } = useTheme();
  const { paletteOpen, setPaletteOpen } = useShell();

  useRegisterCommands([
    { id: "nav.new-session", title: "New conversation", run: () => router.push("/") },
    { id: "nav.sessions", title: "Go to Sessions", run: () => router.push("/sessions") },
    { id: "nav.ops", title: "Go to Ops", run: () => router.push("/ops") },
    { id: "nav.models", title: "Go to Models", run: () => router.push("/models") },
    { id: "nav.behavior", title: "Go to Behavior", run: () => router.push("/behavior") },
    { id: "nav.settings", title: "Go to Settings", run: () => router.push("/settings") },
    { id: "theme.toggle", title: "Toggle light/dark theme", run: toggleTheme },
  ]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setPaletteOpen]);

  return (
    <div className="flex h-dvh flex-col">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-70 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <AppBar />
      <main id="main-content" tabIndex={-1} className="flex min-h-0 flex-1 flex-col overflow-y-auto outline-hidden">
        {children}
      </main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
