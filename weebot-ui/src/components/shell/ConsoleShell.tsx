"use client";

/**
 * ConsoleShell — the persistent 3-pane mission-center layout.
 *
 * Mobile-first (per project standard): the base layout is a single
 * column with the rail and dock as off-canvas drawers; `md:` and up
 * switch to a CSS Grid with all three panes visible side by side.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PanelLeft, PanelRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SessionRail } from "./SessionRail";
import { TopBar } from "./TopBar";
import { CommandPalette } from "@/components/command/CommandPalette";
import { useRegisterCommands } from "@/lib/commands/useRegisterCommands";
import { useTheme } from "@/providers/ThemeProvider";

interface ConsoleShellProps {
  title?: string;
  isConnected?: boolean;
  dock?: React.ReactNode;
  children: React.ReactNode;
}

export function ConsoleShell({ title, isConnected, dock, children }: ConsoleShellProps) {
  const [railOpen, setRailOpen] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const router = useRouter();
  const { toggleTheme } = useTheme();

  useRegisterCommands([
    { id: "nav.new-session", title: "New conversation", shortcut: "⌘N", run: () => router.push("/") },
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
  }, []);

  return (
    // 4rem accounts for the global Header (h-16) this shell renders beneath —
    // see src/app/layout.tsx and src/components/layout/Header.tsx.
    <div className="flex h-[calc(100vh-4rem)] flex-col overflow-hidden">
      <TopBar title={title} isConnected={isConnected} onOpenPalette={() => setPaletteOpen(true)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />

      <div className="flex flex-1 items-center gap-1 border-b bg-surface-1 px-2 py-1 md:hidden">
        <Button variant="ghost" size="sm" onClick={() => setRailOpen(true)} className="h-7 gap-1 text-xs">
          <PanelLeft className="h-3.5 w-3.5" />
          Sessions
        </Button>
        {dock && (
          <Button variant="ghost" size="sm" onClick={() => setDockOpen(true)} className="ml-auto h-7 gap-1 text-xs">
            <PanelRight className="h-3.5 w-3.5" />
            Details
          </Button>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden md:grid md:grid-cols-[var(--rail-w)_1fr_auto]">
        {/* Rail: off-canvas drawer on mobile, inline column on desktop */}
        <div className="hidden md:block md:h-full md:overflow-hidden">
          <SessionRail />
        </div>
        {railOpen && (
          <MobileDrawer onClose={() => setRailOpen(false)} side="left">
            <SessionRail />
          </MobileDrawer>
        )}

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>

        {dock && (
          <>
            <div className="hidden md:block md:h-full md:w-dock md:shrink-0 md:overflow-hidden md:border-l">
              {dock}
            </div>
            {dockOpen && (
              <MobileDrawer onClose={() => setDockOpen(false)} side="right">
                {dock}
              </MobileDrawer>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MobileDrawer({
  children,
  onClose,
  side,
}: {
  children: React.ReactNode;
  onClose: () => void;
  side: "left" | "right";
}) {
  return (
    <div className="fixed inset-0 z-50 flex md:hidden">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        className={`relative flex h-full w-[85vw] max-w-xs flex-col bg-surface-1 shadow-xl ${
          side === "left" ? "mr-auto" : "ml-auto"
        }`}
      >
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onClose}
          aria-label="Close panel"
          className="absolute right-2 top-2 z-10"
        >
          <X className="h-4 w-4" />
        </Button>
        {children}
      </div>
    </div>
  );
}
