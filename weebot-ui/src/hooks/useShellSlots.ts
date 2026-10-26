"use client";

import { useEffect } from "react";
import { ShellSlots, useShell } from "@/providers/ShellProvider";

/** Fill the app bar / dock slots for as long as the calling page is mounted. */
export function useShellSlots({ title, isConnected, dockSessionId }: ShellSlots): void {
  const { setSlots } = useShell();
  useEffect(() => {
    setSlots({ title, isConnected, dockSessionId });
    return () => setSlots({});
  }, [setSlots, title, isConnected, dockSessionId]);
}
