"use client";

/**
 * ShellProvider — what a page tells the chrome around it.
 *
 * A page fills slots (title, connection state, the session whose dock to show) with
 * `useShellSlots`; the app bar and the console layout read them. Pages own no chrome, the
 * chrome mounts once, and the command palette lives here so Ctrl/Cmd+K works on every route.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";

export interface ShellSlots {
  title?: string;
  isConnected?: boolean;
  /** Session whose details dock the console layout should show; null hides the dock. */
  dockSessionId?: string | null;
}

interface ShellContextValue {
  slots: ShellSlots;
  setSlots: (slots: ShellSlots) => void;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean | ((open: boolean) => boolean)) => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const [slots, setSlotsState] = useState<ShellSlots>({});
  const [paletteOpen, setPaletteOpen] = useState(false);
  const setSlots = useCallback((next: ShellSlots) => setSlotsState(next), []);

  const value = useMemo(
    () => ({ slots, setSlots, paletteOpen, setPaletteOpen }),
    [slots, setSlots, paletteOpen]
  );
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): ShellContextValue {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within ShellProvider");
  return ctx;
}
